use std::collections::HashMap;
use std::convert::Infallible;
use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use axum::body::Body;
use axum::extract::{Path, Query, State};
use axum::http::header::{self, HeaderValue};
use axum::http::{HeaderMap, Response, StatusCode};
use axum::response::sse::{Event, KeepAlive, Sse};
use axum::response::{IntoResponse, Redirect};
use axum::routing::{get, patch, post};
use axum::{Json, Router};
use futures_util::stream::Stream;
use futures_util::StreamExt;
use tokio::sync::broadcast;
use tokio_stream::wrappers::BroadcastStream;
use brain::brain::Brain;
use brain::config::{anthropic_api_key, brain_config_from_env, openrouter_api_key};
use brain::instances::{self, InstanceRegistry};
use brain::store::MetadataStore;
use brain::embedder::{embedder_from_env, EmbedderBackend};
use brain::summarizer::{AnthropicClient, OllamaClient, OpenRouterClient};
use brain::{
    BrainError, FeedbackEventType, FeedbackSource, Memory, MemorySource, MemoryType, SearchFilter,
};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

#[derive(Clone)]
struct AppState {
    bind_addr: String,
    settings: ApiSettings,
    limiter: Arc<Mutex<HashMap<String, ClientWindow>>>,
    memory_tx: broadcast::Sender<brain::MemoryEvent>,
    /// Single Brain (index + embedder) built once at boot and shared across
    /// requests. Behind a Mutex because rusqlite's Connection is `!Sync`.
    /// Replaces the old per-request `open_brain` that reloaded all embeddings
    /// and rebuilt the index on every call (~300ms each).
    brain: Arc<Mutex<Brain>>,
    /// Path to `~/.brain/instances.json` (or a temp override in tests).
    registry_path: PathBuf,
    /// Directory under which per-instance `<slug>/brain.db` files live.
    instances_root: PathBuf,
    /// In-memory instance registry, mutated on create/rename/archive/switch
    /// (Task 4) and persisted back to `registry_path` on change.
    registry: Arc<Mutex<InstanceRegistry>>,
    /// db_path of the currently active instance's Brain. Tracked separately
    /// from `registry` so the background worker (Task 5) can read it without
    /// locking the full registry.
    active_db_path: Arc<Mutex<String>>,
    /// Set while an instance switch is in flight, so concurrent requests can
    /// be rejected instead of racing the Brain swap (Task 5).
    switching: Arc<AtomicBool>,
}

#[derive(Clone, Debug)]
struct ApiSettings {
    api_key: String,
    auth_required: bool,
    rate_limit_max_requests: u32,
    rate_limit_window_seconds: u64,
}

#[derive(Clone, Debug)]
struct ClientWindow {
    count: u32,
    window_started: Instant,
}

#[derive(Debug, Serialize)]
struct ApiError {
    error: String,
}

#[derive(Debug, Serialize)]
struct HealthResponse {
    status: &'static str,
    bind: String,
}

#[derive(Debug, Deserialize)]
struct SaveRequest {
    content: String,
    memory_type: String,
    #[serde(default)]
    tags: Vec<String>,
    #[serde(default = "default_project")]
    project: String,
    session_id: Option<String>,
    source: Option<String>,
    #[serde(default)]
    file_path: Option<String>,
    #[serde(default)]
    title: Option<String>,
    /// RFC3339 timestamp representing the **ingest time**.
    /// Omit for live captures — the server uses `Utc::now()`.
    #[serde(default)]
    timestamp: Option<String>,
    // --- Fact-layer fields (all optional; ignored for non-fact memory types) ---
    /// ID of the parent episode from which this fact was extracted.
    #[serde(default)]
    parent_id: Option<String>,
    /// When the fact/event actually occurred (RFC3339). Distinct from `timestamp` (ingest time).
    #[serde(default)]
    event_time: Option<String>,
    /// Extraction confidence 0.0–1.0. Stored but NOT used in retrieval scoring until Phase 6.
    #[serde(default)]
    salience: Option<f64>,
    /// Extractor model + prompt version tag (e.g. "openrouter/claude-sonnet-4-5/v1").
    #[serde(default)]
    derived_from: Option<String>,
    /// Optional entity names to link (fact → entity "mentions" edges).
    #[serde(default)]
    entities: Option<Vec<String>>,
}

#[derive(Debug, Serialize)]
struct SaveResponse {
    id: String,
}

#[derive(Debug, Deserialize)]
struct SaveBatchRequest {
    items: Vec<SaveRequest>,
}

#[derive(Debug, Serialize)]
struct SaveBatchItemResult {
    index: usize,
    id: Option<String>,
    error: Option<String>,
}

#[derive(Debug, Serialize)]
struct SaveBatchResponse {
    accepted: usize,
    failed: usize,
    results: Vec<SaveBatchItemResult>,
}

#[derive(Debug, Deserialize)]
struct ListQuery {
    #[serde(default)]
    source: Option<String>,
    #[serde(default)]
    memory_type: Option<String>,
    #[serde(default)]
    project: Option<String>,
    #[serde(default = "default_list_limit")]
    limit: usize,
    #[serde(default)]
    offset: usize,
}

fn default_list_limit() -> usize {
    1000
}

#[derive(Debug, Serialize)]
struct ListItem {
    id: String,
    content: String,
    memory_type: String,
    source: String,
    project: String,
    timestamp: String,
    session_id: String,
}

#[derive(Debug, Serialize)]
struct ListResponse {
    total: usize,
    returned: usize,
    items: Vec<ListItem>,
}

#[derive(Debug, Deserialize)]
struct DeleteRequest {
    ids: Vec<String>,
}

#[derive(Debug, Serialize)]
struct DeleteResponse {
    deleted: usize,
}

#[derive(Debug, Deserialize)]
struct SearchRequest {
    query: String,
    #[serde(default = "default_n")]
    n: usize,
    project: Option<String>,
    memory_type: Option<String>,
    #[serde(default = "default_true")]
    exclude_superseded: bool,
    alpha: Option<f32>,
    #[serde(default)]
    graph_expand: bool,
}

#[derive(Debug, Serialize)]
struct SearchIndexRow {
    id: String,
    snippet: String,
    memory_type: String,
    project: String,
    timestamp: String,
    distance: f32,
    parent_id: Option<String>,
}

#[derive(Debug, Serialize)]
struct SearchIndexResponse {
    results: Vec<SearchIndexRow>,
}

#[derive(Debug, Deserialize)]
struct GetObservationsRequest {
    ids: Vec<String>,
}

#[derive(Debug, Deserialize)]
struct TimelineRequest {
    anchor_id: String,
    #[serde(default = "default_three")]
    before: u32,
    #[serde(default = "default_three")]
    after: u32,
}

fn default_three() -> u32 {
    3
}

#[derive(Debug, Deserialize)]
struct FeedbackRequest {
    event_type: String,
    #[serde(default)]
    memory_id: Option<String>,
    #[serde(default)]
    query: Option<String>,
    #[serde(default)]
    session_id: Option<String>,
    #[serde(default)]
    project: Option<String>,
    /// Defaults to `brain_api` when omitted.
    #[serde(default)]
    source: Option<String>,
    #[serde(default)]
    payload: Option<serde_json::Value>,
    #[serde(default)]
    idempotency_key: Option<String>,
}

#[derive(Debug, Serialize)]
struct FeedbackResponse {
    id: String,
}

fn default_project() -> String {
    "general".to_string()
}

fn default_n() -> usize {
    5
}

fn default_true() -> bool {
    true
}

#[derive(rust_embed::RustEmbed)]
#[folder = "static/"]
struct StaticAssets;

async fn eval_dashboard_handler() -> impl IntoResponse {
    let dashboard_path = std::env::var("BRAIN_EVAL_DASHBOARD").unwrap_or_else(|_| {
        // Derive from BRAIN_DB_PATH: sibling static/ dir
        let db = std::env::var("BRAIN_DB_PATH")
            .unwrap_or_else(|_| "brain/rust/brain.db".to_string());
        std::path::Path::new(&db)
            .parent()
            .map(|p| p.join("static/eval_dashboard.json").to_string_lossy().into_owned())
            .unwrap_or_else(|| "brain/rust/static/eval_dashboard.json".to_string())
    });
    match std::fs::read_to_string(&dashboard_path) {
        Ok(content) => Response::builder()
            .status(StatusCode::OK)
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from(content))
            .unwrap(),
        Err(_) => Response::builder()
            .status(StatusCode::OK)
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from("{\"runs\":[]}"))
            .unwrap(),
    }
}

