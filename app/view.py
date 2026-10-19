"""Presentation layer: turns engine output into what the screens show — flag tiers and
their one-line reasons, the budget-vs-quote bar, the quote argument, the uncapped
score behind a conflict cap. Nothing here changes a score, a flag or an action; it
only explains them, reading the same config.yaml and helpers score.py uses.
"""
from __future__ import annotations

import copy
import datetime as dt

from app.config_loader import load_config
from app.fmt import date_long, date_short, datetime_long, inr
from app.models import Assessment, Creator, Extraction
from app.score import _blackout_hit, _conflict_partner, assess
from app.spam import detect_spam

FLAGS = {
    "conflict": ("Conflict", "stop"),
    "no_go": ("No-go", "stop"),
    "risky_payment_terms": ("Risky payment terms", "risk"),
    "usage_overreach": ("Usage overreach", "risk"),
    "suspicious_sender": ("Suspicious sender", "risk"),
    "lowball": ("Lowball", "notice"),
    "missing_info": ("Missing info", "notice"),
    "duplicate": ("Duplicate", "notice"),
    "urgent": ("Urgent", "notice"),
    "capacity_full": ("Capacity full", "notice"),
    "blackout_clash": ("Blackout clash", "notice"),
}
FLAG_TIERS = [("stop", "Hard stops"), ("risk", "Risks"), ("notice", "Notices")]
_TIER_RANK = {tier: i for i, (tier, _) in enumerate(FLAG_TIERS)}
_FLAG_RANK = {key: i for i, key in enumerate(FLAGS)}

TYPES = {"paid": "Paid", "barter": "Barter", "hybrid": "Hybrid", "spam": "Spam", "not_a_deal": "Not a deal"}
TYPE_CLASS = {"paid": "paid", "barter": "barter", "hybrid": "hybrid", "spam": "spam", "not_a_deal": "none"}
PRIORITIES = ["P1", "P2", "P3", "Ignore"]
PRIORITY_BARS = {"P1": 3, "P2": 2, "P3": 1, "Ignore": 0}

DELIVERABLE_LABELS = {
    "reel": "Reel", "story": "Story", "static_post": "Static post",
    "carousel": "Carousel", "youtube_integration": "YouTube integration",
}

# Decision log outcome: (label, outcome css modifier)
OUTCOMES = {
    "accept_and_negotiate": ("Approved", "approved"),
    "counter_offer": ("Countered", "asked"),
    "decline": ("Declined", "declined"),
    "ask_for_info": ("Asked for info", "asked"),
    "mark_spam": ("Marked spam", "spam"),
}


def first_name(creator: Creator) -> str:
    return creator.name.split()[0]


def initials(name: str) -> str:
    return "".join(part[0] for part in name.split()[:2]).upper()


def cap(text: str | None) -> str:
    return text[:1].upper() + text[1:] if text else ""


def deliverables_text(ext: Extraction) -> str:
    return ", ".join(f"{d.count} × {DELIVERABLE_LABELS.get(d.type, d.type)}" for d in ext.deliverables)


# ---------------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------------

def flag_list(flags: list[str]) -> list[dict]:
    """Flags in display order: hard stops, then risks, then notices."""
    out = [{"key": f, "label": FLAGS[f][0], "tier": FLAGS[f][1]} for f in flags if f in FLAGS]
    return sorted(out, key=lambda x: (_TIER_RANK[x["tier"]], _FLAG_RANK[x["key"]]))


