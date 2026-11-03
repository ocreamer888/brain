/**
 * A stored atlas dataset served by /v1/atlas/:id (e.g. the AI Model Atlas
 * replica in the ATLAS brain), decoded into the shape AtlasCanvas draws.
 */
export type AtlasMeta = {
  instance: string
  config: { title: string; description: string; palette: string[]; point_size_range: [number, number]; link_opacity: number; quantile_extent: [number, number]; background: string }
  imported_at: string
  points: number
  links: number
  categories: string[]
  category_counts: number[]
}

export type Geometry = { n: number; m: number; positions: Float32Array; size: Float32Array; category: Uint32Array; links: Uint32Array }

/** Binary layout from the API: u32 n, u32 m, f32 xyz[3n], f32 size[n], u32 category[n], u32 links[2m]. */
export function decodeGeometry(buf: ArrayBuffer): Geometry {
  const head = new DataView(buf)
  const n = head.getUint32(0, true)
  const m = head.getUint32(4, true)
  const need = 8 + n * 20 + m * 8
  if (buf.byteLength !== need) throw new Error(`atlas geometry: expected ${need} bytes, got ${buf.byteLength}`)
  let o = 8
  const take = <T>(Kind: new (b: ArrayBuffer, o: number, l: number) => T, len: number) => {
    const v = new Kind(buf, o, len)
    o += len * 4
    return v
  }
  return {
    n,
    m,
    positions: take(Float32Array, n * 3),
    size: take(Float32Array, n),
    category: take(Uint32Array, n),
    links: take(Uint32Array, m * 2),
  }
}

/** Sizes mapped linearly from the data range onto the config's pixel range, as ratios (min = 1). */
export function sizeScale(size: Float32Array, range: [number, number]): Float32Array {
  let lo = Infinity
  let hi = -Infinity
  for (const v of size) {
    if (v < lo) lo = v
    if (v > hi) hi = v
  }
  const [a, b] = range[0] > 0 ? range : [6, 10]
  const span = hi - lo || 1
  return Float32Array.from(size, (v) => (a + ((v - lo) / span) * (b - a)) / a)
}

/** Point colours: palette[category % length] (categories arrive ranked by frequency). */
export function categoryColors(category: Uint32Array, palette: string[]): Float32Array {
  const rgb = palette.map((h) => [1, 3, 5].map((k) => parseInt(h.slice(k, k + 2), 16) / 255))
  const out = new Float32Array(category.length * 3)
  category.forEach((c, i) => out.set(rgb[c % rgb.length], i * 3))
  return out
}

/**
 * Name search, ranked like a person expects: exact name, then names starting
 * with the query, then names containing it; ties go to the point with more
 * links (`weight`), then the shorter name. Case-insensitive.
 */
export function searchLabels(labels: string[], query: string, limit = 8, weight?: ArrayLike<number>): number[] {
  const q = query.trim().toLowerCase()
  if (!q) return []
  const hits: [number, number, number, number][] = []
  for (let i = 0; i < labels.length; i++) {
    const l = labels[i].toLowerCase()
    const at = l.indexOf(q)
    if (at < 0) continue
    // A match after "/" (an author prefix, e.g. "org/name") counts as a start.
    const tier = l === q || l.endsWith('/' + q) ? 0 : at === 0 || l[at - 1] === '/' ? 1 : 2
    hits.push([tier, -(weight?.[i] ?? 0), l.length, i])
  }
  hits.sort((a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2] || a[3] - b[3])
  return hits.slice(0, limit).map((h) => h[3])
}
