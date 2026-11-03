import { useEffect, useMemo, useRef, useState } from 'react'
import { apiKey } from '../../api'
import MemoryReading from '../../components/brand/MemoryReading'
import { Button, SearchPill, Segmented, TypeChip } from '../../components/brand/primitives'
import { decodeAtlas, findEntities, neighbors, projectColors } from '../../lib/atlas'
import { signalFor } from '../../lib/memorySignals'
import { useLoad } from '../../lib/useLoad'
import { useStats } from '../../context/StatsContext'
import AtlasCanvas from './AtlasCanvas'
import ReferenceAtlas from './ReferenceAtlas'
import { recall, remember } from './viewMemory'
import styles from './LinkedAtlas.module.css'

const fmt = new Intl.NumberFormat('en-US')
/** The reading pane's footprint (30rem + its right margin), so the canvas centres beside it. */
const readingWidth = () => 30 * parseFloat(getComputedStyle(document.documentElement).fontSize) + 20
const built = new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeStyle: 'short' })
const LIST_CAP = 200
const LEGEND_CAP = 10
const MODES = [
  { value: 'project', label: 'Project' },
  { value: 'type', label: 'Type' },
]

const authed = (path, init = {}) => fetch(path, { ...init, headers: { 'x-api-key': apiKey(), ...init.headers } })

/** A brain's memory atlas, served live (stored layout + current memories). Null = never built. */
async function loadAtlas(brainId) {
  const r = await authed(`/v1/memory-atlas/${brainId}`)
  if (!r.ok) throw new Error(`${r.status}`)
  const body = await r.json()
  if (body.meta?.needs_build) return null
  // Memory bodies are packed at touching distance; a point about half the gap
  // keeps their grain visible (the look tuned 2026-10-19).
  return { ...decodeAtlas(body), pointToSpacing: 0.43 }
}

/**
 * Linked: the memory atlas (continues the atlas-preview work; goal look = the AI
 * Model Atlas). Memories and the entities they mention, every real "mentions"
 * edge drawn (brand book §8: a line is a real link). Projects are organs.
 */
export default function LinkedAtlas({ initialEntity = 'all' }) {
  const { stats } = useStats()
  const active = stats?.active_instance ?? null
  const dataset = useStoredDataset(active?.id ?? null)
  const hasMemories = (stats?.total_memories ?? 0) > 0
  const options = [
    ...(hasMemories || !dataset ? [{ value: 'memories', label: `${active?.name ?? 'My'} · memories` }] : []),
    ...(dataset ? [{ value: 'dataset', label: dataset.title }] : []),
  ]
  const [picked, setPicked] = useState(null)
  // Reset the choice when the active brain changes; default to what this brain has.
  const source = options.some((o) => o.value === picked) ? picked : options[0]?.value ?? 'memories'
  useEffect(() => setPicked(null), [active?.id])
  return (
    <div data-theme="dark" className={styles.root}>
      {source === 'dataset' ? <ReferenceAtlas key={active.id} instance={active.id} /> : <MemoryAtlas initialEntity={initialEntity} />}
      {options.length > 1 && (
        <div className={styles.sourceBar} data-atlas-panel>
          <Segmented label="Atlas to show" options={options} value={source} onChange={setPicked} />
        </div>
      )}
    </div>
  )
}

/**
 * The active brain's stored atlas dataset, if it has one. Only the active
 * brain: brains don't share a wall (brand book, Instances), so Main never
 * shows what lives in ATLAS.
 */
function useStoredDataset(brainId) {
  const found = useLoad(async () => {
    const r = await fetch(`/v1/atlas/${brainId}`, { headers: { 'x-api-key': apiKey() } })
    const meta = r.ok ? await r.json() : null
    return meta?.points ? { title: meta.config?.title || 'Stored atlas' } : null
  }, brainId)
  return found.data ?? null
}