async fn static_handler(State(state): State<AppState>, Path(path): Path<String>) -> impl IntoResponse {
    let path = path.trim_start_matches('/');
    let path = if path.is_empty() { "index.html" } else { path };
    match StaticAssets::get(path) {
        Some(content) => {
            // Inject API key into index.html so browser JS can authenticate requests.
            if path == "index.html" {
                let html = String::from_utf8_lossy(&content.data).into_owned();
                let key_js = format!(
                    "<script>window.__BRAIN_API_KEY__={};</script>",
                    serde_json::to_string(&state.settings.api_key).unwrap_or_else(|_| "\"\"".to_string())
                );
                let html = html.replacen("</head>", &format!("{}</head>", key_js), 1);
                return Response::builder()
                    .status(StatusCode::OK)
                    .header(header::CONTENT_TYPE, "text/html; charset=utf-8")
                    .body(Body::from(html))
                    .unwrap();
            }
            let mime = mime_guess::from_path(path).first_or_octet_stream();
            let hv = HeaderValue::from_str(mime.as_ref()).unwrap_or_else(|_| {
                HeaderValue::from_static("application/octet-stream")
            });
            Response::builder()
                .status(StatusCode::OK)
                .header(header::CONTENT_TYPE, hv)
                .body(Body::from(content.data.into_owned()))
                .unwrap()
        }
        None => StatusCode::NOT_FOUND.into_response(),
    }
}

fn settings_from_env() -> ApiSettings {
    let api_key = std::env::var("BRAIN_API_KEY").unwrap_or_default();
    let auth_required = std::env::var("BRAIN_API_AUTH_REQUIRED")
        .map(|v| v == "1" || v.eq_ignore_ascii_case("true"))
        .unwrap_or(!api_key.is_empty());
    let rate_limit_max_requests = std::env::var("BRAIN_API_RATE_LIMIT_MAX_REQUESTS")
        .ok()
        .and_then(|s| s.parse::<u32>().ok())
        .unwrap_or(120);
    let rate_limit_window_seconds = std::env::var("BRAIN_API_RATE_LIMIT_WINDOW_SECONDS")
        .ok()
        .and_then(|s| s.parse::<u64>().ok())
        .unwrap_or(60);
    ApiSettings {
        api_key,
        auth_required,
        rate_limit_max_requests,
        rate_limit_window_seconds,
    }
}

#[tokio::main]
async fn main() {
    let bind = std::env::var("BRAIN_API_BIND").unwrap_or_else(|_| "127.0.0.1:8787".to_string());
    let settings = settings_from_env();
    let (memory_tx, _) = broadcast::channel::<brain::MemoryEvent>(256);

    // Bootstrap (or load) the instance registry, then open the *active*
    // instance's db_path rather than BRAIN_DB_PATH directly — on first boot
    // this is a no-op (active == BRAIN_DB_PATH), but it gives later instance
    // switching (Task 4/5) a coherent registry + AppState from the start.
    let env_db = brain_config_from_env().db_path;
    let reg_path = brain::instances::registry_path();
    let instances_root = brain::instances::instances_root();
    let registry = brain::instances::load_or_bootstrap(&reg_path, std::path::Path::new(&env_db))
        .expect("failed to load or bootstrap instances registry");
    let active_path = registry
        .instances
        .iter()
        .find(|i| i.id == registry.active_id)
        .map(|i| i.db_path.clone())
        .unwrap_or_else(|| env_db.clone());

    // Build the Brain once at startup: load all embeddings, build the turbovec
    // index, and create the embedder/LLM client a single time. Shared across
    // all requests via Arc<Mutex<Brain>>.
    let boot = Instant::now();
    let brain = open_brain_at(&active_path, &memory_tx).expect("failed to open Brain at startup");
    eprintln!(
        "[BRAIN API] Brain ready ({} memories indexed) in {:.0} ms",
        brain.get_stats().map(|s| s.total_memories).unwrap_or(0),
        boot.elapsed().as_secs_f64() * 1000.0
    );
    let brain = Arc::new(Mutex::new(brain));

    let state = AppState {
        bind_addr: bind.clone(),
        settings,
        limiter: Arc::new(Mutex::new(HashMap::new())),
        memory_tx,
        brain,
        registry_path: reg_path,
        instances_root,
        registry: Arc::new(Mutex::new(registry)),
        active_db_path: Arc::new(Mutex::new(active_path.clone())),
        switching: Arc::new(AtomicBool::new(false)),
    };

    // Background job worker: open a short-lived DB handle per tick so the connection
    // never crosses an `.await` (rusqlite::Connection is not `Send`). Reads
    // `state.active_db_path` fresh every tick so an instance switch (Task 4)
    // is picked up without restarting the process.
    let active_db_path = state.active_db_path.clone();
    tokio::spawn(async move {
        loop {
            let db_path = active_db_path
                .lock()
                .unwrap_or_else(|p| p.into_inner())
                .clone();
            if db_path != ":memory:" {
                let tick_path = db_path.clone();
                let tick = tokio::task::spawn_blocking(move || {
                    let store = MetadataStore::open(&tick_path)?;
                    brain::worker::process_once(&store)
                })
                .await;
                match tick {
                    Ok(Ok(_)) => {}
                    Ok(Err(e)) => eprintln!("worker error (db_path={db_path}): {e}"),
                    Err(e) => eprintln!("worker join error (db_path={db_path}): {e}"),
                }
            }
            tokio::time::sleep(Duration::from_secs(5)).await;
        }
    });

    let app = build_router(state);

    let addr: SocketAddr = bind.parse().expect("invalid BRAIN_API_BIND");
    let listener = tokio::net::TcpListener::bind(addr)
        .await
        .expect("failed to bind BRAIN_API_BIND");
    eprintln!("[BRAIN API] listening on http://{addr}");
    axum::serve(listener, app).await.expect("server failure");
}

fn build_router(state: AppState) -> Router {
    Router::new()
        .route(
            "/",
            get(|| async { Redirect::permanent("/static/index.html") }),
        )
        .route("/health", get(health))
        .route("/stats", get(stats))
        .route("/save", post(save))
        .route("/save-batch", post(save_batch))
        .route("/search", post(search))
        .route("/v1/search", post(search))
        .route("/v1/search_index", post(search_index_handler))
        .route("/v1/get_observations", post(get_observations_handler))
        .route("/v1/timeline", post(timeline_handler))
        .route("/v1/stream", get(stream_handler))
        .route("/get-episode", get(get_episode_handler))
        .route("/entities", get(entities_handler))
        .route("/link-entities", post(link_entities_handler))
        .route("/neighbors", get(neighbors_handler))
        .route("/linked", get(linked_handler))
        .route("/list", get(list_memories))
        .route("/delete", post(delete_memories))
        .route("/feedback", post(feedback))
        .route("/reflect", post(reflect))
        .route("/memories/:id", patch(patch_memory))
        .route(
            "/v1/instances",
            get(list_instances).post(create_instance_handler),
        )
        .route(
            "/v1/instances/:id",
            patch(patch_instance_handler).delete(delete_instance_handler),
        )
        .route("/v1/instances/:id/switch", post(switch_instance))
        .route("/v1/instances/:id/archive", post(archive_instance))
        .route("/v1/instances/:id/unarchive", post(unarchive_instance))
        .route("/eval_dashboard.json", get(eval_dashboard_handler))
        // Catch-all (`*path`) must be the final segment of the path (matchit).
        .route("/static/*path", get(static_handler))
        .with_state(state)
}

async fn stream_handler(
    State(state): State<AppState>,
    mut headers: HeaderMap,
    Query(params): Query<HashMap<String, String>>,
) -> Result<
    Sse<impl Stream<Item = Result<Event, Infallible>> + Send>,
    (StatusCode, Json<ApiError>),
> {
    // EventSource can't send custom headers; accept API key via ?key= query param.
    if let Some(key) = params.get("key") {
        if let Ok(v) = HeaderValue::from_str(key) {
            headers.insert("x-api-key", v);
        }
    }
    authorize_and_rate_limit(&state, &headers)?;
    let rx = state.memory_tx.subscribe();
    let stream = BroadcastStream::new(rx).filter_map(|item| {
        std::future::ready(match item {
            Ok(evt) => Event::default().json_data(&evt).ok(),
            Err(_) => None,
        })
    });
    let stream = stream.map(Ok::<_, Infallible>);
    Ok(Sse::new(stream).keep_alive(KeepAlive::default()))
}

async fn health(State(state): State<AppState>) -> Json<HealthResponse> {
    Json(HealthResponse {
        status: "ok",
        bind: state.bind_addr,
    })
}

async fn stats(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<ApiError>)> {
    let start = Instant::now();
    authorize_and_rate_limit(&state, &headers)?;
    reject_if_switching(&state)?;
    // Copy id/name out from behind the registry lock first, then drop it
    // before taking the brain lock, so we never hold both at once.
    let (active_id, active_name) = {
        let reg = state.registry.lock().unwrap_or_else(|p| p.into_inner());
        let name = instances::get(&reg, &reg.active_id)
            .map(|r| r.name.clone())
            .unwrap_or_default();
        (reg.active_id.clone(), name)
    };
    let brain = lock_brain(&state);
    let mut value = stats_json(&brain)?;
    drop(brain);
    value["active_instance"] = serde_json::json!({ "id": active_id, "name": active_name });
    log_request("GET", "/stats", StatusCode::OK, start);
    Ok(Json(value))
}

