import { useRef, useState } from 'react'
import { ExpandedCard } from '../components/MemoryCard'
import TimelineDrawer from '../components/TimelineDrawer'
import { apiFetch } from '../lib/apiFetch'

const TYPES = ['all', 'fact', 'conversation', 'solution', 'pattern', 'project_context']

function debounce(fn, ms) {
  let t
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms) }
}

function SkeletonCard() {
  return (
    <div className="py-3 border-b border-zinc-800 animate-pulse">
      <div className="h-3 w-24 bg-zinc-800 rounded mb-2" />
      <div className="h-3 w-full bg-zinc-800 rounded mb-1" />
      <div className="h-3 w-3/4 bg-zinc-800 rounded" />
    </div>
  )
}

export default function Search() {
  const [query, setQuery] = useState('')
  const [typeFilter, setTypeFilter] = useState('all')
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(false)
  const [searchError, setSearchError] = useState(null)
  const [timelineId, setTimelineId] = useState(null)
  const [timelineResults, setTimelineResults] = useState(null)
  const [timelineLoading, setTimelineLoading] = useState(false)
  const [timelineError, setTimelineError] = useState(null)
  const observationsCache = useRef(new Map())

  const doSearch = useRef(debounce(async (q, tf) => {
    if (!q.trim()) { setResults([]); setLoading(false); return }
    setLoading(true)
    setSearchError(null)
    try {
      const body = { query: q, n: 20 }
      if (tf !== 'all') body.memory_type = tf
      const r = await apiFetch('/v1/search_index', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!r.ok) throw new Error(`Search failed: ${r.status}`)
      const data = await r.json()
      setResults(data.results ?? [])
    } catch (e) {
      setSearchError(e.message)
    } finally {
      setLoading(false)
    }
  }, 200)).current

  function handleInput(e) {
    const q = e.target.value
    setQuery(q)
    setLoading(true)
    doSearch(q, typeFilter)
  }

  function handleTypeFilter(type) {
    setTypeFilter(type)
    doSearch(query, type)
  }

  async function handleExpand(id) {
    if (observationsCache.current.has(id)) return
    try {
      const r = await apiFetch('/v1/get_observations', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ ids: [id] }),
      })
      const data = await r.json()
      const mem = (data.results ?? data.memories ?? [])[0]
      observationsCache.current.set(id, mem?.content ?? '(no content)')
    } catch {
      observationsCache.current.set(id, 'Failed to load content.')
    }
  }

  async function handleTimeline(id) {
    setTimelineId(id)
    setTimelineResults(null)
    setTimelineLoading(true)
    setTimelineError(null)
    try {
      const r = await apiFetch('/v1/timeline', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ anchor_id: id, before: 5, after: 5 }),
      })
      if (!r.ok) throw new Error(`Timeline failed: ${r.status}`)
      const data = await r.json()
      setTimelineResults(data.results ?? [])
    } catch (e) {
      setTimelineError(e.message)
    } finally {
      setTimelineLoading(false)
    }
  }

  return (
    <div className="p-6 max-w-3xl">
      <h2 className="text-lg font-semibold text-white mb-4">Search</h2>

      <input
        type="search"
        value={query}
        onChange={handleInput}
        placeholder="Search memories…"
        autoComplete="off"
        className="w-full bg-zinc-900 border border-zinc-700 rounded-full px-4 py-2 text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-zinc-500 mb-3"
      />

      {/* Type filter chips */}
      <div className="flex gap-2 flex-wrap mb-4">
        {TYPES.map(type => (
          <button
            key={type}
            onClick={() => handleTypeFilter(type)}
            className={`px-3 py-0.5 rounded-full text-xs border transition-colors ${
              typeFilter === type
                ? 'bg-zinc-700 border-zinc-500 text-white'
                : 'border-zinc-800 text-zinc-500 hover:border-zinc-600 hover:text-zinc-300'
            }`}
          >
            {type}
          </button>
        ))}
      </div>

      {searchError && (
        <div className="text-xs text-red-400 bg-red-900/20 rounded p-2 mb-3 flex items-center justify-between">
          {searchError}
          <button onClick={() => doSearch(query, typeFilter)} className="underline ml-2">Retry</button>
        </div>
      )}

      <div>
        {loading && results.length === 0 && (
          <>
            <SkeletonCard /><SkeletonCard /><SkeletonCard />
          </>
        )}
        {!loading && query && results.length === 0 && (
          <p className="text-sm text-zinc-600 py-4">No results for "{query}"</p>
        )}
        {results.map(row => (
          <ExpandedCard
            key={row.id}
            memory={row}
            onExpand={handleExpand}
            fullContent={observationsCache.current.get(row.id) ?? null}
            onTimeline={handleTimeline}
          />
        ))}
      </div>

      <TimelineDrawer
        memoryId={timelineId}
        results={timelineResults}
        loading={timelineLoading}
        error={timelineError}
        onClose={() => setTimelineId(null)}
      />
    </div>
  )
}
