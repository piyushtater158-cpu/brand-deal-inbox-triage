"""Runs the real pipeline (AI off) against seed/demo_inbox.json and writes
seed/expected_results.json — the regression fixture test_expected_results.py checks
against. This is how "all scenario types produce the expected result" becomes a
reviewable artifact instead of a hand-typed guess: every number here came from the
engine itself. Independent, hand-computed arithmetic lives separately in
tests/test_quote.py, which this script does not touch.

Run again any time extract.py / quote.py / score.py / config.yaml / the seed changes,
then MANUALLY review the printed summary before trusting the new fixture.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db
from app.config_loader import reference_date
from app.dedupe import merge_duplicates, thread_key
from app.extract import extract_fields
from app.scanner import SampleFolderScanner, filter_by_keywords
from app.score import assess

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"


def main() -> None:
    creators = db.load_creators_from_csv()
    creators_by_id = {c.id: c for c in creators}

    scanner = SampleFolderScanner()
    all_messages = scanner.fetch_all_creators(creators)
    matching, skipped = filter_by_keywords(all_messages)

    ref_date = reference_date()

    pairs = []
    for msg in matching:
        ext = extract_fields(msg.raw_text, msg.subject, msg.sender_domain, ref_date)
        pairs.append((msg, ext))

    merged = merge_duplicates(pairs)

    # scenario tag lookup from the raw seed file (not part of the engine's output —
    # purely so the fixture and this report are human-readable)
    with open(SEED_DIR / "demo_inbox.json", encoding="utf-8") as f:
        raw_by_id = {m["id"]: m for m in json.load(f)}

    results: dict[str, dict] = {}
    print(f"{'inquiry_id':<10} {'scenario':<38} {'type':<10} {'score':>6} {'prio':<6} flags")
    print("-" * 110)
    for group in merged:
        rep_msg = group.messages[0]
        creator = creators_by_id[rep_msg.creator_id]
        inquiry_id = rep_msg.id
        scenario = raw_by_id.get(rep_msg.id, {}).get("scenario", "")

        a = assess(
            creator, group.extraction, ref_date,
            raw_text=rep_msg.raw_text, sender_domain=rep_msg.sender_domain,
            is_duplicate=group.is_duplicate,
        )

        results[inquiry_id] = {
            "scenario": scenario,
            "creator_id": rep_msg.creator_id,
            "brand": group.extraction.brand,
            "message_ids": [m.id for m in group.messages],
            "type": a.type,
            "flags": sorted(a.flags),
            "priority": a.priority,
            "final_score": a.final_score,
            "recommended_action": a.recommended_action,
            "rate_fit_pct": a.rate_fit_pct,
            "counter_offer_amount": a.counter_offer_amount,
            "quote_total": a.quote.total if a.quote else None,
        }
        print(
            f"{inquiry_id:<10} {scenario:<38} {a.type:<10} {a.final_score:>6.1f} "
            f"{a.priority:<6} {','.join(sorted(a.flags))}"
        )

    print("-" * 110)
    print(f"{len(merged)} inquiries from {len(matching)} matching messages, "
          f"{len(skipped)} skipped.")

    out_path = SEED_DIR / "expected_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
