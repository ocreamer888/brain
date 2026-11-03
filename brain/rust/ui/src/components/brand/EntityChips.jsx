import styles from './EntityChips.module.css'

const fmt = new Intl.NumberFormat('en-US')

/** `entities`: [{ id, name, memory_count }], already ranked. `onOpen(name)` opens Linked on it. */
export default function EntityChips({ entities, onOpen }) {
  return (
    <ul className={styles.chips}>
      {entities.map((e) => (
        <li key={e.id}>
          <button
            type="button"
            className={`pressable ${styles.chip}`}
            onClick={() => onOpen(e.name)}
            aria-label={`${e.name}: ${fmt.format(e.memory_count)} memories. Open in Linked`}
          >
            {e.name}
            <span className={styles.count} aria-hidden>
              {fmt.format(e.memory_count)}
            </span>
          </button>
        </li>
      ))}
    </ul>
  )
}
