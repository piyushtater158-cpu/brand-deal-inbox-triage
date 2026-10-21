"""The Add / Edit creator form: every Creator field, typed the way a manager types it.

`values_from_creator` and `values_from_form` both produce the same flat dict of strings
(plus partner and blackout rows), so the form re-renders exactly what was typed when a
save is rejected. `parse_creator_form` turns that into a Creator or raises ValueError
with a message naming the field.
"""
from __future__ import annotations

import datetime as dt
import re

from app.fmt import group_in
from app.models import BlackoutDate, Creator, Partner, RateCard

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def parse_number(raw: str | None, label: str, *, pct: bool = False, integer: bool = False):
    """Form numbers as people type them: '62,000', '₹62000', '10' (percent)."""
    if raw is None or str(raw).strip() == "":
        return None
    text = str(raw).replace(",", "").replace("₹", "").replace("%", "").strip()
    try:
        value = float(text)
    except ValueError:
        raise ValueError(f"{label} must be a number, got '{raw}'.") from None
    if value < 0:
        raise ValueError(f"{label} can't be negative.")
    if pct:
        value /= 100
    return int(value) if integer else value


def _required(raw, label, **kw):
    value = parse_number(raw, label, **kw)
    if value is None:
        raise ValueError(f"{label} is required.")
    return value


def _csv_list(text: str) -> list[str]:
    return [p.strip() for p in (text or "").split(",") if p.strip()]


