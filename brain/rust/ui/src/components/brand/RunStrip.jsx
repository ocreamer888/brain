import { useState } from 'react'
import styles from './RunStrip.module.css'

/**
 * Recent eval runs. Height = P@1 (0–1), so a dip is visible; color and the
 * tooltip word carry pass/fail. Runs come oldest → newest.
 */
export default function RunStrip({ runs }) {
  const [hover, setHover] = useState(null)
  const h = runs[hover]
  return (
    <div className={styles.wrap}>
      <div className={styles.strip} onMouseLeave={() => setHover(null)}>
        {runs.map((r, i) => (
          <button
            key={r.run_id}
            type="button"
            data-pass={r.pass}
            className={styles.cell}
            aria-label={`${r.run_id}: ${r.pass ? 'pass' : 'fail'}, P@1 ${r.p1.toFixed(2)}`}
            onMouseEnter={() => setHover(i)}
            onFocus={() => setHover(i)}
            onBlur={() => setHover(null)}
          >
            <span className={styles.mark} style={{ height: `${Math.max(r.p1, 0.08) * 100}%` }} />
          </button>
        ))}
      </div>
      {h && (
        <div className={`glass ${styles.tip}`} style={{ left: `${((hover + 0.5) / runs.length) * 100}%` }}>
          <p className="t-small">
            {h.pass ? 'Pass' : 'Fail'} · P@1 {h.p1.toFixed(2)}
          </p>
          <p className={`t-mono ${styles.tipMeta}`}>{h.run_id}</p>
        </div>
      )}
      <div className={`t-small ${styles.axis}`} aria-hidden>
        <span>{runs[0]?.run_id.slice(0, 10)}</span>
        <span>{runs.at(-1)?.run_id.slice(0, 10)}</span>
      </div>
    </div>
  )
}
