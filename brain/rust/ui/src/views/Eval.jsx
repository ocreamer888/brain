import { useEffect, useMemo, useState } from 'react'
import LineChart from '../components/brand/LineChart'
import TickRing from '../components/brand/TickRing'
import Tile from '../components/brand/Tile'
import { Button, SignalChip } from '../components/brand/primitives'
import { useEval } from '../context/EvalContext'
import { classifyGap, formatPp, p1Series, parseRunId, pct, summarizeRuns } from '../lib/evalRuns'
import styles from './Eval.module.css'

const PAGE = 20
const SERIES = [
  { key: 'p1', label: 'P@1 average', color: 'var(--chart-1)' },
  { key: 'mcp', label: 'MCP P@1 (live path)', color: 'var(--chart-2)', dashed: true },
]
const GAP_HELP = 'Live MCP P@1 minus offline RRF P@1 on the same gold queries. Positive = the live path beats plain RRF.'
const when = new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeStyle: 'short' })

/** Eval: retrieval quality runs (brand book §10 "Score sheet"). */
export default function Eval({ activeView }) {
  const { data, error, refresh } = useEval()

  // The eval suite writes a file; re-read it whenever the view opens.
  useEffect(() => {
    if (activeView === 'eval') refresh()
  }, [activeView, refresh])

  if (error) return <LoadError message={error} onRetry={refresh} />
  if (!data) return <p className={`t-body ${styles.page} ${styles.secondary}`}>Loading runs…</p>
  const runs = data.runs ?? []
  if (!runs.length) return <NoRuns />
  return <ScoreSheet runs={runs} />
}

function ScoreSheet({ runs }) {
  const summary = summarizeRuns(runs)
  const points = useMemo(() => p1Series(runs), [runs])
  return (
    <div className={styles.page}>
      <PassRing className={styles.ring} summary={summary} />
      <LatestRun className={styles.latest} run={runs[0]} />
      <Tile
        className={styles.trend}
        icon="bars"
        title="Precision over time"
        sub={`${points.length} scored runs, evenly spaced, oldest to newest · hover or use ←/→ for a run`}
      >
        <LineChart points={points} series={SERIES} label="Precision at 1 across eval runs" format={pct} />
      </Tile>
      <RunTable className={styles.runs} runs={runs} />
    </div>
  )
}

function PassRing({ summary, className }) {
  const failed = summary.total - summary.passed
  return (
    <Tile className={className} icon="eval" title="Pass rate" sub={`All ${summary.total} runs`}>
      <div className={styles.ringBody}>
        <TickRing
          value={summary.total ? summary.passed / summary.total : 0}
          tone={failed ? 'fail' : 'ok'}
          label={`${summary.passed} of ${summary.total} runs passed`}
        >
          <TickRing.Value>
            {summary.passed}/{summary.total}
          </TickRing.Value>
          <TickRing.Caption>{failed ? `${failed} failed` : 'all passed'}</TickRing.Caption>
        </TickRing>
      </div>
    </Tile>
  )
}

/** The newest run, in the cream tile: is retrieval good right now? */
function LatestRun({ run, className }) {
  const at = parseRunId(run.run_id)
  return (
    <Tile className={className} tone="lamp" icon="decision" title="Latest run" sub={at ? when.format(at) : run.run_id}>
      <div>
        {run.pass ? (
          <SignalChip signal="use" icon="decision">pass</SignalChip>
        ) : (
          <SignalChip signal="fail" icon="close">fail</SignalChip>
        )}
      </div>
      <div className={styles.metrics}>
        <Metric label="P@1 average" value={pct(run.quick_p1_avg)} />
        <Metric label="Non-fact P@1" value={pct(run.non_fact_p1)} />
        <Metric label="MCP P@1 (live path)" value={pct(run.mcp_p1)} />
        <Metric label="MCP vs RRF" value={<Gap v={run.mcp_gap} />} help={GAP_HELP} />
      </div>
    </Tile>
  )
}

function Metric({ label, value, help }) {
  return (
    <div className={styles.metric}>
      <span className={`t-label ${styles.label}`} title={help}>
        {label}
      </span>
      <span className={`t-kpi ${styles.value}`}>{value}</span>
    </div>
  )
}

const GAP_WORDS = { gain: ['↑', 'beats RRF'], flat: ['→', 'within tolerance'], regression: ['↓', 'regression'] }

/** Gain / within tolerance / regression: arrow + word + color, never color alone. */
function Gap({ v, compact = false }) {
  const kind = classifyGap(v)
  if (!kind) return '—'
  const [arrow, word] = GAP_WORDS[kind]
  return (
    <span className={styles.delta} data-kind={kind} title={GAP_HELP}>
      <span aria-hidden>{arrow}</span>
      {formatPp(v)}
      {!compact && <span className="t-small">{word}</span>}
      {compact && <span className="sr-only">{word}</span>}
    </span>
  )
}

function RunTable({ runs, className }) {
  const [limit, setLimit] = useState(PAGE)
  const shown = runs.slice(0, limit)
  return (
    <Tile className={className} icon="conversation" title="Run history" sub={`Newest first · ${runs.length} runs`}>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr className="t-label">
              <th scope="col">Run</th>
              <th scope="col">Result</th>
              <th scope="col" className={styles.num}>P@1 avg</th>
              <th scope="col" className={styles.num}>Non-fact P@1</th>
              <th scope="col" className={styles.num}>MCP P@1</th>
              <th scope="col" title={GAP_HELP}>MCP vs RRF</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <RunRow key={r.run_id} r={r} />
            ))}
          </tbody>
        </table>
      </div>
      {runs.length > shown.length && (
        <div className={styles.more}>
          <Button onClick={() => setLimit((n) => n + PAGE)}>Show {Math.min(PAGE, runs.length - shown.length)} more</Button>
          <Button onClick={() => setLimit(runs.length)}>Show all {runs.length}</Button>
        </div>
      )}
    </Tile>
  )
}

function RunRow({ r }) {
  const at = parseRunId(r.run_id)
  return (
    <tr>
      <td>
        <span className="t-body">{at ? when.format(at) : r.run_id}</span>
      </td>
      <td>
        {r.pass ? (
          <SignalChip signal="use" icon="decision">pass</SignalChip>
        ) : (
          <SignalChip signal="fail" icon="close">fail</SignalChip>
        )}
      </td>
      <td className={`t-mono ${styles.num}`}>{pct(r.quick_p1_avg)}</td>
      <td className={`t-mono ${styles.num}`}>{pct(r.non_fact_p1)}</td>
      <td className={`t-mono ${styles.num}`}>{pct(r.mcp_p1)}</td>
      <td className="t-mono">
        <Gap v={r.mcp_gap} compact />
      </td>
    </tr>
  )
}

function NoRuns() {
  return (
    <div className={styles.page}>
      <Tile icon="eval" title="No eval runs yet" sub="Run the suite to measure retrieval quality">
        <div className={styles.empty}>
          <p className={`t-body ${styles.secondary}`}>Results appear here after the first run, newest first.</p>
          <code className="t-mono">python3 brain/tools/eval_suite.py</code>
        </div>
      </Tile>
    </div>
  )
}

function LoadError({ message, onRetry }) {
  return (
    <div className={styles.page}>
      <div className={`t-small ${styles.error}`} role="alert">
        <span>Couldn't load eval runs ({message}).</span>
        <Button onClick={onRetry}>Retry</Button>
      </div>
    </div>
  )
}
