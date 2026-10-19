"""SQLite schema + persistence. Per Premise 11, this is a REBUILDABLE artifact, not a
durable store: creators load from seed/roster_seed.csv the first time the DB is
touched, and "Scan inboxes" re-ingests seed/demo_inbox.json fresh every time. The
decision log is the one append-only table that survives a rescan — see pipeline.py.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.models import (
    Assessment,
    BlackoutDate,
    Creator,
    Deliverable,
    Extraction,
    Partner,
    QuoteBreakdown,
    RateCard,
)

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"
DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "app.db"


def db_path() -> Path:
    return Path(os.environ.get("DB_PATH", str(DEFAULT_DB_PATH)))


@contextmanager
def get_conn():
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS creators (
    id TEXT PRIMARY KEY,
    name TEXT, ig_handle TEXT, email TEXT,
    niche TEXT, city TEXT, languages TEXT,
    followers INTEGER, avg_reach INTEGER, engagement_rate REAL,
    rate_card TEXT,
    min_acceptable_pct REAL, accepts_barter INTEGER, barter_min_product_value REAL,
    usage_rights_default_days INTEGER, max_usage_days_without_extra_fee INTEGER,
    no_go_categories TEXT,
    max_paid_deals_per_month INTEGER, current_booked_this_month INTEGER,
    blackout_dates TEXT
);

CREATE TABLE IF NOT EXISTS partners (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_id TEXT, brand TEXT, category TEXT,
    exclusive INTEGER, exclusivity_end_date TEXT
);

CREATE TABLE IF NOT EXISTS inquiries (
    id TEXT PRIMARY KEY,
    creator_id TEXT, source TEXT, received_at TEXT,
    sender_name TEXT, sender_email_or_handle TEXT, sender_domain TEXT,
    raw_text TEXT, subject TEXT, thread_key TEXT, message_ids TEXT, scenario TEXT
);

CREATE TABLE IF NOT EXISTS extractions (
    inquiry_id TEXT PRIMARY KEY,
    brand TEXT, brand_category TEXT, agency_or_direct TEXT,
    budget_amount REAL, budget_currency TEXT, budget_type TEXT, product_value REAL,
    deliverables TEXT,
    go_live_date TEXT, response_deadline TEXT, usage_rights_days INTEGER,
    exclusivity_requested INTEGER, exclusivity_requested_days INTEGER, whitelisting INTEGER,
    payment_advance_pct REAL, payment_net_days INTEGER,
    provenance TEXT
);

CREATE TABLE IF NOT EXISTS assessments (
    inquiry_id TEXT PRIMARY KEY,
    type TEXT, flags TEXT, rate_fit_pct REAL, brand_fit_score REAL,
    urgency_score REAL, completeness_score REAL, risk_penalty REAL, final_score REAL,
    priority TEXT, recommended_action TEXT, counter_offer_amount REAL,
    missing_fields TEXT, reason TEXT, quote TEXT, offer_value REAL
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inquiry_id TEXT, action TEXT, edited_reply TEXT, user TEXT, timestamp TEXT
);

CREATE TABLE IF NOT EXISTS skipped_mail (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_id TEXT, source TEXT, received_at TEXT, subject TEXT, reason TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY, value TEXT
);

CREATE TABLE IF NOT EXISTS ai_cache (
    key TEXT PRIMARY KEY, value TEXT, created_at TEXT
);
"""


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('ai_enabled', 'false')")


def reset_ingest_tables(conn: sqlite3.Connection) -> None:
    """Cleared on every 'Scan inboxes' — NOT creators, NOT decisions (append-only log)."""
    for table in ("inquiries", "extractions", "assessments", "skipped_mail"):
        conn.execute(f"DELETE FROM {table}")