/// Shared stats payload (without `active_instance`) used by both `/stats`
/// and the switch handler's response.
fn stats_json(brain: &Brain) -> Result<serde_json::Value, (StatusCode, Json<ApiError>)> {
    let stats = brain.get_stats().map_err(internal_err)?;
    Ok(serde_json::json!({
        "total_memories": stats.total_memories,
        "total_sessions": stats.total_sessions,
        "save_count_this_session": stats.save_count_this_session,
        "feedback_events_total": stats.feedback_events_total,
        "feedback_last_event_ts": stats.feedback_last_event_ts,
        "by_type": stats.by_type,
    }))
}

async fn save(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<SaveRequest>,
) -> Result<Json<SaveResponse>, (StatusCode, Json<ApiError>)> {
    let start = Instant::now();
    authorize_and_rate_limit(&state, &headers)?;
    reject_if_switching(&state)?;
    let brain = lock_brain(&state);
    let memory_type = parse_memory_type(&req.memory_type)
        .ok_or_else(|| bad_request("invalid memory_type"))?;
    let source = req
        .source
        .as_deref()
        .and_then(parse_memory_source)
        .unwrap_or(MemorySource::ClaudeCodeSession);
    let tags: Vec<&str> = req.tags.iter().map(String::as_str).collect();
    let timestamp = parse_rfc3339_opt(req.timestamp.as_deref())
        .map_err(|e| bad_request(&format!("invalid timestamp: {e}")))?;

    let event_time = parse_rfc3339_opt(req.event_time.as_deref())
        .map_err(|e| bad_request(&format!("invalid event_time: {e}")))?;
    let id = brain
        .save_memory(
            &req.content,
            memory_type,
            &tags,
            &req.project,
            req.session_id.as_deref(),
            source,
            req.file_path.as_deref(),
            req.title.as_deref(),
            timestamp,
            req.parent_id.as_deref(),
            event_time,
            req.salience,
            req.derived_from.as_deref(),
        )
        .map_err(internal_err)?;
    if let Some(ref names) = req.entities {
        if !names.is_empty() {
            // Fact is already persisted; linking failure must not fail the save.
            if let Err(e) = brain.link_entities(&id, names) {
                eprintln!("link_entities failed for {id}: {e}");
            }
        }
    }
    let response = Json(SaveResponse { id });
    log_request("POST", "/save", StatusCode::OK, start);
    Ok(response)
}

async fn save_batch(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<SaveBatchRequest>,
) -> Result<Json<SaveBatchResponse>, (StatusCode, Json<ApiError>)> {
    let start = Instant::now();
    authorize_and_rate_limit(&state, &headers)?;
    reject_if_switching(&state)?;
    let brain = lock_brain(&state);
    let mut accepted = 0usize;
    let mut failed = 0usize;
    let mut results: Vec<SaveBatchItemResult> = Vec::with_capacity(req.items.len());

    for (idx, item) in req.items.iter().enumerate() {
        let memory_type = match parse_memory_type(&item.memory_type) {
            Some(v) => v,
            None => {
                failed += 1;
                results.push(SaveBatchItemResult {
                    index: idx,
                    id: None,
                    error: Some("invalid memory_type".to_string()),
                });
                continue;
            }
        };
        let source = item
            .source
            .as_deref()
            .and_then(parse_memory_source)
            .unwrap_or(MemorySource::ClaudeCodeSession);
        let tags: Vec<&str> = item.tags.iter().map(String::as_str).collect();
        let timestamp = match parse_rfc3339_opt(item.timestamp.as_deref()) {
            Ok(v) => v,
            Err(e) => {
                failed += 1;
                results.push(SaveBatchItemResult {
                    index: idx,
                    id: None,
                    error: Some(format!("invalid timestamp: {e}")),
                });
                continue;
            }
        };
        let item_event_time = match parse_rfc3339_opt(item.event_time.as_deref()) {
            Ok(v) => v,
            Err(e) => {
                failed += 1;
                results.push(SaveBatchItemResult {
                    index: idx,
                    id: None,
                    error: Some(format!("invalid event_time: {e}")),
                });
                continue;
            }
        };
        match brain.save_memory(
            &item.content,
            memory_type,
            &tags,
            &item.project,
            item.session_id.as_deref(),
            source,
            item.file_path.as_deref(),
            item.title.as_deref(),
            timestamp,
            item.parent_id.as_deref(),
            item_event_time,
            item.salience,
            item.derived_from.as_deref(),
        ) {
            Ok(id) => {
                if let Some(ref names) = item.entities {
                    if !names.is_empty() {
                        // Fact is already persisted; linking failure must not fail the save.
                        if let Err(e) = brain.link_entities(&id, names) {
                            eprintln!("link_entities failed for {id}: {e}");
                        }
                    }
                }
                accepted += 1;
                results.push(SaveBatchItemResult {
                    index: idx,
                    id: Some(id),
                    error: None,
                });
            }
            Err(e) => {
                failed += 1;
                results.push(SaveBatchItemResult {
                    index: idx,
                    id: None,
                    error: Some(e.to_string()),
                });
            }
        }
    }
    let response = Json(SaveBatchResponse {
        accepted,
        failed,
        results,
    });
    log_request("POST", "/save-batch", StatusCode::OK, start);
    Ok(response)
}

async fn search(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<SearchRequest>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<ApiError>)> {
    let start = Instant::now();
    authorize_and_rate_limit(&state, &headers)?;
    reject_if_switching(&state)?;
    let brain = lock_brain(&state);
    let filter = SearchFilter {
        project: req.project,
        memory_type: req.memory_type.as_deref().and_then(parse_memory_type),
        exclude_superseded: req.exclude_superseded,
        alpha: req.alpha,
        graph_expand: req.graph_expand,
        ..SearchFilter::default()
    };
    let results = brain
        .search(&req.query, req.n, Some(filter))
        .map_err(internal_err)?;
    if log_search_enabled() {
        let ms = start.elapsed().as_millis();
        let qlen = req.query.chars().count();
        let n = results.len();
        eprintln!(
            "[BRAIN API] search_metrics query_len={qlen} result_count={n} ms={ms}"
        );
    }
    let response = Json(serde_json::json!({ "results": results }));
    log_request("POST", "/search", StatusCode::OK, start);
    Ok(response)
}

async fn search_index_handler(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<SearchRequest>,
) -> Result<Json<SearchIndexResponse>, (StatusCode, Json<ApiError>)> {
    let start = Instant::now();
    authorize_and_rate_limit(&state, &headers)?;
    reject_if_switching(&state)?;
    let brain = lock_brain(&state);
    let filter = SearchFilter {
        project: req.project,
        memory_type: req.memory_type.as_deref().and_then(parse_memory_type),
        exclude_superseded: req.exclude_superseded,
        alpha: req.alpha,
        graph_expand: req.graph_expand,
        ..SearchFilter::default()
    };
    let full = brain
        .search(&req.query, req.n, Some(filter))
        .map_err(internal_err)?;
    let results = full
        .into_iter()
        .map(|r| SearchIndexRow {
            id: r.id,
            snippet: r.content.chars().take(120).collect(),
            memory_type: memory_type_snake(&r.metadata.memory_type),
            project: r.metadata.project,
            timestamp: r.metadata.timestamp.to_rfc3339(),
            distance: r.distance,
            parent_id: r.metadata.parent_id,
        })
        .collect();
    log_request("POST", "/v1/search_index", StatusCode::OK, start);
    Ok(Json(SearchIndexResponse { results }))
}

async fn get_observations_handler(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<GetObservationsRequest>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<ApiError>)> {
    let start = Instant::now();
    authorize_and_rate_limit(&state, &headers)?;
    reject_if_switching(&state)?;
    let brain = lock_brain(&state);
    let refs: Vec<&str> = req.ids.iter().map(String::as_str).collect();
    let mems = brain.get_memories_by_ids(&refs).map_err(internal_err)?;
    let results: Vec<serde_json::Value> = mems.iter().map(api_memory_json).collect();
    log_request("POST", "/v1/get_observations", StatusCode::OK, start);
    Ok(Json(serde_json::json!({ "results": results })))
}

#[derive(Debug, Deserialize)]
struct GetEpisodeQuery {
    id: String,
}

#[derive(Debug, Deserialize)]
struct EntitiesQuery {
    memory_id: Option<String>,
}

#[derive(Debug, Serialize)]
struct EntityRow {
    id: String,
    name: String,
}

#[derive(Debug, Serialize)]
struct EntitiesResponse {
    entities: Vec<EntityRow>,
}

