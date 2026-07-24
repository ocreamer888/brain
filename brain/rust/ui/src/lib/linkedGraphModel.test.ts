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
