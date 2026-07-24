# Linked Tab Bipartite Force-Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Linked tab list UX with a full-bleed canvas bipartite force graph (memories + entities) plus a floating detail/list panel, using existing `GET /linked`.

**Architecture:** Pure TS model builds bipartite nodes/links from `/linked`. A canvas component owns d3-force + d3-zoom (positions in refs, no React re-render per tick). `Linked.tsx` owns selection, ego/full mode, entity filter, and floater state. New code is TypeScript; existing JSX stays with `allowJs`.

**Tech Stack:** React 18, Vite, TypeScript (`allowJs`), Tailwind, `d3-force` / `d3-zoom` / `d3-drag` / `d3-selection`, Vitest for model unit tests

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-23-linked-graph-visualization-design.md`
- UI root: `brain/rust/ui/` — build output `brain/rust/static/` (`vite build`, `base: '/static/'`)
- No Rust/API response shape changes
- Bipartite only: memory↔entity “mentions” edges; do **not** draw `neighbor_ids` as edges
- New Linked graph files: `.ts` / `.tsx`; do **not** migrate the whole UI to TS
- Prefer modular d3 packages over full `d3`
- Force tick must not trigger React re-renders (refs + rAF)
- Floating panel bottom-right (~320px), not a docked sidebar
- Commit only when the user asks (skip commit steps unless they approve commits for this plan)

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Create | `brain/rust/ui/tsconfig.json` | TS + `allowJs` for mixed UI |
| Create | `brain/rust/ui/tsconfig.node.json` | Vite config typing (optional minimal) |
| Modify | `brain/rust/ui/package.json` | deps + `test` script |
| Create | `brain/rust/ui/vitest.config.ts` | Vitest config |
| Create | `brain/rust/ui/src/lib/linkedGraphModel.ts` | Pure bipartite model helpers |
| Create | `brain/rust/ui/src/lib/linkedGraphModel.test.ts` | Unit tests for model |
| Create | `brain/rust/ui/src/lib/memoryTypeColors.ts` | Shared canvas + UI type colors |
| Create | `brain/rust/ui/src/components/LinkedGraph.tsx` | Canvas force graph |
| Create | `brain/rust/ui/src/components/LinkedFloater.tsx` | Floating list/detail card |
| Create | `brain/rust/ui/src/views/Linked.tsx` | Linked tab shell |
| Delete | `brain/rust/ui/src/views/Linked.jsx` | Replaced by `Linked.tsx` |
| Modify | `brain/rust/ui/src/App.jsx` | Import `./views/Linked` (resolves to `.tsx`) |
| Modify | `brain/rust/static/*` | Via `npm run build` only |

---

### Task 1: TypeScript toolchain + d3 + Vitest

**Files:**
- Create: `brain/rust/ui/tsconfig.json`
- Create: `brain/rust/ui/vitest.config.ts`
- Modify: `brain/rust/ui/package.json`

**Interfaces:**
- Consumes: existing Vite React app
- Produces: `tsc`/`vitest` runnable; Vite can import `.tsx`

- [ ] **Step 1: Add `tsconfig.json`**

Create `brain/rust/ui/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "isolatedModules": true,
    "moduleDetection": "force",
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "allowJs": true,
    "checkJs": false,
    "resolveJsonModule": true,
    "types": ["vitest/globals"]
  },
  "include": ["src"]
}
```

- [ ] **Step 2: Add Vitest config**

Create `brain/rust/ui/vitest.config.ts`:

```ts
import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
})
```

- [ ] **Step 3: Install dependencies and scripts**

From `brain/rust/ui/`:

```bash
npm install d3-force d3-zoom d3-drag d3-selection
npm install -D typescript vitest @types/react @types/react-dom @types/d3-force @types/d3-zoom @types/d3-drag @types/d3-selection
```

In `package.json` scripts, add:

```json
"test": "vitest run",
"test:watch": "vitest"
```

(`@types/react` / `@types/react-dom` may already exist as deps — keep a single consistent version.)

- [ ] **Step 4: Verify toolchain**

```bash
cd /Users/Shared/Code/brain/brain/rust/ui && npx tsc --noEmit && npm test
```

Expected: `tsc` exits 0; vitest exits 0 with “No test files found” **or** 0 tests — either is fine before Task 2.

- [ ] **Step 5: Commit** (only if user approved commits)

```bash
git add brain/rust/ui/package.json brain/rust/ui/package-lock.json brain/rust/ui/tsconfig.json brain/rust/ui/vitest.config.ts
git commit -m "$(cat <<'EOF'
chore(ui): add TypeScript, Vitest, and d3 graph deps

Enable allowJs mixed TS/JS for Linked graph work without migrating the whole viewer.
EOF
)"
```

---

### Task 2: Pure bipartite model (`linkedGraphModel.ts`)

**Files:**
- Create: `brain/rust/ui/src/lib/memoryTypeColors.ts`
- Create: `brain/rust/ui/src/lib/linkedGraphModel.ts`
- Test: `brain/rust/ui/src/lib/linkedGraphModel.test.ts`

**Interfaces:**
- Consumes: `/linked` JSON shape (`memories`, `entities`)
- Produces:
  - `buildBipartiteGraph(data) → { nodes: GraphNode[]; links: GraphLink[] }`
  - `oneHopIds(nodes, links, nodeId) → Set<string>`
  - `egoSubgraph(nodes, links, focusId) → { nodes; links }`
  - `filterActiveIds(nodes, links, entityFilter) → Set<string>` (ids that should be **active**/undimmed; empty filter `'all'` → all ids)

