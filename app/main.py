"""FastAPI app. Thin routes — everything that matters lives in pipeline.py / score.py
/ quote.py, and everything a screen shows is derived in view.py; this file wires HTTP
to those and renders Jinja2 templates.
"""
from __future__ import annotations

import base64
import csv
import datetime as dt
import io
from pathlib import Path
from urllib.parse import quote

import yaml
from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import ai, db, extract, fmt, pipeline, view
from app.config_loader import load_config, reference_date, save_config
from app.creator_form import new_creator_id, parse_creator_form, parse_number, values_from_creator, values_from_form
from app.reply import ai_reply, draft_for_page
from app.score import assess

BASE_DIR = Path(__file__).resolve().parent
app = FastAPI(title="Deal Desk — Brand Deal Inbox Triage (SAMPLE DATA)")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

templates.env.filters.update(
    inr=fmt.inr,
    num_in=lambda n: fmt.group_in(n) if n is not None else "",
    num_plain=lambda n: f"{n:g}" if isinstance(n, (int, float)) else n,
    pct_num=lambda x: f"{x * 100:g}" if x is not None else "",
    date_long=fmt.date_long,
    date_short=fmt.date_short,
    datetime_long=fmt.datetime_long,
)
templates.env.globals.update(
    type_labels=view.TYPES, type_class=view.TYPE_CLASS, flag_meta=view.FLAGS,
    flag_tiers=view.FLAG_TIERS, priorities=view.PRIORITIES,
    deliverable_labels=view.DELIVERABLE_LABELS,
)


def _ensure_db() -> None:
    """A fresh database (first boot, or a free host waking on an empty disk) is seeded
    and scanned, so the queue is never empty when someone opens the app."""
    with db.get_conn() as conn:
        db.init_schema(conn)
        if not db.creators_loaded(conn):
            for c in db.load_creators_from_csv():
                db.save_creator(conn, c)
        if not db.get_setting(conn, "last_scan"):
            # Rules only: the host waits on startup before routing traffic, and an AI
            # scan can take its full time budget.
            pipeline.run_scan(conn, ai_on_override=False)


@app.on_event("startup")
def on_startup():
    _ensure_db()


def _render(request: Request, name: str, ctx: dict, conn=None) -> HTMLResponse:
    ctx.setdefault("ai_status", ai.status())
    if "ai_on" not in ctx:
        if conn is None:
            with db.get_conn() as c:
                ctx["ai_on"] = db.ai_enabled(c)
        else:
            ctx["ai_on"] = db.ai_enabled(conn)
    return templates.TemplateResponse(request, name, ctx)


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _priority_rank(p: str) -> int:
    return {"P1": 0, "P2": 1, "P3": 2, "Ignore": 3}.get(p, 4)


def _sorted_rows(rows):
    return sorted(rows, key=lambda r: (_priority_rank(r["assessment"].priority), -r["assessment"].final_score))


# -------------------------------------------------------------------------------
# Triage queue
# -------------------------------------------------------------------------------

def _filter_queue(rows, creator, type_, flag, priority):
    out = []
    for r in rows:
        a = r["assessment"]
        if creator and r["inquiry"]["creator_id"] != creator:
            continue
        if type_ and a.type != type_:
            continue
        if flag == "none" and a.flags:
            continue
        if flag and flag != "none" and flag not in a.flags:
            continue
        if priority and a.priority != priority:
            continue
        out.append(r)
    return out


def _queue_context(conn, creator: str, type_: str, flag: str, priority: str) -> dict:
    creators = db.list_creators(conn)
    by_id = {c.id: c for c in creators}
    rows = db.list_inquiries_with_assessments(conn)
    filtered = _sorted_rows(_filter_queue(rows, creator, type_, flag, priority))
    for r in filtered:
        c = by_id[r["inquiry"]["creator_id"]]
        r["flags"] = view.flag_list(r["assessment"].flags)
        r["bvq"] = view.bvq(c, r["extraction"], r["assessment"])

    active = []
    if creator in by_id:
        active.append(f"Creator: {by_id[creator].name}")
    if type_:
        active.append(f"Type: {view.TYPES.get(type_, type_)}")
    if flag:
        active.append("Flag: No flags" if flag == "none" else f"Flag: {view.FLAGS.get(flag, (flag,))[0]}")
    if priority:
        active.append(f"Priority: {priority}")

    return {
        "rows": filtered, "creators": creators, "has_data": bool(rows), "total": len(rows),
        "creator_count": len({r["inquiry"]["creator_id"] for r in rows}),
        "skipped_count": len(db.list_skipped(conn)), "last_scan": db.get_setting(conn, "last_scan"),
        "last_scan_note": db.get_setting(conn, "last_scan_note"),
        "filters": {"creator": creator, "type": type_, "flag": flag, "priority": priority},
        "active_filters": active, "filter_creator": by_id.get(creator),
        "filter_creator_count": sum(r["inquiry"]["creator_id"] == creator for r in rows),
        "reference_date": reference_date(), "active": "queue",
    }


