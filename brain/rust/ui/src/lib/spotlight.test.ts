import { describe, expect, it } from 'vitest'
import { headline, lessonParts, relativeTime } from './spotlight'

describe('headline', () => {
  it('prefers the title', () => {
    expect(headline('  Use plain CSS ', 'body')).toBe('Use plain CSS')
  })
  it('falls back to the first non-empty line', () => {
    expect(headline(null, '\n\nFirst line\nsecond')).toBe('First line')
  })
  it('cuts a long first line at a word with an ellipsis', () => {
    const h = headline(undefined, `${'word '.repeat(30)}end`)
    expect(h.endsWith('…')).toBe(true)
    expect(h.length).toBeLessThanOrEqual(91)
    expect(h).not.toMatch(/ …$/)
  })
})

describe('lessonParts', () => {
  it('reads Error / Cause / Fix lines', () => {
    expect(lessonParts('Error: boom\nCause: bad input\nFix: validate it')).toEqual({
      error: 'boom',
      cause: 'bad input',
      fix: 'validate it',
    })
  })
  it('needs a Fix line to count', () => {
    expect(lessonParts('Error: boom\nCause: x')).toBeNull()
    expect(lessonParts('free text lesson')).toBeNull()
  })
  it('accepts a lone Fix line', () => {
    expect(lessonParts('Fix: restart')).toEqual({ error: undefined, cause: undefined, fix: 'restart' })
  })
})

describe('relativeTime', () => {
  const now = new Date('2026-10-18T12:00:00Z')
  it('formats past times in the largest whole unit', () => {
    expect(relativeTime('2026-10-18T09:00:00Z', now)).toBe('3 hours ago')
    expect(relativeTime('2026-10-17T12:00:00Z', now)).toBe('yesterday')
    expect(relativeTime('2026-10-04T12:00:00Z', now)).toBe('2 weeks ago')
  })
  it('says just now under a minute, and nothing for bad input', () => {
    expect(relativeTime('2026-10-18T11:59:40Z', now)).toBe('just now')
    expect(relativeTime('nope', now)).toBe('')
  })
})