def creators_loaded(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT COUNT(*) AS c FROM creators").fetchone()
    return row["c"] > 0


# ---------------------------------------------------------------------------------
# Seed loading
# ---------------------------------------------------------------------------------

def _parse_date(s: str | None) -> dt.date | None:
    if not s:
        return None
    return dt.date.fromisoformat(s)


def load_creators_from_csv(path: Path | None = None) -> list[Creator]:
    path = path or (SEED_DIR / "roster_seed.csv")
    creators: list[Creator] = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rate_card_raw = json.loads(row["rate_card_json"])
            partners_raw = json.loads(row["partners_json"])
            blackout_raw = json.loads(row["blackout_dates_json"])
            creators.append(
                Creator(
                    id=row["id"],
                    name=row["name"],
                    ig_handle=row["ig_handle"],
                    email=row["email"],
                    niche=json.loads(row["niche_json"]),
                    city=row["city"],
                    languages=json.loads(row["languages_json"]),
                    followers=int(row["followers"]),
                    avg_reach=int(row["avg_reach"]),
                    engagement_rate=float(row["engagement_rate"]),
                    rate_card=RateCard(
                        reel=rate_card_raw["reel"],
                        story=rate_card_raw["story"],
                        static_post=rate_card_raw["static_post"],
                        carousel=rate_card_raw["carousel"],
                        youtube_integration=rate_card_raw.get("youtube_integration"),
                        bundle_discount_pct=rate_card_raw["bundle_discount_pct"],
                    ),
                    min_acceptable_pct=float(row["min_acceptable_pct"]),
                    accepts_barter=row["accepts_barter"].lower() == "true",
                    barter_min_product_value=float(row["barter_min_product_value"]),
                    usage_rights_default_days=int(row["usage_rights_default_days"]),
                    max_usage_days_without_extra_fee=int(row["max_usage_days_without_extra_fee"]),
                    active_partners=[
                        Partner(
                            brand=p["brand"],
                            category=p["category"],
                            exclusive=p["exclusive"],
                            exclusivity_end_date=_parse_date(p.get("exclusivity_end_date")),
                        )
                        for p in partners_raw
                    ],
                    no_go_categories=json.loads(row["no_go_categories_json"]),
                    max_paid_deals_per_month=int(row["max_paid_deals_per_month"]),
                    current_booked_this_month=int(row["current_booked_this_month"]),
                    blackout_dates=[
                        BlackoutDate(
                            start=dt.date.fromisoformat(b["start"]),
                            end=dt.date.fromisoformat(b["end"]),
                            reason=b.get("reason", ""),
                        )
                        for b in blackout_raw
                    ],
                )
            )
    return creators


def save_creator(conn: sqlite3.Connection, c: Creator) -> None:
    rate_card = {
        "reel": c.rate_card.reel,
        "story": c.rate_card.story,
        "static_post": c.rate_card.static_post,
        "carousel": c.rate_card.carousel,
        "youtube_integration": c.rate_card.youtube_integration,
        "bundle_discount_pct": c.rate_card.bundle_discount_pct,
    }
    conn.execute(
        """INSERT OR REPLACE INTO creators
        (id, name, ig_handle, email, niche, city, languages, followers, avg_reach,
         engagement_rate, rate_card, min_acceptable_pct, accepts_barter,
         barter_min_product_value, usage_rights_default_days,
         max_usage_days_without_extra_fee, no_go_categories,
         max_paid_deals_per_month, current_booked_this_month, blackout_dates)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            c.id, c.name, c.ig_handle, c.email, json.dumps(c.niche), c.city,
            json.dumps(c.languages), c.followers, c.avg_reach, c.engagement_rate,
            json.dumps(rate_card), c.min_acceptable_pct, int(c.accepts_barter),
            c.barter_min_product_value, c.usage_rights_default_days,
            c.max_usage_days_without_extra_fee, json.dumps(c.no_go_categories),
            c.max_paid_deals_per_month, c.current_booked_this_month,
            json.dumps([
                {"start": b.start.isoformat(), "end": b.end.isoformat(), "reason": b.reason}
                for b in c.blackout_dates
            ]),
        ),
    )
    conn.execute("DELETE FROM partners WHERE creator_id = ?", (c.id,))
    for p in c.active_partners:
        conn.execute(
            "INSERT INTO partners (creator_id, brand, category, exclusive, exclusivity_end_date) "
            "VALUES (?,?,?,?,?)",
            (c.id, p.brand, p.category, int(p.exclusive),
             p.exclusivity_end_date.isoformat() if p.exclusivity_end_date else None),
        )


def _row_to_creator(conn: sqlite3.Connection, row: sqlite3.Row) -> Creator:
    rate_card = json.loads(row["rate_card"])
    partners_rows = conn.execute(
        "SELECT * FROM partners WHERE creator_id = ?", (row["id"],)
    ).fetchall()
    return Creator(
        id=row["id"], name=row["name"], ig_handle=row["ig_handle"], email=row["email"],
        niche=json.loads(row["niche"]), city=row["city"],
        languages=json.loads(row["languages"]), followers=row["followers"],
        avg_reach=row["avg_reach"], engagement_rate=row["engagement_rate"],
        rate_card=RateCard(
            reel=rate_card["reel"], story=rate_card["story"],
            static_post=rate_card["static_post"], carousel=rate_card["carousel"],
            youtube_integration=rate_card.get("youtube_integration"),
            bundle_discount_pct=rate_card["bundle_discount_pct"],
        ),
        min_acceptable_pct=row["min_acceptable_pct"],
        accepts_barter=bool(row["accepts_barter"]),
        barter_min_product_value=row["barter_min_product_value"],
        usage_rights_default_days=row["usage_rights_default_days"],
        max_usage_days_without_extra_fee=row["max_usage_days_without_extra_fee"],
        active_partners=[
            Partner(
                brand=p["brand"], category=p["category"], exclusive=bool(p["exclusive"]),
                exclusivity_end_date=_parse_date(p["exclusivity_end_date"]),
            )
            for p in partners_rows
        ],
        no_go_categories=json.loads(row["no_go_categories"]),
        max_paid_deals_per_month=row["max_paid_deals_per_month"],
        current_booked_this_month=row["current_booked_this_month"],
        blackout_dates=[
            BlackoutDate(start=dt.date.fromisoformat(b["start"]), end=dt.date.fromisoformat(b["end"]),
                         reason=b.get("reason", ""))
            for b in json.loads(row["blackout_dates"])
        ],
    )


def list_creators(conn: sqlite3.Connection) -> list[Creator]:
    rows = conn.execute("SELECT * FROM creators ORDER BY name").fetchall()
    return [_row_to_creator(conn, r) for r in rows]


def get_creator(conn: sqlite3.Connection, creator_id: str) -> Creator | None:
    row = conn.execute("SELECT * FROM creators WHERE id = ?", (creator_id,)).fetchone()
    return _row_to_creator(conn, row) if row else None


# ---------------------------------------------------------------------------------
# Extractions / assessments
# ---------------------------------------------------------------------------------

def extraction_to_row(ext: Extraction) -> dict:
    return {
        "brand": ext.brand, "brand_category": ext.brand_category,
        "agency_or_direct": ext.agency_or_direct, "budget_amount": ext.budget_amount,
        "budget_currency": ext.budget_currency, "budget_type": ext.budget_type,
        "product_value": ext.product_value,
        "deliverables": json.dumps([{"type": d.type, "count": d.count} for d in ext.deliverables]),
        "go_live_date": ext.go_live_date.isoformat() if ext.go_live_date else None,
        "response_deadline": ext.response_deadline.isoformat() if ext.response_deadline else None,
        "usage_rights_days": ext.usage_rights_days,
        "exclusivity_requested": int(ext.exclusivity_requested),
        "exclusivity_requested_days": ext.exclusivity_requested_days,
        "whitelisting": int(ext.whitelisting),
        "payment_advance_pct": ext.payment_advance_pct,
        "payment_net_days": ext.payment_net_days,
        "provenance": json.dumps(ext.provenance),
    }


def row_to_extraction(row: sqlite3.Row) -> Extraction:
    return Extraction(
        brand=row["brand"], brand_category=row["brand_category"],
        agency_or_direct=row["agency_or_direct"], budget_amount=row["budget_amount"],
        budget_currency=row["budget_currency"] or "INR", budget_type=row["budget_type"],
        product_value=row["product_value"],
        deliverables=[Deliverable(type=d["type"], count=d["count"]) for d in json.loads(row["deliverables"])],
        go_live_date=_parse_date(row["go_live_date"]),
        response_deadline=_parse_date(row["response_deadline"]),
        usage_rights_days=row["usage_rights_days"],
        exclusivity_requested=bool(row["exclusivity_requested"]),
        exclusivity_requested_days=row["exclusivity_requested_days"],
        whitelisting=bool(row["whitelisting"]),
        payment_advance_pct=row["payment_advance_pct"],
        payment_net_days=row["payment_net_days"],
        provenance=json.loads(row["provenance"]),
    )


def save_extraction(conn: sqlite3.Connection, inquiry_id: str, ext: Extraction) -> None:
    r = extraction_to_row(ext)
    conn.execute(
        """INSERT OR REPLACE INTO extractions
        (inquiry_id, brand, brand_category, agency_or_direct, budget_amount,
         budget_currency, budget_type, product_value, deliverables, go_live_date,
         response_deadline, usage_rights_days, exclusivity_requested,
         exclusivity_requested_days, whitelisting, payment_advance_pct,
         payment_net_days, provenance)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            inquiry_id, r["brand"], r["brand_category"], r["agency_or_direct"],
            r["budget_amount"], r["budget_currency"], r["budget_type"], r["product_value"],
            r["deliverables"], r["go_live_date"], r["response_deadline"],
            r["usage_rights_days"], r["exclusivity_requested"], r["exclusivity_requested_days"],
            r["whitelisting"], r["payment_advance_pct"], r["payment_net_days"], r["provenance"],
        ),
    )


