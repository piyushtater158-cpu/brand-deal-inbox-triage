# Frontend Design Brief — Brand Deal Inbox Triage

This is an independent project. Do not carry over or match the visual identity of any other
brief you may have seen from this user — not the marketplace listing audit, not the
post-campaign watch tool. This one gets its own look.

## What this is

An internal triage tool for a **talent manager at Kalakaaar**, an Indian talent management
agency that represents Instagram creators. Brand inquiries arrive in the creator mailboxes the
agency manages and in Instagram DMs, all mixed together: genuine paid offers, offers slightly
under rate, lowballs, barter pitches, outright scams, and — the expensive ones — offers that
collide with an exclusivity contract the creator has already signed.

The tool scans those inboxes, extracts the deal terms, prices them against each creator's own
rate card, checks them against that creator's partners, no-go categories, monthly capacity and
blackout dates, scores each one 0-100, flags the risks, and drafts a reply. **The manager
approves and copies. Nothing is ever sent automatically.**

A talent manager handles many creators at once and lives in this queue. The tool's job is to
let them look at a card for three seconds and know whether to open it. Density and scanability
beat spaciousness. This is a working tool for one professional, not a marketing page.

## Who uses it

- **Talent manager** (primary): works the queue, opens inquiries, corrects what the extractor
  got wrong, picks an action, copies the reply.
- **Agency head** (secondary): looks only at the pipeline summary.
- Creators and brands never see this app.

## Hard technical constraints

These are not preferences. The build is server-rendered Python (FastAPI + Jinja2) with HTMX
for interactivity, so:

1. **Static HTML + CSS only.** One `.html` file per screen and state, plus one shared
   stylesheet. No build step, no React, no Tailwind config, no framework JavaScript.
2. **No external requests of any kind.** No CDN links, no Google Fonts, no remote images. It
   runs in an offline container. Use a system font stack, or self-host and inline. Icons as
   inline SVG or text.
3. **Semantic HTML with classes.** No inline `style` attributes. Any naming convention is fine
   as long as it is consistent, because I will be splitting these files into Jinja2 partials.
4. **Mark the swappable regions.** HTMX replaces a region of the page wholesale by `id`. Each
   region below must be **one self-contained element** that makes sense when replaced on its
   own, with nothing it needs living outside it:
   - `#assessment` — the single most important one. Score, priority, type, every flag chip,
     quote breakdown, recommended action, counter-offer, and reply draft. **All of it inside
     one element.** This block is re-rendered and swapped every time the manager edits an
     extracted field. If the score sits in a page header and the flags sit in a sidebar, the
     swap is impossible and the design has to be redone.
   - `#queue-list` — the card list, swapped when a filter changes. Filter controls stay
     outside it.
   - `#skipped-notice` — the skipped-mail count line.
   - `#decision-result` — the confirmation that appears after an action is taken.
5. **Works without JavaScript** for everything except those swaps. Plain forms, plain links.
6. **Indian number formatting throughout: `₹2,64,330`**, not `₹264,330`. Two-digit grouping
   above the thousands place. This is a tool for an Indian agency and getting it wrong is the
   first thing the user will notice.
7. **A persistent `SAMPLE DATA` marker** in the shared chrome. All data is synthetic and the
   app must say so on every screen.

## Please avoid

These are the house defaults I see constantly and do not want here: a cream ground with a
high-contrast serif and a terracotta accent; near-black with one neon accent and glowing
edges; italic accent words inside headlines; `01 / 02 / 03` section labels; tiny
letter-spaced monospace labels; pill-shaped buttons. If your first instinct is one of those,
name it and choose again.

## Component inventory

Design these once and reuse them. They carry most of the screen weight:

