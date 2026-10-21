"""Real-browser check of the HTMX swaps and the copy button, which smoke_test.py can
only replay as HTTP. Drives an installed Edge (or Chrome) headlessly against a running
instance and blocks every request that leaves the app's own host, so a page that still
depends on a CDN fails here instead of in an offline container.

    pip install playwright            # dev-only; uses the installed browser, no download
    python scripts/browser_test.py [base_url] [--channel chrome]

Mutates the target's state (rescans, edits, logs decisions, adds a DM). Saves a
full-page screenshot of each screen to scripts/screens/. Exits 0 only if every check
passes.
"""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

args = [a for a in sys.argv[1:] if not a.startswith("--")]
BASE = (args[0] if args else "http://localhost:8000").rstrip("/")
CHANNEL = sys.argv[sys.argv.index("--channel") + 1] if "--channel" in sys.argv else "msedge"
SCREENS = Path(__file__).resolve().parent / "screens"
HINGLISH_DM = (
    "hi ma'am, humein aapke saath ek collab karna hai. budget 40k hai, "
    "ek reel aur do stories chahiye. diwali se pehle live karna hai."
)

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))


def shot(page, name: str) -> None:
    SCREENS.mkdir(exist_ok=True)
    page.screenshot(path=str(SCREENS / f"{name}.png"), full_page=True)


