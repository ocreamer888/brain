import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { pointScale } from '../../lib/atlas'
import { concatPairs, makeRibbons } from './linkRibbons'
import { recall, remember } from './viewMemory'
import styles from './AtlasCanvas.module.css'

// Matched to the AI Model Atlas (its published config + measured layout):
// points sit ~1.6 apart in a body, so a 1.7-unit sphere makes bodies read solid.
// Point and link sizes follow the data's own scale: a point is ~0.85 of the
// typical gap between neighbours (Brain ≈ 1.6 units, the AI Model Atlas ≈ 12.6).
const POINT_TO_SPACING = 0.85
const MAX_PX = 26 // near points stop growing here (no marbles)
const DIM = 0.14 // brightness of points outside a highlight
// Link opacity: the atlas's 0.8 at rest (long links fade further on screen, in
// the ribbon shader); greyed-out links drop to 10% of that, like cosmos.gl.
// similar: dimmest tier -- an order of magnitude more of these than entity
// mentions (every memory has up to 10, vs. needing a shared hub), so kept
// faint by default; still readable close up, fades fastest in the crowd.
const LINK = { rest: 0.8, extra: 0.55, similar: 0.3, lit: 1, focus: 1, greyout: 0.08 }
const LINK_TO_POINT = 0.24 // link width as a share of a point
const reduceMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches

const vertexShader = /* glsl */ `
  attribute float size;
  attribute float dim;
  attribute vec3 color;
  uniform float scale;
  uniform float fadeNear;
  uniform float fadeFar;
  varying vec3 vColor;
  varying float vFade;
  varying float vDim;
  void main() {
    vDim = dim;
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    gl_Position = projectionMatrix * mv;
    float depth = -mv.z;
    gl_PointSize = clamp(size * scale / depth, 1.25, ${MAX_PX.toFixed(1)});
    vFade = mix(1.0, 0.4, clamp((depth - fadeNear) / (fadeFar - fadeNear), 0.0, 1.0));
    vColor = color;
  }
`
// Each sprite is lit like a small sphere (the atlas material), cut to a disc.
// Two passes share this shader: pass 0 draws lit points solid (with depth),
// pass 1 draws dimmed points as faint see-through spheres afterwards, so a
// greyed-out point can never hide a lit one (cosmos.gl's point greyout).
const fragmentShader = /* glsl */ `
  uniform float pass;
  varying vec3 vColor;
  varying float vFade;
  varying float vDim;
  void main() {
    if ((pass < 0.5) == (vDim > 0.5)) discard;
    vec2 p = gl_PointCoord * 2.0 - 1.0;
    float r2 = dot(p, p);
    if (r2 > 1.0) discard;
    vec3 n = vec3(p.x, -p.y, sqrt(1.0 - r2));
    vec3 l = normalize(vec3(-0.45, 0.55, 0.75));
    float diffuse = 0.38 + 0.62 * max(dot(n, l), 0.0);
    float spec = pow(max(dot(reflect(-l, n), vec3(0.0, 0.0, 1.0)), 0.0), 24.0) * 0.3;
    vec3 rgb = (vColor * diffuse + spec) * vFade;
    gl_FragColor = pass < 0.5 ? vec4(rgb, 1.0) : vec4(rgb, ${DIM.toFixed(2)});
  }
`

/**
 * The 3D memory atlas: points + every real edge. `pointColors`: Float32Array rgb
 * per point. `highlight`: Uint8Array (1 = lit) or null. `focus`: the point whose
 * own edges are brightest. Imperative: flyTo(indices), home().
 */
