import { lazy, Suspense, useState } from 'react'
import AuthGate from './components/AuthGate'
import Dock, { VIEWS } from './components/brand/Dock'
import { LiveDot, SearchPill } from './components/brand/primitives'
import { EvalProvider } from './context/EvalContext'
import { FeedProvider, useFeed } from './context/FeedContext'
import { StatsProvider, useStats } from './context/StatsContext'
import Dashboard from './views/Dashboard'
import Search from './views/Search'
import Curate from './views/Curate'
import Eval from './views/Eval'
import Instances from './views/Instances'

// The atlas pulls in three.js (~150 KB gzipped); load it only when Linked opens.
const Linked = lazy(() => import('./views/linked/LinkedAtlas'))
import styles from './App.module.css'

const fmt = new Intl.NumberFormat('en-US')

// Views still on the old Tailwind styling. Each leaves this set when rebuilt.
// Views that own their own scrolling (panes, canvas) instead of scrolling under the header.
const FILL = new Set(['search', 'linked'])

function Shell() {
  const [view, setView] = useState('dashboard')
  const [focusId, setFocusId] = useState(null)
  const [searchSeed, setSearchSeed] = useState('')
  const [entitySeed, setEntitySeed] = useState('all')
  const label = VIEWS.find((v) => v.id === view)?.label

  function search(query) {
    setSearchSeed(query)
    setView('search')
  }

  function openMemory(id) {
    setFocusId(id)
    setView('search')
  }

  function openEntity(name) {
    setEntitySeed(name)
    setView('linked')
  }

  function navigate(next) {
    // Arriving at Linked from the dock shows everything, not a stale filter.
    if (next === 'linked') setEntitySeed('all')
    setView(next)
  }

  const body = (
    <ViewBody
      view={view}
      onNavigate={navigate}
      onOpenMemory={openMemory}
      onOpenEntity={openEntity}
      entitySeed={entitySeed}
      focusId={focusId}
      setFocusId={setFocusId}
      searchSeed={searchSeed}
    />
  )
  return (
    <div className={styles.app}>
      <div className={styles.rail}>
        <div className={styles.wordmarkContainer}>
          <p className={styles.wordmark}>brain</p>
        </div>
        <div className={styles.dockContainer}>
          <Dock active={view} onSelect={navigate} />
        </div>
      </div>
      <main className={styles.panel}>
        <div className={FILL.has(view) ? styles.fill : styles.scroll}>
          <Header title={label} showSearch={view !== 'search'} onSearch={search} />
          {body}
        </div>
      </main>
    </div>
  )
}

function Header({ title, showSearch, onSearch }) {
  const { stats } = useStats()
  const { status } = useFeed()
  const [query, setQuery] = useState('')
  const instance = stats?.active_instance?.name || 'Brain'
  return (
    <header className={styles.header}>
      <div className={styles.heading}>
        <h1 className={`${styles.headline} ${styles.title}`}>{title}</h1>
        <p className={`t-small ${styles.secondary}`}>
          {stats ? `${instance} brain · ${fmt.format(stats.total_memories ?? 0)} memories` : 'Loading…'}
        </p>
      </div>
      <div className={styles.tools}>
        {showSearch && (
          <SearchPill
            value={query}
            onChange={setQuery}
            onSubmit={(q) => {
              setQuery('')
              onSearch(q)
            }}
          />
        )}
        <span className={`glass ${styles.pill}`}>
          <LiveDot state={status} />
        </span>
        <span className={`glass ${styles.pill}`} title="Active instance">
          <span className={styles.monogram} aria-hidden>
            {instance[0]}
          </span>
          <span className="t-small">{instance}</span>
        </span>
      </div>
    </header>
  )
}

function ViewBody({ view, onNavigate, onOpenMemory, onOpenEntity, entitySeed, focusId, setFocusId, searchSeed }) {
  switch (view) {
    case 'dashboard':
      return <Dashboard onNavigate={onNavigate} onOpenMemory={onOpenMemory} onOpenEntity={onOpenEntity} />
    case 'search':
      return <Search focusId={focusId} onFocused={() => setFocusId(null)} initialQuery={searchSeed} />
    case 'linked':
      return (
        <Suspense fallback={<p className="t-body" style={{ padding: 'var(--space-7)' }}>Loading the atlas…</p>}>
          <Linked key={entitySeed} initialEntity={entitySeed} />
        </Suspense>
      )
    case 'curate':
      return <Curate onOpenMemory={onOpenMemory} />
    case 'eval':
      return <Eval activeView={view} />
    case 'instances':
      return <Instances />
    default:
      return null
  }
}

export default function App() {
  return (
    <AuthGate>
      <StatsProvider>
        <EvalProvider>
          <FeedProvider>
            <Shell />
          </FeedProvider>
        </EvalProvider>
      </StatsProvider>
    </AuthGate>
  )
}
