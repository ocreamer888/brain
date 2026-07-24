# Brain Viewer React Rewrite — Design Spec

**Date:** 2026-05-25  
**Scope:** Option B — sidebar nav + four views  
**Status:** Approved, ready for implementation planning

---

## Problem

The current brain viewer (`index.html` + `app.js`, ~280 lines total) is a functional but unpolished 3-tab vanilla JS UI. It exposes a fraction of the available API surface and doesn't feel like a product. Goal: rewrite in React + Tailwind with a sidebar layout, four meaningful views, and clean component architecture — without touching the Rust server.

---

## Tech Stack

- **React 18** + **Tailwind v3** + **Vite**
- Source: `brain/rust/ui/` (new folder)
- Output: `brain/rust/static/` — `vite build` replaces existing `index.html` + `app.js` in place
- Vite config: `build.outDir: '../static'`, `build.emptyOutDir: true`
- Dev: `vite dev` proxies API calls to `localhost:8787` for hot reload
- No React Router — single SPA, `activeView` string in state
- No external state lib — React context sufficient for this scope
- Rule: "if a view needs a back button, add React Router then"

---

## Architecture

### Component Tree

```
<App>                        ← activeView, visited set, stats ctx, evalDashboard ctx
  <Sidebar>                  ← stats.total from ctx
  <Dashboard>                ← useSSEFeed() LOCAL, stats + evalDashboard from ctx
  <Search>                   ← local: query, expandedId, timelineMemoryId, observationsCache
    <MemoryCard expanded>
    <TimelineDrawer>         ← portal to document.body, owned by Search
  <Curate>                   ← local: facts, actedMap, factTypeFilter
    <MemoryCard actionable>
  <Eval>                     ← evalDashboard from ctx, calls refresh() on activation
```

### Shared Hooks (App level, exposed via context)

| Hook | Endpoint | Notes |
|------|----------|-------|
| `useStats()` | `GET /stats` | Polls every 10s via `setInterval` with cleanup. Exposes full stats object — consumers destructure what they need. |
| `useEvalDashboard()` | `GET /eval_dashboard.json` | Fetches on mount. Exposes `data` + stable `refresh()` (wrapped in `useCallback`). |

`useSSEFeed` lives inside `<Dashboard>` — not App level. Mounts/unmounts with Dashboard to avoid a permanently open HTTP stream when the user is on other views. Can be hoisted to App later if persistent accumulation across views is desired.

### Mount Strategy

Views mount on first visit and stay mounted (keep-alive). Active view controls visibility via CSS; inactive views are hidden but not unmounted. This preserves local state (Search results, Curate scroll position) without re-fetching on every visit.

```js
// App level
const [visited, setVisited] = useState(new Set(['dashboard']));
// On nav: setVisited(prev => new Set([...prev, viewId]))
// Render: {visited.has('search') && <Search hidden={activeView !== 'search'} />}
// Each view: <div className={hidden ? 'hidden' : ''}> — Tailwind 'hidden' = display:none
```

### Sidebar

- Fixed left sidebar with four nav items: Dashboard, Search, Curate, Eval
- Built as flex column — items stack naturally, extensible to 6 items (Graph, Patterns) without restructuring
- Displays live `stats.total` memory count badge, updated every 10s

---

## Views

### Dashboard

**Purpose:** Brain health at a glance + live activity feed.

**Data sources:**
- `useStats()` context — total count + breakdown by type (fact, conversation, solution, pattern, project_context) rendered as stat cards
- `useSSEFeed()` local — live stream from `GET /v1/stream`
- `useEvalDashboard()` context — latest run summary (pass/fail badge + non-fact P@1)

**SSE implementation:**
- Ring buffer: `setFeed(prev => [newItem, ...prev].slice(0, 200))` — prevents unbounded RAM growth
- `onerror` handler shows "reconnecting…" indicator in the feed so the user knows when the stream is dead vs. quiet
- `EventSource` cleanup in `useEffect` return

### Search

**Purpose:** Query the brain with type filtering and deep-dive on any result.

**Data sources:**
- `POST /v1/search_index` — debounced at 200ms (bump to 300-400ms if index calls are slow on first test)
- `POST /v1/get_observations` — fired on first card expand only, result cached in `useRef(new Map())`
- `POST /v1/timeline` — fired when Timeline button clicked on a card

