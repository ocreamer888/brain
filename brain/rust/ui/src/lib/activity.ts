/**
 * Daily save counts and active projects from /list items (newest first).
 * /list is capped by `limit`, so the window is only trustworthy when the
 * items reach back past its first day; `complete` says whether they do.
 */
export type ListItem = { timestamp: string; project?: string; source?: string }
export type Day = { date: string; count: number }

/** Local calendar day as YYYY-MM-DD (people read "today" in their own timezone). */
export function dayKey(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

export function summarizeActivity(items: ListItem[], days = 14, now = new Date()) {
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate() - (days - 1))
  const keys: string[] = []
  for (let i = 0; i < days; i++) {
    keys.push(dayKey(new Date(start.getFullYear(), start.getMonth(), start.getDate() + i)))
  }
  const counts = new Map(keys.map((k) => [k, 0]))
  const projects = new Map<string, number>()
  const sources = new Map<string, number>()
  let oldest = Infinity
  for (const it of items) {
    const t = new Date(it.timestamp)
    if (Number.isNaN(t.getTime())) continue
    oldest = Math.min(oldest, t.getTime())
    const k = dayKey(t)
    if (!counts.has(k)) continue
    counts.set(k, (counts.get(k) ?? 0) + 1)
    const p = it.project || 'general'
    projects.set(p, (projects.get(p) ?? 0) + 1)
    const src = it.source || 'unknown'
    sources.set(src, (sources.get(src) ?? 0) + 1)
  }
  return {
    days: keys.map((date) => ({ date, count: counts.get(date) ?? 0 })) as Day[],
    total: [...counts.values()].reduce((a, b) => a + b, 0),
    projects: Object.fromEntries([...projects].sort((a, b) => b[1] - a[1])),
    sources: Object.fromEntries([...sources].sort((a, b) => b[1] - a[1])),
    complete: oldest < start.getTime(),
  }
}

/**
 * Which day columns get an axis label. Short ranges label every day; longer
 * ones every `step` days, counted back from today so today always lines up
 * and the label nearest it never crowds the "today" label.
 */
export function axisLabelEvery(count: number): number {
  if (count <= 14) return 1
  if (count <= 21) return 3
  return 5
}

export function showsAxisLabel(index: number, count: number): boolean {
  const today = count - 1
  const step = axisLabelEvery(count)
  if (step === 1 || index === today) return true
  const fromToday = today - index
  return fromToday % step === 0 && fromToday >= Math.max(step, 2)
}

/**
 * How many memories of one type were saved today and in the last 7 local days
 * (today included). `items` must reach back 7 days for `week` to be exact;
 * `complete` says whether they do.
 */
export function recentCount(
  items: (ListItem & { memory_type?: string })[],
  memoryType: string,
  now = new Date(),
) {
  const today = dayKey(now)
  const weekStart = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 6)
  let todayN = 0
  let weekN = 0
  let oldest = Infinity
  for (const it of items) {
    const t = new Date(it.timestamp)
    if (Number.isNaN(t.getTime())) continue
    oldest = Math.min(oldest, t.getTime())
    if (it.memory_type !== memoryType) continue
    if (t >= weekStart) weekN++
    if (dayKey(t) === today) todayN++
  }
  return { today: todayN, week: weekN, complete: oldest < weekStart.getTime() }
}
