"""Dump TradingView auth cookies so we know exactly what state we're in."""

from __future__ import annotations

import asyncio
import sys

from session import tv_context


async def main() -> int:
    async with tv_context(headless=True) as ctx:
        page = await ctx.new_page()
        # Use /markets/ rather than /chart/ — the chart page holds open
        # WebSockets so even wait_until="domcontentloaded" can race with
        # long resource loads. /markets/ is a lighter landing page that
        # still has the auth cookies set.
        await page.goto("https://www.tradingview.com/markets/",
                        wait_until="domcontentloaded")
        await page.wait_for_timeout(1500)

        # All cookies (including HttpOnly, which `document.cookie` misses).
        cookies = await ctx.cookies("https://www.tradingview.com")
        names = [c["name"] for c in cookies]
        print(f"{len(cookies)} cookies on tradingview.com:", flush=True)
        for c in cookies:
            print(f"  {c['name']}  (httpOnly={c.get('httpOnly')}, "
                  f"expires={c.get('expires')})", flush=True)

        auth_cookies = {"sessionid", "sessionid_sign", "device_t"}
        has_auth = any(n in auth_cookies for n in names)
        print(f"\nAuth cookies present: {has_auth}", flush=True)
        return 0 if has_auth else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
