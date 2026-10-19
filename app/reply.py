"""Reply drafting. AI writes the warm, professional version when it's on and
configured; the template path below is the genuine fallback — same facts, same
numbers, plainer sentences — not a degraded stand-in.
"""
from __future__ import annotations

from app import ai
from app.models import Assessment, Creator, Extraction


def _fmt_inr(amount: float | None) -> str:
    if amount is None:
        return "₹0"
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


def generate_reply(creator: Creator, ext: Extraction, a: Assessment, ai_on: bool) -> str:
    if ai_on:
        context = {
            "creator_name": creator.name,
            "brand": ext.brand,
            "recommended_action": a.recommended_action,
            "reason": a.reason,
            "quote_total": a.quote.total if a.quote else None,
            "counter_offer_amount": a.counter_offer_amount,
            "missing_fields": a.missing_fields,
            "deliverables": [{"type": d.type, "count": d.count} for d in ext.deliverables],
            "flags": a.flags,
        }
        ai_reply = ai.write_reply_ai(context)
        if ai_reply:
            return ai_reply
    return _template_reply(creator, ext, a)
