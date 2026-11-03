import { ArrowChip } from './primitives'
import styles from './GlowHero.module.css'

/**
 * Level-4 glow, Split mesh (§6.5). One per screen. Label and number sit on the
 * dark top (palest in light mode); the caption or stat strip and the arrow sit
 * in the lamp, in ink, so they hold contrast in both appearances. The ember
 * band between the two halves carries no text.
 */
export default function GlowHero({ label, value, caption, stats, actions, onOpen, openLabel }) {
  return (
    <section className={styles.hero}>
      <i className={styles.bg} aria-hidden />
      <div>
        <p className={`t-label ${styles.label}`}>{label}</p>
        <p className={`t-display ${styles.value}`}>{value}</p>
      </div>
      <div className={styles.foot}>
        {stats ? (
          <dl className={styles.stats}>
            {stats.map((s) => (
              <div key={s.label} className={styles.stat}>
                <dd className={styles.statValue}>{s.value}</dd>
                <dt className={`t-small ${styles.statLabel}`}>{s.label}</dt>
              </div>
            ))}
          </dl>
        ) : (
          caption && <p className={`t-body ${styles.caption}`}>{caption}</p>
        )}
        {actions && <div className={styles.actions}>{actions}</div>}
        {onOpen && <ArrowChip label={openLabel} onClick={onOpen} />}
      </div>
    </section>
  )
}
