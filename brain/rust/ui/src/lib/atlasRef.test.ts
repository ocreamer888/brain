import { describe, expect, it } from 'vitest'
import { categoryColors, decodeGeometry, searchLabels, sizeScale } from './atlasRef'

function block(n: number, m: number) {
  const buf = new ArrayBuffer(8 + n * 20 + m * 8)
  const v = new DataView(buf)
  v.setUint32(0, n, true)
  v.setUint32(4, m, true)
  let o = 8
  for (let i = 0; i < n * 3; i++, o += 4) v.setFloat32(o, i, true)
  for (let i = 0; i < n; i++, o += 4) v.setFloat32(o, 50 + i * 350, true)
  for (let i = 0; i < n; i++, o += 4) v.setUint32(o, i * 11, true)
  for (let i = 0; i < m * 2; i++, o += 4) v.setUint32(o, i % n, true)
  return buf
}

describe('decodeGeometry', () => {
  it('reads every array at its offset', () => {
    const g = decodeGeometry(block(2, 1))
    expect([g.n, g.m]).toEqual([2, 1])
    expect([...g.positions]).toEqual([0, 1, 2, 3, 4, 5])
    expect([...g.size]).toEqual([50, 400])
    expect([...g.category]).toEqual([0, 11])
    expect([...g.links]).toEqual([0, 1])
  })
  it('rejects a truncated block', () => {
    expect(() => decodeGeometry(block(2, 1).slice(0, 20))).toThrow(/expected 56 bytes/)
  })
})

describe('sizeScale', () => {
  it('maps the data range onto 6–10 px as ratios', () => {
    expect([...sizeScale(Float32Array.from([50, 225, 400]), [6, 10])].map((v) => +v.toFixed(3))).toEqual([1, 1.333, 1.667])
  })
})

describe('categoryColors', () => {
  it('cycles the palette by category rank', () => {
    const c = categoryColors(Uint32Array.from([0, 2]), ['#ff0000', '#00ff00'])
    expect([...c]).toEqual([1, 0, 0, 1, 0, 0])
  })
})

describe('searchLabels ranking', () => {
  const names = ['Shakker-Labs/FLUX.1-dev-LoRA', 'black-forest-labs/FLUX.1-dev', 'x/flux.1-dev-tuned', 'flux.1-dev-mini']
  it('puts the exact name (after an org prefix) first, then starts-with, then contains', () => {
    expect(searchLabels(names, 'flux.1-dev')).toEqual([1, 3, 2, 0])
  })
  it('breaks ties by links, then shorter names', () => {
    expect(searchLabels(['ab-x', 'ab-yy', 'ab-z'], 'ab', 8, [1, 5, 1])).toEqual([1, 0, 2])
  })
})

describe('searchLabels', () => {
  it('finds substrings, case-insensitive, capped', () => {
    expect(searchLabels(['Llama-3', 'mistral', 'llama-2'], 'LLAMA')).toEqual([0, 2])
    expect(searchLabels(['a', 'a', 'a'], 'a', 2)).toEqual([0, 1])
    expect(searchLabels(['x'], ' ')).toEqual([])
  })
})