#[derive(Debug, Deserialize)]
struct LinkEntitiesRequest {
    memory_id: String,
    #[serde(default)]
    entities: Vec<String>,
}

#[derive(Debug, Serialize)]
struct LinkEntitiesResponse {
    linked: usize,
}

#[derive(Debug, Deserialize)]
struct NeighborsQuery {
    memory_id: Option<String>,
    #[serde(default = "default_true")]
    exclude_superseded: bool,
}

#[derive(Debug, Serialize)]
struct NeighborsResponse {
    ids: Vec<String>,
}

fn require_memory_id(memory_id: Option<String>) -> Result<String, (StatusCode, Json<ApiError>)> {
    memory_id
        .filter(|s| !s.is_empty())
        .ok_or_else(|| bad_request("memory_id is required"))
}

async fn get_episode_handler(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<GetEpisodeQuery>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<ApiError>)> {
    let start = Instant::now();
    authorize_and_rate_limit(&state, &headers)?;
    reject_if_switching(&state)?;
    let brain = lock_brain(&state);
    let mems = brain
        .get_memories_by_ids(&[q.id.as_str()])
        .map_err(internal_err)?;
    let Some(mem) = mems.into_iter().next() else {
        return Err(not_found(format!("id {} not found", q.id)));
    };
    let target = if mem.metadata.parent_id.is_some() {
        let parent_id = mem.metadata.parent_id.as_deref().unwrap();
        let parents = brain
            .get_memories_by_ids(&[parent_id])
            .map_err(internal_err)?;
        match parents.into_iter().next() {
            Some(ep) => ep,
            None => return Err(not_found(format!("parent episode {} not found", parent_id))),
        }
    } else {
        mem
    };
    log_request("GET", "/get-episode", StatusCode::OK, start);
    Ok(Json(api_memory_json(&target)))
}

async fn entities_handler(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<EntitiesQuery>,
) -> Result<Json<EntitiesResponse>, (StatusCode, Json<ApiError>)> {
    let start = Instant::now();
    authorize_and_rate_limit(&state, &headers)?;
    reject_if_switching(&state)?;
    let memory_id = require_memory_id(q.memory_id)?;
    let brain = lock_brain(&state);
    let rows = brain
        .entities_for_memory(&memory_id)
        .map_err(brain_err)?;
    let entities = rows
        .into_iter()
        .map(|(id, name)| EntityRow { id, name })
        .collect();
    log_request("GET", "/entities", StatusCode::OK, start);
    Ok(Json(EntitiesResponse { entities }))
}

async fn link_entities_handler(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<LinkEntitiesRequest>,
) -> Result<Json<LinkEntitiesResponse>, (StatusCode, Json<ApiError>)> {
    let start = Instant::now();
    authorize_and_rate_limit(&state, &headers)?;
    reject_if_switching(&state)?;
    let linked = if req.entities.is_empty() {
        0
    } else {
        let brain = lock_brain(&state);
        brain
            .link_entities(&req.memory_id, &req.entities)
            .map_err(brain_err)?
    };
    log_request("POST", "/link-entities", StatusCode::OK, start);
    Ok(Json(LinkEntitiesResponse { linked }))
}

async fn neighbors_handler(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<NeighborsQuery>,
) -> Result<Json<NeighborsResponse>, (StatusCode, Json<ApiError>)> {
    let start = Instant::now();
    authorize_and_rate_limit(&state, &headers)?;
    reject_if_switching(&state)?;
    let memory_id = require_memory_id(q.memory_id)?;
    let brain = lock_brain(&state);
    let ids = brain
        .neighbor_memory_ids(&[memory_id], q.exclude_superseded)
        .map_err(brain_err)?;
    log_request("GET", "/neighbors", StatusCode::OK, start);
    Ok(Json(NeighborsResponse { ids }))
}

#[derive(Debug, Serialize)]
struct LinkedEntityRef {
    id: String,
    name: String,
}

#[derive(Debug, Serialize)]
struct LinkedEntityStat {
    id: String,
    name: String,
    memory_count: usize,
}

#[derive(Debug, Serialize)]
struct LinkedMemoryItem {
    id: String,
    snippet: String,
    memory_type: String,
    project: String,
    timestamp: String,
    entities: Vec<LinkedEntityRef>,
    neighbor_ids: Vec<String>,
}

#[derive(Debug, Serialize)]
struct LinkedResponse {
    memories: Vec<LinkedMemoryItem>,
    entities: Vec<LinkedEntityStat>,
}

