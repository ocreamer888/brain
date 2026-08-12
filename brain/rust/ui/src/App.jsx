import { useState } from 'react'
import { EvalProvider } from './context/EvalContext'
import { FeedProvider } from './context/FeedContext'
import { StatsProvider, useStats } from './context/StatsContext'
import Dashboard from './views/Dashboard'
import Search from './views/Search'
import Linked from './views/Linked'
import Curate from './views/Curate'
import Eval from './views/Eval'
import Instances from './views/Instances'

const NAV = [
  { id: 'dashboard', label: 'Dashboard', icon: '◉' },
  { id: 'search', label: 'Search', icon: '⌕' },
  { id: 'linked', label: 'Linked', icon: '⚭' },
  { id: 'curate', label: 'Curate', icon: '✦' },
  { id: 'eval', label: 'Eval', icon: '▦' },
  { id: 'instances', label: 'Instances', icon: '⧉' },
]

function Shell() {
  const [view, setView] = useState('dashboard')
  const [focusId, setFocusId] = useState(null)
  const { stats } = useStats()
  const byType = stats?.by_type || {}

  return (
    <div className="flex h-full min-h-0 bg-black text-white">
      <aside className="flex w-56 shrink-0 flex-col border-r border-zinc-900 bg-zinc-950">
        <div className="border-b border-zinc-900 px-4 py-4">
          <p className="text-sm font-semibold tracking-wide">
            {stats?.active_instance?.name || 'Brain'}
          </p>
          <p className="text-xs text-zinc-500">
            {stats?.total_memories ?? '—'} memories
          </p>
        </div>
        <nav className="flex-1 space-y-1 p-2">
          {NAV.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setView(item.id)}
              className={`flex w-full items-center gap-2 rounded px-3 py-2 text-left text-sm ${
                view === item.id
                  ? 'bg-zinc-800 text-white'
                  : 'text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200'
              }`}
            >
              <span className="w-4 text-center">{item.icon}</span>
              {item.label}
            </button>
          ))}
        </nav>
        <div className="border-t border-zinc-900 p-3 text-[11px] font-mono text-zinc-600 space-y-0.5">
          {Object.entries(byType)
            .sort((a, b) => b[1] - a[1])
            .map(([k, v]) => (
              <div key={k} className="flex justify-between gap-2">
                <span>{k}</span>
                <span>{v}</span>
              </div>
            ))}
        </div>
      </aside>
      <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        {view === 'dashboard' && (
          <div className="min-h-0 flex-1 overflow-y-auto">
            <Dashboard />
          </div>
        )}
        {view === 'search' && (
          <div className="min-h-0 flex-1 overflow-y-auto">
            <Search focusId={focusId} onFocused={() => setFocusId(null)} />
          </div>
        )}
        {view === 'linked' && (
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
            <Linked />
          </div>
        )}
        {view === 'curate' && (
          <div className="min-h-0 flex-1 overflow-y-auto">
            <Curate />
          </div>
        )}
        {view === 'eval' && (
          <div className="min-h-0 flex-1 overflow-y-auto">
            <Eval activeView={view} />
          </div>
        )}
        {view === 'instances' && (
          <div className="min-h-0 flex-1 overflow-y-auto">
            <Instances />
          </div>
        )}
      </main>
    </div>
  )
}

export default function App() {
  return (
    <StatsProvider>
      <EvalProvider>
        <FeedProvider>
          <Shell />
        </FeedProvider>
      </EvalProvider>
    </StatsProvider>
  )
}
