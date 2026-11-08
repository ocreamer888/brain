# Run Brain API With API Key

This file shows how to run `brain_api` with authentication enabled.

## 1) Start server with API key required

From repo root:

```bash
cd /Users/macm1air/Documents/AI
BRAIN_API_BIND=127.0.0.1:8787 \
BRAIN_API_AUTH_REQUIRED=true \
BRAIN_API_KEY=<your-own-secret> \
./brain/rust/target/debug/brain_api
```

If you prefer `cargo run`:

```bash
cd /Users/macm1air/Documents/AI
BRAIN_API_BIND=127.0.0.1:8787 \
BRAIN_API_AUTH_REQUIRED=true \
BRAIN_API_KEY=<your-own-secret> \
cargo run --manifest-path brain/rust/Cargo.toml --bin brain_api
```

## 2) Test endpoint without key (should fail)

```bash
curl -i -X POST "http://127.0.0.1:8787/v1/search_index" \
  -H "content-type: application/json" \
  -d '{"query":"code","n":5}'
```

Expected: `401 Unauthorized`.

## 3) Test endpoint with key (should pass)

```bash
curl -i -X POST "http://127.0.0.1:8787/v1/search_index" \
  -H "content-type: application/json" \
  -H "x-api-key: <your-own-secret>" \
  -d '{"query":"code","n":5}'
```

Expected: `200 OK` + JSON results.

## 4) Viewer note

**Out of date as of the 2026-11-05 security fix — corrected here, not restored.** The server
used to inject `window.__BRAIN_API_KEY__` into `index.html` on every request, which meant anyone
who could load the page got the live key handed to them for free, auth or no auth. It now only
injects the key when `BRAIN_API_AUTH_REQUIRED=0` (today's documented loopback/LAN-dev posture).

**With auth enabled, the viewer does NOT work yet** — its own fetches get `401` until a real
login/session flow exists (not built; tracked as a known gap, see
`docs/SECURITY_AUDIT_2026-11-05.md`). SSE (`/v1/stream`) still accepts the key via `?key=` query
param since `EventSource` can't send custom headers, but that's moot while the page itself can't
authenticate its other calls.

## 5) Stop process on port 8787

```bash
lsof -nP -iTCP:8787 -sTCP:LISTEN
kill <PID>
```