@app.get("/", response_class=HTMLResponse)
def queue_page(request: Request, creator: str = "", type: str = "", flag: str = "", priority: str = ""):
    with db.get_conn() as conn:
        return _render(request, "queue.html", _queue_context(conn, creator, type, flag, priority), conn)


@app.get("/partials/queue-list", response_class=HTMLResponse)
def queue_list_partial(request: Request, creator: str = "", type: str = "", flag: str = "", priority: str = ""):
    with db.get_conn() as conn:
        return _render(request, "partials/queue_list.html", _queue_context(conn, creator, type, flag, priority), conn)


@app.post("/scan", response_class=HTMLResponse)
def scan_inboxes(request: Request):
    with db.get_conn() as conn:
        pipeline.run_scan(conn)
    return RedirectResponse("/", status_code=303)


@app.get("/skipped", response_class=HTMLResponse)
def skipped_page(request: Request):
    with db.get_conn() as conn:
        ctx = {
            "rows": db.list_skipped(conn),
            "creator_names": {c.id: c.name for c in db.list_creators(conn)},
            "scanned": bool(db.get_setting(conn, "last_scan")), "active": "queue",
        }
        return _render(request, "skipped.html", ctx, conn)


# -------------------------------------------------------------------------------
# Inquiry detail
# -------------------------------------------------------------------------------

def _inquiry_context(conn, inquiry_id: str, *, prev_assessment=None, prev_uncapped=None,
                     edited_field: str | None = None, edit_error: str | None = None,
                     ai_reply_error: str | None = None) -> dict:
    inquiry = db.get_inquiry(conn, inquiry_id)
    if inquiry is None:
        raise HTTPException(status_code=404, detail="Inquiry not found")
    creator = db.get_creator(conn, inquiry["creator_id"])
    ext = db.get_extraction(conn, inquiry_id)
    a = db.get_assessment(conn, inquiry_id)
    ai_on = db.ai_enabled(conn)
    ref = reference_date()
    raw, domain = inquiry["raw_text"], inquiry["sender_domain"]

    flags = view.flag_list(a.flags)
    for f in flags:
        f["why"] = view.flag_reason(f["key"], creator, ext, a, ref, raw, domain)

    uncapped = None
    if "conflict" in a.flags and "no_go" not in a.flags:
        uncapped = view.uncapped_score(creator, ext, ref, raw, domain, "duplicate" in a.flags)

    cleared, cleared_why = [], ""
    stamp = ""
    if prev_assessment is not None and not edit_error:
        cleared = view.flag_list([f for f in prev_assessment.flags if f not in a.flags])
        if any(f["key"] == "lowball" for f in cleared) and a.rate_fit_pct is not None:
            cleared_why = f"{fmt.inr(a.offer_value)} is {a.rate_fit_pct:.0f}% of the quote."
        moved = int(prev_assessment.final_score) != int(a.final_score)
        change = (f"score {int(prev_assessment.final_score)} → {int(a.final_score)}" if moved
                  else ("score unchanged, still capped" if uncapped else "score unchanged"))
        stamp = f"Re-scored after you edited {view.field_label(edited_field)} · {change}"
    elif db.get_setting(conn, "last_scan"):
        stamp = f"Scored {fmt.datetime_long(db.get_setting(conn, 'last_scan'))}"

    order = [r["inquiry"]["id"] for r in _sorted_rows(db.list_inquiries_with_assessments(conn))]
    pos = order.index(inquiry_id) if inquiry_id in order else None
    nav = {
        "position": pos + 1 if pos is not None else None, "total": len(order),
        "prev_id": order[pos - 1] if pos else None,
        "next_id": order[pos + 1] if pos is not None and pos + 1 < len(order) else None,
    }
    reply_draft, reply_source = draft_for_page(creator, ext, a, ai_on)

    return {
        "inquiry": inquiry, "creator": creator, "extraction": ext, "assessment": a,
        "fields": view.field_rows(ext), "flags": flags, "bvq": view.bvq(creator, ext, a),
        "quote_rows": view.quote_rows(creator, ext, a), "uncapped": uncapped,
        "prev_uncapped": prev_uncapped, "cleared": cleared, "cleared_why": cleared_why,
        "rec": view.recommendation(creator, a), "stamp": stamp, "edit_error": edit_error,
        "reply_draft": reply_draft, "reply_source": reply_source,
        "decision": view.decision_view(db.get_decision_for_inquiry(conn, inquiry_id), creator),
        "nav": nav, "ai_on": ai_on, "active": "queue",
        "ai_reply_error": ai_reply_error,
    }


