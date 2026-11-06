# Security Audit Report — Brain Project Rust Core Engine

**Date:** 2026-11-05  
**Scope:** `/Users/abundancia888/Documents/Code/brain/brain/rust/` (36 source files)  
**Methodology:** Manual source review of all API handlers, database operations, crypto usage, and error paths  

---

## Summary

| Severity | Count |
|----------|-------|
| Critical | 2 |
| High     | 5 |
| Medium   | 6 |
| Low      | 3 |

**Total findings:** 16

---

## Critical Findings

### V-01: API Key Injected into Client-Side JavaScript (Cross-Site Scripting / Credential Leak)

**Severity:** Critical  
**File:** `src/bin/brain_api.rs` (lines 389–420, `static_handler`)  
**Description:** The API key is embedded into `index.html` as a JavaScript variable (`window.__BRAIN_API_KEY__`), making it visible to anyone who loads the dashboard page. This key authenticates ALL API requests. Any XSS vulnerability in the dashboard (or a shared host) would expose the key.

```rust
let key_js = format!(
    "<script>window.__BRAIN_API_KEY__={};</script>",
    serde_json::to_string(&state.settings.api_key).unwrap_or_else(|_| "\"\"".to_string())
);
```

**Impact:** Complete API authentication bypass if XSS is present. Key visible in browser DevTools, network tab, and page source.

**Recommended Fix:** Remove client-side key injection. Have the dashboard page authenticate via a separate login flow, or use a short-lived session token. The API key should never leave the server process.

---

### V-02: Instance Switching Race Condition — No Atomic DB Path Swap

**Severity:** Critical  
**File:** `src/bin/brain_api.rs` (lines 1180–1250, `switch_instance`)  
**Description:** The active database path is read from `active_db_path` (an `Arc<Mutex<String>>`) and used to open a new Brain, but this read is NOT taken under the same lock as the registry update. Between reading the old path and updating the new one, concurrent requests can read stale data or write to a half-swapped state.

```rust
// Reads active_db_path WITHOUT holding registry lock
let active_db_path = self.active_db_path.lock().unwrap().clone();
// ... later ...
// Updates registry and active_db_path separately
```

**Impact:** Data corruption, memory leaks, or serving stale data during instance switches.

**Recommended Fix:** Hold the registry lock for the entire swap operation. Use an `Arc<RwLock<Brain>>` and swap the entire Arc atomically.

---

## High Findings

### V-03: No Authentication on Instance Management Endpoints

**Severity:** High  
**File:** `src/bin/brain_api.rs` (lines 1400–1600, instance handlers)  
**Description:** Endpoints like `/v1/instances` (create, switch, archive, unarchive, delete) do not call `authorize_and_rate_limit()`. Any client can create new instances, switch the active database, or delete instances without authentication.

**Impact:** Unauthorized instance creation, database switching, or data destruction.

**Recommended Fix:** Add `authorize_and_rate_limit()` to all instance management handlers.

---

### V-04: Unbounded `content` Field in Save Requests (DoS)

**Severity:** High  
**File:** `src/bin/brain_api.rs` (lines 687–750, `save` handler)  
**Description:** The `SaveRequest.content` field has no size limit. A malicious client can send arbitrarily large payloads (e.g., 100MB) to exhaust memory or disk.

```rust
struct SaveRequest {
    content: String,  // No max_length validation
    memory_type: String,
    ...
}
```

**Impact:** Denial of service via memory exhaustion.

**Recommended Fix:** Add a `max_content_length` check (e.g., 10KB) before processing. Reject with `413 Payload Too Large`.

---

### V-05: FTS Query Injection via Sanitization Bypass

**Severity:** High  
**File:** `src/store.rs` (lines 1376–1393, `sanitize_fts_query`)  
**Description:** The FTS query sanitizer strips special characters but allows alphanumeric, spaces, hyphens, and apostrophes. This permits FTS5 boolean operators (`AND`, `OR`, `NOT`) if they appear as words, enabling full-text search injection.

```rust
fn sanitize_fts_query(query: &str) -> String {
    query.chars().map(|c| {
        if c.is_alphanumeric() || c == ' ' || c == '-' || c == '\'' {
            c
        } else {
            ' '
        }
    }).collect::<String>()
    ...
}
```

