# Brand Deal Inbox Triage

Proof-of-work build for the Walnut Folks Group "AI Product Engineer (Freshers)"
application, scoped to **Kalakaaar**, the group's talent management agency.

**All data in this app is synthetic and labelled SAMPLE DATA.** Every creator, brand,
email and DM is invented for this build.

## What this is

A talent manager at Kalakaaar handles many creators at once. Brand inquiries land in
creator mailboxes and Instagram DMs mixed together: real paid deals, lowballs, barter
pitches, scams, and offers that collide with an exclusive partnership. This app scans
those inboxes, extracts the deal terms, prices them against each creator's own rate
card, checks them against partners/no-go categories/capacity/blackout dates, scores
and ranks them, flags the risks, and drafts a reply the manager approves and copies.
**Nothing is ever sent automatically.**

Every flag and score traces to a rule in `config.yaml`. AI is an optional layer on top
— filling extraction gaps the rules left, writing reply language on request, and
reading DM screenshots — never the source of truth. The AI toggle in the header
switches everything to deterministic fallbacks, and the app stays fully usable either
way.

## The interface

The screens follow the Claude Design handoff in `design/kalakaaar-triage/` ("Deal
Desk"): one shared stylesheet, system fonts, no external requests, verdicts carried by
colour plus icon plus words, and rank shown by fill weight. `design/NOTES.md` has the
type scale, spacing scale and colour roles. The engine doesn't format anything for
display; `app/view.py` turns its output into what the screens show (flag tiers and
their one-line reasons, the budget-vs-quote bar, the quote argument, the score behind
a conflict cap) without changing a score, flag or action.

## Running it

**Docker (recommended):**

```bash
docker compose up -d --build
```

Open http://localhost:8000, click **Scan inboxes**, and the queue populates from
`seed/`. The SQLite database lives on a named volume (`app_data`) — see "Why the
database is rebuildable" below.

**Locally, without Docker:**

```bash
python -m venv .venv
.venv/bin/pip install -e .          # or: pip install fastapi "uvicorn[standard]" jinja2 pydantic pyyaml httpx python-multipart
.venv/bin/uvicorn app.main:app --reload
```

(On Windows: `.venv\Scripts\pip` / `.venv\Scripts\uvicorn`.)

## Deploy on Render

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/piyushtater158-cpu/brand-deal-inbox-triage)

`render.yaml` describes one free Docker web service in Singapore. The container binds
to the `PORT` Render injects. Only `OPENROUTER_API_KEY` is needed for AI (the free
model lists live in `config.yaml`); leave it empty and the app runs fully on the rules
path, with AI off. `AI_ENABLED_DEFAULT=true` (set in `render.yaml`) makes the header
toggle start on; without it the toggle starts off, and since every wake is a fresh
database, a toggle flipped by hand doesn't survive the next spin-down.

Two free-tier caveats, both expected by design:

- **Spin-down.** The service sleeps after about 15 minutes idle, and the first request
  after that takes up to a minute while it wakes.
- **Ephemeral disk.** Every wake or redeploy starts with an empty database. On boot the
  app reloads creators from `seed/` and runs a rules-only scan (even with AI on, because a
  wake shouldn't wait on a model), so the queue is always
  populated when someone opens it. The decision log, `/config` edits and the AI cache
  reset too (see "Why the database is rebuildable" below).

## Where the config is

`config.yaml` at the repo root — every keyword, scoring weight, risk penalty,
threshold, fee, brand lookup, and spam pattern the engine uses. Nothing is hardcoded
in Python. It's also editable from the running app at `/config` (renders the file,
validates the edit with pydantic before writing back, and every inquiry recomputes
against the new values).

