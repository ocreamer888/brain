import { useEffect, useRef } from 'react'
import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  type Simulation,
  type SimulationNodeDatum,
} from 'd3-force'
import { drag } from 'd3-drag'
import { select } from 'd3-selection'
import { zoom, zoomIdentity } from 'd3-zoom'
import type { GraphLink, GraphNode } from '../lib/linkedGraphModel'
import {
  DEFAULT_MEMORY_FILL,
  ENTITY_FILL,
  ENTITY_STROKE,
  MEMORY_TYPE_FILL,
} from '../lib/memoryTypeColors'
import { isClickGesture } from '../lib/pointerClick'

type SimNode = GraphNode & SimulationNodeDatum & { x: number; y: number }
type SimLink = { source: SimNode | string; target: SimNode | string }

export type LinkedGraphProps = {
  nodes: GraphNode[]
  links: GraphLink[]
  selectedId: string | null
  /** Selection 1-hop set; `null` means no selection highlight (show filter dims only). */
  highlightIds: Set<string> | null
  /** Entity-filter active set; nodes outside are dimmed. */
  activeIds: Set<string>
  onSelect: (id: string | null) => void
  onFocusRequest: (id: string) => void
}

function nodeRadius(n: GraphNode): number {
  return n.kind === 'entity' ? 10 : 7
}

function fillRoundRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number,
) {
  if (typeof ctx.roundRect === 'function') {
    ctx.beginPath()
    ctx.roundRect(x, y, w, h, r)
    return
  }
  ctx.beginPath()
  ctx.rect(x, y, w, h)
}

