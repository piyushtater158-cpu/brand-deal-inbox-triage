"""Pydantic models at the API/config-form boundary. The engine itself (extract.py,
quote.py, score.py) works with plain dataclasses in models.py — this file exists
specifically for the one place the brief asks for real validation: the /config POST,
so a malformed edit gets rejected with a clear error instead of corrupting
config.yaml.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ScoringWeights(BaseModel):
    rate_fit: float
    brand_fit: float
    urgency: float
    completeness: float


class RiskPenalty(BaseModel):
    risky_payment_terms: float
    usage_overreach: float
    suspicious_sender: float
    capacity_full: float = 0
    blackout_clash: float = 0


class PriorityBands(BaseModel):
    p1_min: float
    p2_min: float
    p3_min: float


class BrandFitScores(BaseModel):
    in_category: float
    adjacent: float
    unknown: float
    unrelated: float
    known_brand_bonus: float


class ConfigModel(BaseModel):
    """Mirrors config.yaml. Free-form sections (lookups, keyword lists, spam
    patterns) stay permissive dicts/lists — they're data, not structure that needs
    validating — while the numeric sections that drive the score formula are typed
    so a typo (a string where a weight belongs) is rejected before it reaches the
    engine.
    """

    reference_date: str
    keywords: list[str]
    scoring_weights: ScoringWeights
    rate_fit_cap: float
    risk_penalty: RiskPenalty
    priority_bands: PriorityBands
    min_acceptable_pct_default: float
    lowball_pct: float
    bundle_discount_min_deliverables: int
    usage_fee_pct_per_30_days: float
    whitelisting_fee_pct: float
    exclusivity_fee_pct: float
    counter_offer_round_to: int
    brand_fit_scores: BrandFitScores
    category_adjacency: dict[str, list[str]]
    known_brands: list[str]
    brand_category_lookup: dict[str, str]
    urgency_days_high: int
    urgency_days_medium: int
    duplicate_window_days: int
    global_no_go_categories: list[str]
    spam_patterns: dict[str, Any]
    risky_payment_phrases: list[str]
    ai: dict[str, Any]