- [ ] **Step 1: Write failing tests**

Create `brain/rust/ui/src/lib/linkedGraphModel.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import {
  buildBipartiteGraph,
  egoSubgraph,
  filterActiveIds,
  oneHopIds,
  type LinkedApiResponse,
} from './linkedGraphModel'

const sample: LinkedApiResponse = {
  memories: [
    {
      id: 'm1',
      snippet: 'React app',
      memory_type: 'fact',
      project: 'brain',
      timestamp: '2026-07-01T00:00:00Z',
      entities: [
        { id: 'e-react', name: 'React' },
        { id: 'e-vite', name: 'Vite' },
      ],
      neighbor_ids: ['m2'],
    },
    {
      id: 'm2',
      snippet: 'React note',
      memory_type: 'decision',
      project: 'brain',
      timestamp: '2026-07-02T00:00:00Z',
      entities: [{ id: 'e-react', name: 'React' }],
      neighbor_ids: ['m1'],
    },
    {
      id: 'm3',
      snippet: 'SQLite',
      memory_type: 'solution',
      project: 'brain',
      timestamp: '2026-07-03T00:00:00Z',
      entities: [
        { id: 'e-vite', name: 'Vite' },
        { id: 'e-sql', name: 'SQLite' },
      ],
      neighbor_ids: ['m1'],
    },
  ],
  entities: [
    { id: 'e-react', name: 'React', memory_count: 2 },
    { id: 'e-vite', name: 'Vite', memory_count: 2 },
    { id: 'e-sql', name: 'SQLite', memory_count: 1 },
  ],
}

describe('buildBipartiteGraph', () => {
  it('builds memory+entity nodes and mentions links only', () => {
    const g = buildBipartiteGraph(sample)
    expect(g.nodes.filter((n) => n.kind === 'memory')).toHaveLength(3)
    expect(g.nodes.filter((n) => n.kind === 'entity')).toHaveLength(3)
    expect(g.links).toHaveLength(5)
    expect(g.links.some((l) => l.source === 'm1' && l.target === 'm2')).toBe(false)
  })
})

describe('oneHopIds', () => {
  it('returns focus + adjacent bipartite neighbors', () => {
    const g = buildBipartiteGraph(sample)
    const hop = oneHopIds(g.nodes, g.links, 'e-react')
    expect(hop.has('e-react')).toBe(true)
    expect(hop.has('m1')).toBe(true)
    expect(hop.has('m2')).toBe(true)
    expect(hop.has('m3')).toBe(false)
  })
})

describe('egoSubgraph', () => {
  it('keeps only focus and 1-hop nodes/links', () => {
    const g = buildBipartiteGraph(sample)
    const ego = egoSubgraph(g.nodes, g.links, 'm1')
    const ids = new Set(ego.nodes.map((n) => n.id))
    expect(ids).toEqual(new Set(['m1', 'e-react', 'e-vite']))
    expect(ego.links.every((l) => ids.has(String(l.source)) && ids.has(String(l.target)))).toBe(
      true,
    )
  })
})

describe('filterActiveIds', () => {
  it('marks only memories mentioning the entity and that entity', () => {
    const g = buildBipartiteGraph(sample)
    const active = filterActiveIds(g.nodes, g.links, 'React')
    expect(active.has('m1')).toBe(true)
    expect(active.has('m2')).toBe(true)
    expect(active.has('m3')).toBe(false)
    expect(active.has('e-react')).toBe(true)
    expect(active.has('e-sql')).toBe(false)
  })

  it('returns all ids for all', () => {
    const g = buildBipartiteGraph(sample)
    const active = filterActiveIds(g.nodes, g.links, 'all')
    expect(active.size).toBe(g.nodes.length)
  })
})
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
cd /Users/Shared/Code/brain/brain/rust/ui && npm test
```

Expected: FAIL — module `./linkedGraphModel` not found / exports missing.

- [ ] **Step 3: Add type colors helper**

Create `brain/rust/ui/src/lib/memoryTypeColors.ts`:

```ts
/** Canvas fill colors (hex) keyed by API snake_case memory_type. */
export const MEMORY_TYPE_FILL: Record<string, string> = {
  fact: '#fbbf24',
  conversation: '#60a5fa',
  solution: '#4ade80',
  pattern: '#c084fc',
  project_context: '#f472b6',
  error_lesson: '#f87171',
  decision: '#22d3ee',
  episode: '#a1a1aa',
}

export const DEFAULT_MEMORY_FILL = '#a1a1aa'
export const ENTITY_FILL = '#71717a'
export const ENTITY_STROKE = '#a1a1aa'
```

- [ ] **Step 4: Implement model**

Create `brain/rust/ui/src/lib/linkedGraphModel.ts`:

