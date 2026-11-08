import { useState } from 'react'
import { getEntities, getNeighbors, getObservations, getRelated, getTimeline } from '../../api'
import { parseTags, toRow } from '../../lib/memoryRows'
import { useLoad } from '../../lib/useLoad'
import Icon from './Icon'
import MemoryRow from './MemoryRow'
import { Button, TypeChip } from './primitives'
import styles from './MemoryReading.module.css'

const when = new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeStyle: 'short' })

/**
 * One memory, read in full (brand book §9 "Memory reading"). Loads by id, so
 * it works for a search hit, a dashboard row, or a neighbor alike.
 * `onOpen(id)` moves the reader to another memory.
 */
export default function MemoryReading({ id, onOpen }) {
  const obs = useLoad(async () => (await getObservations([id])).results?.[0] ?? null, id)
  if (obs.loading && !obs.data) return <p className={`t-body ${styles.quiet}`}>Loading memory…</p>
  if (obs.error) return <LoadError what="this memory" message={obs.error} onRetry={obs.retry} />
  if (!obs.data) return <p className={`t-body ${styles.quiet}`}>This memory no longer exists.</p>

  const m = obs.data.metadata ?? {}
  return (
    <article className={styles.reading} aria-label="Memory">
      <ReadingMeta memory={obs.data} />
      {m.superseded_by && (
        <p className={`t-small ${styles.notice}`} role="note">
          <Icon name="pattern" size={16} />
          A newer memory replaces this one.
          <button type="button" className={styles.link} onClick={() => onOpen(String(m.superseded_by))}>
            Read the newer one
          </button>
        </p>
      )}
      <p className={`t-body ${styles.body}`}>{obs.data.content}</p>
      <Tags tags={parseTags(m.tags)} />
      <Linked id={id} onOpen={onOpen} />
      <Related id={id} onOpen={onOpen} />
      <Around id={id} onOpen={onOpen} />
    </article>
  )
}

function ReadingMeta({ memory }) {
  const m = memory.metadata ?? {}
  const ts = memory.timestamp || m.timestamp
  return (
    <header className={styles.meta}>
      <div className={styles.metaRow}>
        <TypeChip type={m.type} />
        {m.project && <span className="t-small">{m.project}</span>}
        {ts && <span className="t-small">{when.format(new Date(ts))}</span>}
        {m.source && <span className="t-small">via {m.source}</span>}
      </div>
      {m.title && <h2 className={`t-h2 ${styles.title}`}>{m.title}</h2>}
      <div className={styles.metaRow}>
        <span className="t-mono">#{memory.id.slice(0, 8)}</span>
        <CopyId id={memory.id} />
      </div>
    </header>
  )
}

function CopyId({ id }) {
  const [copied, setCopied] = useState(false)
  async function copy() {
    try {
      await navigator.clipboard.writeText(id)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      setCopied(false)
    }
  }
  return (
    <button type="button" className={`pressable t-small ${styles.copy}`} onClick={copy} aria-live="polite">
      <Icon name={copied ? 'decision' : 'copy'} size={14} />
      {copied ? 'Copied' : 'Copy id'}
    </button>
  )
}

function Tags({ tags }) {
  if (!tags.length) return null
  return (
    <ul className={styles.tags} aria-label="Tags">
      {tags.map((t) => (
        <li key={t} className={styles.tag}>
          {t}
        </li>
      ))}
    </ul>
  )
}

const NEIGHBOR_PAGE = 10

/**
 * Entities this memory mentions, and memories that share them (real edges only, §8.2).
 * A busy entity can link hundreds of memories, so neighbors load a page at a time.
 */
