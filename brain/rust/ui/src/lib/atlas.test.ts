import { describe, expect, it } from 'vitest'
import { decodeAtlas, findEntities, neighbors, pointScale, projectColors } from './atlas'

const file = {
  meta: { built_at: 't', memories: 2, entities: 2, edges: 3, projects: 1, layout: 'x' },
  types: ['fact'],
  projects: [{ name: 'p', count: 2 }],
  points: {
    id: ['m1', 'm2', 'e:react', 'e:supa'],
    kind: [0, 0, 1, 1],
    type: [0, 0, -1, -1],
    project: [0, 0, 0, 0],
    size: [2, 1, 2, 1],
    label: ['A', 'B', 'React', 'Supabase'],
    xyz: [0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1],
  },
  edges: [0, 2, 1, 2],
  extra: [0, 3],
}

describe('decodeAtlas', () => {
  it('builds positions, an id index, and both-way adjacency', () => {
    const a = decodeAtlas(file)
    expect(a.positions).toBeInstanceOf(Float32Array)
    expect(a.indexOf.get('e:react')).toBe(2)
    expect([...neighbors(a, 2)].sort()).toEqual([0, 1])
    expect([...neighbors(a, 0)].sort()).toEqual([2, 3])
    expect([...neighbors(a, 3)]).toEqual([0])
  })
  it('includes the extra real links in adjacency', () => {
    expect([...neighbors(decodeAtlas(file), 3)]).toEqual([0])
  })
  it('rejects broken files', () => {
    expect(() => decodeAtlas({ ...file, points: { ...file.points, xyz: [0, 0, 0] } })).toThrow(/4 ids/)
    expect(() => decodeAtlas({ ...file, edges: [0] })).toThrow(/odd/)
    expect(() => decodeAtlas({ ...file, edges: [0, 9] })).toThrow(/missing point 9/)
  })
})

describe('pointScale', () => {
  it('keeps the atlas narrow range: memories 1–1.35, hubs up to 1.67', () => {
    const s = pointScale([0, 0, 1, 1], [0, 4, 1, 50])
    expect(s[0]).toBe(1)
    expect(s[1]).toBeCloseTo(1.35)
    expect(s[3]).toBeCloseTo(1.67)
    expect(Math.max(...s) / Math.min(...s)).toBeLessThanOrEqual(1.67 + 1e-6) // ~10/6, the atlas range
  })
})

describe('findEntities', () => {
  it('searches entity points only, biggest first', () => {
    expect(findEntities(file, 'a')).toEqual([2, 3])
    expect(findEntities(file, 'supa')).toEqual([3])
    expect(findEntities(file, '   ')).toEqual([])
  })
})

describe('projectColors', () => {
  it('cycles the atlas palette', () => {
    const c = projectColors(12)
    expect(c[0].map((v) => Math.round(v * 255))).toEqual([255, 89, 94])
    expect(c[10]).toEqual(c[0])
    expect(c.flat().every((v) => v >= 0 && v <= 1)).toBe(true)
  })
})