```ts
export type LinkedEntityRef = { id: string; name: string }
export type LinkedEntityStat = { id: string; name: string; memory_count: number }

export type LinkedMemoryItem = {
  id: string
  snippet: string
  memory_type: string
  project: string
  timestamp: string
  entities: LinkedEntityRef[]
  neighbor_ids: string[]
}

export type LinkedApiResponse = {
  memories: LinkedMemoryItem[]
  entities: LinkedEntityStat[]
}

export type MemoryGraphNode = {
  kind: 'memory'
  id: string
  memory_type: string
  snippet: string
  project: string
  timestamp: string
  entityIds: string[]
  neighbor_ids: string[]
}

export type EntityGraphNode = {
  kind: 'entity'
  id: string
  name: string
  memory_count: number
}

export type GraphNode = MemoryGraphNode | EntityGraphNode

export type GraphLink = {
  source: string
  target: string
}

export function buildBipartiteGraph(data: LinkedApiResponse): {
  nodes: GraphNode[]
  links: GraphLink[]
} {
  const memories = data.memories ?? []
  const entities = data.entities ?? []

  const memoryNodes: MemoryGraphNode[] = memories.map((m) => ({
    kind: 'memory',
    id: m.id,
    memory_type: m.memory_type,
    snippet: m.snippet,
    project: m.project,
    timestamp: m.timestamp,
    entityIds: (m.entities ?? []).map((e) => e.id),
    neighbor_ids: m.neighbor_ids ?? [],
  }))

  const entityNodes: EntityGraphNode[] = entities.map((e) => ({
    kind: 'entity',
    id: e.id,
    name: e.name,
    memory_count: e.memory_count,
  }))

  const links: GraphLink[] = []
  for (const m of memories) {
    for (const e of m.entities ?? []) {
      links.push({ source: m.id, target: e.id })
    }
  }

  return { nodes: [...memoryNodes, ...entityNodes], links }
}

function linkEnds(link: GraphLink): [string, string] {
  const s = typeof link.source === 'string' ? link.source : String(link.source)
  const t = typeof link.target === 'string' ? link.target : String(link.target)
  return [s, t]
}

export function oneHopIds(
  _nodes: GraphNode[],
  links: GraphLink[],
  focusId: string,
): Set<string> {
  const out = new Set<string>([focusId])
  for (const link of links) {
    const [s, t] = linkEnds(link)
    if (s === focusId) out.add(t)
    if (t === focusId) out.add(s)
  }
  return out
}

export function egoSubgraph(
  nodes: GraphNode[],
  links: GraphLink[],
  focusId: string,
): { nodes: GraphNode[]; links: GraphLink[] } {
  const keep = oneHopIds(nodes, links, focusId)
  return {
    nodes: nodes.filter((n) => keep.has(n.id)),
    links: links.filter((l) => {
      const [s, t] = linkEnds(l)
      return keep.has(s) && keep.has(t)
    }),
  }
}

/** IDs that remain undimmed for the active entity filter (`'all'` = everything). */
export function filterActiveIds(
  nodes: GraphNode[],
  links: GraphLink[],
  entityFilter: string,
): Set<string> {
  if (entityFilter === 'all') return new Set(nodes.map((n) => n.id))

  const entity = nodes.find(
    (n) => n.kind === 'entity' && (n.name === entityFilter || n.id === entityFilter),
  )
  if (!entity) return new Set()

  const active = new Set<string>([entity.id])
  for (const link of links) {
    const [s, t] = linkEnds(link)
    if (s === entity.id) active.add(t)
    if (t === entity.id) active.add(s)
  }
  return active
}

export function memoriesForFilter(
  nodes: GraphNode[],
  entityFilter: string,
): MemoryGraphNode[] {
  const memories = nodes.filter((n): n is MemoryGraphNode => n.kind === 'memory')
  if (entityFilter === 'all') return memories
  return memories.filter((m) => {
    const entity = nodes.find(
      (n) => n.kind === 'entity' && (n.name === entityFilter || n.id === entityFilter),
    )
    return entity ? m.entityIds.includes(entity.id) : false
  })
}
```

- [ ] **Step 5: Run tests — expect PASS**

```bash
cd /Users/Shared/Code/brain/brain/rust/ui && npm test
```

Expected: all tests PASS.

- [ ] **Step 6: Commit** (only if user approved commits)

```bash
git add brain/rust/ui/src/lib/linkedGraphModel.ts brain/rust/ui/src/lib/linkedGraphModel.test.ts brain/rust/ui/src/lib/memoryTypeColors.ts
git commit -m "$(cat <<'EOF'
feat(ui): add bipartite linked graph model helpers

Pure builders for mentions edges, 1-hop highlight, ego extract, and entity filter sets.
EOF
)"
```

---

### Task 3: `LinkedGraph` canvas component

**Files:**
- Create: `brain/rust/ui/src/components/LinkedGraph.tsx`

**Interfaces:**
- Consumes: `nodes`, `links` from model; `selectedId`, `highlightIds`, `activeIds`, callbacks
- Produces: interactive canvas; calls `onSelect(id | null)`, `onFocusRequest(id)` on double-click

- [ ] **Step 1: Implement `LinkedGraph.tsx`**

Create `brain/rust/ui/src/components/LinkedGraph.tsx` (full file). Use `drawRef` so selection/filter changes redraw without rebuilding the simulation:

