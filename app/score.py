"""The rules engine. Every flag and the final score trace to config.yaml — see the
design doc's Premises 3-9 for the gaps the brief leaves open and how this module
resolves them. AI never touches anything in this file: it only writes fields this
module reads (extract.py) and language on top of what this module decides (reply.py).
"""
from __future__ import annotations

import datetime as dt

from app.config_loader import load_config
from app.models import Assessment, Creator, Extraction
from app.quote import compute_quote, round_counter_offer
from app.spam import detect_spam

REQUIRED_FIELDS = ["offer_value", "deliverables", "go_live_date", "usage_rights_days"]


def classify_type(ext: Extraction) -> str:
    has_deal_signal = bool(ext.brand) or ext.deliverables or ext.budget_amount or ext.product_value
    if not has_deal_signal:
        return "not_a_deal"
    if ext.product_value and ext.budget_amount:
        return "hybrid"
    if ext.product_value and not ext.budget_amount:
        return "barter"
    return "paid"


def _offer_value(ext: Extraction, deal_type: str) -> float | None:
    if deal_type == "hybrid":
        return (ext.budget_amount or 0) + (ext.product_value or 0)
    if deal_type == "barter":
        return ext.product_value
    return ext.budget_amount


def _brand_fit(creator: Creator, brand: str | None, brand_category: str | None) -> float:
    cfg = load_config()
    scores = cfg["brand_fit_scores"]
    adjacency = cfg["category_adjacency"]
    primary_niche = creator.niche[0] if creator.niche else None

    if not brand_category:
        score = scores["unknown"]
    elif brand_category in creator.niche:
        score = scores["in_category"]
    elif primary_niche and brand_category in adjacency.get(primary_niche, []):
        score = scores["adjacent"]
    elif primary_niche and primary_niche in adjacency.get(brand_category, []):
        score = scores["adjacent"]
    else:
        score = scores["unrelated"]

    if brand:
        known = [b.lower() for b in cfg["known_brands"]]
        if brand.lower() in known:
            score += scores["known_brand_bonus"]
    return min(score, 1.0)


def _urgency(ext: Extraction, reference_date: dt.date, cfg: dict) -> tuple[float, bool]:
    candidates = [d for d in (ext.response_deadline, ext.go_live_date) if d is not None]
    if not candidates:
        return 0.2, False
    days_until = min((d - reference_date).days for d in candidates)
    if days_until <= cfg["urgency_days_high"]:
        return 1.0, True
    if days_until <= cfg["urgency_days_medium"]:
        return 0.6, False
    return 0.2, False


def _conflict_partner(creator: Creator, brand_category: str | None, compare_date: dt.date):
    if not brand_category:
        return None
    for p in creator.active_partners:
        if not p.exclusive or p.category != brand_category:
            continue
        if p.exclusivity_end_date is None or p.exclusivity_end_date > compare_date:
            return p
    return None


def _blackout_hit(creator: Creator, go_live_date: dt.date | None):
    if go_live_date is None:
        return None
    for bd in creator.blackout_dates:
        if bd.start <= go_live_date <= bd.end:
            return bd
    return None


