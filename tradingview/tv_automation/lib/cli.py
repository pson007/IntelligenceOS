"""CLI runner — maps TVAutomationError subclasses to exit codes and
prints result JSON to stdout. Use from every surface module's main()
so error handling is uniform.

Exit codes (from errors.py):
    0 = success
    1 = unexpected generic error
    2 = NotLoggedInError
    3 = NotPaperTradingError
    4 = SelectorDriftError
    5 = ModalError
    6 = VerificationFailedError
    7 = LimitViolationError
    8 = ChartNotReadyError
"""

from __future__ import annotations

import asyncio
import json
import sys
import traceback
from typing import Any, Awaitable, Callable

from . import audit
from .errors import TVAutomationError
from .retry import run_with_retry


def run(
    coro_factory: Callable[[], Awaitable[Any]] | Awaitable[Any],
    *,
    retries: int = 3,
) -> None:
    """Run an async CLI command with transient-error retry and request
    correlation. Prints result JSON; exits with a typed code on failure.

    `coro_factory` can be either an awaitable OR a callable that returns
    one. Prefer the callable form — retries need to create a fresh
    coroutine on each attempt (awaiting a coroutine twice raises).

    Pattern in CLI modules:

        def _main():
            args = parser.parse_args()
            run(lambda: place_order(args.symbol, args.side, args.qty))
    """
    # Mint a request id that lives for this entire CLI invocation. Every
    # audit.log() call within inherits it via the contextvar.
    req_id = audit.new_request_id()
    audit.current_request_id.set(req_id)

    # Normalize to a factory. Passing a raw coroutine still works for
    # call sites that haven't been updated — but those won't get retried
    # because you can't re-await a coroutine object. Surface a warning.
    if asyncio.iscoroutine(coro_factory):
        coro = coro_factory
        attempts = 1  # can't retry — coroutine is one-shot
    else:
        async def _runner():
            return await run_with_retry(coro_factory, attempts=retries)
        coro = _runner()
        attempts = retries

    try:
        result = asyncio.run(coro)
    except TVAutomationError as e:
        _print_err({
            "error": type(e).__name__,
            "message": str(e),
            "exit_code": e.exit_code,
            "request_id": req_id,
            **{k: v for k, v in vars(e).items() if not k.startswith("_")},
        })
        sys.exit(e.exit_code)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        _print_err({
            "error": type(e).__name__,
            "message": str(e),
            "exit_code": 1,
            "request_id": req_id,
            "traceback": traceback.format_exc(),
        })
        sys.exit(1)
    else:
        if result is not None:
            # Embed request_id for callers who want to correlate against
            # the audit log. Only add when result is dict-shaped so we
            # don't mutate primitive/list outputs.
            if isinstance(result, dict) and "request_id" not in result:
                result = {**result, "request_id": req_id}
            print(json.dumps(result, indent=2, default=str))
        sys.exit(0)


def _print_err(payload: dict) -> None:
    print(json.dumps(payload, indent=2, default=str), file=sys.stderr)
