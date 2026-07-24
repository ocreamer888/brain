# Brain cross-cutting integration gaps — implementation plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close the cross-cutting verification gaps between Rust `brain_api`, Python `api_client` / MCP, optional `BRAIN_BACKEND=python`, hooks, and LLM calls so regressions surface in CI or one-command local smoke, not only in production.

**Architecture:** Add **small, explicit smoke layers** (scripts + a few pytest integration tests) that sit *above* existing unit tests: one HTTP round-trip against a real or test-spawned `brain_api`, one MCP stdio handshake against `python -m brain.mcp.server`, optional matrix for `BRAIN_BACKEND`, optional OpenRouter canary behind env flags. Keep unit tests fast; gate heavy tests with `pytest.mark.integration` or env `BRAIN_RUN_INTEGRATION=1`.

**Tech Stack:** Python 3.13+ (project uses `python3`), pytest, `urllib` / `httpx` (pick one and stay consistent with repo), Rust `cargo test`, Axum `brain_api` (`127.0.0.1:8787` default per `brain/rust/src/bin/brain_api.rs`), FastMCP (`mcp>=1.0.0` in `brain/requirements.txt`), GitHub Actions (extend `.github/workflows/brain-rust-onnx.yml` or add a new workflow file under `.github/workflows/`).

---

## Decisions required before implementation (do not guess)

Answer these in the PR or session notes before merging; the plan branches on them.

1. **Golden-path backend for automated smoke:** Should the default integration smoke assume `BRAIN_BACKEND=api` (MCP → `api_client` → Rust) only, or must CI also run a second job with `BRAIN_BACKEND=python` (MCP → `brain.core.memory` + Chroma)?  
   - **Why we need this:** Avoid building two parallel CI pipelines if you are deprecating one path.

2. **OpenRouter in CI:** Do you want any automated job that calls OpenRouter (requires `OPENROUTER_API_KEY` as a GitHub Actions secret), or keep LLM verification **manual / nightly only**?  
   - **Why we need this:** Cost, flake risk, and secret handling differ.

Until (1) is answered, implement **Task A (HTTP smoke)** against `api` mode first; add the `python` matrix job only if you confirm both paths must stay first-class.

---

### Task A: HTTP smoke — live `brain_api` round-trip

**What:** A script or pytest module that performs `GET /health`, then `POST /save`, then `POST /search` using the same URL and headers as production (`BRAIN_API_URL`, optional `BRAIN_API_KEY` in `brain/api_client.py`).

**Why:** Unit tests mock `_request`; Rust tests use in-process Axum. TCP + JSON + auth headers can still fail in real deployments.

**Files:**

- Create: `brain/tests/integration/test_brain_api_http_smoke.py` (or `brain/tools/smoke_brain_api.py` if you prefer non-pytest; prefer pytest + `@pytest.mark.integration` for discoverability).
- Modify: `docs/BRAIN.md` (add “Integration smoke” subsection with exact commands) — only if you already document runbooks there; otherwise skip doc per project preference.
- Modify (optional): `.github/workflows/brain-integration-smoke.yml` **new file** — run after `cargo build --bin brain_api` (exact cargo flags to match your release build).

**Step 1: Write the failing test (skeleton)**

```python
import os
import pytest
import urllib.error
import urllib.request
import json

pytestmark = pytest.mark.integration


def _base():
    return os.environ.get("BRAIN_API_URL", "http://127.0.0.1:8787").rstrip("/")


def test_brain_api_health_save_search_roundtrip():
    if os.environ.get("BRAIN_RUN_INTEGRATION", "").strip().lower() not in ("1", "true", "yes", "on"):
        pytest.skip("set BRAIN_RUN_INTEGRATION=1 and start brain_api")
    # GET /health
    # POST /save with unique content
    # POST /search with query substring; assert hit contains saved content
    raise NotImplementedError
```

**Step 2: Run test — expect fail**

Run: `BRAIN_RUN_INTEGRATION=1 python3 -m pytest brain/tests/integration/test_brain_api_http_smoke.py -v`  
Expected: `NotImplementedError` or skip if env not set.

**Step 3: Implement minimal round-trip** using `urllib.request` (already used in `brain/api_client.py`) so behavior matches production client.

**Step 4: Run test with server**  
Prerequisite: start `brain_api` on `127.0.0.1:8787` (same default bind as `brain/rust/src/bin/brain_api.rs:156`).  
Expected: PASS.

**Step 5: Commit**  
Message example: `test(brain): add optional brain_api HTTP integration smoke`

