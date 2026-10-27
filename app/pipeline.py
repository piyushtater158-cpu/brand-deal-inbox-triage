"""Wires scanner -> extract -> dedupe -> score into the one thing "Scan inboxes"
does, and the one thing a single field edit does (reassess_inquiry). Everything here
is orchestration; the actual rules live in extract.py / quote.py / score.py.
"""
from __future__ import annotations

import datetime as dt
import re
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor, wait

from app import ai, db, extract
from app.config_loader import load_config
from app.config_loader import reference_date as get_reference_date
from app.dedupe import merge_duplicates, thread_key
from app.scanner import SampleFolderScanner, filter_by_keywords
from app.score import assess


def _ai_fill(ext, raw_text: str, subject: str, ref_date) -> bool:
    filled = ai.extract_with_ai(raw_text, subject, ref_date, extract.category_vocabulary())
    if filled:
        extract.fill_gaps(ext, filled)
    return bool(filled)


def _extract_for_message(raw_text: str, subject: str, sender_domain: str, ref_date, ai_on: bool):
    ext = extract.extract_fields(raw_text, subject, sender_domain, ref_date)
    if ai_on and extract.needs_ai(ext):
        _ai_fill(ext, raw_text, subject, ref_date)
    return ext


def _extract_all(messages, ref_date, ai_on: bool) -> tuple[list, dict]:
    """Rules for every message; AI in parallel for the ones with gaps, inside a time
    budget. Anything AI hasn't answered by the deadline keeps its rules extraction
    (its answer still lands in the cache for the next scan)."""
    exts = [extract.extract_fields(m.raw_text, m.subject, m.sender_domain, ref_date) for m in messages]
    stats = {"ai_on": ai_on, "needed": 0, "filled": 0}
    if not ai_on:
        return exts, stats
    todo = [i for i, e in enumerate(exts) if extract.needs_ai(e)]
    stats["needed"] = len(todo)
    if not todo:
        return exts, stats
    cfg = load_config()["ai"]
    pool = ThreadPoolExecutor(max_workers=int(cfg.get("scan_workers", 4)))
    futures = {
        pool.submit(ai.extract_with_ai, messages[i].raw_text, messages[i].subject, ref_date,
                    extract.category_vocabulary()): i
        for i in todo
    }
    done, _ = wait(futures, timeout=float(cfg.get("scan_time_budget_seconds", 40)))
    pool.shutdown(wait=False, cancel_futures=True)
    for f in done:
        filled = f.result() if not f.exception() else None
        if filled:
            extract.fill_gaps(exts[futures[f]], filled)
            stats["filled"] += 1
    return exts, stats


def scan_note(stats: dict) -> str:
    if not stats.get("ai_on"):
        return "rules only (AI off)"
    if not stats["needed"]:
        return "AI on · rules found every scored field, no AI calls needed"
    return (f"AI on · {stats['needed']} message{'s' if stats['needed'] != 1 else ''} had gaps the rules "
            f"couldn't fill · AI filled {stats['filled']}")


def run_scan(conn: sqlite3.Connection, ai_on_override: bool | None = None) -> dict:
    creators = db.list_creators(conn)
    creators_by_id = {c.id: c for c in creators}
    scanner = SampleFolderScanner()
    all_messages = scanner.fetch_all_creators(creators)
    matching, skipped = filter_by_keywords(all_messages)

    ref_date = get_reference_date()
    ai_on = db.ai_enabled(conn) if ai_on_override is None else ai_on_override
    exts, stats = _extract_all(matching, ref_date, ai_on)

    db.reset_ingest_tables(conn)
    merged = merge_duplicates(list(zip(matching, exts)))

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

    db.set_setting(conn, "last_scan", dt.datetime.now().isoformat(timespec="minutes"))
    db.set_setting(conn, "last_scan_note", scan_note(stats))
    return {"matched": len(matching), "skipped": len(skipped), "inquiries": len(merged), **stats}


_AMOUNT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(k|l|lakh|lakhs|lac)?", re.IGNORECASE)