`reference_date` in that file is the frozen "today" every date comparison in the
engine uses (expiry checks, blackout windows, urgency). It's set to `2026-10-19`, the
date this seed was authored against, so `expected_results.json` and the test suite
stay correct forever instead of drifting as real time passes. A real deployment would
drop this key (the engine falls back to `date.today()` when it's unset).

## Verifying it

```bash
pytest                           # 93 tests: quote math, extraction regex, AI-off
                                  # fallbacks, free-models-only + AI gap-filling rules,
                                  # manager edits + live re-score, DM
                                  # preview, config/creator saves, adding / editing /
                                  # removing creators, roster CSV round-trip, pasted
                                  # DMs surviving a rescan, and the full scenario fixture
python scripts/check_expected.py # standalone AI-off acceptance check, no pytest
                                  # needed — exits 0 on a full match
```

Against a running instance (the Docker container, or a deployed URL):

```bash
python scripts/smoke_test.py [base_url]    # 95 HTTP checks: every screen, filters,
                                           # edits, decisions, DM intake, adding a
                                           # creator + their DM, config, AI toggle,
                                           # 404s, concurrent writes, and the
                                           # expected-results match
python scripts/browser_test.py [base_url]  # 16 checks in real Edge/Chrome: HTMX swaps,
                                           # copy-to-clipboard, DM preview, with every
                                           # off-host request blocked; screenshots of
                                           # each screen land in scripts/screens/
```

`browser_test.py` needs `pip install playwright` (a dev-only dependency; it drives the
browser already installed, nothing to download). Both scripts change the target's
state, so point them at a demo instance, not one you're mid-review on.

The container has been verified with no internet access at all (an internal Docker
network), under Render free-tier limits (512 MB, 0.1 CPU) on an injected `PORT`:
all 84 smoke checks pass, ready in 7–13 seconds on the throttled CPU, using about
60 MB of memory.

`scripts/check_expected.py` is the brief's "automated test script passes with AI off"
acceptance test. It re-runs the real pipeline against `seed/demo_inbox.json` and
diffs the result against `seed/expected_results.json` — the regression fixture — for
all 29 inquiries (30 matching messages, one duplicate merge), printing a per-scenario
pass/fail table.

`seed/expected_results.json` was generated by `scripts/generate_expected.py`, which
runs the actual engine (not hand-typed numbers) and is meant to be regenerated —
**after manual review of its printed table** — any time `extract.py` / `quote.py` /
`score.py` / `config.yaml` / the seed changes. Independent, hand-computed ₹ arithmetic
(worked out before the code was run, so it can't just agree with itself) lives
separately in `tests/test_quote.py`.

`GET /api/debug` on the running app returns the full computed state for every
inquiry — the same proof-of-correctness surface, usable from a browser or `curl`.

## The 19 scenarios

`seed/demo_inbox.json` has 30 keyword-matching messages (25 email + 5 DM) covering all
18 scenarios named in the brief plus the agency-on-behalf-of-brand case, each tagged
with a `scenario` field, plus 10 plain filler deals for queue realism, plus 6
non-matching messages that must be skipped. The centerpiece pair: a rival soap brand
pitching Aanya Mehra while her Santoor exclusivity is active (`msg_002` — flagged
`conflict`, capped at score 20) sitting next to a rival protein brand pitching Rohan
Iyer after his exclusivity has already expired (`msg_007` — clean, scores on merit).
Same rule, opposite outcomes, from one date comparison.

Five creators, each carrying one structural condition the engine has to respect:
Aanya Mehra (active Santoor exclusivity), Rohan Iyer (expired exclusivity), Meera Nair
(at capacity, 4/4 booked), Kabir Shah (a blackout window), Tara Dsouza (accepts
barter above a minimum). **Rate-card figures are placeholders** — `config.yaml` and
`scripts/generate_seed_creators.py` flag this; they haven't been checked against a
real Indian creator rate-card source yet (see "What I'd do next").

## Adding or editing a creator

**Creators → Add creator** opens one form with everything the engine reads: profile
(name, handle, collabs email, niche, city, languages), audience, rate card (including
YouTube integration), rules, monthly capacity and deals booked this month, blackout
dates, partners with their exclusivity end dates, and no-go categories. **Edit all
details** on a creator's page opens the same form filled in. Saving validates every
value (nothing is saved on an error, and the form keeps what you typed), then
re-scores that creator's inquiries. The same page can remove a creator, which takes
their inquiries with them.

Niche, partner categories and no-go categories are matched word-for-word against
brand categories (the brand lookup in `/config`), so the form suggests the categories
the engine knows.

**DMs.** A new creator has no seed inbox, so their deals come in as Instagram DMs.
Their page has an **Instagram DMs** panel listing every DM inquiry for them, and a
**Paste a DM for …** button that opens DM intake with them preselected. DMs pasted in
are kept when **Scan inboxes** rebuilds the queue; seed DMs are rebuilt from `seed/`
as before.

**Keeping them.** On the free host, creators added here and pasted DMs last until the
next restart (see below). To make a creator permanent, use **Export roster CSV** on
the Creators page, replace `seed/roster_seed.csv` with the download, and commit. The
export is in exactly the format the app loads on boot.

## Plugging in a real inbox

The scanner sits behind one interface (`app/scanner.py`):

```python
class InboxScanner(Protocol):
    def fetch(self, creator: Creator) -> list[RawMessage]: ...
```

`SampleFolderScanner` reads `seed/demo_inbox.json`. A real IMAP, Gmail API, or Meta DM
export integration only needs to produce the same `RawMessage` fields (id, creator_id,
source, received_at, sender_name, sender_email_or_handle, sender_domain, subject,
raw_text) — swap the one class that's instantiated in `app/pipeline.py`, nothing else
in the pipeline changes. Keyword filtering happens *after* fetch, in the pipeline, so
it applies identically regardless of which scanner is installed.

## Why the database is rebuildable, not durable

SQLite is treated as a rebuildable artifact: `seed/roster_seed.csv` and
`seed/demo_inbox.json` are the source of truth, "Scan inboxes" rebuilds inquiries from
them (keeping DMs pasted in by hand, which no scan could bring back), and creators load
from the seed CSV the first time the database file is touched.
This means the app runs on any free, ephemeral-filesystem host unchanged. The
trade-off: the decision log (an append-only table, never cleared by a rescan) resets
on a cold start on a host that spins the container down between uses. Fine for a
demo; a real deployment would move `decisions` to a durable store first.

## AI

One module (`app/ai.py`) behind `OPENROUTER_API_KEY`. **Only free OpenRouter models are
ever called**: the model lists are in `config.yaml` (`ai.text_models`,
`ai.vision_models`; `OPENROUTER_MODEL` / `OPENROUTER_VISION_MODEL` can override them,
comma-separated), and any model without a `:free` suffix is dropped before a request
is built. Models are tried in chunks of three (OpenRouter's fallback-list limit); a
chunk that errors or returns unusable output moves on to the next.

| Task | AI on | AI off |
|---|---|---|
| Field extraction | Rules first; AI fills only the fields the rules left empty, and only with values that pass validation | Regex: ₹/k/L/lakh, Hinglish numerals, dates, deliverable keywords |
| Brand category | Chosen from the config's category vocabulary (conflict and no-go checks are exact matches), after the brand lookup | `brand_category_lookup` in config + "unknown" |
| Reply writing | **Write with AI** button on the inquiry: warmer wording, same facts and ₹ amounts | Template per recommended action |
| Screenshot OCR | Free vision model transcribes the DM, then the same extraction runs | Disabled — text paste only, per the brief |

Free models are slow (3–30 s), flaky, and capped (about 50 requests a day on an
account without purchased credits), so the AI layer is built to never make the app
feel broken:

- **Nothing waits on a model unless you asked for it.** Page loads and field edits
  only read cached AI replies, so re-scoring stays instant. A scan calls AI only for
  messages with gaps (4 of the 30 seed messages), in parallel, inside a 40 s budget;
  whatever isn't back by then keeps its rules extraction.
- **Every successful answer is cached** in SQLite by task + prompt, so a rescan, a DM
  preview → Add to queue, or a revisit doesn't spend quota again.
- **Rate limits pause AI instead of stalling it.** A per-minute limit pauses AI for a
  minute, the daily limit until 00:00 UTC; the header says so, and rules cover. An
  upstream provider's 429, a retired model's 404 or a model-specific 403 only skips
  that model chunk; only a rejected key (401) pauses AI.
- **Free model slugs churn.** OpenRouter retires `:free` variants without notice
  (two in this list were retired in October 2026). If AI stops filling gaps, check
  the slugs in `config.yaml` against `https://openrouter.ai/api/v1/models`.

If `OPENROUTER_API_KEY` isn't set, every AI call returns `None` immediately and the
caller falls through to the rules path — "AI on, unconfigured" behaves identically to
"AI off," which `tests/test_fallbacks.py` asserts directly. AI never creates,
suppresses, or re-scores a flag; `score.py` doesn't import `ai.py` at all.

## What I'd do next

- Verify the five rate cards against two real Indian creator rate-card benchmarks
  (150-200k follower tier) and cite the source in a `config.yaml` comment — the one
  thing a Kalakaaar reviewer would check first and the one thing no amount of correct
  logic compensates for.
- Move `decisions` to a durable store before any real deployment, per the tradeoff above.