@app.get("/inquiry/{inquiry_id}", response_class=HTMLResponse)
def inquiry_detail(request: Request, inquiry_id: str):
    with db.get_conn() as conn:
        return _render(request, "inquiry_detail.html", _inquiry_context(conn, inquiry_id), conn)


@app.post("/inquiry/{inquiry_id}/edit", response_class=HTMLResponse)
def edit_field(request: Request, inquiry_id: str, field: str = Form(...), value: str = Form("")):
    with db.get_conn() as conn:
        inquiry = db.get_inquiry(conn, inquiry_id)
        if inquiry is None:
            raise HTTPException(status_code=404, detail="Inquiry not found")
        prev = db.get_assessment(conn, inquiry_id)
        prev_uncapped = None
        if prev and "conflict" in prev.flags:
            prev_uncapped = int(view.uncapped_score(
                db.get_creator(conn, inquiry["creator_id"]), db.get_extraction(conn, inquiry_id),
                reference_date(), inquiry["raw_text"], inquiry["sender_domain"], "duplicate" in prev.flags,
            ).final_score)
        error = None
        try:
            pipeline.reassess_inquiry(conn, inquiry_id, field, value)
        except ValueError as e:
            error = f"Couldn't save {view.field_label(field)}: {e}"

        if not _is_htmx(request):
            return RedirectResponse(f"/inquiry/{inquiry_id}", status_code=303)

        ctx = _inquiry_context(conn, inquiry_id, prev_assessment=prev, prev_uncapped=prev_uncapped,
                               edited_field=field, edit_error=error)
        row = next((f for f in ctx["fields"] if f["name"] == field), None)
        if row is not None and error:
            row["value"] = value
        ctx.update(oob_field=row, oob_error=error)
        # 200 even on a bad value: HTMX only swaps successful responses, and the
        # manager needs to see why the edit didn't take.
        return _render(request, "partials/edit_response.html", ctx, conn)


@app.post("/inquiry/{inquiry_id}/reextract", response_class=HTMLResponse)
def reextract(request: Request, inquiry_id: str):
    with db.get_conn() as conn:
        if db.get_inquiry(conn, inquiry_id) is None:
            raise HTTPException(status_code=404, detail="Inquiry not found")
        pipeline.reextract_inquiry(conn, inquiry_id, ai_on_override=False)
        if not _is_htmx(request):
            return RedirectResponse(f"/inquiry/{inquiry_id}", status_code=303)
        ctx = _inquiry_context(conn, inquiry_id)
        ctx["stamp"] = "Re-extracted with rules only · your edits were discarded"
        ctx["refresh_fields"] = True
        return _render(request, "partials/edit_response.html", ctx, conn)


@app.post("/inquiry/{inquiry_id}/ai-reply", response_class=HTMLResponse)
def write_ai_reply(request: Request, inquiry_id: str):
    """The one place a reply waits on a model — on request, never on page load or edit.
    The answer is cached for these exact terms, so the re-render below picks it up."""
    with db.get_conn() as conn:
        inquiry = db.get_inquiry(conn, inquiry_id)
        if inquiry is None:
            raise HTTPException(status_code=404, detail="Inquiry not found")
        creator, ext = db.get_creator(conn, inquiry["creator_id"]), db.get_extraction(conn, inquiry_id)
        a = db.get_assessment(conn, inquiry_id)
        if ext is None or a is None:
            raise HTTPException(status_code=404, detail="Inquiry not scored yet")
        ai_on = db.ai_enabled(conn)
    error = None
    if not ai_on:
        error = "AI is off — turn it on in the header to write the reply with AI."
    elif ai_reply(creator, ext, a) is None:
        error = ai.status()["note"] or "The free AI models didn't answer in time. The template draft is kept — try again in a minute."
    if not _is_htmx(request):
        return RedirectResponse(f"/inquiry/{inquiry_id}", status_code=303)
    with db.get_conn() as conn:
        ctx = _inquiry_context(conn, inquiry_id, ai_reply_error=error)
        return _render(request, "partials/assessment.html", ctx, conn)


