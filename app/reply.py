"""Reply drafting. AI writes the warm, professional version when it's on and
configured; the template path below is the genuine fallback — same facts, same
numbers, plainer sentences — not a degraded stand-in.
"""
from __future__ import annotations

from app import ai
from app.fmt import inr
from app.models import Assessment, Creator, Extraction


def _fmt_inr(amount: float | None) -> str:
    return inr(amount, none="₹0")


def _deliverables_str(ext: Extraction) -> str:
    labels = {
        "reel": "Reel", "story": "Story", "static_post": "Static Post",
        "carousel": "Carousel", "youtube_integration": "YouTube Integration",
    }
    return ", ".join(f"{d.count} × {labels.get(d.type, d.type)}" for d in ext.deliverables) or "the requested deliverables"


def _template_reply(creator: Creator, ext: Extraction, a: Assessment) -> str:
    brand = ext.brand or "there"
    deliverables = _deliverables_str(ext)

    if a.recommended_action == "mark_spam":
        return (
            f"This message has been marked as spam/scam and will not be replied to.\n\n"
            f"Reason: {a.reason}"
        )

    if a.recommended_action == "decline":
        if "conflict" in a.flags:
            return (
                f"Hi {brand} team,\n\n"
                f"Thank you for thinking of {creator.name} for this collaboration. "
                f"Unfortunately, {creator.name} currently has an active exclusivity "
                f"commitment in this category and can't take this on right now. "
                f"We'd be glad to revisit once that commitment ends.\n\n"
                f"Best,\n{creator.name}'s team"
            )
        if "no_go" in a.flags:
            return (
                f"Hi {brand} team,\n\n"
                f"Thanks for reaching out. This category isn't one {creator.name} "
                f"partners in, so we'll have to pass on this one.\n\n"
                f"Best,\n{creator.name}'s team"
            )
        return (
            f"Hi {brand} team,\n\n"
            f"Thanks for the offer. Based on {creator.name}'s current rate card, this "
            f"offer is below what we can take on for {deliverables}. We'd be happy to "
            f"reconsider at a rate closer to {_fmt_inr(a.quote.total if a.quote else None)}.\n\n"
            f"Best,\n{creator.name}'s team"
        )

    if a.recommended_action == "ask_for_info":
        missing = ", ".join(a.missing_fields) or "a few more details"
        return (
            f"Hi {brand} team,\n\n"
            f"Thanks for reaching out about working with {creator.name}! Before we can "
            f"put together a proper quote, could you share {missing}?\n\n"
            f"Once we have that we can turn around a response quickly.\n\n"
            f"Best,\n{creator.name}'s team"
        )

    if a.recommended_action == "counter_offer":
        counter = _fmt_inr(a.counter_offer_amount)
        extra_note = ""
        if ext.budget_type == "barter" or (a.type == "barter"):
            extra_note = " We'd prefer this as a paid collaboration rather than a barter arrangement."
        return (
            f"Hi {brand} team,\n\n"
            f"Thanks so much for thinking of {creator.name} for this!{extra_note} "
            f"Based on {creator.name}'s current rate card for {deliverables}, our rate "
            f"would be {counter}. Happy to walk through the breakdown if useful — let "
            f"us know if that works on your end.\n\n"
            f"Best,\n{creator.name}'s team"
        )

    # accept_and_negotiate
    return (
        f"Hi {brand} team,\n\n"
        f"This looks great — {creator.name} would love to work on this with you! "
        f"We're on board with the terms for {deliverables}. Let's lock in the "
        f"timeline and get started.\n\n"
        f"Best,\n{creator.name}'s team"
    )


def _ai_context(creator: Creator, ext: Extraction, a: Assessment) -> dict:
    return {
        "creator_name": creator.name,
        "brand": ext.brand,
        "recommended_action": a.recommended_action,
        "reason": a.reason,
        "quote_total": _fmt_inr(a.quote.total) if a.quote else None,
        "offered": _fmt_inr(a.offer_value) if a.offer_value else None,
        "counter_offer_amount": _fmt_inr(a.counter_offer_amount) if a.counter_offer_amount else None,
        "missing_fields": a.missing_fields,
        "deliverables": _deliverables_str(ext),
        "flags": a.flags,
    }


def ai_reply(creator: Creator, ext: Extraction, a: Assessment, *, cached_only: bool = False) -> str | None:
    if a.recommended_action == "mark_spam":
        return None
    return ai.write_reply_ai(_ai_context(creator, ext, a), cached_only=cached_only)


def draft_for_page(creator: Creator, ext: Extraction, a: Assessment, ai_on: bool) -> tuple[str, str]:
    """(text, source) without ever waiting on a model: an AI draft for these exact terms
    if one was already written, otherwise the template. Rendering this on every edit is
    what keeps re-scoring instant."""
    if ai_on:
        text = ai_reply(creator, ext, a, cached_only=True)
        if text:
            return text, "ai"
    return _template_reply(creator, ext, a), "template"


def generate_reply(creator: Creator, ext: Extraction, a: Assessment, ai_on: bool) -> str:
    if ai_on:
        text = ai_reply(creator, ext, a)
        if text:
            return text
    return _template_reply(creator, ext, a)
