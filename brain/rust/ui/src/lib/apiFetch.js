// Shares api.js's apiKey() (checks the stored login key before anything else)
// so StatsContext/EvalContext stay in sync with AuthGate instead of running a
// second, independent auth path that never sees a key the user just entered.
import { apiKey } from '../api'

export function apiFetch(url, opts = {}) {
  const headers = { ...opts.headers, 'x-api-key': apiKey() }
  return fetch(url, { ...opts, headers }).then((res) => {
    if (res.status === 401 && typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('brain:unauthorized'))
    }
    return res
  })
}