function MemoryAtlas({ initialEntity }) {
  // Follows the active brain: switching brains switches the atlas.
  const brainId = useStats().stats?.active_instance?.id ?? null
  const [nonce, setNonce] = useState(0)
  const atlas = useLoad(() => loadAtlas(brainId), brainId ? `${brainId}:${nonce}` : null)
  const rebuild = useRebuild(brainId, () => setNonce((n) => n + 1))
  const root = useRef(null)
  const typeColors = useSignalColors(root, atlas.data?.types)
  return (
    <div ref={root} className={styles.fill}>
      {atlas.loading && !atlas.data && <p className={`t-body ${styles.center}`}>Loading the atlas…</p>}
      {atlas.error && <p className={`t-body ${styles.center}`} role="alert">Couldn't load the atlas ({atlas.error}).</p>}
      {brainId && !atlas.loading && !atlas.error && !atlas.data && <NotBuilt rebuild={rebuild} />}
      {atlas.data && typeColors && <Explorer key={`${brainId}:${nonce}`} atlas={atlas.data} typeColors={typeColors} initialEntity={initialEntity} rebuild={rebuild} viewKey={`memories:${brainId}`} />}
    </div>
  )
}

/**
 * Rebuild the stored layout in the background (POST, then poll status); calls
 * `onDone` when a new layout is ready. Survives navigation: status is server-side.
 */
function useRebuild(brainId, onDone) {
  const [state, setState] = useState({ running: false, error: null })
  const done = useRef(onDone)
  done.current = onDone
  useEffect(() => {
    if (!state.running || !brainId) return
    let stop = false
    const poll = async () => {
      if (stop) return
      const s = await authed(`/v1/memory-atlas/${brainId}/status`).then((r) => r.json()).catch(() => null)
      if (stop) return
      if (s && !s.running) {
        setState({ running: false, error: s.last?.status === 'failed' ? s.last.error || 'Rebuild failed.' : null })
        if (s.last?.status === 'done') done.current()
        return
      }
      setTimeout(poll, 1500)
    }
    poll()
    return () => (stop = true)
  }, [state.running, brainId])
  const start = async () => {
    setState({ running: true, error: null })
    const r = await authed(`/v1/memory-atlas/${brainId}/rebuild`, { method: 'POST' }).catch(() => null)
    if (!r?.ok) setState({ running: false, error: `Couldn't start the rebuild${r ? ` (${r.status})` : ''}.` })
  }
  return { ...state, start }
}

function Explorer({ atlas, typeColors, initialEntity, rebuild, viewKey }) {
  const canvas = useRef(null)
  const p = atlas.points
  const saved = recall(viewKey)
  const pointAt = (id) => (id == null ? null : atlas.indexOf.get(id) ?? null) // ids survive rebuilds; indices don't
  const [mode, setMode] = useState(saved?.mode ?? 'project')
  const [entity, setEntity] = useState(() => {
    // 'all' is the shell's "no filter"; a real entity can be named "all", so never match it.
    if (!initialEntity || initialEntity === 'all') return pointAt(saved?.entity)
    const want = initialEntity.toLowerCase()
    const i = p.label.findIndex((l, k) => p.kind[k] === 1 && l.toLowerCase() === want)
    return i >= 0 ? i : null
  })
  const [focus, setFocus] = useState(() => pointAt(saved?.focus))
  const [hover, setHover] = useState(null)
  useEffect(() => {
    remember(viewKey, { mode, entity: entity == null ? null : p.id[entity], focus: focus == null ? null : p.id[focus] })
  }, [viewKey, mode, entity, focus, p])
  const palette = useMemo(() => projectColors(atlas.projects.length), [atlas])
  const pointColors = useMemo(() => colorsFor(atlas, mode, palette, typeColors), [atlas, mode, palette, typeColors])
  // Biggest topics first: the canvas labels as many as fit when zoomed in.
  const topicTags = useMemo(() => {
    const hubs = []
    for (let i = 0; i < p.id.length; i++) if (p.kind[i] === 1) hubs.push(i)
    return hubs.sort((a, b) => p.size[b] - p.size[a]).slice(0, 80).map((i) => ({ i, text: p.label[i] }))
  }, [p])
  const members = useMemo(() => (entity == null ? [] : [...neighbors(atlas, entity)]), [atlas, entity])

  const highlight = useMemo(() => {
    if (entity == null && focus == null) return null
    const mask = new Uint8Array(p.id.length)
    for (const i of [entity, ...members, focus].filter((v) => v != null)) mask[i] = 1
    if (focus != null) for (const i of neighbors(atlas, focus)) mask[i] = 1
    return mask
  }, [atlas, p, entity, members, focus])

  // Fly to a topic when it's chosen, not when a remembered one is restored
  // (compared by value, so React's double-run of effects in dev can't trip it).
  const restoredEntity = useRef(saved?.camera && (!initialEntity || initialEntity === 'all') ? entity : undefined)
  useEffect(() => {
    if (entity === restoredEntity.current) return
    restoredEntity.current = undefined
    if (entity != null) canvas.current?.flyTo([entity, ...members])
  }, [entity, members])

  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== 'Escape') return
      if (focus != null) setFocus(null)
      else if (entity != null) setEntity(null)
    }
    addEventListener('keydown', onKey)
    return () => removeEventListener('keydown', onKey)
  }, [focus, entity])

  const select = (i) => {
    if (i == null) return
    if (p.kind[i] === 1) {
      setFocus(null)
      setEntity(i)
    } else {
      setFocus(i)
      canvas.current?.flyTo([i])
    }
  }
  return (
    <>
      <AtlasCanvas
        ref={canvas}
        atlas={atlas}
        pointColors={pointColors}
        highlight={highlight}
        focus={focus}
        viewKey={viewKey}
        labels={topicTags}
        hovered={hover?.i ?? null}
        insetRight={focus != null ? readingWidth() : 0}
        onHover={(i, at) => setHover(i == null ? null : { i, ...at })}
        onSelect={select}
        label={`Memory atlas: ${fmt.format(atlas.meta.memories)} memories, ${fmt.format(atlas.meta.entities)} entities, ${fmt.format(atlas.meta.edges)} links. Use the entity finder and its list to explore by keyboard.`}
      />
      <div className={styles.stack} data-atlas-panel>
        <AtlasCard atlas={atlas} mode={mode} onMode={setMode} palette={palette} onHome={() => canvas.current?.home()} rebuild={rebuild} />
        <Finder atlas={atlas} entity={entity} members={members} onEntity={setEntity} onPick={select} />
      </div>
      {hover && <Tip atlas={atlas} hover={hover} />}
      {focus != null && <Reading id={p.id[focus]} links={neighbors(atlas, focus).length} onClose={() => setFocus(null)} onOpen={(id) => select(atlas.indexOf.get(id) ?? null)} />}
    </>
  )
}

