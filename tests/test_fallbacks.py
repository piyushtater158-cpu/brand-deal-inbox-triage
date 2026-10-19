"""AI-off must keep every path usable. These tests run with no OPENROUTER_API_KEY in
the environment, which is exactly the state ai.py treats identically to "AI off" —
so they also prove "AI on, but unconfigured" degrades to rules rather than crashing.
"""
import datetime as dt
import os

import pytest

from app import ai
from app.db import load_creators_from_csv
from app.extract import extract_fields
from app.models import Deliverable, Extraction
from app.reply import generate_reply
from app.score import assess

REF = dt.date(2026, 10, 19)
CREATORS = {c.id: c for c in load_creators_from_csv()}


@pytest.fixture(autouse=True)
def no_api_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    monkeypatch.delenv("OPENROUTER_VISION_MODEL", raising=False)


def test_extract_with_ai_returns_none_without_key():
    assert ai.extract_with_ai("some text", "subject", REF) is None


def test_infer_brand_category_ai_returns_none_without_key():
    assert ai.infer_brand_category_ai("SomeBrand", "context") is None


def test_judge_spam_ai_returns_none_without_key():
    assert ai.judge_spam_ai("some text", "example.com") is None


def test_write_reply_ai_returns_none_without_key():
    assert ai.write_reply_ai({"recommended_action": "decline"}) is None


def test_ocr_screenshot_ai_returns_none_without_key():
    assert ai.ocr_screenshot_ai("base64data") is None


def test_full_scoring_pipeline_works_with_ai_off():
    """Rules extraction -> scoring, end to end, no AI involved at all."""
    aanya = CREATORS["aanya_mehra"]
    ext = extract_fields(
        "We'd like 2 reels and 2 stories. Budget: ₹1,50,000. Go live date: 20 Nov 2026. "
        "Usage rights for 30 days. Payment terms: 50% advance, net 30.",
        "Collab — test brand", "test.com", REF,
    )
    a = assess(aanya, ext, REF, raw_text="irrelevant", sender_domain="test.com")
    assert a.type == "paid"
    assert a.final_score > 0


def test_reply_generation_falls_back_to_template_with_ai_on_but_unconfigured():
    aanya = CREATORS["aanya_mehra"]
    ext = Extraction(
        brand="TestBrand", brand_category="skincare", budget_amount=150000,
        deliverables=[Deliverable("reel", 2), Deliverable("story", 2)],
        go_live_date=dt.date(2026, 11, 20), usage_rights_days=30,
    )
    a = assess(aanya, ext, REF, raw_text="", sender_domain="test.com")
    # ai_on=True here, but no key configured — must not raise, must not return None/empty.
    reply = generate_reply(aanya, ext, a, ai_on=True)
    assert reply and isinstance(reply, str) and len(reply) > 10


def test_reply_generation_works_with_ai_off_for_every_action():
    aanya = CREATORS["aanya_mehra"]
    actions_and_flags = [
        ("accept_and_negotiate", [], 200000),
        ("counter_offer", [], 90000),
        ("decline", ["lowball"], 10000),
        ("ask_for_info", ["missing_info"], None),
        ("mark_spam", [], None),
    ]
    for action, flags, budget in actions_and_flags:
        ext = Extraction(
            brand="TestBrand", budget_amount=budget,
            deliverables=[Deliverable("reel", 1)],
        )
        from app.models import Assessment, QuoteBreakdown
        a = Assessment(
            type="spam" if action == "mark_spam" else "paid",
            flags=flags, recommended_action=action,
            reason="test", quote=QuoteBreakdown(
                base=100000, deliverable_count=1, bundle_discount_applied=False,
                bundle_discount_pct=0, after_discount=100000, usage_extra_blocks=0,
                usage_fee_pct=0, usage_fee_amount=0, whitelisting_fee_pct=0,
                whitelisting_fee_amount=0, exclusivity_fee_pct=0,
                exclusivity_fee_amount=0, total=100000,
            ),
            missing_fields=["go-live date"] if action == "ask_for_info" else [],
        )
        reply = generate_reply(aanya, ext, a, ai_on=False)
        assert reply and isinstance(reply, str)