/** `insetRight`: px covered by a panel on the right; the view centres in what's left. */
/** `labels`: [{ i, text }] candidates, most important first; shown on screen when zoomed in. */
const AtlasCanvas = forwardRef(function AtlasCanvas({ atlas, pointColors, highlight, focus, hovered, insetRight = 0, viewKey, labels, onHover, onSelect, label }, ref) {
  const host = useRef(null)
  const world = useRef(null)
  const handlers = useRef({ onHover, onSelect })
  handlers.current = { onHover, onSelect }

  useEffect(() => {
    world.current = createWorld(host.current, atlas, handlers, viewKey)
    return () => world.current.dispose()
  }, [atlas, viewKey])

  useEffect(() => world.current?.paint(pointColors), [pointColors])
  useEffect(() => world.current?.style(highlight, focus), [highlight, focus, pointColors])
  useEffect(() => world.current?.ring(hovered ?? focus), [hovered, focus])
  useEffect(() => world.current?.inset(insetRight), [insetRight])
  useEffect(() => world.current?.setLabels(labels ?? []), [labels])

  useImperativeHandle(ref, () => ({
    flyTo: (indices) => world.current?.flyTo(indices),
    home: () => world.current?.home(),
  }))

  return <div ref={host} className={styles.host} role="img" aria-label={label} />
})

export default AtlasCanvas

