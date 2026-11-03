/**
 * eval_dashboard.json lists runs newest first, and older runs carry no score.
 * The tile needs: how many passed overall, and the last N scored runs, oldest → newest.
 */
export type EvalRun = { run_id: string; pass?: boolean; quick_p1_avg?: number | null }
export type ScoredRun = { run_id: string; p1: number; pass: boolean }

export function summarizeRuns(runs: EvalRun[] = [], recent = 14) {
  const passed = runs.filter((r) => r.pass).length
  const scored: ScoredRun[] = runs
    .filter((r) => typeof r.quick_p1_avg === 'number')
    .slice(0, recent)
    .reverse()
    .map((r) => ({ run_id: r.run_id, p1: r.quick_p1_avg as number, pass: !!r.pass }))
  return { total: runs.length, passed, scored, latest: scored.at(-1) ?? null }
}

/** Run ids are local timestamps: "YYYY-MM-DD-HHMM". Null when the id has another shape. */
export function parseRunId(runId: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})-(\d{2})(\d{2})$/.exec(runId)
  if (!m) return null
  const [, y, mo, d, h, mi] = m.map(Number)
  const date = new Date(y, mo - 1, d, h, mi)
  return Number.isNaN(date.getTime()) ? null : date
}

/** 0.8442 → "84.4%"; missing → "—". */
export function pct(v: number | null | undefined): string {
  return typeof v === 'number' ? `${(v * 100).toFixed(1)}%` : '—'
}

/**
 * MCP vs RRF, in percentage points. The old Eval view flagged ≤ −5 pp as bad;
 * that tolerance is kept. Above 0 is a gain; between −5 pp and 0 is within tolerance.
 */
export const GAP_TOLERANCE = -0.05
export type GapKind = 'gain' | 'flat' | 'regression'

export function classifyGap(v: number | null | undefined): GapKind | null {
  if (typeof v !== 'number') return null
  if (v <= GAP_TOLERANCE) return 'regression'
  return v > 0 ? 'gain' : 'flat'
}

/** "+5.9 pp" / "−8.0 pp" (true minus sign). */
export function formatPp(v: number): string {
  const n = (v * 100).toFixed(1)
  return v >= 0 ? `+${n} pp` : `−${n.replace('-', '')} pp`
}

export type P1Point = { run_id: string; at: Date | null; p1: number | null; mcp: number | null; pass: boolean }

/** Scored runs, oldest → newest, for the precision chart (a missing value stays null = a gap). */
export function p1Series(runs: (EvalRun & { mcp_p1?: number | null })[] = []): P1Point[] {
  return runs
    .filter((r) => typeof r.quick_p1_avg === 'number')
    .slice()
    .reverse()
    .map((r) => ({
      run_id: r.run_id,
      at: parseRunId(r.run_id),
      p1: r.quick_p1_avg as number,
      mcp: typeof r.mcp_p1 === 'number' ? r.mcp_p1 : null,
      pass: !!r.pass,
    }))
}
