export function apiKey() {
  if (typeof window !== 'undefined' && window.__BRAIN_API_KEY__) {
    return window.__BRAIN_API_KEY__
  }
  return 'local-dev-key'
}

/**
 * EventSource cannot set headers, so the real API key never goes on this
 * URL (security audit 2026-11-05, finding #6). Fetches a short-lived,
 * single-use token via the normal header-authenticated POST
 * /v1/stream/token first, then builds a URL carrying that token instead.
 * Call this again for every (re)connect attempt — each token is good for
 * one connection only.
 */
export async function streamUrl() {
  const origin =
    typeof window !== 'undefined' && window.location?.origin
      ? window.location.origin
      : ''
  const { token } = await api('/v1/stream/token', { method: 'POST' })
  return `${origin}/v1/stream?token=${encodeURIComponent(token)}`
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

/** The most-linked entities with memory counts (small; the full catalog is /linked). */
export function getTopEntities(limit = 12) {
  return api(`/entities/top?limit=${limit}`)
}

export function getTimeline(anchorId, before = 3, after = 3) {
  return api('/v1/timeline', {
    method: 'POST',
    body: JSON.stringify({ anchor_id: anchorId, before, after }),
  })
}

/** Change a memory's stored fields (today the API accepts `salience` only). */
export function patchMemory(id, body) {
  return api(`/memories/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(body) })
}

/** Record a feedback event (accepted / rejected / edited …) about a memory. */
export function sendFeedback(body) {
  return api('/feedback', { method: 'POST', body: JSON.stringify(body) })
}

/** The source episode a derived memory (e.g. a fact) was extracted from. */
export function getEpisode(id) {
  return api(`/get-episode?id=${encodeURIComponent(id)}`)
}

export function getLinked() {
  return api('/linked')
}

export function listMemories(limit = 30, { memoryType } = {}) {
  const type = memoryType ? `&memory_type=${encodeURIComponent(memoryType)}` : ''
  return api(`/list?limit=${limit}${type}`)
}

export function listInstances(includeArchived = false) {
  const q = includeArchived ? '?include_archived=1' : ''
  return api(`/v1/instances${q}`)
}

export function createInstance({ name, description = '', tags = [] }) {
  return api('/v1/instances', {
    method: 'POST',
    body: JSON.stringify({ name, description, tags }),
  })
}

export function patchInstance(id, body) {
  return api(`/v1/instances/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export function switchInstance(id) {
  return api(`/v1/instances/${encodeURIComponent(id)}/switch`, { method: 'POST' })
}

export function archiveInstance(id) {
  return api(`/v1/instances/${encodeURIComponent(id)}/archive`, { method: 'POST' })
}

export function unarchiveInstance(id) {
  return api(`/v1/instances/${encodeURIComponent(id)}/unarchive`, { method: 'POST' })
}

export function deleteInstance(id) {
  return api(`/v1/instances/${encodeURIComponent(id)}`, { method: 'DELETE' })
}