function createWorld(host, atlas, handlers, viewKey) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2))
  host.appendChild(renderer.domElement)
  const scene = new THREE.Scene()
  const camera = new THREE.PerspectiveCamera(50, 1, 1, 40000)
  const controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = !reduceMotion()
  controls.dampingFactor = 0.08

  const { points, material, sizes, faint } = makePoints(atlas)
  // One ribbon batch: the forest first, then every other real mention link, then similar_to.
  const forestCount = atlas.edges.length / 2
  const extraCount = (atlas.extra?.length ?? 0) / 2
  const unit = (atlas.pointToSpacing ?? POINT_TO_SPACING) * typicalSpacing(atlas.positions)
  const links = makeRibbons(concatPairs(atlas.edges, atlas.extra, atlas.similar), atlas.positions, unit * LINK_TO_POINT)
  scene.add(links.mesh)
  let pxScale = 1
  scene.add(points)
  const ring = makeRing(material)
  scene.add(ring.points)

  // Home view frames the 5th–95th percentile of points (the atlas's quantileExtent),
  // so the main mass fills the screen and far satellites sit at the edges.
  const sphere = quantileSphere(atlas.positions, 0.05, 0.95)

  let frame = 0
  let tween = null
  const render = () => {
    frame = 0
    const moving = controls.update()
    if (tween) tween.step()
    const dist = camera.position.distanceTo(controls.target)
    material.uniforms.fadeNear.value = Math.max(1, dist - sphere.radius * 0.4)
    material.uniforms.fadeFar.value = dist + sphere.radius
    links.frame(camera, renderer, pxScale)
    renderer.render(scene, camera)
    tags.place(camera, controls, homeDistance)
    if (moving || tween) request()
  }
  const request = () => (frame ||= requestAnimationFrame(render))
  controls.addEventListener('change', request)

  let insetX = 0
  const resize = () => {
    const { clientWidth: w, clientHeight: h } = host
    if (!w || !h) return
    renderer.setSize(w, h, false)
    camera.aspect = w / h
    // Shift the projection so the scene's centre sits in the uncovered area.
    if (insetX) camera.setViewOffset(w, h, insetX / 2, 0, w, h)
    else camera.clearViewOffset()
    camera.updateProjectionMatrix()
    pxScale = (h * renderer.getPixelRatio()) / (2 * Math.tan((camera.fov * Math.PI) / 360))
    material.uniforms.scale.value = unit * pxScale
    request()
  }
  const tags = makeTags(host, atlas.positions)
  // Fixed by the atlas's size, not by how the camera started (it may be restored).
  const homeDistance = (sphere.radius / Math.sin((camera.fov * Math.PI) / 360)) * 1.02
  const ro = new ResizeObserver(resize)
  ro.observe(host)

  function frameSphere(center, radius, animate) {
    const dist = (radius / Math.sin((camera.fov * Math.PI) / 360)) * 1.02
    const dir = camera.position.clone().sub(controls.target).normalize()
    if (!isFinite(dir.x) || dir.lengthSq() === 0) dir.set(0.4, 0.35, 0.85).normalize()
    const toTarget = center.clone()
    const toPos = center.clone().add(dir.multiplyScalar(Math.max(dist, 60)))
    if (!animate || reduceMotion()) {
      controls.target.copy(toTarget)
      camera.position.copy(toPos)
      tween = null
      return request()
    }
    const fromTarget = controls.target.clone()
    const fromPos = camera.position.clone()
    const t0 = performance.now()
    tween = {
      step() {
        const t = Math.min(1, (performance.now() - t0) / 650)
        const e = 1 - (1 - t) ** 3
        controls.target.lerpVectors(fromTarget, toTarget, e)
        camera.position.lerpVectors(fromPos, toPos, e)
        if (t === 1) tween = null
      },
    }
    request()
  }
  // Come back to where you were; otherwise the home framing.
  const view = recall(viewKey)?.camera
  if (view) {
    camera.position.fromArray(view.position)
    controls.target.fromArray(view.target)
  } else {
    frameSphere(sphere.center, sphere.radius, false)
  }
  resize()

  const picker = makePicker(renderer.domElement, camera, points, handlers, () => camera.position.distanceTo(controls.target))
  let colors = null

  return {
    paint(next) {
      colors = next
      points.geometry.getAttribute('color').array.set(next)
      points.geometry.getAttribute('color').needsUpdate = true
      links.paint(next)
      request()
    },
    style(highlight, focus) {
      const dim = points.geometry.getAttribute('dim')
      const size = points.geometry.getAttribute('size')
      for (let i = 0; i < dim.count; i++) {
        const lit = !highlight || highlight[i]
        dim.array[i] = lit ? 0 : 1
        size.array[i] = sizes[i] * (highlight && lit ? 2.2 : 1) // lit points must read at any zoom
      }
      if (focus != null) size.array[focus] = sizes[focus] * 3.2
      dim.needsUpdate = size.needsUpdate = true
      if (colors) {
        let k = 0
        links.style((a, b) => {
          const idx = k++
          const rest = idx < forestCount ? LINK.rest : idx < forestCount + extraCount ? LINK.extra : LINK.similar
          if (focus != null && (a === focus || b === focus)) return LINK.focus
          if (!highlight) return rest
          return highlight[a] && highlight[b] ? LINK.lit : rest * LINK.greyout
        })
      }
      request()
    },
    flyTo(indices) {
      if (!indices?.length) return
      const box = new THREE.Box3()
      const v = new THREE.Vector3()
      for (const i of indices) box.expandByPoint(v.fromArray(atlas.positions, i * 3))
      const s = box.getBoundingSphere(new THREE.Sphere())
      // A single point: frame its neighbourhood (~6% of the atlas), not the whole thing.
      frameSphere(s.center, Math.max(s.radius, sphere.radius * 0.06), true)
    },
    home: () => frameSphere(sphere.center, sphere.radius, true),
    setLabels(list) {
      tags.set(list)
      request()
    },
    inset(px) {
      insetX = Math.min(px, host.clientWidth * 0.6)
      resize()
    },
    ring(i) {
      ring.place(i == null ? null : atlas.positions.subarray(i * 3, i * 3 + 3), i == null ? 0 : sizes[i])
      request()
    },
    dispose() {
      remember(viewKey, { camera: { position: camera.position.toArray(), target: controls.target.toArray() } })
      cancelAnimationFrame(frame)
      ro.disconnect()
      picker.dispose()
      controls.dispose()
      points.geometry.dispose()
      material.dispose()
      faint.material.dispose()
      ring.dispose()
      tags.dispose()
      links.dispose()
      renderer.dispose()
      renderer.domElement.remove()
    },
  }
}

