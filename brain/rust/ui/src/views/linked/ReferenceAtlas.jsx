import { useEffect, useMemo, useRef, useState } from 'react'
import { apiKey } from '../../api'
import { Button, SearchPill } from '../../components/brand/primitives'
import { categoryColors, decodeGeometry, searchLabels, sizeScale } from '../../lib/atlasRef'
import { useLoad } from '../../lib/useLoad'
import AtlasCanvas from './AtlasCanvas'
import { recall, remember } from './viewMemory'
import styles from './LinkedAtlas.module.css'

const fmt = new Intl.NumberFormat('en-US')
const LEGEND = 8

// Mirrors api.js's api(): dispatches brain:unauthorized on a 401 so AuthGate
// re-locks. Fetches directly rather than through api() because this view
// needs binary (arrayBuffer) geometry payloads, not just JSON. Found missing
// in a 2026-11-09 forensic pass -- same class of gap already fixed once in
// apiFetch.js.
async function get(path, as = 'json') {
  const r = await fetch(path, { headers: { 'x-api-key': apiKey() } })
  if (!r.ok) {
    if (r.status === 401 && typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('brain:unauthorized'))
    }
    throw new Error(`${r.status}`)
  }
  return as === 'json' ? r.json() : r.arrayBuffer()
}

/**
 * A stored atlas dataset rendered the way its source project does (positions,
 * categorical palette, size range, links from the data). Geometry first so it
 * draws at once; labels stream in after for hover and search.
 */
export default function ReferenceAtlas({ instance }) {
  const data = useLoad(async () => {
    const [meta, buf] = await Promise.all([get(`/v1/atlas/${instance}`), get(`/v1/atlas/${instance}/geometry`, 'bin')])
    return { meta, geo: decodeGeometry(buf) }
  }, instance)
  const labels = useLoad(async () => (await get(`/v1/atlas/${instance}/labels`)).label, data.data ? instance : null)

  if (data.error) return <p className={`t-body ${styles.center}`} role="alert">Couldn't load this atlas ({data.error}).</p>
  if (!data.data) return <p className={`t-body ${styles.center}`}>Loading the atlas…</p>
  if (!data.data.meta.points) return <p className={`t-body ${styles.center}`}>This brain has no atlas yet.</p>
  return <Explorer meta={data.data.meta} geo={data.data.geo} labels={labels.data} viewKey={`dataset:${instance}`} />
}

