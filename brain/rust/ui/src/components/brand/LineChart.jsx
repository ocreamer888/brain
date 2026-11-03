import { useEffect, useRef, useState } from 'react'
import styles from './LineChart.module.css'

const PAD = { top: 12, right: 52, bottom: 26, left: 40 }
const Y_TICKS = [0, 0.25, 0.5, 0.75, 1]
const axisDate = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric' })
const fullDate = new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeStyle: 'short' })

/**
 * Lines over evenly spaced points on a 0–1 axis. `points`: [{ at: Date|null, ...values }],
 * oldest → newest. `series`: [{ key, label, color, dashed }]. A null value is a gap.
 * Hover or arrow keys move a crosshair; the tooltip names every series.
 */
export default function LineChart({ points, series, height = 220, label, format = (v) => v }) {
  const [ref, width] = useWidth()
  const [at, setAt] = useState(null)
  const w = Math.max(width - PAD.left - PAD.right, 1)
  const h = height - PAD.top - PAD.bottom
  const x = (i) => PAD.left + (points.length < 2 ? w / 2 : (i / (points.length - 1)) * w)
  const y = (v) => PAD.top + (1 - v) * h

  function nearest(clientX) {
    const box = ref.current.getBoundingClientRect()
    const rel = (clientX - box.left - PAD.left) / w
    return Math.min(points.length - 1, Math.max(0, Math.round(rel * (points.length - 1))))
  }
  function onKeyDown(e) {
    const last = points.length - 1
    const move = { ArrowLeft: -1, ArrowRight: 1 }[e.key]
    if (move) setAt((i) => Math.min(last, Math.max(0, (i ?? last) + move)))
    else if (e.key === 'Home') setAt(0)
    else if (e.key === 'End') setAt(last)
    else return
    e.preventDefault()
  }

  return (
    <div className={styles.wrap} ref={ref} tabIndex={0} role="group" aria-label={label} onKeyDown={onKeyDown} onBlur={() => setAt(null)}>
      <div className={`t-small ${styles.legend}`}>
        {series.map((s) => (
          <span key={s.key} className={styles.key}>
            <span className={styles.swatch} style={{ '--c': s.color }} data-dashed={!!s.dashed} />
            {s.label}
          </span>
        ))}
      </div>
      <svg width={width} height={height} aria-hidden onPointerMove={(e) => setAt(nearest(e.clientX))} onPointerLeave={() => setAt(null)}>
        <Axes x={x} y={y} w={w} points={points} />
        {series.map((s) => (
          <Series key={s.key} s={s} points={points} x={x} y={y} format={format} />
        ))}
        {at !== null && <Crosshair i={at} x={x} y={y} points={points} series={series} />}
      </svg>
      {at !== null && <Tip point={points[at]} series={series} left={x(at)} flip={x(at) > width / 2} format={format} />}
    </div>
  )
}

function Axes({ x, y, w, points }) {
  const labelled = dateTicks(points.length)
  return (
    <g>
      {Y_TICKS.map((t) => (
        <g key={t}>
          <line x1={PAD.left} x2={PAD.left + w} y1={y(t)} y2={y(t)} className={t === 0 ? styles.base : styles.grid} />
          <text x={PAD.left - 8} y={y(t) + 4} textAnchor="end" className={styles.tick}>{`${t * 100}%`}</text>
        </g>
      ))}
      {labelled.map((i) => (
        <text key={i} x={x(i)} y={y(0) + 18} textAnchor="middle" className={styles.tick}>
          {points[i].at ? axisDate.format(points[i].at) : ''}
        </text>
      ))}
    </g>
  )
}

function Series({ s, points, x, y, format }) {
  let d = ''
  let pen = false
  points.forEach((p, i) => {
    const v = p[s.key]
    if (typeof v !== 'number') return void (pen = false)
    d += `${pen ? 'L' : 'M'}${x(i)},${y(v)}`
    pen = true
  })
  const lastI = points.findLastIndex((p) => typeof p[s.key] === 'number')
  return (
    <g>
      <path d={d} className={styles.line} style={{ stroke: s.color }} strokeDasharray={s.dashed ? '5 4' : undefined} />
      {lastI >= 0 && (
        <text x={x(lastI) + 8} y={y(points[lastI][s.key]) + 4} className={styles.end}>
          {format(points[lastI][s.key])}
        </text>
      )}
    </g>
  )
}

function Crosshair({ i, x, y, points, series }) {
  return (
    <g>
      <line x1={x(i)} x2={x(i)} y1={y(1)} y2={y(0)} className={styles.cross} />
      {series.map((s) =>
        typeof points[i][s.key] === 'number' ? (
          <circle key={s.key} cx={x(i)} cy={y(points[i][s.key])} r="5" className={styles.dot} style={{ fill: s.color }} />
        ) : null,
      )}
    </g>
  )
}

/** Beside the crosshair (flipping past the middle), so it never covers the legend or the line ends. */
function Tip({ point, series, left, flip, format }) {
  return (
    <div className={`glass t-small ${styles.tip}`} style={{ left }} data-flip={flip} role="status">
      <span>{point.at ? fullDate.format(point.at) : point.run_id}</span>
      {series.map((s) => (
        <span key={s.key}>
          {s.label}: <strong>{typeof point[s.key] === 'number' ? format(point[s.key]) : 'not measured'}</strong>
        </span>
      ))}
      <span className={styles.tipMeta}>{point.run_id}</span>
    </div>
  )
}

/** About five evenly spaced date labels, always the first and last point. */
function dateTicks(n) {
  if (n <= 1) return n ? [0] : []
  const step = Math.max(1, Math.round((n - 1) / 4))
  const out = []
  for (let i = 0; i < n - 1; i += step) out.push(i)
  if (n - 1 - out[out.length - 1] < step / 2) out.pop()
  out.push(n - 1)
  return out
}

/** Element width, kept current, so the SVG draws in real pixels (text never stretches). */
function useWidth() {
  const ref = useRef(null)
  const [width, setWidth] = useState(0)
  useEffect(() => {
    const ro = new ResizeObserver(([e]) => setWidth(Math.floor(e.contentRect.width)))
    ro.observe(ref.current)
    return () => ro.disconnect()
  }, [])
  return [ref, width]
}
