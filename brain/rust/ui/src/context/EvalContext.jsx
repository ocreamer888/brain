import { createContext, useContext, useCallback, useEffect, useState } from 'react'
import { apiFetch } from '../lib/apiFetch'

const EvalContext = createContext(null)

export function EvalProvider({ children }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  const refresh = useCallback(async () => {
    try {
      const r = await apiFetch('/eval_dashboard.json')
      if (r.status === 404) { setData({ runs: [] }); return }
      if (!r.ok) throw new Error(`${r.status}`)
      setData(await r.json())
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  return (
    <EvalContext.Provider value={{ data, error, refresh }}>
      {children}
    </EvalContext.Provider>
  )
}

export function useEval() {
  return useContext(EvalContext)
}