export default function LinkedGraph({
  nodes,
  links,
  selectedId,
  highlightIds,
  activeIds,
  onSelect,
  onFocusRequest,
}: LinkedGraphProps) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const simRef = useRef<Simulation<SimNode, SimLink> | null>(null)
  const nodesRef = useRef<SimNode[]>([])
  const linksRef = useRef<SimLink[]>([])
  const transformRef = useRef(zoomIdentity)
  const sizeRef = useRef({ width: 800, height: 600 })
  const drawRef = useRef<() => void>(() => {})
  const propsRef = useRef({ selectedId, highlightIds, activeIds, onSelect, onFocusRequest })
  propsRef.current = { selectedId, highlightIds, activeIds, onSelect, onFocusRequest }

  useEffect(() => {
    const wrap = wrapRef.current
    const canvasEl = canvasRef.current
    if (!wrap || !canvasEl) return
    const canvas = canvasEl

    const width = wrap.clientWidth || 800
    const height = wrap.clientHeight || 600
    sizeRef.current = { width, height }
    canvas.width = width * devicePixelRatio
    canvas.height = height * devicePixelRatio
    canvas.style.width = `${width}px`
    canvas.style.height = `${height}px`

    const simNodes: SimNode[] = nodes.map((n) => {
      const prev = nodesRef.current.find((p) => p.id === n.id)
      return {
        ...n,
        x: prev?.x ?? width / 2 + (Math.random() - 0.5) * 80,
        y: prev?.y ?? height / 2 + (Math.random() - 0.5) * 80,
      }
    })
    const byId = new Map(simNodes.map((n) => [n.id, n]))
    const simLinks: SimLink[] = links.map((l) => ({
      source: byId.get(l.source) ?? l.source,
      target: byId.get(l.target) ?? l.target,
    }))

    nodesRef.current = simNodes
    linksRef.current = simLinks

    const ctxOrNull = canvas.getContext('2d')
    if (!ctxOrNull) return
    const ctx = ctxOrNull

    simRef.current?.stop()
    const sim = forceSimulation<SimNode>(simNodes)
      .force(
        'link',
        forceLink<SimNode, SimLink>(simLinks)
          .id((d) => d.id)
          .distance(56)
          .strength(0.4),
      )
      .force('charge', forceManyBody().strength(-120))
      .force('center', forceCenter(width / 2, height / 2))
      .force(
        'collide',
        forceCollide<SimNode>().radius((d) => nodeRadius(d) + 4),
      )
    simRef.current = sim

    function draw() {
      const { width: w, height: h } = sizeRef.current
      const { selectedId: sel, highlightIds: hop, activeIds: active } = propsRef.current
      const t = transformRef.current
      ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0)
      ctx.clearRect(0, 0, w, h)
      ctx.save()
      ctx.translate(t.x, t.y)
      ctx.scale(t.k, t.k)

      const hopActive = hop != null && hop.size > 0

      for (const link of linksRef.current) {
        const s = link.source as SimNode
        const tg = link.target as SimNode
        if (s.x == null || tg.x == null) continue
        const idOk =
          active.has(s.id) &&
          active.has(tg.id) &&
          (!hopActive || (hop.has(s.id) && hop.has(tg.id)))
        ctx.beginPath()
        ctx.moveTo(s.x, s.y)
        ctx.lineTo(tg.x, tg.y)
        ctx.strokeStyle = idOk ? 'rgba(161,161,170,0.55)' : 'rgba(63,63,70,0.25)'
        ctx.lineWidth = idOk && hopActive ? 1.5 / t.k : 1 / t.k
        ctx.stroke()
      }

      for (const n of nodesRef.current) {
        if (n.x == null || n.y == null) continue
        const inActive = active.has(n.id)
        const inHop = !hopActive || hop!.has(n.id)
        const alpha = inActive && inHop ? 1 : 0.18
        const r = nodeRadius(n)
        ctx.globalAlpha = alpha
        if (n.kind === 'entity') {
          const size = r * 1.6
          ctx.fillStyle = ENTITY_FILL
          ctx.strokeStyle = n.id === sel ? '#fafafa' : ENTITY_STROKE
          ctx.lineWidth = (n.id === sel ? 2 : 1) / t.k
          fillRoundRect(ctx, n.x - size, n.y - size, size * 2, size * 2, 3)
          ctx.fill()
          ctx.stroke()
          if (t.k > 0.85) {
            ctx.fillStyle = '#e4e4e7'
            ctx.font = `${11 / t.k}px ui-monospace, monospace`
            ctx.textAlign = 'center'
            ctx.fillText(n.name.slice(0, 18), n.x, n.y - size - 4 / t.k)
          }
        } else {
          ctx.beginPath()
          ctx.arc(n.x, n.y, r, 0, Math.PI * 2)
          ctx.fillStyle = MEMORY_TYPE_FILL[n.memory_type] ?? DEFAULT_MEMORY_FILL
          ctx.fill()
          if (n.id === sel) {
            ctx.strokeStyle = '#fafafa'
            ctx.lineWidth = 2 / t.k
            ctx.stroke()
          }
        }
        ctx.globalAlpha = 1
      }
      ctx.restore()
    }

    drawRef.current = draw
    sim.on('tick', draw)
    draw()

    function pointerToWorld(event: MouseEvent): { x: number; y: number } {
      const rect = canvas.getBoundingClientRect()
      const x = event.clientX - rect.left
      const y = event.clientY - rect.top
      const t = transformRef.current
      return { x: (x - t.x) / t.k, y: (y - t.y) / t.k }
    }

    function hitTest(x: number, y: number): SimNode | null {
      for (let i = nodesRef.current.length - 1; i >= 0; i--) {
        const n = nodesRef.current[i]
        if (n.x == null || n.y == null) continue
        const r = nodeRadius(n) + (n.kind === 'entity' ? 4 : 2)
        const dx = n.x - x
        const dy = n.y - y
        if (dx * dx + dy * dy <= r * r) return n
      }
      return null
    }

    const zoomer = zoom<HTMLCanvasElement, unknown>()
      .scaleExtent([0.25, 4])
      .filter((event) => {
        if (event.type === 'mousedown' || event.type === 'pointerdown') {
          const p = pointerToWorld(event as MouseEvent)
          return !hitTest(p.x, p.y)
        }
        return true
      })
      .on('zoom', (event) => {
        transformRef.current = event.transform
        draw()
      })

    const canvasSel = select(canvas)
    canvasSel.call(zoomer)

    const nodeDrag = drag<HTMLCanvasElement, unknown>()
      .subject((event) => {
        const p = pointerToWorld(event.sourceEvent as MouseEvent)
        return hitTest(p.x, p.y)
      })
      .on('start', (event) => {
        if (!event.subject) return
        sim.alphaTarget(0.2).restart()
        ;(event.subject as SimNode).fx = (event.subject as SimNode).x
        ;(event.subject as SimNode).fy = (event.subject as SimNode).y
      })
      .on('drag', (event) => {
        if (!event.subject) return
        const p = pointerToWorld(event.sourceEvent as MouseEvent)
        ;(event.subject as SimNode).fx = p.x
        ;(event.subject as SimNode).fy = p.y
      })
      .on('end', (event) => {
        if (!event.subject) return
        sim.alphaTarget(0)
        ;(event.subject as SimNode).fx = null
        ;(event.subject as SimNode).fy = null
      })

    let lastClickAt = 0
    let lastClickId: string | null = null
    let pointerDownPos: { clientX: number; clientY: number } | null = null

    function onPointerDown(event: PointerEvent) {
      if (event.button !== 0) return
      pointerDownPos = { clientX: event.clientX, clientY: event.clientY }
    }

    function onPointerCancel() {
      pointerDownPos = null
    }

    function onPointerUp(event: PointerEvent) {
      if (event.button !== 0) return
      const down = pointerDownPos
      pointerDownPos = null
      // Pan / node-drag: skip select and double-click focus
      if (!isClickGesture(down, event)) return
      const p = pointerToWorld(event)
      const hit = hitTest(p.x, p.y)
      const now = Date.now()
      if (hit && lastClickId === hit.id && now - lastClickAt < 350) {
        propsRef.current.onFocusRequest(hit.id)
        lastClickAt = 0
        lastClickId = null
        return
      }
      lastClickAt = now
      lastClickId = hit?.id ?? null
      propsRef.current.onSelect(hit ? hit.id : null)
    }

    canvas.addEventListener('pointerdown', onPointerDown)
    canvas.addEventListener('pointerup', onPointerUp)
    canvas.addEventListener('pointercancel', onPointerCancel)
    canvasSel.call(nodeDrag)

    const ro = new ResizeObserver(() => {
      const w = wrap.clientWidth
      const h = wrap.clientHeight
      sizeRef.current = { width: w, height: h }
      canvas.width = w * devicePixelRatio
      canvas.height = h * devicePixelRatio
      canvas.style.width = `${w}px`
      canvas.style.height = `${h}px`
      sim.force('center', forceCenter(w / 2, h / 2))
      sim.alpha(0.2).restart()
      draw()
    })
    ro.observe(wrap)

    return () => {
      ro.disconnect()
      canvas.removeEventListener('pointerdown', onPointerDown)
      canvas.removeEventListener('pointerup', onPointerUp)
      canvas.removeEventListener('pointercancel', onPointerCancel)
      sim.stop()
      canvasSel.on('.zoom', null)
      canvasSel.on('.drag', null)
    }
  }, [nodes, links])

  useEffect(() => {
    drawRef.current()
  }, [selectedId, highlightIds, activeIds])

  return (
    <div ref={wrapRef} className="relative h-full min-h-0 w-full flex-1">
      <canvas ref={canvasRef} className="block h-full w-full cursor-grab active:cursor-grabbing" />
    </div>
  )
}
