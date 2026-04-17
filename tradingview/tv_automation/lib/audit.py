"""Append-only JSONL audit log.

Every mutating action writes a line here so the user can review exactly
what happened after the fact — especially important when an LLM is
driving and you want to reconstruct "what did Claude do at 2pm."

Files rotate by local date: tradingview/audit/YYYY-MM-DD.jsonl

Each entry includes:
  * ts          — ISO 8601 timestamp
  * pid         — process id
  * request_id  — short UUID set by the CLI runner at the start of every
                  invocation. Use to correlate .start/.complete pairs or
                  tie a failure mid-sequence back to the originating call.
  * event       — dotted name, e.g. "trading.place_order.start"
  * duration_ms — present on .complete / .end entries when produced via
                  the `timed()` context manager.
  * ...         — any additional kwargs passed to `log()`.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Iterator

# Parent of tv_automation/ — i.e. the tradingview/ directory.
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent
_AUDIT_DIR = _PACKAGE_ROOT / "audit"

# Per-invocation correlation ID. The CLI runner in lib/cli.py sets this
# at the top of every `run()` call. Everything logged between then and
# the CLI's exit shares the same request_id — so a failed trade and its
# earlier "start" event can be paired even across concurrent processes.
current_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_request_id", default=None,
)


def new_request_id() -> str:
    """Mint a short (8-char) correlation id — unique within typical session
    scope, small enough to eyeball in logs."""
    return uuid.uuid4().hex[:8]


def _today_file() -> Path:
    _AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    return _AUDIT_DIR / f"{time.strftime('%Y-%m-%d')}.jsonl"


def log(event: str, **fields: Any) -> None:
    """Write one audit entry. Never raises — audit must not break the caller."""
    try:
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "pid": os.getpid(),
            "request_id": current_request_id.get(),
            "event": event,
            **fields,
        }
        with _today_file().open("a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception:
        # Audit failures are non-fatal by design.
        pass


@contextlib.contextmanager
def timed(event_base: str, **start_fields: Any) -> Iterator[dict]:
    """Context manager that logs `<event_base>.start` on entry and
    `<event_base>.complete` (or `<event_base>.failed`) on exit, with a
    `duration_ms` field pairing them.

    Usage:
        with timed("trading.place_order", symbol="NVDA", qty=1) as ctx:
            ...do work...
            ctx["executed_qty"] = 1   # attach fields to the .complete entry

    If the block raises, logs `<event_base>.failed` with the exception
    type and message. Re-raises unchanged.
    """
    log(f"{event_base}.start", **start_fields)
    extra: dict[str, Any] = {}
    start = time.perf_counter()
    try:
        yield extra
    except Exception as e:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        # extra wins on key conflicts — it's what the block learned
        # during execution, vs start_fields which were the initial args.
        merged = {**start_fields, **extra}
        log(f"{event_base}.failed",
            duration_ms=elapsed_ms,
            error_type=type(e).__name__,
            error_message=str(e),
            **merged)
        raise
    else:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        merged = {**start_fields, **extra}
        log(f"{event_base}.complete", duration_ms=elapsed_ms, **merged)
