# Brain UI: components dev log

Tracks every UI component in `brain/rust/ui`: what exists, what is planned, and what happened to each. The design rules live in `docs/ui-inspo/brain-brand-book.md`; this file is the work log.

## How to use this file

- One section per component. The **Log** at the bottom of each section is append-only: newest entry last, dated, one or two lines, facts only (what changed, what was verified, what is still open).
- When a component changes status, update its row in the index and add a log line.
- "Data" means what the component reads today. A component that needs an API change says so under **Blocked by**.

**Status:** `shipped` (in the live app, not deployed) · `sample` (sample page only) · `planned` · `blocked` (needs backend) · `idea` (not committed to).

**Rules every component follows:** plain CSS (`Component.module.css` beside it, tokens from `styles/tokens.css`, no Tailwind); both appearances; text contrast measured on rendered pixels (≥ 4.5:1, ≥ 3:1 large); color is never the only signal; state in attributes, not runtime class names; works with Reduce Motion / Reduce Transparency / Increase Contrast.

**Verification tools** (not in the repo): `/tmp/brainpal/contrast.mjs` + `measure.py` (pixel contrast per text run), `search.mjs` / `views.mjs` (browser flows), Playwright from `~/.hermes/hermes-agent/node_modules/playwright-core` driving Brave.

---

## Index

| # | Component | Status | Where | Next step |
| --- | --- | --- | --- | --- |
| 1 | Icon set | shipped | `components/brand/Icon.jsx` | Add icons as new components need them |
| 2 | Primitives (Button, ArrowChip, FilterChip, SearchPill, SignalChip, TypeChip, KpiTile, LiveDot) | shipped | `components/brand/primitives.jsx` | KpiTile is unused in the live app; keep or remove at next cleanup |
| 3 | Dock | shipped | `components/brand/Dock.jsx` | — |
| 4 | App shell + header | shipped | `App.jsx`, `App.module.css` | Drop the `LEGACY` wrapper as views migrate |
| 5 | Tile (+ lamp tone) | shipped | `components/brand/Tile.jsx` | — |
| 6 | GlowHero | shipped | `components/brand/GlowHero.jsx` | Optional: taller portrait variant |
| 7 | RankedBars | shipped | `components/brand/RankedBars.jsx` | — |
| 8 | DailyBars | shipped | `components/brand/DailyBars.jsx` | — |
| 9 | RunStrip | shipped | `components/brand/RunStrip.jsx` | — |
| 10 | MemoryRow | shipped | `components/brand/MemoryRow.jsx` | — |
| 11 | MemoryReading | shipped | `components/brand/MemoryReading.jsx` | Reuse in Linked floater |
| 12 | Dashboard view | shipped | `views/Dashboard.jsx` | Planned list done; ideas #21–24 next if wanted |
| 13 | Search view | shipped | `views/Search.jsx` | Keyboard navigation (↑/↓) |
| 14 | Shared hooks/helpers | shipped | `lib/useLoad.js`, `lib/memoryRows.ts`, `lib/evalRuns.ts`, `lib/activity.ts`, `lib/memorySignals.js` | — |
| 15 | Brand sample page | sample | `sample.html`, `src/sample/` | Keep in step with live components or retire |
| 16 | Memory spotlights (latest decision / lesson) | shipped | `components/brand/Spotlight.jsx`, `lib/spotlight.ts` | — |
| 17 | Top entities | shipped | `components/brand/EntityChips.jsx`, API `GET /entities/top` | — |
| 18 | Time-range pill (7d / 14d / 30d) | shipped | `Segmented` in `primitives.jsx`, `Tile` `actions` slot | — |
| 19 | New facts tile (was "Needs-review") | shipped | `views/Dashboard.jsx` (`NewFactsTile`), `views/Curate.jsx`, `lib/activity.ts` | — |
| 20 | Sources mix | shipped | `views/Dashboard.jsx` (`SourcesTile`), `lib/sources.ts` | — |
| 21 | Calendar heatmap | idea | — | Only if Activity is not enough |
| 22 | Hero sparklines | idea | — | — |
| 23 | "Just saved" toast | idea | — | — |
| 24 | Loading skeletons | idea | — | — |
| 25 | Growth over time | blocked | — | Needs history in the API |
| 26 | Click a day → search | blocked | — | Needs a date filter on search |
| 27 | Instance cards | shipped | in #34 (`BrainCard`) | — |
| 28 | Tick-ring gauge | shipped | `components/brand/TickRing.jsx` | — |
| 29 | ⌘K command palette | idea | — | Consider after all views migrate |
| 30 | Server-side daily counts | blocked | Rust API | Owner decision (backend change) |
| 31 | Linked view (legacy 2D graph) | removed | — | Replaced by #37 |
| 32 | Eval view | shipped | `views/Eval.jsx`, `Eval.module.css` | — |
| 33 | LineChart | shipped | `components/brand/LineChart.jsx` | Reuse for any time series |
| 34 | Instances view | shipped | `views/Instances.jsx`, `views/instances/InstanceForm.jsx` | — |
| 35 | ConfirmDialog | shipped | `components/brand/ConfirmDialog.jsx` | Reuse for every destructive action |
| 36 | Curate view | shipped | `views/Curate.jsx`, `views/curate/FactRow.jsx` | — |
| 38 | Reference atlas (ATLAS brain) | shipped (dev + API live) | `src/atlas.rs`, `bin/brain_atlas_import.rs`, `/v1/atlas/:id`, `views/linked/ReferenceAtlas.jsx` | Better name search ranking |
| 37 | Linked: 3D memory atlas | shipped (dev) | `views/linked/`, `scripts/build_atlas.py`, `scripts/layout_atlas.mjs` | Production route for `atlas.json` (needs a server restart: owner OK) |

---

## Shipped

### 1. Icon set
- **Does:** 24×24, 1.5px stroke icons for nav, memory types, actions. Outline = inactive, filled = active.
- **Refs:** `ui/0229`. Brand book §7.
- **Files:** `components/brand/Icon.jsx`.
- **Log**
  - 2026-10-18: 25 icons drawn (6 nav, 9 types, actions). Wrench redrawn after it rendered unreadably small.
  - 2026-10-18: Added `layers`, `copy`, `back`, `bars`.

