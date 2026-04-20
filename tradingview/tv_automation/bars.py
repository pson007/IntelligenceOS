"""Fetch historical OHLCV bars for bench grading.

Used by `replay_bench.py` to grade sample outcomes against real bars
without scraping TV's chart legend (which proved too fragile — see
REPLAY_BENCH_PLAN.md UNKNOWN #1, option c).

Source: Yahoo Finance via `yfinance`. MNQ1! (TV's front-month micro
Nasdaq futures) is mapped to `MNQ=F` (Yahoo's continuous contract).
These diverge only at roll boundaries; good enough for bar-walk grading.

Limit: Yahoo caps 5m data to the last 60 days. For windows beyond that,
swap the implementation for Polygon or a local CSV. The `fetch_bars`
signature is source-agnostic so the caller doesn't need to know.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache


# TradingView symbol → Yahoo ticker. Only the symbols we actually bench
# need entries; anything else falls through to identity (which may
# still work for stocks/ETFs, fails for futures).
_SYMBOL_MAP: dict[str, str] = {
    "MNQ1!": "MNQ=F",   # Micro E-mini Nasdaq-100 continuous front-month
    "MES1!": "MES=F",   # Micro E-mini S&P 500
    "MGC1!": "MGC=F",   # Micro Gold
    "MCL1!": "MCL=F",   # Micro Crude Oil
    "M2K1!": "M2K=F",   # Micro Russell 2000
    # TV uses `!` suffix for continuous; Yahoo uses `=F`.
}

# Friendly TF → yfinance interval. yfinance accepts "1m","2m","5m",
# "15m","30m","60m","90m","1h","1d","5d","1wk","1mo","3mo".
_TF_MAP: dict[str, str] = {
    "1m": "1m", "2m": "2m", "5m": "5m",
    "15m": "15m", "30m": "30m",
    "1h": "60m", "60m": "60m",
    "1D": "1d", "1d": "1d",
    "1W": "1wk", "1w": "1wk",
}


@dataclass(frozen=True)
class Bar:
    """OHLCV bar. `ts` is the bar's OPEN time in UTC."""
    ts: datetime      # bar-open time, UTC
    open: float
    high: float
    low: float
    close: float
    volume: float


class UnsupportedSymbolError(ValueError):
    pass


class UnsupportedTimeframeError(ValueError):
    pass


def resolve_yahoo_ticker(tv_symbol: str) -> str:
    """TV symbol to Yahoo ticker. Raises for known-unsupported cases."""
    if tv_symbol in _SYMBOL_MAP:
        return _SYMBOL_MAP[tv_symbol]
    # Pass-through for anything without a futures `!` — stocks and ETFs
    # on Yahoo use their ticker directly.
    if "!" not in tv_symbol:
        return tv_symbol
    raise UnsupportedSymbolError(
        f"No Yahoo ticker mapping for {tv_symbol!r}. "
        f"Add it to _SYMBOL_MAP in bars.py."
    )


def resolve_yahoo_interval(tf: str) -> str:
    if tf not in _TF_MAP:
        raise UnsupportedTimeframeError(
            f"TF {tf!r} not supported by yfinance. "
            f"Supported: {sorted(_TF_MAP)}"
        )
    return _TF_MAP[tf]


# Cache the raw fetch keyed by (ticker, interval, date-span) so a 130-
# sample run doesn't round-trip Yahoo per sample. LRU with a small cap
# since the bench only fetches a handful of distinct ranges per run.
@lru_cache(maxsize=32)
def _fetch_raw(ticker: str, interval: str,
               start_iso: str, end_iso: str) -> list[Bar]:
    """Actual yfinance fetch. Separated so the LRU cache key is pure
    (immutable strings) — datetime objects hash awkwardly under TZ."""
    import yfinance as yf  # local import: heavy deps (pandas) only if used
    t = yf.Ticker(ticker)
    df = t.history(start=start_iso, end=end_iso, interval=interval,
                   auto_adjust=False, actions=False)
    if df is None or df.empty:
        return []
    bars: list[Bar] = []
    for idx, row in df.iterrows():
        # idx is a pandas Timestamp (TZ-aware, Yahoo returns ET for
        # US futures). Normalize to UTC datetime for portability.
        ts = idx.to_pydatetime()
        if ts.tzinfo is not None:
            from datetime import timezone
            ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
        bars.append(Bar(
            ts=ts,
            open=float(row["Open"]),
            high=float(row["High"]),
            low=float(row["Low"]),
            close=float(row["Close"]),
            volume=float(row["Volume"]) if row["Volume"] == row["Volume"] else 0.0,
        ))
    return bars


def fetch_bars(tv_symbol: str, tf: str,
               start: datetime, end: datetime) -> list[Bar]:
    """Fetch bars covering [start, end] inclusive for `tv_symbol` at `tf`.

    `start` / `end` are timezone-aware datetimes (or naive = assumed UTC).
    Returns an empty list if Yahoo has no data in the window — caller
    decides whether that's a skip or an error.

    Yahoo's 5m window is limited to the last ~60 days. Requests beyond
    that come back empty with a console warning; the caller's job to
    catch the empty result and fall back."""
    ticker = resolve_yahoo_ticker(tv_symbol)
    interval = resolve_yahoo_interval(tf)
    # Normalize to date strings so LRU cache keys are stable.
    start_iso = _to_date_str(start)
    # Yahoo's `end` is exclusive; bump one day so the last bar of
    # the requested window is included.
    end_iso = _to_date_str(end + timedelta(days=1))
    return _fetch_raw(ticker, interval, start_iso, end_iso)


def _to_date_str(dt: datetime) -> str:
    """yfinance accepts YYYY-MM-DD date strings; it ignores time-of-day
    in the `start`/`end` args anyway. Drop TZ info cleanly."""
    if dt.tzinfo is not None:
        from datetime import timezone
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%d")


def slice_forward(bars: list[Bar], t0: datetime, horizon: int) -> list[Bar]:
    """Return the first `horizon` bars whose open time is strictly after
    `t0`. Bars are assumed sorted ascending.

    `t0` may be TZ-aware; we normalize to UTC naive for comparison
    against `Bar.ts` (which is always UTC naive per the fetch contract).
    """
    if t0.tzinfo is not None:
        from datetime import timezone
        t0 = t0.astimezone(timezone.utc).replace(tzinfo=None)
    out: list[Bar] = []
    for b in bars:
        if b.ts > t0:
            out.append(b)
            if len(out) >= horizon:
                break
    return out
