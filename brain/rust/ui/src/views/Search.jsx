import { useEffect, useRef, useState } from 'react'
import { getObservations, getTimeline, searchIndex } from '../api'
import { ExpandedCard } from '../components/MemoryCard'

const TYPES = ['all', 'fact', 'conversation', 'solution', 'pattern', 'project_context']

function debounce(fn, ms) {
  let t
  return (...args) => {
    clearTimeout(t)
    t = setTimeout(() => fn(...args), ms)
  }
}

export default function Search({ focusId, onFocused }) {
  const [query, setQuery] = useState('')
  const [typeFilter, setTypeFilter] = useState('all')
  const [results, setResults] = useState([])
  const [fullById, setFullById] = useState({})
  const [searchError, setSearchError] = useState(null)
  const [timeline, setTimeline] = useState(null)
  const [openIds, setOpenIds] = useState(() => new Set())

  const doSearch = useRef(
    debounce(async (q, tf) => {
      if (!q.trim()) {
        setResults([])
        return
      }
      setSearchError(null)
      try {
        const data = await searchIndex(
          q,
          20,
          tf === 'all' ? null : tf,
        )
        setResults(data.results || [])
      } catch (e) {
        setSearchError(e.message)
      }
    }, 250),
  ).current

  useEffect(() => {
    doSearch(query, typeFilter)
  }, [query, typeFilter, doSearch])

  useEffect(() => {
    if (!focusId) return
    setOpenIds((prev) => new Set(prev).add(focusId))
    loadFull(focusId)
    onFocused?.()
  }, [focusId]) // eslint-disable-line react-hooks/exhaustive-deps

  async function loadFull(id) {
    if (fullById[id]) return
    try {
      const data = await getObservations([id])
      const mem = (data.results || [])[0]
      setFullById((prev) => ({
        ...prev,
        [id]: mem?.content ?? '(empty)',
      }))
    } catch (e) {
      setFullById((prev) => ({ ...prev, [id]: `Failed: ${e.message}` }))
    }
  }

  async function handleTimeline(id) {
    try {
      const data = await getTimeline(id)
      setTimeline({ anchorId: id, rows: data.results || [] })
    } catch (e) {
      setTimeline({ anchorId: id, error: e.message, rows: [] })
    }
  }

  function handleOpenLinked(id) {
    setOpenIds((prev) => new Set(prev).add(id))
    loadFull(id)
    const el = document.getElementById(`mem-${id}`)
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }

  return (
    <div className="p-8 max-w-4xl">
      <h2 className="text-lg font-semibold text-white mb-4">Search</h2>
      <input
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search memories…"
        className="w-full rounded border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-white placeholder:text-zinc-600 focus:outline-none focus:border-zinc-500"
      />
      <div className="mt-3 flex flex-wrap gap-2">
        {TYPES.map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTypeFilter(t)}
            className={`rounded px-2.5 py-1 text-xs font-mono ${
              typeFilter === t
                ? 'bg-zinc-200 text-black'
                : 'bg-zinc-900 text-zinc-400 hover:text-zinc-200'
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {searchError && (
        <p className="mt-4 text-sm text-red-400">
          {searchError}{' '}
          <button
            type="button"
            onClick={() => doSearch(query, typeFilter)}
            className="underline ml-2"
          >
            Retry
          </button>
        </p>
      )}

      <div className="mt-6">
        {results.length === 0 && query.trim() && !searchError && (
          <p className="text-sm text-zinc-600">No results.</p>
        )}
        {results.map((m) => (
          <div key={m.id} id={`mem-${m.id}`}>
            <ExpandedCard
              memory={m}
              fullContent={openIds.has(m.id) ? fullById[m.id] : undefined}
              onExpand={(id) => {
                setOpenIds((prev) => new Set(prev).add(id))
                loadFull(id)
              }}
              onTimeline={handleTimeline}
              onOpenLinked={handleOpenLinked}
            />
          </div>
        ))}
      </div>

      {timeline && (
        <div className="fixed inset-y-0 right-0 w-full max-w-md border-l border-zinc-800 bg-zinc-950 p-4 shadow-xl overflow-y-auto">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-white">Timeline</h3>
            <button
              type="button"
              className="text-xs text-zinc-500 hover:text-white"
              onClick={() => setTimeline(null)}
            >
              Close
            </button>
          </div>
          {timeline.error && <p className="text-xs text-red-400">{timeline.error}</p>}
          <ul className="space-y-3">
            {(timeline.rows || []).map((r) => (
              <li key={r.id} className="border-b border-zinc-900 pb-2">
                <p className="text-xs text-zinc-500 font-mono">#{r.id?.slice(0, 8)}</p>
                <p className="text-sm text-zinc-300 line-clamp-4">{r.content}</p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