@app.post("/inquiry/{inquiry_id}/decision", response_class=HTMLResponse)
def make_decision(request: Request, inquiry_id: str, action: str = Form(...),
                  reply_text: str = Form(""), draft: str = Form("")):
    with db.get_conn() as conn:
        inquiry = db.get_inquiry(conn, inquiry_id)
        if inquiry is None:
            raise HTTPException(status_code=404, detail="Inquiry not found")
        edited = action != "mark_spam" and reply_text.strip() != draft.strip()
        db.save_decision(conn, inquiry_id, action, reply_text if edited else "")
        if not _is_htmx(request):
            return RedirectResponse(f"/inquiry/{inquiry_id}", status_code=303)
        creator = db.get_creator(conn, inquiry["creator_id"])
        decision = view.decision_view(db.get_decision_for_inquiry(conn, inquiry_id), creator)
        return _render(request, "partials/decision_result.html", {"decision": decision}, conn)


# -------------------------------------------------------------------------------
# Creators
# -------------------------------------------------------------------------------

@app.get("/creators", response_class=HTMLResponse)
def creators_page(request: Request, deleted: str = ""):
    with db.get_conn() as conn:
        rows = db.list_inquiries_with_assessments(conn)
        ref = reference_date()
        out = []
        for c in db.list_creators(conn):
            partners = [view.partner_view(p, ref) for p in c.active_partners]
            out.append({
                "creator": c, "capacity": view.capacity_view(c),
                "active_exclusives": [p for p in partners if p["state"] == "active"],
                "count": sum(r["inquiry"]["creator_id"] == c.id for r in rows),
            })
        return _render(request, "creators.html", {"rows": out, "active": "creators", "deleted": deleted}, conn)


