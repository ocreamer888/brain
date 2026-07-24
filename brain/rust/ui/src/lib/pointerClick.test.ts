import { describe, expect, it } from 'vitest'
import { isClickGesture, POINTER_CLICK_SLOP_PX } from './pointerClick'

describe('isClickGesture', () => {
  it('treats sub-threshold movement as a click', () => {
    expect(
      isClickGesture(
        { clientX: 100, clientY: 200 },
        { clientX: 100 + POINTER_CLICK_SLOP_PX, clientY: 200 },
      ),
    ).toBe(true)
    expect(
      isClickGesture({ clientX: 10, clientY: 10 }, { clientX: 12, clientY: 13 }),
    ).toBe(true)
  })

  it('treats movement beyond slop as a pan/drag, not a click', () => {
    expect(
      isClickGesture(
        { clientX: 100, clientY: 200 },
        { clientX: 100 + POINTER_CLICK_SLOP_PX + 1, clientY: 200 },
      ),
    ).toBe(false)
    expect(
      isClickGesture({ clientX: 0, clientY: 0 }, { clientX: 20, clientY: 0 }),
    ).toBe(false)
  })

  it('returns false when pointerdown was never recorded', () => {
    expect(isClickGesture(null, { clientX: 0, clientY: 0 })).toBe(false)
  })
})