| Component | Needs to express |
|---|---|
| **Priority badge** | `P1` `P2` `P3` `Ignore` — four clearly ranked levels, readable at a glance in a dense list |
| **Score** | `0-100`, shown with its priority. A number that reads as a judgment, not a metric |
| **Type badge** | `Paid` `Barter` `Hybrid` `Spam` `Not a deal` |
| **Flag chip** | Eleven kinds in **three severity tiers**: hard stops (`Conflict`, `No-go`), risks (`Risky payment terms`, `Usage overreach`, `Suspicious sender`), and notices (`Lowball`, `Missing info`, `Duplicate`, `Urgent`, `Capacity full`, `Blackout clash`). A card can carry four at once and must still be readable |
| **Budget vs quote** | A pairing that makes "offered ₹1,50,000 against a ₹2,64,330 quote" instantly legible as short, and "₹1,50,000 against ₹1,44,000" as fine. This is the single most-read element in the app |
| **Quote breakdown** | A line-item table: base rate-card rows, bundle discount as a subtraction, then usage / whitelisting / exclusivity surcharges, then the total. The manager pastes this reasoning into replies, so it must read as an argument, not a receipt |
| **Deliverable pill** | `2 × Reel`, `3 × Story`, `1 × Carousel` |
| **Editable field row** | Label, current value, and an inline input. Must also show **provenance**: AI-extracted, rules-extracted, or manager-edited. The manager needs to know which values to trust |
| **Action group** | `Approve & copy` · `Edit` · `Decline` · `Ask for info` · `Mark spam`. One is recommended by the system and should look recommended without disabling the others |
| **Reply draft** | An editable text block with a copy button. The payoff of the whole app |
| **AI toggle** | A global on/off switch in the chrome, with its current state obvious from across the room |
| **Exclusivity countdown** | `Santoor — EXCLUSIVE — 528 days remaining`, and an expired variant that reads as clearly inactive |
| **Capacity meter** | `2 of 4 booked this month`, plus a full state |
| **Raw message viewer** | Sender, domain, subject, timestamp, and the original body with line breaks preserved. Includes messy Hinglish text |

## The six screens

Use this content. It is real sample data from the build, consistent across screens — please do
not substitute placeholder text.

---

**1. Triage Queue** (`/` — the home screen, most important)

Shared chrome: product name, nav to the other screens, AI toggle, `SAMPLE DATA` marker.

A `Scan inboxes` action, and `#skipped-notice`: *"6 messages skipped — no brand keywords
matched. View list."*

A filter bar outside `#queue-list`: creator, type, flag, priority.

`#queue-list` holds cards sorted by priority then score. Each card: creator name and handle,
brand, budget vs quote, deliverables, score, priority badge, flag chips, and a one-line
plain-language reason. Five real cards:

- **Lumière Skin Co.** → Aanya Mehra `@aanyamehra` · ₹1,50,000 offered vs ₹1,44,000 quote ·
  `2 × Reel` `2 × Story` · **83** · `P1` · no flags · *"Above rate card, in-category, reply
  due in 6 days."*
- **Nivara Soaps** → Aanya Mehra `@aanyamehra` · ₹1,50,000 vs ₹2,64,330 · `2 × Reel`
  `3 × Story` · **20** · `P3` · `Conflict` `Lowball` `Usage overreach` `Risky payment terms` ·
  *"Clashes with active Santoor exclusivity until Mar 2027."*
- **FitFuel India** → Rohan Iyer `@rohan.lifts` · ₹85,000 vs ₹98,000 · `1 × Reel` `2 × Story` ·
  **71** · `P1` · `Urgent` · *"87% of rate card — counter at ₹98,000. Reply due in 2 days."*
- **BetKing11** → Kabir Shah `@kabirbuilds` · ₹2,00,000 vs ₹1,10,000 · `2 × Reel` · **0** ·
  `Ignore` · `No-go` · *"Betting is on Kabir's no-go list."*
- **Zephyr Travel Co.** → Tara Dsouza `@tararoams` · Barter, product value ₹22,000 vs ₹18,000
  quote · `1 × Story` · **64** · `P2` · no flags · *"Barter accepted — product value above her
  ₹15,000 minimum."*

Also design: the **zero-results** state after filtering, and the **empty** state before the
first scan.

---

**2. Inquiry Detail** (`/inquiry/<id>`)

A two-pane layout: the original message on one side, the extracted fields and the assessment
on the other. Use the Nivara Soaps inquiry, because it exercises everything at once.

*Left — raw message.* From `priya.menon@nivarasoaps.in` · domain `nivarasoaps.in` · received
17 Oct 2026, 11:42 · subject *"Collab opportunity — Nivara Soaps festive campaign"* · body is
a real brand outreach email.

*Right, part one — extracted fields,* each an editable field row with provenance: Brand
`Nivara Soaps` · Category `Personal care` · Direct or agency `Direct` · Budget `₹1,50,000`
(fixed) · Deliverables `2 × Reel`, `3 × Story` · Go live `8 Nov 2026` · Response deadline
`20 Oct 2026` · Usage rights `90 days` · Whitelisting `Yes` · Exclusivity requested `No` ·
Payment terms `0% advance, net 60`.

*Right, part two — `#assessment`, one self-contained element:*

- Score **20**, priority `P3`, type `Paid`
- Flags with a one-line explanation each: `Conflict` *"Personal care clashes with the active
  Santoor exclusivity, which runs to 31 Mar 2027 — after the 8 Nov go-live."* · `Lowball`
  *"57% of the quoted price, below Aanya's 70% minimum."* · `Usage overreach` *"90 days
  requested against a 30-day default."* · `Risky payment terms` *"No advance, net 60."*
