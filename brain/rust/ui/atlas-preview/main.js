import { Graph } from '@cosmograph/cosmos'

const TYPE_COLOR = {
  fact: [0.96, 0.77, 0.26, 0.95],
  knowledge: [0.94, 0.64, 0.01, 0.95],
  decision: [0.24, 0.55, 1, 0.95],
  solution: [0.18, 0.77, 0.71, 0.95],
  pattern: [0.91, 0.36, 0.02, 0.95],
  error_lesson: [0.9, 0.22, 0.27, 0.95],
  conversation: [0.61, 0.36, 0.9, 0.92],
  project_context: [0.5, 0.93, 0.6, 0.92],
  episode: [0.55, 0.6, 0.68, 0.85],
  unknown: [0.77, 0.8, 0.84, 0.8],
}

const summary = document.querySelector('#summary')
const pill = document.querySelector('#pill')
const raw = await fetch('/graph.json?v=25').then((response) => response.json())

const indexOf = new Map(raw.points.map((point, index) => [point.id, index]))
const projects = [...new Set(raw.points.map((point) => point.project))]
const projectIndex = new Map(projects.map((project, index) => [project, index]))

const projectColor = new Map(
  projects.map((project, index) => {
    const hue = (index * 137.508) % 360
    const s = 0.78
    const l = 0.56
    const a = s * Math.min(l, 1 - l)
    const channel = (n) => {
      const k = (n + hue / 30) % 12
      return l - a * Math.max(Math.min(k - 3, 9 - k, 1), -1)
    }
    return [project, [channel(0), channel(8), channel(4), 1]]
  }),
)
const positions = new Float32Array(raw.points.length * 3)
const colors = new Float32Array(raw.points.length * 4)
const sizes = new Float32Array(raw.points.length)
const reachLog = raw.points.map((point) => Math.log1p(point.reach))
const minLog = Math.min(...reachLog)
const maxLog = Math.max(...reachLog)
const span = maxLog - minLog || 1

raw.points.forEach((point, index) => {
  positions[index * 3] = point.x
  positions[index * 3 + 1] = point.y
  positions[index * 3 + 2] = point.z
  colors.set(projectColor.get(point.project), index * 4)
  sizes[index] = 6 + ((reachLog[index] - minLog) / span) * 4
})

const linkPairs = []
for (const link of raw.links) {
  const source = indexOf.get(link.source)
  const target = indexOf.get(link.target)
  if (source == null || target == null) continue
  linkPairs.push(source, target)
}

function show(index, event) {
  if (index == null || index < 0) {
    pill.style.display = 'none'
    return
  }
  const point = raw.points[index]
  pill.textContent = point.label || point.project
  if (event && event.clientX != null) {
    pill.style.left = `${event.clientX + 14}px`
    pill.style.top = `${event.clientY - 28}px`
    pill.style.transform = 'none'
  }
  pill.style.display = 'block'
}

const graph = new Graph(document.querySelector('#graph'), {
  spaceDimensions: 3,
  pointSphereShading: true,
  pointDepthFade: 0.15,
  cameraFov: 55,
  scalePointsOnZoom: true,
  backgroundColor: '#121820',
  curvedLinks: true,
  linkColorInterpolateFromEndpoints: true,
  linkBlending: true,
  linkDefaultWidth: 1,
  linkWidthScale: 2.95,
  scaleLinksOnZoom: true,
  linkOpacity: 0.8,
  fitViewOnInit: true,
  fitViewDelay: 600,
  fitViewPadding: 0.2,
  enableDrag: false,
  enableSimulation: false,
  rescalePositions: false,
  onPointMouseOver: (index, _position, event) => show(index, event),
  onPointMouseOut: () => show(null),
  onClick: (index, _position, event) => show(index, event),
})

graph.setPointPositions(positions, { dimensions: 3 })
graph.setPointColors(colors)
graph.setPointSizes(sizes)
graph.setLinks(new Float32Array(linkPairs))
graph.render()

graph.ready.then(() => {
  setTimeout(() => {
    const camera = graph.getCameraState()
    if (!camera) return
    graph.setCameraState({
      target: camera.target,
        distance: camera.distance * 0.85,
        azimuth: 0.4,
        polar: 0.7,
    }, 0)
  }, 900)
})

summary.textContent = `${raw.points.length.toLocaleString()} memories · ${raw.links.length.toLocaleString()} links · ${projects.length} projects. Drag to orbit. Scroll to move in.`
