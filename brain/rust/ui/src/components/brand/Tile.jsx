import Icon from './Icon'
import { ArrowChip } from './primitives'
import styles from './Tile.module.css'

/** One idea per tile (§2.9). The ↗ opens the view that owns the data. */
/** `actions`: controls for the header (e.g. a range picker), placed before the ↗. */
export default function Tile({ icon, title, sub, onOpen, openLabel, tone, actions, children, className = '' }) {
  return (
    <section className={`${styles.tile} ${tone === 'lamp' ? styles.lamp : ''} ${className}`}>
      <header className={styles.head}>
        {icon && (
          <span className={styles.icon}>
            <Icon name={icon} size={18} />
          </span>
        )}
        <div className={styles.titles}>
          <h3 className={`t-h2 ${styles.title}`}>{title}</h3>
          {sub && <p className={`t-small ${styles.sub}`}>{sub}</p>}
        </div>
        {actions}
        {onOpen && <ArrowChip label={openLabel ?? `Open ${title}`} onClick={onOpen} />}
      </header>
      <div className={styles.body}>{children}</div>
    </section>
  )
}
