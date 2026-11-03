# Tendrium brand book plan

Date: 2026-10-14
Status: Draft for review. This is the plan the brand book is written from. The UI/UX refactor of the Tendrium app (`apps/web`) is built on top of the brand book.
Parent brand: LifeHub (lifehub.care). Tendrium is a LifeHub product. This book covers Tendrium only; the Tendrium page on lifehub.care is updated later to match it.

---

## 0. Why we are doing this

Tendrium today feels flat, simple and "everything is green". The code shows why:

| Fact (measured 2026-10-14) | Effect |
| --- | --- |
| 2,636 hard-coded hex colors in 161 component files | The token file (`src/styles/tokens.css`) barely controls the look. Changing the brand means editing 161 files |
| `#84a584` (sage) used 517 times, `#2c3833` / `#3d4d45` (green-grey surfaces) another 529 | One low-saturation green does everything: accents, borders, chips, charts. Nothing stands out, so nothing feels important |
| Sage `#84a584` has very low chroma (0.06 in OKLCH) | It reads grey-green, which is why the app feels dull rather than premium |
| Fonts: Montserrat + Plus Jakarta Sans + Raleway | Three families, none of them the chosen face (Geist) |
| `--ease-out-expo` and `--ease-apple` hold the same curve; `--duration-base` and `--duration-slow` are both 600ms | Motion tokens exist but do not express a system |

The brand book fixes the cause, not the symptoms: one color system with real tone ranges, color that carries meaning, one font, one icon set, one surface model, and a visual idea (the node) that belongs only to Tendrium.

---

## 1. Brand idea

**Tendrium connects scattered public data into one living intelligence.**

The logo already says it: seven nodes joined by soft, liquid connections, growing outward like a root system (a *tendril*). Every visual decision should feel like that mark: connected, organic, precise.

Three words to judge every screen against: **connected · calm · precise.**

---

## 2. Design principles

These decide every case the book does not cover.

1. **Dark, calm ground. Light comes from the brand.** The page is near-black. Color arrives as light: gold and jade glows, never flat paint.
2. **Gold leads, jade supports, neutrals carry the rest.** Mixing the two brand hues is what makes the UI feel present. Neither color does everything (the current problem).
3. **Color means something.** Every hue in the data is a state or a signal (section 5.6). Decoration never borrows a state color.
4. **One glow per screen.** One hero card may glow. Everything else is quiet frosted glass or plain surface. Rarity keeps it premium.
5. **Glass is for chrome, not for data.** Navigation, docks, popovers, chips and overlays can be frosted. Tables and dense charts sit on solid surfaces so they stay sharp and fast.
6. **Numbers are the heroes.** Big numbers with small units and a delta chip; the extra-light style is saved for the one headline figure. Labels stay small and quiet.
7. **Nodes show relationships.** The node language appears where things connect (suppliers to institutions, steps in a process, the agent thinking), not as wallpaper.
8. **Motion reveals and confirms. It never delays.** Product-speed timing (section 11). Nothing loops except a loader.
9. **One idea per panel.** Every card answers one question. If it needs two, it becomes two cards.

---

## 3. Logo

### 3.1 Inventory (already in `apps/web/public/tendrium-logos/`)

The 14 files still carry their Figma export names. The brand book gives them real names (rename when the book is approved; `app-logo.tsx` points at `Group 1000005878.svg` today).

| Current file | What it is | Proposed name |
| --- | --- | --- |
| `Group 1000005878.svg` | Lockup: gold mark + white word (in use today) | `tendrium-lockup-gold-white.svg` |
| `Group 1000005891.svg` | Lockup: all gold | `tendrium-lockup-gold.svg` |
| `Group 1000005895.svg` | Lockup: all `#F8F8F8` | `tendrium-lockup-white.svg` |
| `Group 1000005896.svg` | Lockup: all `#080808` | `tendrium-lockup-black.svg` |
| `Group 1000005897.svg` | Lockup: gold mark + black word | `tendrium-lockup-gold-black.svg` |
| `Group 1000005890.svg` | Lockup: jade-black mark + white word | `tendrium-lockup-ink-white.svg` |
| `Group 1000005892.svg` | Lockup: all jade-black `#0D120E` | `tendrium-lockup-ink.svg` |
| `Group 1000005893.svg` | Lockup: jade-black mark + gold word | `tendrium-lockup-ink-gold.svg` |
| `Group 1000005894.svg` | Lockup: gold mark + jade-black word | `tendrium-lockup-gold-ink.svg` |
| `Group 1000005898.svg` | Lockup: jade-black mark + black word | `tendrium-lockup-ink-black.svg` |
| `Group 1000005888.svg` | App icon: gold mark on jade-black `#0D120E` tile | `tendrium-icon-ink.svg` |
| `Group 1000005889.svg` | App icon: jade-black mark on gold tile | `tendrium-icon-gold.svg` |
| `Group 1000005899.svg` | App icon: gold mark on `#080808` tile | `tendrium-icon-black.svg` |
| `Group 1000005900.svg` | App icon: jade-black mark on `#F8F8F8` tile | `tendrium-icon-white.svg` |

10 lockups (1435×272) and 4 app icon tiles (361×460). Note: the files use a second black, `#0D120E` (a jade-tinted black). It becomes `jade-950`'s neighbour in the palette (section 5) so the logo files and the UI agree.

### 3.2 Rules

