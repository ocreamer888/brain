import * as THREE from 'three'

// Links drawn the way cosmos.gl draws them (read from its shaders, 2026-10-19):
// a rational quadratic Bézier (weight 0.8) whose control point sits at the
// midpoint pushed sideways by half the link's length, in the plane facing the
// camera, so a link looks curved from every angle; 19 segments; width scales
// with zoom; links fade to 25% opacity as their on-screen length goes from
// 50 to 150 px (long sweeps become faint hairs). Colour runs end to end.
export const RIBBON = {
  segments: 19,
  weight: 0.8,
  controlPointDistance: 0.5,
  fadeFromPx: 50,
  fadeToPx: 150,
  fadeMin: 0.25,
  minPx: 0.6,
  maxPx: 6,
}

/**
 * Flat point-index pairs: the forest edges, plus any extra tiers that have
 * something in them. `edges` may be a Uint32Array (ReferenceAtlas's binary
 * geometry has no .concat) rather than a plain array (the memory atlas's
 * JSON edges) -- spread handles both. Skips building a new array when
 * there's nothing to add, so the common one-tier case is a plain pass-through.
 */
export function concatPairs(edges, extra, similar) {
  if (!extra?.length && !similar?.length) return edges
  return [...edges, ...(extra ?? []), ...(similar ?? [])]
}

const vertexShader = /* glsl */ `
  attribute float side;     // -1 / +1 across the ribbon
  attribute float t;        // 0..1 along the link
  attribute vec3 aStart;
  attribute vec3 aEnd;
  attribute vec3 aColorStart;
  attribute vec3 aColorEnd;
  attribute float aAlpha;
  uniform vec3 camForward;
  uniform vec2 viewport;    // drawing buffer size in pixels
  uniform float pixelRatio;
  uniform float pxScale;    // pixels per world unit at depth 1
  uniform float worldWidth;
  varying vec4 vColor;

  vec3 conic(vec3 A, vec3 B, vec3 C, float s, float w) {
    vec3 num = (1.0 - s) * (1.0 - s) * A + 2.0 * (1.0 - s) * s * w * C + s * s * B;
    float den = (1.0 - s) * (1.0 - s) + 2.0 * (1.0 - s) * s * w + s * s;
    return num / den;
  }
  vec2 toPx(vec4 clip) { return (clip.xy / clip.w * 0.5 + 0.5) * viewport; }

  void main() {
    vec3 dir = aEnd - aStart;
    vec3 bend = cross(camForward, dir);
    if (dot(bend, bend) < 1e-6) bend = cross(dir, vec3(0.0, 1.0, 0.0));
    if (dot(bend, bend) < 1e-6) bend = vec3(1.0, 0.0, 0.0);
    vec3 ctrl = (aStart + aEnd) * 0.5 + normalize(bend) * length(dir) * ${RIBBON.controlPointDistance.toFixed(2)};

    mat4 mvp = projectionMatrix * modelViewMatrix;
    float dt = t < 0.999 ? 0.01 : -0.01;
    vec4 c0 = mvp * vec4(conic(aStart, aEnd, ctrl, t, ${RIBBON.weight.toFixed(2)}), 1.0);
    vec4 c1 = mvp * vec4(conic(aStart, aEnd, ctrl, t + dt, ${RIBBON.weight.toFixed(2)}), 1.0);
    if (c0.w <= 0.0 || c1.w <= 0.0) { gl_Position = vec4(2.0, 2.0, 2.0, 1.0); vColor = vec4(0.0); return; }

    vec2 d = toPx(c1) - toPx(c0);
    if (dt < 0.0) d = -d;
    vec2 normal = length(d) > 1e-5 ? normalize(vec2(-d.y, d.x)) : vec2(0.0, 1.0);
    float widthPx = clamp(worldWidth * pxScale / c0.w, ${RIBBON.minPx.toFixed(1)} * pixelRatio, ${RIBBON.maxPx.toFixed(1)} * pixelRatio);
    c0.xy += normal * side * widthPx / viewport * c0.w;  // half width each side, in clip space
    gl_Position = c0;

    // Long on screen → faint, measured in CSS pixels like cosmos.gl.
    vec4 ca = mvp * vec4(aStart, 1.0);
    vec4 cb = mvp * vec4(aEnd, 1.0);
    float lenPx = (ca.w > 0.0 && cb.w > 0.0) ? length(toPx(cb) - toPx(ca)) / pixelRatio : 0.0;
    float fade = mix(1.0, ${RIBBON.fadeMin.toFixed(2)}, smoothstep(${RIBBON.fadeFromPx.toFixed(1)}, ${RIBBON.fadeToPx.toFixed(1)}, lenPx));
    vColor = vec4(mix(aColorStart, aColorEnd, t), aAlpha * fade);
  }
`
const fragmentShader = /* glsl */ `
  varying vec4 vColor;
  void main() {
    if (vColor.a < 0.004) discard;
    gl_FragColor = vColor;
  }
`

