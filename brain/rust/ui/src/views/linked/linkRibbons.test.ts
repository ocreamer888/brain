import { describe, expect, it } from 'vitest'
import { concatPairs } from './linkRibbons'

describe('concatPairs', () => {
  it('passes a plain-array edges through unchanged when there is nothing to add', () => {
    const edges = [0, 1, 1, 2]
    expect(concatPairs(edges, undefined, undefined)).toBe(edges)
  })

  // ReferenceAtlas's binary geometry decodes edges as a Uint32Array (atlasRef.ts),
  // which has no .concat -- this is the exact shape that broke switching to a
  // brain with no memory atlas (only a stored reference dataset).
  it('passes a Uint32Array edges through unchanged when there is nothing to add', () => {
    const edges = new Uint32Array([0, 1, 1, 2])
    expect(concatPairs(edges, undefined, undefined)).toBe(edges)
  })

  it('concatenates a Uint32Array edges with extra/similar tiers', () => {
    const edges = new Uint32Array([0, 1])
    expect(concatPairs(edges, [1, 2], [2, 3])).toEqual([0, 1, 1, 2, 2, 3])
  })

  it('concatenates only the tiers that have content', () => {
    expect(concatPairs([0, 1], [], [2, 3])).toEqual([0, 1, 2, 3])
    expect(concatPairs([0, 1], [2, 3], [])).toEqual([0, 1, 2, 3])
  })
})
