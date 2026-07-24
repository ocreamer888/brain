// Production: key injected by Rust server into window.__BRAIN_API_KEY__.
// Dev (Vite): falls back to VITE_BRAIN_API_KEY from .env.local.
function apiKey() {
  return (typeof window !== 'undefined' && window.__BRAIN_API_KEY__)
    || import.meta.env.VITE_BRAIN_API_KEY
    || 'local-dev-key'
}

export function apiFetch(url, opts = {}) {
  const headers = { ...opts.headers }
  const key = apiKey()
  if (key) headers['x-api-key'] = key
  return fetch(url, { ...opts, headers })
}

// Returns a URL with ?key= appended for use with EventSource (can't send headers).
export function sseUrl(path) {
  const key = apiKey()
  return key ? `${path}?key=${encodeURIComponent(key)}` : path
}
