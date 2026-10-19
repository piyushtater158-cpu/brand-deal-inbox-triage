"""THE graded test. Runs the full pipeline (scan -> extract (AI off) -> dedupe ->
score) against seed/demo_inbox.json and asserts the result matches
seed/expected_results.json exactly — same type, same flags, same priority, no missing
flags, no spurious ones.

The fixture is the spec: regenerate it with `python scripts/generate_expected.py` only
after a deliberate engine change, and manually review the printed table before
trusting the new file (see that script's docstring). This test is what makes "all 18
scenario types produce the expected result" a result rather than a claim.
"""
import json
from pathlib import Path

from app.config_loader import reference_date
from app.db import load_creators_from_csv
from app.dedupe import merge_duplicates
from app.extract import extract_fields
from app.scanner import SampleFolderScanner, filter_by_keywords
from app.score import assess

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"


def _run_pipeline():
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
    return results, matching, skipped


def test_seed_loads_and_scan_counts_match():
    _, matching, skipped = _run_pipeline()
    assert len(matching) == 30, "expected 30 keyword-matching sample messages"
    assert len(skipped) == 6, "expected 6 non-matching messages to be skipped"


def test_all_scenarios_match_expected_results():
    results, _, _ = _run_pipeline()

    with open(SEED_DIR / "expected_results.json", encoding="utf-8") as f:
        expected = json.load(f)

    assert set(results.keys()) == set(expected.keys()), (
        f"inquiry set mismatch: engine produced {sorted(results.keys())}, "
        f"fixture expects {sorted(expected.keys())}"
    )

    for inquiry_id, exp in expected.items():
        actual = results[inquiry_id]
        scenario = exp.get("scenario", inquiry_id)
        assert actual.type == exp["type"], f"[{scenario}] type: {actual.type} != {exp['type']}"
        assert sorted(actual.flags) == sorted(exp["flags"]), (
            f"[{scenario}] flags: {sorted(actual.flags)} != {sorted(exp['flags'])}"
        )
        assert actual.priority == exp["priority"], (
            f"[{scenario}] priority: {actual.priority} != {exp['priority']}"
        )
        assert actual.recommended_action == exp["recommended_action"], (
            f"[{scenario}] action: {actual.recommended_action} != {exp['recommended_action']}"
        )


def test_santoor_conflict_flagged_and_expired_exclusivity_is_not():
    results, _, _ = _run_pipeline()
    conflict_case = results["msg_002"]  # Nivara Soaps vs Aanya's active Santoor exclusivity
    assert "conflict" in conflict_case.flags
    assert conflict_case.final_score <= 20

    expired_case = results["msg_007"]  # MuscleMax vs Rohan's expired IronCore exclusivity
    assert "conflict" not in expired_case.flags


def test_scam_and_lookalike_domain_land_in_spam_with_score_zero():
    results, _, _ = _run_pipeline()
    assert results["msg_012"].type == "spam"
    assert results["msg_012"].final_score == 0.0
    assert results["msg_013"].type == "spam"
    assert results["msg_013"].final_score == 0.0


def test_duplicate_email_and_dm_merge_into_one_thread():
    results, _, _ = _run_pipeline()
    assert "msg_015" not in results, "the DM duplicate should have merged into msg_001, not stand alone"
    assert "duplicate" in results["msg_001"].flags


def test_no_go_category_is_hard_zero():
    results, _, _ = _run_pipeline()
    betting_case = results["msg_008"]
    assert "no_go" in betting_case.flags
    assert betting_case.final_score == 0.0
