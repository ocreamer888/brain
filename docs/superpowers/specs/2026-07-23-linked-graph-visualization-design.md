# Linked Tab — Bipartite Force-Graph Visualization

**Date:** 2026-07-23  
**Status:** Approved for planning  
**Scope:** `brain/rust/ui` Linked tab only (no API shape changes)

## Problem

The Linked tab lists memories with expandable neighbor lists. That shows *that* links exist, but not *how* the entity graph connects. Users need a spatial, interactive view of memory↔entity relationships with focus and detail without giving up the existing filter/list affordances.

## Goals

- Replace the list-primary Linked UX with a **full-bleed canvas force graph**.
- Model a **bipartite** graph: memory nodes + entity nodes; edges = “mentions” only.
- **Click** selects and highlights (node + 1-hop); opens a **floating detail panel**.
- **Double-click** or **Focus** switches to an **ego-only** subgraph; **Back to full** restores.
- Keep **entity filter chips**; filtered-out nodes/edges **dim** in full view (not removed).
- Provide a **floating** filter/list + detail panel (not a fixed sidebar that steals canvas width).
- Target **medium** graphs (~50–200 memory nodes) with graceful behavior on the current small local corpus.

## Non-goals (v1)

- New Rust `/linked` (or other) API response shape
- Creating, editing, or deleting links/entities from the UI
- Mini-map, clustering, search-within-graph
- Changing Search/Dashboard neighbor UX
- React Flow / Cytoscape (explicitly choosing canvas + d3-force instead)
- Migrating the entire Brain Viewer UI from JSX to TypeScript

## Decisions

| Topic | Choice |
| --- | --- |
| Primary interaction | Full graph + click focus/detail |
| Chrome | Graph primary; floating modal-like panel (not docked sidebar) |
| Graph model | Bipartite memories + entities |
| Focus behavior | Highlight in place on click; ego via double-click or Focus control |
| Scale | Design for ~50–200 memories |
| Rendering | Canvas + d3-force (+ d3-zoom / d3-selection as needed) |
| New Linked code language | TypeScript (`.tsx` / `.ts`); existing JSX left as-is (`allowJs`) |

## Layout

```
┌──────────────────────────────────────────────────────────┐
│  toolbar: filters · list · refresh · focus / back        │
│──────────────────────────────────────────────────────────│
│                                                          │
│              full-bleed canvas force graph               │
│                                                          │
│                    ┌─────────────────┐                   │
│                    │ floating panel  │  (on demand)      │
│                    │ list or detail  │                   │
│                    └─────────────────┘                   │
└──────────────────────────────────────────────────────────┘
```

- Linked view uses full main-pane height/width (drop `max-w-4xl` list layout).
- Floating panel sits **bottom-right** over the canvas (~320px wide, max ~60vh tall, scrollable).
- Opens for: selected node detail, or **List** toolbar control for the active entity filter’s memories.
- **List** pins the floater open in list mode; selecting a node switches the floater to detail (list pin cleared unless user re-opens List).
- Dismiss: Esc, close control, or click empty canvas (empty-canvas dismiss skipped while List is pinned).

## Data model

### Source

`GET /linked` (existing), already returns:

- `memories[]`: `id`, `snippet`, `memory_type`, `project`, `timestamp`, `entities[]`, `neighbor_ids[]`
- `entities[]`: `id`, `name`, `memory_count`

### Client bipartite graph

Built in pure helpers (no server change):

- **Memory node:** `{ kind: 'memory', id, memory_type, snippet, project, timestamp, entityIds }`
- **Entity node:** `{ kind: 'entity', id, name, memory_count }`
- **Link:** `{ source: memoryId, target: entityId }` for each `memory.entities` entry

`neighbor_ids` remain useful for floater “related memories” copy but are **not** drawn as memory↔memory edges.

### Optional hydration

On memory select, call existing `getObservations([id])` for fuller content in the floater. Initial graph load does not need observation batches for every neighbor.

## Visual language

