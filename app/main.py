"""FastAPI app. Thin routes — everything that matters lives in pipeline.py / score.py
/ quote.py; this file wires HTTP <-> those functions and renders Jinja2 templates.
"""
from __future__ import annotations

import base64
import uuid
from pathlib import Path

import yaml
from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import ai, db, pipeline
from app.config_loader import load_config, reference_date, save_config
from app.extract import extract_fields
from app.reply import generate_reply
from app.score import assess

BASE_DIR = Path(__file__).resolve().parent
app = FastAPI(title="Brand Deal Inbox Triage (SAMPLE DATA)")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _fmt_inr(amount) -> str:
    if amount is None:
        return "—"
    n = int(round(amount))
    s = str(n)
    if len(s) <= 3:
        return f"₹{s}"
    last3 = s[-3:]
    rest = s[:-3]
    groups = []
    while len(rest) > 2:
        groups.insert(0, rest[-2:])
        rest = rest[:-2]
    if rest:
        groups.insert(0, rest)
    return "₹" + ",".join(groups + [last3])


templates.env.filters["inr"] = _fmt_inr


def _ensure_db() -> None:
    with db.get_conn() as conn:
        db.init_schema(conn)
        if not db.creators_loaded(conn):
            for c in db.load_creators_from_csv():
                db.save_creator(conn, c)


@app.on_event("startup")
def on_startup():
    _ensure_db()


# -------------------------------------------------------------------------------
# Triage queue
# -------------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def queue_page(
    request: Request, creator: str = "", type: str = "", flag: str = "", priority: str = "",
):
    with db.get_conn() as conn:
        rows = db.list_inquiries_with_assessments(conn)
        skipped = db.list_skipped(conn)
        ai_on = db.ai_enabled(conn)
        creators = db.list_creators(conn)

    filtered = _filter_queue(rows, creator, type, flag, priority)
    filtered.sort(key=lambda r: (_priority_rank(r["assessment"].priority), -r["assessment"].final_score))

    return templates.TemplateResponse(
        request,
        "queue.html",
        {
            "rows": filtered, "skipped_count": len(skipped),
            "skipped": skipped, "ai_on": ai_on, "creators": creators,
            "filters": {"creator": creator, "type": type, "flag": flag, "priority": priority},
            "has_data": len(rows) > 0,
        },
    )


def _priority_rank(p: str) -> int:
    return {"P1": 0, "P2": 1, "P3": 2, "Ignore": 3}.get(p, 4)


def _filter_queue(rows, creator, type_, flag, priority):
    out = []
    for r in rows:
        if creator and r["inquiry"]["creator_id"] != creator:
            continue
        if type_ and r["assessment"].type != type_:
            continue
        if flag and flag not in r["assessment"].flags:
            continue
        if priority and r["assessment"].priority != priority:
            continue
        out.append(r)
    return out


@app.get("/partials/queue-list", response_class=HTMLResponse)
def queue_list_partial(
    request: Request, creator: str = "", type: str = "", flag: str = "", priority: str = "",
):
    with db.get_conn() as conn:
        rows = db.list_inquiries_with_assessments(conn)
    filtered = _filter_queue(rows, creator, type, flag, priority)
    filtered.sort(key=lambda r: (_priority_rank(r["assessment"].priority), -r["assessment"].final_score))
    return templates.TemplateResponse(request, "partials/queue_list.html", {"rows": filtered})


@app.post("/scan", response_class=HTMLResponse)
def scan_inboxes(request: Request):
    with db.get_conn() as conn:
        pipeline.run_scan(conn)
    return RedirectResponse("/", status_code=303)


# -------------------------------------------------------------------------------
# Inquiry detail
# -------------------------------------------------------------------------------