```tsx
import { useEffect, useRef } from 'react'
import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  type Simulation,
  type SimulationNodeDatum,
} from 'd3-force'
import { drag } from 'd3-drag'
import { select } from 'd3-selection'
import { zoom, zoomIdentity } from 'd3-zoom'
import type { GraphLink, GraphNode } from '../lib/linkedGraphModel'
import {
  DEFAULT_MEMORY_FILL,
  ENTITY_FILL,
  ENTITY_STROKE,
  MEMORY_TYPE_FILL,
} from '../lib/memoryTypeColors'

type SimNode = GraphNode & SimulationNodeDatum & { x: number; y: number }
type SimLink = { source: SimNode | string; target: SimNode | string }

export type LinkedGraphProps = {
  nodes: GraphNode[]
  links: GraphLink[]
  selectedId: string | null
  /** Selection 1-hop set; `null` means no selection highlight (show filter dims only). */
  highlightIds: Set<string> | null
  /** Entity-filter active set; nodes outside are dimmed. */
  activeIds: Set<string>
  onSelect: (id: string | null) => void
  onFocusRequest: (id: string) => void
}

function nodeRadius(n: GraphNode): number {
  return n.kind === 'entity' ? 10 : 7
}

function fillRoundRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number,
) {
  if (typeof ctx.roundRect === 'function') {
    ctx.beginPath()
    ctx.roundRect(x, y, w, h, r)
    return
  }
  ctx.beginPath()
  ctx.rect(x, y, w, h)
}

export default function LinkedGraph({
  nodes,
  links,
  selectedId,
  highlightIds,
  activeIds,
  onSelect,
  onFocusRequest,
}: LinkedGraphProps) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const simRef = useRef<Simulation<SimNode, SimLink> | null>(null)
  const nodesRef = useRef<SimNode[]>([])
  const linksRef = useRef<SimLink[]>([])
  const transformRef = useRef(zoomIdentity)
  const sizeRef = useRef({ width: 800, height: 600 })
  const drawRef = useRef<() => void>(() => {})
  const propsRef = useRef({ selectedId, highlightIds, activeIds, onSelect, onFocusRequest })
  propsRef.current = { selectedId, highlightIds, activeIds, onSelect, onFocusRequest }

  useEffect(() => {
    const wrap = wrapRef.current
    const canvas = canvasRef.current
    if (!wrap || !canvas) return

    const width = wrap.clientWidth || 800
    const height = wrap.clientHeight || 600
    sizeRef.current = { width, height }
    canvas.width = width * devicePixelRatio
    canvas.height = height * devicePixelRatio
    canvas.style.width = `${width}px`
    canvas.style.height = `${height}px`

    const simNodes: SimNode[] = nodes.map((n) => {
      const prev = nodesRef.current.find((p) => p.id === n.id)
      return {
        ...n,
        x: prev?.x ?? width / 2 + (Math.random() - 0.5) * 80,
        y: prev?.y ?? height / 2 + (Math.random() - 0.5) * 80,
      }
    })
    const byId = new Map(simNodes.map((n) => [n.id, n]))
    const simLinks: SimLink[] = links.map((l) => ({
      source: byId.get(l.source) ?? l.source,
      target: byId.get(l.target) ?? l.target,
    }))

    nodesRef.current = simNodes
    linksRef.current = simLinks

    simRef.current?.stop()
    const sim = forceSimulation<SimNode>(simNodes)
      .force(
        'link',
        forceLink<SimNode, SimLink>(simLinks)
          .id((d) => d.id)
          .distance(56)
          .strength(0.4),
      )
      .force('charge', forceManyBody().strength(-120))
      .force('center', forceCenter(width / 2, height / 2))
      .force(
        'collide',
        forceCollide<SimNode>().radius((d) => nodeRadius(d) + 4),
      )
    simRef.current = sim

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    function draw() {
      const { width: w, height: h } = sizeRef.current
      const { selectedId: sel, highlightIds: hop, activeIds: active } = propsRef.current
      const t = transformRef.current
      ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0)
      ctx.clearRect(0, 0, w, h)
      ctx.save()
      ctx.translate(t.x, t.y)
      ctx.scale(t.k, t.k)

      const hopActive = hop != null && hop.size > 0

      for (const link of linksRef.current) {
        const s = link.source as SimNode
        const tg = link.target as SimNode
        if (s.x == null || tg.x == null) continue
        const idOk =
          active.has(s.id) &&
          active.has(tg.id) &&
          (!hopActive || (hop.has(s.id) && hop.has(tg.id)))
        ctx.beginPath()
        ctx.moveTo(s.x, s.y)
        ctx.lineTo(tg.x, tg.y)
        ctx.strokeStyle = idOk ? 'rgba(161,161,170,0.55)' : 'rgba(63,63,70,0.25)'
        ctx.lineWidth = idOk && hopActive ? 1.5 / t.k : 1 / t.k
        ctx.stroke()
      }

      for (const n of nodesRef.current) {
        if (n.x == null || n.y == null) continue
        const inActive = active.has(n.id)
        const inHop = !hopActive || hop!.has(n.id)
        const alpha = inActive && inHop ? 1 : 0.18
        const r = nodeRadius(n)
        ctx.globalAlpha = alpha
        if (n.kind === 'entity') {
          const size = r * 1.6
          ctx.fillStyle = ENTITY_FILL
          ctx.strokeStyle = n.id === sel ? '#fafafa' : ENTITY_STROKE
          ctx.lineWidth = (n.id === sel ? 2 : 1) / t.k
          fillRoundRect(ctx, n.x - size, n.y - size, size * 2, size * 2, 3)
          ctx.fill()
          ctx.stroke()
          if (t.k > 0.85) {
            ctx.fillStyle = '#e4e4e7'
            ctx.font = `${11 / t.k}px ui-monospace, monospace`
            ctx.textAlign = 'center'
            ctx.fillText(n.name.slice(0, 18), n.x, n.y - size - 4 / t.k)
          }
        } else {
          ctx.beginPath()
          ctx.arc(n.x, n.y, r, 0, Math.PI * 2)
          ctx.fillStyle = MEMORY_TYPE_FILL[n.memory_type] ?? DEFAULT_MEMORY_FILL
          ctx.fill()
          if (n.id === sel) {
            ctx.strokeStyle = '#fafafa'
            ctx.lineWidth = 2 / t.k
            ctx.stroke()
          }
        }
        ctx.globalAlpha = 1
      }
      ctx.restore()
    }

    drawRef.current = draw
    sim.on('tick', draw)
    draw()

    function pointerToWorld(event: MouseEvent): { x: number; y: number } {
      const rect = canvas.getBoundingClientRect()
      const x = event.clientX - rect.left
      const y = event.clientY - rect.top
      const t = transformRef.current
      return { x: (x - t.x) / t.k, y: (y - t.y) / t.k }
    }

    function hitTest(x: number, y: number): SimNode | null {
      for (let i = nodesRef.current.length - 1; i >= 0; i--) {
        const n = nodesRef.current[i]
        if (n.x == null || n.y == null) continue
        const r = nodeRadius(n) + (n.kind === 'entity' ? 4 : 2)
        const dx = n.x - x
        const dy = n.y - y
        if (dx * dx + dy * dy <= r * r) return n
      }
      return null
    }

    const zoomer = zoom<HTMLCanvasElement, unknown>()
      .scaleExtent([0.25, 4])
      .filter((event) => {
        if (event.type === 'mousedown' || event.type === 'pointerdown') {
          const p = pointerToWorld(event as MouseEvent)
          return !hitTest(p.x, p.y)
        }
        return true
      })
      .on('zoom', (event) => {
        transformRef.current = event.transform
        draw()
      })

    const canvasSel = select(canvas)
    canvasSel.call(zoomer)

    const nodeDrag = drag<HTMLCanvasElement, unknown>()
      .subject((event) => {
        const p = pointerToWorld(event.sourceEvent as MouseEvent)
        return hitTest(p.x, p.y)
      })
      .on('start', (event) => {
        if (!event.subject) return
        sim.alphaTarget(0.2).restart()
        ;(event.subject as SimNode).fx = (event.subject as SimNode).x
        ;(event.subject as SimNode).fy = (event.subject as SimNode).y
      })
      .on('drag', (event) => {
        if (!event.subject) return
        const p = pointerToWorld(event.sourceEvent as MouseEvent)
        ;(event.subject as SimNode).fx = p.x
        ;(event.subject as SimNode).fy = p.y
      })
      .on('end', (event) => {
        if (!event.subject) return
        sim.alphaTarget(0)
        ;(event.subject as SimNode).fx = null
        ;(event.subject as SimNode).fy = null
      })

    let lastClickAt = 0
    let lastClickId: string | null = null

    function onPointerUp(event: PointerEvent) {
      if (event.button !== 0) return
      const p = pointerToWorld(event)
      const hit = hitTest(p.x, p.y)
      const now = Date.now()
      if (hit && lastClickId === hit.id && now - lastClickAt < 350) {
        propsRef.current.onFocusRequest(hit.id)
        lastClickAt = 0
        lastClickId = null
        return
      }
      lastClickAt = now
      lastClickId = hit?.id ?? null
      propsRef.current.onSelect(hit ? hit.id : null)
    }

    canvas.addEventListener('pointerup', onPointerUp)
    canvasSel.call(nodeDrag)

    const ro = new ResizeObserver(() => {
      const w = wrap.clientWidth
      const h = wrap.clientHeight
      sizeRef.current = { width: w, height: h }
      canvas.width = w * devicePixelRatio
      canvas.height = h * devicePixelRatio
      canvas.style.width = `${w}px`
      canvas.style.height = `${h}px`
      sim.force('center', forceCenter(w / 2, h / 2))
      sim.alpha(0.2).restart()
      draw()
    })
    ro.observe(wrap)

    return () => {
      ro.disconnect()
      canvas.removeEventListener('pointerup', onPointerUp)
      sim.stop()
      canvasSel.on('.zoom', null)
      canvasSel.on('.drag', null)
    }
  }, [nodes, links])

  useEffect(() => {
    drawRef.current()
  }, [selectedId, highlightIds, activeIds])

  return (
    <div ref={wrapRef} className="relative h-full min-h-0 w-full flex-1">
      <canvas ref={canvasRef} className="block h-full w-full cursor-grab active:cursor-grabbing" />
    </div>
  )
}
```

