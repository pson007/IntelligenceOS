/**
 * TradingView → Bridge router.
 *
 * Flow:
 *   1. Receive POST from TradingView with JSON body containing `auth_token`.
 *   2. Verify the token matches WEBHOOK_AUTH_TOKEN.
 *   3. Strip the token, HMAC-SHA256 sign the rest with BRIDGE_SHARED_SECRET.
 *   4. Forward to BRIDGE_URL (Cloudflare Tunnel → local FastAPI bridge).
 *   5. Return whatever the bridge returns.
 *
 * The Worker uses the Web Crypto API (no Node `crypto`) — same algorithm as
 * Python's hmac.new(secret, body, sha256).hexdigest(), so signatures match.
 */

export interface Env {
  WEBHOOK_AUTH_TOKEN: string;     // secret — set via `wrangler secret put`
  BRIDGE_SHARED_SECRET: string;   // secret — set via `wrangler secret put`
  BRIDGE_URL: string;             // var — set in wrangler.jsonc
}

const enc = new TextEncoder();

async function hmacSha256Hex(secret: string, body: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    enc.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(body));
  return Array.from(new Uint8Array(sig))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    // Health check — handy when verifying tunnel/Worker is reachable.
    if (request.method === "GET" && url.pathname === "/health") {
      return Response.json({ ok: true });
    }

    if (request.method !== "POST" || url.pathname !== "/webhook") {
      return new Response("Not found", { status: 404 });
    }

    const raw = await request.text();
    let payload: Record<string, unknown>;
    try {
      payload = JSON.parse(raw);
    } catch {
      return new Response("Invalid JSON", { status: 400 });
    }

    // Constant-time comparison of the inbound token. (Worker doesn't ship a
    // dedicated timing-safe comparator, so we DIY with same-length XOR.)
    const provided = String(payload.auth_token ?? "");
    if (!constantTimeEq(provided, env.WEBHOOK_AUTH_TOKEN)) {
      return new Response("Unauthorized", { status: 401 });
    }

    // Strip the inbound token before forwarding — the bridge has no need for it
    // and we don't want it sitting in any downstream logs.
    const { auth_token: _t, ...clean } = payload;
    const cleanBody = JSON.stringify(clean);
    const signature = await hmacSha256Hex(env.BRIDGE_SHARED_SECRET, cleanBody);

    const upstream = await fetch(env.BRIDGE_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Bridge-Signature": `sha256=${signature}`,
      },
      body: cleanBody,
    });

    // Pass through the bridge's response so Pine Script alert logs reflect
    // real status codes (200 = trade placed, 4xx/5xx = something went wrong).
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: { "Content-Type": "application/json" },
    });
  },
};

function constantTimeEq(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}
