import { useEffect, useState } from 'react'

/** The value once it has stopped changing for `ms` (debounce without leaking timers). */
export function useSettled(value, ms) {
  const [settled, setSettled] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setSettled(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return settled
}
