# Run Brain API With API Key

This file shows how to run `brain_api` with authentication enabled.

## 1) Start server with API key required

From repo root:

```bash
cd /Users/macm1air/Documents/AI
BRAIN_API_BIND=127.0.0.1:8787 \
BRAIN_API_AUTH_REQUIRED=true \
BRAIN_API_KEY=local-dev-key \
./brain/rust/target/debug/brain_api
```

If you prefer `cargo run`:

```bash
cd /Users/macm1air/Documents/AI
BRAIN_API_BIND=127.0.0.1:8787 \
BRAIN_API_AUTH_REQUIRED=true \
BRAIN_API_KEY=local-dev-key \
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
  -H "x-api-key: local-dev-key" \
  -d '{"query":"code","n":5}'
```

Expected: `200 OK` + JSON results.

## 4) Viewer note

The browser viewer at `http://127.0.0.1:8787/` works with auth enabled. The Rust server injects
`window.__BRAIN_API_KEY__` into `index.html` at serve time; the React app reads it and sends
`x-api-key` on every request. SSE (`/v1/stream`) accepts the key via `?key=` query param since
`EventSource` can't send custom headers.

**`BRAIN_API_AUTH_REQUIRED=0` is no longer needed for the viewer.**

## 5) Stop process on port 8787

```bash
lsof -nP -iTCP:8787 -sTCP:LISTEN
kill <PID>
```