@app.get("/creators/export.csv")
def export_roster():
    """The live roster in roster_seed.csv format — the way to keep creators added or
    edited here, since a free host's disk resets on every restart."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=db.CSV_FIELDNAMES, lineterminator="\n")
    writer.writeheader()
    with db.get_conn() as conn:
        for c in db.list_creators(conn):
            writer.writerow(db.creator_to_csv_row(c))
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="roster_seed.csv"'})


def _creator_form_context(conn, *, creator=None, values=None, error=None) -> dict:
    return {
        "creator": creator, "v": values or values_from_creator(creator), "error": error,
        "categories": extract.category_vocabulary(),
        "global_no_go": load_config()["global_no_go_categories"], "active": "creators",
    }


def _handle_taken(conn, handle: str, creator_id: str) -> str | None:
    wanted = handle.strip().lstrip("@").lower()
    for c in db.list_creators(conn):
        if c.id != creator_id and c.ig_handle.lstrip("@").lower() == wanted:
            return c.name
    return None


def _save_creator_form(request: Request, conn, values: dict, creator_id: str, existing):
    """Shared by Add and Edit: parse, refuse a handle another creator already has, save,
    re-score. Returns the error page on a bad form, None once saved."""
    try:
        creator = parse_creator_form(values, creator_id)
        owner = _handle_taken(conn, creator.ig_handle, creator_id)
        if owner:
            raise ValueError(f"{creator.ig_handle} is already on the roster as {owner}.")
    except ValueError as e:
        return _render(request, "creator_form.html",
                       _creator_form_context(conn, creator=existing, values=values, error=str(e)), conn)
    db.save_creator(conn, creator)
    return None


@app.get("/creators/new", response_class=HTMLResponse)
def new_creator_page(request: Request):
    with db.get_conn() as conn:
        return _render(request, "creator_form.html", _creator_form_context(conn), conn)


@app.post("/creators/new")
async def create_creator(request: Request):
    values = values_from_form(await request.form())
    with db.get_conn() as conn:
        creator_id = new_creator_id(values["name"], {c.id for c in db.list_creators(conn)})
        error_page = _save_creator_form(request, conn, values, creator_id, None)
        if error_page:
            return error_page
    return RedirectResponse(f"/creator/{creator_id}?added=1", status_code=303)


@app.get("/creator/{creator_id}/edit", response_class=HTMLResponse)
def edit_creator_page(request: Request, creator_id: str):
    with db.get_conn() as conn:
        creator = db.get_creator(conn, creator_id)
        if creator is None:
            raise HTTPException(status_code=404, detail="Creator not found")
        return _render(request, "creator_form.html", _creator_form_context(conn, creator=creator), conn)


@app.post("/creator/{creator_id}/edit")
async def edit_creator(request: Request, creator_id: str):
    values = values_from_form(await request.form())
    with db.get_conn() as conn:
        existing = db.get_creator(conn, creator_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Creator not found")
        error_page = _save_creator_form(request, conn, values, creator_id, existing)
        if error_page:
            return error_page
        count = pipeline.rescore_inquiries(conn, creator_id)
    return RedirectResponse(f"/creator/{creator_id}?saved=1&rescored={count}", status_code=303)


@app.post("/creator/{creator_id}/delete")
def delete_creator(request: Request, creator_id: str, confirm: str = Form("")):
    with db.get_conn() as conn:
        creator = db.get_creator(conn, creator_id)
        if creator is None:
            raise HTTPException(status_code=404, detail="Creator not found")
        if confirm != "yes":
            ctx = _creator_form_context(conn, creator=creator,
                                        error=f"Tick the box to confirm removing {creator.name}.")
            return _render(request, "creator_form.html", ctx, conn)
        db.delete_creator(conn, creator_id)
    return RedirectResponse(f"/creators?deleted={quote(creator.name)}", status_code=303)


def _creator_context(conn, creator_id: str, **extra) -> dict:
    creator = db.get_creator(conn, creator_id)
    if creator is None:
        raise HTTPException(status_code=404, detail="Creator not found")
    ref = reference_date()
    history, dms = [], []
    for r in db.list_inquiries_with_assessments(conn):
        inq = r["inquiry"]
        if inq["creator_id"] != creator_id:
            continue
        d = db.get_decision_for_inquiry(conn, inq["id"])
        outcome = view.OUTCOMES.get(d["action"], ("Logged", "open")) if d else ("In queue", "open")
        row = {
            "id": inq["id"], "received": inq["received_at"],
            "brand": r["extraction"].brand or inq["sender_domain"],
            "score": int(r["assessment"].final_score), "priority": r["assessment"].priority,
            "offer": r["assessment"].offer_value, "outcome": outcome,
        }
        history.append(row)
        if inq["source"] == "dm":
            dms.append({**row, "brand": r["extraction"].brand or "Brand not identified",
                        "sender": inq["sender_email_or_handle"] or inq["sender_name"],
                        "pasted": inq["id"].startswith(db.MANUAL_DM_PREFIX)})
    history.sort(key=lambda h: h["received"], reverse=True)
    dms.sort(key=lambda h: h["received"], reverse=True)
    cfg = load_config()
    return {
        "creator": creator, "initials": view.initials(creator.name),
        "partners": [view.partner_view(p, ref) for p in creator.active_partners],
        "capacity": view.capacity_view(creator), "history": history, "dms": dms,
        "month_label": f"{ref:%B %Y}", "bundle_min": cfg["bundle_discount_min_deliverables"],
        "global_no_go": cfg["global_no_go_categories"], "active": "creators", **extra,
    }


@app.get("/creator/{creator_id}", response_class=HTMLResponse)
def creator_page(request: Request, creator_id: str, saved: int = 0, rescored: int = 0, added: int = 0):
    with db.get_conn() as conn:
        return _render(request, "creator.html",
                       _creator_context(conn, creator_id, saved=saved, rescored=rescored, added=added), conn)


@app.post("/creator/{creator_id}/update")
async def update_creator(request: Request, creator_id: str):
    form = await request.form()
    with db.get_conn() as conn:
        creator = db.get_creator(conn, creator_id)
        if creator is None:
            raise HTTPException(status_code=404, detail="Creator not found")
        try:
            rates = {k: parse_number(form.get(k), label) for k, label in
                     [("reel", "Reel"), ("story", "Story"), ("static_post", "Static post"), ("carousel", "Carousel"),
                      ("youtube_integration", "YouTube integration")]}
            bundle = parse_number(form.get("bundle_discount_pct"), "Bundle discount", pct=True)
            minimum = parse_number(form.get("min_acceptable_pct"), "Minimum acceptable", pct=True)
            barter_min = parse_number(form.get("barter_min_product_value"), "Barter minimum")
            usage_default = parse_number(form.get("usage_rights_default_days"), "Usage rights default", integer=True)
            usage_free = parse_number(form.get("max_usage_days_without_extra_fee"), "Max usage", integer=True)
            capacity = parse_number(form.get("max_paid_deals_per_month"), "Monthly capacity", integer=True)
            if bundle is not None and bundle >= 1 or minimum is not None and minimum > 1:
                raise ValueError("Percentages must be between 0 and 100.")
        except ValueError as e:
            return _render(request, "creator.html", _creator_context(conn, creator_id, error=str(e)), conn)

        for k, v in rates.items():
            if v is not None:
                setattr(creator.rate_card, k, v)
        if bundle is not None:
            creator.rate_card.bundle_discount_pct = bundle
        if minimum is not None:
            creator.min_acceptable_pct = minimum
        if "accepts_barter" in form:
            creator.accepts_barter = str(form.get("accepts_barter")).lower() in ("yes", "true", "on", "1")
        if barter_min is not None:
            creator.barter_min_product_value = barter_min
        if usage_default is not None:
            creator.usage_rights_default_days = usage_default
        if usage_free is not None:
            creator.max_usage_days_without_extra_fee = usage_free
        if capacity is not None:
            creator.max_paid_deals_per_month = capacity
        db.save_creator(conn, creator)
        count = pipeline.rescore_inquiries(conn, creator_id)
    return RedirectResponse(f"/creator/{creator_id}?saved=1&rescored={count}", status_code=303)


@app.post("/creator/{creator_id}/nogo")
def update_nogo(creator_id: str, add: str = Form(""), remove: str = Form("")):
    with db.get_conn() as conn:
        creator = db.get_creator(conn, creator_id)
        if creator is None:
            raise HTTPException(status_code=404, detail="Creator not found")
        cats = [c for c in creator.no_go_categories if c != remove.strip().lower()]
        new = add.strip().lower()
        if new and new not in cats:
            cats.append(new)
        creator.no_go_categories = cats
        db.save_creator(conn, creator)
        count = pipeline.rescore_inquiries(conn, creator_id)
    return RedirectResponse(f"/creator/{creator_id}?saved=1&rescored={count}", status_code=303)


# -------------------------------------------------------------------------------
# DM intake — paste/screenshot -> preview -> add to queue
# -------------------------------------------------------------------------------

DM_PREVIEW_FIELDS = ["brand", "brand_category", "budget_amount", "product_value", "deliverables",
                     "go_live_date", "usage_rights_days", "payment_advance_pct", "payment_net_days"]


def _dm_context(conn, *, form=None, preview=None, error=None) -> dict:
    creators = db.list_creators(conn)
    form = form or {"creator_id": "", "sender": "", "dm_text": ""}
    return {
        "creators": creators, "preview": preview, "error": error, "form": form, "active": "dm",
        "for_creator": next((c for c in creators if c.id == form["creator_id"]), None),
    }


def _dm_preview(conn, creator_id: str, text: str, ext, *, from_screenshot=False, values=None, errors=None):
    creator = db.get_creator(conn, creator_id)
    a = assess(creator, ext, reference_date(), raw_text=text, sender_domain=pipeline.DM_DOMAIN)
    fields = [f for f in view.field_rows(ext) if f["name"] in DM_PREVIEW_FIELDS]
    for f in fields:
        f["original"] = f["value"]
        if values and f["name"] in values:
            f["value"] = values[f["name"]]
    return {"fields": fields, "flags": view.flag_list(a.flags), "text": text,
            "from_screenshot": from_screenshot, "errors": errors or {}}


@app.get("/dm", response_class=HTMLResponse)
def dm_intake_page(request: Request, creator: str = ""):
    with db.get_conn() as conn:
        form = {"creator_id": creator, "sender": "", "dm_text": ""}
        return _render(request, "dm_intake.html", _dm_context(conn, form=form), conn)


@app.post("/dm/process", response_class=HTMLResponse)
async def dm_process(request: Request, creator_id: str = Form(...), dm_text: str = Form(""),
                     sender: str = Form(""), screenshot: UploadFile | None = None):
    with db.get_conn() as conn:
        if db.get_creator(conn, creator_id) is None:
            raise HTTPException(status_code=404, detail="Creator not found")
        ai_on = db.ai_enabled(conn)
        form = {"creator_id": creator_id, "sender": sender, "dm_text": dm_text}
        text, from_screenshot = dm_text.strip(), False
        if not text and screenshot is not None and screenshot.filename and ai_on:
            content = await screenshot.read()
            if len(content) > 5 * 1024 * 1024:
                return _render(request, "dm_intake.html", _dm_context(
                    conn, form=form, error="That screenshot is over 5 MB — crop it or paste the text instead."), conn)
            mime = screenshot.content_type if screenshot.content_type in ("image/png", "image/jpeg", "image/webp") else "image/png"
            text = (ai.ocr_screenshot_ai(base64.b64encode(content).decode(), mime) or "").strip()
            from_screenshot = True
            if not text:
                reason = ai.status()["note"] or "The free vision models couldn't read it in time."
                return _render(request, "dm_intake.html", _dm_context(
                    conn, form=form, error=f"Couldn't read that screenshot. {reason} Paste the text instead."), conn)
        if not text:
            return _render(request, "dm_intake.html", _dm_context(
                conn, form=form, error="Paste the DM text first."), conn)
        ext = pipeline.extract_dm(text, ai_on)
        preview = _dm_preview(conn, creator_id, text, ext, from_screenshot=from_screenshot)
        return _render(request, "dm_intake.html", _dm_context(conn, form=form, preview=preview), conn)


@app.post("/dm/commit")
async def dm_commit(request: Request):
    form = await request.form()
    creator_id, sender, text = form.get("creator_id", ""), form.get("sender", ""), form.get("dm_text", "")
    with db.get_conn() as conn:
        if db.get_creator(conn, creator_id) is None:
            raise HTTPException(status_code=404, detail="Creator not found")
        if not text.strip():
            return RedirectResponse("/dm", status_code=303)
        ext = pipeline.extract_dm(text, db.ai_enabled(conn))
        values, errors = {}, {}
        for name in DM_PREVIEW_FIELDS:
            submitted = str(form.get(f"f_{name}", ""))
            values[name] = submitted
            try:
                setattr(ext, name, pipeline.parse_field(name, submitted))
            except ValueError as e:
                errors[name] = str(e)
                continue
            if submitted.strip() != str(form.get(f"o_{name}", "")).strip():
                ext.provenance[name] = "manual"
        if errors:
            preview = _dm_preview(conn, creator_id, text, pipeline.extract_dm(text, db.ai_enabled(conn)),
                                  values=values, errors=errors)
            ctx = _dm_context(conn, form={"creator_id": creator_id, "sender": sender, "dm_text": text},
                              preview=preview, error="Fix the highlighted fields, then add it again.")
            return _render(request, "dm_intake.html", ctx, conn)
        inquiry_id = pipeline.add_dm_inquiry(conn, creator_id, text, sender.strip(), ext)
    return RedirectResponse(f"/inquiry/{inquiry_id}", status_code=303)


# -------------------------------------------------------------------------------
# Pipeline summary
# -------------------------------------------------------------------------------

@app.get("/pipeline", response_class=HTMLResponse)
def pipeline_summary(request: Request):
    with db.get_conn() as conn:
        rows = db.list_inquiries_with_assessments(conn)
        creators = db.list_creators(conn)
        by_id = {c.id: c for c in creators}
        inquiries = {r["inquiry"]["id"]: r for r in rows}

        counts = {p: 0 for p in view.PRIORITIES}
        value_p1 = value_p2 = 0.0
        conflicts = []
        for r in sorted(rows, key=lambda r: r["inquiry"]["received_at"], reverse=True):
            a = r["assessment"]
            counts[a.priority] = counts.get(a.priority, 0) + 1
            if a.priority == "P1" and a.offer_value:
                value_p1 += a.offer_value
            if a.priority == "P2" and a.offer_value:
                value_p2 += a.offer_value
            if "conflict" in a.flags:
                conflicts.append(f"{r['extraction'].brand} → {r['inquiry']['creator_name']}")

        per = {c.id: 0 for c in creators}
        for r in rows:
            per[r["inquiry"]["creator_id"]] = per.get(r["inquiry"]["creator_id"], 0) + 1
        top = max(per.values(), default=0) or 1
        per_creator = sorted(
            ({"creator": by_id[cid], "count": n, "fill": int(round(n / top * 20)) * 5} for cid, n in per.items()),
            key=lambda d: -d["count"],
        )

        decisions = []
        for d in db.list_decisions(conn):
            r = inquiries.get(d["inquiry_id"])
            decisions.append({
                "timestamp": d["timestamp"], "inquiry_id": d["inquiry_id"], "exists": r is not None,
                "creator": r["inquiry"]["creator_name"] if r else "—",
                "brand": (r["extraction"].brand or r["inquiry"]["sender_domain"]) if r else f"{d['inquiry_id']} (cleared by rescan)",
                "outcome": view.OUTCOMES.get(d["action"], (d["action"], "open")),
                "edited": None if d["action"] == "mark_spam" else bool(d["edited_reply"]),
            })

        ctx = {
            "counts": counts, "value_p1": value_p1, "value_p2": value_p2, "conflicts": conflicts,
            "per_creator": per_creator, "creators": creators, "total": len(rows),
            "skipped_count": len(db.list_skipped(conn)), "decisions": decisions,
            "last_scan": db.get_setting(conn, "last_scan"), "active": "pipeline",
        }
        return _render(request, "pipeline.html", ctx, conn)


# -------------------------------------------------------------------------------
# Config
# -------------------------------------------------------------------------------

def _config_context(conn, *, cfg=None, raw_yaml=None, error=None, saved=False, rescored=0) -> dict:
    cfg = cfg or load_config(force_reload=True)
    return {
        "cfg": cfg, "cfg_yaml": yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True),
        "raw_yaml": raw_yaml, "error": error, "saved": saved, "rescored": rescored,
        "inquiry_count": len(db.list_inquiries(conn)), "active": "config",
    }


def _lines(text: str) -> list[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def _config_from_form(form) -> dict:
    cfg = load_config(force_reload=True)
    cfg = yaml.safe_load(yaml.safe_dump(cfg))  # a deep copy we can mutate
    num = lambda key, label, **kw: parse_number(form.get(key), label, **kw)  # noqa: E731

    ref = (form.get("reference_date") or "").strip()
    if ref:
        dt.date.fromisoformat(ref)
    cfg["reference_date"] = ref

    for key in cfg["scoring_weights"]:
        v = num(f"w_{key}", f"Weight {key.replace('_', ' ')}")
        if v is not None:
            cfg["scoring_weights"][key] = v
    if abs(sum(cfg["scoring_weights"].values()) - 100) > 1e-9:
        raise ValueError(f"Scoring weights must total 100 (they total {sum(cfg['scoring_weights'].values()):g}).")
    for key in cfg["risk_penalty"]:
        v = num(f"pen_{key}", f"Penalty {key.replace('_', ' ')}")
        if v is not None:
            cfg["risk_penalty"][key] = v
    for key in cfg["priority_bands"]:
        v = num(f"band_{key}", f"Priority band {key}")
        if v is not None:
            cfg["priority_bands"][key] = v
    b = cfg["priority_bands"]
    if not b["p1_min"] > b["p2_min"] > b["p3_min"]:
        raise ValueError("Priority bands must go down: P1 > P2 > P3.")
    for key, label in [("urgency_days_high", "Urgent window"), ("urgency_days_medium", "Urgency window"),
                       ("duplicate_window_days", "Duplicate window")]:
        v = num(key, label, integer=True)
        if v is not None:
            cfg[key] = v
    for key, label in [("min_acceptable_pct_default", "Default minimum acceptable"),
                       ("usage_fee_pct_per_30_days", "Usage fee"), ("whitelisting_fee_pct", "Whitelisting fee"),
                       ("exclusivity_fee_pct", "Exclusivity fee")]:
        v = num(key, label, pct=True)
        if v is not None:
            cfg[key] = v

    if "keywords" in form:
        cfg["keywords"] = [k.lower() for k in _lines(form.get("keywords"))]
        if not cfg["keywords"]:
            raise ValueError("Keep at least one brand keyword, or every message is skipped.")
    if "global_no_go_categories" in form:
        cfg["global_no_go_categories"] = [k.lower() for k in _lines(form.get("global_no_go_categories"))]
    for key in ("pay_to_join_phrases", "crypto_forex_terms", "shortened_link_domains", "free_mail_domains"):
        if f"spam_{key}" in form:
            cfg["spam_patterns"][key] = _lines(form.get(f"spam_{key}"))

    brands, cats = form.getlist("lk_brand"), form.getlist("lk_cat")
    if brands:
        remove = form.get("remove")
        lookup = {}
        for i, (brand, cat) in enumerate(zip(brands, cats)):
            if remove is not None and str(i) == remove:
                continue
            if brand.strip() and cat.strip():
                lookup[brand.strip().lower()] = cat.strip().lower()
        cfg["brand_category_lookup"] = lookup
    return cfg


@app.get("/config", response_class=HTMLResponse)
def config_page(request: Request, saved: int = 0, rescored: int = 0):
    with db.get_conn() as conn:
        return _render(request, "config.html", _config_context(conn, saved=bool(saved), rescored=rescored), conn)


@app.post("/config/update", response_class=HTMLResponse)
async def config_update(request: Request):
    from app.schemas import ConfigModel

    form = await request.form()
    raw_yaml = form.get("raw_yaml")
    with db.get_conn() as conn:
        try:
            parsed = yaml.safe_load(raw_yaml) if raw_yaml is not None else _config_from_form(form)
            if not isinstance(parsed, dict):
                raise ValueError("The config must be a YAML mapping of keys to values.")
            ConfigModel(**parsed)  # pydantic validation before writing back
        except Exception as e:  # noqa: BLE001 — surface the validation error in the form
            return _render(request, "config.html", _config_context(conn, raw_yaml=raw_yaml, error=str(e)), conn)
        save_config(parsed)
        count = pipeline.rescore_inquiries(conn)
    return RedirectResponse(f"/config?saved=1&rescored={count}", status_code=303)


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
            "ai_fields": sorted(f for f, p in (r["extraction"].provenance if r["extraction"] else {}).items() if p == "ai"),
        })
    return {"inquiries": out, "skipped_count": len(skipped)}