function Explorer({ meta, geo, labels, viewKey }) {
  const canvas = useRef(null)
  const [focus, setFocus] = useState(() => recall(viewKey)?.focus ?? null)
  useEffect(() => remember(viewKey, { focus }), [viewKey, focus])
  const [hover, setHover] = useState(null)
  const cfg = meta.config
  const atlas = useMemo(
    () => ({ positions: geo.positions, edges: geo.links, sizes: sizeScale(geo.size, cfg.point_size_range) }),
    [geo, cfg],
  )
  const colors = useMemo(() => categoryColors(geo.category, cfg.palette), [geo, cfg])
  const degree = useMemo(() => {
    const d = new Uint32Array(geo.n)
    for (const v of geo.links) d[v]++
    return d
  }, [geo])
  // The most-linked points (FLUX.1-dev, Llama…) label the map once names arrive.
  const tags = useMemo(() => {
    if (!labels) return []
    const order = Array.from(degree.keys()).sort((a, b) => degree[b] - degree[a]).slice(0, 80)
    return order.filter((i) => degree[i] > 0).map((i) => ({ i, text: labels[i] }))
  }, [labels, degree])
  const neighbours = useMemo(() => (focus == null ? null : linkedTo(geo, focus)), [geo, focus])
  const highlight = useMemo(() => {
    if (focus == null) return null
    const mask = new Uint8Array(geo.n)
    mask[focus] = 1
    for (const i of neighbours) mask[i] = 1
    return mask
  }, [geo, focus, neighbours])

  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && setFocus(null)
    addEventListener('keydown', onKey)
    return () => removeEventListener('keydown', onKey)
  }, [])

  const select = (i) => {
    if (i == null) return
    setFocus(i)
    canvas.current?.flyTo([i, ...linkedTo(geo, i)])
  }
  const category = (i) => meta.categories[geo.category[i]]
  return (
    <>
      <AtlasCanvas
        ref={canvas}
        atlas={atlas}
        pointColors={colors}
        highlight={highlight}
        focus={focus}
        viewKey={viewKey}
        labels={tags}
        hovered={hover?.i ?? null}
        onHover={(i, at) => setHover(i == null ? null : { i, ...at })}
        onSelect={select}
        label={`${cfg.title}: ${fmt.format(meta.points)} points, ${fmt.format(meta.links)} links. Use the search to explore by keyboard.`}
      />
      <div className={styles.stack} data-atlas-panel>
        <section className={`glass ${styles.card}`} aria-label="Atlas">
          <h2 className={`t-h2 ${styles.title}`}>{cfg.title}</h2>
          <p className={`t-small ${styles.secondary}`}>
            {fmt.format(meta.points)} points · {fmt.format(meta.links)} links · stored in the {meta.instance.toUpperCase()} brain
          </p>
          <ul className={styles.legend} aria-label="Colors (most common first)">
            {meta.categories.slice(0, LEGEND).map((c, i) => (
              <li key={c} className={`t-small ${styles.swatch}`}>
                <i style={{ background: cfg.palette[i % cfg.palette.length] }} aria-hidden />
                {c}
              </li>
            ))}
            <li className={`t-small ${styles.secondary}`}>{fmt.format(meta.categories.length - LEGEND)} more</li>
          </ul>
          <Button icon="dashboard" onClick={() => canvas.current?.home()}>Reset view</Button>
        </section>
        <Finder labels={labels} degree={degree} onPick={select} />
        {focus != null && (
          <section className={`glass ${styles.card}`} aria-label="Selected point">
            <div className={styles.entityHead}>
              <h2 className={`t-h2 ${styles.title}`}>{labels?.[focus] ?? `#${focus}`}</h2>
              <Button icon="close" onClick={() => setFocus(null)}>Close</Button>
            </div>
            <p className={`t-small ${styles.secondary}`}>
              {category(focus)} · {fmt.format(neighbours.length)} linked (lit)
            </p>
          </section>
        )}
      </div>
      {hover && (
        <div className={`glass t-small ${styles.tip}`} style={{ left: hover.x + 14, top: hover.y + 14 }} aria-hidden>
          <span className={styles.tipLabel}>{labels?.[hover.i] ?? '…'}</span>
          <span className={styles.secondary}>{category(hover.i)}</span>
        </div>
      )}
    </>
  )
}

function Finder({ labels, degree, onPick }) {
  const [query, setQuery] = useState('')
  const hits = useMemo(() => (labels ? searchLabels(labels, query, 8, degree) : []), [labels, query, degree])
  return (
    <section className={`glass ${styles.card} ${styles.finder}`} aria-label="Find a point">
      <SearchPill value={query} onChange={setQuery} placeholder={labels ? 'Find by name' : 'Loading names…'} />
      {query.trim() && labels && !hits.length && <p className={`t-small ${styles.secondary}`}>No match.</p>}
      <ul className={styles.suggest}>
        {hits.map((i) => (
          <li key={i}>
            <button type="button" className={`pressable ${styles.item}`} onClick={() => (onPick(i), setQuery(''))}>
              <span className={`t-small ${styles.itemText}`}>{labels[i]}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}

/** Points sharing a link with `i` (both directions). Linear scan: fine for one focus at a time. */
function linkedTo(geo, i) {
  const out = []
  const L = geo.links
  for (let k = 0; k < L.length; k += 2) {
    if (L[k] === i) out.push(L[k + 1])
    else if (L[k + 1] === i) out.push(L[k])
  }
  return out
}
