/** Screen-space slop (px) below which pointerup is treated as a click, not pan/drag. */
export const POINTER_CLICK_SLOP_PX = 5

type Point = { clientX: number; clientY: number }

/**
 * True when pointerup is a real click (movement ≤ slop), not a pan/drag.
 * Missing pointerdown → not a click (avoids spurious select/clear).
 */
export function isClickGesture(
  down: Point | null,
  up: Point,
  slopPx: number = POINTER_CLICK_SLOP_PX,
): boolean {
  if (down == null) return false
  const dx = up.clientX - down.clientX
  const dy = up.clientY - down.clientY
  return dx * dx + dy * dy <= slopPx * slopPx
}
