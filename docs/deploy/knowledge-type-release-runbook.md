# Knowledge Memory Type — Merge + Studio Deploy Runbook

**Status (2026-11-08): historical.** `e40bd67` is already on `main` and the
Studio `brain_api` has been rebuilt/redeployed many times since (most
recently tonight). Steps §1–§6 below describe how that merge and deploy were
done; kept for the record and for the next ship of similar shape, not as an
outstanding TODO. Recovered from an abandoned agent-dispatch worktree that
was never committed at the time.

Ship: `feat(knowledge): first-class knowledge memory type + adaptive grounding`
(commit `e40bd67` on `feature/durable-entity-linking`).
Spec: `docs/superpowers/specs/2026-08-06-knowledge-type-design.md`.

This runbook covers merging that branch to `main` and deploying the rebuilt
`brain_api` to the Mac Studio launchd service (`com.brain.api`). It assumes the
general deploy mechanics in `docs/deploy/README.md` — read that first if you
haven't deployed `brain_api` before; this doc only adds the steps specific to
the knowledge-type ship.

---

## 0. Pre-merge checklist

Run from repo root (`brain/`).

- [ ] Python suite green:
  ```bash
  .venv/bin/python -m pytest brain/tests/ -q
  ```
  Expect all passed (a handful of `s` skips are normal — integration tests
  that need a live Ollama/live hook tree).

