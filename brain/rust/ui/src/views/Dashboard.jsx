import { useEffect, useMemo, useState } from 'react'
import { getObservations, getTopEntities, listMemories } from '../api'
import DailyBars from '../components/brand/DailyBars'
import EntityChips from '../components/brand/EntityChips'
import GlowHero from '../components/brand/GlowHero'
import MemoryRow from '../components/brand/MemoryRow'
import RankedBars, { NameLabel } from '../components/brand/RankedBars'
import RunStrip from '../components/brand/RunStrip'
import Spotlight from '../components/brand/Spotlight'
import Tile from '../components/brand/Tile'
import { Button, FilterChip, Segmented, SignalChip } from '../components/brand/primitives'
import { useEval } from '../context/EvalContext'
import { useFeed } from '../context/FeedContext'
import { useStats } from '../context/StatsContext'
import { recentCount, summarizeActivity } from '../lib/activity'
import { sourceName } from '../lib/sources'
import { summarizeRuns } from '../lib/evalRuns'
import { useLoad } from '../lib/useLoad'
import { MEMORY_SIGNALS, MEMORY_TYPES } from '../lib/memorySignals'
import styles from './Dashboard.module.css'

const fmt = new Intl.NumberFormat('en-US')
const num = (v) => (typeof v === 'number' ? fmt.format(v) : '—')
const PAGE = 6
// Newest memories pulled to count the last two weeks (~1.5 MB, ~0.2 s locally).
// Replace with a server-side daily count when the API has one.
const ACTIVITY_SAMPLE = 2000
const RANGES = [
  { value: 7, label: '7d' },
  { value: 14, label: '14d' },
  { value: 30, label: '30d' },
]
const TOP_ENTITIES = 14

