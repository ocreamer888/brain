import { useState } from 'react'
import { getEpisode } from '../../api'
import { Button, SignalChip } from '../../components/brand/primitives'
import { dayKey } from '../../lib/activity'
import { useLoad } from '../../lib/useLoad'
import styles from './FactRow.module.css'

/**
 * One fact to review. `review`: { promoted, canUndo, rejected, busy, error }.
 * Promote can be undone, but only when canUndo is true (this session recorded
 * the real prior salience) -- otherwise Undo is disabled rather than guessing
 * a value to restore to. Reject is a feedback event the API can't take back,
 * so it has no undo and says the fact stays.
 */
// Past this, a fact is clamped to four lines with a "Show all" toggle.
const LONG = 360

export default function FactRow({ row, review, onPromote, onUndo, onReject, onOpen }) {
  const [full, setFull] = useState(false)
  const long = row.content.length > LONG
  const t = new Date(row.timestamp)
  const done = review.promoted || review.rejected
  return (
    <li className={styles.row} data-state={review.rejected ? 'rejected' : review.promoted ? 'promoted' : 'open'}>
      <div className={styles.meta}>
        {review.promoted && <SignalChip signal="use" icon="decision">promoted</SignalChip>}
        {review.rejected && <SignalChip signal="lesson" icon="close">rejected</SignalChip>}
        {row.project && <span className="t-small">{row.project}</span>}
        {!Number.isNaN(t.getTime()) && <span className="t-mono">{dayKey(t)}</span>}
        <span className={`t-mono ${styles.id}`}>#{row.id.slice(0, 8)}</span>
      </div>
      <p className={`t-body ${styles.text}`} data-clamped={long && !full}>
        {row.content}
      </p>
      {long && (
        <button type="button" className={`t-small ${styles.more}`} onClick={() => setFull((v) => !v)} aria-expanded={full}>
          {full ? 'Show less' : 'Show all'}
        </button>
      )}
      <div className={styles.actions}>
        {review.promoted ? (
          <Button
            onClick={onUndo}
            disabled={review.busy || !review.canUndo}
            title={review.canUndo ? undefined : 'Promoted before this session — no prior value on record to safely undo to.'}
          >
            Undo promote
          </Button>
        ) : (
          <Button icon="decision" onClick={onPromote} disabled={review.busy || review.rejected}>Promote</Button>
        )}
        <Button icon="close" onClick={onReject} disabled={review.busy || done} title="Records 'rejected' feedback. The fact itself stays.">
          Reject
        </Button>
        <Button icon="arrow" onClick={onOpen}>Open</Button>
        {row.parentId && <SourceToggle parentId={row.parentId} />}
        {review.busy && <span className={`t-small ${styles.quiet}`}>Saving…</span>}
        {review.error && <span className={`t-small ${styles.error}`} role="alert">{review.error}</span>}
      </div>
    </li>
  )
}

/** The episode this fact was extracted from, loaded only when asked for. */
function SourceToggle({ parentId }) {
  const [open, setOpen] = useState(false)
  const ep = useLoad(async () => (await getEpisode(parentId)).content ?? '(empty)', open ? parentId : null)
  return (
    <>
      <Button onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        {open ? 'Hide source' : 'Show source'}
      </Button>
      {open && (
        <div className={`t-body ${styles.source}`}>
          {ep.loading && <span className={styles.quiet}>Loading source…</span>}
          {ep.error && <span className={styles.error}>Couldn't load the source ({ep.error}).</span>}
          {ep.data}
        </div>
      )}
    </>
  )
}
