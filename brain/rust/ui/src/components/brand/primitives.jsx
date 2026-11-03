import Icon from './Icon'
import { signalFor } from '../../lib/memorySignals'
import styles from './primitives.module.css'

const cx = (...names) => names.filter(Boolean).join(' ')

/** Signal chip (§5.6): color + icon + word. Used for states like pass/fail. */
export function SignalChip({ signal, icon, children }) {
  return (
    <span className={styles.chip} data-signal={signal}>
      {icon && <Icon name={icon} size={14} />}
      {children}
    </span>
  )
}

/** Memory type chip: the signal, icon, and word for a memory_type. */
export function TypeChip({ type }) {
  const { signal, icon, label } = signalFor(type)
  return (
    <SignalChip signal={signal} icon={icon}>
      {label}
    </SignalChip>
  )
}

/** One per screen: the lamp. Everything else is `quiet`. */
export function Button({ variant = 'quiet', icon, children, className, ...rest }) {
  const look = variant === 'primary' ? styles.primary : cx('glass', styles.quiet)
  return (
    <button type="button" className={cx('pressable hit', styles.button, look, className)} {...rest}>
      {icon && <Icon name={icon} size={16} />}
      {children}
    </button>
  )
}

/** ↗ in a circle: opens the thing it sits on. */
export function ArrowChip({ label = 'Open', ...rest }) {
  return (
    <button type="button" aria-label={label} className={cx('pressable hit', styles.arrow)} {...rest}>
      <Icon name="arrow" size={18} />
    </button>
  )
}

/** Selectable pill (type filters, tabs). */
export function FilterChip({ selected, icon, children, ...rest }) {
  return (
    <button type="button" aria-pressed={selected} className={cx('pressable', styles.filter)} {...rest}>
      {icon && <Icon name={icon} size={14} />}
      {children}
    </button>
  )
}

/** Search pill. With `onSubmit`, Enter hands the query to whoever owns search. */
export function SearchPill({ value, onChange, onSubmit, placeholder = 'Search memories' }) {
  return (
    <label className={cx('glass', styles.search)}>
      <Icon name="search" size={18} />
      <input
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && onSubmit && value.trim()) onSubmit(value.trim())
        }}
        placeholder={placeholder}
        aria-label={placeholder}
      />
    </label>
  )
}

export function KpiTile({ label, value, delta }) {
  return (
    <div className={styles.kpi}>
      <p className={cx('t-label', styles.kpiLabel)}>{label}</p>
      <p className={cx('t-kpi', styles.kpiValue)}>{value}</p>
      {delta && <p className={cx('t-small', styles.kpiDelta)}>{delta}</p>}
    </div>
  )
}

const LIVE_WORDS = { live: 'live', connecting: 'connecting', reconnecting: 'reconnecting' }

/** Live dot: dusk + the word. Breathes only while not yet live (§11). */
export function LiveDot({ state = 'live' }) {
  const live = state === 'live'
  return (
    <span className={cx('t-small', styles.live)} role="status">
      <span className={cx(styles.dot, !live && styles.breathing)} />
      {LIVE_WORDS[state] ?? state}
    </span>
  )
}

/**
 * Segmented control: one choice out of a few (`options`: [{ value, label }]).
 * A real radio group: one tab stop, arrow keys move and select (WAI-ARIA radio pattern).
 */
export function Segmented({ label, options, value, onChange }) {
  const index = Math.max(0, options.findIndex((o) => o.value === value))
  function onKeyDown(e) {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key]
    if (!step) return
    e.preventDefault()
    const next = options[(index + step + options.length) % options.length]
    onChange(next.value)
    e.currentTarget.parentElement?.querySelectorAll('[role="radio"]')[options.indexOf(next)]?.focus()
  }
  return (
    <div role="radiogroup" aria-label={label} className={cx('glass', styles.segmented)}>
      {options.map((o, i) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          tabIndex={i === index ? 0 : -1}
          className={cx('pressable', styles.segment)}
          onClick={() => onChange(o.value)}
          onKeyDown={onKeyDown}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
