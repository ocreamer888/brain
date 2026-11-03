/** Human names for memory sources (brain_api.rs `memory_source_as_str`). */
const SOURCE_NAMES: Record<string, string> = {
  claude_code_session: 'Claude Code',
  cursor_history: 'Cursor history',
  claw_code: 'Claw Code',
  perplexity: 'Perplexity',
  obsidian: 'Obsidian',
  obsidian_books: 'Obsidian books',
  reflection: 'Reflection',
}

/** Known sources get their name; a new one reads as words ("new_tool_x" → "New tool x"). */
export function sourceName(source: string): string {
  if (SOURCE_NAMES[source]) return SOURCE_NAMES[source]
  const words = source.replace(/[_-]+/g, ' ').trim()
  return words ? words[0].toUpperCase() + words.slice(1) : 'Unknown'
}
