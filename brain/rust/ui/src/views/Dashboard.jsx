import { useEffect, useState } from 'react'
import { useStats } from '../context/StatsContext'
import { useEval } from '../context/EvalContext'
import { CompactCard } from '../components/MemoryCard'
import { sseUrl } from '../lib/apiFetch'

const TYPE_ORDER = ['fact', 'conversation', 'solution', 'pattern', 'project_context']
const TYPE_LABELS = {
  fact: 'Facts',
  conversation: 'Conversations',
  solution: 'Solutions',
  pattern: 'Patterns',
  project_context: 'Projects',
}

function StatCard({ label, value, sub }) {
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4">
      <p className="text-xs text-zinc-500 mb-1">{label}</p>
      <p className="text-2xl font-semibold text-white tabular-nums">
        {value != null ? value.toLocaleString() : '—'}
      </p>
      {sub && <p className="text-xs text-zinc-600 mt-1">{sub}</p>}
    </div>
  )
}

function EvalSummary({ data, error }) {
  if (error) return <p className="text-xs text-red-400">Eval load failed: {error}</p>
  if (!data) return <p className="text-xs text-zinc-600">Loading eval…</p>
  const runs = data.runs ?? []
  if (!runs.length) return <p className="text-xs text-zinc-600">No eval runs yet.</p>
  const latest = runs[0]
  const pct = v => v != null ? `${(v * 100).toFixed(1)}%` : '—'
  return (
    <div className="flex items-center gap-3">
      <span className={`text-xs font-semibold px-2 py-0.5 rounded ${latest.pass ? 'bg-green-900/50 text-green-300' : 'bg-red-900/50 text-red-300'}`}>
        {latest.pass ? 'PASS' : 'FAIL'}
      </span>
      <span className="text-xs text-zinc-400">
        non-fact P@1: <strong className="text-white">{pct(latest.non_fact_p1)}</strong>
      </span>
      <span className="text-xs text-zinc-400">
        MCP P@1: <strong className="text-white">{pct(latest.mcp_p1)}</strong>
      </span>
    </div>
  )
}

function useSSEFeed() {
  const [feed, setFeed] = useState([])
  const [reconnecting, setReconnecting] = useState(false)

  useEffect(() => {
    const es = new EventSource(sseUrl('/v1/stream'))
    es.onmessage = e => {
      try {
        const evt = JSON.parse(e.data)
        setFeed(prev => [evt, ...prev].slice(0, 200))
        setReconnecting(false)
      } catch { /* ignore parse errors */ }
    }
    es.onerror = () => setReconnecting(true)
    return () => es.close()
  }, [])

  return { feed, reconnecting }
}

export default function Dashboard() {
  const { stats, error: statsError } = useStats()
  const { data: evalData, error: evalError } = useEval()
  const { feed, reconnecting } = useSSEFeed()

  return (
    <div className="p-6 max-w-4xl">
      <h2 className="text-lg font-semibold text-white mb-4">Dashboard</h2>

      {/* Stat cards */}
      <div className="grid grid-cols-2 gap-3 mb-6">
        <StatCard
          label="Total Memories"
          value={stats?.total_memories}
          sub={statsError ? `Error: ${statsError}` : null}
        />
        <StatCard
          label="Sessions"
          value={stats?.total_sessions}
        />
        {TYPE_ORDER.map(type => (
          <StatCard
            key={type}
            label={TYPE_LABELS[type]}
            value={stats?.by_type?.[type]}
          />
        ))}
      </div>

      {/* Eval summary */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 mb-6">
        <p className="text-xs text-zinc-500 mb-2">Latest Eval Run</p>
        <EvalSummary data={evalData} error={evalError} />
      </div>

      {/* Live feed */}
      <div>
        <div className="flex items-center gap-2 mb-2">
          <p className="text-xs text-zinc-500">Live Feed</p>
          {reconnecting && (
            <span className="text-xs text-amber-400 animate-pulse">reconnecting…</span>
          )}
        </div>
        <div className="space-y-0">
          {feed.length === 0 && (
            <p className="text-xs text-zinc-700 py-4">Waiting for new memories…</p>
          )}
          {feed.map((evt, i) => (
            <CompactCard
              key={`${evt.id}-${i}`}
              memory={{
                id: evt.id,
                memory_type: evt.memory_type,
                timestamp: evt.timestamp,
                content_snippet: evt.content_snippet,
              }}
            />
          ))}
        </div>
      </div>
    </div>
  )
}