---

### Task B: MCP stdio smoke — process + handshake

**What:** Spawn `python3 -m brain.mcp.server` as subprocess with stdio pipes; complete MCP **initialize** (and optionally `tools/list`) per the MCP spec your installed `mcp` package expects.

**Why:** `brain/tests/test_mcp.py` only checks imports and attributes; it does not prove stdio transport, JSON-RPC framing, or `sys.path` shadowing fixes in `brain/mcp/server.py:12-29`.

**Files:**

- Create: `brain/tests/integration/test_mcp_stdio_smoke.py`
- Modify: none in core until test forces a fix.

**Step 1: Read the MCP Python SDK** in your environment (after `pip install -r brain/requirements.txt`) to copy the **exact** client bootstrap pattern (do not invent JSON-RPC shapes). If the SDK exposes `stdio_client` / `ClientSession`, use that.

**Step 2: Write failing test** that spawns subprocess and expects a successful `initialize` response.

**Step 3: Run**  
`BRAIN_RUN_INTEGRATION=1 python3 -m pytest brain/tests/integration/test_mcp_stdio_smoke.py -v`  
Expected: FAIL until handshake implemented.

**Step 4: Implement handshake**; mock backend: set `BRAIN_BACKEND=api` and point `BRAIN_API_URL` to a **mock HTTP server** *or* run `brain_api` in fixture — choose one to avoid network flakiness. Document choice in test module docstring.

**Step 5: Commit**

---

### Task C: Dual-backend parity (conditional on decision #1)

**What:** If **both** `api` and `python` must remain first-class: add a second CI job (or parametrized pytest) that runs the **same semantic smoke** (save → search → visible hit) under each mode.

**Why:** MCP branches in `brain/mcp/server.py` (e.g. `search_brain` uses `py_search` vs `api_search`). Divergence only shows up when both paths are exercised.

**Files:**

- Modify: `brain/tests/integration/test_brain_api_http_smoke.py` OR create `test_mcp_backend_matrix.py`
- Modify: CI workflow(s) under `.github/workflows/`

**Step 1:** Parametrize `BRAIN_BACKEND` in integration tests; skip `python` mode if Chroma deps or model weights are missing (explicit skip message).

**Step 2:** Document required env for `python` mode (Chroma path, embedder) by reading `brain/core/memory.py` and `brain/config.py` — **read those files** when implementing; do not assume env var names.

**Step 3: Commit**

If decision #1 says **api only**, cancel Task C and add a single comment in `brain/mcp/server.py` or `docs/BRAIN.md` stating `python` mode is best-effort / manual QA only.

---

### Task D: Python path + real Chroma / embedder (optional CI lane)

**What:** One integration test that runs with `BRAIN_BACKEND=python`, uses **real** `PersistentClient` (temp dir) and the real embedder **or** documents a `BRAIN_SKIP_HEAVY_EMBEDDER=1` skip when weights unavailable.

**Why:** Current embedder tests patch `_model` in `brain/tests/test_embedder.py`; production `python` mode can break without failing CI.

**Files:**

- Create: `brain/tests/integration/test_python_backend_chroma_smoke.py`
- Modify: `brain/requirements.txt` only if a missing test dependency is discovered while reading imports.

**Step 1:** Read `brain/core/embedder.py` and `brain/core/memory.py` to list required env and side effects.

**Step 2:** Write test; default skip unless `BRAIN_RUN_PYTHON_CHROMA_INTEGRATION=1`.

**Step 3: Commit**

---

### Task E: OpenRouter canary (conditional on decision #2)

**What:** If allowed: single test `test_openrouter_summarizer_reachable` that calls `_openrouter_chat` once with `max_tokens` minimal, gated by `OPENROUTER_API_KEY` and `BRAIN_RUN_OPENROUTER_CANARY=1`.

**Why:** Catches auth, model string, and JSON contract drift without running full summarization pipelines.

**Files:**

- Create: `brain/tests/integration/test_openrouter_canary.py`
- Modify: `.github/workflows/*` **only** if you add repository secrets; otherwise document manual run in plan follow-up.

**Step 1:** Read `brain/core/summarizer.py` and `brain/config.py` for model id and URL constants.

**Step 2:** Implement minimal call; assert non-empty string response.

**Step 3: Commit**

If decision #2 is **no CI secret**, keep test manual-only (skip in CI always).

---

### Task F: Hook contract fixtures — stdin JSON golden files

