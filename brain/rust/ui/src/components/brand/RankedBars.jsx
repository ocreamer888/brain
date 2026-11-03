import { TypeChip } from './primitives'
import styles from './RankedBars.module.css'

const fmt = new Intl.NumberFormat('en-US')

/**
 * Counts, largest first; each row reads aloud as one sentence. `label(key)`
 * renders the row's identity (default: the memory type chip); `nameOf(key)` is
 * what a screen reader hears for it (default: the key itself).
 */
export default function RankedBars({ counts, label = (k) => <TypeChip type={k} />, nameOf = (k) => k, noun = 'memories' }) {
  const rows = Object.entries(counts).sort((a, b) => b[1] - a[1])
  const total = rows.reduce((n, [, v]) => n + v, 0)
  const max = rows[0]?.[1] || 1
  return (
    <ul className={styles.list}>
      {rows.map(([type, value]) => {
        const share = total ? (value / total) * 100 : 0
        return (
          <li
            key={type}
            tabIndex={0}
            className={styles.row}
            aria-label={`${nameOf(type)}: ${fmt.format(value)} ${noun}, ${share.toFixed(1)}%`}
          >
            {label(type)}
            <div className={styles.track} aria-hidden>
              <div className={styles.bar} style={{ width: `${(value / max) * 100}%` }} />
            </div>
            <span className={`t-mono ${styles.value}`}>
              {fmt.format(value)}
              <span className={styles.share}>{share < 1 ? '<1' : Math.round(share)}%</span>
            </span>
          </li>
        )
      })}
    </ul>
  )
}

/** Label for non-type rows (projects, sources). */
export function NameLabel(name) {
  return (
    <span className={`t-small ${styles.name}`} title={name}>
      {name}
    </span>
  )
}
