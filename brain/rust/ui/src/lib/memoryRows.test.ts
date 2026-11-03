import { describe, expect, it } from 'vitest'
import { markCut, parseTags, toRow } from './memoryRows'

describe('toRow', () => {
  it('maps an observation into a row', () => {
    const row = toRow({
      id: 'abc',
      content: 'x'.repeat(300),
      timestamp: '2026-10-18T22:50:31Z',
      metadata: { type: 'solution', project: 'brain' },
    })
    expect(row).toEqual({
      id: 'abc',
      memory_type: 'solution',
      project: 'brain',
      timestamp: '2026-10-18T22:50:31Z',
      snippet: `${'x'.repeat(200)}…`,
    })
  })

  it('does not mark text that fit', () => {
    expect(toRow({ id: 'a', content: 'short' }).snippet).toBe('short')
    expect(toRow({ id: 'a', content: 'y'.repeat(200) }).snippet).toBe('y'.repeat(200))
  })

  it('tolerates missing metadata and content', () => {
    expect(toRow({ id: 'a', metadata: null })).toEqual({
      id: 'a',
      memory_type: '',
      project: '',
      timestamp: '',
      snippet: '',
    })
  })

  it('falls back to the metadata timestamp', () => {
    expect(toRow({ id: 'a', metadata: { timestamp: 't1' } }).timestamp).toBe('t1')
  })
})

describe('parseTags', () => {
  it('splits, trims, and de-duplicates', () => {
    expect(parseTags('ui, design,,ui ,brain/ingest')).toEqual(['ui', 'design', 'brain/ingest'])
  })

  it('returns [] for anything that is not a string', () => {
    expect(parseTags(undefined)).toEqual([])
    expect(parseTags(['a'])).toEqual([])
  })
})

describe('markCut', () => {
  it('adds an ellipsis only at the cut length', () => {
    expect(markCut('a'.repeat(120), 120)).toBe(`${'a'.repeat(120)}…`)
    expect(markCut('a'.repeat(119), 120)).toBe('a'.repeat(119))
  })

  it('trims trailing space before the ellipsis', () => {
    expect(markCut(`${'a'.repeat(118)}  `, 120)).toBe(`${'a'.repeat(118)}…`)
  })
})
