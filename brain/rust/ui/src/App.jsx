import { useState } from 'react'
import { StatsProvider } from './context/StatsContext'
import { EvalProvider } from './context/EvalContext'
import Sidebar from './components/Sidebar'
import Dashboard from './views/Dashboard'
import Search from './views/Search'
import Curate from './views/Curate'
import Eval from './views/Eval'

function BrainApp() {
  const [activeView, setActiveView] = useState('dashboard')
  const [visited, setVisited] = useState(new Set(['dashboard']))

  function navigate(viewId) {
    setActiveView(viewId)
    setVisited(prev => new Set([...prev, viewId]))
  }

  return (
    <div className="flex h-full">
      <Sidebar activeView={activeView} onNavigate={navigate} />
      <main className="flex-1 overflow-auto bg-black">
        {visited.has('dashboard') && (
          <div className={activeView !== 'dashboard' ? 'hidden' : ''}>
            <Dashboard />
          </div>
        )}
        {visited.has('search') && (
          <div className={activeView !== 'search' ? 'hidden' : ''}>
            <Search />
          </div>
        )}
        {visited.has('curate') && (
          <div className={activeView !== 'curate' ? 'hidden' : ''}>
            <Curate />
          </div>
        )}
        {visited.has('eval') && (
          <div className={activeView !== 'eval' ? 'hidden' : ''}>
            <Eval activeView={activeView} />
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
        <BrainApp />
      </EvalProvider>
    </StatsProvider>
  )
}