async fn linked_handler(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Result<Json<LinkedResponse>, (StatusCode, Json<ApiError>)> {
    let start = Instant::now();
    authorize_and_rate_limit(&state, &headers)?;
    reject_if_switching(&state)?;
    let brain = lock_brain(&state);
    let (rows, entity_counts) = brain.list_linked_graph().map_err(brain_err)?;
    let memories = rows
        .into_iter()
        .map(|r| LinkedMemoryItem {
            id: r.id,
            snippet: r.snippet,
            memory_type: memory_type_snake(&r.memory_type),
            project: r.project,
            timestamp: r.timestamp,
            entities: r
                .entities
                .into_iter()
                .map(|(id, name)| LinkedEntityRef { id, name })
                .collect(),
            neighbor_ids: r.neighbor_ids,
        })
        .collect();
    let entities = entity_counts
        .into_iter()
        .map(|(id, name, memory_count)| LinkedEntityStat {
            id,
            name,
            memory_count,
        })
        .collect();
    log_request("GET", "/linked", StatusCode::OK, start);
    Ok(Json(LinkedResponse { memories, entities }))
}

async fn timeline_handler(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<TimelineRequest>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<ApiError>)> {
    let start = Instant::now();
    authorize_and_rate_limit(&state, &headers)?;
    reject_if_switching(&state)?;
    let brain = lock_brain(&state);
    let rows = brain
        .timeline_around(&req.anchor_id, req.before, req.after)
        .map_err(brain_err)?;
    let results: Vec<serde_json::Value> = rows.iter().map(api_memory_json).collect();
    log_request("POST", "/v1/timeline", StatusCode::OK, start);
    Ok(Json(serde_json::json!({ "results": results })))
}

fn api_memory_json(m: &Memory) -> serde_json::Value {
    serde_json::json!({
        "id": m.id,
        "content": m.content,
        "timestamp": m.metadata.timestamp.to_rfc3339(),
        "metadata": m.metadata,
    })
}

fn memory_type_snake(mt: &MemoryType) -> String {
    serde_json::to_value(mt)
        .ok()
        .and_then(|v| v.as_str().map(String::from))
        .unwrap_or_else(|| "unknown".into())
}

fn brain_err(e: BrainError) -> (StatusCode, Json<ApiError>) {
    match e {
        BrainError::NotFound(msg) => not_found(msg),
        _ => internal_err(e),
    }
}

fn log_search_enabled() -> bool {
    std::env::var("BRAIN_LOG_SEARCH")
        .map(|v| v == "1" || v.eq_ignore_ascii_case("true"))
        .unwrap_or(false)
}

async fn feedback(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<FeedbackRequest>,
) -> Result<Json<FeedbackResponse>, (StatusCode, Json<ApiError>)> {
    let start = Instant::now();
    authorize_and_rate_limit(&state, &headers)?;
    reject_if_switching(&state)?;
    let event_type = parse_feedback_event_type(&req.event_type)
        .ok_or_else(|| bad_request("invalid event_type"))?;
    let source = req
        .source
        .as_deref()
        .map(parse_feedback_source)
        .unwrap_or(Some(FeedbackSource::BrainApi))
        .ok_or_else(|| bad_request("invalid source"))?;
    let memory_id = req.memory_id.clone();
    let query = req.query.clone();
    let session_id = req.session_id.clone();
    let project = req.project.clone();
    let idempotency_key = req.idempotency_key.clone();
    let payload = req.payload.unwrap_or_else(|| serde_json::json!({}));
    let brain = state.brain.clone();
    let id = tokio::task::spawn_blocking(move || {
        let brain = brain.lock().unwrap_or_else(|p| p.into_inner());
        brain.append_feedback(
            event_type,
            memory_id.as_deref(),
            query.as_deref(),
            session_id.as_deref(),
            project.as_deref(),
            source,
            payload,
            idempotency_key.as_deref(),
        )
        .map_err(|e| e.to_string())
    })
    .await
    .map_err(|e| internal_err(format!("feedback task join failed: {e}")))?
    .map_err(internal_err)?;
    let response = Json(FeedbackResponse { id });
    log_request("POST", "/feedback", StatusCode::OK, start);
    Ok(response)
}

async fn list_memories(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<ListQuery>,
) -> Result<Json<ListResponse>, (StatusCode, Json<ApiError>)> {
    let start = Instant::now();
    authorize_and_rate_limit(&state, &headers)?;
    reject_if_switching(&state)?;

    let type_filter = q
        .memory_type
        .as_deref()
        .map(|s| parse_memory_type(s).ok_or_else(|| bad_request("invalid memory_type")))
        .transpose()?;
    let source_filter = q
        .source
        .as_deref()
        .map(|s| parse_memory_source(s).ok_or_else(|| bad_request("invalid source")))
        .transpose()?;

    let limit = q.limit.min(5000);
    let offset = q.offset;
    let project_filter = q.project.clone();
    let brain = state.brain.clone();

    let response = tokio::task::spawn_blocking(move || -> Result<ListResponse, String> {
        let brain = brain.lock().unwrap_or_else(|p| p.into_inner());
        let all = brain.list_all_memories().map_err(|e| e.to_string())?;

        let filtered: Vec<_> = all
            .into_iter()
            .filter(|m| {
                type_filter
                    .as_ref()
                    .map(|t| &m.metadata.memory_type == t)
                    .unwrap_or(true)
                    && source_filter
                        .as_ref()
                        .map(|s| &m.metadata.source == s)
                        .unwrap_or(true)
                    && project_filter
                        .as_deref()
                        .map(|p| m.metadata.project == p)
                        .unwrap_or(true)
            })
            .collect();

        let total = filtered.len();
        let items: Vec<ListItem> = filtered
            .into_iter()
            .skip(offset)
            .take(limit)
            .map(|m| ListItem {
                id: m.id,
                content: m.content,
                memory_type: memory_type_as_str(&m.metadata.memory_type).to_string(),
                source: memory_source_as_str(&m.metadata.source).to_string(),
                project: m.metadata.project,
                timestamp: m.metadata.timestamp.to_rfc3339(),
                session_id: m.metadata.session_id,
            })
            .collect();

        Ok(ListResponse {
            total,
            returned: items.len(),
            items,
        })
    })
    .await
    .map_err(|e| internal_err(format!("list task join failed: {e}")))?
    .map_err(internal_err)?;

    log_request("GET", "/list", StatusCode::OK, start);
    Ok(Json(response))
}

async fn delete_memories(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<DeleteRequest>,
) -> Result<Json<DeleteResponse>, (StatusCode, Json<ApiError>)> {
    let start = Instant::now();
    authorize_and_rate_limit(&state, &headers)?;
    reject_if_switching(&state)?;
    if req.ids.is_empty() {
        return Err(bad_request("ids must not be empty"));
    }
    let brain = state.brain.clone();

    let deleted = tokio::task::spawn_blocking(move || -> Result<usize, String> {
        let brain = brain.lock().unwrap_or_else(|p| p.into_inner());
        let id_refs: Vec<&str> = req.ids.iter().map(String::as_str).collect();
        brain.delete_memories(&id_refs).map_err(|e| e.to_string())
    })
    .await
    .map_err(|e| internal_err(format!("delete task join failed: {e}")))?
    .map_err(internal_err)?;

    log_request("POST", "/delete", StatusCode::OK, start);
    Ok(Json(DeleteResponse { deleted }))
}

async fn reflect(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<ApiError>)> {
    let start = Instant::now();
    authorize_and_rate_limit(&state, &headers)?;
    reject_if_switching(&state)?;
    let brain = state.brain.clone();
    let result = tokio::task::spawn_blocking(move || -> Result<_, String> {
        let brain = brain.lock().unwrap_or_else(|p| p.into_inner());
        brain.trigger_reflection().map_err(|e| e.to_string())
    })
    .await
    .map_err(|e| internal_err(format!("reflection task join failed: {e}")))?
    .map_err(internal_err)?;
    let response = Json(serde_json::json!({
        "consolidated": result.consolidated,
        "patterns": result.patterns,
        "to_delete_indices": result.to_delete_indices
    }));
    log_request("POST", "/reflect", StatusCode::OK, start);
    Ok(response)
}

#[derive(Debug, Deserialize)]
struct PatchMemoryRequest {
    salience: Option<f64>,
}

#[derive(Debug, Serialize)]
struct PatchMemoryResponse {
    updated: bool,
}

async fn patch_memory(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(id): Path<String>,
    Json(req): Json<PatchMemoryRequest>,
) -> Result<Json<PatchMemoryResponse>, (StatusCode, Json<ApiError>)> {
    let start = Instant::now();
    authorize_and_rate_limit(&state, &headers)?;
    reject_if_switching(&state)?;
    if req.salience.is_none() {
        return Err(bad_request("no patchable fields provided"));
    }
    let salience = req.salience.unwrap();
    if !(0.0..=1.0).contains(&salience) {
        return Err(bad_request("salience must be 0.0–1.0"));
    }
    let brain = state.brain.clone();
    let updated = tokio::task::spawn_blocking(move || -> Result<bool, String> {
        let brain = brain.lock().unwrap_or_else(|p| p.into_inner());
        brain.update_salience(&id, salience).map_err(|e| e.to_string())
    })
    .await
    .map_err(|e| internal_err(format!("patch task join failed: {e}")))?
    .map_err(internal_err)?;
    if !updated {
        return Err((StatusCode::NOT_FOUND, Json(ApiError { error: "memory not found".into() })));
    }
    log_request("PATCH", "/memories/:id", StatusCode::OK, start);
    Ok(Json(PatchMemoryResponse { updated }))
}

fn reject_if_switching(state: &AppState) -> Result<(), (StatusCode, Json<ApiError>)> {
    if state.switching.load(Ordering::SeqCst) {
        return Err((
            StatusCode::SERVICE_UNAVAILABLE,
            Json(ApiError {
                error: "switching instance".into(),
            }),
        ));
    }
    Ok(())
}

fn conflict(msg: impl Into<String>) -> (StatusCode, Json<ApiError>) {
    (
        StatusCode::CONFLICT,
        Json(ApiError { error: msg.into() }),
    )
}

/// Maps `instances` module errors that represent bad input (create/patch):
/// "instance not found: …" → 404, anything else (e.g. "name required") → 400.
fn map_instance_err(msg: String) -> (StatusCode, Json<ApiError>) {
    if msg.starts_with("instance not found") {
        not_found(msg)
    } else {
        bad_request(&msg)
    }
}

/// Maps `instances` module errors that represent state conflicts
/// (archive/delete/switch guards): "instance not found: …" → 404, else 409.
fn map_instance_conflict_err(msg: String) -> (StatusCode, Json<ApiError>) {
    if msg.starts_with("instance not found") {
        not_found(msg)
    } else {
        conflict(msg)
    }
}

#[derive(Debug, Deserialize)]
struct CreateInstanceRequest {
    name: String,
    #[serde(default)]
    description: String,
    #[serde(default)]
    tags: Vec<String>,
}

#[derive(Debug, Deserialize)]
struct PatchInstanceRequest {
    name: Option<String>,
    description: Option<String>,
    tags: Option<Vec<String>>,
}

#[derive(Debug, Deserialize)]
struct InstanceListQuery {
    #[serde(default)]
    include_archived: Option<String>,
}

#[derive(Debug, Serialize)]
struct InstanceListItem {
    #[serde(flatten)]
    record: instances::InstanceRecord,
    /// Best-effort; `null` if we couldn't cheaply open the DB to count.
    memory_count: Option<usize>,
}

async fn list_instances(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<InstanceListQuery>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<ApiError>)> {
    let start = Instant::now();
    authorize_and_rate_limit(&state, &headers)?;
    let include_archived = q.include_archived.as_deref() == Some("1");
    let (active_id, records) = {
        let reg = state.registry.lock().unwrap_or_else(|p| p.into_inner());
        let records: Vec<instances::InstanceRecord> = reg
            .instances
            .iter()
            .filter(|i| include_archived || !i.archived)
            .cloned()
            .collect();
        (reg.active_id.clone(), records)
    };
    // Active instance's count is cheap (already-open Brain); other instances
    // are opened+closed just to count rows — best-effort, never fails the list.
    let active_count = {
        let brain = lock_brain(&state);
        brain.get_stats().ok().map(|s| s.total_memories)
    };
    let items: Vec<InstanceListItem> = records
        .into_iter()
        .map(|record| {
            let memory_count = if record.id == active_id {
                active_count
            } else {
                MetadataStore::open(&record.db_path)
                    .ok()
                    .and_then(|store| store.count_memories().ok())
            };
            InstanceListItem { record, memory_count }
        })
        .collect();
    log_request("GET", "/v1/instances", StatusCode::OK, start);
    Ok(Json(serde_json::json!({
        "active_id": active_id,
        "instances": items,
    })))
}

async fn create_instance_handler(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<CreateInstanceRequest>,
) -> Result<Json<instances::InstanceRecord>, (StatusCode, Json<ApiError>)> {
    let start = Instant::now();
    authorize_and_rate_limit(&state, &headers)?;
    let mut reg = state.registry.lock().unwrap_or_else(|p| p.into_inner());
    let record = instances::create_instance(
        &mut reg,
        &req.name,
        &req.description,
        req.tags,
        &state.instances_root,
    )
    .map_err(map_instance_err)?;
    instances::save_registry(&state.registry_path, &reg).map_err(internal_err)?;
    log_request("POST", "/v1/instances", StatusCode::OK, start);
    Ok(Json(record))
}

async fn patch_instance_handler(
    Path(id): Path<String>,
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<PatchInstanceRequest>,
) -> Result<Json<instances::InstanceRecord>, (StatusCode, Json<ApiError>)> {
    let start = Instant::now();
    authorize_and_rate_limit(&state, &headers)?;
    let mut reg = state.registry.lock().unwrap_or_else(|p| p.into_inner());
    let record = instances::patch_instance(&mut reg, &id, req.name, req.description, req.tags)
        .map_err(map_instance_err)?
        .clone();
    instances::save_registry(&state.registry_path, &reg).map_err(internal_err)?;
    log_request("PATCH", "/v1/instances/:id", StatusCode::OK, start);
    Ok(Json(record))
}

async fn archive_instance(
    Path(id): Path<String>,
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Result<Json<instances::InstanceRecord>, (StatusCode, Json<ApiError>)> {
    let start = Instant::now();
    authorize_and_rate_limit(&state, &headers)?;
    let mut reg = state.registry.lock().unwrap_or_else(|p| p.into_inner());
    let active_id = reg.active_id.clone();
    instances::set_archived(&mut reg, &id, true, &active_id).map_err(map_instance_conflict_err)?;
    instances::save_registry(&state.registry_path, &reg).map_err(internal_err)?;
    let record = instances::get(&reg, &id)
        .cloned()
        .ok_or_else(|| not_found(format!("instance not found: {id}")))?;
    log_request("POST", "/v1/instances/:id/archive", StatusCode::OK, start);
    Ok(Json(record))
}

async fn unarchive_instance(
    Path(id): Path<String>,
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Result<Json<instances::InstanceRecord>, (StatusCode, Json<ApiError>)> {
    let start = Instant::now();
    authorize_and_rate_limit(&state, &headers)?;
    let mut reg = state.registry.lock().unwrap_or_else(|p| p.into_inner());
    let active_id = reg.active_id.clone();
    instances::set_archived(&mut reg, &id, false, &active_id).map_err(map_instance_conflict_err)?;
    instances::save_registry(&state.registry_path, &reg).map_err(internal_err)?;
    let record = instances::get(&reg, &id)
        .cloned()
        .ok_or_else(|| not_found(format!("instance not found: {id}")))?;
    log_request("POST", "/v1/instances/:id/unarchive", StatusCode::OK, start);
    Ok(Json(record))
}

async fn delete_instance_handler(
    Path(id): Path<String>,
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<ApiError>)> {
    let start = Instant::now();
    authorize_and_rate_limit(&state, &headers)?;
    let removed = {
        let mut reg = state.registry.lock().unwrap_or_else(|p| p.into_inner());
        let active_id = reg.active_id.clone();
        let removed = instances::delete_instance(&mut reg, &id, &active_id)
            .map_err(map_instance_conflict_err)?;
        instances::save_registry(&state.registry_path, &reg).map_err(internal_err)?;
        removed
    };
    if let Err(e) = instances::remove_instance_files(&removed, &state.instances_root) {
        eprintln!(
            "[BRAIN API] remove_instance_files failed for {}: {e}",
            removed.id
        );
    }
    log_request("DELETE", "/v1/instances/:id", StatusCode::OK, start);
    Ok(Json(serde_json::json!({ "deleted": removed.id })))
}

/// Switch the active Brain to another instance. Never drops the current
/// Brain until the new one has opened successfully — on failure the previous
/// instance stays live and `active_id`/`active_db_path` are left untouched.
async fn switch_instance(
    Path(id): Path<String>,
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<ApiError>)> {
    let start = Instant::now();
    authorize_and_rate_limit(&state, &headers)?;

    let already_active = {
        let reg = state.registry.lock().unwrap_or_else(|p| p.into_inner());
        reg.active_id == id
    };
    if already_active {
        let brain = lock_brain(&state);
        let stats = stats_json(&brain)?;
        drop(brain);
        log_request("POST", "/v1/instances/:id/switch", StatusCode::OK, start);
        return Ok(Json(serde_json::json!({ "active_id": id, "stats": stats })));
    }

    if state.switching.swap(true, Ordering::SeqCst) {
        return Err((
            StatusCode::SERVICE_UNAVAILABLE,
            Json(ApiError {
                error: "switching instance".into(),
            }),
        ));
    }

    let db_path = {
        let reg = state.registry.lock().unwrap_or_else(|p| p.into_inner());
        match instances::get(&reg, &id) {
            None => {
                state.switching.store(false, Ordering::SeqCst);
                return Err(not_found(format!("instance not found: {id}")));
            }
            Some(record) if record.archived => {
                state.switching.store(false, Ordering::SeqCst);
                return Err(conflict("cannot activate an archived instance"));
            }
            Some(record) => record.db_path.clone(),
        }
    };

    let memory_tx = state.memory_tx.clone();
    let open_path = db_path.clone();
    let opened = tokio::task::spawn_blocking(move || open_brain_at(&open_path, &memory_tx)).await;

    let new_brain = match opened {
        Ok(Ok(brain)) => brain,
        Ok(Err(e)) => {
            state.switching.store(false, Ordering::SeqCst);
            return Err(internal_err(e));
        }
        Err(e) => {
            state.switching.store(false, Ordering::SeqCst);
            return Err(internal_err(format!("switch task join failed: {e}")));
        }
    };

    // Only now that the replacement Brain opened successfully do we drop the
    // previous one, by overwriting it behind the mutex.
    {
        let mut brain_guard = lock_brain(&state);
        *brain_guard = new_brain;
    }
    *state.active_db_path.lock().unwrap_or_else(|p| p.into_inner()) = db_path.clone();
    // Persist active_id only after the swap succeeded — a crash between the
    // swap and this write just means a restart resumes the previous active_id,
    // which is safe (the DB files themselves are untouched either way).
    {
        let mut reg = state.registry.lock().unwrap_or_else(|p| p.into_inner());
        if let Err(e) = instances::set_active(&mut reg, &id) {
            eprintln!("[BRAIN API] failed to set active_id after switch: {e}");
        }
        if let Err(e) = instances::save_registry(&state.registry_path, &reg) {
            eprintln!("[BRAIN API] failed to persist active_id after switch: {e}");
        }
    }
    state.switching.store(false, Ordering::SeqCst);

    let brain = lock_brain(&state);
    let stats = stats_json(&brain)?;
    drop(brain);
    log_request("POST", "/v1/instances/:id/switch", StatusCode::OK, start);
    Ok(Json(serde_json::json!({ "active_id": id, "stats": stats })))
}

/// Open a Brain against an explicit `db_path`, overriding whatever
/// `BRAIN_DB_PATH` says. All other config (embedder, hybrid alpha, reflection
/// flags) still comes from the environment. This is the primary entry point
/// for both boot and instance switching (Task 4/5).
fn open_brain_at(
    db_path: &str,
    memory_tx: &broadcast::Sender<brain::MemoryEvent>,
) -> Result<Brain, brain::BrainError> {
    let mut config = brain_config_from_env();
    config.db_path = db_path.to_string();
    let embedder = make_embedder()?;
    let brain = Brain::open_with_event_bus(config, embedder, Some(memory_tx.clone()))?;
    attach_llm(brain)
}

/// Lock the shared Brain, recovering from a poisoned mutex (a prior panic
/// while holding the lock) so one failed request can't wedge the server.
fn lock_brain(state: &AppState) -> std::sync::MutexGuard<'_, Brain> {
    state.brain.lock().unwrap_or_else(|p| p.into_inner())
}

/// Wire up an LLM client per `BRAIN_LLM_PROVIDER` (falling back to whichever
/// API key is present). Extracted so both `open_brain_at` and any future
/// per-instance open path share the same provider selection logic.
fn attach_llm(brain: Brain) -> Result<Brain, brain::BrainError> {
    let provider = std::env::var("BRAIN_LLM_PROVIDER")
        .unwrap_or_else(|_| "auto".to_string())
        .to_lowercase();

    match provider.as_str() {
        "openrouter" => {
            if let Some(key) = openrouter_api_key() {
                Ok(brain.with_llm_client(Box::new(OpenRouterClient::new(key))))
            } else {
                Ok(brain)
            }
        }
        "anthropic" => {
            if let Some(key) = anthropic_api_key() {
                Ok(brain.with_llm_client(Box::new(AnthropicClient::new(key))))
            } else {
                Ok(brain)
            }
        }
        "ollama" => Ok(brain.with_llm_client(Box::new(OllamaClient::from_env()))),
        _ => {
            if let Some(key) = openrouter_api_key() {
                Ok(brain.with_llm_client(Box::new(OpenRouterClient::new(key))))
            } else if let Some(key) = anthropic_api_key() {
                Ok(brain.with_llm_client(Box::new(AnthropicClient::new(key))))
            } else {
                Ok(brain)
            }
        }
    }
}

fn make_embedder() -> Result<Box<dyn EmbedderBackend>, brain::BrainError> {
    embedder_from_env("[BRAIN API]")
}

fn bad_request(msg: &str) -> (StatusCode, Json<ApiError>) {
    (
        StatusCode::BAD_REQUEST,
        Json(ApiError {
            error: msg.to_string(),
        }),
    )
}

fn not_found(msg: impl Into<String>) -> (StatusCode, Json<ApiError>) {
    (
        StatusCode::NOT_FOUND,
        Json(ApiError {
            error: msg.into(),
        }),
    )
}

fn internal_err<E: std::fmt::Display>(err: E) -> (StatusCode, Json<ApiError>) {
    (
        StatusCode::INTERNAL_SERVER_ERROR,
        Json(ApiError {
            error: err.to_string(),
        }),
    )
}

fn memory_type_as_str(t: &MemoryType) -> &'static str {
    match t {
        MemoryType::Solution => "solution",
        MemoryType::Decision => "decision",
        MemoryType::Conversation => "conversation",
        MemoryType::Pattern => "pattern",
        MemoryType::ProjectContext => "project_context",
        MemoryType::ErrorLesson => "error_lesson",
        MemoryType::Fact => "fact",
        MemoryType::Episode => "episode",
    }
}

fn memory_source_as_str(s: &MemorySource) -> &'static str {
    match s {
        MemorySource::ClaudeCodeSession => "claude_code_session",
        MemorySource::Reflection => "reflection",
        MemorySource::CursorHistory => "cursor_history",
        MemorySource::ClawCode => "claw_code",
        MemorySource::Perplexity => "perplexity",
        MemorySource::Obsidian => "obsidian",
        MemorySource::ObsidianBooks => "obsidian_books",
    }
}

