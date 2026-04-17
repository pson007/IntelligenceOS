# TradingView Automation

Two related capabilities, sharing one persistent TradingView session:

1. **`screenshot.py`** — clean chart screenshots driven by Playwright (replaces the legacy `tradingview-chart.sh`).
2. **`bridge.py` + `tv-worker/`** — Pine Script alert → Cloudflare Worker → local FastAPI bridge → click Buy/Sell in the TradingView Trading Panel (paper trading).

```
TradingView Pine Script alert
        │ HTTPS POST { auth_token, symbol, side, qty }
        ▼
Cloudflare Worker  (validates token, HMAC-signs body)
        │ POST  X-Bridge-Signature: sha256=…
        ▼
Cloudflare Tunnel  ➜  FastAPI bridge on this Mac
        │ verifies HMAC, validates allowlist
        ▼
Playwright (long-lived Chromium, logged into TradingView)
        │ clicks Buy/Sell on Trading Panel
        ▼
TradingView Paper Trading account
```

---

## One-time setup

### 1. Python deps
```bash
cd tradingview
.venv/bin/pip install -r requirements.txt   # already done if you ran setup
.venv/bin/playwright install chromium
```

### 2. Generate the two shared secrets
```bash
python3 -c "import secrets; print('WEBHOOK_AUTH_TOKEN  =', secrets.token_urlsafe(32))"
python3 -c "import secrets; print('BRIDGE_SHARED_SECRET=', secrets.token_urlsafe(32))"
```

Copy the second one into `tradingview/.env`:
```bash
cp .env.example .env
# then edit .env and paste BRIDGE_SHARED_SECRET=...
```

### 3. Log in to TradingView (visible browser; one time)
```bash
.venv/bin/python login.py
```
After signing in, **open a chart and connect "Paper Trading"** in the bottom Trading Panel. TradingView remembers this per account.

### 4. Set up Cloudflare Worker
```bash
cd ../tv-worker
npm install
npx wrangler login                          # one-time browser auth
npx wrangler secret put WEBHOOK_AUTH_TOKEN   # paste value from step 2
npx wrangler secret put BRIDGE_SHARED_SECRET # paste value from step 2
# Edit wrangler.jsonc → set BRIDGE_URL to your tunnel URL (next step)
npx wrangler deploy
```
After deploy, note the URL printed (e.g. `https://tv-router.your-account.workers.dev`).

### 5. Set up Cloudflare Tunnel (free quick tunnel)
```bash
brew install cloudflared
# in one terminal — start the bridge
cd tradingview && .venv/bin/uvicorn bridge:app --host 127.0.0.1 --port 8787

# in another terminal — start the tunnel
cloudflared tunnel --url http://localhost:8787
```
Cloudflared will print something like `https://random-name.trycloudflare.com`. Update `tv-worker/wrangler.jsonc` → `BRIDGE_URL` to `https://random-name.trycloudflare.com/webhook`, then redeploy:
```bash
cd ../tv-worker && npx wrangler deploy
```

> **Note**: quick tunnels rotate URL on each restart. For a stable URL, switch to a named tunnel — see [Cloudflare Tunnel docs](https://developers.cloudflare.com/cloudflare-tunnel/).

### 6. Add a Pine Script alert
1. Pine Editor → paste `pine/webhook_alert.pine` → Save → "Add to chart".
2. Right-click chart → Add alert.
3. Condition: `Webhook Alert Template` → "Any alert() function call".
4. Webhook URL: `https://tv-router.<your-account>.workers.dev/webhook`
5. Message:
   ```json
   {
     "auth_token": "PASTE_WEBHOOK_AUTH_TOKEN",
     "symbol": "{{ticker}}",
     "side": "{{strategy.order.action}}",
     "qty": 1
   }
   ```
6. Save.

---

## Day-to-day usage

### Take a chart screenshot
```bash
.venv/bin/python screenshot.py AAPL 1D
.venv/bin/python screenshot.py BTCUSD 4h -o /tmp/btc.png
.venv/bin/python screenshot.py NVDA 1h --headed   # watch it run
```

### Run the trading bridge
```bash
.venv/bin/uvicorn bridge:app --host 127.0.0.1 --port 8787
# keep cloudflared running in another terminal
```

---

## End-to-end test plan

Before relying on this for live alerts, walk through:

- [ ] `python login.py` succeeds and prints "Logged in"
- [ ] `python screenshot.py AAPL 1D` produces a real chart PNG (not a login page)
- [ ] `curl http://127.0.0.1:8787/health` returns `{"ok":true,"session_ready":true}` after starting bridge
- [ ] `curl https://tv-router.<acct>.workers.dev/health` returns `{"ok":true}`
- [ ] **Manual signed test** — in `tradingview/` run:
  ```bash
  .venv/bin/python -c '
  import hmac, hashlib, json, os, urllib.request
  from dotenv import load_dotenv; load_dotenv()
  body = json.dumps({"symbol":"AAPL","side":"buy","qty":1}).encode()
  sig = hmac.new(os.environ["BRIDGE_SHARED_SECRET"].encode(), body, hashlib.sha256).hexdigest()
  req = urllib.request.Request("http://127.0.0.1:8787/webhook",
      data=body, headers={"X-Bridge-Signature":f"sha256={sig}", "Content-Type":"application/json"})
  print(urllib.request.urlopen(req).read())
  '
  ```
  Expect: a paper buy of 1 AAPL appears in your TradingView Paper Trading account.
- [ ] Trigger the Pine Script alert manually (TradingView alert dialog → "Trigger an alert" debug).
- [ ] Watch `wrangler tail` and the bridge logs for the round trip.

If the Trading Panel selectors no longer match (TradingView ships UI updates often), run the bridge with `TV_HEADLESS=false uvicorn bridge:app ...` and use `await page.pause()` (Playwright Inspector) to find the new `data-name` attributes. Update the constants in `bridge.py`.

---

## Files

| File | Purpose |
|---|---|
| `session.py` | Persistent Chromium context shared by screenshot + bridge |
| `login.py` | One-time interactive TradingView sign-in |
| `screenshot.py` | Chart screenshot CLI (replaces `../tradingview-chart.sh`) |
| `bridge.py` | FastAPI server that executes paper trades from signed webhooks |
| `pine/webhook_alert.pine` | Pine Script template that fires alerts in the right JSON shape |
| `requirements.txt` | Python deps |
| `.env` | Local secrets (gitignored) |
| `../tv-worker/` | Cloudflare Worker (TypeScript) |
