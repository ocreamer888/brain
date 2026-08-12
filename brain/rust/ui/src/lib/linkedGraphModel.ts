export type LinkedEntityRef = { id: string; name: string }
export type LinkedEntityStat = { id: string; name: string; memory_count: number }

export type LinkedMemoryItem = {
  id: string
  snippet: string
  memory_type: string
  project: string
  timestamp: string
  entities: LinkedEntityRef[]
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