@app.get("/inquiry/{inquiry_id}", response_class=HTMLResponse)
def inquiry_detail(request: Request, inquiry_id: str):
    with db.get_conn() as conn:
        inquiry = db.get_inquiry(conn, inquiry_id)
        if inquiry is None:
            raise HTTPException(status_code=404, detail="Inquiry not found")
        extraction = db.get_extraction(conn, inquiry_id)
        assessment = db.get_assessment(conn, inquiry_id)
        creator = db.get_creator(conn, inquiry["creator_id"])
        ai_on = db.ai_enabled(conn)
        decision = db.get_decision_for_inquiry(conn, inquiry_id)
        reply_draft = generate_reply(creator, extraction, assessment, ai_on)

    return templates.TemplateResponse(
        request,
        "inquiry_detail.html",
        {
            "inquiry": inquiry, "extraction": extraction,
            "assessment": assessment, "creator": creator, "ai_on": ai_on,
            "decision": decision, "reply_draft": reply_draft,
        },
    )


@app.post("/inquiry/{inquiry_id}/edit", response_class=HTMLResponse)
def edit_field(request: Request, inquiry_id: str, field: str = Form(...), value: str = Form("")):
    edit_error = None
    with db.get_conn() as conn:
        inquiry = db.get_inquiry(conn, inquiry_id)
        if inquiry is None:
            raise HTTPException(status_code=404, detail="Inquiry not found")
        try:
            assessment = pipeline.reassess_inquiry(conn, inquiry_id, field, value)
        except ValueError as e:
            # 200, not 4xx: HTMX only swaps successful responses, and the manager
            # needs to see why the edit didn't take.
            edit_error = f"Couldn't save {field.replace('_', ' ')}: {e}"
            assessment = db.get_assessment(conn, inquiry_id)
        extraction = db.get_extraction(conn, inquiry_id)
        creator = db.get_creator(conn, inquiry["creator_id"])
        ai_on = db.ai_enabled(conn)
        reply_draft = generate_reply(creator, extraction, assessment, ai_on)

    return templates.TemplateResponse(
        request,
        "partials/assessment.html",
        {
            "inquiry": inquiry, "extraction": extraction,
            "assessment": assessment, "creator": creator, "reply_draft": reply_draft,
            "decision": None, "edit_error": edit_error,
        },
    )


@app.post("/inquiry/{inquiry_id}/reextract", response_class=HTMLResponse)
def reextract(request: Request, inquiry_id: str):
    with db.get_conn() as conn:
        assessment = pipeline.reextract_inquiry(conn, inquiry_id, ai_on_override=False)
        inquiry = db.get_inquiry(conn, inquiry_id)
        extraction = db.get_extraction(conn, inquiry_id)
        creator = db.get_creator(conn, inquiry["creator_id"])
        reply_draft = generate_reply(creator, extraction, assessment, False)

    return templates.TemplateResponse(
        request,
        "partials/assessment.html",
        {
            "inquiry": inquiry, "extraction": extraction,
            "assessment": assessment, "creator": creator, "reply_draft": reply_draft,
            "decision": None,
        },
    )


@app.post("/inquiry/{inquiry_id}/decision", response_class=HTMLResponse)
def make_decision(
    request: Request, inquiry_id: str, action: str = Form(...), reply_text: str = Form(""),
):
    with db.get_conn() as conn:
        db.save_decision(conn, inquiry_id, action, reply_text)
        decision = db.get_decision_for_inquiry(conn, inquiry_id)

    return templates.TemplateResponse(
        request,
        "partials/decision_result.html",
        {"decision": decision},
    )


# -------------------------------------------------------------------------------
# Creator page
# -------------------------------------------------------------------------------

@app.get("/creator/{creator_id}", response_class=HTMLResponse)
def creator_page(request: Request, creator_id: str):
    with db.get_conn() as conn:
        creator = db.get_creator(conn, creator_id)
        if creator is None:
            raise HTTPException(status_code=404, detail="Creator not found")
        rows = db.list_inquiries_with_assessments(conn)
        ai_on = db.ai_enabled(conn)
    history = [r for r in rows if r["inquiry"]["creator_id"] == creator_id]
    return templates.TemplateResponse(
        request,
        "creator.html",
        {"creator": creator, "history": history, "ai_on": ai_on,
         "ref_date": reference_date()},
    )


