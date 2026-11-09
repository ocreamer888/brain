import { useCallback, useEffect, useRef, useState } from 'react'
import { apiKey, clearApiKey, hasStoredApiKey, setApiKey, validateApiKey } from '../api'
import Login from './brand/Login'

const EXPIRED_MESSAGE = 'Session expired. Please re-enter your key.'

/**
 * Sits outside every data provider so nothing fires an authenticated request
 * before a key is confirmed. Shows Login until `validateApiKey` succeeds,
 * then renders `children`. A `brain:unauthorized` event (dispatched by
 * `api()` on a 401, or by the Dock's lock button) re-locks it -- one path
 * for "server rejected us" and "user chose to lock", per the brand book's
 * preference for the smaller surface.
 */
export default function AuthGate({ children }) {
  const [unlocked, setUnlocked] = useState(false)
  const [checking, setChecking] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const unlockedRef = useRef(false)

  useEffect(() => {
    unlockedRef.current = unlocked
  }, [unlocked])

  const revalidate = useCallback(async () => {
    if (!hasStoredApiKey()) {
      setUnlocked(false)
      setChecking(false)
      return
    }
    const result = await validateApiKey(apiKey())
    if (result.ok) {
      setUnlocked(true)
    } else {
      clearApiKey()
      setUnlocked(false)
    }
    setChecking(false)
  }, [])

  useEffect(() => {
    revalidate()
  }, [revalidate])

  useEffect(() => {
    function onUnauthorized() {
      if (unlockedRef.current) setError(EXPIRED_MESSAGE)
      setUnlocked(false)
      setChecking(false)
    }
    window.addEventListener('brain:unauthorized', onUnauthorized)
    return () => window.removeEventListener('brain:unauthorized', onUnauthorized)
  }, [])

  async function handleUnlock(key) {
    setBusy(true)
    setError(null)
    const result = await validateApiKey(key)
    if (result.ok) {
      setApiKey(key)
      setError(null)
      setBusy(false)
      setUnlocked(true)
    } else {
      setError(result.error || 'That key was not accepted.')
      setBusy(false)
    }
  }

  if (checking) return null
  if (!unlocked) return <Login onUnlock={handleUnlock} busy={busy} error={error} />
  return children
}
