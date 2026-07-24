import { useEffect, useState } from 'react'
import { getEntities, getNeighbors, getObservations } from '../api'
import { apiFetch } from '../lib/apiFetch'

const TYPE_COLORS = {
  fact: 'bg-amber-900/50 text-amber-300',
  conversation: 'bg-blue-900/50 text-blue-300',
  solution: 'bg-green-900/50 text-green-300',
  pattern: 'bg-purple-900/50 text-purple-300',
  project_context: 'bg-pink-900/50 text-pink-300',
  error_lesson: 'bg-red-900/50 text-red-300',
  decision: 'bg-cyan-900/50 text-cyan-300',
  episode: 'bg-zinc-800 text-zinc-300',
}

function TypeBadge({ type }) {
  const cls = TYPE_COLORS[type] ?? 'bg-zinc-800 text-zinc-400'
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-mono ${cls}`}>
      {type}
    </span>
  )
}

function CardMeta({ memory }) {
  const ts = memory.timestamp || memory.metadata?.timestamp || ''
  return (
    <div className="flex items-center gap-2 flex-wrap mb-1">
      <TypeBadge type={memory.memory_type || memory.metadata?.type} />
      {(memory.project || memory.metadata?.project) && (
        <span className="text-xs text-zinc-500">
          {memory.project || memory.metadata?.project}
        </span>
      )}
      {ts && <span className="text-xs text-zinc-600">{String(ts).slice(0, 10)}</span>}
      {memory.id && (
        <span className="text-xs text-zinc-700 font-mono">#{memory.id.slice(0, 8)}</span>
      )}
    </div>
  )
}

export function CompactCard({ memory }) {
  return (
    <div className="py-2 border-b border-zinc-900">
      <CardMeta memory={memory} />
      <p className="text-sm text-zinc-300 leading-snug line-clamp-2">
        {memory.snippet ?? memory.content_snippet ?? memory.content}
      </p>
    </div>
  )
}

function LinkedMemories({ memoryId, onOpen }) {
  const [entities, setEntities] = useState(null)
  const [neighbors, setNeighbors] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setError(null)
      setEntities(null)
      setNeighbors(null)
      try {
        const [ent, neigh] = await Promise.all([
          getEntities(memoryId),
          getNeighbors(memoryId),
        ])
        if (cancelled) return
        setEntities(ent.entities || [])
        const ids = neigh.ids || []
        if (ids.length === 0) {
          setNeighbors([])
          return
        }
        const obs = await getObservations(ids)
        if (cancelled) return
        const rows = (obs.results || []).map((m) => ({
          id: m.id,
          memory_type: m.metadata?.type || m.memory_type,
          project: m.metadata?.project || m.project || '',
          timestamp: m.timestamp || m.metadata?.timestamp,
          snippet: (m.content || '').slice(0, 140),
          content: m.content,
        }))
        setNeighbors(rows)
      } catch (e) {
        if (!cancelled) setError(e.message)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [memoryId])

  return (
    <div className="mt-3 rounded border border-zinc-800 bg-zinc-950/80 p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-zinc-400">
          Linked memories
        </h4>
        {neighbors && (
          <span className="text-xs text-zinc-600">{neighbors.length} via entities</span>
        )}
      </div>

      {entities === null && !error && (
        <p className="text-xs text-zinc-600">Loading links…</p>
      )}
      {error && <p className="text-xs text-red-400">Links failed: {error}</p>}

      {entities && entities.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-1.5">
          {entities.map((e) => (
            <span
              key={e.id}
              className="rounded-full border border-zinc-700 px-2 py-0.5 text-[11px] text-zinc-300"
              title={e.id}
            >
              {e.name}
            </span>
          ))}
        </div>
      )}

      {entities && entities.length === 0 && neighbors && neighbors.length === 0 && (
        <p className="text-xs text-zinc-600">No entity links for this memory.</p>
      )}

      {neighbors && neighbors.length > 0 && (
        <ul className="space-y-2">
          {neighbors.map((n) => (
            <li key={n.id}>
              <button
                type="button"
                onClick={() => onOpen?.(n.id)}
                className="w-full rounded border border-zinc-800 bg-zinc-900/60 px-2.5 py-2 text-left hover:border-zinc-600"
              >
                <CardMeta memory={n} />
                <p className="text-xs text-zinc-400 leading-snug line-clamp-2">{n.snippet}</p>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function ExpandedCard({ memory, onExpand, fullContent, onTimeline, onOpenLinked }) {
  const [open, setOpen] = useState(false)

  function toggle() {
    if (!open) onExpand(memory.id)
    setOpen((o) => !o)
  }

  return (
    <div className="py-3 border-b border-zinc-800">
      <CardMeta memory={memory} />
      <p className="text-sm text-zinc-300 mb-2 leading-snug">{memory.snippet}</p>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={toggle}
          className="text-xs text-blue-400 hover:text-blue-300 underline"
        >
          {open ? 'Collapse' : 'Expand'}
        </button>
        <button
          type="button"
          onClick={() => onTimeline(memory.id)}
          className="text-xs text-zinc-500 hover:text-zinc-300"
        >
          Timeline ↗
        </button>
      </div>
      {open && (
        <div className="mt-2 space-y-2">
          <div className="p-3 bg-zinc-900 rounded border border-zinc-800 text-sm text-zinc-300 font-mono whitespace-pre-wrap break-words">
            {fullContent ?? <span className="text-zinc-600">Loading…</span>}
          </div>
          <LinkedMemories memoryId={memory.id} onOpen={onOpenLinked} />
        </div>
      )}
    </div>
  )
}

export function ActionableCard({ memory, acted, onPromote, onReject }) {
  const [episodeOpen, setEpisodeOpen] = useState(false)
  const [episodeContent, setEpisodeContent] = useState(null)
  const [promoteErr, setPromoteErr] = useState(null)
  const [rejectErr, setRejectErr] = useState(null)

  async function handleEpisode() {
    if (episodeOpen) {
      setEpisodeOpen(false)
      return
    }
    setEpisodeOpen(true)
    if (episodeContent) return
    try {
      const r = await apiFetch(`/get-episode?id=${memory.parent_id ?? memory.id}`)
      const d = await r.json()
      setEpisodeContent(d.content ?? d.error ?? '(empty)')
    } catch {
      setEpisodeContent('Failed to load episode.')
    }
  }

  const isActed = !!acted
  const cardCls = isActed ? 'opacity-40' : ''

  return (
    <div className={`py-3 border-b border-zinc-800 ${cardCls}`}>
      <CardMeta memory={memory} />
      <p className="text-sm text-zinc-300 mb-2 leading-snug">{memory.snippet}</p>
      <div className="flex items-center gap-2 flex-wrap">
        <button
          disabled={isActed}
          onClick={() => {
            setPromoteErr(null)
            onPromote(memory.id).catch(() => setPromoteErr('Promote failed'))
          }}
          className={`px-2 py-0.5 rounded text-xs ${isActed && acted === 'promoted' ? 'bg-green-900/30 text-green-400' : 'bg-green-900/20 text-green-400 hover:bg-green-900/50'} disabled:cursor-not-allowed`}
        >
          {acted === 'promoted' ? 'Promoted ✓' : 'Promote'}
        </button>
        <button
          disabled={isActed}
          onClick={() => {
            setRejectErr(null)
            onReject(memory.id).catch(() => setRejectErr('Reject failed'))
          }}
          className={`px-2 py-0.5 rounded text-xs ${isActed && acted === 'rejected' ? 'bg-red-900/30 text-red-400' : 'bg-red-900/20 text-red-400 hover:bg-red-900/50'} disabled:cursor-not-allowed`}
        >
          {acted === 'rejected' ? 'Rejected ✗' : 'Reject'}
        </button>
        {memory.parent_id && (
          <button
            onClick={handleEpisode}
            className="text-xs text-zinc-500 hover:text-zinc-300 underline"
          >
            {episodeOpen ? 'Hide episode' : 'Show episode'}
          </button>
        )}
        {promoteErr && <span className="text-xs text-red-400">{promoteErr}</span>}
        {rejectErr && <span className="text-xs text-red-400">{rejectErr}</span>}
      </div>
      {episodeOpen && (
        <div className="mt-2 p-3 bg-zinc-900 rounded border border-zinc-800 text-sm text-zinc-300 font-mono whitespace-pre-wrap break-words">
          {episodeContent ?? <span className="text-zinc-600">Loading…</span>}
        </div>
      )}
    </div>
  )
}