- [ ] Rust suite green:
  ```bash
  cd brain/rust && cargo test
  ```
  Expect 0 failed. **Note:** if your shell exports `BRAIN_LLM_PROVIDER=ollama`
  (this Mac Studio's normal dev env does), the debug-profile integration test
  `user_prompt_submit_hook_integration` can spuriously panic on startup with
  `Cannot drop a runtime in a context where blocking is not allowed` — a
  known `reqwest::blocking` + `#[tokio::main]` interaction that only
  reproduces in **debug** builds, not release. It is pre-existing
  (`brain/rust/src/summarizer.rs::OllamaClient::new`, untouched by this
  ship) and does not affect the release binary — confirmed by running
  `target/release/brain_api` directly with the same env and an empty DB
  (starts clean, `/health` returns 200). If you hit it, rerun with those
  vars unset to confirm it's this artifact, not a real regression:
  ```bash
  env -u BRAIN_LLM_PROVIDER -u OLLAMA_URL -u OLLAMA_MODEL cargo test
  ```

- [ ] `test_deploy_parity.py` still passes/skips (SYNC_SET includes
  `brain/ingest/payloads.py` as of this ship — the committed hooks
  (`session_end.py` eager import, `post_tool_use.py` flush path) hard-import
  `forbid_knowledge_type`/`with_ingest_tag` from it; without it in the live
  tree, hooks `ImportError` on the first Stop/PostToolUse event).

- [ ] Fresh-clone sanity: no committed file imports an uncommitted module.
  (Verified for this ship: `brain/core/session_ingest.py` and
  `brain/hooks/post_tool_use.py` import only `brain.ingest.payloads`, never
  `brain.ingest.transcript` — the groundedness work's ingest module is not
  in this commit and nothing here depends on it.)

- [ ] Calibrated constants + benchmark numbers (fill in from the calibration
  agent before merging):

  | Constant | Spec default | Calibrated value | Source |
  | --- | --- | --- | --- |
  | `K_BASE` | 0.06 | _TBD_ | _TBD_ |
  | `K_PROJ` | 0.08 | _TBD_ | _TBD_ |
  | `K_CLOSE_MAX` | 0.10 | _TBD_ | _TBD_ |
  | `KNOWLEDGE_TAU_CLOSE` | 0.35 distance | _TBD_ | _TBD_ |
  | `KNOWLEDGE_TAU_FAR` | 0.55 distance | _TBD_ | _TBD_ |
  | Clamp ceiling | 1.22 | _TBD_ | _TBD_ |

  | Benchmark | Target | Result | Notes |
  | --- | --- | --- | --- |
  | Knowledge twin outranks fact twin (unit) | pass | _TBD_ | `brain::tests::knowledge_twin_outranks_fact_twin` |
  | Closeness smoothstep bounds (unit) | pass | _TBD_ | `brain::tests::knowledge_closeness_smoothstep_bounds` |
  | Live grounding fixture: close doc chunk → `hard` | pass | _TBD_ | see §4 smoke test 1 |
  | Live grounding fixture: unrelated query → no line | pass | _TBD_ | see §4 smoke test 2 |
  | Live grounding fixture: mid-distance → `soft` | pass | _TBD_ | see §4 smoke test 3 |
  | Retrieval latency p95 (unchanged from pre-ship baseline) | ≤ baseline + 10% | _TBD_ | `/search` timing in logs |

  **Do not merge until this table is filled in and every row passes.**

- [ ] Reviewer sign-off on the diff (17 files, ~1000 lines — see `git show
  e40bd67 --stat`).

---

## 1. Merge to main

From the repo root, with the pre-merge checklist green:

```bash
git checkout main
git pull origin main
git merge --no-ff feature/durable-entity-linking
git push origin main
```

If `main` has moved since the branch was cut, rebase or merge `main` into
the feature branch first, rerun the full checklist (§0), then retry the
merge above.

---

## 2. Sync the live hook tree

The Claude Code hooks run from `$BRAIN_LIVE_HOOK_TREE` (default
`~/Documents/AI`), not from this repo — see the docstring in
`brain/tests/test_deploy_parity.py`. Copy every `SYNC_SET` file:

```bash
live_tree="${BRAIN_LIVE_HOOK_TREE:-$HOME/Documents/AI}"
for f in \
  brain/api_client.py \
  brain/ingest/entity_extractor.py \
  brain/ingest/__init__.py \
  brain/ingest/fact_curator.py \
  brain/hooks/spool.py \
  brain/core/memory.py \
  brain/ingest/payloads.py \
; do
  cp "$f" "$live_tree/$f"
done

# Verify byte-identical
.venv/bin/python -m pytest brain/tests/test_deploy_parity.py -v
```

All 7 `test_sync_set_matches_live_hook_tree` cases should pass (or all skip
together if `$live_tree` doesn't exist on this host).

---

## 3. Rebuild the release binary

```bash
cd brain/rust
cargo build --release --bin brain_api
```

(If you also changed the UI, run `bash brain/rust/ui/deploy.sh` instead —
it does `npm run build` + this cargo build + the launchctl restart + a
`/health` check in one step. Skip to §5 if you used it.)

---

## 4. Restart the supervised process

**macOS (launchd) — this Mac Studio:**

```bash
uid=$(id -u)
launchctl kickstart -k gui/$uid/com.brain.api
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8787/health   # expect 200
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8787/static/index.html  # expect 200
```

**Linux (systemd), if applicable elsewhere:**

```bash
sudo systemctl restart brain-api
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8787/health
```

If `AddrInUse` on a manual run — launchd/systemd is already supervising the
port; use the kickstart/restart command above, don't run the binary
directly. See `docs/deploy/README.md` § "Port 8787 conflicts" for the full
procedure.

---

## 5. Live smoke test

Use the MCP tools (`save_memory_tool`, `search_brain`) or `curl` directly
against `http://127.0.0.1:8787`. Below: MCP-tool form first, curl equivalent
in a comment.

### 5a. Ingest one sample doc as knowledge (idempotent)

```bash
python3 brain/tools/ingest_knowledge.py path/to/one-sample-doc.md \
  --project general --source obsidian
```

Confirm it logs chunks saved with `type=knowledge`. Re-run the same command
— it should add **zero** new rows (idempotent re-ingest, unchanged content
hash).

### 5b. Three-way grounding smoke

**Case 1 — close query → `hard`.** Search using text drawn directly from
the ingested doc (a phrase that should land inside `KNOWLEDGE_TAU_CLOSE`,
0.35 distance, of a `knowledge` chunk):

```
search_brain(query="<phrase copied verbatim from the ingested doc>")
```
```bash
# curl equivalent:
curl -s -X POST http://127.0.0.1:8787/search \
  -H 'content-type: application/json' \
  -d '{"query":"<phrase copied verbatim from the ingested doc>","n":10}'
```

Expect the tool output to end with:
```
Grounding: hard — the knowledge corpus covers this query. Prefer citing
knowledge hits...
```

**Case 2 — unrelated query → no grounding line.** Search for something with
no relation to the ingested doc (e.g. a nonsense phrase or an unrelated
topic):

```
search_brain(query="completely unrelated nonsense query xyzzy123")
```

Expect **no** `Grounding:` line at all in the output (distance beyond
`KNOWLEDGE_TAU_FAR`, 0.55, and no BM25 score lead).

**Case 3 — mid-distance → `soft`.** Search using a paraphrase that's
topically related to the doc but not a close phrase match (distance
between τ_close and τ_far, no BM25 keyword lead):

```
search_brain(query="<loose paraphrase, same topic, different wording>")
```

Expect:
```
Grounding: soft — corpus material is nearby. Prefer knowledge hits when
relevant; other memory types are fine.
```

If case 1 or 3 doesn't land in the expected bucket, the live ONNX embedder's
distance distribution differs from the fixture assumptions — retune
`KNOWLEDGE_TAU_CLOSE`/`KNOWLEDGE_TAU_FAR` in `brain/rust/src/brain.rs` and
`_TAU_CLOSE`/`_TAU_FAR` in `brain/mcp/server.py` (**must stay in sync** —
that's a doc'd invariant, not enforced by a shared constant) and repeat.

### 5c. `score` field present in `/search`

```bash
curl -s -X POST http://127.0.0.1:8787/search \
  -H 'content-type: application/json' \
  -d '{"query":"<any prior query>","n":3}' | python3 -m json.tool
```

Confirm every result object has a numeric `"score"` field (not just
`"distance"`). Its presence is what lets `grounding_hint` catch a BM25
keyword win that cosine distance alone would miss (§3 of the spec).

### 5d. Forbidden-writer guard, live

Trigger a normal Stop-hook session end or PostToolUse edit-group flush and
confirm nothing gets saved with `type=knowledge` — only deliberate
`ingest_knowledge.py` runs or explicit `memory_type=knowledge` MCP saves
should produce `knowledge` rows. Spot check:

```bash
curl -s http://127.0.0.1:8787/stats | python3 -c \
  "import sys,json; print(json.load(sys.stdin)['by_type'].get('knowledge'))"
```

Compare the count before/after a normal coding session — it should only
change when you deliberately ran `ingest_knowledge.py` or an explicit
`memory_type=knowledge` save, never from session-end recycling.

---

## 6. Rollback

If the smoke test fails, or `/health` doesn't come back after restart:

```bash
# 1. Revert the merge commit on main (find its SHA first: git log --oneline -5)
git checkout main
git revert -m 1 <merge-commit-sha>
git push origin main

# 2. Rebuild the release binary from the reverted tree
cd brain/rust
cargo build --release --bin brain_api

# 3. Restart the supervised process
launchctl kickstart -k gui/$(id -u)/com.brain.api
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8787/health   # expect 200
```

`brain.db` schema changes in this ship are additive only (new `Knowledge`
`MemoryType` variant, new metadata fields on existing tables) — no
destructive migration, so rollback does **not** require restoring from a DB
backup. Rows already saved as `type=knowledge` remain in the DB after
rollback; the reverted binary's `parse_memory_type` will not recognize
`"knowledge"` as a filter value going forward, but existing rows are inert
(not deleted, just unfiltered until you roll forward again).

If you also synced the live hook tree (§2) and need to fully roll back that
too, restore the pre-ship copies of the `SYNC_SET` files from your last
known-good backup or the prior commit:

```bash
live_tree="${BRAIN_LIVE_HOOK_TREE:-$HOME/Documents/AI}"
git show <pre-ship-sha>:brain/ingest/payloads.py > "$live_tree/brain/ingest/payloads.py" 2>/dev/null \
  || rm -f "$live_tree/brain/ingest/payloads.py"  # file didn't exist pre-ship
```
(`payloads.py` predates this ship — it already existed with
`with_ingest_tag` etc.; only `forbid_knowledge_type` is new. Don't delete the
file, just check out the pre-ship version if you need to roll back that far.)
