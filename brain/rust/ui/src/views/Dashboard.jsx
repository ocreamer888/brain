import { useEffect } from 'react'
import { CompactCard } from '../components/MemoryCard'
import { useFeed } from '../context/FeedContext'
import { useStats } from '../context/StatsContext'

function StatCard({ label, value }) {
  return (
    <div className="rounded border border-zinc-800 bg-zinc-950 p-4">
      <p className="text-xs uppercase tracking-wide text-zinc-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-white">{value ?? '—'}</p>
    </div>
  )
}

export default function Dashboard() {
  const { stats, error, refetch } = useStats()
  const { feed, status } = useFeed()
  const by = stats?.by_type || {}

  useEffect(() => {
    if (!feed?.length) return
    // Refresh counts when live events arrive (ignore initial seed churn lightly).
    refetch?.()
  }, [feed?.[0]?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="p-4 space-y-6">
      <h2 className="text-lg font-semibold text-white">Dashboard</h2>
      {error && <p className="text-sm text-red-400">Stats error: {error}</p>}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <StatCard label="Total Memories" value={stats?.total_memories} />
        <StatCard label="Sessions" value={stats?.total_sessions} />
        <StatCard label="Facts" value={by.fact ?? 0} />
        <StatCard label="Conversations" value={by.conversation ?? 0} />
        <StatCard label="Solutions" value={by.solution ?? 0} />
        <StatCard label="Patterns" value={by.pattern ?? 0} />
      </div>

      <div>
        <div className="mb-2 flex items-center gap-2">
          <p className="text-xs uppercase tracking-wide text-zinc-500">Live Feed</p>
          {status === 'live' && (
            <span className="text-xs text-emerald-500">live</span>
          )}
          {status === 'connecting' && (
            <span className="text-xs text-zinc-500">connecting…</span>
          )}
          {status === 'reconnecting' && (
            <span className="animate-pulse text-xs text-amber-400">reconnecting…</span>
          )}
          <span className="text-xs text-zinc-600">{feed.length} events</span>
        </div>
        <div className="rounded border border-zinc-800 bg-zinc-950 px-4 max-h-[28rem] overflow-y-auto">
          {feed.length === 0 && (
            <p className="py-4 text-xs text-zinc-600">Waiting for new memories…</p>
          )}
          {feed.map((evt, i) => (
            <CompactCard
              key={`${evt.id}-${evt.timestamp || i}`}
              memory={{
                id: evt.id,
                memory_type: evt.memory_type,
                timestamp: evt.timestamp,
                snippet: evt.content_snippet,
                content_snippet: evt.content_snippet,
              }}
            />
          ))}
        </div>
      </div>
    </div>
  )
}
