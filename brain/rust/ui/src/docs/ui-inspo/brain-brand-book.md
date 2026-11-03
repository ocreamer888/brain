# Brain brand book

Date: 2026-10-18 (v2, same day: amended against Apple's Human Interface Guidelines)
Status: Adopted for the sample page. Same job as the Tendrium plan (`inspo/brand-book-plan.md`): this is the document the UI is built from. Tokens live in `src/styles/tokens.css`; the sample page is `sample.html` (dev server: `/static/sample.html`). The live views are not restyled yet.
Quality bar: Apple Design Resources and the HIG (section 16). Where this book and the HIG disagreed, the book changed, and section 16 says where.
Product: Brain, the personal long-horizon memory. This book covers the viewer in `brain/rust/ui` only. It does not restyle Tendrium.

The references in `inspo/` are the same set Tendrium used. The craft is shared (dark ground, one glow, glass chrome, grain, soft corners). The identity is not. Tendrium owns gold + jade and the node. Brain takes the other half of `IMG_0240`: pale lamp-light and the blue corner that plan left behind.

---

## 0. Why we are doing this

The viewer today is a dark utility. It is readable and it is flat. The code shows why:

| Fact (measured 2026-10-18) | Effect |
| --- | --- |
| 228 `zinc-*` utilities across 11 of 24 source files under `brain/rust/ui/src` (docs excluded) | One grey scale does borders, text, cards, hovers, and empty states. Nothing is the brand |
| Tailwind tokens `surface #0a0a0a`, `panel #111111`, `border #222222` in `tailwind.config.js` are unused. Screens use `bg-black`, `bg-zinc-950`, `bg-zinc-900` | The token file does not control the look |
| 14 hard-coded hexes, all in the Linked graph and `memoryTypeColors.ts` | The only real color is a rainbow on memory types |
| Type chips in `MemoryCard.jsx`: amber, blue, green, purple, pink, red, cyan, zinc | Eight hues, none of them a system. `knowledge` has no color in either map |
| No font is loaded. `index.html` sets `bg-black text-white`. Mono is `ui-monospace` | The face is whatever the browser ships |
| Nav icons in `App.jsx` are single unicode glyphs (`◉ ⌕ ⚭ ✦ ▦ ⧉`). `Sidebar.jsx` is a second nav that nothing imports | There is no icon set |
| Radius is Tailwind `rounded` (4px) on cards. No glow, no glass, no grain | The references' depth has nowhere to live |

The book fixes the cause: one color system with real tone ranges, color that carries meaning, one font, one icon set, one surface model, and a visual idea (the lamp) that belongs only to Brain.

---

## 1. Brand idea

**Brain keeps what mattered and brings it back.**

A memory is a point of light that stays. The page is near-black. Recall is a pale lamp rising in that dark. A link is a thin trace between two points, drawn only when the data really connects them.

Three words to judge every screen against: **quiet · lasting · exact.**

Tendrium's three words are connected · calm · precise, and its mark is a living root of nodes. Brain does not borrow that mark. Connection here is a trace you can point at, not a colony.

---

## 2. Design principles

These decide every case the book does not cover.

1. **Quiet ground. Light comes from the lamp.** The page is near-black in dark and warm paper in light. Color arrives as light: a pale cream glow, a dusk-blue trace, never flat paint. Dark is the signature; light must feel like the same room with the lights on.
2. **Dusk leads, lumen supports, neutrals carry the rest.** Dusk is the everyday brand color (active nav, links, live, the thing you just found). Lumen is the lamp: the one hero, the primary button, the headline number. Neither color does everything (the current problem, where zinc does everything).
3. **Color means something.** A hue is a kind of memory or a system state (section 5.6). Decoration never borrows a state color.
4. **One glow per screen.** One hero card may glow. Everything else is quiet frosted glass or a plain surface. Rarity keeps it premium.
5. **Glass is for chrome, not for reading.** Navigation, docks, popovers, chips, and overlays can be frosted. Memory text, tables, and the graph canvas sit on solid surfaces so they stay sharp.
6. **The recalled line is the hero.** A screen's most important sentence or number is large and light. Labels stay small and quiet. A memory's body is 14px and easy to read for a long time.
7. **Traces show real links.** A line joins a memory to an entity only when an edge exists. Unlinked points stay dots. A gap stays a gap.
8. **Motion reveals and confirms. It never delays.** Product-speed timing (section 11). Nothing loops except a loader.
9. **One idea per panel.** Every card answers one question. If it needs two, it becomes two cards.

---

## 3. Logo

### 3.1 Inventory

There is no logo. No SVG, no app icon, no wordmark file in this repo. The viewer prints the word "Brain" (or the active instance name) in the sidebar, semibold, 14px.

Until a mark is drawn, the product uses the word **brain** in Geist, weight 500, tracking -0.03em, in `#F7F4EE` on dark and in `#1E1910` on the lamp. No fake icon beside it.

### 3.2 The mark to draw

One rounded tile of light, the `IMG_0240` lamp reduced to a symbol: dark at the top, pale cream at the bottom, the word or a single bright point sitting in the light. Not seven nodes. Not a brain illustration. Not a letter B built from circuits.

Proposed files, drawn after this book is accepted:

| File | What it is |
| --- | --- |
| `brain-wordmark-light.svg` | Word only, `#F7F4EE`, for the dark shell |
| `brain-wordmark-ink.svg` | Word only, `#1E1910`, for the lamp and any light ground |
| `brain-mark-light.svg` | Lamp tile, for the app icon on dark |
| `brain-mark-ink.svg` | Same tile, ink on `#F7F4EE` |
| `brain-lockup-light.svg` | Mark + word, for the shell header |
| `brain-lockup-ink.svg` | Mark + word, for light grounds |

### 3.3 Rules

- **Clear space:** an empty margin on every side equal to the cap-height of the word "brain". Nothing touches, crosses, or overlaps it.
- **Always visible:** the logo is never covered, cropped, faded behind content, or animated out of view while the screen is in use.
- **On gradients:** allowed when the logo keeps at least **3:1** contrast against the worst spot of the gradient behind it. Check the area under the mark, not the average.
- **Contrast facts (measured):** `#F7F4EE` on `#080808` = 18.2:1. `#1E1910` on `#EEE5D2` (lumen-100) = 14.0:1. `#E4D6B9` (lumen-200) on `#F7F4EE` = 1.3:1, so the pale lamp colors fail on a light ground. **On light ground use the ink word, never the cream one.**
- **Minimum size:** wordmark 72px wide on screen; mark 24px.
- **Never:** recolor outside the variants above, stretch, rotate, add a drop shadow or an outer glow to the mark itself, put it on a busy photo, or rebuild the word in another font.

---

## 4. Typography

**Geist** for everything, **Geist Mono** for ids, timestamps, and scores. Both are open source (SIL Open Font License), published by Vercel.

Installed: `src/assets/fonts/Geist-Variable.woff2` and `GeistMono-Variable.woff2`, from Vercel's `geist` 1.8.1 package, license in `Geist-OFL.txt`. Local `woff2`, no third-party request, no npm dependency.

Why not Apple's SF Pro: Apple distributes SF Pro and SF Symbols for designing apps on Apple platforms. We could not retrieve the license text on 2026-10-18 to confirm web embedding is allowed, so we do not ship either. The HIG's own advice ("minimize the number of typefaces") is met with one family plus its mono.

| Role | Size / weight | Use |
| --- | --- | --- |
| Display | 2.5–3.5rem (40–56px), **weight 400**, tracking -0.03em, leading 1.05 | The one headline on a screen: a count, or the title of the memory you opened. Its size is the highlight, not a thin weight |
| KPI number | 28–32px, weight 500 | Dashboard counts. The unit or label stays 11px above it |
| H1 (screen title) | 28px, 500, -0.02em | "Search", "Linked", "Instances" |
| H2 (panel title) | 18px, 500 | Card and section titles |
| Body | 14px, 400, line height 1.55 | Memory text. This is the size people read for a long session |
| Small / meta | 12px, 400–500 | Project, date, helper text |
| Label | 11px, 500, uppercase, +0.06em | Eyebrows, column headers, type names |
| Mono | Geist Mono 12px | Memory ids, timestamps, eval scores |

Rules:

- **No light weights.** The HIG advises against Ultralight, Thin, and Light. Display is 400, at most once per screen, on the glow hero or the single headline figure. Everywhere else, numbers are weight 500 so they stay sturdy in tiles.
- **Sizes are in rem** (table shows px at the default 16px root) so text grows with the browser's text size. The HIG asks that people can enlarge text to 200%.
- **Tracking changes with size:** negative on display and titles, 0 on body, positive only on uppercase labels.
- Tabular figures (`font-variant-numeric: tabular-nums`) wherever numbers line up.
- Two weights per panel at most.
- Memory body is never below 14px. Meta can be 12px. Nothing important is 10px.

---

## 5. Color system

### 5.1 How it is built

Each brand color is an 11-step tone range, listed **from dark to light** (950 darkest → 50 lightest), generated in OKLCH so the steps are perceptually even. Hue stays fixed. Chroma peaks in the middle and fades at both ends. Contrast below is measured against the page `#080808`. Text needs ≥ 4.5:1. Large numbers and icons need ≥ 3:1.

These ramps were computed on 2026-10-18, not sampled by eye. They are **proposed**. Section 14 has to accept them before they become tokens.

### 5.2 Lumen (the lamp). Hue 86°. The pale light inside a glow

`lumen-300` `#D9C79F` is within 1.00:1 of Tendrium's logo gold `#DAC6A5`. It is the mid-tone of a glow gradient only. It is never a flat fill, never a button, never body text. Brain's visible lamp is the paler end: `lumen-100`.

| Step | Hex | On #080808 | Role |
| --- | --- | --- | --- |
| 950 | `#1E1910` | 1.2 | Ink on the lamp. Button text. Where a glow fades into black |
| 900 | `#2D2719` | 1.4 | Lumen-tinted surface, deep |
| 800 | `#483E28` | 1.9 | Lumen-tinted surface |
| 700 | `#655635` | 2.8 | Dark end of a lumen glow |
| 600 | `#857043` | 4.2 | Quiet lumen icons. Large text only (under 4.5:1) |
| 500 | `#A18A57` | 6.0 | Quiet lumen icons on the page only. 4.4:1 on raised, so not text |
| 400 | `#BAA372` | 8.2 | **Lumen text on dark** (`--lamp-text`), when a sentence must be warm. 6.0:1 on raised |
| 300 | `#D9C79F` | 12.0 | **Glow mid-tone only.** Too close to Tendrium gold to use flat |
| 200 | `#E4D6B9` | 13.9 | Bright shoulder of the glow |
| **100** | **`#EEE5D2`** | **16.0** | **The lamp.** Primary button fill. Headline figures |
| 50 | `#F6F1E7` | 17.8 | Brightest point of a lumen glow |

Lumen gradient, dark to light: `#080808 → lumen-700 → lumen-300 → lumen-50`. The glow rises out of black, passes through the warm mid-tone, and peaks in near-white cream.

### 5.3 Dusk (brand lead). Hue 248°. The blue corner of `IMG_0240`

Richer than a grey-blue (chroma peaks at 0.09, against the 0.04 of a flat steel). This is the color people see all day: active, live, found.

| Step | Hex | On #080808 | Role |
| --- | --- | --- | --- |
| 950 | `#0D1823` | 1.1 | Where a dusk glow fades into black |
| 900 | `#172737` | 1.3 | Dusk-tinted surface, deep |
| 800 | `#294158` | 1.9 | Dusk-tinted surface |
| 700 | `#395D7D` | 2.9 | Dark end of a dusk glow |
| 600 | `#4D7AA3` | 4.4 | Dusk borders, quiet dusk icons. Large text only |
| **500** | **`#6295C4`** | **6.3** | **Dusk core.** Active nav, links, live, "found" |
| 400 | `#7FACD8` | 8.4 | Dusk icons, hover of dusk-500 |
| 300 | `#A0C4E7` | 11.0 | Dusk text on dark when it must be lighter |
| 200 | `#BDD7F1` | 13.5 | |
| 100 | `#D9E9F9` | 16.2 | |
| 50 | `#EDF5FE` | 18.2 | Brightest point of a dusk glow |

Dusk gradient, dark to light: `#080808 → dusk-800 → dusk-500 → dusk-300`.

### 5.4 Neutrals (`#080808` → `#F7F4EE`)

Very slightly cool (hue 250°, chroma 0.008) so greys drift toward dusk, not toward gold.

| Step | Hex | On #080808 | Role |
| --- | --- | --- | --- |
| — | `#080808` | — | **Page ground** |
| 950 | `#0D1014` | 1.1 | Sunken areas, graph canvas |
| 900 | `#171A1E` | 1.2 | Surface (cards, memory list) |
| 800 | `#25282B` | 1.4 | Raised surface, hover rows |
| 700 | `#373A3E` | 1.8 | Borders, dividers |
| 600 | `#4F5256` | 2.6 | Disabled, placeholder |
| 500 | `#696C71` | 3.8 | Quiet icons |
| 400 | `#898D92` | 6.0 | Tertiary: icons and placeholder only. 4.4:1 on raised, so never text |
| 300 | `#AAAEB3` | 9.0 | Secondary text: meta, labels, helper (6.6:1 on raised) |
| 200 | `#CCD1D5` | 13.0 | Body text: memory text |
| 100 | `#E5EAEE` | 16.5 | Headings, when they are not the lamp |
| — | `#F7F4EE` | 18.2 | **Primary text.** Warm paper, so a long read is not cold white |

**Both appearances, following the system.** Decided 2026-10-18. The HIG expects apps to respect the system light/dark choice and allows dark-only only "in rare cases". There is no in-app switch (HIG: avoid app-specific appearance settings); the sample page has a preview switch only. Light values are in 5.8.

### 5.5 Distribution

- **~80% neutrals** (ground, surfaces, memory text).
- **~12% dusk:** active navigation, links, the live dot, a selected row, the memory you just found, graph selection.
- **~8% lumen:** the one glowing hero, the primary button, the single headline number.
- They meet in that one glow (a dusk-to-lumen light fading into black) so the brand reads as one lamp, not two flat paints.
- `lumen-300` never appears as a flat chip. If a screen starts to look like Tendrium, the lamp has leaked.

### 5.6 Memory and state colors

People already read these hues as feelings, so status lands before the word. Every state also has an icon and a label. Color alone fails for color-blind users, and the type name is already the label we have.

Types are grouped by what they ask of you. Two types can share a hue when the word and the icon differ. That is the point: the rainbow in `MemoryCard.jsx` goes away.

| Signal | Types | Text on fill | Why |
| --- | --- | --- | --- |
| **Rely** | `fact`, `knowledge` | lumen-100 `#EEE5D2` on lumen-800 `#483E28` (8.4:1). Light: `#625334` on `#F4E3BF` | Kept on purpose. The lamp means "you can stand on this". v1 used lumen-950, which disappeared on a card |
| **Use** | `decision`, `solution` | dusk-300 `#A0C4E7` on dusk-900 `#172737` (8.4:1). Light: `#2E597F` on `#DCEEFF` (6.2:1) | A choice or a fix you can apply again. Dusk, because using the brain is the lead action |
| **Notice** | `pattern` | amber `#D1A662` on `#362913` (6.3:1). Light: `#714E04` on `#FAE9CE` (6.3:1) | A recurrence. Amber is attention without alarm. **Open:** too close to Rely on screen (hue 78° vs 86°), see 14.10 |
| **Lesson** | `error_lesson` | clay `#E99989` on `#402621` (6.2:1). Light: `#843D30` on `#FFE4DF` (6.5:1) | Something failed and was kept. Muted, not a siren |
| **Spoken** | `conversation` | neutral-200 `#CCD1D5` on neutral-800 `#25282B` (9.6:1). Light: neutral-800 on `#EBE9E5` (12.2:1) | Talk is not a status. Keep it quiet |
| **Frame** | `project_context` | neutral-300 `#AAAEB3` on neutral-800 `#25282B` (6.6:1). Light: neutral-600 on `#EBE9E5` (6.5:1) | The shelf a memory sits on. Quieter than spoken |
| **Raw** | `episode` | neutral-400 `#898D92`, no fill, dashed outline (5.2:1 on a card). Light: neutral-600 | Source tape. Not a durable claim, so it must not look like one |
| **Live** | stream connected | dusk-500 `#6295C4` dot + the word "live" | The feed is open. Dusk, not the current emerald |
| **Fail** | eval fail, request error, destructive confirm | red `#F97770` on `#3F1917` (5.8:1 on the fill, 7.5:1 on the page). Light: `#9B1E22` on `#FFE4E1` (6.7:1) | Reserved for real failure so it keeps its power. v1's `#EA9891` was nearly identical to clay `#E99989`; fail is now the saturated one |
| **Info** | helper, empty, waiting | neutral-300 on neutral-800 | Information is not an emotion |

Amber, clay, and red sit outside the brand ranges on purpose. They are states, never decoration, so the brand stays dusk + lumen.

Icons, one per type, drawn with the set in section 7: fact = small point, knowledge = book, decision = check, solution = wrench, pattern = repeat, lesson = flag, conversation = lines, project = folder, episode = reel. The word is always visible next to the chip in lists. On the graph, the tooltip carries the word.

`goodDirection` does not apply. Brain has no "up is good" metric except eval deltas: a gap that beats the baseline is dusk + ↑, a regression is clay + ↓, no change is neutral + →.

### 5.7 Data visualization

Categorical order, max 6 series: `dusk-400`, `lumen-200`, amber `#D1A662`, `dusk-700`, `neutral-400`, clay `#E99989`. **Superseded for the first two slots (2026-10-19):** chart marks need OKLCH L 0.48–0.67 (dark) / 0.43–0.77 (light) and C ≥ 0.10, which dusk-400 and lumen-200 fail. Validated with the dataviz palette script: `--chart-1` dusk `#5291CC` dark / `#2D6DA5` light, `--chart-2` amber `#BF8532` dark / `#A2650A` light (CVD ΔE ≥ 20, ≥ 3:1 on tiles). Series 2 is dashed. Validate any further slot the same way before use. Sequential (a heat of salience or degree): `dusk-950 → dusk-300`. Diverging (eval, above and below a baseline): `clay ← neutral-600 → dusk`. Gridlines `neutral-700` at 40%. Tracks `neutral-800`.

The Linked canvas is not a chart palette. Memory nodes use the signal color of their type at the 400/500 step. Entity nodes are `neutral-500` with a `neutral-300` ring. Selection is `#F7F4EE`. Edges are `neutral-700`, and the edge under the selection is dusk-500.

### 5.8 Light appearance and the role table

Each role is declared once in `tokens.css` with `light-dark(light, dark)`, so components never branch on theme. Light ground is warm paper, the same `#F7F4EE` that is primary text in dark. **The lamp inverts:** on dark it is cream with ink text; on light it is warm ink `#1E1910` with paper text.

Ratios were measured in the browser on the sample page (the page re-measures live), against ground / surface / raised. Floor: 4.5:1 for text, 3:1 for icons. The HIG asks for 7:1 on small custom text; primary, body, and secondary meet it on the ground and on cards; raised rows dip to 6.5–6.6:1 and stay above AA.

| Role | Dark | Light | Dark ratios | Light ratios |
| --- | --- | --- | --- | --- |
| `--bg-ground` | `#080808` | `#F7F4EE` | | |
| `--bg-sunken` | neutral-950 | `#EFECE7` | | |
| `--bg-surface` | neutral-900 | `#FFFFFF` | | |
| `--bg-raised` | neutral-800 | `#EBE9E5` | | |
| `--fg-primary` | `#F7F4EE` | neutral-900 | 18.2 / 15.9 / 13.5 | 15.9 / 17.5 / 14.4 |
| `--fg-body` | neutral-200 | neutral-800 | 13.0 / 11.3 / 9.6 | 13.5 / 14.8 / 12.2 |
| `--fg-secondary` | neutral-300 | neutral-600 | 9.0 / 7.8 / 6.6 | 7.2 / 7.9 / 6.5 |
| `--fg-tertiary` (icons, placeholder) | neutral-400 | neutral-500 | 6.0 / 5.2 / 4.4 | 4.8 / 5.3 / 4.3 |
| `--accent-text` (links) | dusk-400 | dusk-700 | 8.4 / 7.3 / 6.2 | 6.3 / 6.9 / 5.7 |
| `--lamp-text` (warm text) | lumen-400 | lumen-700 | 8.2 / 7.1 / 6.0 | 6.5 / 7.2 / 5.9 |
| `--accent` (fills, live dot) | dusk-500 | dusk-600 | | |
| `--lamp` / `--on-lamp` | lumen-100 / lumen-950 | `#1E1910` / `#F7F4EE` | 14.0 on fill | 15.9 on fill |

v1 measured contrast only against the page. On cards, v1's secondary text (neutral-400) fell to 4.4:1 on raised rows and its warm text (lumen-500) to 4.4:1, both under AA. Text moved one step lighter; neutral-400 is now icons-only.

Never use `--fg-tertiary` for words. Meta text (dates, ids) is secondary.

---

## 6. Surfaces, shape, and depth

### 6.1 Five depths

| Level | What | Recipe |
| --- | --- | --- |
| 0 Ground | The page, behind the panel | `#080808` / paper, plus an **ambient backdrop** (2026-10-18, ui/0225 · 0224): three blurred blobs of the lamp's light (`--ambient-a/b/c`) and 8% grain, so the frosted panel has something to frost |
| 0.5 Panel | The one floating app panel | `--material-panel` (dark `rgb(38 40 44/.6)`, light warm grey `rgb(240 237 231/.66)`) + blur 40px + rim + soft shadow, radius 40px. The header is the same material denser (`--material-header`) |
| 1 Tile | Cards and lists on the panel | `--material-tile`: a lighter translucent layer (dark `rgb(247 244 238/.075)`, light `rgb(255 255 255/.82)`) + `--material-line` border + top highlight. HIG standard material for the content layer; glass stays for chrome. **Lamp tone:** one cream tile per screen (`Tile tone="lamp"`, ui/0224 · 0236) switches its contents to the light scheme, so every role inside resolves to validated light values |
| 2 Raised | Hover, popovers, menus | `neutral-800` + 1px border `rgba(247,244,238,0.10)` |
| 3 Glass | Nav dock, sticky view header, search pill, popovers | Dark `rgba(247,244,238,0.06)`, light `rgba(255,255,255,0.62)` + `backdrop-filter: blur(20px) saturate(140%)` + top highlight. **Only where content passes under it:** glass over a flat ground is just a grey bar. The sticky header is the main glass surface; rows scroll beneath it |
| 4 Glow | **One** hero card per screen | Mesh: dusk and lumen light fading into black + 3% grain + a glass border |

Depth comes from lighter layers and borders. One drop shadow exists: under the floating panel (and the lamp tile), as in the references. Contrast is measured on rendered pixels, not tokens, because text now sits on translucent layers: 2026-10-18, Dashboard and Search, both modes, every text run ≥ 5.58:1 (the episode chip was lifted to neutral-300 to get there).

Following the HIG's materials guidance: glass is the functional layer (navigation, controls) and never the content layer; it is used sparingly; text on glass is primary or secondary, never tertiary. Two system settings change it:

- **Reduce Transparency** (`prefers-reduced-transparency`): glass becomes a solid raised surface, blur 0.
- **Increase Contrast** (`prefers-contrast: more`): lines go to 30–45% opacity, secondary text becomes body, tertiary becomes secondary, glass becomes solid.

Scroll edges: where content meets floating chrome, fade it with a mask (`.scroll-edge`), not a hard 1px rule.

### 6.2 Radius ladder

| Radius | Use |
| --- | --- |
| 999px (pill) | Buttons, chips, tags, tabs, search, the nav dock |
| 40px | The app panel (squircle where supported) |
| 28px | Hero cards, modals |
| 24px | Standard cards and tiles |
| 14px | Inner tiles, inputs, dropdowns |
| 8px | Table-row hover, mini tiles, the graph's selected halo |

An inner shape's radius = outer radius − padding, so nested corners stay parallel.

### 6.3 Texture

- **Grain:** 3% film grain on glows and on the ground (`IMG_0240`, `IMG_0242`, `IMG_0243`).
- **Dot matrix:** a faint dot field for micro-charts and for the empty graph, the way `ui/0232` and `ui/0234` use dots as data.
- **Photography:** not in v1. Slots that want a picture use a brand glow instead. Rules, if we add pictures later, are in 6.4.

### 6.4 Photography (later, not v1)

Brain is a private tool. It does not need a campaign set to ship the viewer. If a picture is ever used (login, an empty state, a rare hero), it is made by us: generated in-house, reviewed before use, never stock, never a real person presented as a user.

Subjects that fit the lamp, and not Tendrium's hospitals and tenders:

- A dark room with one warm practical light.
- Stone, paper, ink, dust in a beam (`ui/0229` is the mood: an object, a glass dock, black around it).
- Macro of fiber or grain. No faces, no hands holding products, no logos.

Treatment, when that day comes: one grade (dusk-black shadows, lumen highlights, 3% grain), text always on a scrim that holds ≥ 4.5:1, at most one picture on a screen, never behind a memory list or the graph. Until then, every photo slot is a level-4 glow.

### 6.5 Mesh surfaces

The premium in `0231`–`0235`, `0240`, and `0245` comes from layers, not from brighter paint. A mesh is five layers:

1. **Tone fill:** 4–6 large radial blobs from lumen and dusk, blurred together (~42px). They mix in the middle. That mix is the only place the two brand colors share a surface.
2. **Milk:** a soft white wash (~10%) in the middle, never over a line of memory text.
3. **Rim:** a 1px inner highlight plus a brighter top edge.
4. **Vignette:** slight darkening at the edges.
5. **Grain:** fine film grain, soft-light, ~22% on the mesh (the page grain stays at 3%).

**Contrast rule:** mid-tones never sit behind text.

| Type | Text | Use |
| --- | --- | --- |
| **Deep** | `#F7F4EE` | The default hero. Lamp at the bottom, dusk at the top, black at the edges |
| **Light** | `#1E1910` | A rare pale tile (a primary summary). Not the page |
| **Split** | Paper on the dark half, ink on the light half | The `IMG_0240` tile, used for the mark and for one marketing-style empty state |

The bright blob sits behind a number or a single word, never behind a paragraph. Every text node on a mesh must pass WCAG AA (4.5:1, or 3:1 for large text) against the pixels behind it, not against the average.

**Motion:** on hover the blob layer drifts with a transform (scale 1.07, slight turn, 1.8s). Off under `prefers-reduced-motion`.

**Build (as shipped 2026-10-18, ported from sicop-health `ds/mesh.module.css`):**

- The blobs live on their own layer (`.mesh-bg`), oversized to 150% of the card (`inset: -25%`) and blurred 42px, so they melt with no edges. Blob positions are in that layer: the card shows its 17%–83% band.
- **The recipe is `IMG_0240`, sampled, not recalled** (2026-10-18): warm black top `#210903`, an orange ember band `#CC722B` through the middle, cream `#F6D49B`→`#F8E0B1` filling the lower half, a faint peach on the right, and one low-chroma cool mist in the top-right corner. It is **not bands**: one radial blob draws a dark cap in the upper-left whose edge turns umber → ember → honey, so the ember wraps the dark like a ring; the cool mist sits on top of it at the right; cream is the base everywhere else. Matched by measuring both images in a 3×10 grid; the lower half is within ±0.03 lightness of the reference. Blob layer uses `saturate(1.2)` so the ember stays orange through the blur.
- **Gradient-only tones** (`--g-*` in `tokens.css`), used only inside a mesh, never as flat UI color: night, umber, mist (dusk-tinted, so the corner stays Brain), mist-warm, ember, ember-deep, cream, cream-light, peach, core. Each has a light and a dark value; light mode is the same room with the lights on.
- **Orange lives only here.** The ember is the one place orange appears in Brain. It is never a chip, a button, a border, or text.
- **Split layout.** Label and number sit on the dark top in `--fg-primary`; the caption and the arrow sit in the lamp in ink (`--on-glow-soft` `#483E28`, ≥ 7.7:1 measured on the rendered cream in both modes). Nothing sits on the ember band. The number measured ≥ 10.6:1 against the pixels behind it.
- Milk is white in light mode but warm and 5% in dark: a white wash over a dark base reads as grey haze.
- Grain is white-only noise (color matrix), 140px tile, soft-light 22%, laid over the content.
- Squircle corners (`corner-shape: squircle`) where the browser supports them.

---

## 7. Iconography

Reference: `ui/IMG_0229.JPG` (the glass dock). We draw our own set in that style: `src/components/brand/Icon.jsx`, 25 icons, inline SVG. The unicode in `App.jsx` is retired when the shell is rebuilt. SF Symbols is not used, for the license reason in section 4.

| Property | Rule |
| --- | --- |
| Grid | 24×24, 2px safe padding |
| Stroke | 1.5px, round caps, round joins |
| Corners | Soft, about 2px on shapes |
| Detail | One idea per icon |
| States | Inactive = outline. Active = filled, sitting in a lighter glass circle |
| Hit target | Never smaller than 36px with a mouse (HIG floor on macOS is 28pt) and 44px on touch (`pointer: coarse`). The dock buttons are 44px. Icons can be 20–24px inside that target |
| Color | `neutral-300` inactive, `#F7F4EE` active, dusk-400 for the active nav icon, lumen-100 only on the primary button's icon |
| Trace accent | A few icons may end a stroke in a 3px dot (search, linked). Not all of them. The dot is a point of light, not a Tendrium node |

First set, from the views that exist:

| Area | Icons |
| --- | --- |
| Navigation | Dashboard, search, linked, curate, eval, instances |
| Actions | Filter, close, back, more, add, archive, delete, edit, switch, refresh |
| Memory | The nine type icons in 5.6, plus copy-id, open-timeline, open-neighbors |
| States | Live dot, pass, fail, empty, reconnecting |

---

## 8. The trace

Tendrium's section 8 is a node grammar measured from its logo. Brain has no such logo, and it must not grow one. The trace is the equivalent: a point, and a line that is allowed only when the data agrees.

### 8.1 Grammar

| Element | Rule |
| --- | --- |
| Point | A circle. Memory points are 8px in a list spark and 18–28px on the graph. Entity points are one step smaller and hollow |
| Trace | A 1px line, `neutral-700`. It does not pinch, branch, or look liquid. Selected trace is dusk-500 at 1.5px |
| Gap | No edge in the data means no line. Do not decorate a layout with connecting curves |
| Selection | A `#F7F4EE` ring, 2px, plus the dusk trace to its real neighbors |
| Scale | The same point-and-line from a 16px icon dot to the full Linked canvas |

### 8.2 The meaning rule

**A trace means a real link.** On Linked, that is a row in `edges` (relation `mentions`): memory ↔ entity. On a memory card, the neighbor list is the same rule in text. Points with no edge stay quiet. This is also why `episode` is absent from the graph: it is excluded from the durable link set, so it never grows a trace.

### 8.3 View marks

One small mark per view, built from a point and at most one line. Color is dusk or lumen, not a new hue.

| View | Mark |
| --- | --- |
| Dashboard | One filled point (the lamp) |
| Search | A point inside a thin ring |
| Linked | Two points and one trace. The only mark that contains a line |
| Curate | A point with a small check |
| Eval | A tick ring |
| Instances | Two separated rounded squares. The gap is the point: brains do not share a wall |

Used at ≤ 22px inside pills, tabs, and headers.

### 8.4 Patterns

- **Star field:** quiet points at 8–14% opacity, no lines, behind login and empty states.
- **One trace:** a single line between two points, for the Linked empty state ("nothing is linked yet") and for a memory that has neighbors.
- Never a field of branching nodes. That pattern belongs to Tendrium.

### 8.5 Where the trace is the data

| Use | What connects | Where |
| --- | --- | --- |
| Memory ↔ entity | An edge that exists | Linked canvas, the neighbor block on a card |
| Ego | The selected point and its one-hop neighbors | Linked, ego mode |
| Timeline | Memories ordered in time, drawn as a column, not a web | Timeline drawer |
| Instances | Nothing connects. Cards are separate on the ground | Instances |

There is no agent orb and no liquid loader. The wait state is a single dusk point that breathes, 16px, and it stops the moment data arrives. Reduced motion: a still point.

Never: traces behind tables or paragraphs, a looping trace on a working screen, more than one decorative trace pattern per screen.

---

## 9. Components

**Reusable** = used on more than one view. **Specific** = built for one view.

| Component | Type | Reference | Where in Brain |
| --- | --- | --- | --- |
| Glass nav dock (icons, active filled circle, search as its own circle) | Reusable | `ui/0229` | App shell. Replaces the zinc sidebar |
| Pill tab bar | Reusable | `ui/0224`, `ui/0234` | Type filters on Search and Curate |
| Search pill | Reusable | `ui/0179` | Search, Curate, Instances |
| Filter chip row | Reusable | `ui/0224`, `ui/0236` | Search type filter. The missing types (`decision`, `error_lesson`, `knowledge`, `episode`) join this row |
| Type chip (color + icon + word) | Reusable | section 5.6 | Every memory row |
| Primary button (lumen-100 pill, ink text) | Reusable | `ui/0174` | One per screen: save instance, confirm curate, retry |
| Quiet button (glass pill) | Reusable | `ui/0229` | Archive, cancel, secondary |
| Arrow chip (↗ in a circle) | Reusable | `ui/0231` | Open a memory from a card |
| KPI tile (label, one number) | Reusable | `ui/0234` | Dashboard counts |
| Glow hero | Reusable, one per screen | `ui/0231`, `IMG_0240` | Dashboard: total memories. Search: the top hit, when a query is active. Linked: the selected memory |
| Memory row (type chip, project, date, two-line body) | Reusable | `ui/0178` | Dashboard feed, Search, Curate |
| Memory reading (full text, meta, neighbors) | Reusable | `ui/0238` popover | Timeline drawer, Linked floater, expanded search card |
| Solid list | Reusable | `ui/0237` | Any long memory list. No glass under the text |
| Graph canvas | Specific | section 8 | Linked |
| Eval score row (name, percent, delta, pass/fail) | Specific | `ui/0234`, `ui/0246` | Eval |
| Instance card (name, description, tags, active mark, actions) | Specific | `ui/0178` | Instances |
| Confirm dialog (destructive, red only on the confirm) | Specific | — | Archive and delete |
| Empty state (one line, a star field or a glow, no illustration of a brain) | Reusable | `IMG_0244` rebuilt in dusk and lumen | Every view's empty case |

The orange in `IMG_0244` and `ui/0245` is not in the palette. The horizon-light and the short centered line are.

---

## 10. Layout

| Pattern | Reference | Use in Brain |
| --- | --- | --- |
| **App shell:** floating rounded panel on the ground (16px inset, 28px radius), glass icon dock on the left, screen title, instance name on the right | `ui/0224`, `ui/0234`, `ui/0229` | Every view |
| **Dashboard (as sampled 2026-10-18):** glass header (title + instance line left; search, live, instance right). 12-column bento: glow hero (7 cols, stat strip in the lamp) beside "What it keeps" (5 cols, ranked type bars); Latest (8 cols, its type filters inside it) beside Eval (4 cols, pass count + run strip) | `ui/0225`, `ui/0179`, `ui/0239`, `ui/0237` | Dashboard |
| **List:** title, search pill, type chips, solid rows | `ui/0179`, `ui/0237` | Search, Curate |
| **Canvas + floater:** graph on `neutral-950`, glass floater for the selected memory's text | `ui/0238` | Linked |
| **Score sheet:** title, pass/fail summary, rows with a number and a delta | `ui/0237`, `ui/0246` | Eval |
| **Card grid:** one card per instance, the active card is the glow | `ui/0178` | Instances |
| **Reading:** a single column, 14px body, meta above, neighbors below | — | Any opened memory |

Spacing: 4px base. Card padding 20–24px. Gaps between tiles 12–16px. Section gaps 32–48px. Memory text column max 68ch.

The dock lists the six views that exist today: Dashboard, Search, Linked, Curate, Eval, Instances. No new destinations in this pass.

---

## 11. Motion

A tool people leave open all day. Fast, and almost still.

| Move | Timing |
| --- | --- |
| Hover / press | 120–180ms, ease-out |
| Popover, floater, dialog | 200–240ms |
| Number count-up on first load of Dashboard | 600ms, once per visit |
| First-load reveal (tiles rise 12px and fade) | 400ms, 40ms stagger, once |
| View change | Cross-fade ≤ 200ms. No loader on switching views |
| Live dot | Breathes only while the stream is connecting or reconnecting. Solid when live |
| Wait point | One dusk point, loops only while a request is open |

Press feedback starts on pointer-down (scale 0.97, 140ms), not on release. Nothing blocks input while it animates.

`prefers-reduced-motion`: no count-up, no reveal, no breathing, no mesh drift, no press scale. The live state is a still dusk point. Opacity and color changes stay, because they carry meaning.

---

## 12. Reference map

"Take" is what we use. "Leave" is what we do not. Tendrium already claimed gold, jade, and the node from this same folder. Those are in the leave column here on purpose.

### Art direction

| Ref | Take | Leave |
| --- | --- | --- |
| `IMG_0240` (aurō) | **Master direction, and the hero glow recipe itself** (6.5): warm black, ember band, cream lower half, cool corner, grain | Using its warm mid-tone or its orange as a flat color |
| `IMG_0242` (arounda) | Light from one corner, palette shown as glass pills | Cyan and mint |
| `IMG_0243` (exploda) | A soft band of light, palette cards | Lime |
| `IMG_0244` | Horizon light inside a black card, thin icons, one short line | Orange |
| MedAxis | The discipline of one grammar used on purpose | The node grammar itself, and per-service rainbows |

### UI references

| Ref | Take | Where |
| --- | --- | --- |
| `ui/0229` | Icon dock and icon style | Shell |
| `ui/0224`, `ui/0236` | Title, KPI strip, chips, nested tiles | Dashboard, filters |
| `ui/0234`, `ui/0239` | KPI tiles, a quiet score | Dashboard, Eval |
| `ui/0237` | Dense dark data, done calmly | Search results, Eval rows |
| `ui/0231`, `ui/0233` | One glow card, arrow chip, a bottom action | Hero, memory actions |
| `ui/0238` | A floating info card over a canvas | Linked floater |
| `ui/0174` | Glass card, split button | Dialogs, primary + quiet buttons |
| `ui/0178` | A hero tile plus a list with a selected row | Instances, feed |
| `ui/0179` | Search pill, chips | Search, Curate |
| `ui/0245` | A calm centered empty state | Empty states, recolored dusk and lumen |
| `ui/0246` | Tick-ring stat | Eval summary |
| `ui/0221`, `ui/0228` | Card anatomy: title, meta, one action | Memory row |
| `ui/0180` | A chart that stays readable when color is not enough | Eval bars, always with a label |

AgroControl and GeoSales, cited in the Tendrium plan, are the same lesson for us: a premium shell around a working list. We do not take their maps, funnels, or kanban. Brain has no territory and no pipeline.

---

## 13. Screen map

Routes are views inside one shell, as they are now (`App.jsx`), not separate URLs.

| View | Layout | Key components |
| --- | --- | --- |
| Dashboard | Dashboard | Three rows (2026-10-18). 1: glow hero (total memories; sessions / saved this session / feedback in its strip) + "What it keeps" (ranked bars per type). 2: Activity (saves per day, 14 days, columns; labels only on the peak and today; tooltip per day) + Eval (the one cream lamp tile, run strip on its floor). 3: Latest (6 capsule rows with project, type filters, Show more, Search all; rows open the reading pane) + Active projects (ranked bars, last 14 days). Activity and projects come from `/list?limit=2000` counted in the browser (`lib/activity.ts`); if that sample does not reach 14 days back the tile says "at least". Tech debt: a server-side daily count endpoint |
| Search | List + reading (as built 2026-10-18) | Two panes that scroll on their own: search pill + all nine type chips + capsule rows left; the reading pane right (`MemoryReading`: type, title, project, date, source, copy id, superseded notice, full text, tags, Linked = entities + neighbors 10 at a time, "Saved around it" = timeline on request). Below 64rem one pane at a time with Back. No glow on Search: the top hit is a paragraph, and glow never sits behind paragraphs (§6.5) |
| Linked | Canvas + floater | Graph on a sunken solid canvas. Glass floater with the memory text, its entities, and its neighbors. Ego is a mode, not a second product |
| Curate | List | Search, fact-type chips, actionable rows, one primary confirm |
| Eval | Score sheet | Pass/fail summary, rows with percent and delta. Fail is red. A regression is clay. A gain is dusk |
| Instances | Card grid | Active instance is the single glow. Others are solid cards. Create, rename, switch, archive, delete. Delete uses the confirm dialog |

Reading a memory (full text) uses the reading column wherever it opens: search expand, timeline, Linked floater. One component, three hosts.

---

## 14. Decisions

Proposed 2026-10-18. Item 2 was decided by you. The rest were adopted as recommended so the sample page could be built; each can still be reversed on review.

1. **Identity split from Tendrium.** Adopted. Dusk leads, lumen is the lamp, neutrals are cool. `lumen-300` is glow-only because it matches Tendrium gold.
2. **Theme.** **Decided: follow the system light/dark setting** (not dark-only). See 5.4 and 5.8.
3. **Type colors.** Adopted. Rely / Use / Notice / Lesson / Spoken / Frame / Raw. `knowledge` joins `fact` in Rely.
4. **The trace, not the node.** Adopted.
5. **Geist**, self-hosted. Adopted and installed.
6. **No logo file yet.** Adopted. Wordmark in Geist until the lamp tile is drawn.
7. **No photography in v1.** Adopted.
8. **Scope of the rebuild.** Adopted. Shell, then Dashboard, Search, Linked, Curate, Eval, Instances. One view at a time.
9. **Jade and node fields** stay out. Adopted. **Orange** is allowed only as the ember inside the glow (6.5), decided 2026-10-18 to match `IMG_0240`; never as flat UI color.
10. **Open: Rely vs Notice.** On screen, the fact/knowledge chip and the pattern chip are hard to tell apart by color alone (hue 86° vs 78°). Icon and word still separate them. Options: move Notice to another hue, or accept it. Needs a call before Search is rebuilt.

---

## 15. Next steps

Component-level progress (status, plans, dated logs) is tracked in `docs/components-dev.md`.

1. ~~Review this book and answer section 14.~~ Done, except 14.10.
2. ~~Tokens and a sample page.~~ Done: `src/styles/tokens.css`, `src/styles/base.css`, `src/components/brand/*` (each with its `.module.css`), `sample.html`. Run `npm run dev` in `brain/rust/ui` and open `/static/sample.html`. Judge it in both appearances.
3. ~~Shell and Dashboard in the live app~~ (2026-10-18, not deployed): `App.jsx` + `App.module.css` (floating panel, glass dock, glass header with view title, instance line, search that hands its query to Search, live pill, instance pill) and `views/Dashboard.jsx` on real `/stats`, live feed, and `eval_dashboard.json`. Search, Linked, Curate, Eval, Instances still run their Tailwind styling inside the shell, pinned dark (`LEGACY` set in `App.jsx`) until each is rebuilt; they still show their own old title under the header. In dev, the live pill can stay on "connecting" because the Vite proxy holds back the stream's first byte; production reports "live".
4. ~~Search~~ (2026-10-18): `views/Search.jsx` + `components/brand/MemoryReading.jsx`. Dashboard rows now open a memory straight into the reading pane. Fixed on the way: stale responses can no longer overwrite newer ones (`lib/useLoad.js`); no false "0 results" frame; search snippets cut at the API's 120 chars are marked with …; neighbors page 10 at a time (one memory had 908).
5. ~~Linked, Curate, Eval, Instances~~ (2026-10-19). Linked is now a 3D memory atlas (three.js, MIT; position = similarity, real links only for the memory in focus, §8). **Migration complete: Tailwind removed.** Remaining: a production route for `atlas.json`. Details per component in `docs/components-dev.md`.

**Styling rule (decided 2026-10-18): plain CSS only, no Tailwind in new code.** Same pattern as sicop-health:

- `src/styles/tokens.css`: every value (colors, gradient tones, type families, radius, spacing, motion). Global.
- `src/styles/base.css`: reset, page defaults, the text styles (`t-display` … `t-mono`), and three shared behaviors: `glass`, `pressable`, `hit`. Global, and kept that small on purpose.
- One `Component.module.css` beside each component for everything else. State goes in attributes (`aria-pressed`, `aria-current`, `data-signal`), not in class names built at runtime.
- The live views keep their Tailwind only until each is rebuilt. When the last one moves, `tailwindcss`, `postcss`/`autoprefixer` config, and `tailwind.config.js` are deleted.
6. The lamp mark is drawn after the sample page looks right.
7. Pictures, if ever, come last.

---

## 16. Apple standards applied

Source: Apple Design Resources and the Human Interface Guidelines (Accessibility, Color, Dark Mode, Typography, Materials), read 2026-10-18.

| HIG rule | What the book does now | v1 status |
| --- | --- | --- |
| Text contrast at least 4.5:1, aim for 7:1 on small custom text | Role table in 5.8, measured live on the sample page | Failed on raised rows (4.4:1) |
| Respect the system appearance; dark-only only in rare cases | Follows the system, no in-app switch | Dark only |
| Avoid Ultralight, Thin, Light weights | Display is 400 | Display was 300 |
| Let text grow to 200% | Type in rem | px |
| Minimum control size: 28pt macOS, 44pt touch | 36px mouse, 44px touch | Not stated |
| Glass for navigation and controls, sparingly, not the content layer | Glass only where content passes beneath; reading text on solid surfaces | Partly; glass over a flat ground |
| Support Reduce Transparency and Increase Contrast | Both handled in `tokens.css` | Missing |
| Support Reduce Motion with gentler equivalents, not just "off" | Fades and colors stay; movement stops | Present |
| Color is never the only signal | Every chip is color + icon + word | Present |
| Minimize typefaces | Geist + Geist Mono | Present |

---

## Appendix A — What this book is answering

The viewer should feel like the references in `inspo/`: dark, soft, lit from inside, quiet enough to read. It should feel like Brain: a private memory you can trust, search, and trace. It should not feel like Tendrium, and it should not feel like the zinc utility it is today.
