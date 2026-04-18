#!/usr/bin/env bash
# One-shot: expose the IntelligenceOS Console to your tailnet via
# Tailscale Serve, and print a shareable URL with the UI_TOKEN baked
# into its #token=… fragment.
#
# Idempotent — safe to re-run. Tailscale Serve persists across restarts
# of both tailscaled and the UI server, so after the first run you just
# launch ./run-ui.sh normally.
#
# Usage:
#   ./run-ui-tailscale.sh             # default port 8788
#   PORT=9000 ./run-ui-tailscale.sh   # override

set -euo pipefail
cd "$(dirname "$0")"

: "${PORT:=8788}"
ENV_FILE=".env"

# ----------------------------------------------------------------------
# 1. Preflight — Tailscale installed, daemon reachable, logged in.
# ----------------------------------------------------------------------
if ! command -v tailscale >/dev/null 2>&1; then
  echo "✗ tailscale CLI not installed. See https://tailscale.com/download" >&2
  exit 1
fi
if ! tailscale status --self --json >/dev/null 2>&1; then
  echo "✗ tailscale not logged in / daemon offline. Run: tailscale up" >&2
  exit 1
fi
if [ ! -f "$ENV_FILE" ]; then
  echo "✗ $ENV_FILE not found. Copy from .env.example first." >&2
  exit 1
fi

# ----------------------------------------------------------------------
# 2. Ensure UI_TOKEN is set. Empty or missing line → generate one and
#    write it back. Existing non-empty value is preserved (we never
#    rotate a token the user might already be using elsewhere).
# ----------------------------------------------------------------------
current_token=$(grep -E '^UI_TOKEN=' "$ENV_FILE" | head -n1 | cut -d= -f2- || true)

if [ -z "${current_token// /}" ]; then
  new_token=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')
  if grep -qE '^UI_TOKEN=' "$ENV_FILE"; then
    # macOS sed wants '' after -i
    sed -i '' "s|^UI_TOKEN=.*|UI_TOKEN=$new_token|" "$ENV_FILE"
  else
    printf '\n# Shared-secret token for UI Console (required when UI is\n# reachable from tailnet / LAN).\nUI_TOKEN=%s\n' "$new_token" >> "$ENV_FILE"
  fi
  current_token="$new_token"
  token_status="generated (written to $ENV_FILE)"
else
  token_status="reusing existing value from $ENV_FILE"
fi

# ----------------------------------------------------------------------
# 3. Configure Tailscale Serve. `--bg` persists the config across
#    restarts; re-running this command is harmless.
# ----------------------------------------------------------------------
echo "→ configuring: https://+:443/  →  http://127.0.0.1:$PORT  (tailnet only)"
tailscale serve --bg "$PORT" >/dev/null

# ----------------------------------------------------------------------
# 4. Resolve the tailnet DNS name and print the shareable URL.
# ----------------------------------------------------------------------
dns_full=$(tailscale status --self --json | python3 -c \
  'import sys, json; print(json.load(sys.stdin).get("Self", {}).get("DNSName", "").rstrip("."))')
dns_short=${dns_full%%.*}

cat <<EOF

  ┌──────────────────────────────────────────────────────────────────┐
  │  IntelligenceOS Console — exposed on your tailnet                │
  ├──────────────────────────────────────────────────────────────────┤
  │  Token:  $token_status
  │  Target: http://127.0.0.1:$PORT  (UI server — keep it running)
  │                                                                  │
  │  Short URL  (if MagicDNS enabled on peer):                       │
  │    https://$dns_short/#token=$current_token
  │                                                                  │
  │  Full URL  (always works):                                       │
  │    https://$dns_full/#token=$current_token
  └──────────────────────────────────────────────────────────────────┘

  Open that URL on any device on your tailnet. The token stashes into
  that browser's localStorage and clears from the URL bar; subsequent
  visits just use https://$dns_short/ with no token.

  If the UI server isn't running yet, start it with:
    ./run-ui.sh

  To stop exposing:
    tailscale serve reset
EOF
