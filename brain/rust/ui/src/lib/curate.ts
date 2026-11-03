/** Curate: facts with the state worth reviewing. */
import type { Observation } from './memoryRows'

/** Promote stores salience 1.0; facts arrive at ~0.5. Anything this high was promoted. */
export const PROMOTED_AT = 0.95

export type FactRow = {
  id: string
  content: string
  project: string
  timestamp: string
  salience: number | null
  parentId: string | null
}

export function toFactRow(o: Observation): FactRow {
  const m = (o.metadata ?? {}) as Record<string, unknown>
  return {
    id: o.id,
    content: o.content ?? '',
    project: String(m.project ?? ''),
    timestamp: String(o.timestamp ?? m.timestamp ?? ''),
    salience: typeof m.salience === 'number' ? m.salience : null,
    parentId: typeof m.parent_id === 'string' && m.parent_id ? m.parent_id : null,
  }
}

export function isPromoted(salience: number | null | undefined): boolean {
  return typeof salience === 'number' && salience >= PROMOTED_AT
}