def flag_reason(flag: str, creator: Creator, ext: Extraction, a: Assessment,
                ref_date: dt.date, raw_text: str, sender_domain: str) -> str:
    name = first_name(creator)
    cfg = load_config()

    if flag == "conflict":
        p = _conflict_partner(creator, ext.brand_category, ext.go_live_date or ref_date)
        if p is None:
            return "Clashes with an active exclusivity."
        runs = f"which runs to {date_long(p.exclusivity_end_date)}" if p.exclusivity_end_date else "which has no end date"
        when = f"after the {date_short(ext.go_live_date)} go-live" if ext.go_live_date else "and no go-live date is given"
        return f"{cap(ext.brand_category)} clashes with the active {p.brand} exclusivity, {runs} — {when}."

    if flag == "no_go":
        whose = f"{name}'s" if ext.brand_category in creator.no_go_categories else "the agency-wide"
        return f"{cap(ext.brand_category)} is on {whose} no-go list. The score is set to 0."

    if flag == "lowball":
        if a.type == "barter" and not creator.accepts_barter:
            return f"{name} doesn't take barter deals."
        if a.type == "barter" and (ext.product_value or 0) < creator.barter_min_product_value:
            return (f"Product value {inr(ext.product_value)} is under {name}'s "
                    f"{inr(creator.barter_min_product_value)} barter minimum.")
        if a.rate_fit_pct is not None:
            return (f"{a.rate_fit_pct:.0f}% of the quoted price, below {name}'s "
                    f"{creator.min_acceptable_pct * 100:.0f}% minimum.")
        return "Offer is below the creator's minimum."

    if flag == "usage_overreach":
        parts = []
        free = creator.max_usage_days_without_extra_fee
        if ext.usage_rights_days and ext.usage_rights_days > free:
            parts.append(f"{ext.usage_rights_days} days of usage requested against {free} included")
        if ext.whitelisting:
            parts.append("whitelisting (paid ads from the creator's handle) requested")
        return cap("; ".join(parts)) + "." if parts else "Usage terms go beyond the rate card."

    if flag == "risky_payment_terms":
        text = raw_text.lower()
        phrase = next((p for p in cfg["risky_payment_phrases"] if p in text), None)
        if ext.payment_advance_pct == 0 and ext.payment_net_days:
            return f"No advance, net {ext.payment_net_days} days."
        if phrase:
            return f'The message says "{phrase}".'
        return "Payment terms carry collection risk."

    if flag == "suspicious_sender":
        _, _, reasons = detect_spam(raw_text=raw_text, sender_domain=sender_domain, brand=ext.brand)
        return cap(reasons[-1]) + "." if reasons else f"Sender domain {sender_domain} doesn't match the brand."

    if flag == "missing_info":
        return f"Missing {', '.join(a.missing_fields)}." if a.missing_fields else "Key terms are missing."

    if flag == "duplicate":
        return "The same brand reached this creator through more than one message — merged into this inquiry."

    if flag == "urgent":
        dates = [d for d in (ext.response_deadline, ext.go_live_date) if d]
        if not dates:
            return "Reply needed soon."
        soonest = min(dates)
        days = (soonest - ref_date).days
        what = "Reply due" if soonest == ext.response_deadline else "Goes live"
        when = "today" if days == 0 else ("overdue" if days < 0 else f"in {days} day{'s' if days != 1 else ''}")
        return f"{what} {when} ({date_long(soonest)})."

    if flag == "capacity_full":
        return (f"{creator.current_booked_this_month} of {creator.max_paid_deals_per_month} paid deals "
                f"already booked this month — suggest a later date.")

    if flag == "blackout_clash":
        bd = _blackout_hit(creator, ext.go_live_date)
        if bd is None:
            return "Go-live falls in a blackout window."
        why = f" ({bd.reason})" if bd.reason else ""
        return (f"Go-live {date_long(ext.go_live_date)} falls in {name}'s "
                f"{date_short(bd.start)}–{date_long(bd.end)} blackout{why}.")

    return ""


def uncapped_score(creator: Creator, ext: Extraction, ref_date: dt.date,
                   raw_text: str, sender_domain: str, is_duplicate: bool) -> Assessment:
    """What these terms would score without the conflict — the same assess() with the
    clashing partner removed. A conflict carries no risk penalty, so this differs from
    the real assessment only by the cap.
    """
    p = _conflict_partner(creator, ext.brand_category, ext.go_live_date or ref_date)
    shadow = copy.deepcopy(creator)
    shadow.active_partners = [x for x in shadow.active_partners if not (p and x.brand == p.brand)]
    return assess(shadow, ext, ref_date, raw_text=raw_text, sender_domain=sender_domain,
                  is_duplicate=is_duplicate)


# ---------------------------------------------------------------------------------
# Budget vs quote
# ---------------------------------------------------------------------------------

