import { useCallback, useEffect, useState } from 'react'

/**
 * Run an async loader when `key` changes; ignore results that arrive after
 * the key has moved on, so a slow old request never overwrites a newer one.
 * `key === null` means "nothing to load".
 *
 * `loading` is derived (the settled result belongs to another key), not set
 * in an effect, so there is no first frame that claims "loaded, empty".
 * While loading, `data` still holds the previous result so lists don't blink.
 */
export function useLoad(load, key) {
  const [result, setResult] = useState({ key: null, data: null, error: null })
  const [nonce, setNonce] = useState(0)
  const token = key === null ? null : `${key}#${nonce}`

  useEffect(() => {
    if (token === null) return
    let stale = false
    load()
      .then((data) => !stale && setResult({ key: token, data, error: null }))
      .catch((e) => !stale && setResult({ key: token, data: null, error: e.message || String(e) }))
    return () => {
      stale = true
    }
  }, [token]) // eslint-disable-line react-hooks/exhaustive-deps

  const retry = useCallback(() => setNonce((n) => n + 1), [])
  if (token === null) return { data: null, error: null, loading: false, retry }
  const loading = result.key !== token
  return { data: result.data, error: loading ? null : result.error, loading, retry }
}