- A note that the conflict **caps** the score at 20 regardless of the other terms
- Quote breakdown: base `2 × Reel ₹1,24,000` + `3 × Story ₹54,000` = `₹1,78,000`; bundle
  discount (5 deliverables) `−10% = −₹17,800` → `₹1,60,200`; usage fee (2 extra 30-day blocks)
  `+40% = +₹64,080`; whitelisting `+25% = +₹40,050`; exclusivity `not requested, +₹0`; **total
  `₹2,64,330`**
- Recommended action: **Decline**
- Action group, with Decline marked as recommended
- Reply draft, editable, with a copy button
- `#decision-result` region for the post-action confirmation

Also design these states:

- A field row **mid-edit** (input focused).
- **`#assessment` after a re-score.** Same inquiry with the budget corrected to `₹2,70,000`:
  `Lowball` has cleared, the score and priority have moved, the counter-offer is gone. I need
  both versions of this block to confirm the swap looks right. The `Conflict` flag stays —
  money does not fix a conflict, and the design should make that obvious.
- After `Approve & copy`: the confirmation, and the reply marked as copied.

---

**3. Creator Page** (`/creator/<id>`) — use Aanya Mehra

Profile header: Aanya Mehra `@aanyamehra` · Beauty & Skincare · Mumbai · Hindi, English ·
182,400 followers · 96,000 avg reach · 4.1% engagement.

Rate card, editable: Reel `₹62,000` · Story `₹18,000` · Static post `₹34,000` · Carousel
`₹45,000` · bundle discount `10%`.

Rules, editable: minimum acceptable `70%` of rate card · accepts barter `No` · usage rights
default `30 days` · max usage without extra fee `30 days`.

Partners: `Santoor` — Personal care — **EXCLUSIVE** — 528 days remaining. Also show an
**expired** partner variant so the inactive treatment is designed.

No-go categories: `Betting` `Tobacco` `Fairness creams`.

Capacity: `2 of 4 booked this month`. Blackout dates: none for Aanya — design the populated
variant too (`10-20 Nov 2026, travel`).

Inquiry history: a compact table of past inquiries with brand, date, score, and outcome
(approved / declined / asked for info / marked spam).

---

**4. DM Intake** (`/dm`)

Creator selector. A large paste area for Instagram DM text — show it holding real Hinglish:
*"hi ma'am, humein aapke saath ek collab karna hai. budget 40k hai, ek reel aur do stories
chahiye. diwali se pehle live karna hai."*

A screenshot upload area, used when AI is on. Design its **AI-off** state too: upload
disabled, with a short line explaining that screenshot reading needs AI and text paste still
works.

A `Process` action, then the extracted-fields preview before the inquiry joins the queue.

---

**5. Pipeline Summary** (`/pipeline`) — the agency head's screen, read-only

- Counts by priority: `P1 — 7` · `P2 — 9` · `P3 — 6` · `Ignore / spam — 8`
- Total value in play: `₹8,40,000` across P1, `₹4,10,000` across P2
- **`Conflicts caught — 2`** — the headline number, because it is the one the agency head
  cares about most
- Deals per creator, across the five creators
- `Skipped mail — 6`
- Decision log: a table of timestamp, creator, brand, action taken, and whether the reply was
  edited before sending

---

**6. Config** (`/config`)

A plain settings form, grouped. It needs to look like something a reviewer can read and trust,
because this screen is the proof that nothing is hardcoded:

- **Keywords** — the editable brand-keyword list used to filter inboxes (`collab`,
  `sponsorship`, `barter`, `PR package`, `ambassador`, and the rest)
- **Scoring weights** — rate fit `45`, brand fit `25`, urgency `15`, completeness `15`
- **Risk penalties** — payment risk `10`, usage overreach `5`, suspicious sender `15`
- **Thresholds** — minimum acceptable `70%`, urgency windows `2` and `7` days, duplicate
  window `14` days, priority bands `70 / 40 / 20`
- **Fees** — usage `+20%` per extra 30 days, whitelisting `+25%`, exclusivity `+30%`
- **Spam patterns** and the **brand → category lookup**
- **Reference date** — `19 Oct 2026`

## Deliverable

One static HTML file per screen, plus the extra state files called out above (the re-scored
`#assessment`, the mid-edit field row, the post-approve confirmation, the zero-results and
empty queue, the AI-off DM upload, the expired partner), and one shared CSS file. A short
note on the type scale, spacing scale, and colour roles so I can extend it consistently when
I split these into Jinja2 partials.
