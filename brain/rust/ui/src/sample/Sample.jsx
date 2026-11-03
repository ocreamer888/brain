import { useEffect, useRef, useState } from 'react'
import Dock from '../components/brand/Dock'
import GlowHero from '../components/brand/GlowHero'
import MemoryRow from '../components/brand/MemoryRow'
import RankedBars from '../components/brand/RankedBars'
import RunStrip from '../components/brand/RunStrip'
import Tile from '../components/brand/Tile'
import Icon, { ICON_NAMES } from '../components/brand/Icon'
import {
  Button,
  FilterChip,
  LiveDot,
  SearchPill,
  SignalChip,
  TypeChip,
} from '../components/brand/primitives'
import { MEMORY_SIGNALS, MEMORY_TYPES } from '../lib/memorySignals'
import { SAMPLE_MEMORIES, SAMPLE_RUNS, SAMPLE_STATS } from './sampleData'
import s from './Sample.module.css'

// The real app follows the system only (HIG: no app-level appearance switch).
// This preview switch exists so both modes can be judged side by side.
const MODES = ['system', 'light', 'dark']

export default function Sample() {
  const [mode, setMode] = useState('system')
  return (
    <div data-theme={mode === 'system' ? undefined : mode} className={s.page}>
      <header className={s.top}>
        <p className={s.wordmark}>brain</p>
        <div className={`glass ${s.modes}`} role="group" aria-label="Preview appearance">
          {MODES.map((m) => (
            <button key={m} type="button" aria-pressed={mode === m} onClick={() => setMode(m)} className={`pressable ${s.mode}`}>
              {m}
            </button>
          ))}
        </div>
      </header>
      <main className={s.main}>
        <ShellPreview />
        <ColorRoles />
        <TypeScale />
        <Signals />
        <Controls />
      </main>
    </div>
  )
}

function Section({ title, note, children }) {
  return (
    <section>
      <h2 className={`t-h1 ${s.title}`}>{title}</h2>
      {note && <p className={`t-body ${s.note}`}>{note}</p>}
      <div className={s.body}>{children}</div>
    </section>
  )
}

const fmt = new Intl.NumberFormat('en-US')

