// Placeholder rows for the brand sample only. Not real memories.
export const SAMPLE_MEMORIES = [
  { id: 'a1f3c9e2b7', memory_type: 'decision', project: 'brain', timestamp: '2026-10-18', snippet: 'Follow the system light/dark setting instead of shipping dark-only. Roles are declared once with light-dark() so components never branch on theme.' },
  { id: 'b72e0d4411', memory_type: 'fact', project: 'brain', timestamp: '2026-10-18', snippet: 'Secondary text neutral-400 on raised neutral-800 measures 4.4:1, under the 4.5:1 minimum. Secondary moved to neutral-300.' },
  { id: 'c09ab51e3d', memory_type: 'solution', project: 'brain', timestamp: '2026-10-17', snippet: 'Vite emits hashed asset names; a merge conflict on static/index.html is resolved by rebuilding the UI, not by picking a side.' },
  { id: 'd4410fe8a2', memory_type: 'pattern', project: 'tendrium', timestamp: '2026-10-16', snippet: 'Placeholder pattern: the same retrieval miss shows up after each chunking change until the baseline is refreshed.' },
  { id: 'e88c2a7710', memory_type: 'error_lesson', project: 'brain', timestamp: '2026-10-15', snippet: 'Placeholder lesson: a build step that empties its output folder will delete any runtime file stored there.' },
  { id: 'f1029bd3c4', memory_type: 'knowledge', project: 'design', timestamp: '2026-10-14', snippet: 'HIG: avoid Ultralight, Thin, and Light weights, especially when text is small. Prefer Regular, Medium, Semibold, Bold.' },
  { id: '0a7d3e9f21', memory_type: 'conversation', project: 'brain', timestamp: '2026-10-14', snippet: 'Talked through whether the glass dock should sit on the left edge or float at the bottom like the reference.' },
  { id: '1be45c0d98', memory_type: 'project_context', project: 'brain', timestamp: '2026-10-12', snippet: 'Viewer rebuild order: shell, Dashboard, Search, Linked, Curate, Eval, Instances. One view at a time.' },
  { id: '2c6f81aa03', memory_type: 'episode', project: 'brain', timestamp: '2026-10-12', snippet: 'Session transcript, 42 turns. Source tape for the facts above; not a durable claim on its own.' },
  { id: '3d90e4b7c5', memory_type: 'decision', project: 'tendrium', timestamp: '2026-10-10', snippet: 'Brain and Tendrium share craft, not identity. Tendrium keeps gold and the node; Brain takes the lamp and the trace.' },
]

// Snapshot of the live API on 2026-10-18 (GET /stats). Real values, frozen for the sample.
export const SAMPLE_STATS = {
  active_instance: { id: 'main', name: 'Main' },
  total_memories: 22904,
  total_sessions: 2319,
  save_count_this_session: 90,
  feedback_events_total: 58,
  by_type: {
    fact: 15078,
    solution: 4257,
    conversation: 2271,
    project_context: 443,
    knowledge: 291,
    decision: 235,
    pattern: 205,
    error_lesson: 121,
    episode: 3,
  },
}

// Last 14 scored runs from static/eval_dashboard.json (quick_p1_avg), oldest → newest.
export const SAMPLE_RUNS = [
  ['2026-07-16-1927', 0.9992], ['2026-07-16-2300', 1], ['2026-07-17-0056', 1], ['2026-07-17-0545', 1],
  ['2026-07-17-1811', 1], ['2026-07-17-1911', 1], ['2026-07-19-0108', 0.997], ['2026-07-20-2340', 1],
  ['2026-07-21-0703', 0.9992], ['2026-07-21-2334', 1], ['2026-07-24-1237', 1], ['2026-07-24-1348', 1],
  ['2026-08-14-2257', 0.9967], ['2026-10-18-2058', 1],
].map(([run_id, p1]) => ({ run_id, p1, pass: true }))
