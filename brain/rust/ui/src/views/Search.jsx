import { useEffect, useState } from 'react'
import { searchIndex } from '../api'
import MemoryReading from '../components/brand/MemoryReading'
import MemoryRow from '../components/brand/MemoryRow'
import { Button, FilterChip, SearchPill } from '../components/brand/primitives'
import { SEARCH_SNIPPET_CHARS, markCut } from '../lib/memoryRows'
import { useLoad } from '../lib/useLoad'
import { useSettled } from '../lib/useSettled'
import { MEMORY_SIGNALS, MEMORY_TYPES } from '../lib/memorySignals'
import styles from './Search.module.css'

const PAGE = 20
// Fetched once per (query, type) and sliced client-side as "Show more" grows
// `limit` -- `limit` used to be part of the fetch itself, so every click
// re-ran a full server-side embed + cosine/BM25 rank at a bigger n instead
// of revealing more of an already-ranked result set. FETCH is the ceiling on
// how far "Show more" can reveal without a real re-fetch (not implemented --
// same bounded-fetch tradeoff Dashboard.jsx's ACTIVITY_SAMPLE already makes).
const FETCH = 100

/** Search: results left, the open memory right (brand book §10, §13). */
export default function Search({ focusId, onFocused, initialQuery = '' }) {
  const [query, setQuery] = useState(initialQuery)
  const [type, setType] = useState('all')
  const [limit, setLimit] = useState(PAGE)
  const [selected, setSelected] = useState(null)
  const settled = useSettled(query.trim(), 250)

  // A memory opened from elsewhere (Dashboard) reads here even if no search ran.
  useEffect(() => {
    if (!focusId) return
    setSelected(focusId)
    onFocused?.()
  }, [focusId]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => setLimit(PAGE), [settled, type])

  const results = useLoad(
    async () => (await searchIndex(settled, FETCH, type === 'all' ? null : type)).results || [],
    settled ? `${settled}|${type}` : null,
  )

  return (
    <div className={styles.layout} data-reading={selected ? 'true' : 'false'}>
      <section className={styles.listPane} aria-label="Search results">
        <div className={styles.controls}>
          <SearchPill value={query} onChange={setQuery} placeholder="Search memories" />
          <div className={styles.chips}>
            <FilterChip selected={type === 'all'} onClick={() => setType('all')}>All</FilterChip>
            {MEMORY_TYPES.map((t) => (
              <FilterChip key={t} selected={type === t} icon={MEMORY_SIGNALS[t].icon} onClick={() => setType(t)}>
                {MEMORY_SIGNALS[t].label}
              </FilterChip>
            ))}
          </div>
        </div>
        <div className={styles.scroll}>
          <Results
            query={settled}
            type={type}
            state={results}
            limit={limit}
            selected={selected}
            onSelect={setSelected}
            onMore={() => setLimit((n) => Math.min(n + PAGE, FETCH))}
          />
        </div>
      </section>
      <section className={styles.readPane} aria-label="Reading">
        <div className={styles.back}>
          <Button icon="back" onClick={() => setSelected(null)}>
            Back to results
          </Button>
        </div>
        <div className={styles.readScroll}>
          {selected ? (
            <MemoryReading key={selected} id={selected} onOpen={setSelected} />
          ) : (
            <Empty title="Pick a result to read it here." />
          )}
        </div>
      </section>
    </div>
  )
}

function Results({ query, type, state, limit, selected, onSelect, onMore }) {
  if (!query) {
    return (
      <Empty
        title="Search everything this brain keeps."
        hint="Words, a project, an error message, a decision. Results are ranked by meaning, so near matches count."
      />
    )
  }
  if (state.error) {
    return (
      <div className={`t-small ${styles.error}`} role="alert">
        <span>Search failed ({state.error}).</span>
        <Button onClick={state.retry}>Retry</Button>
      </div>
    )
  }
  const all = state.data || []
  const rows = all.slice(0, limit)
  const hasMore = rows.length < all.length
  // all.length hitting the fetch ceiling means there could be even more
  // beyond it we have no way to know about without a real re-fetch.
  const showPlus = hasMore || all.length === FETCH
  const typeWord = type === 'all' ? '' : ` ${MEMORY_SIGNALS[type]?.label}`
  return (
    <>
      <p className={`t-small ${styles.status}`} role="status">
        {state.loading ? 'Searching…' : `${rows.length}${showPlus ? '+' : ''}${typeWord} results for “${query}”`}
      </p>
      {!state.loading && rows.length === 0 && (
        <Empty title={`Nothing matches “${query}”.`} hint={type === 'all' ? 'Try fewer or different words.' : 'Try All types.'} />
      )}
      <ul className={styles.rows}>
        {rows.map((m) => (
          <MemoryRow
            key={m.id}
            memory={{ ...m, snippet: markCut(m.snippet || '', SEARCH_SNIPPET_CHARS) }}
            selected={m.id === selected}
            onOpen={onSelect}
          />
        ))}
      </ul>
      {!state.loading && hasMore && (
        <div className={styles.more}>
          <Button onClick={onMore}>Show {PAGE} more</Button>
        </div>
      )}
    </>
  )
}

function Empty({ title, hint }) {
  return (
    <div className={styles.empty}>
      <p className={`t-h2 ${styles.emptyTitle}`}>{title}</p>
      {hint && <p className={`t-small ${styles.secondary}`}>{hint}</p>}
    </div>
  )
}