**What:** Add **golden JSON** files under `brain/tests/fixtures/hooks/` representing minimal valid stdin for `brain/hooks/session_end.py` (and `session_start` if applicable). Add a test that feeds each file to the **pure functions** you extract or to `runpy`/`subprocess` as appropriate — prefer testing **functions** over executing the whole `if __name__` block if the hook file runs on import.

**Why:** Hooks read stdin and filesystem; today coverage is patch-heavy (`brain/tests/test_session_end_export.py`, `brain/tests/test_session_end_summary.py`). Version drift in Claude Code payload shape needs visible fixtures.

**Files:**

- Create: `brain/tests/fixtures/hooks/session_end_minimal.json` (exact shape: read `brain/hooks/session_end.py:93-105` and match keys the code reads).
- Create: `brain/tests/test_hook_stdin_contracts.py`
- Modify: `brain/hooks/session_end.py` **only if** you must extract `save_session_summary` / parsing into testable functions without executing subprocess ingest — keep diff minimal.

**Step 1:** Read `brain/hooks/session_end.py` full file; list every `context.get(...)` key used.

**Step 2:** Write fixture JSON; test that parsing + `save_session_summary` path runs with mocks (reuse patterns from `brain/tests/test_session_end_summary.py`).

**Step 3: Commit**

---

### Task G: Rust CLI binaries — thin `#[cfg(test)]` or integration tests

**What:** Add at least **one** test per critical binary entrypoint: argument parsing and “happy exit” with env pointing at temp DB. Binaries currently report **0 tests** in `cargo test` output for `brain_post_tool_use`, `brain_session_end`, etc.

**Why:** Production runs bins; library tests do not cover CLI wiring.

**Files (examples — adjust after reading each `src/bin/*.rs`):**

- Modify: `brain/rust/src/bin/brain_post_tool_use.rs` — add `#[cfg(test)] mod tests { ... }` with clap/args parsing test if clap is used; else subprocess `cargo run --bin ... -- --help` from integration test in `brain/rust/tests/` (create `brain/rust/tests/cli_smoke.rs` if integration style preferred).

**Step 1:** List bins: `ls brain/rust/src/bin/*.rs`.

**Step 2:** For each bin, read `main` and identify testable pure functions vs side effects.

**Step 3:** Add smallest test that fails on flag regression.

**Step 4:** `cd brain/rust && cargo test`  
Expected: new tests pass locally; document sandbox: `cargo test` may need writable `CARGO_TARGET_DIR` (Cursor sandbox issue with `libsqlite3-sys`).

**Step 5: Commit**

---

### Task H: CI / sandbox parity for Rust

**What:** Document in `docs/BRAIN.md` or `brain/rust/README.md` (if exists; create only if missing and team wants it) that `cargo test` requires a writable Cargo target dir. Optionally set `CARGO_TARGET_DIR=$PWD/target` in CI workflow env.

**Why:** Prevents false “Rust broken” signals in sandboxed agents and some CI caches.

**Files:**

- Modify: `.github/workflows/brain-rust-onnx.yml` or new workflow — add `env: CARGO_TARGET_DIR: ${{ github.workspace }}/brain/rust/target` if compatible with `rust-cache`.

**Step 1:** Read current workflow file; merge env without breaking `Swatinem/rust-cache@v2` workspace rules.

**Step 2: Commit**

---

## Execution order (recommended)

1. Task A (HTTP smoke) — highest leverage, unblocks real MCP+API verification.  
2. Task B (MCP stdio) — validates the glue Cursor uses.  
3. Task F (hook fixtures) — low dependency on external services.  
4. Task G (Rust bins) — parallelizable with F.  
5. Task H (CI/sandbox docs) — quick win.  
6. Task C / D / E — only after decisions #1 and #2.

---

## Testing commands (summary)

```bash
# Fast suite (existing)
python3 -m pytest brain/tests brain/bootstrap/tests -q
cd brain/rust && cargo test

# Integration (local)
# Terminal 1:
# run brain_api per your standard command (read docs/BRAIN.md or brain/rust README)
# Terminal 2:
BRAIN_RUN_INTEGRATION=1 python3 -m pytest brain/tests/integration/ -v
```

---

**Plan complete and saved to `docs/plans/2026-04-11-brain-cross-cutting-gap-closures.md`. Two execution options:**

**1. Subagent-Driven (this session)** — dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Parallel Session (separate)** — open a new session with superpowers:executing-plans, batch execution with checkpoints.

**Which approach?**

Also please answer **decision #1** (api-only vs api+python CI) and **decision #2** (OpenRouter in CI or manual-only) so implementation does not guess.
