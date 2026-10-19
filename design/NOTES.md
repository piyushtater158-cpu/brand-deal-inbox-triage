# Deal Desk — design notes for the Jinja2 split

Look: **indigo ledger**. Cool grey ground, white panels, deep indigo chrome, ink-black text.
Colour carries verdicts only (green / amber / red), and every verdict also has an icon and words.
Rank is shown by **fill weight**, not by hue: solid → tint → outline → dashed.

## Type scale (system font stack, tabular numerals everywhere)

| Token | px | Use |
|---|---|---|
| `--fs-xs` | 12 | chips, badges, help text, table headers |
| `--fs-sm` | 13 | secondary text, card reasons, quote table |
| `--fs-base` | 14 | body default (density over air) |
| `--fs-md` | 16 | card brand names, panel titles, offered amount |
| `--fs-lg` | 20 | h2, recommended action, counter-offer |
| `--fs-xl` | 28 | h1, score number on cards |
| `--fs-2xl` | 40 | big score in #assessment, KPI numbers |

Weights: 400 body, 600 labels, 700 headings, 800 numbers that are judgments (score, offer, KPI).
No letter-spacing, no italics, no all-caps except `AI ON/OFF`, `SAMPLE DATA`, `EXCLUSIVE`.

## Spacing scale (4-based)

`--s1` 4 · `--s2` 8 · `--s3` 12 · `--s4` 16 · `--s5` 24 · `--s6` 32 · `--s7` 48.
Inside components use s1–s3. Between components s4. Page gutter s5 (s4 under 720px).
Radius: 4px for containers and buttons, 3px for chips. Nothing is pill-shaped.

## Colour roles

| Role | Token | Meaning |
|---|---|---|
| Ground | `--ground` | page background |
| Surface / sunk | `--surface`, `--surface-sunk` | panels / quiet fills, muted cards |
| Ink 1–3 | `--ink`, `--ink-2`, `--ink-3` | text; all pass 4.5:1 on white |
| Indigo | `--indigo`, `-strong`, `-tint`, `-line` | chrome, primary action, P1/P2, recommended action |
| Go | `--go*` | at or above quote, approved, AI on, capacity open |
| Warn | `--warn*` | risk-tier flags, under quote but above floor, capacity full |
| Stop | `--stop*` | hard-stop flags, below floor, no-go, spam |
| Sample | `--sample` | SAMPLE DATA band only |

## Component ranking rules

- **Priority** `.pri--p1/p2/p3/ignore` and **score tile** `.score--*`: solid indigo → indigo tint → white outline → dashed grey. The 3 bars in `.pri__bars` repeat the rank for colour-blind and greyscale use.
- **Flags**: `.flag--stop` (solid red, octagon) → `.flag--risk` (amber tint, triangle) → `.flag--notice` (grey, circle). Render in that order. `.flag--cleared` is struck-through dashed, used only in the re-score note.
- **Provenance**: `.prov--edited` (solid ink) → `.prov--rules` (outline) → `.prov--ai` (dashed). More solid = more trusted.
- **Budget vs quote** `.bvq--ok/under/short/muted`: fill width uses `.pct-0 … .pct-100` (round the ratio to 5, cap at 100, add `.bvq--over` when above 100). The black tick is the creator's floor: `.min-50 … .min-90`, or `.min-none`. No inline styles needed.

## Jinja / HTMX contract

- Swap regions, each one element: `#assessment` (contains `#decision-result`), `#queue-list`, `#skipped-notice`, `#decision-result`. Marked in the HTML with `<!-- swap: … -->` comments.
- **Field edits swap `#assessment` only, so the edited row's provenance chip goes stale.** Return the edited `.field` row as well with `hx-swap-oob="true"` (give each row an id such as `field-budget`).
- **Copy reply needs JavaScript.** The button carries `data-copy="#reply-…"`; wire ~5 lines of `navigator.clipboard.writeText` and toggle `.is-copied` on `.reply`. Without JS the textarea is still selectable, and Approve & copy still records the decision.
- Mid-edit: `.field.is-editing` exists only for the static mock-up; in the app `:focus-within` does the same job.
- Partials worth cutting: `chrome.html`, `score.html`, `pri.html`, `flag.html` (tier + label), `bvq.html`, `dlv.html`, `field.html`, `assessment.html`, `qcard.html`, `excl.html`, `cap.html`.
- Indian grouping: format in Python, not the template, e.g. `babel.numbers.format_currency(x, "INR", locale="en_IN")` or a 6-line custom filter. Applies to follower counts too (1,82,400).