function ShellPreview() {
  const [view, setView] = useState('dashboard')
  const [type, setType] = useState('all')
  const [query, setQuery] = useState('')
  const st = SAMPLE_STATS
  const rows = SAMPLE_MEMORIES.filter(
    (m) => (type === 'all' || m.memory_type === type) && m.snippet.toLowerCase().includes(query.toLowerCase()),
  )
  return (
    <Section title="Shell and dashboard" note="Composition from the ui/ references: one floating panel, a bento with one glow, tiles with one idea each, a list below. Counts and eval runs are a real snapshot of the live API (2026-10-18); memory rows are placeholder.">
      <div className={s.shell}>
        <div className={s.dockSlot}>
          <Dock active={view} onSelect={setView} />
        </div>
        <div className={s.scroller}>
          <header className={`glass ${s.header}`}>
            <div className={s.heading}>
              <h1 className={`t-h1 ${s.title}`}>Dashboard</h1>
              <p className={`t-small ${s.secondary}`}>{st.active_instance.name} brain · {fmt.format(st.total_memories)} memories</p>
            </div>
            <div className={s.tools}>
              <SearchPill value={query} onChange={setQuery} />
              <span className={`glass ${s.pill}`}>
                <LiveDot />
              </span>
              <span className={`glass ${s.pill}`}>
                <span className={s.monogram} aria-hidden>{st.active_instance.name[0]}</span>
                <span className="t-small">{st.active_instance.name}</span>
              </span>
            </div>
          </header>
          <div className={s.bento}>
            <div className={s.areaHero}>
              <GlowHero
                label="Total memories"
                value={fmt.format(st.total_memories)}
                stats={[
                  { label: 'sessions', value: fmt.format(st.total_sessions) },
                  { label: 'saved this session', value: fmt.format(st.save_count_this_session) },
                  { label: 'feedback events', value: fmt.format(st.feedback_events_total) },
                ]}
                onOpen={() => setView('search')}
                openLabel="Open search"
              />
            </div>
            <Tile className={s.areaMix} icon="layers" title="What it keeps" sub="Memories by type" onOpen={() => setView('search')}>
              <RankedBars counts={st.by_type} />
            </Tile>
            <section className={`${s.panel} ${s.areaList}`}>
              <div className={s.listHead}>
                <div>
                  <h3 className={`t-h2 ${s.title}`}>Latest</h3>
                  <p className={`t-small ${s.secondary}`}>{rows.length} of {SAMPLE_MEMORIES.length} · newest first</p>
                </div>
              </div>
              <div className={s.chips}>
                <FilterChip selected={type === 'all'} onClick={() => setType('all')}>All</FilterChip>
                {MEMORY_TYPES.map((t) => (
                  <FilterChip key={t} selected={type === t} icon={MEMORY_SIGNALS[t].icon} onClick={() => setType(t)}>
                    {MEMORY_SIGNALS[t].label}
                  </FilterChip>
                ))}
              </div>
              <ul className={s.rows}>
                {rows.map((m) => (
                  <MemoryRow key={m.id} memory={m} />
                ))}
              </ul>
              {rows.length === 0 && <p className={`t-body ${s.empty}`}>Nothing matches.</p>}
            </section>
            <Tile className={s.areaEval} icon="eval" title="Eval" sub="Last 14 scored runs" onOpen={() => setView('eval')}>
              <div className={s.evalHead}>
                <p className="t-kpi">
                  {SAMPLE_RUNS.filter((r) => r.pass).length}
                  <span className={s.unit}>/{SAMPLE_RUNS.length} passed</span>
                </p>
                <SignalChip signal="use" icon="decision">pass</SignalChip>
              </div>
              <p className={`t-small ${s.secondary}`}>
                Latest P@1 <span className="t-mono">{SAMPLE_RUNS.at(-1).p1.toFixed(2)}</span>
              </p>
              <div className={s.evalStrip}>
                <RunStrip runs={SAMPLE_RUNS} />
              </div>
            </Tile>
          </div>
        </div>
      </div>
    </Section>
  )
}

const ROLES = [
  ['--fg-primary', 'primary', 'Headings, primary text'],
  ['--fg-body', 'body', 'Memory text'],
  ['--fg-secondary', 'secondary', 'Meta, labels, helper'],
  ['--fg-tertiary', 'tertiary', 'Icons, placeholder only (3:1 floor)'],
  ['--accent-text', 'accent text', 'Links, active icon'],
  ['--lamp-text', 'lamp text', 'A warm sentence'],
]
const SURFACES = ['--bg-ground', '--bg-surface', '--bg-raised']

