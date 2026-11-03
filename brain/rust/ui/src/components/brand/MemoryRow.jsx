import { dayKey } from '../../lib/activity'
import { TypeChip } from './primitives'
import styles from './MemoryRow.module.css'

/**
 * Memory row (ui/0178, ui/0237): solid surface, never glass under text.
 * Meta above, two lines of body, id in mono.
 */
export default function MemoryRow({ memory, onOpen, selected = false }) {
  // The reader's own calendar day, not the UTC date baked into the timestamp.
  const t = new Date(memory.timestamp || '')
  const ts = Number.isNaN(t.getTime()) ? '' : dayKey(t)
  // Only a row that can open something is a button; otherwise it is plain content.
  const Row = onOpen ? 'button' : 'div'
  const rowProps = onOpen
    ? {
        type: 'button',
        onClick: () => onOpen(memory.id),
        'aria-current': selected ? 'true' : undefined,
        className: `pressable ${styles.row} ${styles.interactive}`,
      }
    : { className: styles.row, 'aria-current': selected ? 'true' : undefined }
  return (
    <li>
      <Row {...rowProps}>
        <div className={styles.meta}>
          <TypeChip type={memory.memory_type} />
          {memory.project && <span className={`t-small ${styles.project}`}>{memory.project}</span>}
          {ts && <span className={`t-mono ${styles.date}`}>{ts}</span>}
          {memory.id && <span className={`t-mono ${styles.id}`}>#{memory.id.slice(0, 8)}</span>}
        </div>
        <p className={`t-body ${styles.snippet}`}>{memory.snippet}</p>
      </Row>
    </li>
  )
}