def assess(
    creator: Creator,
    ext: Extraction,
    reference_date: dt.date,
    raw_text: str = "",
    sender_domain: str = "",
    is_duplicate: bool = False,
) -> Assessment:
    cfg = load_config()

    is_spam, is_suspicious_sender, spam_reasons = detect_spam(
        raw_text=raw_text,
        sender_domain=sender_domain,
        brand=ext.brand,
    )

    if is_spam:
        return Assessment(
            type="spam",
            flags=["suspicious_sender"] if is_suspicious_sender else [],
            final_score=0.0,
            priority="Ignore",
            recommended_action="mark_spam",
            reason="Flagged as spam/scam: " + "; ".join(spam_reasons) + ".",
        )

    deal_type = classify_type(ext)
    if deal_type == "not_a_deal":
        return Assessment(
            type="not_a_deal",
            flags=[],
            final_score=0.0,
            priority="Ignore",
            recommended_action="decline",
            reason="No brand deal terms found — looks like a newsletter or general mailer.",
        )

    offer_value = _offer_value(ext, deal_type)
    quote = compute_quote(
        creator,
        ext.deliverables,
        ext.usage_rights_days,
        ext.whitelisting,
        ext.exclusivity_requested,
    )
    rate_fit_pct = (offer_value / quote.total * 100) if (offer_value and quote.total > 0) else None

    flags: list[str] = []
    missing_fields: list[str] = []
    if offer_value is None:
        missing_fields.append("budget / product value")
    if not ext.deliverables:
        missing_fields.append("deliverables")
    if ext.go_live_date is None:
        missing_fields.append("go-live date")
    if ext.usage_rights_days is None:
        missing_fields.append("usage rights")
    if missing_fields:
        flags.append("missing_info")

    completeness_score = (4 - len(missing_fields)) / 4

    compare_date = ext.go_live_date or reference_date
    conflict_partner = _conflict_partner(creator, ext.brand_category, compare_date)
    if conflict_partner:
        flags.append("conflict")

    no_go_categories = set(creator.no_go_categories) | set(cfg["global_no_go_categories"])
    is_no_go = bool(ext.brand_category) and ext.brand_category in no_go_categories
    if is_no_go:
        flags.append("no_go")

    if creator.current_booked_this_month >= creator.max_paid_deals_per_month:
        flags.append("capacity_full")

    blackout = _blackout_hit(creator, ext.go_live_date)
    if blackout:
        flags.append("blackout_clash")

    usage_overreach = bool(
        (ext.usage_rights_days and ext.usage_rights_days > creator.max_usage_days_without_extra_fee)
        or ext.whitelisting
    )
    if usage_overreach:
        flags.append("usage_overreach")

    raw_text_l = raw_text.lower()
    risky_payment = bool(
        (ext.payment_advance_pct == 0 and ext.payment_net_days and ext.payment_net_days > 60)
        or any(p in raw_text_l for p in cfg["risky_payment_phrases"])
    )
    if risky_payment:
        flags.append("risky_payment_terms")

    if is_suspicious_sender:
        flags.append("suspicious_sender")

    min_acceptable = creator.min_acceptable_pct
    is_lowball = rate_fit_pct is not None and (rate_fit_pct / 100) < min_acceptable
    if is_lowball:
        flags.append("lowball")

    if is_duplicate:
        flags.append("duplicate")

    urgency_score, is_urgent = _urgency(ext, reference_date, cfg)
    if is_urgent:
        flags.append("urgent")

    brand_fit_score = _brand_fit(creator, ext.brand, ext.brand_category)

    barter_acceptable = True
    if deal_type == "barter":
        barter_acceptable = creator.accepts_barter and (
            (ext.product_value or 0) >= creator.barter_min_product_value
        )
        if not barter_acceptable and "lowball" not in flags:
            flags.append("lowball")

    weights = cfg["scoring_weights"]
    cap = cfg["rate_fit_cap"]
    rate_fit_ratio = (rate_fit_pct / 100) if rate_fit_pct is not None else 0.0
    risk_penalty = sum(
        cfg["risk_penalty"].get(f, 0) for f in flags if f in cfg["risk_penalty"]
    )

    final_score = (
        weights["rate_fit"] * min(rate_fit_ratio, cap) / cap
        + weights["brand_fit"] * brand_fit_score
        + weights["urgency"] * urgency_score
        + weights["completeness"] * completeness_score
        - risk_penalty
    )
    final_score = max(0.0, min(100.0, final_score))

    # Hard caps, applied last, most severe first.
    if is_no_go:
        final_score = 0.0
    elif conflict_partner:
        final_score = min(final_score, 20.0)

    bands = cfg["priority_bands"]
    if final_score >= bands["p1_min"]:
        priority = "P1"
    elif final_score >= bands["p2_min"]:
        priority = "P2"
    elif final_score >= bands["p3_min"]:
        priority = "P3"
    else:
        priority = "Ignore"

    # Recommended action — precedence order.
    counter_offer_amount: float | None = None
    if is_no_go or conflict_partner:
        recommended_action = "decline"
    elif "missing_info" in flags:
        recommended_action = "ask_for_info"
    elif deal_type == "barter" and not barter_acceptable:
        recommended_action = "counter_offer" if brand_fit_score >= 0.5 else "decline"
        if recommended_action == "counter_offer":
            counter_offer_amount = round_counter_offer(quote.total)
    elif rate_fit_pct is None:
        recommended_action = "ask_for_info"
    elif rate_fit_ratio >= 1.0:
        recommended_action = "accept_and_negotiate"
    elif rate_fit_ratio >= min_acceptable:
        recommended_action = "counter_offer"
        counter_offer_amount = round_counter_offer(quote.total)
    else:
        recommended_action = "decline"

    # Reason — the one-line explanation shown on the card.
    reason_parts: list[str] = []
    if conflict_partner:
        end = conflict_partner.exclusivity_end_date
        end_str = end.strftime("%b %Y") if end else "no fixed end date"
        reason_parts.append(
            f"Clashes with active {conflict_partner.brand} exclusivity (runs to {end_str})."
        )
    elif is_no_go:
        reason_parts.append(f"{ext.brand_category} is on the no-go list.")
    elif "missing_info" in flags:
        reason_parts.append(f"Missing {', '.join(missing_fields)} — needs more info.")
    elif rate_fit_pct is not None:
        reason_parts.append(f"{rate_fit_pct:.0f}% of rate card.")
        if recommended_action == "counter_offer" and counter_offer_amount:
            reason_parts.append(f"Counter at ₹{counter_offer_amount:,.0f}.")

    if is_urgent:
        reason_parts.append("Urgent — reply needed within 48 hours.")
    if "capacity_full" in flags:
        reason_parts.append("Creator at capacity this month — suggest moving the date.")
    if "blackout_clash" in flags:
        reason_parts.append("Clashes with a blackout window — suggest another date.")

    reason = " ".join(reason_parts) or "Review needed."

    return Assessment(
        type=deal_type,
        flags=flags,
        rate_fit_pct=rate_fit_pct,
        brand_fit_score=round(brand_fit_score, 2),
        urgency_score=urgency_score,
        completeness_score=completeness_score,
        risk_penalty=risk_penalty,
        final_score=round(final_score, 1),
        priority=priority,
        recommended_action=recommended_action,
        counter_offer_amount=counter_offer_amount,
        missing_fields=missing_fields,
        reason=reason,
        quote=quote,
        offer_value=offer_value,
    )