def get_extraction(conn: sqlite3.Connection, inquiry_id: str) -> Extraction | None:
    row = conn.execute("SELECT * FROM extractions WHERE inquiry_id = ?", (inquiry_id,)).fetchone()
    return row_to_extraction(row) if row else None


def quote_to_json(q: QuoteBreakdown | None) -> str | None:
    if q is None:
        return None
    return json.dumps(q.__dict__)


def json_to_quote(s: str | None) -> QuoteBreakdown | None:
    if not s:
        return None
    return QuoteBreakdown(**json.loads(s))


def save_assessment(conn: sqlite3.Connection, inquiry_id: str, a: Assessment) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO assessments
        (inquiry_id, type, flags, rate_fit_pct, brand_fit_score, urgency_score,
         completeness_score, risk_penalty, final_score, priority, recommended_action,
         counter_offer_amount, missing_fields, reason, quote, offer_value)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            inquiry_id, a.type, json.dumps(a.flags), a.rate_fit_pct, a.brand_fit_score,
            a.urgency_score, a.completeness_score, a.risk_penalty, a.final_score,
            a.priority, a.recommended_action, a.counter_offer_amount,
            json.dumps(a.missing_fields), a.reason, quote_to_json(a.quote), a.offer_value,
        ),
    )


def row_to_assessment(row: sqlite3.Row) -> Assessment:
    return Assessment(
        type=row["type"], flags=json.loads(row["flags"]), rate_fit_pct=row["rate_fit_pct"],
        brand_fit_score=row["brand_fit_score"], urgency_score=row["urgency_score"],
        completeness_score=row["completeness_score"], risk_penalty=row["risk_penalty"],
        final_score=row["final_score"], priority=row["priority"],
        recommended_action=row["recommended_action"], counter_offer_amount=row["counter_offer_amount"],
        missing_fields=json.loads(row["missing_fields"]), reason=row["reason"],
        quote=json_to_quote(row["quote"]), offer_value=row["offer_value"],
    )


