"""End-to-end smoke test against a running instance — the Docker container locally,
or the deployed URL. Drives every screen and flow over plain HTTP, the same requests
the browser and HTMX make, and prints a pass/fail table.

    python scripts/smoke_test.py                      # http://localhost:8000
    python scripts/smoke_test.py https://<host>       # a deployed instance

Mutates the target's state: rescans, edits, logs decisions and saves config (then
restores it). Exits 0 only if every check passes. Needs only httpx (an app dependency).
"""
from __future__ import annotations

import csv
import html
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"
BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
PAGES = ["/", "/dm", "/creators", "/pipeline", "/config", "/skipped",
         "/creator/aanya_mehra", "/inquiry/msg_002"]
HX = {"HX-Request": "true"}
HINGLISH_DM = (
    "hi ma'am, humein aapke saath ek collab karna hai. budget 40k hai, "
    "ek reel aur do stories chahiye. diwali se pehle live karna hai."
)
INDIAN_RUPEES = re.compile(r"₹\d{1,2}(?:,\d{2})*,\d{3}|₹\d{1,3}")
CARD = re.compile(r'<li class="qcard[^"]*">\s*<div class="score score--([a-z0-9]+)')

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, bool(ok), detail))
    return bool(ok)


def debug(c: httpx.Client) -> dict:
    return c.get("/api/debug").json()


def row(c: httpx.Client, inquiry_id: str) -> dict:
    return next(r for r in debug(c)["inquiries"] if r["inquiry_id"] == inquiry_id)


def set_ai(c: httpx.Client, on: bool) -> None:
    c.post("/settings/ai-toggle", data={"enabled": "true" if on else "false"})


def golden_mismatches(c: httpx.Client) -> list[str]:
    expected = json.loads((SEED_DIR / "expected_results.json").read_text(encoding="utf-8"))
    actual = {r["inquiry_id"]: r for r in debug(c)["inquiries"]}
    bad = []
    for iid, exp in expected.items():
        a = actual.get(iid)
        if a is None:
            bad.append(f"{iid} missing")
            continue
        for key in ("type", "priority", "recommended_action"):
            if a[key] != exp[key]:
                bad.append(f"{iid} {key} {a[key]} != {exp[key]}")
        if sorted(a["flags"]) != sorted(exp["flags"]):
            bad.append(f"{iid} flags {sorted(a['flags'])} != {sorted(exp['flags'])}")
    extra = set(actual) - set(expected)
    if extra:
        bad.append(f"unexpected inquiries {sorted(extra)}")
    return bad


def edit(c: httpx.Client, iid: str, field: str, value: str | None) -> httpx.Response:
    data = {"field": field}
    if value is not None:
        data["value"] = value
    return c.post(f"/inquiry/{iid}/edit", data=data, headers=HX)


def add_dm(c: httpx.Client, creator_id: str, text: str) -> str:
    """Process -> preview -> Add to queue, submitting the preview's own field values."""
    preview = c.post("/dm/process", data={"creator_id": creator_id, "dm_text": text}).text
    data = {"creator_id": creator_id, "sender": "", "dm_text": text}
    for name, value in re.findall(r'name="([fo]_[a-z_]+)"[^>]*value="([^"]*)"', preview):
        data[name] = html.unescape(value)
    return c.post("/dm/commit", data=data).headers.get("location", "")