- [ ] **Step 2: Typecheck**

```bash
cd /Users/Shared/Code/brain/brain/rust/ui && npx tsc --noEmit
```

Expected: exit 0 (or only pre-existing JSX noise — `include: ["src"]` with `allowJs` should be fine).

- [ ] **Step 3: Commit** (only if user approved commits)

```bash
git add brain/rust/ui/src/components/LinkedGraph.tsx
git commit -m "$(cat <<'EOF'
feat(ui): add canvas force graph for Linked tab

Render bipartite memory/entity nodes with d3-force, pan/zoom, drag, and highlight dims.
EOF
)"
```

---

### Task 4: `LinkedFloater` floating panel

**Files:**
- Create: `brain/rust/ui/src/components/LinkedFloater.tsx`

**Interfaces:**
- Consumes: mode `'list' | 'detail'`, filter memories, selected `GraphNode`, optional fullContent, actions
- Produces: bottom-right floating card UI

- [ ] **Step 1: Implement floater**

Create `brain/rust/ui/src/components/LinkedFloater.tsx`:

```tsx
import type { GraphNode, MemoryGraphNode } from '../lib/linkedGraphModel'

const TYPE_BADGE: Record<string, string> = {
  fact: 'bg-amber-900/50 text-amber-300',
  conversation: 'bg-blue-900/50 text-blue-300',
  solution: 'bg-green-900/50 text-green-300',
  pattern: 'bg-purple-900/50 text-purple-300',
  project_context: 'bg-pink-900/50 text-pink-300',
  error_lesson: 'bg-red-900/50 text-red-300',
  decision: 'bg-cyan-900/50 text-cyan-300',
  episode: 'bg-zinc-800 text-zinc-300',
}

function TypeBadge({ type }: { type: string }) {
  const cls = TYPE_BADGE[type] ?? 'bg-zinc-800 text-zinc-400'
  return (
    <span className={`inline-block rounded px-2 py-0.5 font-mono text-xs ${cls}`}>{type}</span>
  )
}

export type LinkedFloaterProps = {
  mode: 'list' | 'detail'
  listPin: boolean
  entityFilter: string
  listMemories: MemoryGraphNode[]
  selected: GraphNode | null
  fullContent: string | null
  onClose: () => void
  onSelectMemory: (id: string) => void
  onFocus: () => void
}

export default function LinkedFloater({
  mode,
  listPin,
  entityFilter,
  listMemories,
  selected,
  fullContent,
  onClose,
  onSelectMemory,
  onFocus,
}: LinkedFloaterProps) {
  return (
    <div className="pointer-events-auto absolute bottom-4 right-4 z-20 flex max-h-[60vh] w-[320px] flex-col overflow-hidden rounded-lg border border-zinc-700 bg-zinc-950/95 shadow-xl backdrop-blur">
      <div className="flex items-center justify-between border-b border-zinc-800 px-3 py-2">
        <p className="text-xs font-medium text-zinc-300">
          {mode === 'list'
            ? `List · ${entityFilter === 'all' ? 'all' : entityFilter}`
            : selected?.kind === 'entity'
              ? 'Entity'
              : 'Memory'}
          {listPin && mode === 'list' ? ' · pinned' : ''}
        </p>
        <button
          type="button"
          onClick={onClose}
          className="text-xs text-zinc-500 hover:text-white"
          aria-label="Close"
        >
          ✕
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {mode === 'list' && (
          <ul className="space-y-2">
            {listMemories.length === 0 && (
              <li className="text-xs text-zinc-600">No memories for this filter.</li>
            )}
            {listMemories.map((m) => (
              <li key={m.id}>
                <button
                  type="button"
                  onClick={() => onSelectMemory(m.id)}
                  className="w-full rounded border border-zinc-800 bg-zinc-900/70 px-2 py-2 text-left hover:border-zinc-600"
                >
                  <div className="mb-1 flex flex-wrap gap-1">
                    <TypeBadge type={m.memory_type} />
                  </div>
                  <p className="line-clamp-2 text-xs text-zinc-400">{m.snippet}</p>
                </button>
              </li>
            ))}
          </ul>
        )}

        {mode === 'detail' && selected?.kind === 'memory' && (
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <TypeBadge type={selected.memory_type} />
              {selected.project && (
                <span className="text-xs text-zinc-500">{selected.project}</span>
              )}
              <span className="font-mono text-xs text-zinc-600">
                #{selected.id.slice(0, 8)}
              </span>
            </div>
            <p className="whitespace-pre-wrap text-sm leading-snug text-zinc-300">
              {fullContent || selected.snippet}
            </p>
            <p className="text-xs text-zinc-600">
              {selected.entityIds.length} entities · {selected.neighbor_ids.length} neighbor
              memories
            </p>
            <button
              type="button"
              onClick={onFocus}
              className="rounded border border-zinc-700 px-2 py-1 text-xs text-zinc-300 hover:text-white"
            >
              Focus
            </button>
          </div>
        )}

        {mode === 'detail' && selected?.kind === 'entity' && (
          <div className="space-y-2">
            <p className="text-sm font-medium text-zinc-200">{selected.name}</p>
            <p className="text-xs text-zinc-500">{selected.memory_count} linked memories</p>
            <button
              type="button"
              onClick={onFocus}
              className="rounded border border-zinc-700 px-2 py-1 text-xs text-zinc-300 hover:text-white"
            >
              Focus
            </button>
          </div>
        )}

        {mode === 'detail' && !selected && (
          <p className="text-xs text-zinc-600">Nothing selected.</p>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Commit** (only if user approved commits)

```bash
git add brain/rust/ui/src/components/LinkedFloater.tsx
git commit -m "$(cat <<'EOF'
feat(ui): add Linked floating detail/list panel

