"""Real-browser check of the HTMX swaps, which smoke_test.py can only replay as HTTP.
Drives an installed Edge (or Chrome) headlessly against a running instance and blocks
every request that leaves the app's own host, so a page that still depends on a CDN
fails here instead of in an offline container.

    pip install playwright            # dev-only; uses the installed browser, no download
    python scripts/browser_test.py [base_url] [--channel chrome]

Mutates the target's state (rescans, edits, logs a decision). Writes a screenshot of the
re-scored inquiry to scripts/browser_test_inquiry.png. Exits 0 only if every check passes.
"""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

args = [a for a in sys.argv[1:] if not a.startswith("--")]
BASE = (args[0] if args else "http://localhost:8000").rstrip("/")
CHANNEL = sys.argv[sys.argv.index("--channel") + 1] if "--channel" in sys.argv else "msedge"
SCREENSHOT = Path(__file__).resolve().parent / "browser_test_inquiry.png"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))


def run(page, blocked: list[str], console_errors: list[str]) -> None:
    page.goto(f"{BASE}/")
    page.get_by_role("button", name="Scan inboxes").click()
    page.wait_for_url(f"{BASE}/")
    cards = page.locator("#queue-list .queue-card")
    expect(cards).to_have_count(29)
    check("scan from the browser fills the queue", cards.count() == 29, str(cards.count()))

    page.locator('select[name="priority"]').select_option("P1")
    expect(page.locator("#queue-list .queue-card:not(.priority-p1)")).to_have_count(0)
    p1 = cards.count()
    check("priority filter swaps #queue-list in place", 0 < p1 < 29 and page.url == f"{BASE}/",
          f"{p1} cards, url {page.url}")
    page.locator('select[name="type"]').select_option("spam")
    expect(page.locator("#queue-list .empty-state")).to_be_visible()
    check("impossible filter shows the zero-results state", True)

    page.goto(f"{BASE}/inquiry/msg_002")
    assessment = page.locator("#assessment")
    expect(assessment.locator(".flag-lowball")).to_have_count(1)
    budget = page.locator("#f_budget_amount")
    budget.fill("270000")
    budget.press("Tab")
    expect(assessment.locator(".flag-lowball")).to_have_count(0)
    check("budget edit re-renders #assessment: Lowball clears",
          assessment.locator(".flag-conflict").count() == 1 and assessment.locator(".score").inner_text() == "20",
          f"score {assessment.locator('.score').inner_text()}")

    deliverables = page.locator("#f_deliverables")
    deliverables.fill("1 × Reel")
    deliverables.press("Tab")
    expect(assessment.locator(".quote-total")).to_contain_text("₹1,02,300")
    check("deliverables edit re-prices the quote to ₹1,02,300", True)

    deliverables.fill("2 × Podcast")
    deliverables.press("Tab")
    expect(assessment.locator(".edit-error")).to_contain_text("Podcast")
    check("bad deliverables input shows an inline error", True)

    page.get_by_role("button", name="Decline").click()
    expect(page.locator("#decision-result")).to_contain_text("Logged: Decline")
    check("Decline logs and confirms in #decision-result", page.url == f"{BASE}/inquiry/msg_002")
    page.screenshot(path=str(SCREENSHOT), full_page=True)

    page.get_by_role("button", name="AI OFF", exact=True).click()
    expect(page.get_by_role("button", name="AI ON", exact=True)).to_be_visible()
    page.get_by_role("button", name="AI ON", exact=True).click()
    expect(page.get_by_role("button", name="AI OFF", exact=True)).to_be_visible()
    check("AI toggle flips on and back off", True)

    for path in ("/dm", "/pipeline", "/config", "/creator/aanya_mehra"):
        page.goto(f"{BASE}{path}")
    check("no requests left the app's host", not blocked, ", ".join(sorted(set(blocked))[:5]))
    check("no browser console errors", not console_errors, " | ".join(console_errors[:3]))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    host = urlparse(BASE).netloc
    blocked: list[str] = []
    console_errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=CHANNEL, headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
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
