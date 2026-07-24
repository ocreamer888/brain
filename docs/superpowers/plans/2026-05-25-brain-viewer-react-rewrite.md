# Brain Viewer React Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the vanilla JS brain viewer with a React 18 + Tailwind v3 + Vite SPA featuring a sidebar layout and four views: Dashboard, Search, Curate, Eval.

**Architecture:** Vite builds to `brain/rust/static/` (same folder the Rust server embeds via rust-embed). No new API endpoints except one small addition: `by_type` counts on the existing `/stats` response. React context holds shared hooks at App level; each view owns its local state.

**Tech Stack:** React 18, Tailwind CSS v3, Vite 5, PostCSS, Node 18+

---

## Build Workflows

**Dev (hot reload):**
```bash
cd brain/rust/ui
npm run dev   # Vite proxies /v1/*, /stats, etc. to localhost:8787
# Open http://localhost:5173
```

**Production:**
```bash
cd brain/rust/ui && npm run build   # outputs to brain/rust/static/
cd brain/rust && cargo build --release   # re-embeds static files via rust-embed
# Restart brain_api
```

---

## File Map

**Backend changes (small — one new SQL method, one struct field):**
- Modify: `brain/rust/src/types.rs` — add `by_type` field to `BrainStats`
- Modify: `brain/rust/src/store.rs` — add `count_memories_by_type()` method
- Modify: `brain/rust/src/brain.rs` — populate `by_type` in `get_stats()`
- Modify: `brain/rust/src/bin/brain_api.rs` — add `by_type` to `/stats` JSON response

**Frontend (all new):**
```
brain/rust/ui/
├── package.json
├── vite.config.js
├── index.html
├── tailwind.config.js
├── postcss.config.js
└── src/
    ├── main.jsx                   ← React root mount
    ├── App.jsx                    ← activeView, visited set, context providers, layout
    ├── context/
    │   ├── StatsContext.jsx       ← useStats hook + provider (polls /stats every 10s)
    │   └── EvalContext.jsx        ← useEvalDashboard hook + provider
    ├── components/
    │   ├── Sidebar.jsx            ← nav items, stats.total badge
    │   ├── MemoryCard.jsx         ← compact | expanded | actionable variants
    │   └── TimelineDrawer.jsx     ← portal to document.body, singleton
    └── views/
        ├── Dashboard.jsx          ← useSSEFeed (local), stat cards, live feed, eval summary
        ├── Search.jsx             ← search input, type filters, expandable cards
        ├── Curate.jsx             ← facts list, promote/reject actions
        └── Eval.jsx               ← run history table, latest metrics
```

---

## Task 0: Add `by_type` to `/stats` backend

**Files:**
- Modify: `brain/rust/src/types.rs`
- Modify: `brain/rust/src/store.rs`
- Modify: `brain/rust/src/brain.rs`
- Modify: `brain/rust/src/bin/brain_api.rs`

- [ ] **Step 1: Add `by_type` to `BrainStats`**

In `brain/rust/src/types.rs`, find `BrainStats` (line ~194) and add the new field:

```rust
pub struct BrainStats {
    pub total_memories: usize,
    pub total_sessions: usize,
    pub save_count_this_session: usize,
    pub feedback_events_total: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub feedback_last_event_ts: Option<String>,
    pub by_type: std::collections::HashMap<String, usize>,
}
```

- [ ] **Step 2: Add `count_memories_by_type` to `Store`**

In `brain/rust/src/store.rs`, after `count_memories()` (line ~444), add:

```rust
pub fn count_memories_by_type(&self) -> Result<std::collections::HashMap<String, usize>, BrainError> {
    let mut stmt = self.conn
        .prepare("SELECT type, COUNT(*) FROM memories GROUP BY type")
        .map_err(|e| BrainError::Database(e.to_string()))?;
    let mut map = std::collections::HashMap::new();
    let rows = stmt.query_map([], |row| {
        Ok((row.get::<_, String>(0)?, row.get::<_, usize>(1)?))
    }).map_err(|e| BrainError::Database(e.to_string()))?;
    for row in rows {
        let (raw_type, count) = row.map_err(|e| BrainError::Database(e.to_string()))?;
        // raw_type is JSON-serialized, e.g. `"fact"` — strip surrounding quotes
        let key = raw_type.trim_matches('"').to_string();
        map.insert(key, count);
    }
    Ok(map)
}
```

- [ ] **Step 3: Populate `by_type` in `get_stats()`**

In `brain/rust/src/brain.rs`, update `get_stats()` (line ~380):

```rust
pub fn get_stats(&self) -> Result<BrainStats, BrainError> {
    Ok(BrainStats {
        total_memories: self.store.count_memories()?,
        total_sessions: self.store.count_sessions()?,
        save_count_this_session: self.save_count.load(Ordering::Relaxed),
        feedback_events_total: self.store.count_feedback_events()?,
        feedback_last_event_ts: self.store.feedback_last_event_ts()?,
        by_type: self.store.count_memories_by_type()?,
    })
}
```

- [ ] **Step 4: Serialize `by_type` in the `/stats` handler**

In `brain/rust/src/bin/brain_api.rs`, update the `stats` handler (line ~422):

```rust
async fn stats(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<ApiError>)> {
    let start = Instant::now();
    authorize_and_rate_limit(&state, &headers)?;
    let brain = open_brain(&state).map_err(internal_err)?;
    let stats = brain.get_stats().map_err(internal_err)?;
    let response = Json(serde_json::json!({
        "total_memories": stats.total_memories,
        "total_sessions": stats.total_sessions,
        "save_count_this_session": stats.save_count_this_session,
        "feedback_events_total": stats.feedback_events_total,
        "feedback_last_event_ts": stats.feedback_last_event_ts,
        "by_type": stats.by_type,
    }));
    log_request("GET", "/stats", StatusCode::OK, start);
    Ok(response)
}
```

- [ ] **Step 5: Build and verify**

```bash
cd brain/rust && cargo build 2>&1 | tail -5
```

Expected: `Finished` with no errors.

```bash
curl -s http://localhost:8787/stats | python3 -m json.tool
```

Expected: JSON with `by_type` object like `{ "fact": 14758, "conversation": 2000, ... }`.

- [ ] **Step 6: Commit**

```bash
git add brain/rust/src/types.rs brain/rust/src/store.rs brain/rust/src/brain.rs brain/rust/src/bin/brain_api.rs
git commit -m "feat(api): add by_type breakdown to /stats response"
```

---

## Task 1: Scaffold Vite Project

