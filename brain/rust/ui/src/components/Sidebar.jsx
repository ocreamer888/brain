import { useStats } from '../context/StatsContext'

const NAV = [
  { id: 'dashboard', label: 'Dashboard', icon: '◉' },
  { id: 'search',    label: 'Search',    icon: '⌕' },
  { id: 'curate',    label: 'Curate',    icon: '✦' },
  { id: 'eval',      label: 'Eval',      icon: '▦' },
]

export default function Sidebar({ activeView, onNavigate }) {
  const { stats } = useStats()

  return (
    <aside className="flex flex-col w-48 shrink-0 border-r border-zinc-800 bg-zinc-950 h-full">
      <div className="px-4 py-4 border-b border-zinc-800">
        <p className="text-sm font-semibold text-white">Brain</p>
        {stats && (
          <p className="text-xs text-zinc-500 mt-0.5">
            {stats.total_memories.toLocaleString()} memories
          </p>
        )}
      </div>
      <nav className="flex flex-col gap-1 p-2 flex-1">
        {NAV.map(item => (
          <button
            key={item.id}
            onClick={() => onNavigate(item.id)}
            className={`flex items-center gap-2 px-3 py-2 rounded-md text-sm text-left transition-colors ${
              activeView === item.id
                ? 'bg-zinc-800 text-white'
                : 'text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200'
            }`}
          >
            <span className="text-base leading-none">{item.icon}</span>
            {item.label}
          </button>
        ))}
      </nav>
      {stats?.by_type && (
        <div className="p-4 border-t border-zinc-800">
          {Object.entries(stats.by_type)
            .sort((a, b) => b[1] - a[1])
            .map(([type, count]) => (
              <div key={type} className="flex justify-between text-xs mb-0.5">
                <span className="text-zinc-600">{type}</span>
                <span className="text-zinc-500">{count.toLocaleString()}</span>
              </div>
            ))
          }
        </div>
      )}
    </aside>
  )
}
