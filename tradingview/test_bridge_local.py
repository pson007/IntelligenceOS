"""
Local dry-run of the bridge's TVSession.execute() — no FastAPI, no HMAC.
Just spins up the persistent Playwright session, fires ONE paper-trade
BUY for qty=2 of AAPL, and prints the result.

Run AFTER login.py + activate_paper.py have succeeded.

    .venv/bin/python test_bridge_local.py
"""

from __future__ import annotations

import asyncio
import os
import sys

# Force visible browser so we can watch the trade fire.
os.environ["TV_HEADLESS"] = "false"
# Bridge import asserts a non-empty BRIDGE_SHARED_SECRET — set a dummy for
# this local test, since we're not exercising the HMAC verification path.
os.environ.setdefault("BRIDGE_SHARED_SECRET", "dummy-secret-for-local-test")

from bridge import TVSession, OrderRequest


async def main() -> int:
    tv = TVSession()
    await tv.start()
    try:
        order = OrderRequest(symbol="AAPL", side="buy", qty=2)
        result = await tv.execute(order)
        print("\nRESULT:", result, flush=True)
        # Hold a few seconds so we can see the trade-confirmation toast.
        await asyncio.sleep(5)
    finally:
        await tv.stop()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