**Files:**
- Create: `brain/rust/ui/package.json`
- Create: `brain/rust/ui/vite.config.js`
- Create: `brain/rust/ui/index.html`
- Create: `brain/rust/ui/tailwind.config.js`
- Create: `brain/rust/ui/postcss.config.js`
- Create: `brain/rust/ui/src/main.jsx`
- Create: `brain/rust/ui/src/index.css`

- [ ] **Step 1: Create `package.json`**

Create `brain/rust/ui/package.json`:

```json
{
  "name": "brain-viewer",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.3.1",
    "autoprefixer": "^10.4.20",
    "postcss": "^8.4.49",
    "tailwindcss": "^3.4.15",
    "vite": "^5.4.11"
  }
}
```

- [ ] **Step 2: Create `vite.config.js`**

Create `brain/rust/ui/vite.config.js`:

```js
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: '../static',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/v1': 'http://localhost:8787',
      '/stats': 'http://localhost:8787',
      '/search': 'http://localhost:8787',
      '/save': 'http://localhost:8787',
      '/memories': 'http://localhost:8787',
      '/feedback': 'http://localhost:8787',
      '/reflect': 'http://localhost:8787',
      '/get-episode': 'http://localhost:8787',
      '/eval_dashboard.json': 'http://localhost:8787',
      '/list': 'http://localhost:8787',
    },
  },
})
```

- [ ] **Step 3: Create `tailwind.config.js`**

Create `brain/rust/ui/tailwind.config.js`:

```js
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      fontFamily: {
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      colors: {
        surface: '#0a0a0a',
        panel: '#111111',
        border: '#222222',
      },
    },
  },
  plugins: [],
}
```

- [ ] **Step 4: Create `postcss.config.js`**

Create `brain/rust/ui/postcss.config.js`:

```js
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}
```

- [ ] **Step 5: Create `index.html`**

Create `brain/rust/ui/index.html`:

```html
<!doctype html>
<html lang="en" class="h-full">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Brain Viewer</title>
  </head>
  <body class="h-full bg-black text-white">
    <div id="root" class="h-full"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
```

- [ ] **Step 6: Create `src/index.css`**

Create `brain/rust/ui/src/index.css`:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  * { box-sizing: border-box; }
  ::-webkit-scrollbar { width: 6px; }
  ::-webkit-scrollbar-track { background: #111; }
  ::-webkit-scrollbar-thumb { background: #333; border-radius: 3px; }
}
```

- [ ] **Step 7: Create `src/main.jsx`**

Create `brain/rust/ui/src/main.jsx`:

```jsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import './index.css'
import App from './App'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
```

- [ ] **Step 8: Create a placeholder `src/App.jsx`**

Create `brain/rust/ui/src/App.jsx`:

```jsx
export default function App() {
  return (
    <div className="flex h-full items-center justify-center text-zinc-400">
      Brain Viewer — scaffolding complete
    </div>
  )
}
```

- [ ] **Step 9: Install and verify dev server starts**

```bash
cd brain/rust/ui && npm install && npm run dev
```

Expected: Vite dev server starts, `http://localhost:5173` shows "Brain Viewer — scaffolding complete" on a black background.

- [ ] **Step 10: Commit**

```bash
cd brain/rust/ui && git add . && cd ../../.. && git add brain/rust/ui && git commit -m "feat(ui): scaffold Vite + React 18 + Tailwind v3 project"
```

---

## Task 2: `<MemoryCard>` Component

**Files:**
- Create: `brain/rust/ui/src/components/MemoryCard.jsx`

This is the shared primitive used in Dashboard (compact), Search (expanded), and Curate (actionable). Build it first — everything else depends on it.

- [ ] **Step 1: Create `src/components/MemoryCard.jsx`**

```jsx
import { useState } from 'react'

const TYPE_COLORS = {
  fact: 'bg-amber-900/50 text-amber-300',
  conversation: 'bg-blue-900/50 text-blue-300',
  solution: 'bg-green-900/50 text-green-300',
  pattern: 'bg-purple-900/50 text-purple-300',
  project_context: 'bg-pink-900/50 text-pink-300',
}

function TypeBadge({ type }) {
  const cls = TYPE_COLORS[type] ?? 'bg-zinc-800 text-zinc-400'
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-mono ${cls}`}>
      {type}
    </span>
  )
}

function CardMeta({ memory }) {
  return (
    <div className="flex items-center gap-2 flex-wrap mb-1">
      <TypeBadge type={memory.memory_type} />
      {memory.project && (
        <span className="text-xs text-zinc-500">{memory.project}</span>
      )}
      {memory.timestamp && (
        <span className="text-xs text-zinc-600">{memory.timestamp.slice(0, 10)}</span>
      )}
      {memory.id && (
        <span className="text-xs text-zinc-700 font-mono">#{memory.id.slice(0, 8)}</span>
      )}
    </div>
  )
}

// compact: Dashboard feed — type badge, timestamp, snippet only
export function CompactCard({ memory }) {
  return (
    <div className="py-2 border-b border-zinc-900">
      <CardMeta memory={memory} />
      <p className="text-sm text-zinc-300 leading-snug line-clamp-2">{memory.snippet ?? memory.content_snippet}</p>
    </div>
  )
}

// expanded: Search results — inline expansion + Timeline button
export function ExpandedCard({ memory, onExpand, fullContent, onTimeline }) {
  const [open, setOpen] = useState(false)

  function toggle() {
    if (!open) onExpand(memory.id)
    setOpen(o => !o)
  }

  return (
    <div className="py-3 border-b border-zinc-800">
      <CardMeta memory={memory} />
      <p className="text-sm text-zinc-300 mb-2 leading-snug">{memory.snippet}</p>
      <div className="flex gap-2">
        <button
          onClick={toggle}
          className="text-xs text-blue-400 hover:text-blue-300 underline"
        >
          {open ? 'Collapse' : 'Expand'}
        </button>
        <button
          onClick={() => onTimeline(memory.id)}
          className="text-xs text-zinc-500 hover:text-zinc-300"
        >
          Timeline ↗
        </button>
      </div>
      {open && (
        <div className="mt-2 p-3 bg-zinc-900 rounded border border-zinc-800 text-sm text-zinc-300 font-mono whitespace-pre-wrap break-words">
          {fullContent ?? <span className="text-zinc-600">Loading…</span>}
        </div>
      )}
    </div>
  )
}