### 2. Primitives
- **Does:** Button (primary lamp / quiet glass), ArrowChip, FilterChip, SearchPill (Enter → `onSubmit`), SignalChip, TypeChip, KpiTile, LiveDot (live / connecting / reconnecting).
- **Refs:** `ui/0174`, `0179`, `0224`, `0231`.
- **Files:** `components/brand/primitives.jsx`, `primitives.module.css`.
- **Log**
  - 2026-10-18: Built on Tailwind, then converted to CSS Modules when the no-Tailwind rule was set.
  - 2026-10-18: Chips use `data-signal`; the earlier runtime class names were being purged by Tailwind.
  - 2026-10-18: Dark `episode` chip raised to neutral-300 (measured 4.01:1 on the translucent tile, now passes).
  - Open: KpiTile is used only by the sample page.

### 3. Dock
- **Does:** Glass vertical nav for the six views; 44px targets; `aria-current` on the active view.
- **Refs:** `ui/0229`.
- **Files:** `components/brand/Dock.jsx`.
- **Log**
  - 2026-10-18: Built; replaced the zinc sidebar and the unicode nav glyphs.

### 4. App shell + header
- **Does:** Ambient backdrop, one frosted floating panel, a header with the view title, instance line, search (hands the query to Search), live pill, instance pill. Views not yet rebuilt render pinned dark inside it.
- **Refs:** `ui/0224`, `0225`, `0236`.
- **Files:** `App.jsx`, `App.module.css`, `main.jsx`, `index.html`.
- **Log**
  - 2026-10-18: Shell moved from the sample into the live app; `LEGACY` set for unmigrated views; `FILL` set for views that own their scrolling.
  - 2026-10-18: Materials pass: ambient backdrop, frosted panel (40px), denser header material, 2.5rem headline.
  - 2026-10-18: Parallel edits made in Cursor (Cursor local history, 40 saves to `App.module.css` 22:10–22:31): added `.wordmarkContainer` / `.dockContainer` (dock centred vertically), removed `.panel` background and shadow, header `position` sticky → relative and `z-index` removed. Kept as-is (owner's design edits); `App.jsx` holds both sets of changes. Pixel contrast after those edits: still passing (234 runs, worst 5.88:1).
  - Known: in dev the live pill can stay on "connecting" (Vite proxy holds the stream's first byte); production on :8787 shows "live".

### 5. Tile
- **Does:** Card with icon circle, title, subtitle, optional ↗; translucent material. `tone="lamp"` = the one cream tile per screen, contents in the light scheme.
- **Refs:** `ui/0239`, `0224`, `0236`.
- **Files:** `components/brand/Tile.jsx`.
- **Log**
  - 2026-10-18: Built; then moved to the translucent tile material; lamp tone added and used for Eval.
  - 2026-10-18: Body became a flex column so content can anchor to the floor.
  - 2026-10-19: `actions` slot in the header (used by the range pill); header wraps on narrow tiles.

### 6. GlowHero
- **Does:** The one glow per screen. Number on the dark cap, stat strip or caption in ink on the cream.
- **Refs:** `IMG_0240` (measured), `ui/0225` (stat strip). Brand book §6.5.
- **Files:** `components/brand/GlowHero.jsx`.
- **Log**
  - 2026-10-18: Mesh ported from sicop-health `ds/mesh.module.css` (blurred blob layer, milk/rim, grain).
  - 2026-10-18: Recipe rebuilt from `IMG_0240` pixel samples: dark cap with an ember ring, cool mist, cream base. Split layout.
  - 2026-10-18: Stat strip added. Contrast measured: number ≥ 9.7:1, strip ≥ 7.9:1.
  - 2026-10-19: `actions` slot in the foot; the foot always sits on cream, so it uses the light scheme (controls there get validated light colors; the Dashboard arrow chip turns white on cream).
  - Open: our hero is a wide card; aurō is a portrait tile.

### 7. RankedBars
- **Does:** Counts largest-first, one hue, value + share; the label carries identity (type chip by default, `NameLabel` for plain names).
- **Refs:** `ui/0237`; dataviz guidance (more than 7 skewed classes → bar list).
- **Files:** `components/brand/RankedBars.jsx`.
- **Log**
  - 2026-10-18: Built for memory types.
  - 2026-10-18: `label` / `noun` props + `NameLabel`; reused for Active projects.
  - 2026-10-19: `nameOf` prop so screen readers hear a display name, not a raw key (Sources).

### 8. DailyBars
- **Does:** Saves per day as columns; labels only on peak and today; tooltip and aria-label per day; zero days keep a stub.
- **Refs:** `ui/0225`, `0237`, `0239`.
- **Files:** `components/brand/DailyBars.jsx`.
- **Log**
  - 2026-10-18: Built; local-day bucketing via `lib/activity.ts`.
  - 2026-10-19: Works for any range; axis labels thin out past 14 days (#18).

### 9. RunStrip
- **Does:** Eval runs as status cells; height = P@1; tooltip per run.
- **Refs:** `ui/0246`, `0234`.
- **Files:** `components/brand/RunStrip.jsx`.
- **Log**
  - 2026-10-18: Built; real runs via `lib/evalRuns.ts`.

### 10. MemoryRow
- **Does:** Type chip, project, date, id, two-line snippet. A button only when it can open something; `selected` shows the dusk ring.
- **Refs:** `ui/0178`, `0225`, `0237`.
- **Files:** `components/brand/MemoryRow.jsx`.
- **Log**
  - 2026-10-18: Built; meta text moved to the secondary tier (tertiary failed on raised rows).
  - 2026-10-18: Renders as plain content without `onOpen`; `selected` state added.
  - 2026-10-18: Fixed: the date was sliced from the UTC timestamp, so evening saves showed tomorrow's date; now the reader's local day (`dayKey`).

### 11. MemoryReading
- **Does:** One memory in full, loaded by id: meta, title, copy id, superseded notice, text, tags, Linked (entities + neighbors, 10 per page), Saved around it (timeline on request).
- **Refs:** `ui/0238`. Brand book §9 "Memory reading".
- **Files:** `components/brand/MemoryReading.jsx`.
- **Log**
  - 2026-10-18: Built for Search; neighbors paged after one memory showed 908 (the old UI fetched all of them).

### 12. Dashboard view
- **Does:** Hero + What it keeps / Activity + Eval / Latest + Active projects, on live data.
- **Files:** `views/Dashboard.jsx`.
- **Log**
  - 2026-10-18: Rebuilt on `/stats`, the live feed, and `eval_dashboard.json`.
  - 2026-10-18: Activity and Active projects added from `/list?limit=2000`; Latest cut to 6 rows with Show more and Search all; rows open the reading pane.
  - 2026-10-18: Pixel contrast: 165 text runs per mode, worst 5.66:1.
  - 2026-10-18: Right column added for spotlights; the 2000-item load moved up to the view and its 14-day summary is computed once (`useMemo`) for Activity and Active projects.
  - Known (dev): React StrictMode runs every effect twice, so each request shows twice in the network log; `useLoad` discards the stale one. The page settles in ~1.4 s in dev.

### 13. Search view
- **Does:** Two panes (results / reading), all nine type filters, paging, narrow single-pane mode with Back.
- **Files:** `views/Search.jsx`.
- **Log**
  - 2026-10-18: Rebuilt; stale responses ignored; no false "0 results" frame; search snippets cut at the API's 120 chars marked with "…".
  - Open: ↑/↓ keyboard navigation through results.

### 14. Shared hooks/helpers
- **Log**
  - 2026-10-18: `useLoad` (key-based, stale-safe, derived loading); `memoryRows` (toRow, parseTags, markCut); `evalRuns`; `activity`; 25 tests across them.

### 15. Brand sample page
- **Log**
  - 2026-10-18: Built as the design proving ground; now behind the live app. Decide whether to keep it current or retire it.

### 16. Memory spotlights
- **Does:** "Latest decision" and "Latest lesson" tiles: headline, project · relative time, a short body, ↗ into the reading pane. A lesson with a `Fix:` line shows that line, labelled; its headline is the full `Error:` line.
- **Refs:** `ui/0231`, `0233`.
- **Data:** `/list?memory_type=<type>&limit=1` → `/v1/get_observations` (titles live in metadata, not in `/list`).
- **Files:** `components/brand/Spotlight.jsx`, `lib/spotlight.ts` (+ tests), `api.js` (`listMemories(limit, { memoryType })`).
- **Log**
  - 2026-10-18: Proposed; recommended in the first batch.
  - 2026-10-18: Checked real data first: 235 decisions, 121 lessons; only 35 lessons follow Error / Cause / Fix, so the Fix line is shown when present and plain text otherwise. Stored lesson titles are clipped ("Fix: <error…>"), so the Error line is used as the headline.
  - 2026-10-18: Shipped in the Dashboard's right column (Latest decision, Latest lesson, Active projects). Both ↗ open the right memory in the reading pane (browser-verified). Pixel contrast: 203 text runs per mode, worst 5.6:1. 8 helper tests.

### 17. Top entities
- **Does:** "What it knows about": a full-width strip of the 14 most-linked entities, name + count; each chip opens Linked filtered to that entity; ↗ opens Linked unfiltered.
- **Refs:** `ui/0179`, `0224`, `0236` (chip rows).
- **Data:** new `GET /entities/top?limit=N` (default 12, max 100): ~1 KB, ~70 ms. `/linked` (11.8 MB, 1.3 s) was the only other source.
- **Files:** `components/brand/EntityChips.jsx`; `api.js` (`getTopEntities`); `views/Linked.tsx` (`initialEntity` prop); `App.jsx` (`openEntity`, dock resets the filter). Rust: `store.rs` (`list_top_entities`, shared query with a LIMIT), `brain.rs` (`top_entities`), `bin/brain_api.rs` (handler + route).
- **Log**
  - 2026-10-18: Proposed; recommended in the first batch.
  - 2026-10-18: Blocked on data: `/linked` returns 16,147 memories + 27,050 entities (11.8 MB). Owner approved a small endpoint and a restart of the live API.
  - 2026-10-18: Endpoint added; new store test + 143 lib tests pass. Release binary trialled first in isolation (temp `HOME`, `sqlite3 .backup` snapshot, launchd env, spare port): healthy in 2 s, cap enforced. Live service restarted with `launchctl kickstart`; healthy after 15 s.
  - 2026-10-18: Shipped on the Dashboard. Browser-verified: 14 chips, a chip opens Linked with that entity selected, the dock opens Linked unfiltered. Production preview build: 3 runs, both modes, no errors. Pixel contrast 234 text runs per mode, worst 5.88:1.
  - Known (dev only): a stack overflow in React Fast Refresh when a hot update lands while Linked is open, because Linked renders all 27,050 entity buttons. Not reproducible in the production build. Fixed 2026-10-18, see #31.

### 18. Time-range pill
- **Does:** 7d / 14d / 30d segmented control in the Activity tile header; drives Activity and Active projects together; both subtitles name the range (and say "at least" if the sample doesn't reach back far enough).
- **Refs:** `ui/0224`, `0237`.
- **Data:** the same `/list?limit=2000` sample (reached back to 2026-09-04 on 2026-10-19, so 30 days is complete today).
- **Files:** `components/brand/primitives.jsx` (`Segmented`), `components/brand/Tile.jsx` (`actions` slot), `components/brand/DailyBars.jsx` (thinned axis), `lib/activity.ts` (`axisLabelEvery`, `showsAxisLabel`), `views/Dashboard.jsx`.
- **Log**
  - 2026-10-18: Proposed; recommended in the first batch.
  - 2026-10-19: Checked Cursor history first: none of the files had owner edits.
  - 2026-10-19: Shipped. `Segmented` is a WAI-ARIA radio group (one tab stop, arrows move + select + wrap, focus follows). At 30 days the axis labels every 5th day counted back from today; today is always labelled. A test caught a step-1 bug (yesterday's label hidden) before shipping. 3 tests, 40 total.
  - 2026-10-19: Browser-verified: bars 14 → 7 → 30 and both subtitles follow; Active projects re-ranks (sicop-health leads at 30 days); keyboard behaviour as above; no errors in either mode.
  - 2026-10-19: Pixel contrast: unselected options first measured 4.83:1 in dark (secondary text on glass over a tile; passes AA but the page's new worst). Moved to the body tier: now 7.01:1 dark / 14.81:1 light. Page worst back to 5.88:1 (236 runs per mode).

### 19. New facts tile (was "Needs-review")
- **Does:** Facts saved in the last 7 local days, how many today, and **Review newest** (the Dashboard's one primary action) which opens Curate on the newest facts. Eval keeps the cream tile.
- **Refs:** `ui/0224`, `0236` (a number with its action).
- **Data:** the Dashboard's existing `/list?limit=2000` sample (`recentCount`), no extra request. Curate: `/list?memory_type=fact&limit=50` → `/v1/get_observations`.
- **Files:** `views/Dashboard.jsx` (`NewFactsTile`, row 2 is now Activity 6 · New facts 3 · Eval 3), `lib/activity.ts` (`recentCount` + 2 tests), `views/Curate.jsx` (newest-first mode).
- **Log**
  - 2026-10-18: Proposed as "Needs-review": count of facts waiting in Curate, taking the cream tile from Eval.
  - 2026-10-19: Premise failed on inspection: Curate has no review queue (it showed the 50 facts nearest the word "fact"; Promote = salience 1.0, Reject = a feedback event; nothing records "reviewed"; `curation_events` is the auto-dedup log, last written 2026-05-03). A "N waiting" count would be invented. Owner chose the honest version: count arrivals, open Curate on the newest.
  - 2026-10-19: Curate now lists the newest 50 facts when nothing is typed (search unchanged), labels which mode it is in, and no longer flashes "0 newest facts" while loading (count hidden until the first load lands).
  - 2026-10-19: Shipped. Browser-verified: tile 97 this week / 0 today (it was just past midnight; rolling-24h figures from the API were 111 / 65, both correct for their windows); Review newest → Curate "50 newest facts, newest first", all dated today; search still returns matches. Pixel contrast 241 runs per mode, worst 5.88:1. 42 tests.
  - Found: Curate's `named_entity` / `other` filter is dead. Search hits carry no `fact_type`, and the newest 50 facts have no `fact_type:` tag (only older extractor-tagged facts do). Removed in the Curate rebuild (#36).

### 20. Sources mix
- **Does:** "Sources": where memories came from over the chosen range (follows the 7d / 14d / 30d pill), ranked bars with readable names; shares the row with "What it knows about" (8 + 4 columns).
- **Data:** `source` on the Dashboard's existing `/list?limit=2000` sample, counted per window in `summarizeActivity`; no extra request.
- **Files:** `views/Dashboard.jsx` (`SourcesTile`), `lib/sources.ts` (`sourceName` + 2 tests), `lib/activity.ts` (`sources` in the summary + 1 test), `components/brand/RankedBars.jsx` (`nameOf` for screen readers), `components/brand/Icon.jsx` (`inbox`).
- **Log**
  - 2026-10-18: Proposed.
  - 2026-10-19: Checked Cursor history first: no owner edits on the files. Real data: only three sources were active recently (Claude Code, Obsidian books, Cursor history); four more are defined in the API (Perplexity, Obsidian, Reflection, Claw Code).
  - 2026-10-19: Shipped. Browser-verified across ranges: 7d Obsidian books 290 vs Claude Code 278 (the import lands inside the week), 14d Claude Code 606 / 68%, 30d Claude Code 1,330 / 82%. Screen readers hear names ("Claude Code: 606 saved, 67.6%"), not ids. Own `inbox` icon (the `layers` icon belongs to "What it keeps"). Pixel contrast 253 runs per mode, worst 5.88:1. 45 tests.

---

## Planned

### 28. Tick-ring gauge
- **Does:** A 0–1 ratio as a ring of 60 ticks with the number inside; `tone="fail"` fills in the fail signal. `role="img"` with a spoken label.
- **Refs:** `ui/0246`, `0224`.
- **Files:** `components/brand/TickRing.jsx`.
- **Log**
  - 2026-10-18: Proposed for the Eval view.
  - 2026-10-19: Shipped as Eval's pass-rate ring (98/98, "all passed").

### 32. Eval view
- **Does:** Score sheet. Pass-rate ring; latest run in the cream tile (pass/fail, P@1 average, non-fact P@1, MCP P@1, MCP vs RRF as ↑ gain / → within tolerance / ↓ regression, with the old −5 pp threshold); precision over time (line chart); run history as capsule rows (20, show more, show all). Loading, error + retry, and the empty state with the eval command are kept.
- **Refs:** `ui/0246`, `0237`, `0234`. Brand book §10 "Score sheet".
- **Data:** `eval_dashboard.json` via `EvalContext` (re-read whenever the view opens, as before).
- **Files:** `views/Eval.jsx`, `views/Eval.module.css`, `lib/evalRuns.ts` (`parseRunId`, `pct`, `classifyGap`, `formatPp`, `p1Series` + 5 tests), `styles/base.css` (`.sr-only`), `App.jsx` (Eval left `LEGACY`).
- **Log**
  - 2026-10-19: Checked Cursor history first: no owner edits on Eval files.
  - 2026-10-19: Profiled the data: 98 runs, 0 failures; P@1 0.84–1.00 (87 scored), MCP P@1 0.11–0.64 (82), MCP vs RRF −89 pp to +7 pp.
  - 2026-10-19: Shipped. Numbers match the old view exactly (latest 100.0% / 100.0% / 17.6% / +5.9 pp). Browser-verified both modes: ring 98/98, table 20 → 98 rows, chart keyboard Home/End (May 23 84.4% → Oct 18 100%), no errors. Pixel contrast 120 runs per mode, worst 5.53:1.
  - 2026-10-19: Fixed during review: chart dates showed two-digit years; tooltip covered the legend (now beside the crosshair, flipping past the middle); chart subtitle now says runs are evenly spaced (index, not time). Header showed "Brain brain · — memories" while stats loaded; now "Loading…".

### 33. LineChart
- **Does:** Lines over evenly spaced points on a 0–1 axis; null = gap; legend + end labels; crosshair + tooltip on hover and ←/→/Home/End; draws in real pixels (ResizeObserver), so text never stretches. Series 2 is dashed.
- **Colors:** `--chart-1` / `--chart-2`, validated with the dataviz palette script in both modes (lightness band, chroma ≥ 0.10, CVD ΔE ≥ 20, ≥ 3:1 on the tile). First candidates (dusk-400 / lumen-200 from the brand book §5.7) failed the band and chroma checks.
- **Files:** `components/brand/LineChart.jsx`, `styles/tokens.css`.
- **Log**
  - 2026-10-19: Built for Eval.

### 34. Instances view
- **Does:** The active brain is the page's glow (name, memories, created, tags, Edit); a plain-words "What's a brain?" note; other brains as cards (memories, tags, archived chip; Switch / Edit / Archive or Restore / Delete… for archived only); New brain and Edit in a form dialog; "Switch to it now?" after create; status line for every outcome. Old rules kept: can't switch to the active, an archived, or while switching; the active can't be archived; only archived brains can be deleted; stats and feed reload after a switch.
- **Files:** `views/Instances.jsx`, `views/Instances.module.css`, `views/instances/InstanceForm.jsx` (+ css), `lib/instances.ts` (`sortInstances`, `parseTagInput`, `friendlyError` + 5 tests), `App.jsx` (left `LEGACY`).
- **Log**
  - 2026-10-19: Checked Cursor history first: no owner edits.
  - 2026-10-19: Safety rule for this view: no create/switch/archive/delete against the live server while testing. Live checks were read-only; every action was tested against a mocked `/v1/instances` in the test browser, with a guard that aborts any write that would reach the real API (0 aborted).
  - 2026-10-19: Server errors used to surface raw (`409: {"error":"…"}`); now sentences ("Instance is still being written to.", "The server is busy switching brains…").
  - 2026-10-19: Shipped. Verified (mocked): empty name rejected; tags de-duplicated; create → switch prompt (Cancel focused, Esc closes); edit; switch moves the glow to the new brain; archive; delete dialog shows the DB path, Cancel focused, a 409 stays in the dialog, retry deletes. Live: Main as the glow, 22,941 memories. Pixel contrast 27 runs per mode, worst 5.84:1 (56px name). 55 tests.

### 35. ConfirmDialog
- **Does:** Native `<dialog>` modal: focus trap, Esc cancels, page behind dimmed and inert, Cancel focused first; `danger` makes only the confirm red; async confirm shows "Working…" and keeps the dialog open with the error if it fails.
- **Files:** `components/brand/ConfirmDialog.jsx` (+ css); `InstanceForm` reuses its shell.
- **Log**
  - 2026-10-19: Built for Instances (delete, switch-to-new); replaces `window.confirm`.

### 36. Curate view
- **Does:** Review facts: newest 50 when nothing is typed, best 50 matches otherwise (always full rows via `get_observations`). Each fact: project, date, id, text clamped to 4 lines with Show all; **Promote** (salience 1.0) with **Undo** (restores the previous value), **Reject** (records "rejected" feedback; no undo because the API can't retract it; the fact stays), **Open** (reading pane in Search), **Show source** when the fact has an episode. Side panel: this session's confirmed counts and what each button does.
- **Files:** `views/Curate.jsx` (+ css), `views/curate/FactRow.jsx` (+ css), `lib/curate.ts` (`toFactRow`, `isPromoted` + 3 tests), `lib/useSettled.js` (moved out of Search), `api.js` (`patchMemory`, `sendFeedback`, `getEpisode`), `App.jsx` (left `LEGACY`; Open wired to the reading pane).
- **Log**
  - 2026-10-19: Checked Cursor history first: no owner edits.
  - 2026-10-19: Data: facts arrive at salience 0.5 (49/50) or 0.55; none of the newest 50 has a source episode. "Promoted" now comes from stored salience (≥ 0.95), so it survives reloads; before, all review state lived in the browser and vanished.
  - 2026-10-19: Removed the `named_entity` / `other` filter: it never matched (search hits carry no fact type; new facts have no `fact_type:` tag).
  - 2026-10-19: Removed `components/MemoryCard.jsx` (no users left; its rainbow type colors are gone with it).
  - 2026-10-19: Safety: live checks read-only (0 writes sent); Promote / Undo / Reject / source tested with every request mocked. Verified: a server failure shows "Database is locked." on the row and changes nothing; retry promotes; Undo sends `{"salience":0.5}`; Reject sends the feedback event and disables Promote; a fact promoted long ago shows as promoted; counts add up. Live: 50 newest, search, Open → reading pane. Pixel contrast 216 runs per mode, worst 5.58:1.
  - 2026-10-19: Long facts (15+ lines today) clamped to 4 lines with Show all: first row 343 → 215 px.
  - Open: Undo on a fact promoted in an earlier session restores 0.5 (the usual arrival value); the true earlier value isn't stored.

### 37. Linked: 3D memory atlas
- **Does:** Every live memory as a point in 3D; position = similarity (t-SNE inside each project), projects are separate organs with gaps; color = memory type (brand signals). Hover shows the title; click (or pick from a list) opens the reading pane and draws that memory's **real** links (shared-entity neighbors, up to 60, with "N of M drawn"). Entity finder over the top 300 entities lights their memories and lists them (the keyboard path); Dashboard chips arrive pre-filtered. Reset view, Esc closes focus then clears the entity. Pinned dark (immersive data canvas).
- **Continues:** Grok's `atlas-preview` (handoff memory ccad7ef5: "still not the atlas flower, middle crowded, needs a saved layout").
- **Decisions (owner, 2026-10-19):** the atlas replaces Linked; lines only for real links, on focus; data from an offline build; **three.js (MIT)**, not `@cosmograph/cosmos`, which is CC BY-NC (non-commercial) and so unsafe if Brain ships inside Tendrium.
- **Files:** `views/linked/LinkedAtlas.jsx` (+ css), `views/linked/AtlasCanvas.jsx` (three.js: shaded point sprites, depth fade, arcs, picking, fly-to, on-demand rendering), `lib/atlas.ts` (+ 6 tests), `scripts/build_atlas.py` → `public/atlas.json` (gitignored), `App.jsx` (lazy-loaded).
- **Log**
  - 2026-10-19: Read Grok's code and memories. Found: legend listed type colors while points were colored by project; the legend wasn't positioned; links were similarity, not real; the 3D engine is non-commercial; the canvas was never visually verified (WebGL works in Playwright-launched Brave on the M4 GPU, so it is now).
  - 2026-10-19: Layout rebuilt: 12,436 memories, 26 projects, 300 entities, 1.8 MB (was 5.3 MB), 21 s. Closest organ pair 1.16× their radii (no overlap); the 2D check shows separate organs, not the old knot.
  - 2026-10-19: Shipped in dev. Verified on the GPU: entity search (Supabase 241 lit + list), pick → reading pane + "60 of 309 linked memories drawn (26 aren't in the atlas)", Esc twice, Dashboard React chip → React filtered (267 lit), hover title. Zero writes. Pixel contrast of the overlays 23 runs per mode, worst 6.05:1.
  - 2026-10-19: Fixed during review: points too big (piles, not dust) 9 → 5.5; fly-to framed a single memory too close (min radius 260); link lines blew out to white (opacity 0.5); reading pane covered the finder (panels now stack left); finder rows 702 px in a 334 px list (grid `minmax(0, 1fr)`); highlighted points 1.35× → 1.8×.
  - 2026-10-19: Lazy-loaded: main bundle 215 KB (70 KB gz), the atlas chunk 524 KB (136 KB gz) only when Linked opens.
  - Open: production serving. `public/atlas.json` is baked into the binary at build time; rebuilding it on demand in production needs a runtime route like `/eval_dashboard.json` (Rust change + restart).
  - Open: color is memory type, so facts (≈ 2/3) make the atlas mostly cream. A project-color mode is possible but 26 categories can't pass the categorical palette checks; owner's call.
  - Open: `brain/rust/ui/atlas-preview/` (Grok's experiment, untracked) still depends on the non-commercial package; delete it or keep it as a personal toy.
  - 2026-10-19: Owner: "it looks like a white hairball; make it look JUST like the AI Model Atlas." Inspected the live atlas in the GPU test browser and downloaded its data: published config (palette, 6–10 px points, sphere shading, curved links opacity 0.8 coloured by endpoints, no additive blend), background #192129, and the parquet. Measured: 176,382 points, 88,878 links forming a **forest** (one parent per model; median 1 child, FLUX 2,231), 91k points with no link, largest component 17%, organs = fine-tune families packed solid.
  - 2026-10-19: Rebuilt to that shape from real data only. Each memory hangs off the most-mentioned entity it mentions; each hub off the bigger hub it is co-mentioned with in ≥ 15% of its memories (127 families, largest 14%); free memories sit beside their most similar linked memory (layout-only pull, never drawn). Layout (`scripts/layout_atlas.mjs`, d3-force-3d, MIT, devDependency): each family simulated alone into a solid ball, then families packed biggest-first in the centre with satellites in a shell. Tuned against the reference's own saved layout, projected side by side (9 variants). 12,442 memories + 1,476 hubs, 10,006 forest links drawn + 11,514 other real links as faint hairs; 2.0 MB; 25 s build.
  - 2026-10-19: Renderer: the atlas palette cycled by project (or memory type), 1.7-unit sphere points with a narrow 1–1.67 size range, normal blending (the white blowout was additive blending of 37k overlapping lines), #333841 hover label. Verified on the GPU: the close view matches the reference material; the far view has its composition but reads coarser (19k points vs 176k).
  - 2026-10-19: Styling pass ("something is still missing"). Read cosmos.gl's shaders for its link model: rational quadratic Bézier (weight 0.8), control point = midpoint + half the link length sideways in the camera-facing plane (curved from every angle), 19 segments, width scales with zoom, links fade to 25% opacity as on-screen length goes 50 → 150 px, greyed links at 10%. Built `views/linked/linkRibbons.js`: GPU instanced ribbons computing exactly that per frame (WebGL lines are 1 px, so the old links were hairlines). All 22,735 real links drawn at 0.8 (forest) / 0.55 (others), coloured end to end.
  - 2026-10-19: Background set to the atlas's #192129: saturated filaments need a mid slate. This reverses the owner's 02:04 removal of the previous near-black background; flagged to the owner, one line to revert.
  - 2026-10-19: Home view frames the 5th–95th percentile of points (the atlas's `quantileExtent [0.05, 0.95]`); finer points (1.35 units); hover ring (the atlas's `renderHoveredPointRing`); hover label white on #333841.
  - 2026-10-19: Tried plume shapes (weaker centre pull for big families): they thin out rather than stream; the reference's comets come from its data (thousands of fine-tunes of one base). Kept solid bodies; option left in the layout (`bigAt`, `gravityBig`, off).
  - 2026-10-19: Verified on the GPU: close view shows curved coloured filament bundles between organs like the reference; interactions unchanged, zero writes; contrast worst 4.98:1 (unselected segment on glass over slate, passes AA); 52 tests; atlas chunk 138 KB gz.
  - 2026-10-19: Polish pass. Captured every state (home, mid, close, entity lit, memory focused). Fixed: (1) focusing a memory flew to 220 units and filled the screen with spheres; now frames ~6% of the atlas. (2) Lit points were hidden behind dimmed ones (dimming darkened colour but kept them solid). Now two passes: lit points solid with depth, dimmed points afterwards as faint see-through spheres (cosmos.gl point greyout), so a lit set always shows. Lit points 2.2×, the focused point 3.2×, lit links full opacity. Load to ready ~1.5 s, 60 fps idle.

### 38. Reference atlas (ATLAS brain)
- **Does:** The AI Model Atlas itself, stored the way its Cosmograph project stores it (points table with `layout_x/y/z`, links table, project config), served by Brain and drawn by our renderer. Linked has a source switch: My memories · AI Model Atlas.
- **Data:** owner created the ATLAS brain and downloaded the links table (identical, row for row, to the parquet served by the live atlas); the points table came from the same public storage. Sources in `~/.brain/instances/atlas/source/`.
- **Rust:** `src/atlas.rs`: `atlas_points` / `atlas_links` / `atlas_meta` in each brain's DB (created with the other tables); RFC 4180 CSV importer (quoted labels, multi-line fields; replace is one transaction, a failed import keeps the old atlas); columnar reader ranking colour categories by frequency (the reference's legend order); binary geometry. `bin/brain_atlas_import <brain> <points.csv> <links.csv>` (AI Model Atlas preset: mapping + palette + size range + quantile extent). 5 tests.
- **API:** `GET /v1/atlas/:id` (config, counts, categories), `/geometry` (binary, 4.2 MB, 0.08 s), `/labels` (8.6 MB, 0.10 s); any brain, read-only, no switching; ETag + 304; 404 for unknown brains.
- **Log**
  - 2026-10-19: ATLAS was the active brain after creation, so every agent would have saved into it. Switched back to Main with the owner's OK; ATLAS had 0 memories, nothing misrouted.
  - 2026-10-19: Imported 176,382 points + 88,878 links into ATLAS in 1.0 s, 0 skipped. Main untouched.
  - 2026-10-19: Release binary trialled in isolation (temp HOME + registry, DB snapshots, spare port), then live restart (healthy in 12 s, Main still active).
  - 2026-10-19: Renderer now sizes points and links from each dataset's own spacing (median nearest-neighbour gap, sampled) instead of a fixed constant; the reference's points are 8× further apart than Brain's.
  - 2026-10-19: Verified on the GPU: draws in 0.3 s, names stream in by 2.9 s, 60 fps; search, select (lights links), Esc, reset, switch back to memories; zero writes. Side by side with run.cosmograph.app: a near-identical match far and close, which confirms the renderer; remaining differences in the memory atlas are data and layout.
  - Open: name search returns substring matches in table order; rank exact and prefix matches first, then by links.

### 39. Memory atlas served by the server (the real fix)
- **Does:** "My memories" in Linked now shows the **active brain's** atlas: positions stored in that brain's DB, everything else read live. New memories appear at once beside their topic ("N new since"); **Rebuild layout** recomputes in the background; a brain never built shows **Build the atlas**. The switch reads "Main · memories".
- **Files:** Rust `src/memory_atlas.rs`, `bin/brain_memory_atlas.rs`, `bin/brain_api.rs` (3 routes); UI `views/linked/LinkedAtlas.jsx` (`loadAtlas(brainId)`, `useRebuild`, `RebuildButton`, `NotBuilt`), `AtlasCanvas.jsx` (`pointToSpacing` per dataset). Spec: `docs/superpowers/specs/2026-10-19-memory-atlas-layout-design.md` §8.
- **Log**
  - 2026-10-19: Owner noticed Linked showed Main's file even when looking at ATLAS: "My memories" was a static file built from Main's DB path. Owner chose the real fix.
  - 2026-10-19: Rust layout port: same 1,037 families and spacing as the JS one on a Main snapshot, 19.7 s. 4 tests (real links only, superseded excluded, deterministic, provisional placement beside the hub, two layouts kept). 151 lib tests + integration pass.
  - 2026-10-19: Trial in isolation (needs-build → rebuild → second click refused → done; 2.1 MB in 0.14 s; 304), then live restart (slow boot, >40 s this time) and Main's first stored layout built live; memory counts unchanged.
  - 2026-10-19: Browser-verified: atlas from the API, Rebuild changes "Layout built" (11:47 → 11:48), never-built brain shows Build, a failed rebuild shows its error; requests only to `/v1/memory-atlas/main*`; all other flows pass; zero writes elsewhere.
  - 2026-10-19: Points came out chunky after the reference work (renderer used 0.85 of the neighbour gap); memory bodies are packed at touching distance, so they use 0.43 (the earlier tuned look). Spacing itself unchanged.
  - Retired: `public/atlas.json` (backup in /tmp/brainpal), `scripts/build_atlas.py`, `scripts/layout_atlas.mjs`, `d3-force-3d`.
  - 2026-10-19: **Automatic rebuild (built, not live yet).** Every 10 min the server checks the active brain; at 200+ memories saved since its layout it rebuilds in the background (warm start, so regions stay put). Brains never built are left alone. Settings: `BRAIN_ATLAS_AUTO_REBUILD` (count, 0 = off), `BRAIN_ATLAS_AUTO_CHECK_SECS`. `/status` reports `auto_rebuild_after`. Trial on a snapshot (threshold 1, 5 s): fired once, finished, then stayed quiet. Live restart waits on the owner's OK.
  - Open: response compression.
  - 2026-10-19: Owner asked why the AI Model Atlas showed while Main was active: the switch listed every brain's stored dataset. Now Linked shows only the active brain's content (brand book: brains don't share a wall): Main → its memories, no switch; ATLAS (no memories) → its AI Model Atlas directly; a brain with both gets the switch. Verified with Main live and ATLAS via mocked /stats (no real switch, so agents keep saving to Main).
  - 2026-10-19: Polish: with the reading pane open the view's centre shifts into the uncovered area (`insetRight` → `camera.setViewOffset`), so the selected memory is no longer hidden behind the pane.
  - 2026-10-19: Polish batch. (1) **Remember the view** (`views/linked/viewMemory.js`): camera, colour mode, lit topic and selected memory per atlas for the session (memories stored by id, so they survive rebuilds); a Dashboard topic chip still overrides; restore vs. fly compared by value so React's dev double-run can't trip it. Before/after canvas pixel difference 0.28/255. (2) **Topic labels on the canvas** once zoomed past 85% of the home distance: biggest topics first (memory atlas: hubs by children; reference: most-linked models), greedy no-overlap, never under a panel (`data-atlas-panel`), front side only, max 12. Bug found: home distance was taken from the first framing, which the restored camera skips; now computed from the atlas's size. (3) **Ranked name search** in the reference: exact (after an org prefix) → starts-with → contains, ties by links then length; "flux.1-dev" now finds black-forest-labs/FLUX.1-dev. 2 tests. (4) **Warm-start rebuilds** (Rust): families mostly present before start from their old shape at alpha 0.3 and keep their old centre if it's free (else search along its direction). On a Main copy: median move 3.25 (90th pct 8.5) in a 441-unit atlas, versus 111 with a cold rebuild. 1 test; 152 lib tests. Trialled in isolation, live restart (13 s).

---

## Ideas (not committed)

### 21. Calendar heatmap
- **Refs:** `ui/0224`. Repeats Activity; build only if a month view earns its space.
- **Log**
  - 2026-10-18: Listed.

### 22. Hero sparklines
- **Refs:** `ui/0239`. e.g. saved this week beside the hero numbers.
- **Log**
  - 2026-10-18: Listed.

### 23. "Just saved" toast
- **Refs:** `ui/0225` (bell). Must respect Reduce Motion and never steal focus.
- **Log**
  - 2026-10-18: Listed.

### 24. Loading skeletons
- **Log**
  - 2026-10-18: Listed; replaces "Loading…" text.

### 29. ⌘K command palette
- **Log**
  - 2026-10-18: Listed; after all views migrate.

---

## Blocked (needs backend)

### 25. Growth over time
- **Blocked by:** the API keeps no history of totals.
- **Log**
  - 2026-10-18: Listed.

### 26. Click a day → search
- **Blocked by:** `/v1/search_index` has no date filter.
- **Log**
  - 2026-10-18: Listed.

### 27. Instance cards
- **Log**
  - 2026-10-18: Listed as blocked (only one instance exists).
  - 2026-10-19: Built as part of #34 anyway: the view must handle many brains; tested with a mocked API of three.

### 30. Server-side daily counts
- **Does:** Replaces the Dashboard's 1.5 MB `/list?limit=2000` pull with a small per-day count endpoint.
- **Blocked by:** owner decision (Rust API change).
- **Log**
  - 2026-10-18: Flagged as tech debt when Activity shipped.
  - 2026-10-18: Measured: every `/list` call loads all ~22.9k memories behind the brain lock, so the Dashboard's four list calls queue (~150 ms each). A count endpoint and a `limit`-aware query would both help.
  - 2026-10-18: Precedent set by #17: additive read endpoints are trialled in isolation, then the live service is restarted with owner approval.

### 31. Linked view (legacy, partial fixes)
- **Does:** The graph view. Still on legacy Tailwind inside the shell; only targeted fixes so far.
- **Files:** `views/Linked.tsx`, `views/Linked.module.css`, `lib/linkedGraphModel.ts` (`visibleEntities`), `css-modules.d.ts`.
- **Log**
  - 2026-10-18: `initialEntity` prop so Dashboard chips open it pre-filtered.
  - 2026-10-18: Entity strip drew all ~27,060 entities as buttons. Now draws the top 40 plus a "Find an entity" box over the whole catalog (up to 40 matches); the selected entity is always kept visible. 4 tests. Browser-verified: 41 buttons instead of 27,061; "supa" → 108 matches; three forced hot updates with Linked open, no errors (this used to overflow the stack).
  - 2026-10-18: Added `css-modules.d.ts` so TypeScript files can import `.module.css` (tsc clean).
  - 2026-10-19: Removed with the old 2D view when #37 replaced it (with `LinkedGraph`, `LinkedFloater`, `linkedGraphModel`, `pointerClick`, `memoryTypeColors` and their tests; d3 dependencies dropped).

---

## Found along the way (not components)

- 2026-10-18: **Integration test `user_prompt_submit_hook_integration` failed on main.** Root cause: the test inherited the developer's shell, where `BRAIN_LLM_PROVIDER=ollama` makes `brain_api` build a blocking HTTP client (`OllamaClient::from_env`) inside its async startup (`main` → `open_brain_at` → `attach_llm`); reqwest's debug-build check panics on that ("Cannot drop a runtime…"). It also never isolated `HOME`, so it would have opened the real brain through `~/.brain/instances.json`. Checked: no test memories ever reached the real DB.
  - **Fixed 2026-10-18:** startup now opens the brain inside `spawn_blocking`, the same as the instance-switch path already did (`brain_api.rs`); the test uses `env_clear()` + a temp `HOME` for both processes. Full suite green (143 lib + all integration). Release builds were never affected, so the live server needs no restart; the next deploy picks it up.
- 2026-10-18: **"Phantom" Vite hot updates explained.** They were real saves made in Cursor (local history: `App.jsx` 22:28:36; `App.module.css` 22:28:59, 22:29:15, 22:29:38, 22:29:59, 22:31:38–58), matching every logged update. Vite reports "update App.jsx" when anything App imports changes (here `App.module.css`), and Tailwind re-reports `index.css`. Idle for 75 s and browsing all views: zero updates. Not a bug. Process note: two editors on the same files can overwrite each other; check Cursor history (`~/Library/Application Support/Cursor/User/History`) before editing shared files.
- 2026-10-19: **My dev server was killed (exit 137) around 00:17, when a separate `brain/rust/ui/atlas-preview/` Vite project started on port 5199.** Not mine; left untouched. The UI dev server now runs on **http://localhost:5198/static/**.
- 2026-10-19: **Tailwind removed.** The last legacy view is gone, so `tailwindcss`, `postcss`, `autoprefixer`, `tailwind.config.js`, `postcss.config.js`, the `@tailwind` directives, and the `LEGACY` wrapper in the shell are deleted (as the brand book planned). Also removed the dead `TimelineDrawer.jsx` and `Sidebar.jsx`. Main CSS 50.7 → 39.3 KB.
