import { useEffect } from 'react'
import ReactDOM from 'react-dom'

function TimelineEntry({ memory }) {
  return (
    <div className="py-2 border-b border-zinc-800">
      <div className="flex items-center gap-2 mb-1">
        <span className="text-xs text-zinc-600 font-mono">#{memory.id?.slice(0, 8)}</span>
        <span className="text-xs text-zinc-500">{memory.metadata?.memory_type}</span>
        <span className="text-xs text-zinc-700">
          {memory.timestamp?.slice(0, 10)}
        </span>
      </div>
      <p className="text-sm text-zinc-300 leading-snug">
        {memory.content?.slice(0, 200)}{(memory.content?.length ?? 0) > 200 ? '…' : ''}
      </p>
    </div>
  )
}

export default function TimelineDrawer({ memoryId, results, loading, error, onClose }) {
  useEffect(() => {
    function onKey(e) { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  if (!memoryId) return null

  const drawer = (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* backdrop */}
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      {/* panel */}
      <div className="relative w-96 bg-zinc-950 border-l border-zinc-800 h-full overflow-y-auto p-4 flex flex-col">
        <div className="flex items-center justify-between mb-4">
          <p className="text-sm font-semibold text-white">Timeline</p>
          <button onClick={onClose} className="text-zinc-500 hover:text-white text-lg leading-none">×</button>
        </div>
        <p className="text-xs text-zinc-600 mb-3 font-mono">anchor: #{memoryId.slice(0, 8)}</p>
        {loading && <p className="text-xs text-zinc-600">Loading…</p>}
        {error && (
          <div className="text-xs text-red-400 bg-red-900/20 rounded p-2 mb-3">
            {error}
          </div>
        )}
        {results && results.map(m => (
          <TimelineEntry key={m.id} memory={m} />
        ))}
      </div>
    </div>
  )

  return ReactDOM.createPortal(drawer, document.body)
}