@app.post("/creator/{creator_id}/update")
def update_creator(
    request: Request, creator_id: str,
    reel: float = Form(...), story: float = Form(...), static_post: float = Form(...),
    carousel: float = Form(...), bundle_discount_pct: float = Form(...),
    min_acceptable_pct: float = Form(...), accepts_barter: bool = Form(False),
    barter_min_product_value: float = Form(0),
    usage_rights_default_days: int = Form(30), max_usage_days_without_extra_fee: int = Form(30),
):
    with db.get_conn() as conn:
        creator = db.get_creator(conn, creator_id)
        creator.rate_card.reel = reel
        creator.rate_card.story = story
        creator.rate_card.static_post = static_post
        creator.rate_card.carousel = carousel
        creator.rate_card.bundle_discount_pct = bundle_discount_pct
        creator.min_acceptable_pct = min_acceptable_pct
        creator.accepts_barter = accepts_barter
        creator.barter_min_product_value = barter_min_product_value
        creator.usage_rights_default_days = usage_rights_default_days
        creator.max_usage_days_without_extra_fee = max_usage_days_without_extra_fee
        db.save_creator(conn, creator)

        # Existing inquiries for this creator re-score against the new rate card —
        # "editable" means it changes outcomes, not just the displayed number.
        ref_date = reference_date()
        for row in db.list_inquiries(conn):
            if row["creator_id"] != creator_id:
                continue
            ext = db.get_extraction(conn, row["id"])
            prev = db.get_assessment(conn, row["id"])
            a = assess(
                creator, ext, ref_date, raw_text=row["raw_text"],
                sender_domain=row["sender_domain"],
                is_duplicate="duplicate" in (prev.flags if prev else []),
            )
            db.save_assessment(conn, row["id"], a)

    return RedirectResponse(f"/creator/{creator_id}", status_code=303)


# -------------------------------------------------------------------------------
# DM intake
# -------------------------------------------------------------------------------

@app.get("/dm", response_class=HTMLResponse)
def dm_intake_page(request: Request):
    with db.get_conn() as conn:
        creators = db.list_creators(conn)
        ai_on = db.ai_enabled(conn)
    return templates.TemplateResponse(
        request, "dm_intake.html", {"creators": creators, "ai_on": ai_on, "preview": None},
    )


@app.post("/dm/process", response_class=HTMLResponse)
async def dm_process(
    request: Request, creator_id: str = Form(...), dm_text: str = Form(""),
    screenshot: UploadFile | None = None,
):
    with db.get_conn() as conn:
        creators = db.list_creators(conn)
        creator = db.get_creator(conn, creator_id)
        ai_on = db.ai_enabled(conn)
        ref_date = reference_date()

        text = dm_text
        if (not text) and screenshot is not None and ai_on:
            content = await screenshot.read()
            b64 = base64.b64encode(content).decode()
            ocr_text = ai.ocr_screenshot_ai(b64)
            text = ocr_text or ""

        preview = None
        new_inquiry_id = None
        if text.strip():
            ext = extract_fields(text, "", "instagram.com", ref_date) if not ai_on else (
                ai.extract_with_ai(text, "", ref_date) or extract_fields(text, "", "instagram.com", ref_date)
            )
            a = assess(creator, ext, ref_date, raw_text=text, sender_domain="instagram.com")
            import datetime as dt
            new_inquiry_id = f"dm_{int(dt.datetime.now().timestamp())}_{uuid.uuid4().hex[:6]}"
            db.save_inquiry(
                conn, inquiry_id=new_inquiry_id, creator_id=creator_id, source="dm",
                received_at=dt.datetime.now(), sender_name="DM intake", sender_email_or_handle="",
                sender_domain="instagram.com", raw_text=text, subject="",
                thread_key=f"{creator_id}::{(ext.brand or 'unknown').lower()}",
                message_ids=[new_inquiry_id],
            )
            db.save_extraction(conn, new_inquiry_id, ext)
            db.save_assessment(conn, new_inquiry_id, a)
            preview = {"extraction": ext, "assessment": a}

    if new_inquiry_id:
        return RedirectResponse(f"/inquiry/{new_inquiry_id}", status_code=303)

    return templates.TemplateResponse(
        request,
        "dm_intake.html",
        {"creators": creators, "ai_on": ai_on, "preview": preview},
    )


