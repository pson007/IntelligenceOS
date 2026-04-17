"""Load limits.yaml and expose as typed config.

Single import point for the safety limits — every mutating action pulls
from here. Failing to load means refusing to trade rather than defaulting
to "anything goes."
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from .lib.errors import LimitViolationError

_LIMITS_PATH = Path(__file__).resolve().parent / "limits.yaml"


@dataclass(frozen=True)
class Limits:
    allowed_symbols: frozenset[str]
    max_qty: int
    per_symbol_max_qty: dict[str, int]
    per_symbol_tick_size: dict[str, float]
    required_broker_contains: tuple[str, ...]
    min_seconds_between_orders: float


@lru_cache(maxsize=1)
def limits() -> Limits:
    data = yaml.safe_load(_LIMITS_PATH.read_text()) or {}
    raw_qty_overrides = data.get("per_symbol_max_qty") or {}
    raw_tick_overrides = data.get("per_symbol_tick_size") or {}
    return Limits(
        allowed_symbols=frozenset(
            s.upper() for s in (data.get("allowed_symbols") or [])
        ),
        max_qty=int(data.get("max_qty", 1)),
        per_symbol_max_qty={
            k.upper(): int(v) for k, v in raw_qty_overrides.items()
        },
        per_symbol_tick_size={
            k.upper(): float(v) for k, v in raw_tick_overrides.items()
        },
        required_broker_contains=tuple(
            s.lower() for s in (data.get("required_broker_contains") or ["paper"])
        ),
        min_seconds_between_orders=float(
            data.get("min_seconds_between_orders", 0)
        ),
    )


def check_symbol(symbol: str) -> None:
    """Raise LimitViolationError if the symbol isn't in the allowlist.
    Strips any exchange prefix (NASDAQ:AAPL → AAPL) before checking."""
    lim = limits()
    bare = symbol.split(":")[-1].upper()
    if bare not in lim.allowed_symbols:
        raise LimitViolationError(
            f"Symbol {symbol!r} (bare={bare!r}) not in allowlist. "
            f"Edit tv_automation/limits.yaml to add it."
        )


def check_qty(qty: int, symbol: str | None = None) -> None:
    """Raise LimitViolationError if qty exceeds the configured max.

    Per-symbol override wins when present: e.g. MNQ1! may cap at 1
    contract while equities keep the global max_qty of 100. Pass
    `symbol` to opt into the lookup; omit to use the global cap only
    (back-compat for callers that predate the override)."""
    lim = limits()
    if qty <= 0:
        raise LimitViolationError(f"qty must be positive, got {qty}")
    bare = (symbol.split(":")[-1].upper() if symbol else None)
    cap = lim.per_symbol_max_qty.get(bare, lim.max_qty) if bare else lim.max_qty
    if qty > cap:
        source = (
            f"per_symbol_max_qty[{bare!r}]={cap}"
            if bare and bare in lim.per_symbol_max_qty
            else f"max_qty={cap}"
        )
        raise LimitViolationError(
            f"qty {qty} exceeds {source}. "
            f"Edit tv_automation/limits.yaml to change."
        )


def check_tick_alignment(
    symbol: str | None, price: float | None, *, field: str = "price",
) -> None:
    """Raise LimitViolationError if `price` isn't a multiple of the
    symbol's configured tick size. No-op when either argument is None
    or the symbol has no entry in `per_symbol_tick_size` (passthrough).

    The `field` kwarg is used in the error message — pass "limit_price",
    "stop_loss", etc. so the caller knows which field was off-tick.

    Why reject rather than round: TV often silently rounds off-tick
    prices to the nearest valid tick, which produces an order that
    DIFFERS from what the CLI asked for. A rejection surfaces the
    typo explicitly — the caller can fix it, not debug a subtle diff.
    """
    if symbol is None or price is None:
        return
    lim = limits()
    bare = symbol.split(":")[-1].upper()
    tick = lim.per_symbol_tick_size.get(bare)
    if tick is None or tick <= 0:
        return
    # Use a tolerance proportional to tick size to avoid floating-point
    # false positives — 0.1% of a tick is well below any meaningful
    # misalignment. `round(price/tick)*tick` gives the nearest valid price.
    rounded = round(price / tick) * tick
    if abs(price - rounded) > tick * 0.001:
        raise LimitViolationError(
            f"{field} {price} for symbol {bare!r} is not on a {tick}-tick "
            f"grid (nearest valid: {rounded}). "
            f"Edit tv_automation/limits.yaml → per_symbol_tick_size if "
            f"this symbol's tick size has changed."
        )


def broker_label_allowed(label: str | None) -> bool:
    """True if the broker-chip label matches one of the required substrings.
    Called by guards.assert_paper_trading via config-driven policy."""
    if not label:
        return False
    lbl = label.lower()
    return any(sub in lbl for sub in limits().required_broker_contains)


# ---------------------------------------------------------------------------
# Velocity limit — stamp-file based.
# ---------------------------------------------------------------------------

import time
from pathlib import Path as _Path

from .lib.errors import LimitViolationError as _LimitViolationError

_STAMP_DIR = _Path("/tmp/tv-automation")


def check_velocity(action: str = "order") -> None:
    """Raise LimitViolationError if the most recent call under this
    action name was too recent per `min_seconds_between_orders`.

    Per-action stamp file — so place_order and close_position could use
    distinct names ("order", "close") if you want independent throttles.
    For now, both share `"order"` to catch the common "LLM retry loop"
    failure mode where a place + close rapidly alternate.

    Call `record_action(action)` AFTER a mutating action to stamp the
    current time.
    """
    min_gap = limits().min_seconds_between_orders
    if min_gap <= 0:
        return
    _STAMP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _STAMP_DIR / f"{action}.stamp"
    if not stamp.exists():
        return
    elapsed = time.time() - stamp.stat().st_mtime
    if elapsed < min_gap:
        remaining = min_gap - elapsed
        raise _LimitViolationError(
            f"Velocity limit: last {action!r} was {elapsed:.1f}s ago "
            f"(min_seconds_between_orders={min_gap}). "
            f"Wait {remaining:.1f}s and retry."
        )


def record_action(action: str = "order") -> None:
    """Stamp the current time for the given action — use AFTER a
    successful mutation so the next call respects the cooldown."""
    _STAMP_DIR.mkdir(parents=True, exist_ok=True)
    (_STAMP_DIR / f"{action}.stamp").touch()