**Impact:** Information disclosure via FTS5 injection (e.g., `NOT` operator to exclude results).

**Recommended Fix:** Whitelist only allowed characters. Strip or escape FTS5 operators (`AND`, `OR`, `NOT`, `phrase`, etc.).

---

### V-06: No Rate Limiting on `/save-batch`

**Severity:** High  
**File:** `src/bin/brain_api.rs` (lines 1300–1380, `save_batch`)  
**Description:** The batch save endpoint accepts a `Vec<SaveRequest>` with no limit on the array size. A client can send thousands of save operations in a single request, bypassing per-request rate limits.

```rust
struct SaveBatchRequest {
    items: Vec<SaveRequest>,  // No size limit
}
```

**Impact:** Rate limit bypass, database overload, DoS.

**Recommended Fix:** Add a maximum batch size (e.g., 100 items). Enforce rate limiting per item in the batch.

---

### V-07: SQLite Error Messages Leaked to Clients

**Severity:** High  
**File:** `src/store.rs` (multiple locations)  
**Description:** Database errors are propagated as `BrainError::Database(e.to_string())`, which includes the raw SQLite error message. SQLite errors can reveal table names, column names, constraint names, and internal query structure.

```rust
.map_err(|e| BrainError::Database(e.to_string()))?;
```

**Impact:** Information disclosure about database schema and internal structure.

**Recommended Fix:** Map SQLite errors to generic messages for client responses. Log detailed errors server-side only.

---

## Medium Findings

### V-08: Health Endpoint Exposes Bind Address Without Auth

**Severity:** Medium  
**File:** `src/bin/brain_api.rs` (lines 624–629, `health`)  
**Description:** The `/health` endpoint returns the bind address without any authentication. This can be used for reconnaissance.

```rust
async fn health(State(state): State<AppState>) -> Json<HealthResponse> {
    Json(HealthResponse {
        status: "ok",
        bind: state.bind_addr,  // Exposed without auth
    })
}
```

**Impact:** Information disclosure.

**Recommended Fix:** Add authentication to `/health` or restrict to localhost only.

---

### V-09: No Encryption at Rest for Sensitive Data

**Severity:** Medium  
**File:** `src/store.rs` (entire file)  
**Description:** The SQLite database stores memories, embeddings, and metadata in plaintext. No SQLCipher or other encryption at rest is used.

**Impact:** If the database file is stolen, all data is exposed.

**Recommended Fix:** Use SQLCipher or similar for encryption at rest. Alternatively, encrypt sensitive fields before storage.

---

### V-10: `file_path` Field Accepted Without Validation

**Severity:** Medium  
**File:** `src/bin/brain_api.rs` (lines 148–186, `SaveRequest`)  
**Description:** The `file_path` field is accepted from user input and stored directly. No validation for path traversal or absolute paths.

```rust
struct SaveRequest {
    #[serde(default)]
    file_path: Option<String>,
    ...
}
```

**Impact:** Potential path traversal if `file_path` is used elsewhere in the application.

**Recommended Fix:** Validate `file_path` to ensure it's a relative path within an allowed directory. Reject absolute paths and path traversal sequences (`../`).

---

### V-11: No Input Validation on `entity_name` in Link Entities

**Severity:** Medium  
**File:** `src/store.rs` (lines 900–970, `upsert_entity`, `link_memory_entities`)  
**Description:** Entity names are accepted with minimal validation. The `looks_like_secret` check is basic and may not catch all sensitive patterns.

```rust
if looks_like_secret(name) || normalize_entity_name(name).is_none() {
    continue;
}
```

**Impact:** Potential injection of sensitive data as entity names.

**Recommended Fix:** Strengthen secret detection. Add length limits and character whitelisting for entity names.

---

### V-12: Unbounded `ids` Vector in Delete Request

**Severity:** Medium  
**File:** `src/bin/brain_api.rs` (lines 258–266, `DeleteRequest`)  
**Description:** The `ids` field in `DeleteRequest` has no size limit. A client can request deletion of thousands of memories in a single request.

```rust
struct DeleteRequest {
    ids: Vec<String>,  // No size limit
}
```

**Impact:** Denial of service via excessive database operations.

**Recommended Fix:** Add a maximum ID count (e.g., 100). Process in batches if needed.

---