/**
 * All links as one instanced mesh. `pairs`: flat [a, b, …] point indices,
 * `positions`: Float32Array xyz per point. Colours and alpha are set later.
 */
export function makeRibbons(pairs, positions, worldWidth) {
  const count = pairs.length / 2
  const S = RIBBON.segments
  const base = new THREE.InstancedBufferGeometry()
  const t = new Float32Array((S + 1) * 2)
  const side = new Float32Array((S + 1) * 2)
  for (let i = 0; i <= S; i++) {
    t[i * 2] = t[i * 2 + 1] = i / S
    side[i * 2] = -1
    side[i * 2 + 1] = 1
  }
  const index = []
  for (let i = 0; i < S; i++) {
    const a = i * 2
    index.push(a, a + 1, a + 2, a + 1, a + 3, a + 2)
  }
  base.setIndex(index)
  base.setAttribute('position', new THREE.BufferAttribute(new Float32Array((S + 1) * 2 * 3), 3)) // unused, required by three
  base.setAttribute('t', new THREE.BufferAttribute(t, 1))
  base.setAttribute('side', new THREE.BufferAttribute(side, 1))

  const start = new Float32Array(count * 3)
  const end = new Float32Array(count * 3)
  for (let k = 0; k < count; k++) {
    start.set(positions.subarray(pairs[2 * k] * 3, pairs[2 * k] * 3 + 3), k * 3)
    end.set(positions.subarray(pairs[2 * k + 1] * 3, pairs[2 * k + 1] * 3 + 3), k * 3)
  }
  const colorStart = new THREE.InstancedBufferAttribute(new Float32Array(count * 3), 3)
  const colorEnd = new THREE.InstancedBufferAttribute(new Float32Array(count * 3), 3)
  const alpha = new THREE.InstancedBufferAttribute(new Float32Array(count), 1)
  base.setAttribute('aStart', new THREE.InstancedBufferAttribute(start, 3))
  base.setAttribute('aEnd', new THREE.InstancedBufferAttribute(end, 3))
  base.setAttribute('aColorStart', colorStart)
  base.setAttribute('aColorEnd', colorEnd)
  base.setAttribute('aAlpha', alpha)
  base.instanceCount = count

  const material = new THREE.ShaderMaterial({
    vertexShader,
    fragmentShader,
    transparent: true,
    depthWrite: false,
    side: THREE.DoubleSide,
    uniforms: {
      camForward: { value: new THREE.Vector3(0, 0, -1) },
      viewport: { value: new THREE.Vector2(1, 1) },
      pixelRatio: { value: 1 },
      pxScale: { value: 1 },
      worldWidth: { value: worldWidth },
    },
  })
  const mesh = new THREE.Mesh(base, material)
  mesh.frustumCulled = false // instances span the whole atlas

  return {
    mesh,
    /** Colour each link from its endpoints' colours (rgb per point). */
    paint(pointColors) {
      for (let k = 0; k < count; k++) {
        colorStart.array.set(pointColors.subarray(pairs[2 * k] * 3, pairs[2 * k] * 3 + 3), k * 3)
        colorEnd.array.set(pointColors.subarray(pairs[2 * k + 1] * 3, pairs[2 * k + 1] * 3 + 3), k * 3)
      }
      colorStart.needsUpdate = colorEnd.needsUpdate = true
    },
    /** alphaOf(a, b) → opacity for the link between points a and b. */
    style(alphaOf) {
      for (let k = 0; k < count; k++) alpha.array[k] = alphaOf(pairs[2 * k], pairs[2 * k + 1])
      alpha.needsUpdate = true
    },
    /** Per frame: camera direction (for the bend) and screen metrics. */
    frame(camera, renderer, pxScale) {
      camera.getWorldDirection(material.uniforms.camForward.value)
      renderer.getDrawingBufferSize(material.uniforms.viewport.value)
      material.uniforms.pixelRatio.value = renderer.getPixelRatio()
      material.uniforms.pxScale.value = pxScale
    },
    dispose() {
      base.dispose()
      material.dispose()
    },
  }
}
