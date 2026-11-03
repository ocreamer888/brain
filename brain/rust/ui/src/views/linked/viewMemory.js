// Where you were in each atlas (camera, colour mode, selection), kept for the
// browser session so leaving Linked and coming back doesn't reset the view.
// Keyed by atlas (e.g. "memories:main", "dataset:atlas"); brains never share one.
const saved = new Map()

export const recall = (key) => (key ? saved.get(key) : undefined)

export function remember(key, patch) {
  if (key) saved.set(key, { ...saved.get(key), ...patch })
}