def _step5(pct: float) -> int:
    return int(round(pct / 5) * 5)


def bvq(creator: Creator, ext: Extraction, a: Assessment) -> dict:
    """The pairing that answers 'is this offer short?' in one glance."""
    offer = a.offer_value
    quote = a.quote.total if a.quote and a.quote.total > 0 else None
    barter = a.type == "barter"
    view = {
        "offer": offer, "quote": quote, "vs": "product value vs" if barter else "offered vs",
        "state": None, "pct": None, "fill": 0, "over": False, "min_class": "min-none",
        "verdict": "", "sub": "", "floor": None,
    }
    if offer is None:
        view["state"] = "muted"
        view["verdict"] = "Budget not stated"
        return view

    minimum = creator.min_acceptable_pct
    m = _step5(minimum * 100)
    view["min_class"] = f"min-{m}" if 50 <= m <= 90 else "min-none"
    if quote is None:
        view["state"] = "muted"
        view["verdict"] = "No quote — deliverables not stated"
        return view

    ratio = offer / quote
    pct = ratio * 100
    view.update(pct=pct, fill=min(100, _step5(pct)), over=ratio > 1, floor=quote * minimum)
    diff = abs(offer - quote)
    if ratio >= 1:
        view["state"], view["verdict"] = "ok", f"{pct:.0f}% · {inr(diff)} above" if diff >= 1 else f"{pct:.0f}% · matches the quote"
    elif ratio >= minimum:
        view["state"], view["verdict"] = "under", f"{pct:.0f}% · {inr(diff)} short"
    else:
        view["state"], view["verdict"] = "short", f"{pct:.0f}% · {inr(diff)} short"

    if "no_go" in a.flags or a.type == "spam":
        view["state"] = "muted"
        view["verdict"] = f"{pct:.0f}% · money doesn't matter here"
    elif "conflict" in a.flags and ratio >= minimum:
        view["sub"] = "price is fine; the conflict is not"
    elif view["state"] == "short":
        view["sub"] = f"floor is {minimum * 100:.0f}% ({inr(view['floor'])})"
    return view


# ---------------------------------------------------------------------------------
# Quote breakdown — reads as an argument the manager can paste into a reply
# ---------------------------------------------------------------------------------

def quote_rows(creator: Creator, ext: Extraction, a: Assessment) -> list[dict]:
    q = a.quote
    if q is None or not ext.deliverables:
        return []
    cfg = load_config()
    name = first_name(creator)
    rows: list[dict] = []
    running = 0.0

    for d in ext.deliverables:
        rate = creator.rate_for(d.type)
        amount = rate * d.count
        running += amount
        why = f"Rate card, {inr(rate)} each" if d.count > 1 else "Rate card"
        if not rate:
            why = f"Not on {name}'s rate card"
        rows.append({"kind": "base", "what": f"{d.count} × {DELIVERABLE_LABELS.get(d.type, d.type)}",
                     "why": why, "amount": inr(amount), "running": inr(running)})

    pct = creator.rate_card.bundle_discount_pct * 100
    if q.bundle_discount_applied:
        rows.append({"kind": "minus", "what": "Bundle discount",
                     "why": f"{q.deliverable_count} deliverables in one booking — {name}'s bundle rate is {pct:.0f}% off {inr(q.base)}",
                     "amount": inr(-(q.base - q.after_discount)), "running": inr(q.after_discount)})
    elif creator.rate_card.bundle_discount_pct > 0:
        rows.append({"kind": "zero", "what": "Bundle discount",
                     "why": f"Not applied — needs {cfg['bundle_discount_min_deliverables']}+ deliverables, this booking has {q.deliverable_count}",
                     "amount": "₹0", "running": inr(q.after_discount)})

    rows.append({"kind": "sub", "what": "Content fee", "why": "Rights below are charged on this figure",
                 "amount": "", "running": inr(q.after_discount)})
    running = q.after_discount

    free = creator.max_usage_days_without_extra_fee
    step = cfg["usage_fee_pct_per_30_days"] * 100
    if q.usage_extra_blocks:
        running += q.usage_fee_amount
        blocks = q.usage_extra_blocks
        rows.append({"kind": "plus", "what": "Usage rights",
                     "why": f"{ext.usage_rights_days} days asked, {free} included — {blocks} extra 30-day block{'s' if blocks != 1 else ''} × {step:.0f}% = {q.usage_fee_pct * 100:.0f}%",
                     "amount": "+" + inr(q.usage_fee_amount), "running": inr(running)})
    else:
        why = f"{ext.usage_rights_days} days asked, {free} included" if ext.usage_rights_days else f"Not stated — priced at the {free} days included"
        rows.append({"kind": "zero", "what": "Usage rights", "why": why, "amount": "+₹0", "running": inr(running)})

    if q.whitelisting_fee_amount:
        running += q.whitelisting_fee_amount
        rows.append({"kind": "plus", "what": "Whitelisting",
                     "why": f"Paid ads run from {name}'s handle — {q.whitelisting_fee_pct * 100:.0f}%",
                     "amount": "+" + inr(q.whitelisting_fee_amount), "running": inr(running)})
    else:
        rows.append({"kind": "zero", "what": "Whitelisting", "why": "Not requested", "amount": "+₹0", "running": inr(running)})

    if q.exclusivity_fee_amount:
        running += q.exclusivity_fee_amount
        days = f"{ext.exclusivity_requested_days} days requested — " if ext.exclusivity_requested_days else "Requested — "
        rows.append({"kind": "plus", "what": "Exclusivity", "why": f"{days}{q.exclusivity_fee_pct * 100:.0f}%",
                     "amount": "+" + inr(q.exclusivity_fee_amount), "running": inr(running)})
    else:
        rows.append({"kind": "zero", "what": "Exclusivity", "why": "Not requested", "amount": "+₹0", "running": inr(running)})

    rows.append({"kind": "total", "what": "Quote", "why": "", "amount": "", "running": inr(q.total)})
    return rows