export default function Dashboard({ onNavigate, onOpenMemory, onOpenEntity }) {
  const { stats, error, refetch } = useStats()
  const { feed } = useFeed()
  const recent = useLoad(async () => (await listMemories(ACTIVITY_SAMPLE)).items || [], 'recent')
  const [days, setDays] = useState(14)
  const activity = useMemo(() => (recent.data ? summarizeActivity(recent.data, days) : null), [recent.data, days])
  const facts = useMemo(() => (recent.data ? recentCount(recent.data, 'fact') : null), [recent.data])
  const decision = useLatest('decision')
  const lesson = useLatest('error_lesson')

  // Counts follow the live feed: a new memory arriving means the totals moved.
  useEffect(() => {
    if (feed?.length) refetch?.()
  }, [feed?.[0]?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className={styles.bento}>
      <div className={styles.hero}>
        <GlowHero
          label="Total memories"
          value={num(stats?.total_memories)}
          stats={[
            { label: 'sessions', value: num(stats?.total_sessions) },
            { label: 'saved this session', value: num(stats?.save_count_this_session) },
            { label: 'feedback events', value: num(stats?.feedback_events_total) },
          ]}
          onOpen={() => onNavigate('search')}
          openLabel="Open search"
        />
      </div>
      <Tile className={styles.mix} icon="layers" title="What it keeps" sub="Memories by type" onOpen={() => onNavigate('search')} openLabel="Open search">
        {error && <StatsError message={error} onRetry={refetch} />}
        {!error && !stats && <p className={`t-small ${styles.secondary}`}>Loading counts…</p>}
        {stats?.by_type && <RankedBars counts={stats.by_type} />}
      </Tile>
      <TopEntities onOpen={onOpenEntity} onOpenAll={() => onNavigate('linked')} />
      <SourcesTile recent={recent} a={activity} days={days} />
      <ActivityTile recent={recent} a={activity} days={days} onDays={setDays} />
      <NewFactsTile recent={recent} counts={facts} onReview={() => onNavigate('curate')} />
      <EvalTile onOpen={() => onNavigate('eval')} />
      <Latest feed={feed} onOpen={onOpenMemory} onSearch={() => onNavigate('search')} />
      <aside className={styles.side} aria-label="Highlights">
        <Spotlight icon="decision" title="Latest decision" state={decision} onOpen={onOpenMemory} />
        <Spotlight icon="lesson" title="Latest lesson" state={lesson} onOpen={onOpenMemory} />
        <ProjectsTile recent={recent} a={activity} days={days} onOpen={() => onNavigate('search')} />
      </aside>
    </div>
  )
}

function StatsError({ message, onRetry }) {
  return (
    <div className={`t-small ${styles.error}`} role="alert">
      <span>Couldn't load counts ({message}).</span>
      <Button onClick={onRetry}>Retry</Button>
    </div>
  )
}

function Latest({ feed, onOpen, onSearch }) {
  const [type, setType] = useState('all')
  const [limit, setLimit] = useState(PAGE)
  const matching = feed.filter((e) => type === 'all' || e.memory_type === type)
  const rows = matching.slice(0, limit)
  return (
    <section className={`${styles.panel} ${styles.list}`}>
      <div className={styles.listHead}>
        <h3 className={`t-h2 ${styles.title}`}>Latest</h3>
        <p className={`t-small ${styles.secondary}`}>
          {rows.length} of {matching.length} · newest first, live
        </p>
      </div>
      <div className={styles.chips}>
        <FilterChip selected={type === 'all'} onClick={() => setType('all')}>All</FilterChip>
        {MEMORY_TYPES.map((t) => (
          <FilterChip key={t} selected={type === t} icon={MEMORY_SIGNALS[t].icon} onClick={() => setType(t)}>
            {MEMORY_SIGNALS[t].label}
          </FilterChip>
        ))}
      </div>
      {feed.length === 0 && <p className={`t-body ${styles.note}`}>Waiting for new memories…</p>}
      {feed.length > 0 && rows.length === 0 && (
        <p className={`t-body ${styles.note}`}>No {MEMORY_SIGNALS[type]?.label ?? type} memories in the recent feed.</p>
      )}
      <ul className={styles.rows}>
        {rows.map((e, i) => (
          <MemoryRow
            key={`${e.id}-${e.timestamp || i}`}
            memory={{ id: e.id, memory_type: e.memory_type, project: e.project, timestamp: e.timestamp, snippet: e.content_snippet }}
            onOpen={onOpen}
          />
        ))}
      </ul>
      <div className={styles.more}>
        {matching.length > rows.length && (
          <Button onClick={() => setLimit((n) => n + PAGE)}>Show {Math.min(PAGE, matching.length - rows.length)} more</Button>
        )}
        <Button icon="search" onClick={onSearch}>
          Search all
        </Button>
      </div>
    </section>
  )
}

/** Newest memory of a type, with its full metadata (titles live there, not in /list). */
function useLatest(memoryType) {
  return useLoad(async () => {
    const item = (await listMemories(1, { memoryType })).items?.[0]
    if (!item) return null
    return (await getObservations([item.id])).results?.[0] ?? null
  }, memoryType)
}

const quiet = (text) => <p className={`t-small ${styles.secondary}`}>{text}</p>

/** What the brain knows about most: entities ranked by how many memories mention them. */
function TopEntities({ onOpen, onOpenAll }) {
  const top = useLoad(async () => (await getTopEntities(TOP_ENTITIES)).entities || [], 'top-entities')
  return (
    <Tile
      className={styles.entities}
      icon="linked"
      title="What it knows about"
      sub="Most-linked entities · memories that mention each"
      onOpen={onOpenAll}
      openLabel="Open Linked"
    >
      {top.loading && !top.data && quiet('Loading entities…')}
      {top.error && <StatsError message={top.error} onRetry={top.retry} />}
      {top.data?.length === 0 && quiet('Nothing linked yet.')}
      {top.data?.length > 0 && <EntityChips entities={top.data} onOpen={onOpen} />}
    </Tile>
  )
}

/** Saves per day over the chosen range, counted from the newest memories. */
function ActivityTile({ recent, a, days, onDays }) {
  return (
    <Tile
      className={styles.activity}
      icon="bars"
      title="Activity"
      sub={a ? `${fmt.format(a.total)} saved in the last ${days} days${a.complete ? '' : ' (at least)'}` : 'Saved per day'}
      actions={<Segmented label="Time range for Activity and Active projects" options={RANGES} value={days} onChange={onDays} />}
    >
      {recent.error && <StatsError message={recent.error} onRetry={recent.retry} />}
      {recent.loading && !a && quiet('Loading activity…')}
      {a && <DailyBars days={a.days} />}
      {a && !a.complete && quiet(`Only the newest ${fmt.format(ACTIVITY_SAMPLE)} memories were counted; earlier days may be low.`)}
    </Tile>
  )
}

/**
 * Facts that came in this week, and the way to look at them. Curate has no
 * review queue, so this counts arrivals, not "pending": an honest number.
 */
function NewFactsTile({ recent, counts, onReview }) {
  return (
    <Tile className={styles.facts} icon="fact" title="New facts" sub="Saved in the last 7 days">
      {recent.loading && !counts && quiet('Counting…')}
      {recent.error && quiet("Couldn't count new facts.")}
      {counts && (
        <div className={styles.factsBody}>
          <p className={`t-kpi ${styles.title}`}>
            {fmt.format(counts.week)}
            {!counts.complete && <span className={styles.unit}> at least</span>}
          </p>
          <p className={`t-small ${styles.secondary}`}>{fmt.format(counts.today)} saved today</p>
          <div className={styles.factsAction}>
            <Button variant="primary" icon="curate" onClick={onReview}>
              Review newest
            </Button>
          </div>
        </div>
      )}
    </Tile>
  )
}

/** Where those saves came from, same window as Activity. */
function SourcesTile({ recent, a, days }) {
  return (
    <Tile
      className={styles.sources}
      icon="inbox"
      title="Sources"
      sub={`Where memories came from · last ${days} days${a && !a.complete ? ' (at least)' : ''}`}
    >
      {recent.loading && !a && quiet('Loading sources…')}
      {recent.error && quiet("Couldn't load sources.")}
      {a && Object.keys(a.sources).length === 0 && quiet('Nothing saved in this window.')}
      {a && Object.keys(a.sources).length > 0 && (
        <RankedBars counts={a.sources} label={(k) => NameLabel(sourceName(k))} nameOf={sourceName} noun="saved" />
      )}
    </Tile>
  )
}

/** Projects behind those saves, same window. */
function ProjectsTile({ recent, a, days, onOpen }) {
  const top = a ? Object.fromEntries(Object.entries(a.projects).slice(0, 6)) : null
  return (
    <Tile icon="project" title="Active projects" sub={`Last ${days} days${a && !a.complete ? ' (at least)' : ''}`} onOpen={onOpen} openLabel="Open search">
      {recent.loading && !a && quiet('Loading projects…')}
      {recent.error && quiet("Couldn't load projects.")}
      {top && Object.keys(top).length === 0 && quiet('Nothing saved in this window.')}
      {top && Object.keys(top).length > 0 && <RankedBars counts={top} label={NameLabel} noun="saved" />}
    </Tile>
  )
}

function EvalTile({ onOpen }) {
  const { data, error } = useEval()
  const s = summarizeRuns(data?.runs)
  const allPass = s.total > 0 && s.passed === s.total
  return (
    <Tile className={styles.eval} tone="lamp" icon="eval" title="Eval" sub={s.total ? `${s.total} runs` : 'Retrieval quality'} onOpen={onOpen} openLabel="Open eval">
      {error && <p className={`t-small ${styles.error}`} role="alert">Couldn't load eval runs ({error}).</p>}
      {!error && !data && <p className={`t-small ${styles.secondary}`}>Loading runs…</p>}
      {data && s.total === 0 && <p className={`t-small ${styles.secondary}`}>No eval runs yet.</p>}
      {s.total > 0 && (
        <div className={styles.evalBody}>
          <div className={styles.evalHead}>
            <p className="t-kpi">
              {fmt.format(s.passed)}
              <span className={styles.unit}>/{fmt.format(s.total)} passed</span>
            </p>
            {allPass ? (
              <SignalChip signal="use" icon="decision">pass</SignalChip>
            ) : (
              <SignalChip signal="fail" icon="close">{s.total - s.passed} failed</SignalChip>
            )}
          </div>
          {s.latest && (
            <p className={`t-small ${styles.secondary}`}>
              Latest P@1 <span className="t-mono">{s.latest.p1.toFixed(2)}</span> · last {s.scored.length} scored runs below
            </p>
          )}
          {s.scored.length > 0 && (
            <div className={styles.evalStrip}>
              <RunStrip runs={s.scored} />
            </div>
          )}
        </div>
      )}
    </Tile>
  )
}
