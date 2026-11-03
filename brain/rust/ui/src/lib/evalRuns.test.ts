import { describe, expect, it } from 'vitest'
import { classifyGap, formatPp, p1Series, parseRunId, pct, summarizeRuns } from './evalRuns'

describe('summarizeRuns', () => {
  const runs = [
    { run_id: 'c', pass: true, quick_p1_avg: 1 },
    { run_id: 'b', pass: false, quick_p1_avg: 0.5 },
    { run_id: 'old', pass: true, quick_p1_avg: null },
    { run_id: 'a', pass: true, quick_p1_avg: 0.9 },
  ]

  it('counts passes across every run, scored or not', () => {
    const s = summarizeRuns(runs)
    expect(s.total).toBe(4)
    expect(s.passed).toBe(3)
  })

  it('keeps only scored runs, oldest first, capped at `recent`', () => {
    expect(summarizeRuns(runs).scored.map((r) => r.run_id)).toEqual(['a', 'b', 'c'])
    expect(summarizeRuns(runs, 2).scored.map((r) => r.run_id)).toEqual(['b', 'c'])
  })

  it('reports the newest scored run as latest', () => {
    expect(summarizeRuns(runs).latest).toEqual({ run_id: 'c', p1: 1, pass: true })
  })

  it('handles no runs', () => {
    expect(summarizeRuns([])).toEqual({ total: 0, passed: 0, scored: [], latest: null })
    expect(summarizeRuns(undefined).total).toBe(0)
  })
})

describe('parseRunId', () => {
  it('reads the local timestamp in a run id', () => {
    expect(parseRunId('2026-10-18-2058')).toEqual(new Date(2026, 9, 18, 20, 58))
  })
  it('rejects other shapes', () => {
    expect(parseRunId('2026-10-18')).toBeNull()
    expect(parseRunId('latest')).toBeNull()
  })
})

describe('pct / formatPp', () => {
  it('formats percents and percentage points', () => {
    expect(pct(0.8442)).toBe('84.4%')
    expect(pct(null)).toBe('—')
    expect(formatPp(0.0589)).toBe('+5.9 pp')
    expect(formatPp(-0.0803)).toBe('−8.0 pp')
    expect(formatPp(0)).toBe('+0.0 pp')
  })
})

describe('classifyGap', () => {
  it('keeps the old −5 pp tolerance', () => {
    expect(classifyGap(0.0589)).toBe('gain')
    expect(classifyGap(0)).toBe('flat')
    expect(classifyGap(-0.03)).toBe('flat')
    expect(classifyGap(-0.05)).toBe('regression')
    expect(classifyGap(-0.8947)).toBe('regression')
    expect(classifyGap(null)).toBeNull()
  })
})

describe('p1Series', () => {
  it('keeps scored runs oldest first and leaves missing MCP as a gap', () => {
    const runs = [
      { run_id: '2026-10-18-2058', pass: true, quick_p1_avg: 1, mcp_p1: 0.1765 },
      { run_id: '2026-07-24-1348', pass: true, quick_p1_avg: 1, mcp_p1: null },
      { run_id: '2026-05-23-1628', pass: true, quick_p1_avg: null },
    ]
    const s = p1Series(runs)
    expect(s.map((p) => p.run_id)).toEqual(['2026-07-24-1348', '2026-10-18-2058'])
    expect(s[0].mcp).toBeNull()
    expect(s[1].mcp).toBe(0.1765)
  })
})
