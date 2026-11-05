import { useState } from 'react'
import { getObservations, listMemories, patchMemory, searchIndex, sendFeedback } from '../api'
import Tile from '../components/brand/Tile'
import { Button, SearchPill } from '../components/brand/primitives'
import { isPromoted, toFactRow } from '../lib/curate'
import { friendlyError } from '../lib/instances'
import { useLoad } from '../lib/useLoad'
import { useSettled } from '../lib/useSettled'
import FactRow from './curate/FactRow'
import styles from './Curate.module.css'

const PAGE = 50
const PROMOTED_SALIENCE = 1.0

/** Facts in review order: newest when nothing is typed, best match otherwise. Always full rows. */
async function loadFacts(query) {
  const ids = query
    ? ((await searchIndex(query, PAGE, 'fact')).results ?? []).map((r) => r.id)
    : ((await listMemories(PAGE, { memoryType: 'fact' })).items ?? []).map((m) => m.id)
  if (!ids.length) return []
  const byId = new Map(((await getObservations(ids)).results ?? []).map((o) => [o.id, o]))
  return ids.map((id) => byId.get(id)).filter(Boolean).map(toFactRow)
}

/** Curate: review facts (brand book §13 "List"). Promote marks a fact reliable; Reject records feedback. */
export default function Curate({ onOpenMemory }) {
  const [query, setQuery] = useState('')
  const settled = useSettled(query.trim(), 300)
  const facts = useLoad(() => loadFacts(settled), `facts|${settled}`)
  const review = useReview()

  const rows = facts.data ?? []
  return (
    <div className={styles.page}>
      <section className={styles.list} aria-label="Facts to review">
        <SearchPill value={query} onChange={setQuery} placeholder="Search facts (empty shows the newest)" />
        <p className={`t-small ${styles.secondary}`} role="status">
          {facts.loading ? 'Loading facts…' : settled ? `${rows.length} matches for “${settled}”` : `${rows.length} newest facts, newest first`}
        </p>
        {facts.error && (
          <div className={`t-small ${styles.error}`} role="alert">
            <span>Couldn't load facts ({friendlyError(facts.error)}).</span>
            <Button onClick={facts.retry}>Retry</Button>
          </div>
        )}
        {!facts.loading && !facts.error && rows.length === 0 && (
          <p className={`t-body ${styles.secondary}`}>{settled ? 'No facts match. Try other words.' : 'No facts saved yet.'}</p>
        )}
        <ul className={styles.rows}>
          {rows.map((row) => (
            <FactRow
              key={row.id}
              row={row}
              review={review.stateOf(row)}
              onPromote={() => review.promote(row)}
              onUndo={() => review.undo(row)}
              onReject={() => review.reject(row)}
              onOpen={() => onOpenMemory?.(row.id)}
            />
          ))}
        </ul>
      </section>
      <HowItWorks counts={review.counts} />
    </div>
  )
}

/**
 * Review state per fact: what the server confirmed this session, layered over
 * what the data already says (a stored salience ≥ 0.95 means promoted earlier).
 * Nothing changes on screen until the server confirms.
 */
function useReview() {
  const [byId, setById] = useState({}) // id → { salience?, rejected?, prev?, busy?, error? }
  const patch = (id, next) => setById((m) => ({ ...m, [id]: { ...m[id], ...next } }))

  async function act(row, fn, after) {
    patch(row.id, { busy: true, error: null })
    try {
      await fn()
      patch(row.id, { busy: false, ...after })
    } catch (e) {
      patch(row.id, { busy: false, error: friendlyError(e.message || String(e)) })
    }
  }

  const stateOf = (row) => {
    const s = byId[row.id] ?? {}
    const salience = s.salience ?? row.salience
    // promoted reflects the real stored state (a fact promoted last session still shows
    // as promoted); canUndo is stricter -- only true when this session actually knows
    // the real prior salience to restore, so Undo never overwrites it with a guess.
    return {
      promoted: isPromoted(salience),
      canUndo: isPromoted(salience) && s.prev !== undefined,
      rejected: !!s.rejected,
      busy: !!s.busy,
      error: s.error ?? null,
    }
  }

  return {
    stateOf,
    promote: (row) =>
      act(
        row,
        () => patchMemory(row.id, { salience: PROMOTED_SALIENCE, salience_pinned: true }),
        { salience: PROMOTED_SALIENCE, prev: row.salience ?? 0.5, promotedNow: true },
      ),
    undo: (row) => {
      const prev = byId[row.id]?.prev ?? 0.5
      // salience_pinned: false -- restoring the pre-promotion value is not a
      // new deliberate pin (G0: PATCH defaults salience_pinned to true when
      // omitted, which would be wrong here).
      return act(
        row,
        () => patchMemory(row.id, { salience: prev, salience_pinned: false }),
        { salience: prev, promotedNow: false },
      )
    },
    reject: (row) =>
      act(row, () => sendFeedback({ event_type: 'rejected', memory_id: row.id, source: 'mcp' }), { rejected: true }),
    counts: {
      promoted: Object.values(byId).filter((s) => s.promotedNow).length,
      rejected: Object.values(byId).filter((s) => s.rejected).length,
    },
  }
}

function HowItWorks({ counts }) {
  return (
    <aside className={styles.side} aria-label="How curating works">
      <Tile icon="curate" title="This session" sub="Confirmed by the server">
        <p className={`t-kpi ${styles.primary}`}>
          {counts.promoted}
          <span className={styles.unit}> promoted</span>
        </p>
        <p className={`t-kpi ${styles.primary}`}>
          {counts.rejected}
          <span className={styles.unit}> rejected</span>
        </p>
      </Tile>
      <Tile icon="fact" title="What the buttons do">
        <p className={`t-small ${styles.secondary}`}>
          <strong className={styles.primary}>Promote</strong> marks a fact as reliable (importance 1.0, up from about 0.5). It shows as
          promoted from then on, and you can undo it.
        </p>
        <p className={`t-small ${styles.secondary} ${styles.note}`}>
          <strong className={styles.primary}>Reject</strong> records “not useful” feedback for ranking. The fact itself stays, and
          the API has no way to take the feedback back, so there's no undo.
        </p>
      </Tile>
    </aside>
  )
}