**State:**
- `expandedId: string | null` — single card expanded at a time; clicking expanded card collapses it
- `timelineMemoryId: string | null` — drives the singleton TimelineDrawer
- `observationsCache: useRef(new Map())` — id → full content, never re-fetches

**UI:**
- Type filter chips above results: All, Fact, Conversation, Solution, Pattern, Project
- Results as `<MemoryCard expanded>` — type badge, project, timestamp, snippet; inline expand for full content
- `<TimelineDrawer>` — singleton, portal to `document.body`, shows ±10 surrounding memories, closes on Escape or backdrop click

### Curate

**Purpose:** Review and act on facts — promote high-value ones, reject noise.

**Data sources:**
- `POST /v1/search_index` with `memory_type: "fact"` — initial load + search
- `PATCH /memories/:id` — promote (salience: 1.0)
- `POST /feedback` — reject
- `GET /get-episode` — expand parent episode inline

**State:**
- `facts: SearchIndexRow[]`
- `actedMap: Record<id, "promoted" | "rejected">` — cards stay in list after action, visual state changes
- `factTypeFilter: string` — "all" | "named_entity" | "other"

**Filter chips:** All, named_entity, other (catch-all for missing/unknown `fact_type` — always returns results)

**Card behavior after action:** Buttons disabled, muted opacity, label "Promoted ✓" or "Rejected ✗". Card stays visible — removing it causes disorientation ("did I already do this one?").

**Episode expand:** Same inline pattern as Search for consistency.

### Eval

**Purpose:** Track retrieval quality over time.

**Data sources:**
- `useEvalDashboard()` context — `data` + `refresh()`

**Activation trigger:**
```js
useEffect(() => {
  if (activeView === 'eval') refresh();
}, [activeView, refresh]); // refresh is stable via useCallback
```

**UI:**
- Latest run: large pass/fail badge, non-fact P@1, MCP P@1, MCP gap
- Run history table, newest first, `font-variant-numeric: tabular-nums` on all numeric columns
- Empty state: "No eval runs yet. Run `python3 brain/tools/eval_suite.py` to generate results." — designed before the happy path

---

## Shared Component

### `<MemoryCard>`

Single component used across Dashboard feed, Search results, and Curate list. Three variants via props:

| Variant | Used in | Shows |
|---------|---------|-------|
| `compact` | Dashboard feed | type badge, timestamp, snippet (no actions) |
| `expanded` | Search | type badge, project, timestamp, snippet + inline expand for full content + Timeline button |
| `actionable` | Curate | type badge, project, timestamp, snippet + Promote/Reject buttons + Episode expand |

Build this first before the views — it's the shared primitive everything depends on.

---

## API Surface Used

| Endpoint | Method | Used by |
|----------|--------|---------|
| `/stats` | GET | Sidebar, Dashboard |
| `/v1/stream` | GET (SSE) | Dashboard |
| `/v1/search_index` | POST | Search, Curate |
| `/v1/get_observations` | POST | Search (on expand) |
| `/v1/timeline` | POST | Search (TimelineDrawer) |
| `/get-episode` | GET | Curate (episode expand) |
| `/memories/:id` | PATCH | Curate (promote) |
| `/feedback` | POST | Curate (reject) |
| `/eval_dashboard.json` | GET | Dashboard (summary), Eval (full) |

No new backend endpoints required.

---

## Error & Loading States

### Error States Convention

REST errors: show an inline error message in place of the data, with a retry button. No toast notifications. Curate action failures (promote/reject) re-enable the buttons and show a small error label on the card.

### Loading States Convention

Skeletons: 3 placeholder shimmer cards on Curate and Search first load. Spinner on stat cards while `/stats` resolves. Subsequent refreshes keep showing stale data while re-fetching — no flash of empty content on re-entry.

---

## Edge Cases

### Curate — Empty Query Sentinel

`POST /v1/search_index` requires a non-empty query string. Embedding an empty string produces unreliable cosine results; BM25 returns nothing. On initial load (no user input), send `{ query: "fact", memory_type: "fact", n: 30 }` as the sentinel — same pattern the existing `app.js` uses.

---

## Out of Scope

- Graph view (needs NER entity extraction pipeline first — ML-Bio T2)
- Pattern/Trajectory view (needs temporal aggregation endpoint)
- Sidebar designed to accept both as future items without restructuring
