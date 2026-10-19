"""Rate-card math (Premise 3). Order of operations, fixed and documented because the
brief never states one:

    base = Σ(rate_card[type] × count)
    if total deliverable count >= bundle_discount_min_deliverables:
        base *= (1 - creator.bundle_discount_pct)
    surcharge_multiplier = 1 + usage_pct + whitelist_pct + exclusivity_pct
    quoted_price = (discounted) base * surcharge_multiplier

Every factor comes from config.yaml except the per-creator bundle_discount_pct, which
is part of that creator's own rate card.
"""
from __future__ import annotations

import math

from app.config_loader import load_config
from app.models import Creator, Deliverable, QuoteBreakdown


def compute_quote(
    creator: Creator,
    deliverables: list[Deliverable],
    usage_rights_days: int | None,
    whitelisting: bool,
    exclusivity_requested: bool,
) -> QuoteBreakdown:
    cfg = load_config()

    base = 0.0
    count = 0
    for d in deliverables:
        base += creator.rate_for(d.type) * d.count
        count += d.count

    bundle_min = cfg["bundle_discount_min_deliverables"]
    discount_applied = count >= bundle_min and creator.rate_card.bundle_discount_pct > 0
    discount_pct = creator.rate_card.bundle_discount_pct if discount_applied else 0.0
    after_discount = base * (1 - discount_pct) if discount_applied else base

    # Usage fee: +20% per extra 30-day block (ceiling) beyond the creator's
    # max_usage_days_without_extra_fee. No overage -> 0 blocks, 0 fee.
    usage_days = usage_rights_days or 0
    overage = max(0, usage_days - creator.max_usage_days_without_extra_fee)
    usage_blocks = math.ceil(overage / 30) if overage > 0 else 0
    usage_fee_pct = usage_blocks * cfg["usage_fee_pct_per_30_days"]
    usage_fee_amount = after_discount * usage_fee_pct

    whitelisting_fee_pct = cfg["whitelisting_fee_pct"] if whitelisting else 0.0
    whitelisting_fee_amount = after_discount * whitelisting_fee_pct

    exclusivity_fee_pct = cfg["exclusivity_fee_pct"] if exclusivity_requested else 0.0
    exclusivity_fee_amount = after_discount * exclusivity_fee_pct

    total = after_discount + usage_fee_amount + whitelisting_fee_amount + exclusivity_fee_amount

    return QuoteBreakdown(
        base=round(base, 2),
        deliverable_count=count,
        bundle_discount_applied=discount_applied,
        bundle_discount_pct=discount_pct,
        after_discount=round(after_discount, 2),
        usage_extra_blocks=usage_blocks,
        usage_fee_pct=usage_fee_pct,
        usage_fee_amount=round(usage_fee_amount, 2),
        whitelisting_fee_pct=whitelisting_fee_pct,
        whitelisting_fee_amount=round(whitelisting_fee_amount, 2),
        exclusivity_fee_pct=exclusivity_fee_pct,
        exclusivity_fee_amount=round(exclusivity_fee_amount, 2),
        total=round(total, 2),
    )


def round_counter_offer(amount: float) -> float:
    cfg = load_config()
    step = cfg["counter_offer_round_to"]
    return round(amount / step) * step