/** Per-point rgb: by project (vivid, the atlas look) or by memory type (brand signals). */
function colorsFor(atlas, mode, palette, typeColors) {
  const p = atlas.points
  const out = new Float32Array(p.id.length * 3)
  for (let i = 0; i < p.id.length; i++) {
    let c
    if (mode === 'project') c = palette[p.project[i]]
    else c = p.kind[i] === 1 ? [0.62, 0.66, 0.72] : typeColors[p.type[i]]
    out.set(c, i * 3)
  }
  return out
}

function AtlasCard({ atlas, mode, onMode, palette, onHome, rebuild }) {
  const m = atlas.meta
  const present = new Set(atlas.points.type.filter((t) => t >= 0))
  const toRgb = (c) => `rgb(${c.map((v) => Math.round(v * 255)).join(' ')})`
  return (
    <section className={`glass ${styles.card}`} aria-label="Atlas">
      <h2 className={`t-h2 ${styles.title}`}>Memory atlas</h2>
      <p className={`t-small ${styles.secondary}`}>
        {fmt.format(m.memories)} memories · {fmt.format(m.entities)} hub entities · {fmt.format(m.edges + (m.extra_edges ?? 0))} real links
      </p>
      {m.superseded > 0 && (
        <p className={`t-small ${styles.secondary}`}>
          Every current memory. {fmt.format(m.superseded)} older versions, replaced by newer ones, aren't shown.
        </p>
      )}
      <p className={`t-small ${styles.secondary}`}>
        Layout built {built.format(new Date(m.built_at))}
        {m.unplaced > 0 && ` · ${fmt.format(m.unplaced)} new since, placed by their topic`}
      </p>
      <RebuildButton rebuild={rebuild} />
      <div className={styles.modeRow}>
        <span className={`t-label ${styles.secondary}`}>Color by</span>
        <Segmented label="Color points by" options={MODES} value={mode} onChange={onMode} />
      </div>
      {mode === 'project' ? (
        <ul className={styles.legend} aria-label="Project colors">
          {atlas.projects.slice(0, LEGEND_CAP).map((pr, i) => (
            <li key={pr.name} className={`t-small ${styles.swatch}`}>
              <i style={{ background: toRgb(palette[i]) }} aria-hidden />
              {pr.name}
            </li>
          ))}
          {atlas.projects.length > LEGEND_CAP && <li className={`t-small ${styles.secondary}`}>{atlas.projects.length - LEGEND_CAP} more</li>}
        </ul>
      ) : (
        <ul className={styles.legend} aria-label="Memory type colors">
          {atlas.types.map((t, i) => (present.has(i) ? <li key={t}><TypeChip type={t} /></li> : null))}
        </ul>
      )}
      <Button icon="dashboard" onClick={onHome}>Reset view</Button>
    </section>
  )
}

