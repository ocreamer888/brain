import { clearApiKey } from '../../api'
import Icon from './Icon'
import styles from './Dock.module.css'

export const VIEWS = [
  { id: 'dashboard', label: 'Dashboard' },
  { id: 'search', label: 'Search' },
  { id: 'linked', label: 'Linked' },
  { id: 'curate', label: 'Curate' },
  { id: 'eval', label: 'Eval' },
  { id: 'instances', label: 'Instances' },
]

/** Glass nav dock (ui/0229). Active = filled icon in a lighter glass circle. */
export default function Dock({ active, onSelect }) {
  return (
    <nav aria-label="Views" className={`glass ${styles.dock}`}>
      {VIEWS.map((v) => {
        const isActive = v.id === active
        return (
          <button
            key={v.id}
            type="button"
            title={v.label}
            aria-label={v.label}
            aria-current={isActive ? 'page' : undefined}
            onClick={() => onSelect(v.id)}
            className={`pressable ${styles.item}`}
          >
            <Icon name={v.id} filled={isActive} size={22} />
          </button>
        )
      })}
      <button
        type="button"
        title="Lock"
        aria-label="Lock"
        onClick={lock}
        className={`pressable ${styles.item}`}
      >
        <Icon name="lock" size={22} />
      </button>
    </nav>
  )
}

/** Clears the stored key and re-locks through the same path a 401 uses (see api.js). */
function lock() {
  clearApiKey()
  window.dispatchEvent(new CustomEvent('brain:unauthorized'))
}