fn parse_memory_type(s: &str) -> Option<MemoryType> {
    match s {
        "solution" => Some(MemoryType::Solution),
        "decision" => Some(MemoryType::Decision),
        "conversation" => Some(MemoryType::Conversation),
        "pattern" => Some(MemoryType::Pattern),
        "project_context" => Some(MemoryType::ProjectContext),
        "error_lesson" => Some(MemoryType::ErrorLesson),
        "fact" => Some(MemoryType::Fact),
        "episode" => Some(MemoryType::Episode),
        _ => None,
    }
}

fn parse_feedback_event_type(s: &str) -> Option<FeedbackEventType> {
    FeedbackEventType::from_str(s)
}

fn parse_feedback_source(s: &str) -> Option<FeedbackSource> {
    FeedbackSource::from_str(s)
}

fn parse_rfc3339_opt(s: Option<&str>) -> Result<Option<DateTime<Utc>>, String> {
    match s {
        None => Ok(None),
        Some(raw) => {
            let trimmed = raw.trim();
            if trimmed.is_empty() {
                return Ok(None);
            }
            DateTime::parse_from_rfc3339(trimmed)
                .map(|dt| Some(dt.with_timezone(&Utc)))
                .map_err(|e| e.to_string())
        }
    }
}

fn parse_memory_source(s: &str) -> Option<MemorySource> {
    match s {
        "claude_code_session" => Some(MemorySource::ClaudeCodeSession),
        "reflection" => Some(MemorySource::Reflection),
        "cursor_history" => Some(MemorySource::CursorHistory),
        "claw_code" => Some(MemorySource::ClawCode),
        "perplexity" => Some(MemorySource::Perplexity),
        "obsidian" => Some(MemorySource::Obsidian),
        "obsidian_books" => Some(MemorySource::ObsidianBooks),
        _ => None,
    }
}