- **Memory nodes:** filled circles; color by `memory_type` (reuse Linked/Search type palette).
- **Entity nodes:** rounded squares with muted accent fill/stroke so they read as hubs (not circles).
- **Edges:** thin lines; brighten when incident to the selection / highlight set; otherwise dim when outside highlight or outside entity filter.
- **Labels:** entity names shown (truncated if needed); memory labels sparse — short snippet/id on hover and/or when zoomed in enough to avoid label soup.
- **Dim vs hide:** in **full** mode, out-of-filter and non-highlighted nodes dim. In **ego** mode, only the ego subgraph is simulated/drawn.

## Interaction

| Action | Result |
| --- | --- |
| Drag node | Pin/move in force sim |
| Pan / zoom | Canvas transform (d3-zoom) |
| Click node | Select; highlight node + 1-hop; open floater detail |
| Double-click node **or** Focus | Ego subgraph of that node; toolbar shows Back to full |
| Back to full | Restore full graph; keep selection highlight if still valid |
| Click empty canvas | Clear selection; close floater unless List is pinned |
| Entity filter chip | Set active filter; dim non-matching memories and unused entities/edges |
| List (toolbar) | Open/pin floater with memories for the active filter |
| Refresh | Reload `/linked` and rebuild graph |

## Components

New Linked graph code is **TypeScript (`.tsx` / `.ts`)**. Existing viewer files stay JSX; no full-UI migration in this change.

| Module | Responsibility |
| --- | --- |
| `src/views/Linked.tsx` | Load data, toolbar, mode (`full` \| `ego`), selection, floater open/close/pin (replaces `Linked.jsx`) |
| `src/components/LinkedGraph.tsx` | Canvas render loop, force sim, hit-testing, pan/zoom, highlight/ego props |
| `src/components/LinkedFloater.tsx` | Floating card UI: filter list **or** node detail |
| `src/lib/linkedGraphModel.ts` | Pure: build nodes/links, filter membership, 1-hop set, ego extract |

**TS toolchain (minimal, Linked-scoped):** add `typescript`, `@types/react`, `@types/react-dom`, and a root `tsconfig.json` that allows JS (`allowJs: true`) so existing `.jsx` keeps compiling under Vite. Type `api.js` call sites via light ambient types or small typed wrappers only as needed for Linked — do not rewrite the whole UI to TS in v1.

Dependencies: modular `d3-force`, `d3-zoom`, `d3-selection` (prefer modular packages over full `d3`) plus their `@types/*` where useful.

## State flow

1. Mount → `getLinked()` → `buildBipartiteGraph` → pass to `LinkedGraph`.
2. User filter / selection / ego → recompute highlight or subgraph → graph redraws; floater updates.
3. Memory select → optional `getObservations` → floater body.

## Errors & empty states

- Load failure: error message in toolbar area + Retry.
- Zero linked memories: empty state centered over canvas.
- Ego node with no neighbors: show single node; floater explains no mentions/neighbors.

## Testing

- **Manual smoke:** load → bipartite layout visible; click memory/entity → floater + highlight; Focus/Back; filter dims; Refresh.
- **Unit (optional, non-blocking):** pure helpers in `linkedGraphModel.ts` if/when a UI test runner exists.

## Implementation notes

- Prefer requestAnimationFrame redraw driven by force `tick`; avoid React re-render per tick (keep positions in refs).
- Rebuild simulation when the **node/link set** changes (ego swap, full reload); do not rebuild on mere highlight/dim.
- Match existing dark zinc viewer chrome; floating panel should feel like a card over the canvas, not a second route.
- After UI changes, rebuild static assets into `brain/rust/static/` as the project already does for the viewer SPA.

## Success criteria

- Linked tab shows an interactive bipartite force graph from `/linked` with no API changes.
- Click highlight + floating detail work for both memory and entity nodes.
- Ego focus and back-to-full work.
- Entity filter dims outsiders; floating list can show the filtered memory set.
- Usable at ~50–200 memory nodes on a typical laptop without freezing the tab.
