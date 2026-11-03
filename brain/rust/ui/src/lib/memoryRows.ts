/**
 * The API returns memories in two shapes: search hits (flat) and observations
 * (content + metadata). Rows and the reading pane want one shape.
 */
export type Observation = {
  id: string
  content?: string
  timestamp?: string
  metadata?: Record<string, unknown> | null
}

export type MemoryRow = {
  id: string
  memory_type: string
  project: string
  timestamp: string
  snippet: string
}

const SNIPPET = 200

/** /v1/search_index cuts `snippet` at exactly this many chars (brain_api.rs, search handler). */
export const SEARCH_SNIPPET_CHARS = 120

/** Mark text that was cut at `limit` chars, so a clipped sentence never reads as complete. */
export function markCut(text: string, limit: number): string {
  return [...text].length >= limit ? `${text.trimEnd()}…` : text
}

export function toRow(o: Observation): MemoryRow {
  const m = o.metadata ?? {}
  return {
    id: o.id,
    memory_type: String(m.type ?? m.memory_type ?? ''),
    project: String(m.project ?? ''),
    timestamp: String(o.timestamp ?? m.timestamp ?? ''),
    snippet: markCut((o.content ?? '').slice(0, SNIPPET), (o.content ?? '').length > SNIPPET ? SNIPPET : Infinity),
  }
}

/** Tags arrive as one comma-separated string; empty pieces are dropped. */
export function parseTags(tags: unknown): string[] {
  if (typeof tags !== 'string') return []
  return [...new Set(tags.split(',').map((t) => t.trim()).filter(Boolean))]
}