def run() -> None:
    c = httpx.Client(base_url=BASE, timeout=90)

    t0 = time.perf_counter()
    first = c.get("/")
    check("GET / responds (health check path)", first.status_code == 200,
          f"{first.status_code} in {time.perf_counter() - t0:.1f}s")
    check("SAMPLE DATA marker in chrome", "SAMPLE DATA" in first.text)
    if debug(c)["inquiries"]:
        check("empty queue state before first scan", True, "skipped: target already has data")
    else:
        check("empty queue state before first scan", "The queue is empty until the first scan" in first.text)

    set_ai(c, False)

    # Scan
    r = c.post("/scan")
    check("POST /scan redirects to queue", r.status_code == 303 and r.headers.get("location") == "/",
          str(r.status_code))
    d = debug(c)
    check("scan produced 29 inquiries", len(d["inquiries"]) == 29, str(len(d["inquiries"])))
    check("scan skipped 6 messages", d["skipped_count"] == 6, str(d["skipped_count"]))
    bad = golden_mismatches(c)
    check("AI-off results match seed/expected_results.json", not bad, "; ".join(bad[:5]))

    # Offline constraint: every page and its assets must be served by the app itself.
    for path in PAGES:
        page = c.get(path)
        external = re.findall(r'(?:src|href)="(https?://[^"]+)"', page.text)
        check(f"no external requests on {path}", page.status_code == 200 and not external,
              f"{page.status_code} " + ", ".join(sorted(set(external))))
    for asset in sorted(set(re.findall(r'(?:src|href)="(/static/[^"]+)"', c.get("/").text))):
        r = c.get(asset)
        check(f"asset {asset} served", r.status_code == 200 and len(r.content) > 0,
              f"{r.status_code}, {len(r.content)} bytes")

    # Queue
    q = c.get("/").text
    cards = CARD.findall(q)
    check("queue renders a card per inquiry", len(cards) == 29, str(len(cards)))
    rank = {"p1": 0, "p2": 1, "p3": 2, "ignore": 3}
    check("queue sorted by priority", [rank[p] for p in cards] == sorted(rank[p] for p in cards))
    check("skipped notice shows 6", "6 messages skipped" in q)
    check("Indian ₹ grouping on queue (₹2,64,330 / ₹1,50,000)", "₹2,64,330" in q and "₹1,50,000" in q)
    western = re.findall(r"₹\d{1,3},\d{3},\d{3}", q)
    check("no Western ₹ grouping on queue", not western, ", ".join(western[:3]))
    check("skipped list page shows the 6", c.get("/skipped").text.count("<tr>") == 7)

    # Filters: HTMX partial and the no-JS full-page form
    conflicts = sum("conflict" in r["flags"] for r in d["inquiries"])
    p1 = c.get("/partials/queue-list", params={"priority": "P1"}).text
    p1_cards = CARD.findall(p1)
    check("filter partial: priority=P1 only P1 cards", p1_cards and set(p1_cards) == {"p1"},
          f"{len(p1_cards)} cards")
    check("filter partial is just the #queue-list region",
          p1.lstrip().startswith('<section id="queue-list"') and "<html" not in p1)
    fc_cards = len(CARD.findall(c.get("/partials/queue-list", params={"flag": "conflict"}).text))
    check("filter partial: flag=conflict count", fc_cards == conflicts, f"{fc_cards} vs {conflicts}")
    unflagged = sum(not r["flags"] for r in d["inquiries"])
    none_cards = len(CARD.findall(c.get("/partials/queue-list", params={"flag": "none"}).text))
    check("filter partial: flag=none shows unflagged only", none_cards == unflagged, f"{none_cards} vs {unflagged}")
    zero = c.get("/partials/queue-list", params={"type": "spam", "priority": "P1"}).text
    check("filter partial: zero-results state", "No inquiries match these filters" in zero and not CARD.findall(zero))
    nojs = c.get("/", params={"creator": "kabir_shah"}).text
    kabir = sum(r["creator_id"] == "kabir_shah" for r in d["inquiries"])
    check("no-JS filter on full page", len(CARD.findall(nojs)) == kabir, f"{kabir} expected")

    # Every inquiry detail page
    failures = []
    for r_ in d["inquiries"]:
        resp = c.get(f"/inquiry/{r_['inquiry_id']}")
        if resp.status_code != 200 or 'id="assessment"' not in resp.text or 'id="decision-result"' not in resp.text:
            failures.append(f"{r_['inquiry_id']}:{resp.status_code}")
    check("all 29 inquiry pages render with #assessment and #decision-result", not failures,
          ", ".join(failures))
    nivara = c.get("/inquiry/msg_002").text
    check("Nivara page: conflict cap note and quote argument",
          "Score capped at 20 by Conflict" in nivara and "How the quote is built" in nivara and "₹2,64,330" in nivara)

    # Field edits on the Nivara Soaps conflict case
    before = row(c, "msg_002")
    check("Nivara quote ₹2,64,330 before edits", before["quote_total"] == 264330.0, str(before["quote_total"]))
    r = edit(c, "msg_002", "budget_amount", "₹2,70,000")
    a = row(c, "msg_002")
    check("budget edit returns #assessment plus the edited row out-of-band",
          r.status_code == 200 and r.text.lstrip().startswith('<section id="assessment"')
          and 'id="field-budget_amount"' in r.text and 'hx-swap-oob="true"' in r.text)
    check("budget ₹2,70,000: Lowball clears, Conflict stays, score capped",
          "lowball" not in a["flags"] and "conflict" in a["flags"] and a["final_score"] <= 20, str(a["flags"]))
    check("re-score shows the cleared Lowball", "Cleared since last score" in r.text and "flag--cleared" in r.text)
    r = edit(c, "msg_002", "deliverables", "1 × Reel")
    check("deliverables edit re-prices to ₹1,02,300", row(c, "msg_002")["quote_total"] == 102300.0,
          str(row(c, "msg_002")["quote_total"]))
    r = edit(c, "msg_002", "whitelisting", "no")
    check("whitelisting off drops its fee (₹86,800)", row(c, "msg_002")["quote_total"] == 86800.0,
          str(row(c, "msg_002")["quote_total"]))
    r = edit(c, "msg_002", "go_live_date", "2026-11-08")
    check("date field edit", r.status_code == 200 and 'role="alert"' not in r.text, str(r.status_code))
    for field, value in [("deliverables", "2 × Podcast"), ("budget_amount", "abc"),
                         ("go_live_date", "not-a-date"), ("no_such_field", "x")]:
        r = edit(c, "msg_002", field, value)
        check(f"bad edit {field}={value!r} shows inline error", r.status_code == 200 and 'role="alert"' in r.text,
              str(r.status_code))
    r = c.post("/inquiry/msg_002/edit", data={"field": "brand", "value": "Nivara Soaps"})
    check("edit without JavaScript redirects back to the page",
          r.status_code == 303 and r.headers.get("location") == "/inquiry/msg_002", str(r.status_code))
    page = c.get("/inquiry/msg_002").text
    check("edited fields show the Edited provenance", "prov--edited" in page)
    r = c.post("/inquiry/msg_002/reextract", headers=HX)
    check("re-extract with AI off restores ₹2,64,330",
          r.status_code == 200 and row(c, "msg_002")["quote_total"] == 264330.0)

    # Decisions
    for iid, action, label in [("msg_001", "accept_and_negotiate", "Approved"),
                               ("msg_002", "decline", "Declined"),
                               ("msg_003", "counter_offer", "Countered"),
                               ("msg_004", "ask_for_info", "Asked for info"),
                               ("msg_012", "mark_spam", "Marked spam")]:
        r = c.post(f"/inquiry/{iid}/decision", headers=HX,
                   data={"action": action, "reply_text": "smoke reply", "draft": "smoke reply"})
        check(f"decision {action} confirms in #decision-result",
              r.status_code == 200 and r.text.lstrip().startswith('<div id="decision-result"')
              and f"{label} · logged" in r.text, str(r.status_code))
    log = c.get("/pipeline").text
    check("decisions appear in pipeline decision log", all(f"/inquiry/{i}" in log for i in
                                                            ("msg_001", "msg_002", "msg_003", "msg_004", "msg_012")))

    # Creators
    with open(SEED_DIR / "roster_seed.csv", encoding="utf-8") as f:
        roster = list(csv.DictReader(f))
    roster_page = c.get("/creators").text
    check("creators list links every creator", all(f"/creator/{cr['id']}" in roster_page for cr in roster))
    for cr in roster:
        r = c.get(f"/creator/{cr['id']}")
        check(f"creator page {cr['id']}", r.status_code == 200 and cr["name"] in r.text, str(r.status_code))
    aanya = c.get("/creator/aanya_mehra").text
    check("Aanya: active Santoor exclusivity, followers 1,82,400",
          "Santoor" in aanya and "EXCLUSIVE" in aanya and "days remaining" in aanya and "1,82,400" in aanya)
    check("Rohan: expired exclusivity shown as expired", "excl--expired" in c.get("/creator/rohan_iyer").text)

    seed = next(cr for cr in roster if cr["id"] == "aanya_mehra")
    rc = json.loads(seed["rate_card_json"])
    r = c.post("/creator/aanya_mehra/update", data={"reel": "70,000"})
    check("rate-card edit redirects back with a re-score count",
          r.status_code == 303 and "rescored=" in r.headers.get("location", ""), str(r.status_code))
    raised = row(c, "msg_002")["quote_total"]
    check("rate-card edit re-scores existing inquiries", raised != 264330.0, str(raised))
    c.post("/creator/aanya_mehra/update", data={"reel": str(rc["reel"]),
                                                "bundle_discount_pct": f"{rc['bundle_discount_pct'] * 100:g}"})
    check("restoring the rate card restores ₹2,64,330", row(c, "msg_002")["quote_total"] == 264330.0)

    # DM intake: process -> preview -> add to queue
    dm = c.get("/dm").text
    check("DM page: AI-off screenshot note, no upload input",
          "ai-off-note" in dm and 'type="file"' not in dm)
    count_before = len(debug(c)["inquiries"])
    preview = c.post("/dm/process", data={"creator_id": "aanya_mehra", "dm_text": HINGLISH_DM})
    check("Hinglish DM shows a preview, not yet in the queue",
          "Check before adding to the queue" in preview.text and len(debug(c)["inquiries"]) == count_before)
    check("Hinglish DM preview: ₹40,000 and 1 reel + 2 stories",
          'value="₹40,000"' in preview.text and 'value="1 × Reel, 2 × Story"' in preview.text)
    loc = add_dm(c, "aanya_mehra", HINGLISH_DM)
    check("Add to queue creates the inquiry", loc.startswith("/inquiry/dm_") and c.get(loc).status_code == 200, loc)
    ids = [add_dm(c, "tara_dsouza", f"collab? budget {20 + i}k, ek reel") for i in range(2)]
    check("two DMs in quick succession are both kept",
          len(set(ids)) == 2 and len(debug(c)["inquiries"]) == count_before + 3, ", ".join(ids))
    r = c.post("/dm/process", data={"creator_id": "aanya_mehra", "dm_text": ""})
    check("empty DM re-renders the form with a prompt", r.status_code == 200 and "Paste the DM text first" in r.text)

    # Pipeline
    pl = c.get("/pipeline").text
    d = debug(c)
    tile = re.search(r'kpi--headline">.*?<p class="kpi__num">(\d+)<', pl, re.S)
    check("pipeline conflicts-caught tile", tile is not None and int(tile.group(1)) ==
          sum("conflict" in r["flags"] for r in d["inquiries"]), tile.group(1) if tile else "missing")
    money = re.findall(r'<p class="kpi__num num">([^<]*)</p>', pl)
    check("pipeline ₹ tiles use Indian grouping",
          money and all(INDIAN_RUPEES.fullmatch(m.strip()) for m in money), ", ".join(money))

    # Config: structured save, raw YAML round-trip, rejection
    r = c.post("/config/update", data={"w_rate_fit": "50"})
    check("config: weights not totalling 100 are rejected", "must total 100" in r.text)
    cfg_page = c.get("/config").text
    raw = html.unescape(re.search(r'<textarea[^>]*name="raw_yaml"[^>]*>(.*?)</textarea>', cfg_page, re.S).group(1))
    r = c.post("/config/update", data={"raw_yaml": raw})
    check("config: saving unchanged YAML validates and re-scores",
          r.status_code == 303 and "rescored=" in r.headers.get("location", ""), str(r.status_code))
    r = c.post("/config/update", data={"raw_yaml": "scoring_weights: nope"})
    check("config: malformed YAML is rejected", "Validation failed" in r.text)
    c.post("/scan")
    bad = golden_mismatches(c)
    check("after config round-trip, rescan still matches expected results", not bad, "; ".join(bad[:5]))

    # AI toggle with no API key configured: must behave exactly like AI off
    set_ai(c, True)
    check("AI toggle on shows in chrome", "ai-toggle--on" in c.get("/").text)
    check("DM page offers screenshot upload when AI on", 'type="file"' in c.get("/dm").text)
    c.post("/scan")
    ai_touched = {r["inquiry_id"] for r in debug(c)["inquiries"] if r.get("ai_fields")}
    bad = [b for b in golden_mismatches(c) if b.split()[0] not in ai_touched]
    check("AI on: every inquiry AI didn't fill matches the rules results", not bad,
          "; ".join(bad[:5]) or (f"AI filled gaps in {len(ai_touched)}: {sorted(ai_touched)}"
                                 if ai_touched else "no key or no gaps: identical to AI off"))
    set_ai(c, False)
    check("AI toggle off shows in chrome", "ai-toggle--off" in c.get("/").text)

    # 404s
    for path in ("/inquiry/nope", "/creator/nope"):
        check(f"404 for {path}", c.get(path).status_code == 404)
    check("404 for edit on unknown inquiry",
          c.post("/inquiry/nope/edit", data={"field": "brand", "value": "x"}).status_code == 404)

    # Concurrency: reads and SQLite writes at once
    def hit(i: int) -> int:
        with httpx.Client(base_url=BASE, timeout=90) as cc:
            if i % 3 == 0:
                return edit(cc, "msg_005", "budget_amount", str(50000 + i)).status_code
            return cc.get("/" if i % 2 else "/pipeline").status_code
    with ThreadPoolExecutor(max_workers=10) as pool:
        codes = list(pool.map(hit, range(30)))
    check("30 concurrent requests (reads + edits) all succeed", set(codes) == {200},
          ", ".join(str(x) for x in sorted(set(codes))))

    c.post("/scan")
    bad = golden_mismatches(c)
    check("final rescan matches expected results", not bad, "; ".join(bad[:5]))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        run()
    except Exception as e:  # noqa: BLE001 — a crash mid-run is itself a failed check
        check("smoke test ran to completion", False, f"{type(e).__name__}: {e}")
    width = max(len(n) for n, _, _ in results)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {detail if not ok or detail.startswith('skipped') else ''}".rstrip())
    failed = sum(not ok for _, ok, _ in results)
    print("-" * (width + 8))
    print(f"{len(results) - failed}/{len(results)} checks passed against {BASE}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
