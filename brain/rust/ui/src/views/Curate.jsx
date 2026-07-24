import { useEffect, useRef, useState } from 'react'
import { ActionableCard } from '../components/MemoryCard'
import { apiFetch } from '../lib/apiFetch'

const FACT_TYPES = ['all', 'named_entity', 'other']

function SkeletonCard() {
  return (
    <div className="py-3 border-b border-zinc-800 animate-pulse">
      <div className="h-3 w-24 bg-zinc-800 rounded mb-2" />
      <div className="h-3 w-full bg-zinc-800 rounded mb-1" />
      <div className="h-3 w-2/3 bg-zinc-800 rounded" />
    </div>
  )
}

export default function Curate() {
  const [facts, setFacts] = useState([])
  const [query, setQuery] = useState('')
  const [factTypeFilter, setFactTypeFilter] = useState('all')
  const [actedMap, setActedMap] = useState({})
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(null)
  const initialLoad = useRef(true)

  async function loadFacts(q, ftf) {
    if (initialLoad.current) setLoading(true)
    setLoadError(null)
    try {
      const effectiveQuery = q.trim() || 'fact'
      const body = { query: effectiveQuery, n: 50, memory_type: 'fact' }
      const r = await apiFetch('/v1/search_index', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!r.ok) throw new Error(`Load failed: ${r.status}`)
      const data = await r.json()
      let results = data.results ?? []

      // Client-side fact_type filter
      if (ftf === 'named_entity') {
        results = results.filter(r => r.fact_type === 'named_entity')
      } else if (ftf === 'other') {
        results = results.filter(r => r.fact_type !== 'named_entity')
      }

      setFacts(results)
    } catch (e) {
      setLoadError(e.message)
    } finally {
      setLoading(false)
      initialLoad.current = false
    }
  }

  useEffect(() => { loadFacts('', 'all') }, [])

  function debounce(fn, ms) {
    let t
    return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms) }
  }
  const debouncedLoad = useRef(debounce((q, ftf) => loadFacts(q, ftf), 300)).current

  function handleQuery(e) {
    const q = e.target.value
    setQuery(q)
    debouncedLoad(q, factTypeFilter)
  }

  function handleTypeFilter(ftf) {
    setFactTypeFilter(ftf)
    loadFacts(query, ftf)
  }

  async function handlePromote(id) {
    const r = await apiFetch(`/memories/${id}`, {
      method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ salience: 1.0 }),
    })
    if (!r.ok) throw new Error(`Promote failed: ${r.status}`)
    setActedMap(prev => ({ ...prev, [id]: 'promoted' }))
  }

  async function handleReject(id) {
    const r = await apiFetch('/feedback', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ event_type: 'rejected', memory_id: id, source: 'mcp' }),
    })
    if (!r.ok) throw new Error(`Reject failed: ${r.status}`)
    setActedMap(prev => ({ ...prev, [id]: 'rejected' }))
  }

  return (
    <div className="p-6 max-w-3xl">
      <h2 className="text-lg font-semibold text-white mb-4">Curate</h2>

      <input
        type="search"
        value={query}
        onChange={handleQuery}
        placeholder="Filter facts…"
        autoComplete="off"
        className="w-full bg-zinc-900 border border-zinc-700 rounded-full px-4 py-2 text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-zinc-500 mb-3"
      />

      {/* Fact type filter chips */}
      <div className="flex gap-2 mb-4">
        {FACT_TYPES.map(ft => (
          <button
            key={ft}
            onClick={() => handleTypeFilter(ft)}
            className={`px-3 py-0.5 rounded-full text-xs border transition-colors ${
              factTypeFilter === ft
                ? 'bg-zinc-700 border-zinc-500 text-white'
                : 'border-zinc-800 text-zinc-500 hover:border-zinc-600 hover:text-zinc-300'
            }`}
          >
            {ft}
          </button>
        ))}
      </div>

      {loadError && (
        <div className="text-xs text-red-400 bg-red-900/20 rounded p-2 mb-3 flex items-center justify-between">
          {loadError}
          <button onClick={() => loadFacts(query, factTypeFilter)} className="underline ml-2">Retry</button>
        </div>
      )}

      <p className="text-xs text-zinc-600 mb-3">{facts.length} facts</p>

      <div>
        {loading && (
          <><SkeletonCard /><SkeletonCard /><SkeletonCard /></>
        )}
        {!loading && facts.length === 0 && (
          <p className="text-sm text-zinc-600 py-4">No facts found.</p>
        )}
        {facts.map(fact => (
          <ActionableCard
            key={fact.id}
            memory={fact}
            acted={actedMap[fact.id] ?? null}
            onPromote={handlePromote}
            onReject={handleReject}
          />
        ))}
      </div>
    </div>
  )
}