fn authorize_and_rate_limit(
    state: &AppState,
    headers: &HeaderMap,
) -> Result<(), (StatusCode, Json<ApiError>)> {
    if state.settings.auth_required {
        let token = extract_token(headers);
        let unauthorized = token
            .as_deref()
            .map(|t| t != state.settings.api_key)
            .unwrap_or(true);
        if unauthorized {
            return Err((StatusCode::UNAUTHORIZED, Json(ApiError { error: "missing or invalid API key".to_string() })));
        }
    }

    let client_key = client_key(headers);
    let now = Instant::now();
    let mut limiter = state
        .limiter
        .lock()
        .map_err(|_| internal_err("rate limit state poisoned"))?;
    let window = limiter.entry(client_key).or_insert(ClientWindow {
        count: 0,
        window_started: now,
    });
    if now.duration_since(window.window_started)
        >= Duration::from_secs(state.settings.rate_limit_window_seconds)
    {
        window.count = 0;
        window.window_started = now;
    }
    if window.count >= state.settings.rate_limit_max_requests {
        return Err((StatusCode::TOO_MANY_REQUESTS, Json(ApiError { error: "rate limit exceeded".to_string() })));
    }
    window.count += 1;
    Ok(())
}

fn log_request(method: &str, path: &str, status: StatusCode, start: Instant) {
    eprintln!(
        "[BRAIN API] {} {} -> {} ({}ms)",
        method,
        path,
        status.as_u16(),
        start.elapsed().as_millis()
    );
}

fn extract_token(headers: &HeaderMap) -> Option<String> {
    if let Some(v) = headers.get("x-api-key").and_then(|h| h.to_str().ok()) {
        return Some(v.to_string());
    }
    headers
        .get("authorization")
        .and_then(|h| h.to_str().ok())
        .and_then(|raw| raw.strip_prefix("Bearer "))
        .map(str::trim)
        .map(str::to_string)
}

