"""Multi-symbol pre-session scanner.

Inspired by LewisWJackson/tradingview-mcp-jackson's "morning brief"
workflow. Iterates a watchlist of symbols and produces a compact
session-open snapshot per symbol — daily OHLC, session range, ATR
proxy, distance from key levels, and any user-drawn levels TV knows
about. Useful at 09:25 ET as a "scan everything I'd consider trading
today" pass before committing to a single-symbol forecast.

Built on the in-place navigation primitives (`set_symbol_in_place`)
landed in this session — switching 5 symbols × 1m takes ~5s instead
of ~25s with the old page.goto path. Each symbol stays on the SAME
chart layout, so any reference indicators on that layout (e.g. a
forecast overlay or back-adjusted continuous contract) follow along.

Output:
  - JSON written to `tradingview/scans/{YYYY-MM-DD}_morning.json`
  - Markdown summary printed to stdout / saved alongside
  - Per-symbol screenshots in `~/Desktop/TradingView/morning_scan/`

CLI:
    python -m tv_automation.morning_scan
    python -m tv_automation.morning_scan --symbols MNQ1!,ES1!,RTY1!
    python -m tv_automation.morning_scan --tf 5m
    python -m tv_automation.morning_scan --include-drawings  # add user-drawn levels
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from . import bar_reader, replay, replay_api, user_drawings as ud
from .lib import audit
from .lib.capture_invariants import CaptureExpect, assert_capture_ready
from .lib.context import chart_session


_SCAN_ROOT = (Path(__file__).parent.parent / "scans").resolve()
_SCREENSHOT_ROOT = (Path.home() / "Desktop" / "TradingView" / "morning_scan").resolve()


# Default watchlist — index futures the user actually trades / watches.
# The MNQ1! is primary per CLAUDE.md; the others are correlation context.
_DEFAULT_SYMBOLS = ["MNQ1!", "MES1!", "MYM1!", "M2K1!"]


def _today_session_bounds() -> tuple[datetime, datetime]:
    """Return naive ET datetimes for today's RTH open + close."""
    now = datetime.now()
    open_dt = now.replace(hour=9, minute=30, second=0, microsecond=0)
    close_dt = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return open_dt, close_dt