Bottom-right card for entity-filter lists and selected memory/entity detail.
EOF
)"
```

---

### Task 5: `Linked.tsx` shell — wire graph + floater

**Files:**
- Create: `brain/rust/ui/src/views/Linked.tsx`
- Delete: `brain/rust/ui/src/views/Linked.jsx`
- Modify: `brain/rust/ui/src/App.jsx` (import path stays `./views/Linked`)

**Interfaces:**
- Consumes: `getLinked`, `getObservations` from `../api`; model + graph + floater
- Produces: full Linked tab UX per spec

- [ ] **Step 1: Implement `Linked.tsx`**

Create `brain/rust/ui/src/views/Linked.tsx`:

```tsx
import { useCallback, useEffect, useMemo, useState } from 'react'
import { getLinked, getObservations } from '../api'
import LinkedFloater from '../components/LinkedFloater'
import LinkedGraph from '../components/LinkedGraph'
import {
  buildBipartiteGraph,
  egoSubgraph,
  filterActiveIds,
  memoriesForFilter,
  oneHopIds,
  type GraphNode,
  type LinkedApiResponse,
} from '../lib/linkedGraphModel'

export default function Linked() {
  const [data, setData] = useState<LinkedApiResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [entityFilter, setEntityFilter] = useState('all')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [graphMode, setGraphMode] = useState<'full' | 'ego'>('full')
  const [egoFocusId, setEgoFocusId] = useState<string | null>(null)
  const [floaterOpen, setFloaterOpen] = useState(false)
  const [listPin, setListPin] = useState(false)
  const [floaterMode, setFloaterMode] = useState<'list' | 'detail'>('detail')
  const [fullContent, setFullContent] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      const d = (await getLinked()) as LinkedApiResponse
      setData(d)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const fullGraph = useMemo(
    () => (data ? buildBipartiteGraph(data) : { nodes: [], links: [] }),
    [data],
  )

  const viewGraph = useMemo(() => {
    if (graphMode === 'ego' && egoFocusId) {
      return egoSubgraph(fullGraph.nodes, fullGraph.links, egoFocusId)
    }
    return fullGraph
  }, [fullGraph, graphMode, egoFocusId])

  const selected: GraphNode | null = useMemo(
    () => viewGraph.nodes.find((n) => n.id === selectedId) ?? null,
    [viewGraph.nodes, selectedId],
  )

  const highlightIds = useMemo(() => {
    if (!selectedId) return null
    return oneHopIds(viewGraph.nodes, viewGraph.links, selectedId)
  }, [viewGraph, selectedId])

  const activeIds = useMemo(
    () => filterActiveIds(fullGraph.nodes, fullGraph.links, entityFilter),
    [fullGraph, entityFilter],
  )

  const listMemories = useMemo(
    () => memoriesForFilter(fullGraph.nodes, entityFilter),
    [fullGraph.nodes, entityFilter],
  )

  useEffect(() => {
    let cancelled = false
    async function hydrate() {
      setFullContent(null)
      if (!selected || selected.kind !== 'memory') return
      try {
        const obs = await getObservations([selected.id])
        const row = obs?.results?.[0]
        if (!cancelled && row?.content) setFullContent(String(row.content))
      } catch {
        /* keep snippet */
      }
    }
    void hydrate()
    return () => {
      cancelled = true
    }
  }, [selected])

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        if (listPin && floaterMode === 'list') {
          setListPin(false)
          setFloaterOpen(false)
          return
        }
        setSelectedId(null)
        setFloaterOpen(false)
        setListPin(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [listPin, floaterMode])

  function handleSelect(id: string | null) {
    if (id == null) {
      if (listPin) {
        setSelectedId(null)
        setFloaterMode('list')
        setFloaterOpen(true)
        return
      }
      setSelectedId(null)
      setFloaterOpen(false)
      return
    }
    setSelectedId(id)
    setListPin(false)
    setFloaterMode('detail')
    setFloaterOpen(true)
  }

  function enterEgo(id: string) {
    setEgoFocusId(id)
    setGraphMode('ego')
    setSelectedId(id)
    setFloaterMode('detail')
    setFloaterOpen(true)
    setListPin(false)
  }

  function backToFull() {
    setGraphMode('full')
    setEgoFocusId(null)
  }

  return (
    <div className="relative flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-zinc-900 px-4 py-3">
        <div className="mr-2">
          <h2 className="text-sm font-semibold text-white">Linked</h2>
          <p className="text-[11px] text-zinc-500">
            {data?.memories?.length ?? '—'} memories · {data?.entities?.length ?? '—'} entities
            {graphMode === 'ego' ? ' · ego' : ''}
          </p>
        </div>

        <button
          type="button"
          onClick={() => setEntityFilter('all')}
          className={`rounded px-2 py-1 font-mono text-xs ${
            entityFilter === 'all'
              ? 'bg-zinc-200 text-black'
              : 'bg-zinc-900 text-zinc-400 hover:text-zinc-200'
          }`}
        >
          all ({data?.memories?.length ?? 0})
        </button>
        {(data?.entities ?? []).map((e) => (
          <button
            key={e.id}
            type="button"
            onClick={() => setEntityFilter(e.name)}
            className={`rounded px-2 py-1 font-mono text-xs ${
              entityFilter === e.name
                ? 'bg-zinc-200 text-black'
                : 'bg-zinc-900 text-zinc-400 hover:text-zinc-200'
            }`}
          >
            {e.name} ({e.memory_count})
          </button>
        ))}

        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            onClick={() => {
              setListPin(true)
              setFloaterMode('list')
              setFloaterOpen(true)
            }}
            className="rounded border border-zinc-700 px-2.5 py-1 text-xs text-zinc-400 hover:text-white"
          >
            List
          </button>
          {graphMode === 'ego' ? (
            <button
              type="button"
              onClick={backToFull}
              className="rounded border border-zinc-700 px-2.5 py-1 text-xs text-zinc-400 hover:text-white"
            >
              Back to full
            </button>
          ) : (
            <button
              type="button"
              disabled={!selectedId}
              onClick={() => selectedId && enterEgo(selectedId)}
              className="rounded border border-zinc-700 px-2.5 py-1 text-xs text-zinc-400 hover:text-white disabled:opacity-40"
            >
              Focus
            </button>
          )}
          <button
            type="button"
            onClick={() => void load()}
            className="rounded border border-zinc-700 px-2.5 py-1 text-xs text-zinc-400 hover:text-white"
          >
            Refresh
          </button>
        </div>
      </div>

      {error && <p className="px-4 py-2 text-sm text-red-400">{error}</p>}

      <div className="relative min-h-0 flex-1">
        {!data && !error && (
          <p className="p-8 text-sm text-zinc-600">Loading linked graph…</p>
        )}
        {data && viewGraph.nodes.length === 0 && (
          <p className="p-8 text-sm text-zinc-600">No linked memories.</p>
        )}
        {data && viewGraph.nodes.length > 0 && (
          <LinkedGraph
            nodes={viewGraph.nodes}
            links={viewGraph.links}
            selectedId={selectedId}
            highlightIds={highlightIds}
            activeIds={activeIds}
            onSelect={handleSelect}
            onFocusRequest={enterEgo}
          />
        )}

        {floaterOpen && (
          <LinkedFloater
            mode={floaterMode}
            listPin={listPin}
            entityFilter={entityFilter}
            listMemories={listMemories}
            selected={selected}
            fullContent={fullContent}
            onClose={() => {
              setFloaterOpen(false)
              setListPin(false)
            }}
            onSelectMemory={(id) => handleSelect(id)}
            onFocus={() => selectedId && enterEgo(selectedId)}
          />
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Delete `Linked.jsx` and confirm `App.jsx` import**

Delete `brain/rust/ui/src/views/Linked.jsx`.

`App.jsx` already has `import Linked from './views/Linked'` — leave as-is (Vite resolves `.tsx`).

Ensure the main pane gives Linked height. In `App.jsx`, `main` uses `overflow-y-auto`. For full-bleed graph, change main children wrapper behavior:

Modify `brain/rust/ui/src/App.jsx` so the main area is a flex column with `min-h-0` and Linked fills height:

```jsx
<main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
  {view === 'dashboard' && (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <Dashboard />
    </div>
  )}
  {view === 'search' && (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <Search focusId={focusId} onFocused={() => setFocusId(null)} />
    </div>
  )}
  {view === 'linked' && (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <Linked />
    </div>
  )}
  {view === 'curate' && (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <Curate />
    </div>
  )}
  {view === 'eval' && (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <Eval />
    </div>
  )}
</main>
```

- [ ] **Step 3: Run unit tests + typecheck + dev sanity**

```bash
cd /Users/Shared/Code/brain/brain/rust/ui && npm test && npx tsc --noEmit && npm run build
```

Expected: tests pass; `tsc` clean; Vite build writes to `../static`.

- [ ] **Step 4: Manual smoke** (with `brain_api` on `:8787`)

```bash
cd /Users/Shared/Code/brain/brain/rust/ui && npm run dev
```

Checklist:
- [ ] Linked shows bipartite force graph
- [ ] Click memory/entity → floater + highlight
- [ ] Double-click / Focus → ego; Back to full restores
- [ ] Entity chip dims outsiders
- [ ] List opens pinned floater; Esc / ✕ dismisses
- [ ] Refresh reloads

- [ ] **Step 5: Commit** (only if user approved commits)

```bash
git add brain/rust/ui/src/views/Linked.tsx brain/rust/ui/src/App.jsx brain/rust/ui/src/components/ brain/rust/static/
git rm brain/rust/ui/src/views/Linked.jsx
git commit -m "$(cat <<'EOF'
feat(ui): ship Linked tab bipartite force-graph view

Replace the list-primary Linked UX with canvas + d3-force and a floating detail panel.
EOF
)"
```

---

## Spec coverage (self-review)

| Spec requirement | Task |
|---|---|
| Full-bleed canvas force graph | 3, 5 |
| Bipartite memories + entities | 2, 3 |
| Floating panel (not sidebar) | 4, 5 |
| Click highlight + detail | 3, 5 |
| Double-click / Focus ego + Back | 3, 5 |
| Entity filter dims | 2, 5 |
| List toolbar control | 5 |
| No API changes | all |
| TS for new Linked files only | 1, 2–5 |
| Medium scale / no per-tick React | 3 |
| Build to `static/` | 5 |
| Model unit tests | 2 |

**Placeholder scan:** none remaining after Task 3 `drawRef` cleanup.

**Type consistency:** `GraphNode` / `GraphLink` / `LinkedApiResponse` / `filterActiveIds` / `oneHopIds` / `egoSubgraph` names match across Tasks 2–5.