- **Clear space:** keep an empty margin on every side equal to the diameter of one node of the mark (about 20% of the logo's height). Nothing touches, crosses or overlaps it: no text, no edge, no other mark.
- **Always visible:** the logo is never covered, cropped, faded behind content, or animated out of view while the screen is in use.
- **On gradients:** allowed when the logo keeps at least **3:1 contrast** against the *worst* spot of the gradient behind it (WCAG non-text contrast). Check the area under the mark, not the average.
- **Contrast facts:** gold `#DAC6A5` on `#080808` = 12.0:1 (excellent). Gold on `#F8F8F8` = 1.57:1 (fails). **On light ground use the black or jade-black variants, never the gold one.**
- **Minimum size:** lockup 96px wide on screen; app icon 24px.
- **Never:** recolor outside the variants above, stretch, rotate, add shadow or glow to the mark itself, put it inside a busy photo, or rebuild the word in another font.

---

## 4. Typography

**Geist** for everything, **Geist Mono** for codes and machine values. Both are open source (SIL Open Font License) and published by Vercel.

**Installed 2026-10-14, self-hosted:** `apps/web/src/fonts/geist-variable.woff2` and `geist-mono-variable.woff2` (v1.7.2 from github.com/vercel/geist-font, weights 100–900, license in `OFL-geist.txt`), loaded with `next/font/local` in `src/app/layout.tsx` as `--font-geist` / `--font-geist-mono` (Tailwind: `font-geist`, `font-geist-mono`). No third-party request at build or run time. The app does not use it as the default yet; the switch happens with the app shell in the rollout.

| Role | Size / weight | Use |
| --- | --- | --- |
| Display number | 48–64px, **weight 300**, tracking -0.03em | The hero number of a screen. Light weight is a **highlight, not the default** (rule below) |
| KPI number | 28–36px, weight 400–500 | Number tiles. Units and decimals at 50–60% size, raised (`$12,340`, `75` + small `%`) |
| H1 (screen title) | 28px, 500, -0.02em | "Licitaciones", "Precios" |
| H2 (panel title) | 18px, 500 | Card and section titles |
| Body | 14px, 400, line height 1.5 | Default text |
| Small / meta | 12px, 400–500 | Dates, institutions, helper text |
| Label | 11px, 500, uppercase, +0.06em | Eyebrows and column headers |
| Mono | Geist Mono 12–13px | `instcartelno`, UNSPSC codes, order numbers, IDs |

Rules:
- **Light display numbers (weight 300) are used sparingly (approved 2026-10-14):** at most one per screen, only on the glow hero card or a screen's single headline figure. Everywhere else numbers are 400–500 so they stay sturdy and scannable in tiles and tables.
- Tabular figures (`font-variant-numeric: tabular-nums`) everywhere numbers line up.
- Two weights per panel at most.

---

## 5. Color system

### 5.1 How it is built

Each brand color becomes an 11-step tone range, listed **from dark to light** (950 darkest → 50 lightest), generated in OKLCH so every step is perceptually even. Hue stays fixed per range, saturation peaks in the middle and fades at both ends. Contrast numbers are measured against the page (`#080808`) and the light ground (`#F8F8F8`). Text needs ≥ 4.5:1; large numbers and icons need ≥ 3:1.

### 5.2 Gold (brand lead). Anchored on the logo: `gold-300 = #DAC6A5`

| Step | Hex | On #080808 | Role |
| --- | --- | --- | --- |
| 950 | `#18130A` | 1.1 | Where gold glows fade into black |
| 900 | `#29231A` | 1.3 | Gold-tinted surface, deep |
| 800 | `#453C2C` | 1.9 | Gold-tinted surface |
| 700 | `#66553A` | 2.8 | Dark end of gold glows |
| 600 | `#856E46` | 4.1 | Gold borders, quiet gold icons |
| 500 | `#A38859` | 5.9 | Gold text and icons on dark |
| 400 | `#B8A17C` | 8.0 | Hover / pressed of primary |
| **300** | **`#DAC6A5`** | **12.0** | **Logo gold.** Primary action fill, active nav, key numbers |
| 200 | `#DFD3BE` | 13.5 | |
| 100 | `#EFE7DA` | 16.3 | Highlight text on dark |
| 50 | `#FCF4E7` | 18.3 | Brightest point of gold glows |

Gold gradient, dark to light: `#080808 → gold-700 → gold-300 (logo) → gold-50`. The glow rises out of black, passes through the logo gold, and peaks in a near-white cream.

### 5.3 Jade (brand support). Approved 2026-10-14: `jade-500 = #3BA278`

Hue OKLCH 163°, bluer and richer than today's sage (145°, chroma 0.06), so it stops reading grey.

| Step | Hex | On #080808 | Role |
| --- | --- | --- | --- |
| 950 | `#061810` | 1.1 | Where jade glows fade into black. Sits next to the logo's jade-black `#0D120E` |
| 900 | `#162920` | 1.3 | Jade-tinted surface, deep |
| 800 | `#254536` | 1.9 | Jade-tinted surface |
| 700 | `#2A654C` | 2.9 | Dark end of jade glows |
| 600 | `#2C8461` | 4.4 | Jade borders, quiet jade icons |
| **500** | **`#3BA278`** | **6.3** | **Jade core.** Live / open / positive |
| 400 | `#6CB794` | 8.4 | Jade icons, positive values |
| 300 | `#95CCB1` | 11.0 | Jade text on dark (large) |
| 200 | `#B8DFCB` | 13.8 | |
| 100 | `#D6EFE2` | 16.5 | |
| 50 | `#E4FCEF` | 18.6 | Brightest point of jade glows |

Jade gradient, dark to light: `#080808 → jade-800 → jade-500 → jade-300`.

### 5.4 Neutrals (`#080808` → `#F8F8F8`)

Very slightly warm (toward gold) so greys never drift green.

| Step | Hex | On #080808 | Role |
| --- | --- | --- | --- |
| — | `#080808` | — | **Page ground** |
| 950 | `#0E0D0B` | 1.0 | Sunken areas |
| 900 | `#181715` | 1.1 | Surface (cards, table body) |
| 800 | `#252422` | 1.3 | Raised surface, hover rows |
| 700 | `#393836` | 1.7 | Borders, dividers, inactive tracks |
| 600 | `#51504D` | 2.5 | Disabled, placeholder |
| 500 | `#6D6B69` | 3.8 | Quiet icons, chart gridline labels |
| 400 | `#8D8C89` | 6.0 | Secondary text |
| 300 | `#AFAEAB` | 9.0 | Body text on dark |
| 200 | `#D2D1CE` | 13.1 | Strong body text |
| 100 | `#ECEBE8` | 16.8 | Headings |
| — | `#F8F8F8` | 18.9 | **Primary text** |

**Dark only (approved 2026-10-14).** v1 ships one dark theme. Tokens are named by role (`--surface`, `--text-primary`), not by value, so a light theme can be added later without touching components.

### 5.5 Distribution: how the mix feels "present"

- **~80% neutrals** (ground, surfaces, text).
- **~12% gold**: brand moments, primary actions, active navigation, the one glowing hero card, the most important number on the screen.
- **~8% jade**: everything live, open or improving: open tenders, positive deltas, "live" dots, success.
- Gold and jade appear **together** in glows (a gold-to-jade gradient behind the hero card) so the brand reads as one living light, not one flat color.

### 5.6 State colors (psychology-based)

Each state uses the emotion people already attach to the color, so users read status before reading the word. Every state also gets an icon and a label, because color alone fails for color-blind users (~8% of men) and red/green pairs are the most confused.

| State | Color | Text / Fill | Why this color |
| --- | --- | --- | --- |
| **Publicado / open** (an opportunity to act) | Jade | `#4CC493` on `#002C1C` | Green = go, growth, safety. The primary "you can act now" signal |
| **En evaluación / in review** | Azure | `#74B3DE` on `#102636` | Blue = calm, trust, waiting. Signals "in progress, nothing to do yet" without urgency |
| **Adjudicado / awarded** | Gold | `#DBB970` on `#2E2207` | Gold = achievement, reward, value. Ties success to the brand |
| **Desierto / void** | Slate | `#89939E` on `#212428` | Grey = absence, neutrality. A void tender is not a failure, so it must not look like one |
| **Cancelado / cancelled** | Clay | `#CD7769` on `#381A15` | Muted red = stop, loss, without the panic of pure red |
| **Urgente / closing soon** | Amber | `#F7AC4D` on `#361E00` | Orange = caution, attention. Highest visibility after red; draws the eye without alarm |
| **Crítico / overdue, sanctioned supplier** | Red | `#E8605B` on `#421110` | Red = danger, act now. Reserved for real risk so it keeps its power |
| **Info** | Neutral | `neutral-300` on `neutral-800` | Information is not an emotion. Keep it quiet |

Azure, slate, clay, amber and red sit outside the brand ranges on purpose: they exist only as states, never as decoration, so the brand stays gold + jade.

Deltas: up/positive = jade + ↑ icon. Down/negative = clay + ↓ icon. No change = neutral + →. Whether "up" is good depends on the metric (a price going up is bad for a buyer); the component takes a `goodDirection` setting.

All state text colors pass 4.7:1 or better on their fill and 6:1 or better on the page.

### 5.7 Data visualization palette

Categorical order (max 6 series per chart): `gold-300`, `jade-400`, `#74B3DE` azure, `gold-600`, `jade-700`, `neutral-400`. Sequential (maps, heat): `jade-950 → jade-300`, or `gold-950 → gold-300` for money. Diverging (above/below a reference): `clay ← neutral-600 → jade`. Gridlines `neutral-700` at 40%; bar tracks `neutral-800`.

---

## 6. Surfaces, shape and depth

### 6.1 Five depths

| Level | What | Recipe |
| --- | --- | --- |
| 0 Ground | The page | `#080808`, optional film grain at 3% |
| 1 Surface | Cards, tables, panels | `neutral-900` + 1px border `rgba(248,248,248,0.06)` |
| 2 Raised | Hover, popovers, menus | `neutral-800` + 1px border `rgba(248,248,248,0.10)` |
| 3 Glass | Nav dock, filters bar, chips over imagery, modals | `rgba(248,248,248,0.06)` + `backdrop-filter: blur(20px) saturate(140%)` + top highlight `inset 0 1px 0 rgba(255,255,255,0.08)` |
| 4 Glow | **One** hero card per screen | Mesh gradient (gold + jade light fading into black) + 3% grain + glass border |

No drop shadows on dark. Depth comes from lighter surfaces and borders. A soft colored glow may sit behind the level-4 card only.

### 6.2 Radius ladder

| Radius | Use |
| --- | --- |
| 999px (pill) | Buttons, chips, tags, tabs, search, nav dock |
| 28px | App shell panels, hero cards, modals |
| 20px | Standard cards and tiles |
| 14px | Inner tiles inside a card, inputs, dropdowns |
| 8px | Small elements: table row hover, mini tiles, avatars-square |

Rule: an inner shape's radius = outer radius − padding (keeps nested corners parallel, as in every bento reference).

### 6.3 Texture

- **Grain:** 3% film grain on glows and ground (IMG_0240, IMG_0242, IMG_0243).
- **Dot matrix:** the MedAxis/TD Bank dot grid, used for micro-charts and as a faint fade-in texture at panel edges.
- **Photography:** a core part of the look, in the app and outside it. Always made by us, never stock. Rules in 6.4.

### 6.4 Photography

Every photo is **made by us: generated in-house with AI** (decided 2026-10-14). No stock, no images with someone else's rights, no real brand names or logos on products, no real people presented as clients or staff without their consent.

**The vibe (from the references):**

| Quality | What it means | References |
| --- | --- | --- |
| Low-key light | Mostly dark frames; one directional light source; deep shadows that fall into the `#080808` ground | `0228` (light through blinds), `0225`, `0246` |
| Warm highlights, deep shadows | Graded so highlights lean toward gold and shadows toward jade-black, never neutral grey or blue | `0222`, `0228`, `IMG_0240` |
| Texture | Fine film grain (~3%), soft focus at the edges, shallow depth of field | `0231`, `0235`, `0221` |
| Atmosphere | Fog, frosted haze, motion blur used with purpose: the subject stays readable, the background dissolves | `0231` (motion-blurred figure), `0235` (portrait in fog) |
| Nature as data | Macro organic textures (moss, roots, leaves) that echo the node logo and the jade range | `0246` (moss), `IMG_0168` moss on the LifeHub board |
| Calm subjects | People at work, in focus, unposed; no smiling-at-camera stock look | `0225`, `0235`, Horm references |

**Subjects for Tendrium:**

- **People:** pharma and medical-device sales teams, procurement officers, pharmacists, regulatory specialists, hospital buyers, working in Central American settings.
- **Products:** vials, blister packs, boxes, medical devices, unbranded, studio-lit on dark ground (product renders like `0222` are also allowed).
- **Places:** hospitals, public institutions, warehouses, ports, Central American landscapes per country (used on the markets hub).
- **Hands and documents:** signing, reviewing tenders, handling samples. Close, warm, with depth of field.
- **Organic macro:** moss, roots, leaf veins, water: the "living network" behind the node idea.

**Where photography is used:**

| Place | How |
| --- | --- |
| Markets hub `/markets` | One landscape per country, darkened, behind a glass card |
| Glow hero cards | Blurred photo behind the glass layer, so the glow has depth (`0231`) |
| Dashboards | One photo tile per dashboard at most, in the bento (`0225`, `0178`) |
| Login, onboarding, agent home | Full-bleed photo or macro texture under the glass card |
| Empty states | Organic macro, dimmed, with one line of copy |
| Catálogos / products | Product photography or renders on dark ground |
| Marketing, reports, social | Full range |

**Never:** behind tables, charts or dense text; as decoration on a working screen that already has a glow card; more than one photo per panel.

**Treatment rules:**

- Text on a photo always has a scrim or glass layer that keeps ≥ 4.5:1 contrast.
- Photos inside cards use the inner radius (section 6.2) and sit at 70–90% opacity on dark, so type stays louder than the picture.
- One color grade for everything (a shared preset / LUT: gold highlights, jade-black shadows, 3% grain). A photo that does not take the grade is not used.
- Files: AVIF or WebP, max 1920px wide, decorative images use empty `alt`, meaningful ones get a real description.

**Production (AI, in-house):**

- **Quality bar:** hyperrealistic, the highest quality the tools can produce. It must read as a real photograph at full size: correct anatomy (hands, fingers, eyes, teeth), believable skin and fabric texture, physically correct light and reflections, no warped text or packaging, no melted edges, no plastic look.
- **The vibe is part of the image itself**, not a filter added afterwards: grain, gradient light, haze, frosted depth and the gold/jade grade are written into the generation prompt, then the shared grade is applied on top for consistency.
- **One prompt library:** every image is generated from a saved base prompt (light, lens, grade, texture, mood) plus a subject line, so the whole set looks like one shoot. Prompts are stored next to the images so any image can be remade.
- **Approval gate (founder review):** every image goes to review before it is used anywhere.
  1. Generate candidates, and I pre-check each one against this section (realism defects, vibe, grade, rights rules). Clear failures are dropped before review.
  2. You review. **Pass** → the image is exported and enters the library. **Fail** → it is remade (same subject, adjusted prompt) or replaced (different subject), then reviewed again.
  3. Nothing reaches the app or any public surface without your pass.
- **Record:** each approved image keeps its prompt, tool and settings, date, and review result, so the library stays traceable.

**Tool (decided 2026-10-14):** `Qwen/Qwen-Image-2.1`, run locally in ComfyUI (`~/Documents/Code/ComfyUI`) with the official workflows from `Comfy-Org/Qwen-Image-2.1` (text-to-image, image edit, background removal; Turbo at 8 steps for fast drafts). Setup follows the AI Search video "Finally! New best local AI image editor is here".

- **Licensing:** the model ships under the Qwen Research License (non-commercial). The founder is resolving commercial licensing. Until then, images made with it are **placeholders**: they fill the product while we build, and get replaced (or kept, once licensed).
- **Tracking:** every image's record includes `model: qwen-image-2.1`, so all placeholders can be found and swapped in one pass.
- **Machine:** Apple M4 Max, 64 GB memory. Local ComfyUI is 0.24.0 (2026-06-11), older than the model (2026-09-30), so it will likely need an update before the 2.1 workflows run. No model files downloaded yet (~22 GB for the base model, text encoder and VAE).

---

**Style lock (approved by the founder 2026-10-14, calibration batch 1: 8/8 approved).**

| Setting | Value |
| --- | --- |
| Model | Qwen-Image 2.1, int8 files, local ComfyUI 0.40.0 (official text-to-image wiring) |
| Steps / sampler | 40 · euler · simple · cfg 1 (25 steps was visibly softer on faces and hands) |
| Prompt enhancer | Off (about 11 s per token on this Mac, hours per prompt). Prompts are written the way the enhancer writes them: an observer describing the finished frame |
| Sizes | 896×1120 (4:5, people) · 1248×832 (3:2, places, products, macro) · about 4.3 min per image |
| Prompt | `docs/brand/imagery/prompts.py`: one shared BASE style block + one subject line |
| Grade | `docs/brand/imagery/grade.py`: split tone (jade-black `#0D120E` shadows, gold `#DAC6A5` highlights, strength 0.22), vignette 0.18, film grain 0.032. The model barely produces grain or haze by itself, so the grade adds them identically to every image. Raw files are always kept |
| Lessons | Keep hands simple; avoid small complex props in hands (glasses, blister packs drift). Light, mood, landscapes, textures and products are the model's strengths |
| Library | `docs/brand/imagery/library/`: approved images, each with its JSON record (prompt, seed, settings, grade, review) |

### 6.5 Mesh surfaces (approved direction 2026-10-14, specimen v0.3)

The premium look of the references (0231–0235, 0240, 0245) comes from technique, not from brighter colors. A mesh surface is built in five layers:

1. **Tone fill:** the card is filled edge to edge with 4–6 large radial blobs from our ranges, blurred together (~42px). Gold and jade blend into moss where they meet; that is how the two brand colors feel "mixed and present".
2. **Milk:** a soft white wash (~10%) in the middle of the card, never over text rows.
3. **Rim:** a 1px inner highlight border plus a brighter top edge, so the card reads as frosted glass.
4. **Vignette:** a slight darkening at the edges.
5. **Grain:** fine film grain over everything (soft-light blend, ~22%).

Squircle corners (`corner-shape: squircle`) with a rounded fallback.

**Contrast rule (non-negotiable):** every mesh is one of three types, and mid-tones never sit behind text.

| Type | Text | Recipes |
| --- | --- | --- |
| **Deep** | White | Moss, Champagne, Ledger |
| **Light** | Ink (`#080808`) | Sage, Sun, Dusk, Field |
| **Split** | White on the dark top, ink on the light bottom | Aurum (the IMG_0240 look) |

The single bright blob of a Deep mesh goes behind the visual (dot chart, illustration), never behind labels. Text over vivid or busy areas (agent screens) sits on a dark glass chip. Every text element on a mesh must pass WCAG AA (4.5:1, or 3:1 for large text). `docs/brand/specimen/audit.sh` measures every text element against its real background and fails below AA; the specimen passes 161/161.

**Gradient-only tones** (used inside meshes, never as flat UI color): umber `#2D1205` / `#542C11`, copper `#A36B44`, vivid gold `#A76C12` / `#CC9230` / `#EFCC8C`, cream `#FAE6BB`, moss `#4A4B22` / `#757543`, sage-grey `#899E97`. Bright accent on mesh ("spark", for lit dots, checks, markers): `#F3E2B3`.

**Motion:** on hover the blobs drift slowly (1.8s); the agent orb breathes only while listening. Both are off under `prefers-reduced-motion`.

## 7. Iconography

Reference: `ui/IMG_0229.JPG` (the glass dock on the rock). We draw our own set in that style.

| Property | Rule |
| --- | --- |
| Grid | 24×24, 2px safe padding |
| Stroke | 1.5px, round caps, round joins |
| Corners | Soft (2px radius on shapes), like the house and calendar in the reference |
| Detail | Minimal interior detail: one line or one glyph (the bookmark's single bar, the calendar's date) |
| States | **Inactive = outline. Active = filled two-tone** (the telescope), placed in a lighter glass circle |
| Color | `neutral-300` inactive, `#F8F8F8` active, gold-300 for brand-critical actions only |
| Node accent | Where an icon has a joint or endpoint, end it in a small round node, a quiet nod to the logo (used on a few icons, not all) |

First set to draw (from the app's real routes):

| Area | Icons |
| --- | --- |
| Navigation | Home/dashboard, licitaciones, precios, contratos, órdenes, catálogos, analytics, agent, alertas, notifications, equipo, markets/country, settings, search |
| Actions | Filter, sort, export, share, add, close, back, more, external link, download, calendar, bookmark/watch |
| Data | Trend up, trend down, price, institution, supplier, product/molecule, document, deadline/clock, map pin, connection (node) |
| States | Open, in review, awarded, void, cancelled, urgent, critical, info, live dot |

---

## 8. The node system

Reference: MedAxis (one grammar for the symbol, the service marks, the patterns and the data). Tendrium's logo already is that grammar.

### 8.1 Grammar (measured from the logo)

`docs/brand/specimen/nodes.py` rebuilds the logo from 7 nodes and 6 connections at a **99.3% pixel match**, so every node graphic is drawn with the mark's own geometry:

| Element | Rule |
| --- | --- |
| Node | Circle, radius 0.275 unit |
| Connection | Leaves each node at 45°, pinches to a 0.39 r waist, widens into the next node. Never a straight bar |
| Unit | Node to node is one unit. Directions 0°, 45°, 90° (marks); data views may use any of the 8 grammar directions |
| Growth | Branches like the logo; lines never cross |
| Scale | Same shapes from a 16 px mark to a full-panel texture |

### 8.2 The meaning rule

**Connected means related.** Nodes join only when the data is truly continuous or related (consecutive on-time deliveries, a supplier that sold to an institution, completed lifecycle steps, live markets). Unrelated points stay as quiet dots; a gap stays a gap. This keeps the node language meaningful instead of decorative.

### 8.3 Module marks

One mark per area, all built from the grammar (like MedAxis service marks). Color comes from the module's mesh recipe, not from new hues.

| Module | Mark | Mesh |
| --- | --- | --- |
| Licitaciones | A call that branches into offers | Moss |
| Precios | A rising chain | Sun |
| Contratos | A closed loop of four (agreement) | Champagne |
| Órdenes | A chain flowing down to delivery | Ledger |
| Catálogos | A 2×2 grid | Field |
| Agente | The logo's top branch | Aurum |
| Alertas | Two nodes (reads as "!") | Dusk |
| Analítica | Columns of nodes (a bar chart) | Sage |

Small size (≤ 22 px) in gold inside pills, for tabs and headers.

### 8.4 Patterns (never behind data)

- **Ghost structure:** huge outlined nodes (clean outer contour only) at ~6–18% opacity behind brand panels, login, onboarding.
- **Growth texture:** a field of nodes that thickens into connected colonies, for panel corners and covers.
- **Dot field:** quiet dots are all the data; the connected path is what Tendrium found. For insight cards and empty states.

### 8.5 On purpose: where the node is the data

| Use | What connects | Where |
| --- | --- | --- |
| Who sells to whom | Institution ↔ suppliers; node size = share of awarded value | Institution and supplier pages, analytics |
| Delivery continuity | Consecutive on-time months; a miss breaks the chain (hollow clay ring), pending = small dot | Contract detail, supplier profile |
| Lifecycle | Completed steps joined (jade), current step glows (gold), future outlined + dotted | Tender detail |
| Coverage | Live markets joined; coming soon outlined (Belize); DR linked by a dotted arc | Markets hub, dashboard |
| Agent states (liquid) | One shape that flows between the app's agent states: nodes split off, travel and merge back like drops, connections stretch and snap, the scale glides. It settles into the true vector logo at rest | Agent chat, every wait state |

### 8.6 Agent states: one liquid shape

Replaces today's single pill (`AgentPending`, states `spawn · tool · think · draft · validate`). Same states, same moments, rebuilt in nodes. Engine: `docs/brand/specimen/nodemorph.js` (spring physics; connections drawn with the logo's pinched neck; a light gooey filter fuses joints so nodes merge like liquid).

| State | Label | Shape |
| --- | --- | --- |
| spawn | Iniciando… | A drop dividing into two |
| tool | Consultando herramientas… | A core node sends a probe out along the 45° directions; it stretches on a thin waist and melts back |
| think | Pensando… | Three nodes orbiting as one liquid ring |
| draft | Redactando… | A chain that undulates like a line being written |
| validate | Validando… | Four nodes forming a check, breathing |
| rest | — | Flows into the logo, then the exact vector mark fades in |

Rules: extra nodes always split from the nearest node; removed nodes always merge into the nearest node (nothing pops in or out). Each state has one fixed scale, and the zoom between states rides the same spring. Sizes: 240 px stage on the agent home, 30 px inline next to the status label. Reduced motion: each state is shown as a still shape, no transitions.

Never: behind tables or numbers, looping on a working screen (except the loader while waiting), more than one node pattern per screen.

## 9. Components (and where each comes from)

**Reusable** = used across the app. **Specific** = built for one screen or use case.

| Component | Type | Reference | Where in Tendrium |
| --- | --- | --- | --- |
| Glass nav dock (icons, active filled circle, separate search circle) | Reusable | `ui/0229` | App shell navigation |
| Pill tab bar (active = filled pill) | Reusable | AgroControl, `ui/0224`, `ui/0234` | Top-level tabs inside a module (e.g. Dashboard · Licitaciones · Precios) |
| Search pill + filter pill | Reusable | AgroControl, `ui/0179` | Every list screen |
| Filter chip row (scrollable, active filled, "+" to add) | Reusable | `ui/0224`, `ui/0236`, `ui/0179` | Licitaciones / precios / contratos filters |
| Removable tag (label + ×) | Reusable | `ui/0228` | Active filters, alert keywords |
| Primary button (gold pill) and split button (label + dark round icon) | Reusable | `ui/0174`, `ui/0173`, AgroControl "New task" | Primary actions. One per screen |
| Arrow chip (↗ in a circle, top-right of a card) | Reusable | `ui/0231`, `ui/0234`, GeoSales | "Open detail" on every card |
| KPI tile (label, light big number, delta chip, micro-viz) | Reusable | `ui/0234`, `ui/0239`, GeoSales funnel | Dashboards |
| Micro-viz set (dot score, mini bars, sparkline, ring) | Reusable | `ui/0232`, `ui/0234`, `ui/0237` | Inside KPI tiles and table rows |
| Glow hero card | Reusable (1 per screen) | `ui/0231`, `ui/0233`, `IMG_0240` | The single most important item on a screen (top opportunity, total market, current tender) |
| Status pill (state color + icon + label) | Reusable | AgroControl column pills | Tender, contract and order states |
| List row with avatar/icon, two lines, actions | Reusable | GeoSales territory list, `ui/0178` rooms | Supplier lists, institution lists, equipo |
| Data table (solid surface, sparkline column, sticky header) | Reusable | `ui/0237`, `ui/0225` | Licitaciones, precios, órdenes |
| Popover info card | Reusable | `ui/0238` (Egypt Operations card) | Map hover, chart hover |
| Notched "NUEVO" tab cut into a card edge | Reusable | `ui/0177`, MedAxis insight card | New tenders since last visit |
| Icon with alert badge | Reusable | `ui/0232` | Notifications, alerts |
| Avatar stack (+N) | Reusable | AgroControl, `ui/0228`, `ui/0179` | Equipo / staff on a tender |
| Kanban board (status columns, counts, uniform cards) | Specific | AgroControl | Pipeline: tenders a user tracks |
| Tender card (title, date + days left, institution, urgency flag, assignees) | Specific | AgroControl task card, `ui/0221` event card | Board and "upcoming deadlines" |
| Deadline ring (circular countdown) | Specific | `ui/0230` time tracker | Tender detail: time left to submit |
| Timeline month grid (✓ / ✗ per month) | Specific | `ui/0233` | Contract delivery / payment history |
| Progress track with marker | Specific | `ui/0233` | Contract executed vs total, budget used |
| Tick-ring stat | Specific | `ui/0246` | Intel score, coverage % |
| Choropleth map + mini-map + zoom controls | Specific | GeoSales heatmap, `ui/0238` | Central America coverage and spend |
| Map with arcs + label chips | Specific | GeoSales territory map | Import origin → country, supplier → institution flows |
| Segmented gradient bar rows | Specific | GeoSales mobile list | Institution / supplier rankings |
| Funnel row | Specific | GeoSales sales funnel | Published → offers → awarded → contracted |
| Textured chart fills (dots, hatching) | Specific | `ui/0180` | Categorical charts that need more than color to tell series apart |
| Agent home (greeting, suggestion chips, orb, chat) | Specific | `ui/0245` | `/cr/agent`, recolored gold (orange is off-palette) |
| Glass login card | Specific | `ui/0174` | `/auth/*` |
| Booking-style summary card | Specific | `ui/0228` | Alert setup summary, onboarding confirmation |

---

## 10. Layout and structure patterns

| Pattern | Reference | Use in Tendrium |
| --- | --- | --- |
| **App shell**: floating rounded panel on the ground (16px inset, 28px radius), glass icon dock left, pill tabs top, profile + actions top right | AgroControl, GeoSales, `ui/0224`, `ui/0234` | Every authenticated screen |
| **Dashboard bento**: header row (title + KPI strip) → 1 glow hero tile + 3–5 KPI tiles → chart row → list row | `ui/0224`, `ui/0234`, `ui/0239`, `ui/0178`, `ui/0179` | `/{country}/dashboard` |
| **List + filters**: title, search + filter pill, chip row, view toggle (table / board), solid table | AgroControl, `ui/0179`, `ui/0237` | Licitaciones, precios, contratos, órdenes, catálogos |
| **Master + map**: left list panel (search, selectable rows) + map canvas + floating stats card bottom-right | GeoSales territory map | Institutions / suppliers explorer, coverage |
| **Detail page**: glow hero (title, state, deadline ring) → tab bar (Details · Timeline · Documents) → bento of facts → action bar at bottom | `ui/0233`, `ui/0221` | `/licitaciones/[id]`, `/contratos/[id]`, `/ordenes/[n]` |
| **Board**: status columns with counts, uniform cards | AgroControl | Tracked-tender pipeline |
| **Agent space**: centered greeting, suggestion chips, conversation | `ui/0245` | `/cr/agent` |
| **Hub**: large glass cards per market with a node texture | `ui/0178` rooms, MedAxis | `/markets` |
| **Auth**: single glass card over a brand glow | `ui/0174`, `IMG_0240` | `/auth/*` |

Spacing: 4px base grid. Card padding 20–24px. Gaps between tiles 12–16px (bento references sit tight). Section gaps 32–48px.

---

## 11. Motion (product speed)

Built on the LifeHub/RMT vocabulary, tuned for a tool people use all day.

| Move | Timing |
| --- | --- |
| Hover / press | 120–180ms, ease-out |
| Panel / popover open | 200–240ms |
| Number count-up on first load | 600ms, once per session per screen |
| Content reveal on first load (tiles rise 12px + fade) | 400ms, 40ms stagger, once |
| Route change | Cross-fade ≤ 200ms. No circle transition, no loader on navigation |
| Node loader | Loops only while waiting; disappears the moment data arrives |

`prefers-reduced-motion`: no count-ups, no reveals, no node animation (static node mark instead).

---

## 12. Reference map

Every image gets one job. "Take" is what we use; "Leave" is what we do not.

### Art direction

| Ref | Take | Leave |
| --- | --- | --- |
| `IMG_0240` (aurō) | **Master art direction**: soft-cornered glowing tile, light fading from cream-gold into black, grain, frosted edge | Its blue-grey corner tone |
| `IMG_0242` (arounda) | Jade light glowing from one corner into black; palette shown as glass pills | Cyan and mint colors |
| `IMG_0243` (exploda) | Diagonal blurred green light band; palette cards | Lime `#96D13F` (too acid next to gold) |
| `IMG_0244` (orange glow cards) | **The feel and vibe**: light rising from a horizon or a curved edge inside a black card, thin line icons, short centered copy. Rebuilt in our gold and jade gradients (approved 2026-10-14). Use: empty states, onboarding, brand moments | Orange itself |
| MedAxis | Node language, dot-matrix texture, outlined pill labels, notched card | Per-service rainbow accents (we keep color for meaning) |

### Dashboards and components

| Ref | Take | Where |
| --- | --- | --- |
| AgroControl | Pill tabs, search + filter pills, board with status columns, uniform task card anatomy, one loud CTA | Shell, list screens, pipeline |
| GeoSales heatmap | Choropleth, mini-map, zoom controls, funnel row with deltas, segmented bar rows | Coverage map, dashboard, rankings |
| GeoSales territory | List + map, arcs + label chips, floating performance card, date / share / export actions | Explorer screens, reports |
| `ui/0221` Street Ballers | Event card: photo, time, host, address, "check on map", primary + secondary stacked | Tender card (apertura date, institution, map) |
| `ui/0222` P58 | Glass bento of product tiles, round "+" buttons, carousel arrows | Catálogos (products/molecules) |
| `ui/0223` VR furniture | Spatial glass panels (low detail) | Mood only |
| `ui/0224` / `ui/0236` Automatic Payment | Title + KPI strip header, filter chips with "+", nested tiles inside one panel, cream highlight tile with toggle. 0236 proves the same layout re-skins cleanly in green | Dashboard header, precios, alert rules |
| `ui/0225` Channel Analytics | Hero promo tile, KPI strip, line chart with highlighted point, table rows with sparklines | Analytics screens |
| `ui/0228` N99 | Summary card (who, what, when, price), removable tags, image grid with add buttons | Alert summary, onboarding |
| `ui/0229` Icon dock | **Icon style and nav dock** (section 7) | Navigation |
| `ui/0230` Time tracker | Gradient tile with ring timer, date tile, meetings list, split progress bar | Deadline ring, upcoming deadlines |
| `ui/0231` / `ui/0232` / `ui/0233` TD Bank | Glow cards, dot-matrix micro-charts, arrow chip, alert badge on icon, segmented filter pills, month grid timeline, bottom action bar | Hero cards, contract detail |
| `ui/0234` / `ui/0239` Credit / Health Karma | KPI tiles each with a different micro-viz, gauge, score history, offers carousel | Dashboard KPI tiles, intel score |
| `ui/0235` Heart & Circulation | Fog/frosted gradient tiles in a health context | Mood for the light mode, if we do one |
| `ui/0237` CoinUnity | Dense dark data screen done well: area chart, table with sparklines, sentiment slider | Precios, analytics/pricing |
| `ui/0238` World Risk Map | 3D relief choropleth, popover card, risk distribution bars, top-regions list with risk chips, trend chart | Coverage / risk map (also matches the relief maps on the LifeHub Pinterest board) |
| `ui/0245` AI agent | Agent home, suggestion chips, voice orb, chat bubbles | Agent, recolored gold |
| `ui/0246` Eidetic | Dark green landing, tick-ring stats, numbered stat cards with corner dot, moss imagery | Marketing / onboarding, tick-ring |
| `ui/0173` / `0175` / `0177` Aloha | Split panel layout, outlined/filled pill tags, notched "NEW" tab, card bottom action bar | Tags, "Nuevo" marker |
| `ui/0174` C.Lab | Glass login, two-tone date ("Thu" / "24th"), split pill button | Auth, dates |
| `ui/0178` Smart home | Bento with a hero tile + list panel with selected row, toggles | Markets hub, settings |
| `ui/0179` Nestify | Search pill with round button, category pill row, arrow chips, avatar stack | Filters |
| `ui/0180` Inventory | Textured chart fills, map with delay chips, glass inputs | Charts, logistics/ordenes |

---

## 13. Screen map (first pass)

| Screen (routes) | Layout | Key components |
| --- | --- | --- |
| Markets hub `/markets` | Hub | Market glass cards, node texture |
| Dashboard `/{cr,do,pa,gt,hn,ni,sv,bz}/dashboard` | Dashboard bento | Glow hero (top opportunity), KPI tiles, funnel, coverage map, upcoming deadlines |
| Licitaciones list | List + filters | Search, chips, table / board toggle, status pills, "Nuevo" notch |
| Licitación detail `[id]` | Detail | Glow hero, deadline ring, lifecycle nodes, tabs, documents, staff avatar stack |
| Precios / analytics | List + charts | Area/line charts, sparklines table, price deltas with `goodDirection` |
| Contratos / órdenes (+ detail) | List / detail | Status pills, month grid timeline, progress track |
| Catálogos (+ moléculas, registros) | Product bento | Product tiles, tags |
| Alertas / notifications | List | Summary card, removable tags, icon with badge |
| Equipo | Master list | List rows, avatar, contact actions |
| CGR, precalificados, labs, spaces/* | List + filters | Same list kit |
| Agent `/cr/agent` | Agent space | Greeting, suggestion chips, node "thinking" loader |
| Auth `/auth/*` | Auth | Glass card over brand glow |

---

## 14. Decisions (resolved 2026-10-14)

1. **Jade:** approved, `jade-500 #3BA278`. All tone ranges are listed dark → light.
2. **Theme:** dark only for v1. Light-themed references (`0230`, `0235`, `0239`) are used for layout and components, not for their light ground.
3. **`IMG_0244` and every warm/orange reference** (`0244`, `0245`): keep the feel and vibe, rebuild them in our own colors and gradients. Orange never enters the palette.
4. **Light display numbers:** yes, but sparingly (section 4 rule).
5. **Geist:** installed, self-hosted from local files (section 4). No third party.
6. **Photography:** yes, in the app and outside it, following the references' vibe, always made by us (section 6.4).

7. **How photos are made:** generated in-house with AI, hyperrealistic at maximum quality, with the vibe (texture, grain, gradients, frosted) built into each image. Every image passes founder review; failures are remade or replaced (section 6.4).

8. **Image tool:** Qwen-Image 2.1 in local ComfyUI. Images are placeholders until the founder resolves commercial licensing (section 6.4).

---

## 15. Next steps

1. ~~You review this plan and answer section 14.~~ Done 2026-10-14.
2. I write the brand book (`docs/brand/tendrium-brand-book.md`) with the final tokens, plus a visual sample page (palette, type, surfaces, icons, nodes, key components) so it can be judged on screen, not only in text.
3. ~~Tokens go into `src/styles/tokens.css` as the single source of truth.~~ Done 2026-10-15: two layers (62 raw values written once; roles only point at them), existing token names kept as the role names, duplicates and unused tokens removed, Tailwind keys `gold-*`, `jade-*`, `ground`, `brand`, `surface`, `line`, `content`, `state-*`, `rounded-shell/card/inner/pill` point at the tokens.
4. **Styling decision (2026-10-15): plain CSS via CSS Modules, Tailwind frozen.** Every rebuilt component gets a `Component.module.css` next to it, with values only from `tokens.css`. No new Tailwind utilities (`npm run css:freeze` fails if any file gains one; baseline 2026-10-15: 145 files, 12,001 utilities). Each screen leaves Tailwind as it is rebuilt; Tailwind, its config and its PostCSS plugin are removed when the count reaches 0. Done: app shell (top bar, section dock, footer, skip link), body base styles, the switch to Geist; design-system blocks in `src/components/ds/` (MeshCard, KpiTile, ButtonLink, ArrowLink, SectionHeader, StatusPill); CR dashboard (2026-10-15, 11,638 utilities left): mesh hero, KPI tiles with mini bars, data-freshness chip, Closing soon (deadline ring + tender cards with NUEVO notch), Agent panel (prepared questions open the agent pre-filled via `/cr/agent?new=1&q=`, never auto-sent), Markets node network (logo neck geometry in `src/lib/brand/nodes.ts`), institution ranking, status share. All from real data. Liquid agent mark ported (`src/lib/brand/node-morph.ts` + `components/ds/liquid-mark.tsx`), live in the agent chat's `AgentPending` and the dashboard agent panel. First app photo: CR cloud forest behind Markets (`public/brand/photos/`, placeholder register). Shared licitaciones table, pagination and urgency badge converted (11,261 utilities left). CGR insights (2026-10-15): yearly bars (no % change: CGR yearly totals swing up to 5×, 2024 = ₡826,7 MM vs ₡128–264 MM), procedures funnel + award-rate ring, "Who sells to CCSS" node network + competitor strip (awards < ₡10.000 dropped as data errors); categories as light insight tiles; empty and stale states. New ds pieces: ProgressRing, InsightTile, SupplierNetwork, CompetitorStrip, EmptyState. Shared dashboard pieces (StatCard, CountryMacroStrip, BackToMarketsLink) are converted, so all 8 country dashboards use the new tiles; the other 7 page layouts are still Tailwind.
5. Rollout, one screen at a time, each one checked against the book by an independent review loop (brand, accessibility, data accuracy), max 3 rounds, logged. The 2,636 hard-coded colors are replaced as each screen is touched, not in one risky sweep. Suggested order: app shell → dashboard → licitaciones list → licitación detail → the rest.
6. Image production (ComfyUI update, Qwen-Image 2.1 download, base prompt library, founder review) is one of the **last** steps. Until then, photo slots use brand-light placeholders (gold/jade glow on black) so layouts are built and tested without waiting on images.

---

## Appendix A — Original brief (2026-10-14)

> this document is the inicial step to create a branding book for tendrium. based on this brand book we'll then build the ui/ux for tendrium.
>
> **ui:** `apps/web/public/inspo/ui` these are visual references for the ui we're about to build. all of them are modern, feel premium and got the feel we're looking for.
>
> **AgroControl** (https://dribbble.com/shots/27108598-Agriculture-App-Dashboard-UI-AgroControl): this has almost the same feel as tendrium has today, but it feels premium and enhanced. ours is flat and simple, very bad in fact. our dashboards and spaces can use this as reference for enhancement for specific use cases.
>
> **GeoSales** (https://dribbble.com/shots/27342416-Dashboard-Design-for-SaaS-GeoSales, https://dribbble.com/shots/27024629-Sales-Analytics-Dashboard-Design-GeoSales): this also has a tendrium like feel, but premium. we should also use this as reference for specific use cases.
>
> **Design and art direction:** i love the feel of `IMG_0240.JPG`, we are taking on this direction on the art direction side, the gradients, texture, frosted, rounded shape. `IMG_0243.JPG` and `IMG_0242.JPG` are great gradient references.
>
> **MedAxis** (https://dribbble.com/shots/27768405-Medical-Brand-Identity-Design-MedAxis-Group): notice how this design directly connects with tendrium logo. we MUST apply this kind of interconnected feel design through node like connections. It's exactly how tendrium logo design is, if u see it that way. this can also be used on purpose for specific spaces or use cases.
>
> **Color palette:** jade green, gold, #080808 and #f8f8f8. we can take gradients on each color to create a complete color system.

### Follow-up direction (same day)

- Gold gradient: light → logo gold → mixed with darker tones; a full tone range is needed.
- LifeHub is the parent company; Tendrium is a LifeHub product. Focus on Tendrium; update LifeHub's page later.
- Each color needs light-to-dark tones. State colors should follow psychological principles.
- UI references are used for components (reusable and specific), following our design principles.
- Font is Geist. Logo needs its own clear space, never touching or overlapping anything, always visible; it may sit on a gradient with enough contrast. Icon reference: `ui/IMG_0229.JPG`; each icon is drawn new.
- Colors mixed so the UI feels more present; the current "everything is green" feels flat.
