export function apiKey() {
  if (typeof window !== 'undefined' && window.__BRAIN_API_KEY__) {
    return window.__BRAIN_API_KEY__
  }
  return 'local-dev-key'
}

/** EventSource cannot set headers — key goes on the query string. */
export function streamUrl() {
  const origin =
    typeof window !== 'undefined' && window.location?.origin
      ? window.location.origin
      : ''
  return `${origin}/v1/stream?key=${encodeURIComponent(apiKey())}`
}

export async function api(path, options = {}) {
  const headers = {
    ...(options.headers || {}),
    'x-api-key': apiKey(),
  }
  if (options.body && !headers['content-type']) {
    headers['content-type'] = 'application/json'
  }
  const res = await fetch(path, { ...options, headers })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`${res.status}${text ? `: ${text}` : ''}`)
  }
  if (res.status === 204) return null
  return res.json()
}

export function getStats() {
  return api('/stats')
}

export function searchIndex(query, n = 20, memory_type = null) {
  const body = { query, n }
  if (memory_type) body.memory_type = memory_type
  return api('/v1/search_index', { method: 'POST', body: JSON.stringify(body) })
}

export function getObservations(ids) {
  return api('/v1/get_observations', {
    method: 'POST',
    body: JSON.stringify({ ids }),
  })
}

export function getNeighbors(memoryId) {
  return api(`/neighbors?memory_id=${encodeURIComponent(memoryId)}`)
}

export function getEntities(memoryId) {
  return api(`/entities?memory_id=${encodeURIComponent(memoryId)}`)
}

export function getTimeline(anchorId, before = 3, after = 3) {
  return api('/v1/timeline', {
    method: 'POST',
    body: JSON.stringify({ anchor_id: anchorId, before, after }),
  })
}

export function getLinked() {
  return api('/linked')
}

export function listMemories(limit = 30) {
  return api(`/list?limit=${limit}`)
}