def run(page, blocked: list[str], console_errors: list[str]) -> None:
    page.goto(f"{BASE}/")
    if page.locator("#queue-list .empty__title", has_text="first scan").count():
        shot(page, "01-queue-empty")
    page.locator("form[action='/scan'] button").first.click()
    page.wait_for_url(f"{BASE}/")
    cards = page.locator("#queue-list .qcard")
    # Pasted DMs (dm_*) survive a rescan, so only the seed cards are counted.
    seed_cards = page.locator("#queue-list .qcard:not(:has(a[href^='/inquiry/dm_']))")
    expect(seed_cards).to_have_count(29)
    check("scan from the browser fills the queue", seed_cards.count() == 29, str(seed_cards.count()))
    shot(page, "02-queue")

    page.locator("#f-pri").select_option("P1")
    expect(page.locator("#queue-list .qcard .score:not(.score--p1)")).to_have_count(0)
    p1 = cards.count()
    check("priority filter swaps #queue-list in place and updates the URL",
          0 < p1 < 29 and "priority=P1" in page.url, f"{p1} cards, url {page.url}")
    page.locator("#f-type").select_option("spam")
    expect(page.locator("#queue-list .empty__title")).to_contain_text("No inquiries match")
    check("impossible filter shows the zero-results state", True)
    shot(page, "03-queue-zero-results")

    page.goto(f"{BASE}/inquiry/msg_002")
    assessment = page.locator("#assessment")
    lowball = assessment.locator(".flag-list .flag", has_text="Lowball")
    expect(lowball).to_have_count(1)
    shot(page, "04-inquiry")
    budget = page.locator("#f_budget_amount")
    budget.fill("₹2,70,000")
    budget.press("Tab")
    expect(lowball).to_have_count(0)
    check("budget edit re-renders #assessment: Lowball clears, Conflict and the cap stay",
          assessment.locator(".flag-list .flag", has_text="Conflict").count() == 1
          and assessment.locator(".score__num").inner_text() == "20",
          f"score {assessment.locator('.score__num').inner_text()}")
    expect(page.locator("#field-budget_amount .prov")).to_have_text("Edited")
    check("edited row's provenance chip flips to Edited (out-of-band swap)", True)
    expect(assessment.locator(".cleared-note")).to_contain_text("Lowball")
    check("re-score names the cleared flag", True)
    shot(page, "05-inquiry-rescored")

    deliverables = page.locator("#f_deliverables")
    deliverables.fill("1 × Reel")
    deliverables.press("Tab")
    expect(assessment.locator(".quote__row--total")).to_contain_text("₹1,02,300")
    check("deliverables edit re-prices the quote to ₹1,02,300", True)

    deliverables.fill("2 × Podcast")
    deliverables.press("Tab")
    expect(assessment.locator(".alert")).to_contain_text("Podcast")
    expect(page.locator("#field-deliverables.has-error")).to_have_count(1)
    check("bad deliverables input shows an inline error on the row and the assessment", True)

    page.get_by_role("button", name="Copy reply").click()
    expect(page.locator(".reply.is-copied")).to_have_count(1)
    copied = page.evaluate("navigator.clipboard.readText()")
    check("Copy reply puts the draft on the clipboard", copied.strip().startswith("Hi "), copied[:40])

    page.get_by_role("button", name="Decline", exact=True).click()
    expect(page.locator("#decision-result")).to_contain_text("Declined · logged")
    check("Decline logs and confirms in #decision-result without a page load",
          page.url == f"{BASE}/inquiry/msg_002")
    shot(page, "06-inquiry-decided")

    page.locator(".ai-toggle__btn").click()
    expect(page.locator("form.ai-toggle--on")).to_have_count(1)
    page.locator(".ai-toggle__btn").click()
    expect(page.locator("form.ai-toggle--off")).to_have_count(1)
    check("AI toggle flips on and back off", True)

    page.goto(f"{BASE}/creator/aanya_mehra")
    page.get_by_role("link", name="Paste a DM for Aanya").first.click()
    page.wait_for_url("**/dm?creator=aanya_mehra")
    check("creator page links to DM intake with the creator preselected",
          page.locator("#dm-creator").input_value() == "aanya_mehra")
    shot(page, "07-dm-ai-off")
    page.locator("#dm-text").fill(HINGLISH_DM)
    page.get_by_role("button", name="Process").click()
    expect(page.get_by_text("Check before adding to the queue")).to_be_visible()
    check("DM preview shows ₹40,000 and 1 reel + 2 stories",
          page.locator("#p-budget_amount").input_value() == "₹40,000"
          and page.locator("#p-deliverables").input_value() == "1 × Reel, 2 × Story")
    shot(page, "08-dm-preview")
    page.locator("#p-brand").fill("Glow Brand")
    page.get_by_role("button", name="Add to queue").click()
    page.wait_for_url("**/inquiry/dm_*")
    check("Add to queue opens the new inquiry with the edited brand",
          page.locator("#f_brand").input_value() == "Glow Brand"
          and page.locator("#field-brand .prov").inner_text() == "Edited")

    for path, name in [("/creator/aanya_mehra", "09-creator"), ("/creator/kabir_shah", "10-creator-blackout"),
                       ("/creators", "11-creators"), ("/pipeline", "12-pipeline"), ("/config", "13-config"),
                       ("/skipped", "14-skipped"), ("/creators/new", "15-creator-add"),
                       ("/creator/aanya_mehra/edit", "16-creator-edit")]:
        page.goto(f"{BASE}{path}")
        shot(page, name)
    check("no requests left the app's host", not blocked, ", ".join(sorted(set(blocked))[:5]))
    check("no browser console errors", not console_errors, " | ".join(console_errors[:3]))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    host = urlparse(BASE).netloc
    blocked: list[str] = []
    console_errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=CHANNEL, headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        context.grant_permissions(["clipboard-read", "clipboard-write"], origin=BASE)
        page = context.new_page()
        page.set_default_timeout(15000)

        def gate(route):
            if urlparse(route.request.url).netloc == host:
                route.continue_()
            else:
                blocked.append(route.request.url)
                route.abort()

        page.route("**/*", gate)
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        try:
            run(page, blocked, console_errors)
        except Exception as e:  # noqa: BLE001 — a timeout mid-run is itself a failed check
            check("browser test ran to completion", False, f"{type(e).__name__}: {str(e).splitlines()[0]}")
        browser.close()

    width = max(len(n) for n, _, _ in results)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {'' if ok else detail}".rstrip())
    failed = sum(not ok for _, ok, _ in results)
    print("-" * (width + 8))
    print(f"{len(results) - failed}/{len(results)} checks passed against {BASE} ({CHANNEL})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
