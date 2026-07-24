import { useState } from 'react'
import { apiFetch } from '../lib/apiFetch'

const TYPE_COLORS = {
  fact: 'bg-amber-900/50 text-amber-300',
  conversation: 'bg-blue-900/50 text-blue-300',
  solution: 'bg-green-900/50 text-green-300',
  pattern: 'bg-purple-900/50 text-purple-300',
  project_context: 'bg-pink-900/50 text-pink-300',
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
  return (
    <div className="flex items-center gap-2 flex-wrap mb-1">
      <TypeBadge type={memory.memory_type} />
      {memory.project && (
        <span className="text-xs text-zinc-500">{memory.project}</span>
      )}
      {memory.timestamp && (
        <span className="text-xs text-zinc-600">{memory.timestamp.slice(0, 10)}</span>
      )}
      {memory.id && (
        <span className="text-xs text-zinc-700 font-mono">#{memory.id.slice(0, 8)}</span>
      )}
    </div>
  )
}

// compact: Dashboard feed — type badge, timestamp, snippet only
export function CompactCard({ memory }) {
  return (
    <div className="py-2 border-b border-zinc-900">
      <CardMeta memory={memory} />
      <p className="text-sm text-zinc-300 leading-snug line-clamp-2">{memory.snippet ?? memory.content_snippet}</p>
    </div>
  )
}

// expanded: Search results — inline expansion + Timeline button
export function ExpandedCard({ memory, onExpand, fullContent, onTimeline }) {
  const [open, setOpen] = useState(false)

  function toggle() {
    if (!open) onExpand(memory.id)
    setOpen(o => !o)
  }

  return (
    <div className="py-3 border-b border-zinc-800">
      <CardMeta memory={memory} />
      <p className="text-sm text-zinc-300 mb-2 leading-snug">{memory.snippet}</p>
      <div className="flex gap-2">
        <button
          onClick={toggle}
          className="text-xs text-blue-400 hover:text-blue-300 underline"
        >
          {open ? 'Collapse' : 'Expand'}
        </button>
        <button
          onClick={() => onTimeline(memory.id)}
          className="text-xs text-zinc-500 hover:text-zinc-300"
        >
          Timeline ↗
        </button>
      </div>
      {open && (
        <div className="mt-2 p-3 bg-zinc-900 rounded border border-zinc-800 text-sm text-zinc-300 font-mono whitespace-pre-wrap break-words">
          {fullContent ?? <span className="text-zinc-600">Loading…</span>}
        </div>
      )}
    </div>
  )
}

// actionable: Curate — promote/reject buttons + episode expand
export function ActionableCard({ memory, acted, onPromote, onReject }) {
  const [episodeOpen, setEpisodeOpen] = useState(false)
  const [episodeContent, setEpisodeContent] = useState(null)
  const [promoteErr, setPromoteErr] = useState(null)
  const [rejectErr, setRejectErr] = useState(null)

  async function handleEpisode() {
    if (episodeOpen) { setEpisodeOpen(false); return }
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
          onClick={() => { setPromoteErr(null); onPromote(memory.id).catch(() => setPromoteErr('Promote failed')) }}
          className={`px-2 py-0.5 rounded text-xs ${isActed && acted === 'promoted' ? 'bg-green-900/30 text-green-400' : 'bg-green-900/20 text-green-400 hover:bg-green-900/50'} disabled:cursor-not-allowed`}
        >
          {acted === 'promoted' ? 'Promoted ✓' : 'Promote'}
        </button>
        <button
          disabled={isActed}
          onClick={() => { setRejectErr(null); onReject(memory.id).catch(() => setRejectErr('Reject failed')) }}
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