def _lines(text: str) -> list[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def _money(n) -> str:
    return group_in(n) if n is not None else ""


def _pct(x) -> str:
    return f"{x * 100:g}" if x is not None else ""


def values_from_creator(c: Creator | None) -> dict:
    if c is None:
        return {
            "name": "", "ig_handle": "", "email": "", "niche": "", "city": "", "languages": "",
            "followers": "", "avg_reach": "", "engagement_rate": "",
            "reel": "", "story": "", "static_post": "", "carousel": "", "youtube_integration": "",
            "bundle_discount_pct": "10", "min_acceptable_pct": "70", "accepts_barter": "no",
            "barter_min_product_value": "0", "usage_rights_default_days": "30",
            "max_usage_days_without_extra_fee": "30", "max_paid_deals_per_month": "4",
            "current_booked_this_month": "0", "no_go_categories": "",
            "partners": [], "blackouts": [],
        }
    rc = c.rate_card
    return {
        "name": c.name, "ig_handle": c.ig_handle, "email": c.email,
        "niche": ", ".join(c.niche), "city": c.city, "languages": ", ".join(c.languages),
        "followers": _money(c.followers), "avg_reach": _money(c.avg_reach),
        "engagement_rate": f"{c.engagement_rate:g}",
        "reel": _money(rc.reel), "story": _money(rc.story), "static_post": _money(rc.static_post),
        "carousel": _money(rc.carousel), "youtube_integration": _money(rc.youtube_integration),
        "bundle_discount_pct": _pct(rc.bundle_discount_pct), "min_acceptable_pct": _pct(c.min_acceptable_pct),
        "accepts_barter": "yes" if c.accepts_barter else "no",
        "barter_min_product_value": _money(c.barter_min_product_value),
        "usage_rights_default_days": str(c.usage_rights_default_days),
        "max_usage_days_without_extra_fee": str(c.max_usage_days_without_extra_fee),
        "max_paid_deals_per_month": str(c.max_paid_deals_per_month),
        "current_booked_this_month": str(c.current_booked_this_month),
        "no_go_categories": "\n".join(c.no_go_categories),
        "partners": [
            {"brand": p.brand, "category": p.category, "exclusive": "yes" if p.exclusive else "no",
             "end": p.exclusivity_end_date.isoformat() if p.exclusivity_end_date else ""}
            for p in c.active_partners
        ],
        "blackouts": [
            {"start": b.start.isoformat(), "end": b.end.isoformat(), "reason": b.reason}
            for b in c.blackout_dates
        ],
    }


SCALAR_FIELDS = [k for k in values_from_creator(None) if k not in ("partners", "blackouts")]


def values_from_form(form) -> dict:
    v = {k: str(form.get(k, "") or "") for k in SCALAR_FIELDS}
    v["partners"] = [
        {"brand": b, "category": c, "exclusive": e, "end": d}
        for b, c, e, d in zip(form.getlist("p_brand"), form.getlist("p_cat"),
                              form.getlist("p_excl"), form.getlist("p_end"))
    ]
    v["blackouts"] = [
        {"start": s, "end": e, "reason": r}
        for s, e, r in zip(form.getlist("b_start"), form.getlist("b_end"), form.getlist("b_reason"))
    ]
    return v


def _date(raw: str, label: str) -> dt.date:
    try:
        return dt.date.fromisoformat(raw.strip())
    except ValueError:
        raise ValueError(f"{label} must be a date (YYYY-MM-DD), got '{raw}'.") from None


def parse_creator_form(v: dict, creator_id: str) -> Creator:
    name = v["name"].strip()
    if not name:
        raise ValueError("Name is required.")
    handle = v["ig_handle"].strip()
    if not handle:
        raise ValueError("Instagram handle is required.")
    if not handle.startswith("@"):
        handle = "@" + handle
    email = v["email"].strip()
    if not EMAIL_RE.match(email):
        raise ValueError(f"Email must look like name@domain.com, got '{email}'.")
    niche = [n.lower() for n in _csv_list(v["niche"])]
    if not niche:
        raise ValueError("Add at least one niche — brand fit is scored against it.")

    engagement = _required(v["engagement_rate"], "Engagement rate")
    if engagement > 100:
        raise ValueError("Engagement rate is a percentage, so it can't be over 100.")
    bundle = parse_number(v["bundle_discount_pct"], "Bundle discount", pct=True) or 0.0
    minimum = _required(v["min_acceptable_pct"], "Minimum acceptable", pct=True)
    if bundle >= 1 or minimum > 1:
        raise ValueError("Percentages must be between 0 and 100.")

    partners = []
    for i, p in enumerate(v["partners"], start=1):
        brand, cat = p["brand"].strip(), p["category"].strip().lower()
        if not brand and not cat:
            continue
        if not brand or not cat:
            raise ValueError(f"Partner row {i} needs both a brand and a category.")
        exclusive = p["exclusive"] == "yes"
        end = _date(p["end"], f"Partner {brand} end date") if exclusive and p["end"].strip() else None
        partners.append(Partner(brand=brand, category=cat, exclusive=exclusive, exclusivity_end_date=end))

    blackouts = []
    for i, b in enumerate(v["blackouts"], start=1):
        if not b["start"].strip() and not b["end"].strip():
            continue
        start = _date(b["start"], f"Blackout row {i} start")
        end = _date(b["end"], f"Blackout row {i} end")
        if end < start:
            raise ValueError(f"Blackout row {i} ends before it starts.")
        blackouts.append(BlackoutDate(start=start, end=end, reason=b["reason"].strip()))

    no_go = []
    for cat in _lines(v["no_go_categories"]):
        if cat.lower() not in no_go:
            no_go.append(cat.lower())

    return Creator(
        id=creator_id, name=name, ig_handle=handle, email=email, niche=niche,
        city=v["city"].strip(), languages=_csv_list(v["languages"]),
        followers=_required(v["followers"], "Followers", integer=True),
        avg_reach=_required(v["avg_reach"], "Average reach", integer=True),
        engagement_rate=engagement,
        rate_card=RateCard(
            reel=_required(v["reel"], "Reel rate"),
            story=_required(v["story"], "Story rate"),
            static_post=_required(v["static_post"], "Static post rate"),
            carousel=_required(v["carousel"], "Carousel rate"),
            youtube_integration=parse_number(v["youtube_integration"], "YouTube integration rate"),
            bundle_discount_pct=bundle,
        ),
        min_acceptable_pct=minimum,
        accepts_barter=v["accepts_barter"] == "yes",
        barter_min_product_value=parse_number(v["barter_min_product_value"], "Barter minimum") or 0.0,
        usage_rights_default_days=_required(v["usage_rights_default_days"], "Usage rights default", integer=True),
        max_usage_days_without_extra_fee=_required(
            v["max_usage_days_without_extra_fee"], "Max usage without extra fee", integer=True),
        active_partners=partners,
        no_go_categories=no_go,
        max_paid_deals_per_month=_required(v["max_paid_deals_per_month"], "Monthly capacity", integer=True),
        current_booked_this_month=parse_number(
            v["current_booked_this_month"], "Booked this month", integer=True) or 0,
        blackout_dates=blackouts,
    )


def new_creator_id(name: str, existing_ids) -> str:
    """'Ishaan Verma' -> 'ishaan_verma', then 'ishaan_verma_2' if that's taken."""
    base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "creator"
    candidate, n = base, 2
    while candidate in existing_ids:
        candidate, n = f"{base}_{n}", n + 1
    return candidate