/** Entity search → its memories lit, and a keyboard-usable list of them. */
function Finder({ atlas, entity, members, onEntity, onPick }) {
  const [query, setQuery] = useState('')
  const p = atlas.points
  const matches = findEntities(atlas, query)
  if (entity != null) {
    return (
      <section className={`glass ${styles.card} ${styles.finder}`} aria-label="Entity">
        <div className={styles.entityHead}>
          <h2 className={`t-h2 ${styles.title}`}>{p.label[entity]}</h2>
          <Button icon="close" onClick={() => onEntity(null)}>Clear</Button>
        </div>
        <p className={`t-small ${styles.secondary}`}>{fmt.format(members.length)} memories mention it (lit)</p>
        <ul className={styles.list} aria-label={`Memories that mention ${p.label[entity]}`}>
          {members.slice(0, LIST_CAP).map((i) => (
            <li key={i}>
              <button type="button" className={`pressable ${styles.item}`} onClick={() => onPick(i)}>
                <TypeChip type={atlas.types[p.type[i]]} />
                <span className={`t-small ${styles.itemText}`}>{p.label[i]}</span>
              </button>
            </li>
          ))}
        </ul>
        {members.length > LIST_CAP && <p className={`t-small ${styles.secondary}`}>First {LIST_CAP} listed; all are lit.</p>}
      </section>
    )
  }
  return (
    <section className={`glass ${styles.card} ${styles.finder}`} aria-label="Find an entity">
      <SearchPill value={query} onChange={setQuery} placeholder="Find an entity (React, SICOP…)" />
      {query.trim() && !matches.length && <p className={`t-small ${styles.secondary}`}>No entity matches.</p>}
      <ul className={styles.suggest}>
        {matches.map((i) => (
          <li key={i}>
            <button type="button" className={`pressable ${styles.item}`} onClick={() => (onEntity(i), setQuery(''))}>
              <span className={`t-small ${styles.itemText}`}>{p.label[i]}</span>
              <span className={`t-mono ${styles.count}`}>{fmt.format(neighbors(atlas, i).length)}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}

function Tip({ atlas, hover }) {
  const p = atlas.points
  const i = hover.i
  const project = atlas.projects[p.project[i]]?.name
  const entity = p.kind[i] === 1
  return (
    <div className={`glass t-small ${styles.tip}`} style={{ left: hover.x + 14, top: hover.y + 14 }} aria-hidden>
      <span className={styles.tipLabel}>{entity ? `Entity: ${p.label[i]}` : p.label[i]}</span>
      <span className={styles.secondary}>
        {entity ? `${fmt.format(neighbors(atlas, i).length)} memories mention it · click to light them` : `${signalFor(atlas.types[p.type[i]]).label} · ${project} · ${p.size[i]} links`}
      </span>
    </div>
  )
}

function Reading({ id, links, onClose, onOpen }) {
  return (
    <aside className={`glass ${styles.reading}`} aria-label="Selected memory" data-atlas-panel>
      <div className={styles.readingHead}>
        <p className={`t-small ${styles.secondary}`} role="status">
          {links ? `Its ${fmt.format(links)} entities and their links are lit` : 'This memory mentions no shared entity.'}
        </p>
        <Button icon="close" onClick={onClose}>Close</Button>
      </div>
      <div className={styles.readingBody}>
        <MemoryReading key={id} id={id} onOpen={onOpen} />
      </div>
    </aside>
  )
}

function RebuildButton({ rebuild }) {
  return (
    <div className={styles.rebuild}>
      <Button icon="layers" onClick={rebuild.start} disabled={rebuild.running}>
        {rebuild.running ? 'Placing every memory…' : 'Rebuild layout'}
      </Button>
      {rebuild.error && <span className={`t-small ${styles.errorText}`} role="alert">{rebuild.error}</span>}
    </div>
  )
}

function NotBuilt({ rebuild }) {
  return (
    <div className={`${styles.center} ${styles.notBuilt}`}>
      <h2 className="t-h2">This brain's atlas hasn't been built yet</h2>
      <p className={`t-body ${styles.secondary}`}>It places every memory and the topics they mention in 3D, then saves the positions. About 20 seconds.</p>
      <div>
        <Button variant="primary" icon="layers" onClick={rebuild.start} disabled={rebuild.running}>
          {rebuild.running ? 'Placing every memory…' : 'Build the atlas'}
        </Button>
      </div>
      {rebuild.error && <p className={`t-small ${styles.errorText}`} role="alert">{rebuild.error}</p>}
    </div>
  )
}

/** Memory-type colors as GPU rgb triples, read from the design tokens (dark scheme). */
function useSignalColors(root, types) {
  const [colors, setColors] = useState(null)
  useEffect(() => {
    if (!root.current || !types) return
    const probe = document.createElement('span')
    root.current.appendChild(probe)
    setColors(
      types.map((t) => {
        probe.style.color = `var(--sig-${signalFor(t).signal}-fg)`
        const [r, g, b] = getComputedStyle(probe).color.match(/[\d.]+/g).map(Number)
        return [r / 255, g / 255, b / 255]
      }),
    )
    probe.remove()
  }, [root, types])
  return colors
}