function ColorRoles() {
  return (
    <Section title="Color roles" note="Contrast is measured live from the rendered colors, so these numbers are what the browser actually paints in the current mode. Text needs 4.5:1; HIG asks for 7:1 on small custom text.">
      <div className={`${s.panel} ${s.tableWrap}`}>
        <table className={s.table}>
          <thead>
            <tr className="t-label">
              <th>Role</th>
              {SURFACES.map((bg) => (
                <th key={bg}>on {bg.replace('--bg-', '')}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ROLES.map(([v, name, use]) => (
              <tr key={v}>
                <td>
                  <p className={s.roleName}>{name}</p>
                  <p className={`t-small ${s.secondary}`}>{use}</p>
                </td>
                {SURFACES.map((bg) => (
                  <ContrastCell key={bg} fg={v} bg={bg} floor={name === 'tertiary' ? 3 : 4.5} />
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  )
}

function ContrastCell({ fg, bg, floor }) {
  const ref = useRef(null)
  const ratio = useContrast(ref)
  return (
    <td>
      <div ref={ref} style={{ color: `var(${fg})`, background: `var(${bg})` }} className={s.swatch}>
        <span className={s.aa}>Aa</span>
        <span className="t-mono">{ratio ? `${ratio.toFixed(1)}:1` : '—'}</span>
      </div>
      {ratio && ratio < floor && <span className={`t-small ${s.below}`}>below {floor}:1</span>}
    </td>
  )
}

// Re-measures on mode change: color-scheme flips repaint, so observe the root attribute and media query.
function useContrast(ref) {
  const [ratio, setRatio] = useState(null)
  useEffect(() => {
    const measure = () => {
      const cs = getComputedStyle(ref.current)
      setRatio(contrast(cs.color, cs.backgroundColor))
    }
    measure()
    const mq = matchMedia('(prefers-color-scheme: dark)')
    const mo = new MutationObserver(measure)
    mo.observe(document.body, { attributes: true, subtree: true, attributeFilter: ['data-theme'] })
    mq.addEventListener('change', measure)
    return () => {
      mo.disconnect()
      mq.removeEventListener('change', measure)
    }
  }, [ref])
  return ratio
}

function contrast(a, b) {
  const lum = (c) => {
    const [r, g, bl] = c.match(/[\d.]+/g).slice(0, 3).map((x) => {
      const v = Number(x) / 255
      return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4
    })
    return 0.2126 * r + 0.7152 * g + 0.0722 * bl
  }
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

const TYPE_SPECIMENS = [
  ['t-display', 'Display', '12,480'],
  ['t-kpi', 'KPI number', '3,912'],
  ['t-h1', 'H1 · screen title', 'Search'],
  ['t-h2', 'H2 · panel title', 'Linked memories'],
  ['t-body', 'Body · memory text', 'Follow the system appearance. Roles are declared once, so components never branch on theme, and a long read stays comfortable at 14px with 1.55 leading.'],
  ['t-small', 'Small · meta', 'brain · 2026-10-18'],
  ['t-label', 'Label', 'Total memories'],
  ['t-mono', 'Mono · ids, scores', '#a1f3c9e2 · 0.842'],
]

function TypeScale() {
  return (
    <Section title="Type" note="Geist and Geist Mono, self-hosted. Sizes are in rem so they grow with the browser's text size. Display is Regular (400): HIG advises against Light weights.">
      <div className={s.panel}>
        {TYPE_SPECIMENS.map(([cls, name, text]) => (
          <div key={cls} className={s.specimen}>
            <p className={`t-small ${s.secondary}`}>{name}</p>
            <p className={`${cls} ${s.specimenText}`}>{text}</p>
          </div>
        ))}
      </div>
    </Section>
  )
}

function Signals() {
  return (
    <Section title="Memory types and states" note="Seven signals instead of eight rainbow hues. Every chip carries color, icon, and word. Episode is dashed: source tape, not a durable claim.">
      <div className={`${s.panel} ${s.padded}`}>
        <div className={s.row}>
          {MEMORY_TYPES.map((t) => (
            <TypeChip key={t} type={t} />
          ))}
        </div>
        <div className={s.row}>
          <LiveDot />
          <LiveDot state="reconnecting" />
          <SignalChip signal="use" icon="decision">pass</SignalChip>
          <SignalChip signal="fail" icon="close">fail</SignalChip>
          <span className={`t-mono ${s.gain}`}>↑ +2.1 vs baseline</span>
          <span className={`t-mono ${s.regression}`}>↓ −1.4 regression</span>
          <span className={`t-mono ${s.secondary}`}>→ no change</span>
        </div>
      </div>
    </Section>
  )
}

function Controls() {
  return (
    <Section title="Controls and icons" note="One primary (the lamp) per screen. Press feedback happens on pointer-down. Targets are 36px with a mouse and 44px on touch.">
      <div className={`${s.panel} ${s.padded}`}>
        <div className={s.row}>
          <Button variant="primary" icon="add">New instance</Button>
          <Button icon="filter">Filter</Button>
          <Button>Cancel</Button>
          <Button disabled>Disabled</Button>
        </div>
        <div className={s.icons}>
          {ICON_NAMES.map((n) => (
            <div key={n} className={s.icon}>
              <Icon name={n} size={24} />
              <span className="t-small">{n}</span>
            </div>
          ))}
        </div>
      </div>
    </Section>
  )
}
