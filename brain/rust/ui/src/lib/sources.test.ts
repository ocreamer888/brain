import { describe, expect, it } from 'vitest'
import { sourceName } from './sources'

describe('sourceName', () => {
  it('names every source the API knows', () => {
    expect(sourceName('claude_code_session')).toBe('Claude Code')
    expect(sourceName('obsidian_books')).toBe('Obsidian books')
    expect(sourceName('cursor_history')).toBe('Cursor history')
  })
  it('turns an unknown id into words instead of showing snake_case', () => {
    expect(sourceName('new_tool_x')).toBe('New tool x')
    expect(sourceName('')).toBe('Unknown')
  })
})
