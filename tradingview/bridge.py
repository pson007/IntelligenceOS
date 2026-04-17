"""
FastAPI bridge: receives signed webhooks and executes paper trades by
driving the TradingView Trading Panel via a long-lived Playwright session.

Run:
    .venv/bin/uvicorn bridge:app --host 127.0.0.1 --port 8787

End-to-end flow:
    Pine Script alert
      → Cloudflare Worker (validates HMAC v1)
      → Cloudflare Tunnel
      → THIS server (validates HMAC v2, executes trade)
      → Trading Panel UI in persistent Chromium

Prerequisites:
  1. `python login.py` — sign in to TradingView once.
  2. `python activate_paper.py` — activates Paper Trading as the connected
     broker (one-time). Note: Paper Trading triggers a SECOND sign-in
     inside the broker-connection flow even though you're already logged
     into the chart — this is normal. Look for the small "Sign in" link
     at the BOTTOM of the dark Sign Up panel.
  3. Set BRIDGE_SHARED_SECRET in .env.

How a trade is placed (the verified flow):
  TradingView's inline quick-trade bar at the top of the chart has three
  controls in a row:
      [SELL @ $price]  [qty: N]  [BUY @ $price]
  Clicking BUY or SELL fires a MARKET order INSTANTLY for `qty` shares.
  There is no order ticket to fill — it's one-click trading.
  Editing qty alone does not place a trade; only Buy/Sell click does.
  So the bridge sets qty, then clicks side. Two atomic steps.

Security model:
  - Every request must carry an `X-Bridge-Signature` header with
    `sha256=<hex hmac>` computed over the raw request body using
    BRIDGE_SHARED_SECRET. We compare in constant time.
  - We validate symbol/side/qty against an allowlist before clicking.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
from contextlib import asynccontextmanager
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from playwright.async_api import BrowserContext, Page
from pydantic import BaseModel, Field, field_validator

from preflight import ensure_automation_chromium
from session import open_chart, tv_context

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
log = logging.getLogger("tv-bridge")

SHARED_SECRET = os.getenv("BRIDGE_SHARED_SECRET", "").encode()
if not SHARED_SECRET:
    raise SystemExit(
        "BRIDGE_SHARED_SECRET is empty. Generate one with:\n"
        '  python3 -c "import secrets; print(secrets.token_urlsafe(32))"\n'
        "and set it in tradingview/.env"
    )

# ---------------------------------------------------------------------------
# Allowlist — the bridge will reject anything outside these bounds even with
# a valid signature. This is a second line of defense against a leaked secret.
# ---------------------------------------------------------------------------
ALLOWED_SYMBOLS: set[str] = {
    # Add yours here. Use TradingView's full symbol form when needed,
    # e.g. "NASDAQ:AAPL", "BINANCE:BTCUSDT".
    "AAPL", "MSFT", "NVDA", "TSLA", "SPY", "QQQ",
}
MAX_QTY = 100  # Reject any single order larger than this.

# ---------------------------------------------------------------------------
# Verified inline quick-trade selectors (probed 2026-04-16 via probe_qty.py
# against TradingView's current React build). All carry stable `data-name`
# attributes that survive React class-name rotations across deploys.
#
# qtyEl is a <div> wrapping a <span> showing the current qty. Clicking it
# pops a calculator with input#calculator-input. The id is stable; the
# input has no data-name. We type the new qty and press Tab to commit.
# ---------------------------------------------------------------------------
SEL_QTY_EL = '[data-name="qtyEl"]'
SEL_QTY_CALCULATOR_INPUT = 'input#calculator-input'
SEL_BUY_BUTTON = '[data-name="buy-order-button"]'
SEL_SELL_BUTTON = '[data-name="sell-order-button"]'

# Sanity-check selector: the broker picker dialog. If this is ever visible
# at the moment we're about to place a trade, Paper Trading was deactivated
# and clicking BUY would open a "pick your broker" modal instead of trading.
# We refuse to proceed in that case rather than risk a wrong-broker click.
SEL_BROKER_PICKER = '[data-name="select-broker-dialog"]'

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class OrderRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=32)
    side: Literal["buy", "sell"]
    qty: int = Field(..., gt=0, le=MAX_QTY)
    # Future: order_type: Literal["market", "limit"] = "market"
    # Future: limit_price: float | None = None

    @field_validator("symbol")
    @classmethod
    def _allowed(cls, v: str) -> str:
        # Strip exchange prefix for the allowlist check (NASDAQ:AAPL → AAPL)
        bare = v.split(":")[-1].upper()
        if bare not in ALLOWED_SYMBOLS:
            raise ValueError(f"symbol {v!r} not in allowlist")
        return v


# ---------------------------------------------------------------------------
# Long-lived Playwright session — one browser, one chart page, reused.
# ---------------------------------------------------------------------------

class TVSession:
    """Holds the open browser context + chart page across requests."""

    def __init__(self) -> None:
        self.ctx: BrowserContext | None = None
        self.page: Page | None = None
        self._ctx_cm = None  # async context manager handle for clean shutdown
        self.lock = asyncio.Lock()  # serialize trade execution

    async def start(self) -> None:
        log.info("Starting persistent Playwright session...")
        # In CDP-attach mode, ensure the long-running Chromium is up and
        # signed in before we try to connect. In launch mode this is a no-op.
        await ensure_automation_chromium()
        self._ctx_cm = tv_context()
        self.ctx = await self._ctx_cm.__aenter__()
        self.page = await open_chart(self.ctx)  # blank chart, no symbol
        log.info("Session ready.")

    async def stop(self) -> None:
        if self._ctx_cm is not None:
            await self._ctx_cm.__aexit__(None, None, None)
            log.info("Session closed.")

    async def execute(self, order: OrderRequest) -> dict:
        """Set qty in the inline quick-trade bar, then click Buy or Sell."""
        assert self.page is not None
        page = self.page

        # Switch the chart to the requested symbol via URL. The inline
        # quick-trade bar (top of chart) re-renders for the new symbol but
        # its [data-name] selectors stay the same.
        await page.goto(
            f"https://www.tradingview.com/chart/?symbol={order.symbol}",
            wait_until="domcontentloaded",
        )
        await page.wait_for_selector("canvas", state="visible", timeout=20_000)
        # Buy/Sell/qty controls hydrate after the chart paints — wait on the
        # qtyEl rather than a fixed timeout.
        await page.wait_for_selector(SEL_QTY_EL, state="visible", timeout=15_000)

        # Refuse to place an order if the broker picker is visible. That
        # means Paper Trading isn't connected and clicking BUY would open
        # a "select broker" dialog instead of trading.
        if await page.locator(SEL_BROKER_PICKER).count() > 0:
            raise RuntimeError(
                "Broker picker visible — Paper Trading isn't connected. "
                "Run activate_paper.py."
            )

        # Set qty: click qtyEl → calculator input gets focus → select-all,
        # type new value, Tab to commit. Doing this BEFORE clicking Buy/Sell
        # is critical because the side buttons are atomic-fire.
        await page.click(SEL_QTY_EL)
        calc = page.locator(SEL_QTY_CALCULATOR_INPUT).first
        await calc.wait_for(state="visible", timeout=5_000)
        # Cmd+A on macOS, Ctrl+A elsewhere — Playwright maps "ControlOrMeta".
        await page.keyboard.press("ControlOrMeta+A")
        await page.keyboard.type(str(order.qty))
        await page.keyboard.press("Tab")
        await page.wait_for_timeout(300)

        # Verify the qty actually committed. The qtyEl span should now read
        # our value. If it doesn't, abort instead of firing at the wrong qty.
        committed = (await page.locator(f"{SEL_QTY_EL} span").first.inner_text()).strip()
        if committed != str(order.qty):
            raise RuntimeError(
                f"qty did not commit: requested {order.qty}, qtyEl shows {committed!r}"
            )

        # Fire the market order. This is the single atomic action that
        # actually executes the trade.
        side_sel = SEL_BUY_BUTTON if order.side == "buy" else SEL_SELL_BUTTON
        await page.click(side_sel)
        # Brief wait so the trade-notification toast has time to render
        # before we accept another request (helps the lock-released ordering).
        await page.wait_for_timeout(500)

        log.info("Placed: %s %d %s", order.side.upper(), order.qty, order.symbol)
        return {"ok": True, "executed": order.model_dump()}


tv = TVSession()


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    await tv.start()
    yield
    await tv.stop()


app = FastAPI(title="TradingView Paper-Trading Bridge", lifespan=lifespan)


def verify_signature(body: bytes, header: str | None) -> None:
    if not header or not header.startswith("sha256="):
        raise HTTPException(status_code=401, detail="missing or malformed signature header")
    sent = header.removeprefix("sha256=")
    expected = hmac.new(SHARED_SECRET, body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sent, expected):
        raise HTTPException(status_code=401, detail="bad signature")


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "session_ready": tv.page is not None}


@app.post("/webhook")
async def webhook(request: Request) -> dict:
    raw = await request.body()
    verify_signature(raw, request.headers.get("X-Bridge-Signature"))

    try:
        order = OrderRequest.model_validate_json(raw)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invalid payload: {e}")

    # Serialize so two alerts firing at once don't fight over the UI.
    async with tv.lock:
        try:
            return await tv.execute(order)
        except Exception as e:
            log.exception("Trade execution failed")
            raise HTTPException(status_code=500, detail=str(e))
