import { headline, lessonParts, relativeTime } from '../../lib/spotlight'
import Tile from './Tile'
import styles from './Spotlight.module.css'

/**
 * One memory worth re-reading (latest decision, latest lesson). `state` is a
 * useLoad result whose data is an observation ({ id, content, timestamp, metadata }).
 */
export default function Spotlight({ icon, title, state, onOpen, className }) {
  const obs = state.data
  const m = obs?.metadata ?? {}
  const when = obs ? relativeTime(obs.timestamp || m.timestamp) : ''
  const sub = obs ? [m.project, when].filter(Boolean).join(' · ') : undefined
  return (
    <Tile
      className={className}
      icon={icon}
      title={title}
      sub={sub}
      onOpen={obs ? () => onOpen(obs.id) : undefined}
      openLabel={`Open ${title.toLowerCase()}`}
    >
      {state.loading && !obs && <p className={`t-small ${styles.quiet}`}>Loading…</p>}
      {state.error && <p className={`t-small ${styles.quiet}`} role="alert">Couldn't load ({state.error}).</p>}
      {!state.loading && !state.error && !obs && <p className={`t-small ${styles.quiet}`}>None saved yet.</p>}
      {obs && <Body obs={obs} />}
    </Tile>
  )
}

function Body({ obs }) {
  const lesson = lessonParts(obs.content)
  // A lesson's stored title is a clipped "Fix: <error…>"; its Error line says it in full.
  const title = lesson?.error ? headline(null, lesson.error) : headline(obs.metadata?.title, obs.content)
  // Without a stored title the headline is the first line; don't repeat it below.
  const rest = obs.metadata?.title ? obs.content : obs.content.split('\n').slice(1).join('\n').trim()
  return (
    <>
      <p className={styles.headline}>{title}</p>
      {lesson ? (
        <p className={`t-small ${styles.text}`}>
          <span className={styles.fixLabel}>Fix</span>
          {lesson.fix}
        </p>
      ) : (
        rest && <p className={`t-small ${styles.text}`}>{rest}</p>
      )}
    </>
  )
}
