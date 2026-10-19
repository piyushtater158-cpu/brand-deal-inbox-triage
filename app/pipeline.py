"""Wires scanner -> extract -> dedupe -> score into the one thing "Scan inboxes"
does, and the one thing a single field edit does (reassess_inquiry). Everything here
is orchestration; the actual rules live in extract.py / quote.py / score.py.
"""
from __future__ import annotations

import sqlite3

from app import ai, db, extract
from app.config_loader import reference_date as get_reference_date
from app.dedupe import merge_duplicates, thread_key
from app.scanner import SampleFolderScanner, filter_by_keywords
from app.score import assess


def _extract_for_message(raw_text: str, subject: str, sender_domain: str, ref_date, ai_on: bool):
    if ai_on:
        ai_ext = ai.extract_with_ai(raw_text, subject, ref_date)
        if ai_ext is not None:
            return ai_ext
    return extract.extract_fields(raw_text, subject, sender_domain, ref_date)


def run_scan(conn: sqlite3.Connection) -> dict:
    creators = db.list_creators(conn)
    creators_by_id = {c.id: c for c in creators}
    scanner = SampleFolderScanner()
    all_messages = scanner.fetch_all_creators(creators)
    matching, skipped = filter_by_keywords(all_messages)

    db.reset_ingest_tables(conn)

    ref_date = get_reference_date()
    ai_on = db.ai_enabled(conn)

    pairs = []
    for msg in matching:
        ext = _extract_for_message(msg.raw_text, msg.subject, msg.sender_domain, ref_date, ai_on)
        pairs.append((msg, ext))

    merged = merge_duplicates(pairs)

    for group in merged:
        rep_msg = group.messages[0]
        creator = creators_by_id[rep_msg.creator_id]
        inquiry_id = rep_msg.id
        key = thread_key(rep_msg.creator_id, group.extraction.brand)

        db.save_inquiry(
            conn,
            inquiry_id=inquiry_id,
            creator_id=rep_msg.creator_id,
            source=rep_msg.source,
            received_at=rep_msg.received_at,
            sender_name=rep_msg.sender_name,
            sender_email_or_handle=rep_msg.sender_email_or_handle,
            sender_domain=rep_msg.sender_domain,
            raw_text=rep_msg.raw_text,
            subject=rep_msg.subject,
            thread_key=key,
            message_ids=[m.id for m in group.messages],
        )
        db.save_extraction(conn, inquiry_id, group.extraction)

        assessment = assess(
            creator, group.extraction, ref_date,
            raw_text=rep_msg.raw_text, sender_domain=rep_msg.sender_domain,
            is_duplicate=group.is_duplicate,
        )
        db.save_assessment(conn, inquiry_id, assessment)

    for msg, reason in skipped:
        db.save_skipped(conn, msg.creator_id, msg.source, msg.received_at, msg.subject, reason)

    return {"matched": len(matching), "skipped": len(skipped), "inquiries": len(merged)}


_FIELD_PARSERS = {
    "brand": lambda v: v or None,
    "brand_category": lambda v: v or None,
    "agency_or_direct": lambda v: v,
    "budget_amount": lambda v: float(v) if v not in (None, "") else None,
    "budget_type": lambda v: v,
    "product_value": lambda v: float(v) if v not in (None, "") else None,
    "deliverables": extract.parse_deliverables,
    "go_live_date": lambda v: __import__("datetime").date.fromisoformat(v) if v else None,
    "response_deadline": lambda v: __import__("datetime").date.fromisoformat(v) if v else None,
    "usage_rights_days": lambda v: int(v) if v not in (None, "") else None,
    "exclusivity_requested": lambda v: str(v).lower() in ("true", "on", "1", "yes"),
    "whitelisting": lambda v: str(v).lower() in ("true", "on", "1", "yes"),
    "payment_advance_pct": lambda v: float(v) if v not in (None, "") else None,
    "payment_net_days": lambda v: int(v) if v not in (None, "") else None,
}


def reassess_inquiry(conn: sqlite3.Connection, inquiry_id: str, field: str, value: str):
    """A manager edit on one field: parse it, mark it 'manual', re-run score.assess(),
    and persist — this is the whole 'instant re-score' requirement.
    """
    inquiry_row = db.get_inquiry(conn, inquiry_id)
    if inquiry_row is None:
        return None
    ext = db.get_extraction(conn, inquiry_id)
    if field not in _FIELD_PARSERS:
        raise ValueError(f"Unknown editable field: {field}")
    parsed = _FIELD_PARSERS[field](value)
    setattr(ext, field, parsed)
    ext.provenance[field] = "manual"

    creator = db.get_creator(conn, inquiry_row["creator_id"])
    ref_date = get_reference_date()
    prev_assessment = db.get_assessment(conn, inquiry_id)
    was_duplicate = prev_assessment is not None and "duplicate" in prev_assessment.flags

    assessment = assess(
        creator, ext, ref_date,
        raw_text=inquiry_row["raw_text"], sender_domain=inquiry_row["sender_domain"],
        is_duplicate=was_duplicate,
    )
    db.save_extraction(conn, inquiry_id, ext)
    db.save_assessment(conn, inquiry_id, assessment)
    return assessment


def reextract_inquiry(conn: sqlite3.Connection, inquiry_id: str, ai_on_override: bool | None = None):
    """'Re-extract with AI off' — makes the fallback path demonstrable on the same
    message without a full rescan.
    """
    inquiry_row = db.get_inquiry(conn, inquiry_id)
    if inquiry_row is None:
        return None
    ref_date = get_reference_date()
    ai_on = db.ai_enabled(conn) if ai_on_override is None else ai_on_override
    ext = _extract_for_message(
        inquiry_row["raw_text"], inquiry_row["subject"], inquiry_row["sender_domain"], ref_date, ai_on,
    )
    creator = db.get_creator(conn, inquiry_row["creator_id"])
    prev_assessment = db.get_assessment(conn, inquiry_id)
    was_duplicate = prev_assessment is not None and "duplicate" in prev_assessment.flags
    assessment = assess(
        creator, ext, ref_date,
        raw_text=inquiry_row["raw_text"], sender_domain=inquiry_row["sender_domain"],
        is_duplicate=was_duplicate,
    )
    db.save_extraction(conn, inquiry_id, ext)
    db.save_assessment(conn, inquiry_id, assessment)
    return assessment