# ---------------------------------------------------------------------------------
# Recommended action and the action group
# ---------------------------------------------------------------------------------

def recommendation(creator: Creator, a: Assessment) -> dict:
    rec = a.recommended_action
    headline = {
        "accept_and_negotiate": "Approve",
        "counter_offer": f"Counter at {inr(a.counter_offer_amount)}" if a.counter_offer_amount else "Counter-offer",
        "decline": "Decline",
        "ask_for_info": "Ask for info",
        "mark_spam": "Mark spam",
    }.get(rec, rec)

    if "conflict" in a.flags:
        why = "of the Conflict flag"
    elif "no_go" in a.flags:
        why = "of the No-go flag"
    elif a.type == "spam":
        why = "the message matches spam patterns"
    elif a.type == "not_a_deal":
        why = "there are no deal terms in the message"
    elif rec == "ask_for_info":
        why = "key terms are missing"
    elif rec == "accept_and_negotiate":
        why = "the offer meets the quote"
    elif rec == "counter_offer" and a.type == "barter":
        why = "the barter falls short but the brand is a fit — counter with a paid quote"
    elif rec == "counter_offer":
        why = (f"the offer is {a.rate_fit_pct:.0f}% of the quote — above {first_name(creator)}'s "
               f"{creator.min_acceptable_pct * 100:.0f}% floor, short of the full price")
    elif "lowball" in a.flags:
        why = "the offer is below the floor"
    else:
        why = "of the terms above"

    button = {"accept_and_negotiate": "approve", "counter_offer": "approve",
              "decline": "decline", "ask_for_info": "ask_for_info", "mark_spam": "mark_spam"}.get(rec)
    return {
        "headline": headline,
        "why": f"{headline.split(' at ')[0]} is recommended because {why}. Every action stays available.",
        "button": button,
        "approve_value": "counter_offer" if rec == "counter_offer" else "accept_and_negotiate",
    }


def decision_view(decision, creator: Creator | None) -> dict | None:
    if decision is None:
        return None
    label, outcome = OUTCOMES.get(decision["action"], (decision["action"], "open"))
    replies = decision["action"] != "mark_spam"
    edited = bool(decision["edited_reply"])
    detail = f"Logged {datetime_long(decision['timestamp'])}"
    if replies:
        where = f" into {creator.email}" if creator and creator.email else ""
        detail += f" · reply {'edited' if edited else 'as drafted'} · nothing was sent — paste it{where}."
    else:
        detail += " · no reply needed."
    return {"label": label, "outcome": outcome, "detail": detail, "timestamp": decision["timestamp"]}


