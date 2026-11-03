import { describe, expect, it } from 'vitest'
import { isPromoted, toFactRow } from './curate'

describe('toFactRow', () => {
  it('keeps what review needs: content, project, time, salience, source', () => {
    expect(
      toFactRow({ id: 'f1', content: 'x', timestamp: 't', metadata: { project: 'brain', salience: 0.5, parent_id: 'ep1' } }),
    ).toEqual({ id: 'f1', content: 'x', project: 'brain', timestamp: 't', salience: 0.5, parentId: 'ep1' })
  })
  it('treats missing or empty fields as absent', () => {
    expect(toFactRow({ id: 'f2', metadata: { parent_id: '' } })).toEqual({
      id: 'f2', content: '', project: '', timestamp: '', salience: null, parentId: null,
    })
  })
})

describe('isPromoted', () => {
  it('reads promotion from stored salience', () => {
    expect(isPromoted(1)).toBe(true)
    expect(isPromoted(0.5)).toBe(false)
    expect(isPromoted(0.55)).toBe(false)
    expect(isPromoted(null)).toBe(false)
  })
})
