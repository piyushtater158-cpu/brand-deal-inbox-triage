#!/usr/bin/env python
"""Standalone acceptance check, AI off — the "automated test script passes with AI
off" acceptance test (brief section 13). Doesn't need pytest; exits 0 on full match,
1 on any mismatch, and prints a human-readable per-scenario pass/fail table either way.

Usage: python scripts/check_expected.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Force AI off for this run, regardless of the environment, so this script is always
# the "AI off" proof the acceptance test asks for.
os.environ.pop("OPENROUTER_API_KEY", None)
os.environ.pop("OPENROUTER_MODEL", None)

from app.config_loader import reference_date
from app.db import load_creators_from_csv
from app.dedupe import merge_duplicates
from app.extract import extract_fields
from app.scanner import SampleFolderScanner, filter_by_keywords
from app.score import assess

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"


def main() -> int:
    creators = load_creators_from_csv()
    creators_by_id = {c.id: c for c in creators}
    scanner = SampleFolderScanner()
    all_messages = scanner.fetch_all_creators(creators)
    matching, skipped = filter_by_keywords(all_messages)
    ref_date = reference_date()

    pairs = [
        (msg, extract_fields(msg.raw_text, msg.subject, msg.sender_domain, ref_date))
        for msg in matching
    ]
    merged = merge_duplicates(pairs)

    results = {}
    for group in merged:
        rep_msg = group.messages[0]
        creator = creators_by_id[rep_msg.creator_id]
        a = assess(
            creator, group.extraction, ref_date,
            raw_text=rep_msg.raw_text, sender_domain=rep_msg.sender_domain,
            is_duplicate=group.is_duplicate,
        )
        results[rep_msg.id] = a

    with open(SEED_DIR / "expected_results.json", encoding="utf-8") as f:
        expected = json.load(f)

    print(f"Scan: {len(matching)} matched, {len(skipped)} skipped, {len(merged)} inquiries\n")
    print(f"{'scenario':<42} {'result':<6} detail")
    print("-" * 90)

    all_ok = True
    missing = set(expected.keys()) - set(results.keys())
    extra = set(results.keys()) - set(expected.keys())
    for inquiry_id in missing:
        all_ok = False
        print(f"{expected[inquiry_id].get('scenario', inquiry_id):<42} {'FAIL':<6} missing from engine output")
    for inquiry_id in extra:
        all_ok = False
        print(f"{inquiry_id:<42} {'FAIL':<6} unexpected extra inquiry")

    for inquiry_id, exp in expected.items():
        if inquiry_id not in results:
            continue
        a = results[inquiry_id]
        scenario = exp.get("scenario", inquiry_id)
        problems = []
        if a.type != exp["type"]:
            problems.append(f"type {a.type}!={exp['type']}")
        if sorted(a.flags) != sorted(exp["flags"]):
            problems.append(f"flags {sorted(a.flags)}!={sorted(exp['flags'])}")
        if a.priority != exp["priority"]:
            problems.append(f"priority {a.priority}!={exp['priority']}")
        if a.recommended_action != exp["recommended_action"]:
            problems.append(f"action {a.recommended_action}!={exp['recommended_action']}")
        ok = not problems
        all_ok = all_ok and ok
        print(f"{scenario:<42} {'PASS' if ok else 'FAIL':<6} {'; '.join(problems)}")

    print("-" * 90)
    print("ALL SCENARIOS PASS" if all_ok else "SOME SCENARIOS FAILED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
