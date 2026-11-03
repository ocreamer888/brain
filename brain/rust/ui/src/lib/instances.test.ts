import { describe, expect, it } from 'vitest'
import { friendlyError, parseTagInput, sortInstances } from './instances'

describe('sortInstances', () => {
  it('puts the active brain first and archived ones last', () => {
    const list = [
      { id: 'z', name: 'Zed', archived: true },
      { id: 'b', name: 'Beta' },
      { id: 'm', name: 'Main' },
      { id: 'a', name: 'Alpha' },
    ]
    expect(sortInstances(list, 'm').map((i) => i.id)).toEqual(['m', 'a', 'b', 'z'])
  })
})

describe('parseTagInput', () => {
  it('trims, drops empties, de-duplicates', () => {
    expect(parseTagInput(' work, personal,, work ')).toEqual(['work', 'personal'])
    expect(parseTagInput('')).toEqual([])
  })
})

describe('friendlyError', () => {
  it('explains a busy server', () => {
    expect(friendlyError('503: {"error":"switching instance"}')).toMatch(/busy switching/)
  })
  it('surfaces the server reason as a sentence', () => {
    expect(friendlyError('409: {"error":"cannot delete the active instance"}')).toBe('Cannot delete the active instance.')
    expect(friendlyError('400: {"error":"name required"}')).toBe('Name required.')
  })
  it('handles non-JSON bodies, bare statuses, and other errors', () => {
    expect(friendlyError('500: boom')).toBe('Boom.')
    expect(friendlyError('500')).toBe('Request failed (500).')
    expect(friendlyError('Failed to fetch')).toBe('Failed to fetch')
  })
})
