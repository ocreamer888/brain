import { useCallback, useEffect, useMemo, useState } from 'react'
import { getLinked, getObservations } from '../api'
import LinkedFloater from '../components/LinkedFloater'
import LinkedGraph from '../components/LinkedGraph'
import {
  buildBipartiteGraph,
  egoSubgraph,
  filterActiveIds,
  memoriesForFilter,
  oneHopIds,
  type GraphNode,
  type LinkedApiResponse,
} from '../lib/linkedGraphModel'

export default function Linked() {
  const [data, setData] = useState<LinkedApiResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [entityFilter, setEntityFilter] = useState('all')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [graphMode, setGraphMode] = useState<'full' | 'ego'>('full')
  const [egoFocusId, setEgoFocusId] = useState<string | null>(null)
  const [floaterOpen, setFloaterOpen] = useState(false)
  const [listPin, setListPin] = useState(false)
  const [floaterMode, setFloaterMode] = useState<'list' | 'detail'>('detail')
  const [fullContent, setFullContent] = useState<string | null>(null)
  const [entitiesOpen, setEntitiesOpen] = useState(true)

  const load = useCallback(async () => {
    setError(null)
    try {
      const d = (await getLinked()) as LinkedApiResponse
      setData(d)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const fullGraph = useMemo(
    () => (data ? buildBipartiteGraph(data) : { nodes: [], links: [] }),
    [data],
  )

  const viewGraph = useMemo(() => {
    if (graphMode === 'ego' && egoFocusId) {
      return egoSubgraph(fullGraph.nodes, fullGraph.links, egoFocusId)
    }
    return fullGraph
  }, [fullGraph, graphMode, egoFocusId])

  const selected: GraphNode | null = useMemo(
    () => fullGraph.nodes.find((n) => n.id === selectedId) ?? null,
    [fullGraph.nodes, selectedId],
  )

  const highlightIds = useMemo(() => {
    if (!selectedId) return null
    if (!viewGraph.nodes.some((n) => n.id === selectedId)) return null
    return oneHopIds(viewGraph.nodes, viewGraph.links, selectedId)
  }, [viewGraph, selectedId])

  const activeIds = useMemo(
    () => filterActiveIds(fullGraph.nodes, fullGraph.links, entityFilter),
    [fullGraph, entityFilter],
  )

  const listMemories = useMemo(
    () => memoriesForFilter(fullGraph.nodes, entityFilter),
    [fullGraph.nodes, entityFilter],
  )

  useEffect(() => {
    let cancelled = false
    async function hydrate() {
      setFullContent(null)
      if (!selected || selected.kind !== 'memory') return
      try {
        const obs = await getObservations([selected.id])
        const row = obs?.results?.[0]
        if (!cancelled && row?.content) setFullContent(String(row.content))
      } catch {
        /* keep snippet */
      }
    }
    void hydrate()
    return () => {
      cancelled = true
    }
  }, [selected])

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        if (listPin && floaterMode === 'list') {
          setListPin(false)
          setFloaterOpen(false)
          return
        }
        setSelectedId(null)
        setFloaterOpen(false)
        setListPin(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [listPin, floaterMode])

  function handleSelect(id: string | null) {
    if (id == null) {
      if (listPin) {
        setSelectedId(null)
        setFloaterMode('list')
        setFloaterOpen(true)
        return
      }
      setSelectedId(null)
      setFloaterOpen(false)
      return
    }
    // List can pick a memory outside the ego subgraph — exit ego so the graph shows it.
    if (graphMode === 'ego' && !viewGraph.nodes.some((n) => n.id === id)) {
      backToFull()
    }
    setSelectedId(id)
    setListPin(false)
    setFloaterMode('detail')
    setFloaterOpen(true)
  }

  function enterEgo(id: string) {
    setEgoFocusId(id)
    setGraphMode('ego')
    setSelectedId(id)
    setFloaterMode('detail')
    setFloaterOpen(true)
    setListPin(false)
  }

  function backToFull() {
    setGraphMode('full')
    setEgoFocusId(null)
  }

  const entityCount = data?.entities?.length ?? 0
  const pillClass = (active: boolean) =>
    `rounded px-2 py-1 font-mono text-xs ${
      active ? 'bg-zinc-200 text-black' : 'bg-zinc-900 text-zinc-400 hover:text-zinc-200'
    }`

  return (
    <div className="relative flex h-full min-h-0 flex-col">
      <div className="shrink-0 border-b border-zinc-900">
        <div className="flex flex-wrap items-center gap-2 px-4 py-3">
          <div className="mr-2">
            <h2 className="text-sm font-semibold text-white">Linked</h2>
            <p className="text-[11px] text-zinc-500">
              {data?.memories?.length ?? '—'} memories · {entityCount || '—'} entities
              {graphMode === 'ego' ? ' · ego' : ''}
            </p>
          </div>

          {!entitiesOpen && entityFilter !== 'all' && (
            <button
              type="button"
              onClick={() => setEntityFilter('all')}
              className={pillClass(true)}
              title="Clear entity filter"
            >
              {entityFilter} ×
            </button>
          )}

          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              onClick={() => setEntitiesOpen((v) => !v)}
              className="rounded border border-zinc-700 px-2.5 py-1 text-xs text-zinc-400 hover:text-white"
              aria-pressed={entitiesOpen}
              aria-expanded={entitiesOpen}
            >
              {entitiesOpen ? 'Hide entities' : `Entities (${entityCount})`}
            </button>
            <button
              type="button"
              onClick={() => {
                setListPin(true)
                setFloaterMode('list')
                setFloaterOpen(true)
              }}
              className="rounded border border-zinc-700 px-2.5 py-1 text-xs text-zinc-400 hover:text-white"
            >
              List
            </button>
            {graphMode === 'ego' ? (
              <button
                type="button"
                onClick={backToFull}
                className="rounded border border-zinc-700 px-2.5 py-1 text-xs text-zinc-400 hover:text-white"
              >
                Back to full
              </button>
            ) : (
              <button
                type="button"
                disabled={!selectedId}
                onClick={() => selectedId && enterEgo(selectedId)}
                className="rounded border border-zinc-700 px-2.5 py-1 text-xs text-zinc-400 hover:text-white disabled:opacity-40"
              >
                Focus
              </button>
            )}
            <button
              type="button"
              onClick={() => void load()}
              className="rounded border border-zinc-700 px-2.5 py-1 text-xs text-zinc-400 hover:text-white"
            >
              Refresh
            </button>
          </div>
        </div>

        {entitiesOpen && (
          <div className="flex max-h-36 flex-wrap gap-2 overflow-y-auto px-4 pb-3">
            <button
              type="button"
              onClick={() => setEntityFilter('all')}
              className={pillClass(entityFilter === 'all')}
            >
              all ({data?.memories?.length ?? 0})
            </button>
            {(data?.entities ?? []).map((e) => (
              <button
                key={e.id}
                type="button"
                onClick={() => setEntityFilter(e.name)}
                className={pillClass(entityFilter === e.name)}
              >
                {e.name} ({e.memory_count})
              </button>
            ))}
          </div>
        )}
      </div>

      {error && <p className="px-4 py-2 text-sm text-red-400">{error}</p>}

      <div className="relative min-h-0 flex-1">
        {!data && !error && (
          <p className="p-8 text-sm text-zinc-600">Loading linked graph…</p>
        )}
        {data && viewGraph.nodes.length === 0 && (
          <p className="p-8 text-sm text-zinc-600">No linked memories.</p>
        )}
        {data && viewGraph.nodes.length > 0 && (
          <LinkedGraph
            nodes={viewGraph.nodes}
            links={viewGraph.links}
            selectedId={selectedId}
            highlightIds={highlightIds}
            activeIds={activeIds}
            onSelect={handleSelect}
            onFocusRequest={enterEgo}
          />
        )}

        {floaterOpen && (
          <LinkedFloater
            mode={floaterMode}
            listPin={listPin}
            entityFilter={entityFilter}
            listMemories={listMemories}
            selected={selected}
            fullContent={fullContent}
            onClose={() => {
              setFloaterOpen(false)
              setListPin(false)
            }}
            onSelectMemory={(id) => handleSelect(id)}
            onFocus={() => selectedId && enterEgo(selectedId)}
          />
        )}
      </div>
    </div>
  )
}
