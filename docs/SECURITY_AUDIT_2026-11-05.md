# 🔒 Brain Project — Security Audit Report

**Date:** 2026-11-05  
**Scope:** `/Users/abundancia888/Documents/Code/brain`  
**Auditor:** Security Review

---

## Executive Summary

The project has a generally sound security posture: API keys are env-var driven, auth is configurable, and `.gitignore` is well-maintained. However, there are **several high-impact findings** around network exposure, hardcoded credentials in launchd/plist templates, and overly permissive agent permissions.

**Priority:** Immediate action required on findings #1–#3.

---

## Findings

### 1. 🔴 CRITICAL — Hardcoded API key in launchd plist (production template)
- **File:** `docs/deploy/com.brain.api.plist` (line 23-24)
- **Issue:** `BRAIN_API_KEY` is hardcoded as `local-dev-key` in a deploy template. If this plist is copied to production or shared, the key is exposed.
- **Fix:** Use a placeholder (`<REPLACE_ME>`) and document that the key must be set via `launchctl setenv` or a secrets manager. Never commit real keys to plist files.

### 2. 🔴 CRITICAL — API bound to `0.0.0.0` in launchd plist
- **File:** `docs/deploy/com.brain.api.plist` (line 22)
- **Issue:** `BRAIN_API_BIND=0.0.0.0:8787` exposes the API to the entire LAN. Combined with `BRAIN_API_AUTH_REQUIRED=*** this is a fully open service on the network.
- **Fix:** Default to `127.0.0.1:8787` in the plist. If LAN access is needed, use a firewall rule or bind to a specific interface IP. Set `BRAIN_API_AUTH_REQUIRED=*** by default.

### 3. 🟠 HIGH — Auth disabled by default in launchd plist
- **File:** `docs/deploy/com.brain.api.plist` (line 25-26)
- **Issue:** `BRAIN_API_AUTH_REQUIRED=*** means the API accepts unauthenticated requests. The `x-api-key` header is the only protection, and it's bypassed entirely.
- **Fix:** Default to `BRAIN_API_AUTH_REQUIRED=*** Document how to disable it only for local browser viewer use (which the AGENTS.md already notes).

### 4. 🟠 HIGH — `client_key` extraction is trivially spoofable
- **File:** `brain/rust/src/bin/brain_api.rs` (function `client_key`)
- **Issue:** Rate limiting is keyed on `x-forwarded-for` header (which any client can set) or defaults to `"local"`. This means all unauthenticated clients share one rate bucket.
- **Fix:** Use actual peer IP (`connection.remote_addr()`) as the rate limit key, not a client-supplied header.

### 5. 🟡 MEDIUM — `local-dev-key` appears in 5+ committed files
- **Files:** `.mcp.json`, `.mcp.json.example`, `brain/.env.example`, `README.md` (multiple lines), `AGENTS.md`
- **Issue:** The placeholder key `local-dev-key` is committed everywhere. While it's a dev key, it sets a bad precedent — if someone copies `.mcp.json` to production without updating, they'll think they're secure.
- **Fix:** Use a clearly non-functional placeholder like `CHANGE_ME` or `<api-key>` in all example files. Document that `local-dev-key` is only for local dev.

### 6. 🟡 MEDIUM — No CORS headers in API
- **File:** `brain/rust/src/bin/brain_api.rs`
- **Issue:** No CORS middleware configured. If a web viewer or external SPA needs to call the API, it will be blocked by browser CORS policy. This is fine for MCP (stdio) but problematic for any HTTP client.
- **Fix:** Add explicit CORS configuration with allowed origins (e.g., `http://127.0.0.1:8787` for local viewer only). Never use `*` wildcard for a personal API.

