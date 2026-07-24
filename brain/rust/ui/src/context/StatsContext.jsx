import { createContext, useContext, useEffect, useState } from 'react'
import { apiFetch } from '../lib/apiFetch'

const StatsContext = createContext(null)

export function StatsProvider({ children }) {
  const [stats, setStats] = useState(null)
  const [error, setError] = useState(null)

  async function fetchStats() {
    try {
      const r = await apiFetch('/stats')
      if (!r.ok) throw new Error(`${r.status}`)
      setStats(await r.json())
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }

  useEffect(() => {
    fetchStats()
    const id = setInterval(fetchStats, 10_000)
    return () => clearInterval(id)
  }, [])

  return (
    <StatsContext.Provider value={{ stats, error, refetch: fetchStats }}>
      {children}
    </StatsContext.Provider>
  )
}

export function useStats() {
  return useContext(StatsContext)
}