### V-13: Background Worker Opens New DB Connection Every 5 Seconds

**Severity:** Medium  
**File:** `src/bin/brain_api.rs` (lines 509–535)  
**Description:** The background worker spawns a new `MetadataStore` and opens a new SQLite connection every 5 seconds. This creates unnecessary resource churn.

```rust
tokio::spawn(async move {
    loop {
        let db_path = active_db_path.lock().unwrap().clone();
        if db_path != ":memory:" {
            let tick_path = db_path.clone();
            let tick = tokio::task::spawn_blocking(move || {
                let store = MetadataStore::open(&tick_path)?;  // New connection each time
                brain::worker::process_once(&store)
            })
            .await;
        }
        tokio::time::sleep(Duration::from_secs(5)).await;
    }
});
```

**Impact:** Resource waste, potential connection exhaustion under load.

**Recommended Fix:** Reuse a single connection or use a connection pool for the worker.

---

## Low Findings

### V-14: `eprintln!` Used for Error Logging (Potential Info Leak)

**Severity:** Low  
**File:** `src/bin/brain_api.rs` (multiple locations)  
**Description:** Error messages are logged to stderr via `eprintln!`, which may include sensitive information like database paths or internal state.

```rust
eprintln!("worker error (db_path={db_path}): {e}");
```

**Impact:** Information disclosure in logs.

**Recommended Fix:** Use a structured logging framework (e.g., `tracing`) with appropriate log levels. Redact sensitive fields.

---

### V-15: No TLS Enforcement

**Severity:** Low  
**File:** `src/bin/brain_api.rs` (line 445)  
**Description:** The server binds to `127.0.0.1:8787` by default. While this limits exposure to localhost, if the bind address is changed, there's no enforcement of TLS.

```rust
let bind = std::env::var("BRAIN_API_BIND").unwrap_or_else(|_| "127.0.0.1:8787".to_string());
```

**Impact:** Plaintext API key transmission if bound to a non-localhost address.

**Recommended Fix:** Enforce TLS when binding to non-localhost addresses. Add a `BRAIN_API_TLS_ENABLED` flag.

---

### V-16: No Audit Trail for Instance Management

**Severity:** Low  
**File:** `src/bin/brain_api.rs` (instance handlers)  
**Description:** Instance creation, switching, and deletion are not logged. There's no way to audit who changed the active instance.

**Impact:** Lack of accountability for administrative actions.

**Recommended Fix:** Log all instance management operations with timestamps and client identifiers.

---

## Recommendations Summary

### Immediate Actions (Critical/High)
1. **Remove client-side API key injection** — Move authentication to a server-side session or token exchange
2. **Add authentication to instance management endpoints** — All instance operations require auth
3. **Add content size limits** — Reject payloads >10KB with 413 status
4. **Add batch size limits** — Cap `/save-batch` at 100 items
5. **Fix instance switch race condition** — Use atomic swap with proper locking

### Short-Term (Medium)
6. **Sanitize FTS queries** — Whitelist allowed characters, strip FTS5 operators
7. **Redact SQLite errors** — Map to generic messages for clients, log details server-side
8. **Validate `file_path` input** — Reject absolute paths and traversal sequences
9. **Strengthen entity name validation** — Add comprehensive secret detection
10. **Add ID count limits** — Cap delete requests at 100 IDs

### Long-Term (Low)
11. **Implement encryption at rest** — Use SQLCipher or field-level encryption
12. **Enforce TLS** — Require TLS for non-localhost bindings
13. **Add structured logging** — Use `tracing` with redaction
14. **Add audit logging** — Log all administrative actions

---

## Methodology Notes

- **Scope:** All 36 Rust source files in `/Users/abundancia888/Documents/Code/brain/brain/rust/`
- **Excluded:** `/Users/abundancia888/Documents/Code/brain/brain/src/` (path does not exist)
- **Tools:** Manual source review, no automated scanning
- **Assumptions:** 
  - Server is bound to `127.0.0.1` (localhost only)
  - API key is the sole authentication mechanism
  - No network exposure beyond localhost

---

## Conclusion

The Brain project has several security issues ranging from critical (API key exposure, race conditions) to low (logging practices). The most urgent fixes are removing client-side API key injection and adding authentication to instance management endpoints. These should be addressed before any production deployment.
