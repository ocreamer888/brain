/** The memory atlas (GET /v1/memory-atlas/:id: stored layout + live memories), decoded for the GPU. */

export type AtlasFile = {
  meta: { built_at: string; memories: number; superseded?: number; entities: number; edges: number; extra_edges?: number; similar_edges?: number; projects: number; layout: string }
  types: string[]
  projects: { name: string; count: number }[]
  points: {
    id: string[]
    kind: number[] // 0 memory, 1 entity
    type: number[] // memory type index; -1 for entities
    project: number[]
    size: number[] // links per memory / memories per entity
    label: string[]
    xyz: number[]
  }
  edges: number[] // the forest that shapes the layout, flat [a, b, a, b, …]
  extra?: number[] // every other real mention link, same format
  /** similar_to (G7): memory-memory embedding links, same format. Decorative,
   *  same as extra -- deliberately not folded into the adjacency below, so
   *  entity-based neighbor counts (Reading, Finder, Tip) stay unaffected. */
  similar?: number[]
}

export type Atlas = AtlasFile & {
  positions: Float32Array
  indexOf: Map<string, number>
  /** CSR adjacency: neighbors of i are adj[start[i] .. start[i + 1]). */
  start: Uint32Array
  adj: Uint32Array
}

export function decodeAtlas(file: AtlasFile): Atlas {
  const n = file.points.id.length
  if (file.points.xyz.length !== n * 3) throw new Error(`atlas: ${n} ids but ${file.points.xyz.length / 3} positions`)
  const all = file.extra ? file.edges.concat(file.extra) : file.edges
  if (file.edges.length % 2 || all.length % 2) throw new Error('atlas: odd edge list')
  const deg = new Uint32Array(n)
  for (const v of all) {
    if (v >= n) throw new Error(`atlas: edge to missing point ${v}`)
    deg[v]++
  }
  const start = new Uint32Array(n + 1)
  for (let i = 0; i < n; i++) start[i + 1] = start[i] + deg[i]
  const fill = start.slice(0, n)
  const adj = new Uint32Array(all.length)
  for (let k = 0; k < all.length; k += 2) {
    const a = all[k]
    const b = all[k + 1]
    adj[fill[a]++] = b
    adj[fill[b]++] = a
  }
  return {
    ...file,
    positions: Float32Array.from(file.points.xyz),
    indexOf: new Map(file.points.id.map((id, i) => [id, i])),
    start,
    adj,
  }
}

export function neighbors(atlas: Pick<Atlas, 'start' | 'adj'>, i: number): Uint32Array {
  return atlas.adj.subarray(atlas.start[i], atlas.start[i + 1])
}

/**
 * Point scale, the atlas's narrow 6–10 range: memories 1 → 1.35 by links, hubs
 * 1.35 → 1.67 by children (log). Size hints, it never dominates.
 */
export function pointScale(kind: number[], size: number[]): Float32Array {
  const max = [1e-6, 1e-6]
  size.forEach((s, i) => (max[kind[i]] = Math.max(max[kind[i]], Math.log1p(s))))
  return Float32Array.from(size, (s, i) => {
    const t = Math.log1p(s) / max[kind[i]]
    return kind[i] ? 1.35 + t * 0.32 : 1 + t * 0.35
  })
}

/** Entity points whose name contains the query (case-insensitive), biggest first, capped. */
export function findEntities(atlas: Pick<AtlasFile, 'points'>, query: string, limit = 8): number[] {
  const q = query.trim().toLowerCase()
  if (!q) return []
  const p = atlas.points
  const hits: number[] = []
  for (let i = 0; i < p.id.length; i++) if (p.kind[i] === 1 && p.label[i].toLowerCase().includes(q)) hits.push(i)
  return hits.sort((a, b) => p.size[b] - p.size[a]).slice(0, limit)
}

/** The AI Model Atlas's categorical palette ("classic", read from its published config). */
export const ATLAS_PALETTE = ['#ff595e', '#ff924c', '#ffca3a', '#c5ca30', '#8ac926', '#52a675', '#1982c4', '#4267ac', '#6a4c93', '#b5a6c9']

/**
 * Project colors from the atlas palette, cycled like the atlas does for its
 * 34k authors. Colors repeat past 10, so identity is always also in the
 * legend, the tooltip, and the label.
 */
export function projectColors(count: number): [number, number, number][] {
  return Array.from({ length: count }, (_, i) => {
    const h = ATLAS_PALETTE[i % ATLAS_PALETTE.length]
    return [1, 3, 5].map((k) => parseInt(h.slice(k, k + 2), 16) / 255) as [number, number, number]
  })
}
