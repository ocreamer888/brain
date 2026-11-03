import { describe, expect, it } from 'vitest'
import { axisLabelEvery, dayKey, recentCount, showsAxisLabel, summarizeActivity } from './activity'

const now = new Date(2026, 9, 19, 15, 0) // Oct 19, local time
const at = (day: number, hour = 12) => new Date(2026, 9, day, hour).toISOString()

describe('summarizeActivity', () => {
  it('buckets by local day across the window, oldest first, zero-filled', () => {
    const items = [{ timestamp: at(19) }, { timestamp: at(19, 1) }, { timestamp: at(17) }, { timestamp: at(1) }]
    const s = summarizeActivity(items, 3, now)
    expect(s.days).toEqual([
      { date: '2026-10-17', count: 1 },
      { date: '2026-10-18', count: 0 },
      { date: '2026-10-19', count: 2 },
    ])
    expect(s.total).toBe(3)
  })

  it('is complete only when items reach back before the window', () => {
    expect(summarizeActivity([{ timestamp: at(19) }, { timestamp: at(1) }], 3, now).complete).toBe(true)
    expect(summarizeActivity([{ timestamp: at(19) }, { timestamp: at(18) }], 3, now).complete).toBe(false)
  })

  it('ranks projects inside the window only, unnamed as general', () => {
    const items = [
      { timestamp: at(19), project: 'brain' },
      { timestamp: at(19), project: 'brain' },
      { timestamp: at(18), project: '' },
      { timestamp: at(1), project: 'old' },
    ]
    expect(summarizeActivity(items, 3, now).projects).toEqual({ brain: 2, general: 1 })
  })

  it('ranks sources inside the window only, missing as unknown', () => {
    const items = [
      { timestamp: at(19), source: 'claude_code_session' },
      { timestamp: at(18), source: 'claude_code_session' },
      { timestamp: at(18) },
      { timestamp: at(1), source: 'perplexity' },
    ]
    expect(summarizeActivity(items, 3, now).sources).toEqual({ claude_code_session: 2, unknown: 1 })
  })

  it('skips unparseable timestamps', () => {
    expect(summarizeActivity([{ timestamp: 'nope' }], 3, now).total).toBe(0)
  })
})

describe('dayKey', () => {
  it('pads month and day', () => {
    expect(dayKey(new Date(2026, 0, 5))).toBe('2026-01-05')
  })
})

describe('axis labels', () => {
  const labelled = (n: number) => Array.from({ length: n }, (_, i) => i).filter((i) => showsAxisLabel(i, n))

  it('labels every day for a week or two', () => {
    expect(labelled(7)).toEqual([0, 1, 2, 3, 4, 5, 6])
    expect(axisLabelEvery(14)).toBe(1)
  })

  it('labels every 5th day back from today over 30 days, always including today', () => {
    const l = labelled(30)
    expect(l.at(-1)).toBe(29)
    expect(l).toEqual([4, 9, 14, 19, 24, 29])
  })

  it('never puts a label right next to today', () => {
    for (const n of [7, 14, 21, 30]) {
      const l = labelled(n)
      const today = n - 1
      if (axisLabelEvery(n) > 1) expect(l).not.toContain(today - 1)
    }
  })
})

describe('recentCount', () => {
  const now = new Date(2026, 9, 19, 15, 0)
  const at = (day: number, hour = 12) => new Date(2026, 9, day, hour).toISOString()

  it('counts one type today and over the last 7 local days', () => {
    const items = [
      { timestamp: at(19, 9), memory_type: 'fact' },
      { timestamp: at(19, 1), memory_type: 'fact' },
      { timestamp: at(19), memory_type: 'decision' },
      { timestamp: at(13), memory_type: 'fact' }, // 7th day back: inside
      { timestamp: at(12), memory_type: 'fact' }, // 8th day back: outside
    ]
    expect(recentCount(items, 'fact', now)).toEqual({ today: 2, week: 3, complete: true })
  })

  it('is incomplete when the items do not reach back a week', () => {
    expect(recentCount([{ timestamp: at(18), memory_type: 'fact' }], 'fact', now).complete).toBe(false)
  })
})
