/** Helpers for the Instances view (API: /v1/instances*). */

export type Instance = {
  id: string
  name: string
  description?: string
  tags?: string[]
  memory_count?: number | null
  archived?: boolean
  created_at?: string
  db_path?: string
}

/** Active first, then archived last, then by name. */
export function sortInstances(list: Instance[], activeId: string | null): Instance[] {
  return [...list].sort((a, b) => {
    if (a.id === activeId) return -1
    if (b.id === activeId) return 1
    if (!!a.archived !== !!b.archived) return a.archived ? 1 : -1
    return a.name.localeCompare(b.name)
  })
}

/** "a, b,, a " → ["a", "b"]: trimmed, no empties, no repeats. */
export function parseTagInput(text: string): string[] {
  return [...new Set(text.split(',').map((t) => t.trim()).filter(Boolean))]
}

/**
 * api.js throws `Error("<status>: <body>")`, where the body is `{"error":"…"}`.
 * Turn that into a sentence a person can act on.
 */
export function friendlyError(message: string): string {
  const m = /^(\d{3})(?::\s*(.*))?$/s.exec(message.trim())
  if (!m) return message
  const status = Number(m[1])
  let detail = m[2] ?? ''
  try {
    detail = JSON.parse(detail).error ?? detail
  } catch {
    /* body was not JSON; keep it */
  }
  if (status === 503) return 'The server is busy switching brains. Try again in a moment.'
  if (status === 404) return 'That brain no longer exists. The list has been refreshed.'
  const text = String(detail).trim()
  return text ? text[0].toUpperCase() + text.slice(1) + (/[.!?]$/.test(text) ? '' : '.') : `Request failed (${status}).`
}
