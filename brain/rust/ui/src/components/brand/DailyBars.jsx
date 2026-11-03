import { useState } from 'react'
import { showsAxisLabel } from '../../lib/activity'
import styles from './DailyBars.module.css'

const fmt = new Intl.NumberFormat('en-US')
const long = new Intl.DateTimeFormat('en-US', { weekday: 'short', month: 'short', day: 'numeric' })

/** `days`: [{ date: 'YYYY-MM-DD', count }], oldest → newest; the last one is today. */
export default function DailyBars({ days }) {
  const [hover, setHover] = useState(null)
  const max = Math.max(1, ...days.map((d) => d.count))
  const peak = days.findIndex((d) => d.count === max && d.count > 0)
  const today = days.length - 1
  const h = days[hover]
  return (
    <div className={styles.wrap}>
      <div className={styles.plot} onMouseLeave={() => setHover(null)}>
        {days.map((d, i) => {
          const pct = (d.count / max) * 100
          const labelled = i === peak || i === today
          return (
            <button
              key={d.date}
              type="button"
              className={styles.col}
              data-zero={d.count === 0}
              style={{ '--h': `${pct}%` }}
              aria-label={`${long.format(parse(d.date))}: ${fmt.format(d.count)} saved`}
              onMouseEnter={() => setHover(i)}
              onFocus={() => setHover(i)}
              onBlur={() => setHover(null)}
            >
              {labelled && <span className={`t-mono ${styles.label}`}>{fmt.format(d.count)}</span>}
              <span className={styles.bar} style={{ height: `${pct}%` }} />
            </button>
          )
        })}
      </div>
      <div className={`t-small ${styles.axis}`} aria-hidden>
        {days.map((d, i) => (
          <span key={d.date} className={i === today ? styles.today : undefined}>
            {i === today ? 'today' : showsAxisLabel(i, days.length) ? parse(d.date).getDate() : ''}
          </span>
        ))}
      </div>
      {h && (
        <div className={`glass t-small ${styles.tip}`} style={{ left: `${((hover + 0.5) / days.length) * 100}%` }}>
          {long.format(parse(h.date))} · {fmt.format(h.count)} saved
        </div>
      )}
    </div>
  )
}

/** 'YYYY-MM-DD' as a local date (new Date('YYYY-MM-DD') would be UTC midnight). */
function parse(key) {
  const [y, m, d] = key.split('-').map(Number)
  return new Date(y, m - 1, d)
}