def get_assessment(conn: sqlite3.Connection, inquiry_id: str) -> Assessment | None:
    row = conn.execute("SELECT * FROM assessments WHERE inquiry_id = ?", (inquiry_id,)).fetchone()
    return row_to_assessment(row) if row else None


# ---------------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------------

def get_setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))


def ai_enabled(conn: sqlite3.Connection) -> bool:
    return get_setting(conn, "ai_enabled", "false") == "true"


def ai_cache_get(key: str) -> str | None:
    """Own short-lived connection: AI calls run in worker threads, outside any request
    transaction. A missing table (schema not initialised yet) is just a cache miss."""
    try:
        with get_conn() as conn:
            row = conn.execute("SELECT value FROM ai_cache WHERE key = ?", (key,)).fetchone()
    except sqlite3.OperationalError:
        return None
    return row["value"] if row else None


def ai_cache_put(key: str, value: str) -> None:
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO ai_cache (key, value, created_at) VALUES (?, ?, ?)",
                (key, value, dt.datetime.now().isoformat(timespec="seconds")),
            )
    except sqlite3.OperationalError:
        pass


# ---------------------------------------------------------------------------------
# Inquiries / skipped mail / decisions
# ---------------------------------------------------------------------------------

def save_inquiry(
    conn: sqlite3.Connection,
    inquiry_id: str,
    creator_id: str,
    source: str,
    received_at: dt.datetime,
    sender_name: str,
    sender_email_or_handle: str,
    sender_domain: str,
    raw_text: str,
    subject: str,
    thread_key: str,
    message_ids: list[str],
    scenario: str = "",
) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO inquiries
        (id, creator_id, source, received_at, sender_name, sender_email_or_handle,
         sender_domain, raw_text, subject, thread_key, message_ids, scenario)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            inquiry_id, creator_id, source, received_at.isoformat(), sender_name,
            sender_email_or_handle, sender_domain, raw_text, subject, thread_key,
            json.dumps(message_ids), scenario,
        ),
    )