// actionable: Curate — promote/reject buttons + episode expand
export function ActionableCard({ memory, acted, onPromote, onReject }) {
  const [episodeOpen, setEpisodeOpen] = useState(false)
  const [episodeContent, setEpisodeContent] = useState(null)
  const [promoteErr, setPromoteErr] = useState(null)
  const [rejectErr, setRejectErr] = useState(null)

  async function handleEpisode() {
    if (episodeOpen) { setEpisodeOpen(false); return }
    setEpisodeOpen(true)
    if (episodeContent) return
    try {
      const r = await fetch(`/get-episode?id=${memory.parent_id ?? memory.id}`)
      const d = await r.json()
      setEpisodeContent(d.content ?? d.error ?? '(empty)')
    } catch {
      setEpisodeContent('Failed to load episode.')
    }
  }

  const isActed = !!acted
  const cardCls = isActed ? 'opacity-40' : ''

  return (
    <div className={`py-3 border-b border-zinc-800 ${cardCls}`}>
      <CardMeta memory={memory} />
      <p className="text-sm text-zinc-300 mb-2 leading-snug">{memory.snippet}</p>
      <div className="flex items-center gap-2 flex-wrap">
        <button
          disabled={isActed}
          onClick={() => { setPromoteErr(null); onPromote(memory.id).catch(() => setPromoteErr('Promote failed')) }}
          className={`px-2 py-0.5 rounded text-xs ${isActed && acted === 'promoted' ? 'bg-green-900/30 text-green-400' : 'bg-green-900/20 text-green-400 hover:bg-green-900/50'} disabled:cursor-not-allowed`}
        >
          {acted === 'promoted' ? 'Promoted ✓' : 'Promote'}
        </button>
        <button
          disabled={isActed}
          onClick={() => { setRejectErr(null); onReject(memory.id).catch(() => setRejectErr('Reject failed')) }}
          className={`px-2 py-0.5 rounded text-xs ${isActed && acted === 'rejected' ? 'bg-red-900/30 text-red-400' : 'bg-red-900/20 text-red-400 hover:bg-red-900/50'} disabled:cursor-not-allowed`}
        >
          {acted === 'rejected' ? 'Rejected ✗' : 'Reject'}
        </button>
        {memory.parent_id && (
          <button
            onClick={handleEpisode}
            className="text-xs text-zinc-500 hover:text-zinc-300 underline"
          >
            {episodeOpen ? 'Hide episode' : 'Show episode'}
          </button>
        )}
        {promoteErr && <span className="text-xs text-red-400">{promoteErr}</span>}
        {rejectErr && <span className="text-xs text-red-400">{rejectErr}</span>}
      </div>
      {episodeOpen && (
        <div className="mt-2 p-3 bg-zinc-900 rounded border border-zinc-800 text-sm text-zinc-300 font-mono whitespace-pre-wrap break-words">
          {episodeContent ?? <span className="text-zinc-600">Loading…</span>}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Smoke-test MemoryCard in App.jsx**

Temporarily replace `src/App.jsx` to render all three variants with mock data:

```jsx
import { CompactCard, ExpandedCard, ActionableCard } from './components/MemoryCard'

const mock = {
  id: 'abc12345-dead-beef-cafe-000000000000',
  memory_type: 'fact',
  project: 'brain',
  timestamp: '2026-05-25T10:00:00Z',
  snippet: 'The /stats endpoint returns total_memories, total_sessions, and by_type breakdown.',
  parent_id: 'parent-episode-id',
}

export default function App() {
  return (
    <div className="max-w-xl mx-auto p-8 space-y-8">
      <div>
        <p className="text-zinc-500 text-xs mb-2">compact</p>
        <CompactCard memory={mock} />
      </div>
      <div>
        <p className="text-zinc-500 text-xs mb-2">expanded</p>
        <ExpandedCard
          memory={mock}
          onExpand={() => {}}
          fullContent="Full content would appear here after expansion."
          onTimeline={() => {}}
        />
      </div>
      <div>
        <p className="text-zinc-500 text-xs mb-2">actionable</p>
        <ActionableCard
          memory={mock}
          acted={null}
          onPromote={() => Promise.resolve()}
          onReject={() => Promise.resolve()}
        />
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Verify in browser**

Run `npm run dev` (if not already running). Open `http://localhost:5173`. Verify:
- Three cards render with dark background, type badge, meta info, snippet
- ExpandedCard "Expand" button toggles the content section
- ActionableCard "Promote" and "Reject" buttons disable and change label after click

- [ ] **Step 4: Commit**

```bash
git add brain/rust/ui/src/components/MemoryCard.jsx brain/rust/ui/src/App.jsx
git commit -m "feat(ui): MemoryCard component — compact, expanded, actionable variants"
```

---

## Task 3: Shared Hooks + Context

**Files:**
- Create: `brain/rust/ui/src/context/StatsContext.jsx`
- Create: `brain/rust/ui/src/context/EvalContext.jsx`

- [ ] **Step 1: Create `src/context/StatsContext.jsx`**

```jsx
import { createContext, useContext, useEffect, useState } from 'react'

const StatsContext = createContext(null)

export function StatsProvider({ children }) {
  const [stats, setStats] = useState(null)
  const [error, setError] = useState(null)

  async function fetchStats() {
    try {
      const r = await fetch('/stats')
      if (!r.ok) throw new Error(`${r.status}`)
      setStats(await r.json())
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }

  useEffect(() => {
    fetchStats()
    const id = setInterval(fetchStats, 10_000)
    return () => clearInterval(id)
  }, [])

  return (
    <StatsContext.Provider value={{ stats, error, refetch: fetchStats }}>
      {children}
    </StatsContext.Provider>
  )
}

export function useStats() {
  return useContext(StatsContext)
}
```

- [ ] **Step 2: Create `src/context/EvalContext.jsx`**

```jsx
import { createContext, useContext, useCallback, useEffect, useState } from 'react'

const EvalContext = createContext(null)

export function EvalProvider({ children }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  const refresh = useCallback(async () => {
    try {
      const r = await fetch('/eval_dashboard.json')
      if (r.status === 404) { setData({ runs: [] }); return }
      if (!r.ok) throw new Error(`${r.status}`)
      setData(await r.json())
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  return (
    <EvalContext.Provider value={{ data, error, refresh }}>
      {children}
    </EvalContext.Provider>
  )
}

export function useEval() {
  return useContext(EvalContext)
}
```

- [ ] **Step 3: Verify hooks work by wiring into App.jsx temporarily**

Update `src/App.jsx`:

```jsx
import { StatsProvider, useStats } from './context/StatsContext'
import { EvalProvider, useEval } from './context/EvalContext'

function Inner() {
  const { stats, error } = useStats()
  const { data } = useEval()
  return (
    <div className="p-8 space-y-4">
      <pre className="text-xs text-zinc-400">{JSON.stringify(stats, null, 2)}</pre>
      <pre className="text-xs text-zinc-400">{JSON.stringify(data?.runs?.length, null, 2)} eval runs</pre>
      {error && <p className="text-red-400">{error}</p>}
    </div>
  )
}

export default function App() {
  return (
    <StatsProvider>
      <EvalProvider>
        <Inner />
      </EvalProvider>
    </StatsProvider>
  )
}
```

Open `http://localhost:5173`. Verify stats JSON (including `by_type`) renders on screen and eval run count shows.

- [ ] **Step 4: Commit**

```bash
git add brain/rust/ui/src/context/ brain/rust/ui/src/App.jsx
git commit -m "feat(ui): StatsContext and EvalContext with polling and stable refresh"
```

---

## Task 4: App Shell + Sidebar

**Files:**
- Create: `brain/rust/ui/src/components/Sidebar.jsx`
- Modify: `brain/rust/ui/src/App.jsx` (final version)

- [ ] **Step 1: Create `src/components/Sidebar.jsx`**

```jsx
import { useStats } from '../context/StatsContext'

const NAV = [
  { id: 'dashboard', label: 'Dashboard', icon: '◉' },
  { id: 'search',    label: 'Search',    icon: '⌕' },
  { id: 'curate',    label: 'Curate',    icon: '✦' },
  { id: 'eval',      label: 'Eval',      icon: '▦' },
]

export default function Sidebar({ activeView, onNavigate }) {
  const { stats } = useStats()

  return (
    <aside className="flex flex-col w-48 shrink-0 border-r border-zinc-800 bg-zinc-950 h-full">
      <div className="px-4 py-4 border-b border-zinc-800">
        <p className="text-sm font-semibold text-white">Brain</p>
        {stats && (
          <p className="text-xs text-zinc-500 mt-0.5">
            {stats.total_memories.toLocaleString()} memories
          </p>
        )}
      </div>
      <nav className="flex flex-col gap-1 p-2 flex-1">
        {NAV.map(item => (
          <button
            key={item.id}
            onClick={() => onNavigate(item.id)}
            className={`flex items-center gap-2 px-3 py-2 rounded-md text-sm text-left transition-colors ${
              activeView === item.id
                ? 'bg-zinc-800 text-white'
                : 'text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200'
            }`}
          >
            <span className="text-base leading-none">{item.icon}</span>
            {item.label}
          </button>
        ))}
      </nav>
      {stats?.by_type && (
        <div className="p-4 border-t border-zinc-800">
          {Object.entries(stats.by_type)
            .sort((a, b) => b[1] - a[1])
            .map(([type, count]) => (
              <div key={type} className="flex justify-between text-xs mb-0.5">
                <span className="text-zinc-600">{type}</span>
                <span className="text-zinc-500">{count.toLocaleString()}</span>
              </div>
            ))
          }
        </div>
      )}
    </aside>
  )
}
```

- [ ] **Step 2: Write final `src/App.jsx`**

```jsx
import { useState } from 'react'
import { StatsProvider } from './context/StatsContext'
import { EvalProvider } from './context/EvalContext'
import Sidebar from './components/Sidebar'
import Dashboard from './views/Dashboard'
import Search from './views/Search'
import Curate from './views/Curate'
import Eval from './views/Eval'

function BrainApp() {
  const [activeView, setActiveView] = useState('dashboard')
  const [visited, setVisited] = useState(new Set(['dashboard']))

  function navigate(viewId) {
    setActiveView(viewId)
    setVisited(prev => new Set([...prev, viewId]))
  }

  return (
    <div className="flex h-full">
      <Sidebar activeView={activeView} onNavigate={navigate} />
      <main className="flex-1 overflow-auto bg-black">
        {visited.has('dashboard') && (
          <div className={activeView !== 'dashboard' ? 'hidden' : ''}>
            <Dashboard />
          </div>
        )}
        {visited.has('search') && (
          <div className={activeView !== 'search' ? 'hidden' : ''}>
            <Search />
          </div>
        )}
        {visited.has('curate') && (
          <div className={activeView !== 'curate' ? 'hidden' : ''}>
            <Curate />
          </div>
        )}
        {visited.has('eval') && (
          <div className={activeView !== 'eval' ? 'hidden' : ''}>
            <Eval activeView={activeView} />
          </div>
        )}
      </main>
    </div>
  )
}

export default function App() {
  return (
    <StatsProvider>
      <EvalProvider>
        <BrainApp />
      </EvalProvider>
    </StatsProvider>
  )
}
```

- [ ] **Step 3: Create placeholder views so App compiles**

Create `brain/rust/ui/src/views/Dashboard.jsx`:
```jsx
export default function Dashboard() {
  return <div className="p-8 text-zinc-400">Dashboard — coming soon</div>
}
```

Create `brain/rust/ui/src/views/Search.jsx`:
```jsx
export default function Search() {
  return <div className="p-8 text-zinc-400">Search — coming soon</div>
}
```

Create `brain/rust/ui/src/views/Curate.jsx`:
```jsx
export default function Curate() {
  return <div className="p-8 text-zinc-400">Curate — coming soon</div>
}
```

Create `brain/rust/ui/src/views/Eval.jsx`:
```jsx
export default function Eval() {
  return <div className="p-8 text-zinc-400">Eval — coming soon</div>
}
```

- [ ] **Step 4: Verify in browser**

Open `http://localhost:5173`. Verify:
- Sidebar renders on the left with four nav items
- Memory count appears under "Brain" heading
- `by_type` breakdown renders at the bottom of the sidebar
- Clicking nav items switches active highlight and shows the placeholder view

- [ ] **Step 5: Commit**

```bash
git add brain/rust/ui/src/components/Sidebar.jsx brain/rust/ui/src/App.jsx brain/rust/ui/src/views/
git commit -m "feat(ui): App shell with sidebar navigation and keep-alive view mounting"
```

---

## Task 5: Dashboard View

**Files:**
- Modify: `brain/rust/ui/src/views/Dashboard.jsx`

- [ ] **Step 1: Write `src/views/Dashboard.jsx`**

```jsx
import { useEffect, useRef, useState } from 'react'
import { useStats } from '../context/StatsContext'
import { useEval } from '../context/EvalContext'
import { CompactCard } from '../components/MemoryCard'

const TYPE_ORDER = ['fact', 'conversation', 'solution', 'pattern', 'project_context']
const TYPE_LABELS = {
  fact: 'Facts',
  conversation: 'Conversations',
  solution: 'Solutions',
  pattern: 'Patterns',
  project_context: 'Projects',
}

function StatCard({ label, value, sub }) {
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4">
      <p className="text-xs text-zinc-500 mb-1">{label}</p>
      <p className="text-2xl font-semibold text-white tabular-nums">
        {value != null ? value.toLocaleString() : '—'}
      </p>
      {sub && <p className="text-xs text-zinc-600 mt-1">{sub}</p>}
    </div>
  )
}

function EvalSummary({ data, error }) {
  if (error) return <p className="text-xs text-red-400">Eval load failed: {error}</p>
  if (!data) return <p className="text-xs text-zinc-600">Loading eval…</p>
  const runs = data.runs ?? []
  if (!runs.length) return <p className="text-xs text-zinc-600">No eval runs yet.</p>
  const latest = runs[0]
  const pct = v => v != null ? `${(v * 100).toFixed(1)}%` : '—'
  return (
    <div className="flex items-center gap-3">
      <span className={`text-xs font-semibold px-2 py-0.5 rounded ${latest.pass ? 'bg-green-900/50 text-green-300' : 'bg-red-900/50 text-red-300'}`}>
        {latest.pass ? 'PASS' : 'FAIL'}
      </span>
      <span className="text-xs text-zinc-400">
        non-fact P@1: <strong className="text-white">{pct(latest.non_fact_p1)}</strong>
      </span>
      <span className="text-xs text-zinc-400">
        MCP P@1: <strong className="text-white">{pct(latest.mcp_p1)}</strong>
      </span>
    </div>
  )
}

function useSSEFeed() {
  const [feed, setFeed] = useState([])
  const [reconnecting, setReconnecting] = useState(false)

  useEffect(() => {
    const es = new EventSource('/v1/stream')
    es.onmessage = e => {
      try {
        const evt = JSON.parse(e.data)
        setFeed(prev => [evt, ...prev].slice(0, 200))
        setReconnecting(false)
      } catch { /* ignore parse errors */ }
    }
    es.onerror = () => setReconnecting(true)
    return () => es.close()
  }, [])

  return { feed, reconnecting }
}

export default function Dashboard() {
  const { stats, error: statsError } = useStats()
  const { data: evalData, error: evalError } = useEval()
  const { feed, reconnecting } = useSSEFeed()

  return (
    <div className="p-6 max-w-4xl">
      <h2 className="text-lg font-semibold text-white mb-4">Dashboard</h2>

      {/* Stat cards */}
      <div className="grid grid-cols-2 gap-3 mb-6">
        <StatCard
          label="Total Memories"
          value={stats?.total_memories}
          sub={statsError ? `Error: ${statsError}` : null}
        />
        <StatCard
          label="Sessions"
          value={stats?.total_sessions}
        />
        {TYPE_ORDER.map(type => (
          <StatCard
            key={type}
            label={TYPE_LABELS[type]}
            value={stats?.by_type?.[type]}
          />
        ))}
      </div>

      {/* Eval summary */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 mb-6">
        <p className="text-xs text-zinc-500 mb-2">Latest Eval Run</p>
        <EvalSummary data={evalData} error={evalError} />
      </div>

      {/* Live feed */}
      <div>
        <div className="flex items-center gap-2 mb-2">
          <p className="text-xs text-zinc-500">Live Feed</p>
          {reconnecting && (
            <span className="text-xs text-amber-400 animate-pulse">reconnecting…</span>
          )}
        </div>
        <div className="space-y-0">
          {feed.length === 0 && (
            <p className="text-xs text-zinc-700 py-4">Waiting for new memories…</p>
          )}
          {feed.map((evt, i) => (
            <CompactCard
              key={`${evt.id}-${i}`}
              memory={{
                id: evt.id,
                memory_type: evt.memory_type,
                timestamp: evt.timestamp,
                content_snippet: evt.content_snippet,
              }}
            />
          ))}
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify in browser**

Open `http://localhost:5173`, click Dashboard. Verify:
- Stat cards render (Total Memories shows the real count from `/stats`)
- `by_type` cards render with counts
- Latest eval run shows pass/fail badge and P@1 metrics
- Live feed section visible (may be empty if no new memories saved)
- Save a test memory via `curl -X POST http://localhost:8787/save -H 'content-type: application/json' -d '{"content":"test dashboard feed","memory_type":"fact","project":"test"}'` and confirm it appears in the feed within 1-2 seconds

- [ ] **Step 3: Commit**

```bash
git add brain/rust/ui/src/views/Dashboard.jsx
git commit -m "feat(ui): Dashboard view — stat cards, eval summary, live SSE feed"
```

---

## Task 6: Search View + TimelineDrawer

**Files:**
- Create: `brain/rust/ui/src/components/TimelineDrawer.jsx`
- Modify: `brain/rust/ui/src/views/Search.jsx`

- [ ] **Step 1: Create `src/components/TimelineDrawer.jsx`**

```jsx
import { useEffect, useRef } from 'react'
import ReactDOM from 'react-dom'

function TimelineEntry({ memory }) {
  return (
    <div className="py-2 border-b border-zinc-800">
      <div className="flex items-center gap-2 mb-1">
        <span className="text-xs text-zinc-600 font-mono">#{memory.id?.slice(0, 8)}</span>
        <span className="text-xs text-zinc-500">{memory.metadata?.memory_type}</span>
        <span className="text-xs text-zinc-700">
          {memory.timestamp?.slice(0, 10)}
        </span>
      </div>
      <p className="text-sm text-zinc-300 leading-snug">
        {memory.content?.slice(0, 200)}{(memory.content?.length ?? 0) > 200 ? '…' : ''}
      </p>
    </div>
  )
}

export default function TimelineDrawer({ memoryId, results, loading, error, onClose }) {
  if (!memoryId) return null

  const drawer = (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* backdrop */}
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      {/* panel */}
      <div className="relative w-96 bg-zinc-950 border-l border-zinc-800 h-full overflow-y-auto p-4 flex flex-col">
        <div className="flex items-center justify-between mb-4">
          <p className="text-sm font-semibold text-white">Timeline</p>
          <button onClick={onClose} className="text-zinc-500 hover:text-white text-lg leading-none">×</button>
        </div>
        <p className="text-xs text-zinc-600 mb-3 font-mono">anchor: #{memoryId.slice(0, 8)}</p>
        {loading && <p className="text-xs text-zinc-600">Loading…</p>}
        {error && (
          <div className="text-xs text-red-400 bg-red-900/20 rounded p-2 mb-3">
            {error}
          </div>
        )}
        {results && results.map(m => (
          <TimelineEntry key={m.id} memory={m} />
        ))}
      </div>
    </div>
  )

  return ReactDOM.createPortal(drawer, document.body)
}
```

- [ ] **Step 2: Write `src/views/Search.jsx`**

```jsx
import { useRef, useState } from 'react'
import { ExpandedCard } from '../components/MemoryCard'
import TimelineDrawer from '../components/TimelineDrawer'

const TYPES = ['all', 'fact', 'conversation', 'solution', 'pattern', 'project_context']

function debounce(fn, ms) {
  let t
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms) }
}

function SkeletonCard() {
  return (
    <div className="py-3 border-b border-zinc-800 animate-pulse">
      <div className="h-3 w-24 bg-zinc-800 rounded mb-2" />
      <div className="h-3 w-full bg-zinc-800 rounded mb-1" />
      <div className="h-3 w-3/4 bg-zinc-800 rounded" />
    </div>
  )
}

export default function Search() {
  const [query, setQuery] = useState('')
  const [typeFilter, setTypeFilter] = useState('all')
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(false)
  const [searchError, setSearchError] = useState(null)
  const [expandedId, setExpandedId] = useState(null)
  const [timelineId, setTimelineId] = useState(null)
  const [timelineResults, setTimelineResults] = useState(null)
  const [timelineLoading, setTimelineLoading] = useState(false)
  const [timelineError, setTimelineError] = useState(null)
  const observationsCache = useRef(new Map())

  const doSearch = useRef(debounce(async (q, tf) => {
    if (!q.trim()) { setResults([]); setLoading(false); return }
    setLoading(true)
    setSearchError(null)
    try {
      const body = { query: q, n: 20 }
      if (tf !== 'all') body.memory_type = tf
      const r = await fetch('/v1/search_index', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!r.ok) throw new Error(`Search failed: ${r.status}`)
      const data = await r.json()
      setResults(data.results ?? [])
    } catch (e) {
      setSearchError(e.message)
    } finally {
      setLoading(false)
    }
  }, 200)).current

  function handleInput(e) {
    const q = e.target.value
    setQuery(q)
    setLoading(true)
    doSearch(q, typeFilter)
  }

  function handleTypeFilter(type) {
    setTypeFilter(type)
    doSearch(query, type)
  }

  async function handleExpand(id) {
    if (observationsCache.current.has(id)) return
    try {
      const r = await fetch('/v1/get_observations', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ ids: [id] }),
      })
      const data = await r.json()
      const mem = (data.results ?? data.memories ?? [])[0]
      observationsCache.current.set(id, mem?.content ?? '(no content)')
    } catch {
      observationsCache.current.set(id, 'Failed to load content.')
    }
  }

  async function handleTimeline(id) {
    setTimelineId(id)
    setTimelineResults(null)
    setTimelineLoading(true)
    setTimelineError(null)
    try {
      const r = await fetch('/v1/timeline', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ anchor_id: id, before: 5, after: 5 }),
      })
      if (!r.ok) throw new Error(`Timeline failed: ${r.status}`)
      const data = await r.json()
      setTimelineResults(data.results ?? [])
    } catch (e) {
      setTimelineError(e.message)
    } finally {
      setTimelineLoading(false)
    }
  }

  return (
    <div className="p-6 max-w-3xl">
      <h2 className="text-lg font-semibold text-white mb-4">Search</h2>

      <input
        type="search"
        value={query}
        onChange={handleInput}
        placeholder="Search memories…"
        autoComplete="off"
        className="w-full bg-zinc-900 border border-zinc-700 rounded-full px-4 py-2 text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-zinc-500 mb-3"
      />

      {/* Type filter chips */}
      <div className="flex gap-2 flex-wrap mb-4">
        {TYPES.map(type => (
          <button
            key={type}
            onClick={() => handleTypeFilter(type)}
            className={`px-3 py-0.5 rounded-full text-xs border transition-colors ${
              typeFilter === type
                ? 'bg-zinc-700 border-zinc-500 text-white'
                : 'border-zinc-800 text-zinc-500 hover:border-zinc-600 hover:text-zinc-300'
            }`}
          >
            {type}
          </button>
        ))}
      </div>

      {searchError && (
        <div className="text-xs text-red-400 bg-red-900/20 rounded p-2 mb-3 flex items-center justify-between">
          {searchError}
          <button onClick={() => doSearch(query, typeFilter)} className="underline ml-2">Retry</button>
        </div>
      )}

      <div>
        {loading && results.length === 0 && (
          <>
            <SkeletonCard /><SkeletonCard /><SkeletonCard />
          </>
        )}
        {!loading && query && results.length === 0 && (
          <p className="text-sm text-zinc-600 py-4">No results for "{query}"</p>
        )}
        {results.map(row => (
          <ExpandedCard
            key={row.id}
            memory={row}
            onExpand={handleExpand}
            fullContent={observationsCache.current.get(row.id) ?? null}
            onTimeline={handleTimeline}
          />
        ))}
      </div>

      <TimelineDrawer
        memoryId={timelineId}
        results={timelineResults}
        loading={timelineLoading}
        error={timelineError}
        onClose={() => setTimelineId(null)}
      />
    </div>
  )
}
```

- [ ] **Step 3: Add Escape key handler for TimelineDrawer**

The drawer closes on backdrop click (already in TimelineDrawer). Add Escape key support. In `src/components/TimelineDrawer.jsx`, update the drawer panel opening:

Add this import and effect inside the `TimelineDrawer` component (before the `const drawer = ...` line):

```jsx
useEffect(() => {
  function onKey(e) { if (e.key === 'Escape') onClose() }
  document.addEventListener('keydown', onKey)
  return () => document.removeEventListener('keydown', onKey)
}, [onClose])
```

The `useEffect` import is already at the top. Add `useEffect` to the imports from `'react'`.

Updated full imports for `TimelineDrawer.jsx`:
```jsx
import { useEffect } from 'react'
import ReactDOM from 'react-dom'
```

- [ ] **Step 4: Check `/v1/get_observations` response shape**

The API returns observations. Verify the actual response structure:

```bash
curl -s -X POST http://localhost:8787/v1/get_observations \
  -H 'content-type: application/json' \
  -d '{"ids": ["SOME_REAL_ID_FROM_YOUR_DB"]}' | python3 -m json.tool | head -20
```

If the top-level key is not `results`, update the `handleExpand` function's extraction line accordingly. (The handler currently tries both `results` and `memories` as fallbacks.)

- [ ] **Step 5: Verify in browser**

Click Search in sidebar. Verify:
- Search input renders, type filter chips appear below it
- Typing a query (e.g., "fact") shows skeleton cards then real results
- Clicking "Expand" on a result shows full content (fetched once, cached on re-expand)
- Clicking "Timeline ↗" opens the drawer on the right side
- Pressing Escape or clicking the backdrop closes the drawer

- [ ] **Step 6: Commit**

```bash
git add brain/rust/ui/src/views/Search.jsx brain/rust/ui/src/components/TimelineDrawer.jsx
git commit -m "feat(ui): Search view with type filters, card expansion, timeline drawer"
```

---

## Task 7: Curate View

**Files:**
- Modify: `brain/rust/ui/src/views/Curate.jsx`

- [ ] **Step 1: Write `src/views/Curate.jsx`**

```jsx
import { useEffect, useRef, useState } from 'react'
import { ActionableCard } from '../components/MemoryCard'

const FACT_TYPES = ['all', 'named_entity', 'other']

function SkeletonCard() {
  return (
    <div className="py-3 border-b border-zinc-800 animate-pulse">
      <div className="h-3 w-24 bg-zinc-800 rounded mb-2" />
      <div className="h-3 w-full bg-zinc-800 rounded mb-1" />
      <div className="h-3 w-2/3 bg-zinc-800 rounded" />
    </div>
  )
}

export default function Curate() {
  const [facts, setFacts] = useState([])
  const [query, setQuery] = useState('')
  const [factTypeFilter, setFactTypeFilter] = useState('all')
  const [actedMap, setActedMap] = useState({})
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(null)
  const initialLoad = useRef(true)

  async function loadFacts(q, ftf) {
    if (initialLoad.current) setLoading(true)
    setLoadError(null)
    try {
      const effectiveQuery = q.trim() || 'fact'
      const body = { query: effectiveQuery, n: 50, memory_type: 'fact' }
      const r = await fetch('/v1/search_index', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!r.ok) throw new Error(`Load failed: ${r.status}`)
      const data = await r.json()
      let results = data.results ?? []

      // Client-side fact_type filter
      if (ftf === 'named_entity') {
        results = results.filter(r => r.fact_type === 'named_entity')
      } else if (ftf === 'other') {
        results = results.filter(r => r.fact_type !== 'named_entity')
      }

      setFacts(results)
    } catch (e) {
      setLoadError(e.message)
    } finally {
      setLoading(false)
      initialLoad.current = false
    }
  }

  useEffect(() => { loadFacts('', 'all') }, [])

  function debounce(fn, ms) {
    let t
    return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms) }
  }
  const debouncedLoad = useRef(debounce((q, ftf) => loadFacts(q, ftf), 300)).current

  function handleQuery(e) {
    const q = e.target.value
    setQuery(q)
    debouncedLoad(q, factTypeFilter)
  }

  function handleTypeFilter(ftf) {
    setFactTypeFilter(ftf)
    loadFacts(query, ftf)
  }

  async function handlePromote(id) {
    const r = await fetch(`/memories/${id}`, {
      method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ salience: 1.0 }),
    })
    if (!r.ok) throw new Error(`Promote failed: ${r.status}`)
    setActedMap(prev => ({ ...prev, [id]: 'promoted' }))
  }

  async function handleReject(id) {
    const r = await fetch('/feedback', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ event_type: 'rejected', memory_id: id, source: 'mcp' }),
    })
    if (!r.ok) throw new Error(`Reject failed: ${r.status}`)
    setActedMap(prev => ({ ...prev, [id]: 'rejected' }))
  }

  return (
    <div className="p-6 max-w-3xl">
      <h2 className="text-lg font-semibold text-white mb-4">Curate</h2>

      <input
        type="search"
        value={query}
        onChange={handleQuery}
        placeholder="Filter facts…"
        autoComplete="off"
        className="w-full bg-zinc-900 border border-zinc-700 rounded-full px-4 py-2 text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-zinc-500 mb-3"
      />

      {/* Fact type filter chips */}
      <div className="flex gap-2 mb-4">
        {FACT_TYPES.map(ft => (
          <button
            key={ft}
            onClick={() => handleTypeFilter(ft)}
            className={`px-3 py-0.5 rounded-full text-xs border transition-colors ${
              factTypeFilter === ft
                ? 'bg-zinc-700 border-zinc-500 text-white'
                : 'border-zinc-800 text-zinc-500 hover:border-zinc-600 hover:text-zinc-300'
            }`}
          >
            {ft}
          </button>
        ))}
      </div>

      {loadError && (
        <div className="text-xs text-red-400 bg-red-900/20 rounded p-2 mb-3 flex items-center justify-between">
          {loadError}
          <button onClick={() => loadFacts(query, factTypeFilter)} className="underline ml-2">Retry</button>
        </div>
      )}

      <p className="text-xs text-zinc-600 mb-3">{facts.length} facts</p>

      <div>
        {loading && (
          <><SkeletonCard /><SkeletonCard /><SkeletonCard /></>
        )}
        {!loading && facts.length === 0 && (
          <p className="text-sm text-zinc-600 py-4">No facts found.</p>
        )}
        {facts.map(fact => (
          <ActionableCard
            key={fact.id}
            memory={fact}
            acted={actedMap[fact.id] ?? null}
            onPromote={handlePromote}
            onReject={handleReject}
          />
        ))}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify `fact_type` field is present in search results**

Check a real search result to confirm the `fact_type` field exists on fact rows:

```bash
curl -s -X POST http://localhost:8787/v1/search_index \
  -H 'content-type: application/json' \
  -d '{"query": "fact", "n": 3, "memory_type": "fact"}' | python3 -m json.tool | head -30
```

If `fact_type` is absent from results, the "named_entity" and "other" filter chips will always show all results vs. no results. Note the actual field name if different and update the `.filter()` calls in `Curate.jsx` accordingly.

- [ ] **Step 3: Verify in browser**

Click Curate in sidebar. Verify:
- Facts load on first visit (skeleton cards → real content)
- Filter chips filter by fact_type
- Promote → button disables, label changes to "Promoted ✓", card dims
- Reject → button disables, label changes to "Rejected ✗", card dims
- Both: card stays in list (not removed)
- Re-navigating away and back keeps acted state (cards stay dimmed)

- [ ] **Step 4: Commit**

```bash
git add brain/rust/ui/src/views/Curate.jsx
git commit -m "feat(ui): Curate view — facts list with promote/reject, fact_type filter"
```

---

## Task 8: Eval View

**Files:**
- Modify: `brain/rust/ui/src/views/Eval.jsx`

- [ ] **Step 1: Write `src/views/Eval.jsx`**

```jsx
import { useEffect } from 'react'
import { useEval } from '../context/EvalContext'

function pct(v) {
  return v != null ? `${(v * 100).toFixed(1)}%` : '—'
}

function gap(v) {
  if (v == null) return '—'
  const sign = v >= 0 ? '+' : ''
  const cls = v <= -0.05 ? 'text-red-400' : 'text-green-400'
  return <span className={cls}>{sign}{(v * 100).toFixed(1)}pp</span>
}

function PassBadge({ pass }) {
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-semibold ${
      pass ? 'bg-green-900/50 text-green-300' : 'bg-red-900/50 text-red-300'
    }`}>
      {pass ? 'PASS' : 'FAIL'}
    </span>
  )
}

export default function Eval({ activeView }) {
  const { data, error, refresh } = useEval()

  useEffect(() => {
    if (activeView === 'eval') refresh()
  }, [activeView, refresh])

  if (error) {
    return (
      <div className="p-6">
        <h2 className="text-lg font-semibold text-white mb-4">Eval</h2>
        <div className="text-xs text-red-400 bg-red-900/20 rounded p-3 flex items-center justify-between">
          Failed to load eval data: {error}
          <button onClick={refresh} className="underline ml-2">Retry</button>
        </div>
      </div>
    )
  }

  if (!data) {
    return (
      <div className="p-6">
        <h2 className="text-lg font-semibold text-white mb-4">Eval</h2>
        <p className="text-xs text-zinc-600">Loading…</p>
      </div>
    )
  }

  const runs = data.runs ?? []

  if (!runs.length) {
    return (
      <div className="p-6">
        <h2 className="text-lg font-semibold text-white mb-4">Eval</h2>
        <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-6 text-center">
          <p className="text-sm text-zinc-400 mb-2">No eval runs yet.</p>
          <p className="text-xs text-zinc-600 font-mono">
            python3 brain/tools/eval_suite.py
          </p>
        </div>
      </div>
    )
  }

  const latest = runs[0]

  return (
    <div className="p-6 max-w-4xl">
      <h2 className="text-lg font-semibold text-white mb-4">Eval</h2>

      {/* Latest run summary */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-5 mb-6">
        <div className="flex items-center gap-3 mb-3">
          <PassBadge pass={latest.pass} />
          <p className="text-xs text-zinc-500 font-mono">{latest.run_id}</p>
        </div>
        <div className="grid grid-cols-3 gap-4">
          <div>
            <p className="text-xs text-zinc-600 mb-1">non-fact P@1</p>
            <p className="text-xl font-semibold text-white tabular-nums">{pct(latest.non_fact_p1)}</p>
          </div>
          <div>
            <p className="text-xs text-zinc-600 mb-1">MCP P@1</p>
            <p className="text-xl font-semibold text-white tabular-nums">{pct(latest.mcp_p1)}</p>
          </div>
          <div>
            <p className="text-xs text-zinc-600 mb-1">MCP gap</p>
            <p className="text-xl font-semibold tabular-nums">{gap(latest.mcp_gap)}</p>
          </div>
        </div>
      </div>

      {/* Run history table */}
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="text-left text-xs text-zinc-500 border-b border-zinc-800">
            <th className="pb-2 pr-4 font-normal">Run ID</th>
            <th className="pb-2 pr-4 font-normal">Pass</th>
            <th className="pb-2 pr-4 font-normal tabular-nums">P@1 avg</th>
            <th className="pb-2 pr-4 font-normal tabular-nums">non-fact P@1</th>
            <th className="pb-2 pr-4 font-normal tabular-nums">MCP P@1</th>
            <th className="pb-2 font-normal">MCP gap</th>
          </tr>
        </thead>
        <tbody>
          {runs.map(r => (
            <tr key={r.run_id} className="border-b border-zinc-900 text-zinc-400">
              <td className="py-2 pr-4 font-mono text-xs text-zinc-500">{r.run_id}</td>
              <td className="py-2 pr-4"><PassBadge pass={r.pass} /></td>
              <td className="py-2 pr-4 tabular-nums">{pct(r.quick_p1_avg)}</td>
              <td className="py-2 pr-4 tabular-nums">{pct(r.non_fact_p1)}</td>
              <td className="py-2 pr-4 tabular-nums">{pct(r.mcp_p1)}</td>
              <td className="py-2">{gap(r.mcp_gap)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
```

- [ ] **Step 2: Verify in browser**

Click Eval in sidebar. Verify:
- Latest run summary card renders with pass/fail badge and three metrics
- Run history table renders with all rows, numeric columns are tabular-aligned
- If no eval runs exist, empty state shows the command `python3 brain/tools/eval_suite.py`
- Navigate away and back — `refresh()` fires again (check network tab: one `/eval_dashboard.json` request per Eval visit)

- [ ] **Step 3: Commit**

```bash
git add brain/rust/ui/src/views/Eval.jsx
git commit -m "feat(ui): Eval view — latest run summary, run history table, empty state"
```

---

## Task 9: Production Build + Verify

**Files:**
- No new files — build output goes to `brain/rust/static/`

- [ ] **Step 1: Run the production build**

```bash
cd brain/rust/ui && npm run build
```

Expected output ends with something like:
```
dist/index.html             1.xx kB
dist/assets/index-[hash].js 120.xx kB │ gzip: 40.xx kB
dist/assets/index-[hash].css  8.xx kB │ gzip:  2.xx kB
```

Verify files landed in `static/`:
```bash
ls ../static/
```

Expected: `index.html`, `assets/` folder. The old `app.js` should be gone (`emptyOutDir: true` clears it).

- [ ] **Step 2: Rebuild the Rust binary to re-embed static files**

```bash
cd brain/rust && cargo build --release 2>&1 | tail -3
```

Expected: `Finished release [optimized] target(s)`.

- [ ] **Step 3: Restart brain_api and verify**

```bash
# Kill existing brain_api if running
pkill -f brain_api || true
./target/release/brain_api &
sleep 1
curl -s http://localhost:8787/ -o /dev/null -w "%{http_code}\n"
```

Expected: `301` (redirect to `/static/index.html`).

- [ ] **Step 4: Open production build in browser**

Open `http://localhost:8787` in a browser. Verify:
- App loads (no dev server, served from Rust)
- All four views navigate correctly
- Stats load and update
- Search returns results
- Curate loads facts

- [ ] **Step 5: Final commit**

```bash
cd brain/rust && git add ui/ && git commit -m "feat(ui): brain viewer React rewrite complete — Dashboard, Search, Curate, Eval"
```

---

## Self-Review Checklist

- [x] **Task 0** covers `by_type` on `/stats` (spec: Dashboard stat cards by type)
- [x] **Task 1** covers Vite scaffold, Tailwind, dev proxy, `emptyOutDir`
- [x] **Task 2** covers `<MemoryCard>` with compact/expanded/actionable variants
- [x] **Task 3** covers `useStats` (10s polling) and `useEvalDashboard` (stable `refresh`)
- [x] **Task 4** covers App shell with keep-alive mount strategy and Sidebar with type breakdown
- [x] **Task 5** covers Dashboard: stat cards, SSE ring buffer (200), reconnect indicator, eval summary
- [x] **Task 6** covers Search: debounce, single `expandedId`, observations cache, singleton TimelineDrawer with portal + Escape key
- [x] **Task 7** covers Curate: `"fact"` sentinel, `actedMap`, cards stay in list, inline episode expand
- [x] **Task 8** covers Eval: refresh on activation, `tabular-nums`, empty state before happy path
- [x] **Task 9** covers build workflow and production verification
