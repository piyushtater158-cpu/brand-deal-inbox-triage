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
    assert ai.extract_with_ai("some text", "subject", REF, ["skincare"]) is None


def test_only_free_models_are_ever_requested(monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODEL", "openai/gpt-5, minimax/minimax-m3.1-flash:free, openrouter/auto")
    assert ai._models("text") == ["minimax/minimax-m3.1-flash:free"]


def test_a_model_specific_403_does_not_pause_ai(monkeypatch):
    monkeypatch.setitem(ai._pause, "until", 0.0)
    ai._handle_error(403, '{"message": "this model is only available on agentic harnesses"}')
    assert ai._pause["until"] == 0.0
    ai._handle_error(401, '{"message": "User not found."}')
    assert ai._pause["until"] > 0
    monkeypatch.setitem(ai._pause, "until", 0.0)


@pytest.mark.parametrize("env_value, expected", [(None, False), ("true", True), ("0", False)])
def test_fresh_database_seeds_ai_toggle_from_env(tmp_path, monkeypatch, env_value, expected):
    from app import db

    monkeypatch.setenv("DB_PATH", str(tmp_path / "app.db"))
    if env_value is None:
        monkeypatch.delenv("AI_ENABLED_DEFAULT", raising=False)
    else:
        monkeypatch.setenv("AI_ENABLED_DEFAULT", env_value)
    with db.get_conn() as conn:
        db.init_schema(conn)
        assert db.ai_enabled(conn) is expected


def test_boot_scan_is_rules_only_even_with_ai_on(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("AI_ENABLED_DEFAULT", "true")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(ai.httpx, "post", lambda *a, **k: pytest.fail("boot scan called the API"))
    from app.main import app

    with TestClient(app) as client:
        page = client.get("/").text
        assert "AI ON" in page
        assert len(client.get("/api/debug").json()["inquiries"]) == 29


def test_ai_fills_only_gaps_and_only_with_known_categories():
    """Rules values always win; an AI category outside the config vocabulary is dropped,
    because conflict and no-go checks are exact matches."""
    from app.extract import category_vocabulary, fill_gaps

    rules = extract_fields(
        "hi, ek reel aur do stories chahiye. budget 40k hai.", "", "instagram.com", REF,
    )
    assert rules.brand is None and rules.go_live_date is None
    ai_fields = ai._clean_extraction({
        "brand": "Plum Goodness", "brand_category": "Ayurveda",
        "budget_amount": 99999, "go_live_date": "2026-11-08",
        "deliverables": [{"type": "reels", "count": 4}],
    }, category_vocabulary())
    assert "brand_category" not in ai_fields and "deliverables" not in ai_fields

    ext = fill_gaps(rules, ai_fields)
    assert ext.budget_amount == 40000 and ext.provenance["budget_amount"] == "rules"
    assert ext.brand == "Plum Goodness" and ext.provenance["brand"] == "ai"
    assert ext.go_live_date == dt.date(2026, 11, 8) and ext.provenance["go_live_date"] == "ai"
    assert ext.brand_category is None


def test_ai_brand_resolves_category_through_the_lookup_first():
    from app.extract import category_vocabulary, fill_gaps

    rules = extract_fields("2 reels, budget ₹1,50,000", "", "x.in", REF)
    ext = fill_gaps(rules, ai._clean_extraction(
        {"brand": "Nivara Soaps", "brand_category": "skincare"}, category_vocabulary()))
    assert ext.brand_category == "personal care"


def test_page_render_never_waits_on_a_model(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(ai.httpx, "post", lambda *a, **k: pytest.fail("page render called the API"))
    from app.reply import draft_for_page

    aanya = CREATORS["aanya_mehra"]
    ext = Extraction(brand="TestBrand", budget_amount=150000, deliverables=[Deliverable("reel", 1)])
    a = assess(aanya, ext, REF, raw_text="", sender_domain="test.com")
    text, source = draft_for_page(aanya, ext, a, ai_on=True)
    assert source == "template" and text


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