function Linked({ id, onOpen }) {
  const [limit, setLimit] = useState(NEIGHBOR_PAGE)
  const links = useLoad(async () => {
    const [ent, neigh] = await Promise.all([getEntities(id), getNeighbors(id)])
    return { entities: ent.entities || [], ids: neigh.ids || [] }
  }, id)
  const ids = links.data?.ids ?? []
  const page = ids.slice(0, limit)
  const rows = useLoad(
    async () => ((await getObservations(page)).results || []).map(toRow),
    page.length ? `${id}|${page.length}` : null,
  )
  const empty = links.data && links.data.entities.length === 0 && ids.length === 0
  return (
    <section className={styles.section} aria-label="Linked memories">
      <div className={styles.sectionHead}>
        <h3 className="t-label">Linked</h3>
        {ids.length > 0 && <span className="t-small">{ids.length} via shared entities</span>}
      </div>
      {links.loading && <p className={`t-small ${styles.quiet}`}>Loading links…</p>}
      {links.error && <LoadError what="links" message={links.error} onRetry={links.retry} />}
      {empty && <p className={`t-small ${styles.quiet}`}>Not linked to anything yet.</p>}
      {links.data?.entities.length > 0 && (
        <ul className={styles.entities} aria-label="Entities">
          {links.data.entities.map((e) => (
            <li key={e.id} className={styles.tag} title={e.id}>
              {e.name}
            </li>
          ))}
        </ul>
      )}
      {rows.error && <LoadError what="linked memories" message={rows.error} onRetry={rows.retry} />}
      <MemoryList rows={rows.data} onOpen={onOpen} />
      {ids.length > limit && (
        <div>
          <Button onClick={() => setLimit((n) => n + NEIGHBOR_PAGE)} disabled={rows.loading}>
            {rows.loading ? 'Loading…' : `Show ${Math.min(NEIGHBOR_PAGE, ids.length - limit)} more of ${ids.length}`}
          </Button>
        </div>
      )}
    </section>
  )
}

/**
 * Nearest other memories by embedding similarity (G7, spec §7.3) -- distinct from
 * Linked's shared-entity edges: no entity in common required, just close in meaning.
 * Response rows already match MemoryRow's shape, so no toRow/getObservations round-trip.
 */
function Related({ id, onOpen }) {
  const related = useLoad(async () => (await getRelated(id)).related || [], id)
  const rows = related.data ?? []
  return (
    <section className={styles.section} aria-label="Related memories">
      <div className={styles.sectionHead}>
        <h3 className="t-label">Related</h3>
        {rows.length > 0 && <span className="t-small">{rows.length} by similarity</span>}
      </div>
      {related.loading && <p className={`t-small ${styles.quiet}`}>Loading related memories…</p>}
      {related.error && <LoadError what="related memories" message={related.error} onRetry={related.retry} />}
      {related.data && rows.length === 0 && <p className={`t-small ${styles.quiet}`}>No close matches yet.</p>}
      <MemoryList rows={rows} onOpen={onOpen} />
    </section>
  )
}

/** What was saved just before and after (§8.5: a column in time, not a web). Loaded on request. */
function Around({ id, onOpen }) {
  const [asked, setAsked] = useState(null)
  const around = useLoad(async () => ((await getTimeline(id)).results || []).map(toRow), asked === id ? id : null)
  return (
    <section className={styles.section} aria-label="Saved around it">
      <div className={styles.sectionHead}>
        <h3 className="t-label">Saved around it</h3>
      </div>
      {asked !== id && (
        <div>
          <Button icon="conversation" onClick={() => setAsked(id)}>
            Show what was saved before and after
          </Button>
        </div>
      )}
      {around.loading && <p className={`t-small ${styles.quiet}`}>Loading timeline…</p>}
      {around.error && <LoadError what="the timeline" message={around.error} onRetry={around.retry} />}
      <MemoryList rows={around.data} onOpen={onOpen} currentId={id} />
    </section>
  )
}

function MemoryList({ rows, onOpen, currentId }) {
  if (!rows?.length) return null
  return (
    <ul className={styles.rows}>
      {rows.map((r) => (
        <MemoryRow
          key={r.id}
          memory={r}
          selected={r.id === currentId}
          onOpen={r.id === currentId ? undefined : onOpen}
        />
      ))}
    </ul>
  )
}

function LoadError({ what, message, onRetry }) {
  return (
    <div className={`t-small ${styles.error}`} role="alert">
      <span>
        Couldn't load {what} ({message}).
      </span>
      <Button onClick={onRetry}>Retry</Button>
    </div>
  )
}