# -------------------------------------------------------------------------------
# Pipeline summary
# -------------------------------------------------------------------------------

@app.get("/pipeline", response_class=HTMLResponse)
def pipeline_summary(request: Request):
    with db.get_conn() as conn:
        rows = db.list_inquiries_with_assessments(conn)
        skipped = db.list_skipped(conn)
        decisions = db.list_decisions(conn)
        creators = db.list_creators(conn)
        ai_on = db.ai_enabled(conn)

    counts = {"P1": 0, "P2": 0, "P3": 0, "Ignore": 0}
    value_p1 = 0.0
    value_p2 = 0.0
    conflicts_caught = 0
    deals_per_creator = {c.id: 0 for c in creators}
    for r in rows:
        a = r["assessment"]
        counts[a.priority] = counts.get(a.priority, 0) + 1
        if a.priority == "P1" and a.offer_value:
            value_p1 += a.offer_value
        if a.priority == "P2" and a.offer_value:
            value_p2 += a.offer_value
        if "conflict" in a.flags:
            conflicts_caught += 1
        creator_id = r["inquiry"]["creator_id"]
        deals_per_creator[creator_id] = deals_per_creator.get(creator_id, 0) + 1

    return templates.TemplateResponse(
        request,
        "pipeline.html",
        {
            "counts": counts, "value_p1": value_p1, "value_p2": value_p2,
            "conflicts_caught": conflicts_caught, "deals_per_creator": deals_per_creator,
            "creators": {c.id: c for c in creators}, "skipped_count": len(skipped),
            "decisions": decisions, "ai_on": ai_on,
        },
    )


# -------------------------------------------------------------------------------
# Config
# -------------------------------------------------------------------------------

@app.get("/config", response_class=HTMLResponse)
def config_page(request: Request):
    cfg = load_config(force_reload=True)
    with db.get_conn() as conn:
        ai_on = db.ai_enabled(conn)
    return templates.TemplateResponse(
        request, "config.html", {"cfg": cfg, "raw_yaml": None, "ai_on": ai_on},
    )


@app.post("/config/update", response_class=HTMLResponse)
def config_update(request: Request, raw_yaml: str = Form(...)):
    from app.schemas import ConfigModel

    with db.get_conn() as conn:
        ai_on = db.ai_enabled(conn)

    error = None
    try:
        parsed = yaml.safe_load(raw_yaml)
        ConfigModel(**parsed)  # pydantic validation before writing back
        save_config(parsed)
        cfg = load_config(force_reload=True)
    except Exception as e:  # noqa: BLE001 — surface the validation error in the form
        error = str(e)
        cfg = load_config(force_reload=True)

    return templates.TemplateResponse(
        request,
        "config.html",
        {"cfg": cfg, "raw_yaml": raw_yaml if error else None,
         "error": error, "ai_on": ai_on},
    )


# -------------------------------------------------------------------------------
# AI toggle + debug
# -------------------------------------------------------------------------------

@app.post("/settings/ai-toggle")
def ai_toggle(request: Request, enabled: str = Form(...)):
    with db.get_conn() as conn:
        db.set_setting(conn, "ai_enabled", "true" if enabled == "true" else "false")
    referer = request.headers.get("referer", "/")
    return RedirectResponse(referer, status_code=303)


@app.get("/api/debug")
def api_debug():
    with db.get_conn() as conn:
        rows = db.list_inquiries_with_assessments(conn)
        skipped = db.list_skipped(conn)
    out = []
    for r in rows:
        a = r["assessment"]
        out.append({
            "inquiry_id": r["inquiry"]["id"],
            "creator_id": r["inquiry"]["creator_id"],
            "brand": r["extraction"].brand if r["extraction"] else None,
            "type": a.type,
            "flags": a.flags,
            "final_score": a.final_score,
            "priority": a.priority,
            "recommended_action": a.recommended_action,
            "rate_fit_pct": a.rate_fit_pct,
            "counter_offer_amount": a.counter_offer_amount,
            "quote_total": a.quote.total if a.quote else None,
        })
    return {"inquiries": out, "skipped_count": len(skipped)}