def get_inquiry(conn: sqlite3.Connection, inquiry_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM inquiries WHERE id = ?", (inquiry_id,)).fetchone()


def list_inquiries(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM inquiries").fetchall()


def list_inquiries_with_assessments(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """SELECT i.*, c.name AS creator_name, c.ig_handle AS creator_handle
           FROM inquiries i JOIN creators c ON c.id = i.creator_id"""
    ).fetchall()
    out = []
    for row in rows:
        a = get_assessment(conn, row["id"])
        e = get_extraction(conn, row["id"])
        out.append({"inquiry": row, "assessment": a, "extraction": e})
    return out


def save_skipped(conn: sqlite3.Connection, creator_id: str, source: str,
                  received_at: dt.datetime, subject: str, reason: str) -> None:
    conn.execute(
        "INSERT INTO skipped_mail (creator_id, source, received_at, subject, reason) "
        "VALUES (?,?,?,?,?)",
        (creator_id, source, received_at.isoformat(), subject, reason),
    )


def list_skipped(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM skipped_mail ORDER BY received_at").fetchall()


def save_decision(conn: sqlite3.Connection, inquiry_id: str, action: str,
                   edited_reply: str, user: str = "talent_manager") -> None:
    conn.execute(
        "INSERT INTO decisions (inquiry_id, action, edited_reply, user, timestamp) "
        "VALUES (?,?,?,?,?)",
        (inquiry_id, action, edited_reply, user, dt.datetime.now().isoformat()),
    )


def list_decisions(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM decisions ORDER BY timestamp DESC").fetchall()


def get_decision_for_inquiry(conn: sqlite3.Connection, inquiry_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM decisions WHERE inquiry_id = ? ORDER BY timestamp DESC LIMIT 1",
        (inquiry_id,),
    ).fetchone()