function makePoints(atlas) {
  const n = atlas.positions.length / 3
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.BufferAttribute(atlas.positions, 3))
  geometry.setAttribute('color', new THREE.BufferAttribute(new Float32Array(n * 3).fill(0.8), 3))
  const sizes = atlas.sizes ?? pointScale(atlas.points.kind, atlas.points.size)
  geometry.setAttribute('size', new THREE.BufferAttribute(sizes.slice(), 1))
  geometry.setAttribute('dim', new THREE.BufferAttribute(new Float32Array(n), 1))
  const material = new THREE.ShaderMaterial({
    vertexShader,
    fragmentShader,
    uniforms: { scale: { value: 1 }, fadeNear: { value: 1 }, fadeFar: { value: 2 }, pass: { value: 0 } },
  })
  const solid = new THREE.Points(geometry, material)
  // Same geometry, same uniforms; only the pass flag and blending differ.
  const faint = new THREE.Points(
    geometry,
    new THREE.ShaderMaterial({
      vertexShader,
      fragmentShader,
      uniforms: { ...material.uniforms, pass: { value: 1 } },
      transparent: true,
      depthWrite: false,
    }),
  )
  faint.renderOrder = 1
  solid.add(faint)
  return { points: solid, material, sizes, faint }
}

/**
 * The ring around the hovered point (the atlas's renderHoveredPointRing): one
 * sprite drawn as a thin white annulus, sized from the point it surrounds.
 */
function makeRing(pointsMaterial) {
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(3), 3))
  const material = new THREE.ShaderMaterial({
    uniforms: { scale: pointsMaterial.uniforms.scale, size: { value: 1 } },
    vertexShader: /* glsl */ `
      uniform float scale;
      uniform float size;
      void main() {
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        gl_Position = projectionMatrix * mv;
        gl_PointSize = clamp(size * 1.9 * scale / -mv.z, 10.0, 64.0);
      }`,
    fragmentShader: /* glsl */ `
      void main() {
        float r = length(gl_PointCoord * 2.0 - 1.0);
        float a = smoothstep(0.72, 0.8, r) * (1.0 - smoothstep(0.92, 1.0, r));
        if (a < 0.01) discard;
        gl_FragColor = vec4(1.0, 1.0, 1.0, a * 0.95);
      }`,
    transparent: true,
    depthTest: false,
  })
  const points = new THREE.Points(geometry, material)
  points.visible = false
  points.renderOrder = 2
  return {
    points,
    place(xyz, size) {
      points.visible = !!xyz
      if (!xyz) return
      geometry.getAttribute('position').array.set(xyz)
      geometry.getAttribute('position').needsUpdate = true
      geometry.computeBoundingSphere()
      material.uniforms.size.value = size
    },
    dispose() {
      geometry.dispose()
      material.dispose()
    },
  }
}

const TAG_LIMIT = 12
const TAG_ZOOM = 0.85 // labels appear once the camera is closer than this share of the home view

/**
 * On-canvas labels for the biggest points (HTML over the canvas, so text stays
 * crisp). Greedy: most important first, skipped if it would overlap one
 * already placed, off screen, or behind the camera's target.
 */
function makeTags(host, P) {
  const layer = document.createElement('div')
  layer.className = styles.tags
  layer.setAttribute('aria-hidden', 'true')
  host.appendChild(layer)
  const pool = Array.from({ length: TAG_LIMIT }, () => layer.appendChild(document.createElement('span')))
  pool.forEach((el) => (el.className = styles.tag))
  let list = []
  const v = new THREE.Vector3()
  return {
    set(next) {
      list = next
    },
    place(camera, controls, homeDistance) {
      const dist = camera.position.distanceTo(controls.target)
      let used = 0
      if (dist < homeDistance * TAG_ZOOM) {
        const w = host.clientWidth
        const h = host.clientHeight
        // Panels floating over the canvas (marked data-atlas-panel) count as taken space.
        const origin = host.getBoundingClientRect()
        const boxes = [...(host.parentElement?.querySelectorAll('[data-atlas-panel]') ?? [])].map((el) => {
          const r = el.getBoundingClientRect()
          return [r.left - origin.left - 8, r.top - origin.top - 8, r.right - origin.left + 8, r.bottom - origin.top + 8]
        })
        for (const { i, text } of list) {
          if (used === TAG_LIMIT) break
          v.fromArray(P, i * 3)
          if (v.distanceTo(camera.position) > dist * 1.15) continue // far side of the focus
          v.project(camera)
          if (v.z > 1 || v.x < -1 || v.x > 1 || v.y < -1 || v.y > 1) continue
          const x = ((v.x + 1) / 2) * w
          const y = ((1 - v.y) / 2) * h
          const bw = Math.min(220, text.length * 6.6 + 16)
          const box = [x - bw / 2, y - 30, x + bw / 2, y - 8]
          if (boxes.some((b) => box[0] < b[2] && box[2] > b[0] && box[1] < b[3] && box[3] > b[1])) continue
          boxes.push(box)
          const el = pool[used++]
          el.textContent = text
          el.style.transform = `translate(${x}px, ${y - 12}px) translate(-50%, -100%)`
          el.style.display = 'block'
        }
      }
      for (let k = used; k < TAG_LIMIT; k++) pool[k].style.display = 'none'
    },
    dispose() {
      layer.remove()
    },
  }
}