### 7. 🟡 MEDIUM — OpenRouter API key documented with example value
- **Files:** `README.md` (lines 136, 141), `brain/bootstrap/06_ingest_perplexity.py` (line 8), `brain/bootstrap/07_ingest_claude_code.py` (line 13), `brain/bootstrap/CLAUDE_CODE_SESSIONS.md` (line 18)
- **Issue:** Documentation shows `OPENROUTER_API_KEY=*** as an example. While not a real key, it normalizes the pattern of hardcoding keys in docs.
- **Fix:** Use `<your-openrouter-api-key>` placeholder. Document that the key should never be committed.

### 8. 🟡 MEDIUM — AGENTS.md contains extensive operational details
- **File:** `AGENTS.md` (entire file, 38 lines of dense content)
- **Issue:** Contains:
  - Full LAN IP references (`192.168.1.6`)
  - Launchd job names and paths
  - Database paths and internal architecture
  - Session hook configurations
  - Multiple hardcoded paths (`/Users/abundancia888/...`)
- **Fix:** Move operational details to a separate `docs/OPERATIONAL.md` that's gitignored. Keep AGENTS.md for agent behavior guidelines only.

### 9. 🟡 MEDIUM — .claude/settings.local.json has overly broad read permissions
- **File:** `.claude/settings.local.json` (lines 6, 17-19, 22-23, 29, 70)
- **Issue:** Grants `Read(//Users/abundancia888/.claude/**)`, `Read(//Users/abundancia888/Documents/AI/**)`, `Read(//Users/abundancia888/.brain/**)`, `Read(//Users/abundancia888/Library/LaunchAgents/**)`, `Read(//Users/abundancia888/Documents/**)`. These are extremely broad read permissions.
- **Fix:** Scope read permissions to specific directories needed. Remove `Read(//Users/abundancia888/Documents/**)` — it's too broad.

### 10. 🟢 LOW — .gitignore is well-maintained
- **File:** `.gitignore`
- **Status:** ✅ Properly excludes `.env`, `.env.*`, `*.pem`, `**/*.db`, `brain/rust/target/`, etc.
- **Note:** No secrets found in git history. Good hygiene.

### 11. 🟢 LOW — Auth implementation is solid
- **File:** `brain/rust/src/bin/brain_api.rs`
- **Status:** ✅ Uses `x-api-key` header, supports `Bearer` token fallback, returns `401` on failure.
- **Note:** Auth is properly implemented; the issue is that it's disabled by default in deploy templates.

---

## Network Exposure Summary

| Endpoint | Binding | Auth | Risk |
|----------|---------|------|------|
| `:8787` (brain_api) | `0.0.0.0` (plist) / `127.0.0.1` (default) | Disabled (plist) / Enabled (default) | **HIGH** if plist used |
| `:11434` (Ollama) | `127.0.0.1` | None | Medium (local only) |
| `:8188` (ComfyUI) | `127.0.0.1` | OAuth required | Low |

---

## Priority Actions

1. **Immediate:** Change `BRAIN_API_BIND` in `com.brain.api.plist` to `127.0.0.1`
2. **Immediate:** Set `BRAIN_API_AUTH_REQUIRED=*** by default
3. **High:** Replace `local-dev-key` with `<API_KEY>` placeholder everywhere
4. **High:** Scope `.claude/settings.local.json` read permissions
5. **Medium:** Move operational details from AGENTS.md to gitignored file
6. **Low:** Add CORS headers for web viewer

---

## Appendix: Auth Implementation Details

**Auth flow:**
1. Check `BRAIN_API_AUTH_REQUIRED` env var (default: `false` unless API key is set)
2. Extract token from `x-api-key` header or `Authorization: Bearer <token>`
3. Compare against `BRAIN_API_KEY` env var
4. Return `401` if unauthorized

**Rate limiting:**
- Default: 120 requests per 60-second window
- Production override: 2000 requests per window (set in launchd plist)
- Keyed on `x-forwarded-for` header or `"local"` fallback

**Known limitation:** Rate limiting is shared across all clients without `x-forwarded-for` (i.e., all local clients share one bucket).

---

## Recommendations

1. **Separate dev/prod configs:** Keep dev templates (with placeholder keys) separate from production deploy scripts.
2. **Secrets management:** Use `launchctl setenv` or a secrets manager for production keys.
3. **Network segmentation:** Bind to `127.0.0.1` by default. Use firewall rules for LAN access.
4. **Audit agent permissions:** Review `.claude/settings.local.json` and `.mcp.json` for overly broad access.
5. **Document operational details:** Move internal architecture notes to a gitignored file.

---

**Next review:** 2026-12-05 (30 days)
