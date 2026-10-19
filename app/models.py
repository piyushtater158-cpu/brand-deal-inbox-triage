"""Internal data model. Plain dataclasses — fast to construct, easy to mutate when a
manager edits a field, and cheap to re-score. Pydantic models in schemas.py wrap these
only at the API / config-form boundary.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field


@dataclass
class Partner:
    brand: str
    category: str
    exclusive: bool
    exclusivity_end_date: dt.date | None = None


@dataclass
class BlackoutDate:
    start: dt.date
    end: dt.date
    reason: str = ""


@dataclass
class RateCard:
    reel: float
    story: float
    static_post: float
    carousel: float
    youtube_integration: float | None = None
    bundle_discount_pct: float = 0.0


@dataclass
class Creator:
    id: str
    name: str
    ig_handle: str
    email: str
    niche: list[str]
    city: str
    languages: list[str]
    followers: int
    avg_reach: int
    engagement_rate: float
    rate_card: RateCard
    min_acceptable_pct: float
    accepts_barter: bool
    barter_min_product_value: float
    usage_rights_default_days: int
    max_usage_days_without_extra_fee: int
    active_partners: list[Partner] = field(default_factory=list)
    no_go_categories: list[str] = field(default_factory=list)
    max_paid_deals_per_month: int = 4
    current_booked_this_month: int = 0
    blackout_dates: list[BlackoutDate] = field(default_factory=list)

    def rate_for(self, deliverable_type: str) -> float:
        rc = self.rate_card
        mapping = {
            "reel": rc.reel,
            "story": rc.story,
            "static_post": rc.static_post,
            "carousel": rc.carousel,
            "youtube_integration": rc.youtube_integration or 0.0,
        }
        return mapping.get(deliverable_type, 0.0)


@dataclass
class Deliverable:
    type: str  # reel | story | static_post | carousel | youtube_integration
    count: int


@dataclass
class RawMessage:
    """What an InboxScanner hands the pipeline. Nothing else is required of a real
    mailbox integration — see scanner.py and the README's 'plug in a real inbox' note.
    """

    id: str
    creator_id: str
    source: str  # "email" | "dm"
    received_at: dt.datetime
    sender_name: str
    sender_email_or_handle: str
    sender_domain: str
    subject: str
    raw_text: str


@dataclass
class Extraction:
    brand: str | None = None
    brand_category: str | None = None
    agency_or_direct: str = "direct"  # "direct" | "agency"
    budget_amount: float | None = None
    budget_currency: str = "INR"
    budget_type: str = "not_stated"  # fixed | per_deliverable | negotiable | not_stated | barter
    product_value: float | None = None
    deliverables: list[Deliverable] = field(default_factory=list)
    go_live_date: dt.date | None = None
    response_deadline: dt.date | None = None
    usage_rights_days: int | None = None
    exclusivity_requested: bool = False
    exclusivity_requested_days: int | None = None
    whitelisting: bool = False
    payment_advance_pct: float | None = None
    payment_net_days: int | None = None
    # per-field provenance: "ai" | "rules" | "manual"
    provenance: dict[str, str] = field(default_factory=dict)


@dataclass
class QuoteBreakdown:
    base: float
    deliverable_count: int
    bundle_discount_applied: bool
    bundle_discount_pct: float
    after_discount: float
    usage_extra_blocks: int
    usage_fee_pct: float
    usage_fee_amount: float
    whitelisting_fee_pct: float
    whitelisting_fee_amount: float
    exclusivity_fee_pct: float
    exclusivity_fee_amount: float
    total: float


@dataclass
class Assessment:
    type: str = "not_a_deal"  # paid | barter | hybrid | spam | not_a_deal
    flags: list[str] = field(default_factory=list)
    rate_fit_pct: float | None = None
    brand_fit_score: float = 0.0
    urgency_score: float = 0.0
    completeness_score: float = 0.0
    risk_penalty: float = 0.0
    final_score: float = 0.0
    priority: str = "Ignore"  # P1 | P2 | P3 | Ignore
    recommended_action: str = "ask_for_info"
    counter_offer_amount: float | None = None
    missing_fields: list[str] = field(default_factory=list)
    reason: str = ""
    quote: QuoteBreakdown | None = None
    offer_value: float | None = None