def parse_amount(value: str) -> float | None:
    """A manager-typed rupee amount: '₹1,50,000', '150000', '1.5L', '40k'."""
    text = (value or "").strip().lower().replace("₹", "").replace(",", "").replace(" ", "")
    text = re.sub(r"^(rs\.?|inr)", "", text)
    if not text:
        return None
    m = _AMOUNT_RE.fullmatch(text)
    if not m:
        raise ValueError(f"Can't read '{value}' as an amount — try 150000, 1,50,000 or 1.5L")
    amount = float(m.group(1))
    suffix = (m.group(2) or "").lower()
    if suffix == "k":
        amount *= 1_000
    elif suffix:
        amount *= 100_000
    return amount


_FIELD_PARSERS = {
    "brand": lambda v: v.strip() or None,
    "brand_category": lambda v: v.strip().lower() or None,
    "agency_or_direct": lambda v: v if v in ("direct", "agency") else "direct",
    "budget_amount": parse_amount,
    "budget_type": lambda v: v,
    "product_value": parse_amount,
    "deliverables": extract.parse_deliverables,
    "go_live_date": lambda v: __import__("datetime").date.fromisoformat(v) if v else None,
    "response_deadline": lambda v: __import__("datetime").date.fromisoformat(v) if v else None,
    "usage_rights_days": lambda v: int(v) if v not in (None, "") else None,
    "exclusivity_requested": lambda v: str(v).lower() in ("true", "on", "1", "yes"),
    "whitelisting": lambda v: str(v).lower() in ("true", "on", "1", "yes"),
    "payment_advance_pct": lambda v: float(v) if v not in (None, "") else None,
    "payment_net_days": lambda v: int(v) if v not in (None, "") else None,
}


def parse_field(field: str, value: str):
    if field not in _FIELD_PARSERS:
        raise ValueError(f"Unknown editable field: {field}")
    return _FIELD_PARSERS[field](value)


def rescore_inquiries(conn: sqlite3.Connection, creator_id: str | None = None) -> int:
    """Re-run score.assess() on stored extractions — after a rate-card, rule or config
    change. Manager edits survive because the extraction isn't re-derived.
    """
    ref_date = get_reference_date()
    count = 0
    for row in db.list_inquiries(conn):
        if creator_id and row["creator_id"] != creator_id:
            continue
        creator = db.get_creator(conn, row["creator_id"])
        prev = db.get_assessment(conn, row["id"])
        a = assess(
            creator, db.get_extraction(conn, row["id"]), ref_date,
            raw_text=row["raw_text"], sender_domain=row["sender_domain"],
            is_duplicate="duplicate" in (prev.flags if prev else []),
        )
        db.save_assessment(conn, row["id"], a)
        count += 1
    return count


def reassess_inquiry(conn: sqlite3.Connection, inquiry_id: str, field: str, value: str):
    """A manager edit on one field: parse it, mark it 'manual', re-run score.assess(),
    and persist — this is the whole 'instant re-score' requirement.
    """
    inquiry_row = db.get_inquiry(conn, inquiry_id)
    if inquiry_row is None:
        return None
    ext = db.get_extraction(conn, inquiry_id)
    setattr(ext, field, parse_field(field, value))
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


DM_DOMAIN = "instagram.com"


def extract_dm(text: str, ai_on: bool):
    return _extract_for_message(text, "", DM_DOMAIN, get_reference_date(), ai_on)


def add_dm_inquiry(conn: sqlite3.Connection, creator_id: str, text: str, sender: str, ext) -> str:
    """A pasted DM joins the queue through the same assess() as scanned mail."""
    creator = db.get_creator(conn, creator_id)
    assessment = assess(creator, ext, get_reference_date(), raw_text=text, sender_domain=DM_DOMAIN)
    now = dt.datetime.now()
    inquiry_id = f"dm_{int(now.timestamp())}_{uuid.uuid4().hex[:6]}"
    db.save_inquiry(
        conn, inquiry_id=inquiry_id, creator_id=creator_id, source="dm",
        received_at=now, sender_name=sender or "Instagram DM", sender_email_or_handle=sender,
        sender_domain=DM_DOMAIN, raw_text=text, subject="",
        thread_key=thread_key(creator_id, ext.brand), message_ids=[inquiry_id],
    )
    db.save_extraction(conn, inquiry_id, ext)
    db.save_assessment(conn, inquiry_id, assessment)
    return inquiry_id
