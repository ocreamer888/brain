import type { GraphNode, MemoryGraphNode } from '../lib/linkedGraphModel'

const TYPE_BADGE: Record<string, string> = {
  fact: 'bg-amber-900/50 text-amber-300',
  conversation: 'bg-blue-900/50 text-blue-300',
  solution: 'bg-green-900/50 text-green-300',
  pattern: 'bg-purple-900/50 text-purple-300',
  project_context: 'bg-pink-900/50 text-pink-300',
  error_lesson: 'bg-red-900/50 text-red-300',
  decision: 'bg-cyan-900/50 text-cyan-300',
  episode: 'bg-zinc-800 text-zinc-300',
}

function TypeBadge({ type }: { type: string }) {
  const cls = TYPE_BADGE[type] ?? 'bg-zinc-800 text-zinc-400'
  return (
    <span className={`inline-block rounded px-2 py-0.5 font-mono text-xs ${cls}`}>{type}</span>
  )
}

export type LinkedFloaterProps = {
  mode: 'list' | 'detail'
  listPin: boolean
  entityFilter: string
  listMemories: MemoryGraphNode[]
  selected: GraphNode | null
  fullContent: string | null
  onClose: () => void
  onSelectMemory: (id: string) => void
  onFocus: () => void
}

export default function LinkedFloater({
  mode,
  listPin,
  entityFilter,
  listMemories,
  selected,
  fullContent,
  onClose,
  onSelectMemory,
  onFocus,
}: LinkedFloaterProps) {
  return (
    <div className="pointer-events-auto absolute bottom-4 right-4 z-20 flex max-h-[60vh] w-[320px] flex-col overflow-hidden rounded-lg border border-zinc-700 bg-zinc-950/95 shadow-xl backdrop-blur">
      <div className="flex items-center justify-between border-b border-zinc-800 px-3 py-2">
        <p className="text-xs font-medium text-zinc-300">
          {mode === 'list'
            ? `List · ${entityFilter === 'all' ? 'all' : entityFilter}`
            : selected?.kind === 'entity'
              ? 'Entity'
              : 'Memory'}
          {listPin && mode === 'list' ? ' · pinned' : ''}
        </p>
        <button
          type="button"
          onClick={onClose}
          className="text-xs text-zinc-500 hover:text-white"
          aria-label="Close"
        >
          ✕
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {mode === 'list' && (
          <ul className="space-y-2">
            {listMemories.length === 0 && (
              <li className="text-xs text-zinc-600">No memories for this filter.</li>
            )}
            {listMemories.map((m) => (
              <li key={m.id}>
                <button
                  type="button"
                  onClick={() => onSelectMemory(m.id)}
                  className="w-full rounded border border-zinc-800 bg-zinc-900/70 px-2 py-2 text-left hover:border-zinc-600"
                >
                  <div className="mb-1 flex flex-wrap gap-1">
                    <TypeBadge type={m.memory_type} />
                  </div>
                  <p className="line-clamp-2 text-xs text-zinc-400">{m.snippet}</p>
                </button>
              </li>
            ))}
          </ul>
        )}

        {mode === 'detail' && selected?.kind === 'memory' && (
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <TypeBadge type={selected.memory_type} />
              {selected.project && (
                <span className="text-xs text-zinc-500">{selected.project}</span>
              )}
              <span className="font-mono text-xs text-zinc-600">
                #{selected.id.slice(0, 8)}
              </span>
            </div>
            <p className="whitespace-pre-wrap text-sm leading-snug text-zinc-300">
              {fullContent || selected.snippet}
            </p>
            <p className="text-xs text-zinc-600">
              {selected.entityIds.length} entities · {selected.neighbor_ids.length} neighbor
              memories
            </p>
            <button
              type="button"
              onClick={onFocus}
              className="rounded border border-zinc-700 px-2 py-1 text-xs text-zinc-300 hover:text-white"
            >
              Focus
            </button>
          </div>
        )}

        {mode === 'detail' && selected?.kind === 'entity' && (
          <div className="space-y-2">
            <p className="text-sm font-medium text-zinc-200">{selected.name}</p>
            <p className="text-xs text-zinc-500">{selected.memory_count} linked memories</p>
            <button
              type="button"
              onClick={onFocus}
              className="rounded border border-zinc-700 px-2 py-1 text-xs text-zinc-300 hover:text-white"
            >
              Focus
            </button>
          </div>
        )}

        {mode === 'detail' && !selected && (
          <p className="text-xs text-zinc-600">Nothing selected.</p>
        )}
      </div>
    </div>
  )
}