# ---------------------------------------------------------------------------------
# Editable field rows
# ---------------------------------------------------------------------------------

PROVENANCE = {"manual": ("edited", "Edited"), "rules": ("rules", "Rules"), "ai": ("ai", "AI")}
BUDGET_TYPES = {
    "fixed": "Fixed budget", "per_deliverable": "Per deliverable", "negotiable": "Negotiable",
    "barter": "Barter — product, not cash", "not_stated": "Budget type not stated",
}
_YES_NO = [("yes", "Yes"), ("no", "No")]


def field_rows(ext: Extraction) -> list[dict]:
    def row(name, label, value, kind="text", num=False, options=None, note="", placeholder=""):
        css, prov_label = PROVENANCE.get(ext.provenance.get(name, "rules"), PROVENANCE["rules"])
        return {"name": name, "label": label, "value": "" if value is None else value, "kind": kind,
                "num": num, "options": options, "note": note, "placeholder": placeholder,
                "prov": css, "prov_label": prov_label}

    def iso(d):
        return d.isoformat() if d else ""

    def amount(v):
        return inr(v) if v is not None else ""

    return [
        row("brand", "Brand", ext.brand, placeholder="Not identified — add it"),
        row("brand_category", "Category", cap(ext.brand_category), placeholder="Unknown"),
        row("agency_or_direct", "Direct or agency", ext.agency_or_direct, kind="select",
            options=[("direct", "Direct"), ("agency", "Agency")]),
        row("budget_amount", "Budget", amount(ext.budget_amount), num=True,
            note=BUDGET_TYPES.get(ext.budget_type, ""), placeholder="Not stated"),
        row("product_value", "Product value", amount(ext.product_value), num=True,
            placeholder="Barter only"),
        row("deliverables", "Deliverables", deliverables_text(ext), placeholder="e.g. 2 × Reel, 3 × Story"),
        row("go_live_date", "Go live", iso(ext.go_live_date), kind="date"),
        row("response_deadline", "Response deadline", iso(ext.response_deadline), kind="date"),
        row("usage_rights_days", "Usage rights (days)", ext.usage_rights_days, kind="number", num=True,
            placeholder="Not stated"),
        row("whitelisting", "Whitelisting", "yes" if ext.whitelisting else "no", kind="select", options=_YES_NO),
        row("exclusivity_requested", "Exclusivity requested", "yes" if ext.exclusivity_requested else "no",
            kind="select", options=_YES_NO),
        row("payment_advance_pct", "Advance (%)",
            None if ext.payment_advance_pct is None else f"{ext.payment_advance_pct:g}",
            kind="number", num=True, placeholder="Not stated"),
        row("payment_net_days", "Net days", ext.payment_net_days, kind="number", num=True,
            placeholder="Not stated"),
    ]


def field_label(name: str) -> str:
    return next((r["label"] for r in field_rows(Extraction()) if r["name"] == name), name.replace("_", " "))


# ---------------------------------------------------------------------------------
# Creator page pieces
# ---------------------------------------------------------------------------------

def partner_view(p, ref_date: dt.date) -> dict:
    view = {"brand": p.brand, "category": cap(p.category), "exclusive": p.exclusive,
            "end": p.exclusivity_end_date, "state": "nonexcl", "days": None}
    if not p.exclusive:
        return view
    if p.exclusivity_end_date is None:
        view["state"] = "active"
        return view
    days = (p.exclusivity_end_date - ref_date).days
    view["days"] = abs(days)
    view["state"] = "active" if days > 0 else "expired"
    return view


def capacity_view(creator: Creator) -> dict:
    booked, total = creator.current_booked_this_month, creator.max_paid_deals_per_month
    return {"booked": booked, "total": total, "full": booked >= total,
            "open": max(0, total - booked), "slots": [i < booked for i in range(max(total, booked))]}
