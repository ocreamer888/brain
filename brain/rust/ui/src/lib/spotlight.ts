/** Text helpers for spotlight cards (latest decision, latest lesson). */

const HEADLINE = 90

/** The memory's title, else its first line, cut at a word boundary with "…". */
export function headline(title: unknown, content = ''): string {
  if (typeof title === 'string' && title.trim()) return title.trim()
  const first = content.split('\n').find((l) => l.trim())?.trim() ?? ''
  if (first.length <= HEADLINE) return first
  const cut = first.slice(0, HEADLINE)
  const space = cut.lastIndexOf(' ')
  return `${(space > 40 ? cut.slice(0, space) : cut).trimEnd()}…`
}

export type Lesson = { error?: string; cause?: string; fix: string }

/** Lessons saved as "Error: … / Cause: … / Fix: …". Only a lesson with a Fix line counts. */
export function lessonParts(content = ''): Lesson | null {
  const pick = (label: string) => content.match(new RegExp(`^${label}:\\s*(.+)$`, 'mi'))?.[1]?.trim()
  const fix = pick('Fix')
  if (!fix) return null
  return { error: pick('Error'), cause: pick('Cause'), fix }
}

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['year', 365 * 86400],
  ['month', 30 * 86400],
  ['week', 7 * 86400],
  ['day', 86400],
  ['hour', 3600],
  ['minute', 60],
]
const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })

/** "3 hours ago", "yesterday", "just now". Empty string for an unreadable date. */
export function relativeTime(iso: string, now = new Date()): string {
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return ''
  const secs = Math.round((t - now.getTime()) / 1000)
  for (const [unit, size] of UNITS) {
    if (Math.abs(secs) >= size) return rtf.format(Math.round(secs / size), unit)
  }
  return 'just now'
}
