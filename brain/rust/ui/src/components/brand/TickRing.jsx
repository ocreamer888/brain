import styles from './TickRing.module.css'

const TICKS = 60

/**
 * A 0–1 ratio as a ring of ticks (ui/0246). `value` fills ticks clockwise from
 * the top; `label` reads aloud, `children` is what's printed in the middle.
 */
export default function TickRing({ value, size = 168, tone = 'ok', label, children }) {
  const filled = Math.round(Math.min(1, Math.max(0, value)) * TICKS)
  const r = size / 2
  const outer = r - 2
  const inner = r - 14
  return (
    <div className={styles.ring} style={{ width: size, height: size }} data-tone={tone} role="img" aria-label={label}>
      <svg className={styles.svg} viewBox={`0 0 ${size} ${size}`} aria-hidden>
        {Array.from({ length: TICKS }, (_, i) => {
          const a = (i / TICKS) * 2 * Math.PI - Math.PI / 2
          const cos = Math.cos(a)
          const sin = Math.sin(a)
          return (
            <line
              key={i}
              x1={r + inner * cos}
              y1={r + inner * sin}
              x2={r + outer * cos}
              y2={r + outer * sin}
              strokeWidth="2.5"
              strokeLinecap="round"
              className={i < filled ? styles.on : styles.off}
            />
          )
        })}
      </svg>
      <div className={styles.center}>{children}</div>
    </div>
  )
}

TickRing.Value = function Value({ children }) {
  return <span className={styles.value}>{children}</span>
}

TickRing.Caption = function Caption({ children }) {
  return <span className={`t-small ${styles.caption}`}>{children}</span>
}