fn client_key(headers: &HeaderMap) -> String {
    headers
        .get("x-forwarded-for")
        .and_then(|h| h.to_str().ok())
        .map(str::to_string)
        .unwrap_or_else(|| "local".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::body::Body;
    use std::sync::LazyLock;
    use tower::util::ServiceExt;

    // Serialise test setup: BRAIN_DB_PATH is process-global, so tests that call
    // open_brain() race if they set different paths concurrently.
    static ENV_MUTEX: LazyLock<std::sync::Mutex<()>> =
        LazyLock::new(|| std::sync::Mutex::new(()));

    #[test]
    fn search_index_response_is_compact() {
        let row = SearchIndexRow {
            id: "abc".into(),
            snippet: "test".into(),
            memory_type: "solution".into(),
            project: "brain".into(),
            timestamp: "2026-04-20T00:00:00Z".into(),
            distance: 0.12,
            parent_id: None,
        };
        let json = serde_json::to_string(&row).unwrap();
        assert!(json.len() < 300, "row too large: {}", json.len());
        assert!(!json.contains("\"content\""));
    }

    fn test_state() -> (AppState, std::sync::MutexGuard<'static, ()>) {
        let guard = ENV_MUTEX.lock().unwrap_or_else(|e| e.into_inner());
        std::env::set_var("BRAIN_EMBEDDER", "mock");
        // open_brain_at() attaches an LLM client per BRAIN_LLM_PROVIDER/*_API_KEY.
        // Force "no client" so tests stay hermetic and don't depend on (or pay
        // network calls for) whatever LLM env vars happen to be set on the host.
        std::env::set_var("BRAIN_LLM_PROVIDER", "none");
        std::env::remove_var("OPENROUTER_API_KEY");
        std::env::remove_var("ANTHROPIC_API_KEY");
        let dir = tempfile::tempdir().expect("tempdir");
        let base = dir.keep();
        let db_path = base.join("brain.db");
        std::env::set_var("BRAIN_DB_PATH", db_path.to_string_lossy().as_ref());
        let (memory_tx, _) = broadcast::channel(64);
        let brain = Arc::new(Mutex::new(
            open_brain_at(&db_path.to_string_lossy(), &memory_tx).expect("open brain in test"),
        ));

        // Bootstrap a throwaway registry under the same tempdir so tests never
        // touch the real `~/.brain/instances.json`.
        let registry_path = base.join("instances.json");
        let instances_root = base.join("instances");
        let registry = brain::instances::load_or_bootstrap(&registry_path, &db_path)
            .expect("bootstrap test registry");

        let state = AppState {
            bind_addr: "127.0.0.1:8787".to_string(),
            settings: ApiSettings {
                api_key: "secret".to_string(),
                auth_required: true,
                rate_limit_max_requests: 2,
                rate_limit_window_seconds: 60,
            },
            limiter: Arc::new(Mutex::new(HashMap::new())),
            memory_tx,
            brain,
            registry_path,
            instances_root,
            active_db_path: Arc::new(Mutex::new(db_path.to_string_lossy().into_owned())),
            registry: Arc::new(Mutex::new(registry)),
            switching: Arc::new(AtomicBool::new(false)),
        };
        (state, guard)
    }

    #[tokio::test]
    async fn health_without_auth_is_allowed() {
        let (state, _guard) = test_state();
        let app = build_router(state);
        let res = app
            .oneshot(axum::http::Request::builder().uri("/health").body(Body::empty()).unwrap())
            .await
            .unwrap();
        assert_eq!(res.status(), StatusCode::OK);
    }

    #[tokio::test]
    async fn protected_endpoint_requires_auth() {
        let (state, _guard) = test_state();
        let app = build_router(state);
        let res = app
            .oneshot(axum::http::Request::builder().uri("/stats").body(Body::empty()).unwrap())
            .await
            .unwrap();
        assert_eq!(res.status(), StatusCode::UNAUTHORIZED);
    }

    #[tokio::test]
    async fn protected_endpoint_accepts_valid_api_key() {
        let (state, _guard) = test_state();
        let app = build_router(state);
        let res = app
            .oneshot(
                axum::http::Request::builder()
                    .uri("/stats")
                    .header("x-api-key", "secret")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(res.status(), StatusCode::OK);
    }

    #[tokio::test]
    async fn feedback_accepts_valid_payload() {
        let (state, _guard) = test_state();
        let app = build_router(state);
        let body = serde_json::json!({
            "event_type": "accepted",
            "memory_id": "abc-123",
            "source": "brain_api",
            "payload": {"rank": 1}
        });
        let res = app
            .oneshot(
                axum::http::Request::builder()
                    .method("POST")
                    .uri("/feedback")
                    .header("x-api-key", "secret")
                    .header("content-type", "application/json")
                    .body(Body::from(body.to_string()))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(res.status(), StatusCode::OK);
    }

    async fn body_json(res: axum::response::Response) -> serde_json::Value {
        let bytes = axum::body::to_bytes(res.into_body(), usize::MAX)
            .await
            .expect("read response body");
        serde_json::from_slice(&bytes).expect("response body is valid JSON")
    }

    fn get_request(uri: &str) -> axum::http::Request<Body> {
        axum::http::Request::builder()
            .uri(uri)
            .header("x-api-key", "secret")
            .body(Body::empty())
            .unwrap()
    }

    fn method_request(method: &str, uri: &str) -> axum::http::Request<Body> {
        axum::http::Request::builder()
            .method(method)
            .uri(uri)
            .header("x-api-key", "secret")
            .body(Body::empty())
            .unwrap()
    }

    fn json_request(method: &str, uri: &str, body: serde_json::Value) -> axum::http::Request<Body> {
        axum::http::Request::builder()
            .method(method)
            .uri(uri)
            .header("x-api-key", "secret")
            .header("content-type", "application/json")
            .body(Body::from(body.to_string()))
            .unwrap()
    }

    #[tokio::test]
    async fn bootstrap_list_contains_main() {
        let (mut state, _guard) = test_state();
        state.settings.rate_limit_max_requests = 50;
        let app = build_router(state);

        let res = app.oneshot(get_request("/v1/instances")).await.unwrap();
        assert_eq!(res.status(), StatusCode::OK);
        let body = body_json(res).await;
        assert_eq!(body["active_id"], "main");
        assert!(body["instances"]
            .as_array()
            .unwrap()
            .iter()
            .any(|i| i["id"] == "main"));
    }

    #[tokio::test]
    async fn create_grows_list_and_creates_db_file() {
        let (mut state, _guard) = test_state();
        state.settings.rate_limit_max_requests = 50;
        let app = build_router(state);

        let create_res = app
            .clone()
            .oneshot(json_request(
                "POST",
                "/v1/instances",
                serde_json::json!({"name": "Biz", "description": "work", "tags": ["work"]}),
            ))
            .await
            .unwrap();
        assert_eq!(create_res.status(), StatusCode::OK);
        let created = body_json(create_res).await;
        assert_eq!(created["id"], "biz");
        let db_path = created["db_path"].as_str().unwrap().to_string();
        assert!(std::path::Path::new(&db_path).is_file());

        let list_res = app.oneshot(get_request("/v1/instances")).await.unwrap();
        let body = body_json(list_res).await;
        assert_eq!(body["instances"].as_array().unwrap().len(), 2);
    }

    #[tokio::test]
    async fn switch_to_new_instance_and_back() {
        let (mut state, _guard) = test_state();
        state.settings.rate_limit_max_requests = 50;
        let app = build_router(state);

        let create_res = app
            .clone()
            .oneshot(json_request(
                "POST",
                "/v1/instances",
                serde_json::json!({"name": "Empty"}),
            ))
            .await
            .unwrap();
        let created = body_json(create_res).await;
        let id = created["id"].as_str().unwrap().to_string();

        let switch_res = app
            .clone()
            .oneshot(method_request(
                "POST",
                &format!("/v1/instances/{id}/switch"),
            ))
            .await
            .unwrap();
        assert_eq!(switch_res.status(), StatusCode::OK);
        let switch_body = body_json(switch_res).await;
        assert_eq!(switch_body["active_id"], id);
        assert_eq!(switch_body["stats"]["total_memories"], 0);

        let stats_res = app.clone().oneshot(get_request("/stats")).await.unwrap();
        let stats_body = body_json(stats_res).await;
        assert_eq!(stats_body["total_memories"], 0);
        assert_eq!(stats_body["active_instance"]["id"], id);

        let back_res = app
            .clone()
            .oneshot(method_request("POST", "/v1/instances/main/switch"))
            .await
            .unwrap();
        assert_eq!(back_res.status(), StatusCode::OK);

        let stats_res2 = app.oneshot(get_request("/stats")).await.unwrap();
        let stats_body2 = body_json(stats_res2).await;
        assert_eq!(stats_body2["active_instance"]["id"], "main");
    }

    #[tokio::test]
    async fn search_returns_503_while_switching() {
        let (mut state, _guard) = test_state();
        state.settings.rate_limit_max_requests = 50;
        state.switching.store(true, Ordering::SeqCst);
        let app = build_router(state);

        let res = app
            .oneshot(json_request(
                "POST",
                "/search",
                serde_json::json!({"query": "test"}),
            ))
            .await
            .unwrap();
        assert_eq!(res.status(), StatusCode::SERVICE_UNAVAILABLE);
    }

    #[tokio::test]
    async fn delete_requires_archived_and_not_active() {
        let (mut state, _guard) = test_state();
        state.settings.rate_limit_max_requests = 50;
        let app = build_router(state);

        let del_active = app
            .clone()
            .oneshot(method_request("DELETE", "/v1/instances/main"))
            .await
            .unwrap();
        assert_eq!(del_active.status(), StatusCode::CONFLICT);

        let create_res = app
            .clone()
            .oneshot(json_request(
                "POST",
                "/v1/instances",
                serde_json::json!({"name": "Temp"}),
            ))
            .await
            .unwrap();
        let created = body_json(create_res).await;
        let id = created["id"].as_str().unwrap().to_string();

        let del_unarchived = app
            .clone()
            .oneshot(method_request("DELETE", &format!("/v1/instances/{id}")))
            .await
            .unwrap();
        assert_eq!(del_unarchived.status(), StatusCode::CONFLICT);

        let archive_res = app
            .clone()
            .oneshot(method_request(
                "POST",
                &format!("/v1/instances/{id}/archive"),
            ))
            .await
            .unwrap();
        assert_eq!(archive_res.status(), StatusCode::OK);

        let del_res = app
            .oneshot(method_request("DELETE", &format!("/v1/instances/{id}")))
            .await
            .unwrap();
        assert_eq!(del_res.status(), StatusCode::OK);
    }

    #[tokio::test]
    async fn patch_renames_name_only() {
        let (mut state, _guard) = test_state();
        state.settings.rate_limit_max_requests = 50;
        let app = build_router(state);

        let res = app
            .oneshot(json_request(
                "PATCH",
                "/v1/instances/main",
                serde_json::json!({"name": "Casa"}),
            ))
            .await
            .unwrap();
        assert_eq!(res.status(), StatusCode::OK);
        let body = body_json(res).await;
        assert_eq!(body["name"], "Casa");
        assert_eq!(body["id"], "main");
        assert_eq!(body["slug"], "main");
    }

    #[tokio::test]
    async fn rate_limit_is_enforced() {
        let (state, _guard) = test_state();
        let app = build_router(state);
        let req = || {
            axum::http::Request::builder()
                .uri("/stats")
                .header("x-api-key", "secret")
                .header("x-forwarded-for", "1.1.1.1")
                .body(Body::empty())
                .unwrap()
        };

        let r1 = app.clone().oneshot(req()).await.unwrap();
        let r2 = app.clone().oneshot(req()).await.unwrap();
        let r3 = app.clone().oneshot(req()).await.unwrap();

        assert_eq!(r1.status(), StatusCode::OK);
        assert_eq!(r2.status(), StatusCode::OK);
        assert_eq!(r3.status(), StatusCode::TOO_MANY_REQUESTS);
    }
}

