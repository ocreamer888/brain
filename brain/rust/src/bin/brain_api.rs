use std::collections::HashMap;
use std::convert::Infallible;
use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
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
use brain::index::VectorIndex;
use brain::instances::{self, InstanceRegistry};
use brain::read_pool::ReadPool;
use brain::store::MetadataStore;
use brain::embedder::{embedder_from_env, EmbedderBackend};
use brain::summarizer::{AnthropicClient, OllamaClient, OpenRouterClient};
use brain::{
    apply_type_diversity_cap, compute_stats, rank_candidates, BrainError, FeedbackEventType,
    FeedbackSource, Memory, MemorySource, MemoryType, SearchFilter, SearchResult,
};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

#[derive(Clone)]
struct AppState {
    bind_addr: String,
    settings: ApiSettings,
    limiter: Arc<Mutex<HashMap<(String, RateClass), ClientWindow>>>,
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
    /// G6: handles for the lock-free read path (/search without graph_expand,
    /// /stats), bypassing `brain` (and its Arc<Mutex<Brain>>) entirely.
    /// Profiling found the single lock genuinely serializes every request --
    /// even /stats, which barely touches SQLite -- down to a flat ~60 req/s
    /// ceiling regardless of concurrency. Rebuilt wholesale on every
    /// instance switch, at the same moment `brain` itself is swapped (see
    /// switch_instance), so this can never point at a stale instance.
    fast: Arc<std::sync::RwLock<FastHandles>>,
}

/// See AppState.fast's doc comment. Cheap to clone (three Arcs + a float) --
/// readers hold the RwLock only for the instant it takes to clone this out,
/// then do their real work with no lock held at all.
#[derive(Clone)]
struct FastHandles {
    index: Arc<Mutex<VectorIndex>>,
    embedder: Arc<dyn EmbedderBackend>,
    /// None when the active instance is a `:memory:` DB (tests only --
    /// SQLite in-memory databases don't support independent connections to
    /// "the same" database). Handlers fall back to the locked path.
    read_pool: Option<Arc<ReadPool>>,
    hybrid_alpha: f32,
    /// In-process save counter, not in SQLite -- see Brain::save_count_handle.
    save_count: Arc<AtomicUsize>,
}

impl FastHandles {
    fn from_brain(brain: &Brain, db_path: &str) -> Self {
        let read_pool = if db_path == ":memory:" {
            None
        } else {
            match ReadPool::open(db_path, 4) {
                Ok(p) => Some(Arc::new(p)),
                Err(e) => {
                    eprintln!(
                        "[BRAIN API] warning: failed to open read pool for {db_path}: {e} \
                         -- /search and /stats will use the locked path until the next switch"
                    );
                    None
                }
            }
        };
        Self {
            index: brain.index_handle(),
            embedder: brain.embedder_handle(),
            read_pool,
            hybrid_alpha: brain.hybrid_alpha(),
            save_count: brain.save_count_handle(),
        }
    }
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

/// Rate-limit bucket class. Reads and writes get independent budgets per
/// client so a read flood (evals, MCP searches, ad-hoc scripts) can no longer
/// starve hook saves on the shared "local" key — see V-17.
#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
enum RateClass {
    Read,
    Write,
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
    /// Wire name: `extracted_by`. `derived_from` is its own field, not a serde
    /// `alias`, because `alias` makes serde error on "duplicate field" if a
    /// caller's JSON has both keys -- see `extracted_by()` below for the merge.
    #[serde(default)]
    extracted_by: Option<String>,
    #[serde(default, rename = "derived_from")]
    derived_from_legacy: Option<String>,
    /// Optional entity names to link (fact → entity "mentions" edges).
    #[serde(default)]
    entities: Option<Vec<String>>,
}

impl SaveRequest {
    /// `extracted_by` if present, else the legacy `derived_from` name. If a
    /// caller sends both, `extracted_by` (the current wire name) wins.
    fn extracted_by(&self) -> Option<&str> {
        self.extracted_by.as_deref().or(self.derived_from_legacy.as_deref())
    }
}

#[derive(Debug, Serialize)]
struct SaveResponse {
    id: String,
    #[serde(default)]
    deduped: bool,
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
    /// G0 eval-only escape hatch — see SearchFilter::salience_neutral's doc
    /// comment. Default off.
    #[serde(default)]
    salience_neutral: bool,
    /// Eval-only opt-in — see SearchFilter::apply_source_quality's doc
    /// comment. Default off.
    #[serde(default)]
    apply_source_quality: bool,
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
struct ByDateRequest {
    since: String,
    #[serde(default)]
    until: Option<String>,
    #[serde(default)]
    memory_type: Option<String>,
    #[serde(default)]
    project: Option<String>,
    /// `stored` (ingest time, default) or `event` (event_time; undated rows drop out).
    #[serde(default)]
    when: Option<String>,
    #[serde(default = "default_by_date_n")]
    n: usize,
}

fn default_by_date_n() -> usize {
    8
}

#[derive(Debug, Deserialize)]
struct ProjectBriefRequest {
    project: String,
    #[serde(default = "default_brief_n")]
    n: usize,
}

fn default_brief_n() -> usize {
    5
}

#[derive(Debug, Deserialize)]
struct ByFileRequest {
    path: String,
    #[serde(default = "default_by_date_n")]
    n: usize,
}

#[derive(Debug, Deserialize)]
struct ByEntityRequest {
    name: String,
    #[serde(default = "default_by_date_n")]
    n: usize,
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
    // Off the async runtime, like the instance-switch path: opening a Brain
    // does blocking work (SQLite, embeddings, and a blocking HTTP client for
    // Ollama), which must not run inside an async context.
    let boot_path = active_path.clone();
    let boot_tx = memory_tx.clone();
    let brain = tokio::task::spawn_blocking(move || open_brain_at(&boot_path, &boot_tx))
        .await
        .expect("Brain open task panicked")
        .expect("failed to open Brain at startup");
    eprintln!(
        "[BRAIN API] Brain ready ({} memories indexed) in {:.0} ms",
        brain.get_stats().map(|s| s.total_memories).unwrap_or(0),
        boot.elapsed().as_secs_f64() * 1000.0
    );
    // Opening the read pool is blocking I/O (SQLite connections), same as
    // opening Brain itself above -- off the async runtime for the same reason.
    let fast_path = active_path.clone();
    let (fast_handles, brain) = tokio::task::spawn_blocking(move || {
        let handles = FastHandles::from_brain(&brain, &fast_path);
        (handles, brain)
    })
    .await
    .expect("FastHandles build task panicked");
    let fast = Arc::new(std::sync::RwLock::new(fast_handles));
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
        fast,
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