async def _scan_one_symbol(
    page, symbol: str, *, interval: str = "1",
    include_drawings: bool = False,
) -> dict:
    """Switch chart to `symbol` in-place and capture: state confirm,
    session OHLC (live + prev-day), screenshot, optional drawings."""
    sym_for_api = symbol if "!" in symbol or ":" in symbol else f"{symbol}!"

    landed = await replay_api.set_symbol_in_place(
        page, symbol=sym_for_api, interval=interval,
    )
    if not landed:
        return {"symbol": symbol, "ok": False,
                "error": "set_symbol_in_place failed"}

    # Today's session OHLC — may be partial if scan runs mid-session,
    # full when run after close.
    open_dt, close_dt = _today_session_bounds()
    today_ohlc = await bar_reader.read_session_ohlc(
        page, start_et=open_dt, end_et=close_dt,
    )

    # Prior day for context — same RTH window, 24h earlier.
    prev_open = open_dt - timedelta(days=1)
    prev_close = close_dt - timedelta(days=1)
    prev_ohlc = await bar_reader.read_session_ohlc(
        page, start_et=prev_open, end_et=prev_close,
    )

    # Pre-market activity — globex up to 09:30 ET. Strong move overnight
    # often colors the morning's bias.
    overnight_open = open_dt.replace(hour=18) - timedelta(days=1)
    overnight_close = open_dt - timedelta(minutes=1)
    overnight_ohlc = await bar_reader.read_session_ohlc(
        page, start_et=overnight_open, end_et=overnight_close,
    )

    # Take a screenshot for visual reference (optional but useful).
    _SCREENSHOT_ROOT.mkdir(parents=True, exist_ok=True)
    safe_sym = re.sub(r"[^A-Za-z0-9]+", "_", sym_for_api)
    ts = datetime.now().strftime("%H%M%S")
    shot_path = _SCREENSHOT_ROOT / f"{safe_sym}_{interval}_{ts}.png"
    screenshot_error = None
    try:
        await assert_capture_ready(
            page,
            CaptureExpect(
                symbol=sym_for_api,
                interval=interval,
                replay_mode=False,
            ),
        )
        await page.screenshot(path=str(shot_path))
    except Exception as e:
        screenshot_error = f"{type(e).__name__}: {e}"
        audit.log("morning_scan.screenshot.fail",
                  symbol=symbol, err=screenshot_error)
        shot_path = None

    drawings_summary = None
    if include_drawings:
        drawings = await ud.read_user_drawings(page)
        drawings_summary = {
            "total": drawings.get("total", 0),
            "by_kind": drawings.get("by_kind_counts", {}),
            "horizontal_prices": sorted({
                pt["price"]
                for s in (drawings.get("by_kind") or {}).get("horizontal", [])
                for pt in (s.get("points") or [])
                if isinstance(pt.get("price"), (int, float))
            }, reverse=True),
        }

    return {
        "symbol": symbol,
        "tv_symbol": landed.get("symbol"),
        "interval": landed.get("resolution"),
        "ok": screenshot_error is None,
        "error": screenshot_error,
        "today_session": today_ohlc,
        "prev_session": prev_ohlc,
        "overnight": overnight_ohlc,
        "drawings": drawings_summary,
        "screenshot": str(shot_path) if shot_path else None,
        "scanned_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def _summarize_one(result: dict) -> str:
    """Compact one-line markdown summary per symbol."""
    if not result.get("ok"):
        return f"- **{result['symbol']}**: ❌ {result.get('error', 'failed')}"

    today = result.get("today_session") or {}
    prev = result.get("prev_session") or {}
    on = result.get("overnight") or {}

    parts = [f"- **{result['symbol']}**"]
    if today.get("bars_count"):
        net = today.get("net_pts", 0)
        arrow = "↑" if (net or 0) > 0 else ("↓" if (net or 0) < 0 else "→")
        parts.append(
            f"today {arrow} {abs(net or 0):g}pts "
            f"(O {today.get('open', '?')} → "
            f"H {today.get('hod', '?')} / L {today.get('lod', '?')} / "
            f"C {today.get('close', '?')})"
        )
    elif on.get("bars_count"):
        parts.append(
            f"pre-mkt span {on.get('span_pts', '?')}pts "
            f"(H {on.get('hod', '?')} / L {on.get('lod', '?')})"
        )

    if prev.get("close") is not None and today.get("open") is not None:
        gap = today["open"] - prev["close"]
        gap_pct = (gap / prev["close"]) * 100 if prev["close"] else 0
        gap_arrow = "↑" if gap > 0 else ("↓" if gap < 0 else "→")
        parts.append(f"gap {gap_arrow} {abs(gap):g}pts ({gap_pct:+.2f}%)")

    drawings = result.get("drawings") or {}
    horiz = drawings.get("horizontal_prices") or []
    if horiz:
        nearby = sorted(horiz)[:5]
        parts.append(f"user levels: {', '.join(f'{p:g}' for p in nearby)}")

    return " · ".join(parts)


async def scan(
    symbols: list[str], *, interval: str = "1",
    include_drawings: bool = False,
) -> dict:
    _SCAN_ROOT.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now()
    audit.log("morning_scan.start", symbols=symbols, interval=interval)

    results: list[dict] = []
    async with chart_session() as (_ctx, page):
        await replay.exit_replay(page)
        if not await replay_api.api_available(page):
            return {
                "ok": False,
                "error": "TradingViewApi not exposed on the active chart tab",
            }
        for sym in symbols:
            try:
                results.append(await _scan_one_symbol(
                    page, sym, interval=interval,
                    include_drawings=include_drawings,
                ))
            except Exception as e:
                results.append({"symbol": sym, "ok": False,
                                "error": f"{type(e).__name__}: {e}"})

    finished_at = datetime.now()
    summary_md = "# Morning scan — " \
                 + started_at.strftime("%Y-%m-%d %H:%M ET") + "\n\n"
    summary_md += "\n".join(_summarize_one(r) for r in results)

    out = {
        "ok": True,
        "started_at": started_at.astimezone().isoformat(timespec="seconds"),
        "finished_at": finished_at.astimezone().isoformat(timespec="seconds"),
        "duration_s": round((finished_at - started_at).total_seconds(), 1),
        "symbols": symbols,
        "interval": interval,
        "include_drawings": include_drawings,
        "results": results,
        "summary_md": summary_md,
    }

    today_str = started_at.strftime("%Y-%m-%d")
    json_path = _SCAN_ROOT / f"{today_str}_morning.json"
    md_path = _SCAN_ROOT / f"{today_str}_morning.md"
    json_path.write_text(json.dumps(out, indent=2, default=str))
    md_path.write_text(summary_md + "\n")

    audit.log("morning_scan.complete",
              count=len(results),
              duration_s=out["duration_s"],
              json_path=str(json_path))
    return out


def _main() -> None:
    p = argparse.ArgumentParser(prog="tv_automation.morning_scan")
    p.add_argument(
        "--symbols", default=",".join(_DEFAULT_SYMBOLS),
        help=f"Comma-separated list (default: {','.join(_DEFAULT_SYMBOLS)})",
    )
    p.add_argument("--tf", default="1",
                   help="Timeframe in TV-native form (1, 5, 60, D). Default 1.")
    p.add_argument("--include-drawings", action="store_true",
                   help="Also read user-drawn levels per symbol")
    args = p.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    out = asyncio.run(scan(
        symbols, interval=args.tf, include_drawings=args.include_drawings,
    ))
    print(out["summary_md"])
    print(f"\nJSON: {_SCAN_ROOT}/{datetime.now().strftime('%Y-%m-%d')}_morning.json")


if __name__ == "__main__":
    _main()
