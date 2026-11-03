/**
 * Brain icon set (brand book §7): 24×24 grid, 1.5px stroke, round caps.
 * Inactive = outline; `filled` swaps in the solid variant where one exists.
 * A few strokes end in a 3px point of light (search, linked). Not all.
 */
const dot = (cx, cy, r = 1.5) => <circle cx={cx} cy={cy} r={r} fill="currentColor" stroke="none" />

const ICONS = {
  // Navigation: the view marks from §8.3
  dashboard: (f) => (
    <>
      <circle cx="12" cy="12" r="7.5" />
      {f ? dot(12, 12, 4) : dot(12, 12, 2.5)}
    </>
  ),
  search: () => (
    <>
      <circle cx="10.5" cy="10.5" r="6" />
      <path d="M15 15l3.2 3.2" />
      {dot(19.5, 19.5)}
    </>
  ),
  linked: (f) => (
    <>
      <path d="M8.2 15.4l7.6-6.8" />
      <circle cx="6.2" cy="17.2" r="2.5" fill={f ? 'currentColor' : 'none'} />
      <circle cx="17.8" cy="6.8" r="2.5" fill={f ? 'currentColor' : 'none'} />
    </>
  ),
  curate: (f) => (
    <>
      <circle cx="12" cy="12" r="7.5" fill={f ? 'currentColor' : 'none'} fillOpacity="0.22" />
      <path d="M8.8 12.2l2.2 2.2 4.2-4.4" />
    </>
  ),
  eval: () => (
    <>
      <circle cx="12" cy="12" r="7.5" strokeDasharray="0.1 3.82" strokeWidth="2" />
      {dot(12, 12, 2)}
    </>
  ),
  instances: (f) => (
    <>
      <rect x="3.5" y="6" width="7" height="12" rx="2.5" fill={f ? 'currentColor' : 'none'} />
      <rect x="13.5" y="6" width="7" height="12" rx="2.5" fill={f ? 'currentColor' : 'none'} />
    </>
  ),

  // Memory types (§5.6)
  fact: () => dot(12, 12, 3.5),
  knowledge: () => (
    <>
      <path d="M12 7c-2.4-1.6-5-1.9-7.5-1v12c2.5-.9 5.1-.6 7.5 1 2.4-1.6 5-1.9 7.5-1V6c-2.5-.9-5.1-.6-7.5 1z" />
      <path d="M12 7v12" />
    </>
  ),
  decision: () => <path d="M5 12.5l4.5 4.5L19 7.5" />,
  solution: () => (
    <>
      <path d="M12.6 11.4L5 19" />
      <path d="M16.9 4.7A4 4 0 1 0 19.3 7.1L16.6 9 15 7.4z" />
    </>
  ),
  pattern: () => (
    <>
      <path d="M16.5 4.5l3 3-3 3" />
      <path d="M19.5 7.5H9a4.5 4.5 0 0 0-4.5 4.5" />
      <path d="M7.5 19.5l-3-3 3-3" />
      <path d="M4.5 16.5H15a4.5 4.5 0 0 0 4.5-4.5" />
    </>
  ),
  lesson: () => (
    <>
      <path d="M5.5 20.5v-16" />
      <path d="M5.5 4.5h12l-2.5 4 2.5 4h-12" />
    </>
  ),
  conversation: () => <path d="M4.5 7h15M4.5 12h11M4.5 17h7" />,
  project: () => (
    <path d="M3.5 7.5a2 2 0 0 1 2-2h3.6l2 2h7.4a2 2 0 0 1 2 2v7.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z" />
  ),
  episode: () => (
    <>
      <circle cx="12" cy="12" r="8" />
      <circle cx="12" cy="8" r="1.6" />
      <circle cx="16" cy="12" r="1.6" />
      <circle cx="12" cy="16" r="1.6" />
      <circle cx="8" cy="12" r="1.6" />
    </>
  ),

  inbox: () => (
    <>
      <path d="M4.5 13.5l2-7.5h11l2 7.5v5h-15z" />
      <path d="M4.5 13.5h4.25l1.25 2h4l1.25-2h4.25" />
    </>
  ),
  bars: () => <path d="M6 19.5v-6M10 19.5v-11M14 19.5v-8M18 19.5V5" />,
  layers: () => (
    <>
      <path d="M12 4.5l7.5 3.75L12 12 4.5 8.25z" />
      <path d="M4.5 12L12 15.75 19.5 12" />
      <path d="M4.5 15.75L12 19.5l7.5-3.75" />
    </>
  ),

  // Actions
  arrow: () => <path d="M7.5 16.5l9-9M9 7.5h7.5V15" />,
  back: () => <path d="M14.5 6l-6 6 6 6" />,
  close: () => <path d="M6.5 6.5l11 11M17.5 6.5l-11 11" />,
  add: () => <path d="M12 5.5v13M5.5 12h13" />,
  filter: () => <path d="M4.5 7h15M7.5 12h9M10.5 17h3" />,
  copy: () => (
    <>
      <rect x="8.5" y="8.5" width="11" height="11" rx="2.5" />
      <path d="M15.5 5.5a2 2 0 0 0-2-1.5h-7a2.5 2.5 0 0 0-2.5 2.5v7a2 2 0 0 0 1.5 2" />
    </>
  ),
  more: () => (
    <>
      {dot(6, 12)}
      {dot(12, 12)}
      {dot(18, 12)}
    </>
  ),
}

export const ICON_NAMES = Object.keys(ICONS)

export default function Icon({ name, size = 20, filled = false, className = '', title }) {
  const draw = ICONS[name]
  if (!draw) return null
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden={title ? undefined : true}
      role={title ? 'img' : undefined}
    >
      {title && <title>{title}</title>}
      {draw(filled)}
    </svg>
  )
}