    spawn_atlas_auto_rebuild(state.clone());
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
        .route("/v1/by_date", post(by_date_handler))
        .route("/v1/project_brief", post(project_brief_handler))
        .route("/v1/project_brief/pin", post(pin_project_brief_handler))
        .route("/v1/project_brief/unpin", post(unpin_project_brief_handler))
        .route("/v1/follow", post(follow_handler))
        .route("/v1/by_file", post(by_file_handler))
        .route("/v1/by_entity", post(by_entity_handler))
        .route("/v1/stream", get(stream_handler))
        .route("/get-episode", get(get_episode_handler))
        .route("/entities", get(entities_handler))
        .route("/entities/top", get(top_entities_handler))
        .route("/v1/atlas/:id", get(atlas_meta_handler))
        .route("/v1/memory-atlas/:id", get(memory_atlas_handler))
        .route("/v1/memory-atlas/:id/rebuild", post(memory_atlas_rebuild_handler))
        .route("/v1/memory-atlas/:id/status", get(memory_atlas_status_handler))
        .route("/v1/atlas/:id/geometry", get(atlas_geometry_handler))
        .route("/v1/atlas/:id/labels", get(atlas_labels_handler))
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
    authorize_and_rate_limit(&state, &headers, RateClass::Read)?;
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
    authorize_and_rate_limit(&state, &headers, RateClass::Read)?;
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
    let handles = state.fast.read().unwrap_or_else(|p| p.into_inner()).clone();
    let mut value = if handles.read_pool.is_some() {
        // See the /search handler's comment: keep blocking SQLite work off
        // the async runtime's worker threads.
        let stats = tokio::task::spawn_blocking(move || {
            let pool = handles.read_pool.as_ref().expect("checked Some above");
            let conn = pool.acquire();
            compute_stats(&conn, &handles.save_count)
        })
        .await
        .expect("stats fast-path task panicked")
        .map_err(internal_err)?;
        stats_value(&stats)
    } else {
        let brain = lock_brain(&state);
        stats_json(&brain)?
    };
    value["active_instance"] = serde_json::json!({ "id": active_id, "name": active_name });
    log_request("GET", "/stats", StatusCode::OK, start);
    Ok(Json(value))
}

/// Shared stats payload (without `active_instance`) used by both `/stats`
/// and the switch handler's response.
fn stats_json(brain: &Brain) -> Result<serde_json::Value, (StatusCode, Json<ApiError>)> {
    let stats = brain.get_stats().map_err(internal_err)?;
    Ok(stats_value(&stats))
}

fn stats_value(stats: &brain::BrainStats) -> serde_json::Value {
    serde_json::json!({
        "total_memories": stats.total_memories,
        "total_sessions": stats.total_sessions,
        "save_count_this_session": stats.save_count_this_session,
        "feedback_events_total": stats.feedback_events_total,
        "feedback_last_event_ts": stats.feedback_last_event_ts,
        "by_type": stats.by_type,
    })
}

async fn save(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<SaveRequest>,
) -> Result<Json<SaveResponse>, (StatusCode, Json<ApiError>)> {
    let start = Instant::now();
    authorize_and_rate_limit(&state, &headers, RateClass::Write)?;
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
    let outcome = brain
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
            req.extracted_by(),
        )
        .map_err(internal_err)?;
    if let Some(ref names) = req.entities {
        if !outcome.deduped && !names.is_empty() {
            // Fact is already persisted; linking failure must not fail the save.
            if let Err(e) = brain.link_entities(&outcome.id, names) {
                eprintln!("link_entities failed for {}: {e}", outcome.id);
            }
        }
    }
    let response = Json(SaveResponse {
        id: outcome.id,
        deduped: outcome.deduped,
    });
    log_request("POST", "/save", StatusCode::OK, start);
    Ok(response)
}

async fn save_batch(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<SaveBatchRequest>,
) -> Result<Json<SaveBatchResponse>, (StatusCode, Json<ApiError>)> {
    let start = Instant::now();
    authorize_and_rate_limit(&state, &headers, RateClass::Write)?;
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
            item.extracted_by(),
        ) {
            Ok(outcome) => {
                if let Some(ref names) = item.entities {
                    if !outcome.deduped && !names.is_empty() {
                        // Fact is already persisted; linking failure must not fail the save.
                        if let Err(e) = brain.link_entities(&outcome.id, names) {
                            eprintln!("link_entities failed for {}: {e}", outcome.id);
                        }
                    }
                }
                accepted += 1;
                results.push(SaveBatchItemResult {
                    index: idx,
                    id: Some(outcome.id),
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
    authorize_and_rate_limit(&state, &headers, RateClass::Read)?;
    reject_if_switching(&state)?;
    let filter = SearchFilter {
        project: req.project,
        memory_type: req.memory_type.as_deref().and_then(parse_memory_type),
        exclude_superseded: req.exclude_superseded,
        alpha: req.alpha,
        graph_expand: req.graph_expand,
        salience_neutral: req.salience_neutral,
        apply_source_quality: req.apply_source_quality,
        ..SearchFilter::default()
    };

    // G6 fast path: bypass Arc<Mutex<Brain>> entirely for the common case
    // (no graph_expand -- off by default, and the one thing the pool-based
    // path doesn't implement, see rank_candidates' doc comment). Falls back
    // to the locked path if the active instance has no read pool (a
    // `:memory:` DB, tests only) or if graph_expand was explicitly requested.
    let results = if !filter.graph_expand {
        let handles = state.fast.read().unwrap_or_else(|p| p.into_inner()).clone();
        if handles.read_pool.is_some() {
            let query = req.query.clone();
            let n = req.n;
            // Blocking SQLite + embedding work must run off the async runtime's
            // worker threads (same convention as every other handler in this
            // file) -- otherwise concurrent requests starve each other for
            // Tokio worker threads even though they no longer contend for
            // Arc<Mutex<Brain>>.
            tokio::task::spawn_blocking(move || -> Result<Vec<SearchResult>, BrainError> {
                let pool = handles.read_pool.as_ref().expect("checked Some above");
                let conn = pool.acquire();
                let (scored, _embedding, type_filter_active) = rank_candidates(
                    &conn,
                    &handles.index,
                    handles.embedder.as_ref(),
                    handles.hybrid_alpha,
                    &query,
                    n,
                    Some(&filter),
                )?;
                Ok(apply_type_diversity_cap(scored, n, type_filter_active))
            })
            .await
            .expect("search fast-path task panicked")
            .map_err(internal_err)?
        } else {
            lock_brain(&state).search(&req.query, req.n, Some(filter)).map_err(internal_err)?
        }
    } else {
        lock_brain(&state).search(&req.query, req.n, Some(filter)).map_err(internal_err)?
    };
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
    authorize_and_rate_limit(&state, &headers, RateClass::Read)?;
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
    authorize_and_rate_limit(&state, &headers, RateClass::Read)?;
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

#[derive(Debug, Deserialize)]
struct TopEntitiesQuery {
    #[serde(default = "default_top_entities")]
    limit: usize,
}

fn default_top_entities() -> usize {
    12
}

/// Cap so this stays a small, cheap read; the full catalog lives on /linked.
const TOP_ENTITIES_MAX: usize = 100;

#[derive(Debug, Serialize)]
struct TopEntitiesResponse {
    entities: Vec<LinkedEntityStat>,
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
    authorize_and_rate_limit(&state, &headers, RateClass::Read)?;
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
    authorize_and_rate_limit(&state, &headers, RateClass::Read)?;
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

fn brain_db_path(state: &AppState, id: &str) -> Result<String, (StatusCode, Json<ApiError>)> {
    let reg = state.registry.lock().unwrap_or_else(|p| p.into_inner());
    brain::instances::get(&reg, id)
        .map(|r| r.db_path.clone())
        .ok_or_else(|| (StatusCode::NOT_FOUND, Json(ApiError { error: format!("no brain with id '{id}'") })))
}

/// Brains with a memory-atlas rebuild in flight (one at a time per brain).
fn atlas_rebuilds() -> &'static Mutex<std::collections::HashSet<String>> {
    static SET: std::sync::OnceLock<Mutex<std::collections::HashSet<String>>> = std::sync::OnceLock::new();
    SET.get_or_init(Default::default)
}

/// A brain's memory atlas, live: stored positions + current memories and links.
async fn memory_atlas_handler(State(state): State<AppState>, headers: HeaderMap, Path(id): Path<String>) -> Result<Response<Body>, (StatusCode, Json<ApiError>)> {
    let start = Instant::now();
    authorize_and_rate_limit(&state, &headers, RateClass::Read)?;
    let path = brain_db_path(&state, &id)?;
    let res = tokio::task::spawn_blocking(move || -> Result<Response<Body>, (StatusCode, Json<ApiError>)> {
        let conn = brain::atlas::open_read(&path).map_err(internal_err)?;
        // Changes when the layout, the live memories, or the links change.
        let run = brain::memory_atlas::current_run(&conn).map_err(internal_err)?.map(|r| r.0).unwrap_or_default();
        let (count, latest): (i64, Option<String>) = conn
            .query_row("SELECT COUNT(*), MAX(timestamp) FROM memories WHERE superseded_by IS NULL", [], |r| Ok((r.get(0)?, r.get(1)?)))
            .map_err(internal_err)?;
        let links: i64 = conn.query_row("SELECT COUNT(*) FROM edges", [], |r| r.get(0)).map_err(internal_err)?;
        let etag = format!("\"{id}:{run}:{count}:{}:{links}\"", latest.unwrap_or_default());
        if let Some(r) = atlas_not_modified(&headers, &etag) {
            return Ok(r);
        }
        let body = brain::memory_atlas::read(&conn).map_err(internal_err)?.to_string();
        Ok(Response::builder()
            .status(StatusCode::OK)
            .header(header::CONTENT_TYPE, "application/json")
            .header(header::ETAG, etag)
            .header(header::CACHE_CONTROL, "no-cache")
            .body(Body::from(body))
            .unwrap())
    })
    .await
    .map_err(internal_err)??;
    log_request("GET", "/v1/memory-atlas/:id", res.status(), start);
    Ok(res)
}

/// Start a layout rebuild in the background; poll /status. Single-flight per brain.
async fn memory_atlas_rebuild_handler(State(state): State<AppState>, headers: HeaderMap, Path(id): Path<String>) -> Result<(StatusCode, Json<serde_json::Value>), (StatusCode, Json<ApiError>)> {
    let start = Instant::now();
    authorize_and_rate_limit(&state, &headers, RateClass::Write)?;
    let path = brain_db_path(&state, &id)?;
    let started = start_atlas_rebuild(id, path);
    log_request("POST", "/v1/memory-atlas/:id/rebuild", StatusCode::ACCEPTED, start);
    Ok((StatusCode::ACCEPTED, Json(serde_json::json!({ "started": started, "running": true }))))
}

/// Run a layout rebuild for one brain in the background. False if one is already running.
fn start_atlas_rebuild(id: String, path: String) -> bool {
    if !atlas_rebuilds().lock().unwrap_or_else(|p| p.into_inner()).insert(id.clone()) {
        return false;
    }
    tokio::task::spawn_blocking(move || {
        let outcome = rusqlite::Connection::open(&path).map_err(|e| e.to_string()).and_then(|mut conn| {
            conn.busy_timeout(Duration::from_secs(15)).ok();
            brain::memory_atlas::rebuild(&mut conn).map_err(|e| e.to_string())
        });
        if let Err(e) = outcome {
            eprintln!("[BRAIN API] memory atlas rebuild failed for {id}: {e}");
        }
        atlas_rebuilds().lock().unwrap_or_else(|p| p.into_inner()).remove(&id);
    });
    true
}

/// Automatic rebuilds: every `BRAIN_ATLAS_AUTO_CHECK_SECS` (default 600) the active
/// brain is checked; once `BRAIN_ATLAS_AUTO_REBUILD` (default 200, 0 = off) or more
/// memories were saved since its layout, it is rebuilt in the background (warm start,
/// so familiar regions stay put). Brains never built are left alone.
fn atlas_auto_settings() -> (u64, i64) {
    let every = std::env::var("BRAIN_ATLAS_AUTO_CHECK_SECS").ok().and_then(|v| v.parse().ok()).unwrap_or(600);
    let after = std::env::var("BRAIN_ATLAS_AUTO_REBUILD").ok().and_then(|v| v.parse().ok()).unwrap_or(200);
    (every.max(5), after)
}

fn spawn_atlas_auto_rebuild(state: AppState) {
    let (every, after) = atlas_auto_settings();
    if after <= 0 {
        eprintln!("[BRAIN API] memory atlas auto-rebuild off");
        return;
    }
    tokio::spawn(async move {
        loop {
            tokio::time::sleep(Duration::from_secs(every)).await;
            let id = state.registry.lock().unwrap_or_else(|p| p.into_inner()).active_id.clone();
            let Ok(path) = brain_db_path(&state, &id) else { continue };
            let check = path.clone();
            let due = tokio::task::spawn_blocking(move || {
                brain::atlas::open_read(&check).and_then(|c| brain::memory_atlas::new_since_layout(&c)).ok().flatten()
            })
            .await
            .ok()
            .flatten();
            if let Some(n) = due.filter(|n| *n >= after) {
                if start_atlas_rebuild(id.clone(), path) {
                    eprintln!("[BRAIN API] memory atlas auto-rebuild for {id}: {n} new memories since the layout");
                }
            }
        }
    });
}

async fn memory_atlas_status_handler(State(state): State<AppState>, headers: HeaderMap, Path(id): Path<String>) -> Result<Json<serde_json::Value>, (StatusCode, Json<ApiError>)> {
    authorize_and_rate_limit(&state, &headers, RateClass::Read)?;
    let path = brain_db_path(&state, &id)?;
    let running = atlas_rebuilds().lock().unwrap_or_else(|p| p.into_inner()).contains(&id);
    let last = tokio::task::spawn_blocking(move || {
        brain::atlas::open_read(&path).and_then(|c| brain::memory_atlas::status(&c))
    })
    .await
    .map_err(internal_err)?
    .map_err(internal_err)?;
    let (_, after) = atlas_auto_settings();
    Ok(Json(serde_json::json!({ "running": running, "last": last, "auto_rebuild_after": if after > 0 { Some(after) } else { None } })))
}

/// Any brain's stored atlas, read-only, without switching brains.
/// Returns the connection and its version (for the ETag), or 404 if unknown.
fn atlas_source(state: &AppState, id: &str) -> Result<(rusqlite::Connection, String), (StatusCode, Json<ApiError>)> {
    let db_path = brain_db_path(state, id)?;
    let conn = brain::atlas::open_read(&db_path).map_err(internal_err)?;
    let version = brain::atlas::version(&conn).map_err(internal_err)?.unwrap_or_else(|| "none".into());
    Ok((conn, version))
}

/// `304` when the client already has this atlas version, else `None`.
fn atlas_not_modified(headers: &HeaderMap, etag: &str) -> Option<Response<Body>> {
    let fresh = headers.get(header::IF_NONE_MATCH).and_then(|v| v.to_str().ok()) == Some(etag);
    fresh.then(|| Response::builder().status(StatusCode::NOT_MODIFIED).header(header::ETAG, etag).body(Body::empty()).unwrap())
}

#[derive(Clone, Copy)]
enum AtlasPart {
    Meta,
    Geometry,
    Labels,
}

async fn atlas_part(state: AppState, headers: HeaderMap, id: String, part: AtlasPart, route: &'static str) -> Result<Response<Body>, (StatusCode, Json<ApiError>)> {
    let start = Instant::now();
    authorize_and_rate_limit(&state, &headers, RateClass::Read)?;
    let result = tokio::task::spawn_blocking(move || -> Result<Response<Body>, (StatusCode, Json<ApiError>)> {
        let (conn, version) = atlas_source(&state, &id)?;
        let etag = format!("\"{id}:{version}:{}\"", part as u8);
        if let Some(r) = atlas_not_modified(&headers, &etag) {
            return Ok(r);
        }
        let a = brain::atlas::read_columns(&conn).map_err(internal_err)?;
        let (body, kind) = match part {
            AtlasPart::Meta => (
                serde_json::json!({
                    "instance": id,
                    "config": a.config,
                    "imported_at": a.imported_at,
                    "points": a.id.len(),
                    "links": a.link_count,
                    "categories": a.categories,
                    "category_counts": a.category_counts,
                })
                .to_string()
                .into_bytes(),
                "application/json",
            ),
            AtlasPart::Geometry => (brain::atlas::geometry_bytes(&a), "application/octet-stream"),
            AtlasPart::Labels => (serde_json::json!({ "id": a.id, "label": a.label }).to_string().into_bytes(), "application/json"),
        };
        Ok(Response::builder()
            .status(StatusCode::OK)
            .header(header::CONTENT_TYPE, kind)
            .header(header::ETAG, etag)
            .header(header::CACHE_CONTROL, "no-cache")
            .body(Body::from(body))
            .unwrap())
    })
    .await
    .map_err(internal_err)??;
    log_request("GET", route, result.status(), start);
    Ok(result)
}

async fn atlas_meta_handler(State(state): State<AppState>, headers: HeaderMap, Path(id): Path<String>) -> Result<Response<Body>, (StatusCode, Json<ApiError>)> {
    atlas_part(state, headers, id, AtlasPart::Meta, "/v1/atlas/:id").await
}

async fn atlas_geometry_handler(State(state): State<AppState>, headers: HeaderMap, Path(id): Path<String>) -> Result<Response<Body>, (StatusCode, Json<ApiError>)> {
    atlas_part(state, headers, id, AtlasPart::Geometry, "/v1/atlas/:id/geometry").await
}

async fn atlas_labels_handler(State(state): State<AppState>, headers: HeaderMap, Path(id): Path<String>) -> Result<Response<Body>, (StatusCode, Json<ApiError>)> {
    atlas_part(state, headers, id, AtlasPart::Labels, "/v1/atlas/:id/labels").await
}

async fn top_entities_handler(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<TopEntitiesQuery>,
) -> Result<Json<TopEntitiesResponse>, (StatusCode, Json<ApiError>)> {
    let start = Instant::now();
    authorize_and_rate_limit(&state, &headers, RateClass::Read)?;
    reject_if_switching(&state)?;
    let limit = q.limit.min(TOP_ENTITIES_MAX);
    let brain = lock_brain(&state);
    let entities = brain
        .top_entities(limit)
        .map_err(brain_err)?
        .into_iter()
        .map(|(id, name, memory_count)| LinkedEntityStat {
            id,
            name,
            memory_count,
        })
        .collect();
    log_request("GET", "/entities/top", StatusCode::OK, start);
    Ok(Json(TopEntitiesResponse { entities }))
}

async fn link_entities_handler(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<LinkEntitiesRequest>,
) -> Result<Json<LinkEntitiesResponse>, (StatusCode, Json<ApiError>)> {
    let start = Instant::now();
    authorize_and_rate_limit(&state, &headers, RateClass::Write)?;
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
    authorize_and_rate_limit(&state, &headers, RateClass::Read)?;
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
    authorize_and_rate_limit(&state, &headers, RateClass::Read)?;
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
    authorize_and_rate_limit(&state, &headers, RateClass::Read)?;
    reject_if_switching(&state)?;
    let brain = lock_brain(&state);
    let rows = brain
        .timeline_around(&req.anchor_id, req.before, req.after)
        .map_err(brain_err)?;
    let results: Vec<serde_json::Value> = rows.iter().map(api_memory_json).collect();
    log_request("POST", "/v1/timeline", StatusCode::OK, start);
    Ok(Json(serde_json::json!({ "results": results })))
}

fn lookup_memory_json(m: &brain::lookups::CalendarMemory) -> serde_json::Value {
    serde_json::json!({
        "id": m.id,
        "timestamp": m.timestamp,
        "memory_type": m.memory_type,
        "project": m.project,
        "snippet": m.snippet,
        "active": m.active,
        "event_time": m.event_time,
    })
}

fn count_json(rows: &[brain::lookups::CalendarCount]) -> Vec<serde_json::Value> {
    rows.iter()
        .map(|c| serde_json::json!({"key": c.key, "count": c.count}))
        .collect()
}

async fn by_date_handler(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<ByDateRequest>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<ApiError>)> {
    let start = Instant::now();
    authorize_and_rate_limit(&state, &headers, RateClass::Read)?;
    reject_if_switching(&state)?;
    let window = brain::lookups::resolve_calendar_window(&req.since, req.until.as_deref())
        .map_err(|e| bad_request(&e))?;
    let memory_type = req.memory_type.unwrap_or_default();
    if !memory_type.is_empty() && parse_memory_type(&memory_type).is_none() {
        return Err(bad_request("invalid memory_type"));
    }
    let axis = brain::lookups::TimeAxis::parse(req.when.as_deref().unwrap_or("stored"))
        .map_err(|e| bad_request(&e))?;
    let project = req.project.unwrap_or_default();
    let n = req.n.clamp(1, 20);
    let brain = lock_brain(&state);
    let report = brain
        .memories_in_calendar(&window, axis, &memory_type, &project, n)
        .map_err(brain_err)?;
    log_request("POST", "/v1/by_date", StatusCode::OK, start);
    Ok(Json(serde_json::json!({
        "since": report.since,
        "until": report.until,
        "when": report.when,
        "stored": report.stored,
        "active": report.active,
        "saved_without_event_time": report.saved_without_event_time,
        "by_type": count_json(&report.by_type),
        "by_day": count_json(&report.by_day),
        "memories": report.memories.iter().map(lookup_memory_json).collect::<Vec<_>>(),
    })))
}

async fn project_brief_handler(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<ProjectBriefRequest>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<ApiError>)> {
    let start = Instant::now();
    authorize_and_rate_limit(&state, &headers, RateClass::Read)?;
    reject_if_switching(&state)?;
    let project = req.project.trim();
    if project.is_empty() {
        return Err(bad_request("project is required"));
    }
    let n = req.n.clamp(1, 8);
    let brain = lock_brain(&state);
    let report = brain.project_brief(project, n).map_err(brain_err)?;
    log_request("POST", "/v1/project_brief", StatusCode::OK, start);
    Ok(Json(serde_json::json!({
        "query": report.query,
        "matched_project": report.matched_project,
        "candidates": report.candidates.iter().map(|c| serde_json::json!({
            "project": c.project,
            "stored": c.stored,
        })).collect::<Vec<_>>(),
        "status": report.status,
        "stored": report.stored,
        "active": report.active,
        "by_type": count_json(&report.by_type),
        "pinned": report.pinned.as_ref().map(pinned_json),
        "briefs": report.briefs.iter().map(lookup_memory_json).collect::<Vec<_>>(),
    })))
}

fn pinned_json(pin: &brain::lookups::PinnedBrief) -> serde_json::Value {
    serde_json::json!({
        "memory_id": pin.memory_id,
        "pinned_at": pin.pinned_at,
        "state": pin.state,
        "memory": pin.memory.as_ref().map(lookup_memory_json),
    })
}

fn reject_lookup(err: brain::lookups::LookupReject) -> (StatusCode, Json<ApiError>) {
    match err {
        brain::lookups::LookupReject::Bad(msg) => bad_request(&msg),
        brain::lookups::LookupReject::Db(e) => brain_err(e),
    }
}

#[derive(Debug, Deserialize)]
struct PinBriefRequest {
    project: String,
    memory_id: String,
}

#[derive(Debug, Deserialize)]
struct UnpinBriefRequest {
    project: String,
}

#[derive(Debug, Deserialize)]
struct FollowRequest {
    id: String,
}

async fn pin_project_brief_handler(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<PinBriefRequest>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<ApiError>)> {
    let start = Instant::now();
    authorize_and_rate_limit(&state, &headers, RateClass::Write)?;
    reject_if_switching(&state)?;
    if req.memory_id.trim().is_empty() {
        return Err(bad_request("memory_id is required"));
    }
    let brain = lock_brain(&state);
    let outcome = brain
        .pin_project_brief(req.project.trim(), req.memory_id.trim())
        .map_err(reject_lookup)?;
    log_request("POST", "/v1/project_brief/pin", StatusCode::OK, start);
    Ok(Json(serde_json::json!({
        "project": outcome.project,
        "memory_id": outcome.memory_id,
        "pinned_at": outcome.pinned_at,
        "previous_memory_id": outcome.previous_memory_id,
    })))
}

async fn unpin_project_brief_handler(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<UnpinBriefRequest>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<ApiError>)> {
    let start = Instant::now();
    authorize_and_rate_limit(&state, &headers, RateClass::Write)?;
    reject_if_switching(&state)?;
    if req.project.trim().is_empty() {
        return Err(bad_request("project is required"));
    }
    let brain = lock_brain(&state);
    let removed = brain
        .unpin_project_brief(req.project.trim())
        .map_err(reject_lookup)?;
    log_request("POST", "/v1/project_brief/unpin", StatusCode::OK, start);
    Ok(Json(serde_json::json!({ "removed": removed })))
}

async fn follow_handler(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<FollowRequest>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<ApiError>)> {
    let start = Instant::now();
    authorize_and_rate_limit(&state, &headers, RateClass::Read)?;
    reject_if_switching(&state)?;
    if req.id.trim().is_empty() {
        return Err(bad_request("id is required"));
    }
    let brain = lock_brain(&state);
    let report = brain.follow_memory(req.id.trim()).map_err(brain_err)?;
    log_request("POST", "/v1/follow", StatusCode::OK, start);
    Ok(Json(serde_json::json!({
        "id": report.id,
        "status": report.status,
        "detail": report.detail,
        "chain": report.chain.iter().map(lookup_memory_json).collect::<Vec<_>>(),
        "predecessors": report.predecessors.iter().map(lookup_memory_json).collect::<Vec<_>>(),
    })))
}

async fn by_file_handler(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<ByFileRequest>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<ApiError>)> {
    let start = Instant::now();
    authorize_and_rate_limit(&state, &headers, RateClass::Read)?;
    reject_if_switching(&state)?;
    let path = req.path.trim();
    if path.is_empty() {
        return Err(bad_request("path is required"));
    }
    let n = req.n.clamp(1, 12);
    let brain = lock_brain(&state);
    let report = brain.memories_for_file(path, n).map_err(brain_err)?;
    log_request("POST", "/v1/by_file", StatusCode::OK, start);
    Ok(Json(serde_json::json!({
        "query": report.query,
        "status": report.status,
        "path_count": report.path_count,
        "paths": report.paths,
        "stored": report.stored,
        "memories": report.memories.iter().map(lookup_memory_json).collect::<Vec<_>>(),
    })))
}

async fn by_entity_handler(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<ByEntityRequest>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<ApiError>)> {
    let start = Instant::now();
    authorize_and_rate_limit(&state, &headers, RateClass::Read)?;
    reject_if_switching(&state)?;
    let name = req.name.trim();
    if name.is_empty() {
        return Err(bad_request("name is required"));
    }
    let n = req.n.clamp(1, 12);
    let brain = lock_brain(&state);
    let report = brain.memories_for_entity(name, n).map_err(brain_err)?;
    log_request("POST", "/v1/by_entity", StatusCode::OK, start);
    Ok(Json(serde_json::json!({
        "query": report.query,
        "name": report.name,
        "status": report.status,
        "degree": report.degree,
        "capped": report.capped,
        "memories": report.memories.iter().map(lookup_memory_json).collect::<Vec<_>>(),
    })))
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
    authorize_and_rate_limit(&state, &headers, RateClass::Write)?;
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
    authorize_and_rate_limit(&state, &headers, RateClass::Read)?;
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
    authorize_and_rate_limit(&state, &headers, RateClass::Write)?;
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
    authorize_and_rate_limit(&state, &headers, RateClass::Write)?;
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
    /// G0: defaults true when omitted -- a PATCH is always a deliberate human
    /// action (only the UI's Promote/Undo flow calls this endpoint today), so
    /// pre-existing callers that don't send this field keep their old
    /// behavior. Undo-promote explicitly sends `false` to un-pin.
    #[serde(default = "default_true")]
    salience_pinned: bool,
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
    authorize_and_rate_limit(&state, &headers, RateClass::Write)?;
    reject_if_switching(&state)?;
    if req.salience.is_none() {
        return Err(bad_request("no patchable fields provided"));
    }
    let salience = req.salience.unwrap();
    if !(0.0..=1.0).contains(&salience) {
        return Err(bad_request("salience must be 0.0–1.0"));
    }
    let pinned = req.salience_pinned;
    let brain = state.brain.clone();
    let updated = tokio::task::spawn_blocking(move || -> Result<bool, String> {
        let brain = brain.lock().unwrap_or_else(|p| p.into_inner());
        brain.update_salience(&id, salience, pinned).map_err(|e| e.to_string())
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
    authorize_and_rate_limit(&state, &headers, RateClass::Read)?;
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
    authorize_and_rate_limit(&state, &headers, RateClass::Write)?;
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
    authorize_and_rate_limit(&state, &headers, RateClass::Write)?;
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
    authorize_and_rate_limit(&state, &headers, RateClass::Write)?;
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
    authorize_and_rate_limit(&state, &headers, RateClass::Write)?;
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
    authorize_and_rate_limit(&state, &headers, RateClass::Write)?;
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
    authorize_and_rate_limit(&state, &headers, RateClass::Write)?;

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

    // Build the new instance's fast-path handles (G6) before the swap below,
    // off the async runtime -- ReadPool::open does blocking SQLite opens,
    // same reasoning as opening Brain itself just above. Must land at the
    // same moment as the brain_guard swap or a request could briefly use
    // read-path handles from the old instance with the new one now active.
    let new_fast_path = db_path.clone();
    let (new_fast, new_brain) = tokio::task::spawn_blocking(move || {
        let handles = FastHandles::from_brain(&new_brain, &new_fast_path);
        (handles, new_brain)
    })
    .await
    .expect("FastHandles rebuild task panicked");

    // Only now that the replacement Brain opened successfully do we drop the
    // previous one, by overwriting it behind the mutex. fast is swapped in
    // the same critical window so the two are never inconsistent.
    {
        let mut brain_guard = lock_brain(&state);
        *brain_guard = new_brain;
        *state.fast.write().unwrap_or_else(|p| p.into_inner()) = new_fast;
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
        MemoryType::Knowledge => "knowledge",
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
        MemorySource::Hermes => "hermes",
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
        "knowledge" => Some(MemoryType::Knowledge),
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
        "hermes" => Some(MemorySource::Hermes),
        _ => None,
    }
}

fn authorize_and_rate_limit(
    state: &AppState,
    headers: &HeaderMap,
    class: RateClass,
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
    let window = limiter.entry((client_key, class)).or_insert(ClientWindow {
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

    // extracted_by/derived_from used to be a single field with #[serde(alias =
    // "derived_from")], which makes serde error on "duplicate field" if a
    // request sends both keys. Split into two fields + a merge method instead.
    #[test]
    fn save_request_extracted_by_only() {
        let req: SaveRequest = serde_json::from_str(
            r#"{"content":"x","memory_type":"fact","extracted_by":"model-a"}"#,
        )
        .unwrap();
        assert_eq!(req.extracted_by(), Some("model-a"));
    }

    #[test]
    fn save_request_derived_from_only_legacy() {
        let req: SaveRequest = serde_json::from_str(
            r#"{"content":"x","memory_type":"fact","derived_from":"model-b"}"#,
        )
        .unwrap();
        assert_eq!(req.extracted_by(), Some("model-b"));
    }

    #[test]
    fn save_request_both_present_does_not_error_and_prefers_extracted_by() {
        let req: SaveRequest = serde_json::from_str(
            r#"{"content":"x","memory_type":"fact","extracted_by":"model-a","derived_from":"model-b"}"#,
        )
        .unwrap();
        assert_eq!(req.extracted_by(), Some("model-a"));
    }

    #[test]
    fn save_request_neither_present() {
        let req: SaveRequest =
            serde_json::from_str(r#"{"content":"x","memory_type":"fact"}"#).unwrap();
        assert_eq!(req.extracted_by(), None);
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
        let opened_brain =
            open_brain_at(&db_path.to_string_lossy(), &memory_tx).expect("open brain in test");
        let fast = Arc::new(std::sync::RwLock::new(FastHandles::from_brain(
            &opened_brain,
            &db_path.to_string_lossy(),
        )));
        let brain = Arc::new(Mutex::new(opened_brain));

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
            fast,
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

    // G6: /stats' save_count_this_session comes from an in-process
    // AtomicUsize (not SQLite), now shared into FastHandles via
    // Brain::save_count_handle so the fast path can read it too. This
    // proves a write through the normal save() path is visible to a /stats
    // call served by the fast path -- i.e. the Arc clone genuinely aliases
    // the same counter, not a stale snapshot taken at FastHandles::from_brain.
    #[tokio::test]
    async fn stats_save_count_reflects_saves_via_fast_path() {
        let (mut state, _guard) = test_state();
        state.settings.rate_limit_max_requests = 50;
        let app = build_router(state);

        let stats_before = app
            .clone()
            .oneshot(get_request("/stats"))
            .await
            .unwrap();
        let stats_before_body = body_json(stats_before).await;
        assert_eq!(stats_before_body["save_count_this_session"], 0);

        app.clone()
            .oneshot(json_request(
                "POST",
                "/save",
                serde_json::json!({"content": "g6 stats probe", "memory_type": "fact"}),
            ))
            .await
            .unwrap();

        let stats_after = app.oneshot(get_request("/stats")).await.unwrap();
        let stats_after_body = body_json(stats_after).await;
        assert_eq!(stats_after_body["save_count_this_session"], 1);
    }

    // G0 (cognitive-architecture-spec.md section 0): PATCH /memories/:id is
    // the only write path that can set salience_pinned, and it's the only
    // thing that makes salience_w affect ranking at all. Proves the default
    // (omitted salience_pinned -> true, i.e. a PATCH is always deliberate)
    // and the explicit un-pin path (Undo-promote) both land correctly.
    #[tokio::test]
    async fn patch_memory_salience_pinned_defaults_true_and_can_be_unset() {
        let (mut state, _guard) = test_state();
        state.settings.rate_limit_max_requests = 50;
        let app = build_router(state);

        let save_res = app
            .clone()
            .oneshot(json_request(
                "POST",
                "/save",
                serde_json::json!({"content": "g0 pin test content", "memory_type": "fact"}),
            ))
            .await
            .unwrap();
        let save_body = body_json(save_res).await;
        let id = save_body["id"].as_str().unwrap().to_string();

        let patch_res = app
            .clone()
            .oneshot(json_request(
                "PATCH",
                &format!("/memories/{id}"),
                serde_json::json!({"salience": 1.0}),
            ))
            .await
            .unwrap();
        assert_eq!(patch_res.status(), StatusCode::OK);

        let search_res = app
            .clone()
            .oneshot(json_request(
                "POST",
                "/search",
                serde_json::json!({"query": "g0 pin test content", "n": 5}),
            ))
            .await
            .unwrap();
        let search_body = body_json(search_res).await;
        let hit = search_body["results"]
            .as_array()
            .unwrap()
            .iter()
            .find(|r| r["id"] == id)
            .expect("saved memory must be findable");
        assert_eq!(
            hit["metadata"]["salience_pinned"], true,
            "omitting salience_pinned on PATCH must default to true"
        );

        let undo_res = app
            .clone()
            .oneshot(json_request(
                "PATCH",
                &format!("/memories/{id}"),
                serde_json::json!({"salience": 0.5, "salience_pinned": false}),
            ))
            .await
            .unwrap();
        assert_eq!(undo_res.status(), StatusCode::OK);

        let search_res2 = app
            .oneshot(json_request(
                "POST",
                "/search",
                serde_json::json!({"query": "g0 pin test content", "n": 5}),
            ))
            .await
            .unwrap();
        let search_body2 = body_json(search_res2).await;
        let hit2 = search_body2["results"]
            .as_array()
            .unwrap()
            .iter()
            .find(|r| r["id"] == id)
            .expect("saved memory must still be findable after undo");
        assert_eq!(
            hit2["metadata"]["salience_pinned"], false,
            "explicit salience_pinned:false must un-pin"
        );
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

    // G6: /search's fast path reads through `state.fast` (index + read-pool
    // handles) instead of the `Arc<Mutex<Brain>>` lock. Those handles are
    // rebuilt and swapped only at `switch_instance` time, so this test exists
    // to prove the swap actually happens -- that a search right after
    // switching instances sees the NEW instance's data, not the handles the
    // fast path had cached from the previous active instance.
    #[tokio::test]
    async fn search_after_switch_reflects_new_instance_not_stale_fast_handles() {
        let (mut state, _guard) = test_state();
        state.settings.rate_limit_max_requests = 50;
        let app = build_router(state);

        let save_main = app
            .clone()
            .oneshot(json_request(
                "POST",
                "/save",
                serde_json::json!({
                    "content": "zzz-main-only-marker-content",
                    "memory_type": "fact"
                }),
            ))
            .await
            .unwrap();
        assert_eq!(save_main.status(), StatusCode::OK);

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

        // Immediately after switching, a search for the OLD instance's
        // content must come back empty -- the new instance has zero
        // memories, so even the mock embedder's always-return-top-n
        // behavior has nothing stale to surface unless the fast path were
        // still holding the previous instance's read-pool/index.
        let stale_check = app
            .clone()
            .oneshot(json_request(
                "POST",
                "/search",
                serde_json::json!({"query": "zzz-main-only-marker-content", "n": 5}),
            ))
            .await
            .unwrap();
        let stale_body = body_json(stale_check).await;
        let stale_results = stale_body["results"].as_array().unwrap();
        assert!(
            stale_results.is_empty(),
            "search after switch returned stale data from the previous instance: {stale_body:?}"
        );

        let save_new = app
            .clone()
            .oneshot(json_request(
                "POST",
                "/save",
                serde_json::json!({
                    "content": "zzz-new-instance-only-marker",
                    "memory_type": "fact"
                }),
            ))
            .await
            .unwrap();
        assert_eq!(save_new.status(), StatusCode::OK);

        let fresh_check = app
            .clone()
            .oneshot(json_request(
                "POST",
                "/search",
                serde_json::json!({"query": "zzz-new-instance-only-marker", "n": 5}),
            ))
            .await
            .unwrap();
        let fresh_body = body_json(fresh_check).await;
        let fresh_results = fresh_body["results"].as_array().unwrap();
        assert!(
            fresh_results
                .iter()
                .any(|r| r["content"] == "zzz-new-instance-only-marker"),
            "search did not find a memory saved into the newly-active instance: {fresh_body:?}"
        );

        let back_res = app
            .clone()
            .oneshot(method_request("POST", "/v1/instances/main/switch"))
            .await
            .unwrap();
        assert_eq!(back_res.status(), StatusCode::OK);

        // And switching back must restore the fast path to main's data --
        // the new instance's marker must no longer be visible (main's
        // corpus is small, so the mock embedder's always-return-top-n
        // behavior may still surface irrelevant rows -- the check that
        // actually matters is that the new instance's exact content is
        // gone), and main's own marker must be found again.
        let after_back_new = app
            .clone()
            .oneshot(json_request(
                "POST",
                "/search",
                serde_json::json!({"query": "zzz-new-instance-only-marker", "n": 5}),
            ))
            .await
            .unwrap();
        let after_back_new_body = body_json(after_back_new).await;
        assert!(
            !after_back_new_body["results"]
                .as_array()
                .unwrap()
                .iter()
                .any(|r| r["content"] == "zzz-new-instance-only-marker"),
            "search after switching back to main still returned the other instance's memory: {after_back_new_body:?}"
        );

        let after_back_main = app
            .oneshot(json_request(
                "POST",
                "/search",
                serde_json::json!({"query": "zzz-main-only-marker-content", "n": 5}),
            ))
            .await
            .unwrap();
        let after_back_main_body = body_json(after_back_main).await;
        assert!(
            after_back_main_body["results"]
                .as_array()
                .unwrap()
                .iter()
                .any(|r| r["content"] == "zzz-main-only-marker-content"),
            "search after switching back to main did not find main's own memory: {after_back_main_body:?}"
        );
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

    // V-17: reads and writes must hold independent buckets, so a read flood
    // cannot starve a write from the same client (the observed hook failure).
    #[tokio::test]
    async fn read_flood_does_not_starve_writes() {
        let (state, _guard) = test_state(); // rate_limit_max_requests = 2
        let app = build_router(state);
        let read_req = || {
            axum::http::Request::builder()
                .uri("/stats")
                .header("x-api-key", "secret")
                .header("x-forwarded-for", "1.1.1.1")
                .body(Body::empty())
                .unwrap()
        };
        // Exhaust the read budget for this client.
        assert_eq!(app.clone().oneshot(read_req()).await.unwrap().status(), StatusCode::OK);
        assert_eq!(app.clone().oneshot(read_req()).await.unwrap().status(), StatusCode::OK);
        assert_eq!(
            app.clone().oneshot(read_req()).await.unwrap().status(),
            StatusCode::TOO_MANY_REQUESTS,
            "read bucket should be exhausted"
        );

        // A write from the SAME client still succeeds on its own bucket.
        let save_req = axum::http::Request::builder()
            .method("POST")
            .uri("/save")
            .header("x-api-key", "secret")
            .header("x-forwarded-for", "1.1.1.1")
            .header("content-type", "application/json")
            .body(Body::from(
                r#"{"content":"v17 write-bucket probe","memory_type":"fact"}"#,
            ))
            .unwrap();
        assert_eq!(
            app.clone().oneshot(save_req).await.unwrap().status(),
            StatusCode::OK,
            "write was starved by the read flood — V-17 regression"
        );
    }
}

