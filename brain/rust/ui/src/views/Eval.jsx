import { useEffect } from 'react'
import { useEval } from '../context/EvalContext'

function pct(v) {
  return v != null ? `${(v * 100).toFixed(1)}%` : '—'
}

function gap(v) {
  if (v == null) return '—'
  const sign = v >= 0 ? '+' : ''
  const cls = v <= -0.05 ? 'text-red-400' : 'text-green-400'
  return <span className={cls}>{sign}{(v * 100).toFixed(1)}pp</span>
}

function PassBadge({ pass }) {
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-semibold ${
      pass ? 'bg-green-900/50 text-green-300' : 'bg-red-900/50 text-red-300'
    }`}>
      {pass ? 'PASS' : 'FAIL'}
    </span>
  )
}

export default function Eval({ activeView }) {
  const { data, error, refresh } = useEval()

  useEffect(() => {
    if (activeView === 'eval') refresh()
  }, [activeView, refresh])

  if (error) {
    return (
      <div className="p-6">
        <h2 className="text-lg font-semibold text-white mb-4">Eval</h2>
        <div className="text-xs text-red-400 bg-red-900/20 rounded p-3 flex items-center justify-between">
          Failed to load eval data: {error}
          <button onClick={refresh} className="underline ml-2">Retry</button>
        </div>
      </div>
    )
  }

  if (!data) {
    return (
      <div className="p-6">
        <h2 className="text-lg font-semibold text-white mb-4">Eval</h2>
        <p className="text-xs text-zinc-600">Loading…</p>
      </div>
    )
  }

  const runs = data.runs ?? []

  if (!runs.length) {
    return (
      <div className="p-6">
        <h2 className="text-lg font-semibold text-white mb-4">Eval</h2>
        <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-6 text-center">
          <p className="text-sm text-zinc-400 mb-2">No eval runs yet.</p>
          <p className="text-xs text-zinc-600 font-mono">
            python3 brain/tools/eval_suite.py
          </p>
        </div>
      </div>
    )
  }

  const latest = runs[0]

  return (
    <div className="p-6 max-w-4xl">
      <h2 className="text-lg font-semibold text-white mb-4">Eval</h2>

      {/* Latest run summary */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-5 mb-6">
        <div className="flex items-center gap-3 mb-3">
          <PassBadge pass={latest.pass} />
          <p className="text-xs text-zinc-500 font-mono">{latest.run_id}</p>
        </div>
        <div className="grid grid-cols-3 gap-4">
          <div>
            <p className="text-xs text-zinc-600 mb-1">non-fact P@1</p>
            <p className="text-xl font-semibold text-white tabular-nums">{pct(latest.non_fact_p1)}</p>
          </div>
          <div>
            <p className="text-xs text-zinc-600 mb-1">MCP P@1</p>
            <p className="text-xl font-semibold text-white tabular-nums">{pct(latest.mcp_p1)}</p>
          </div>
          <div>
            <p className="text-xs text-zinc-600 mb-1" title="Live MCP P@1 minus offline RRF P@1 on the same gold queries. Positive = live path beats plain RRF.">MCP vs RRF</p>
            <p className="text-xl font-semibold tabular-nums">{gap(latest.mcp_gap)}</p>
          </div>
        </div>
      </div>

      {/* Run history table */}
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="text-left text-xs text-zinc-500 border-b border-zinc-800">
            <th className="pb-2 pr-4 font-normal">Run ID</th>
            <th className="pb-2 pr-4 font-normal">Pass</th>
            <th className="pb-2 pr-4 font-normal tabular-nums">P@1 avg</th>
            <th className="pb-2 pr-4 font-normal tabular-nums">non-fact P@1</th>
            <th className="pb-2 pr-4 font-normal tabular-nums">MCP P@1</th>
            <th className="pb-2 font-normal" title="Live MCP P@1 minus offline RRF P@1 on the same gold queries. Positive = live path beats plain RRF.">MCP vs RRF</th>
          </tr>
        </thead>
        <tbody>
          {runs.map(r => (
            <tr key={r.run_id} className="border-b border-zinc-900 text-zinc-400">
              <td className="py-2 pr-4 font-mono text-xs text-zinc-500">{r.run_id}</td>
              <td className="py-2 pr-4"><PassBadge pass={r.pass} /></td>
              <td className="py-2 pr-4 tabular-nums">{pct(r.quick_p1_avg)}</td>
              <td className="py-2 pr-4 tabular-nums">{pct(r.non_fact_p1)}</td>
              <td className="py-2 pr-4 tabular-nums">{pct(r.mcp_p1)}</td>
              <td className="py-2">{gap(r.mcp_gap)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