/** Hover (one raycast per frame at most) and click-without-drag selection. */
function makePicker(el, camera, points, handlers, distance) {
  const ray = new THREE.Raycaster()
  const ndc = new THREE.Vector2()
  let pending = null
  let down = null
  const pick = (e) => {
    const r = el.getBoundingClientRect()
    ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1)
    ray.params.Points.threshold = distance() * 0.005
    ray.setFromCamera(ndc, camera)
    const hit = ray.intersectObject(points, false)[0]
    return hit ? hit.index : null
  }
  const move = (e) => {
    if (pending) return
    pending = requestAnimationFrame(() => {
      pending = null
      handlers.current.onHover?.(pick(e), { x: e.clientX, y: e.clientY })
    })
  }
  const pdown = (e) => (down = { x: e.clientX, y: e.clientY })
  const pup = (e) => {
    if (down && Math.hypot(e.clientX - down.x, e.clientY - down.y) < 5) handlers.current.onSelect?.(pick(e))
    down = null
  }
  const leave = () => handlers.current.onHover?.(null, null)
  el.addEventListener('pointermove', move)
  el.addEventListener('pointerdown', pdown)
  el.addEventListener('pointerup', pup)
  el.addEventListener('pointerleave', leave)
  return {
    dispose() {
      cancelAnimationFrame(pending)
      el.removeEventListener('pointermove', move)
      el.removeEventListener('pointerdown', pdown)
      el.removeEventListener('pointerup', pup)
      el.removeEventListener('pointerleave', leave)
    },
  }
}

/** Bounding sphere of the points between the lo and hi quantiles on each axis. */
function quantileSphere(P, lo, hi) {
  const n = P.length / 3
  const box = new THREE.Box3()
  const axis = new Float32Array(n)
  for (let d = 0; d < 3; d++) {
    for (let i = 0; i < n; i++) axis[i] = P[i * 3 + d]
    axis.sort()
    box.min.setComponent(d, axis[Math.floor(lo * (n - 1))])
    box.max.setComponent(d, axis[Math.floor(hi * (n - 1))])
  }
  return box.getBoundingSphere(new THREE.Sphere())
}

/**
 * Median distance from a sample of points to their nearest neighbour: the
 * data's own grain. Sampled (≤ 400 × ≤ 20k) so it stays fast at 176k points.
 */
function typicalSpacing(P) {
  const n = P.length / 3
  if (n < 2) return 1
  const step = Math.max(1, Math.floor(n / 20000))
  const probes = Math.min(400, n)
  const out = []
  for (let k = 0; k < probes; k++) {
    const i = Math.floor((k * n) / probes)
    let best = Infinity
    for (let j = 0; j < n; j += step) {
      if (j === i) continue
      const dx = P[i * 3] - P[j * 3]
      const dy = P[i * 3 + 1] - P[j * 3 + 1]
      const dz = P[i * 3 + 2] - P[j * 3 + 2]
      const d = dx * dx + dy * dy + dz * dz
      if (d > 0 && d < best) best = d
    }
    if (best < Infinity) out.push(Math.sqrt(best))
  }
  out.sort((a, b) => a - b)
  // Subsampling overestimates the gap by about the cube root of the step.
  return (out[out.length >> 1] ?? 1) / Math.cbrt(step)
}
