/**
 * memory_type → signal, icon, and display word (brand book §5.6).
 * Types share a signal hue when they ask the same thing of the reader;
 * the icon and word keep them apart.
 */
export const MEMORY_SIGNALS = {
  fact: { signal: 'rely', icon: 'fact', label: 'fact' },
  knowledge: { signal: 'rely', icon: 'knowledge', label: 'knowledge' },
  decision: { signal: 'use', icon: 'decision', label: 'decision' },
  solution: { signal: 'use', icon: 'solution', label: 'solution' },
  pattern: { signal: 'notice', icon: 'pattern', label: 'pattern' },
  error_lesson: { signal: 'lesson', icon: 'lesson', label: 'lesson' },
  conversation: { signal: 'spoken', icon: 'conversation', label: 'conversation' },
  project_context: { signal: 'frame', icon: 'project', label: 'project' },
  episode: { signal: 'raw', icon: 'episode', label: 'episode' },
}

export const MEMORY_TYPES = Object.keys(MEMORY_SIGNALS)

export function signalFor(type) {
  return MEMORY_SIGNALS[type] ?? { signal: 'info', icon: 'fact', label: type || 'unknown' }
}
