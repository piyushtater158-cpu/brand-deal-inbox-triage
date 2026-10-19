"""The single AI-calling function (Premise 10), behind OPENROUTER_MODEL, with one
retry and a genuine deterministic fallback for every task. AI never creates or
suppresses a flag and never changes a score (score.py doesn't import this module at
all) — it only fills Extraction fields and writes reply language, both always shown
as editable, never final.

If OPENROUTER_API_KEY / OPENROUTER_MODEL aren't set, every call below returns None
immediately and the caller falls back to rules — "AI on" with no key configured is
indistinguishable from "AI off" from the engine's point of view, which is the point:
nothing breaks either way.
"""
from __future__ import annotations

import datetime as dt
import json
import os

import httpx

from app.config_loader import load_config
from app.models import Deliverable, Extraction

_API_URL = "https://openrouter.ai/api/v1/chat/completions"


def _configured() -> tuple[str | None, str | None]:
    cfg = load_config()["ai"]
    api_key = os.environ.get(cfg["api_key_env_var"])
    model = os.environ.get(cfg["model_env_var"])
    return api_key, model


def _call(system_prompt: str, user_prompt: str, model: str | None = None) -> dict | None:
    api_key, configured_model = _configured()
    model = model or configured_model
    if not api_key or not model:
        return None
    cfg = load_config()["ai"]
    retries = cfg["max_retries"]
    last_error = None
    for _ in range(retries + 1):
        try:
            resp = httpx.post(
                _API_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.2,
                },
                timeout=20.0,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return json.loads(content)
        except Exception as e:  # noqa: BLE001 — any failure here just means "fall back"
            last_error = e
            continue
    if last_error:
        return None
    return None


def extract_with_ai(raw_text: str, subject: str, reference_date: dt.date) -> Extraction | None:
    system = (
        "Extract brand-deal fields from a creator's inbound message (often Hinglish). "
        "Reply with a single JSON object with exactly these keys: brand (string|null), "
        "brand_category (string|null), agency_or_direct ('direct'|'agency'), "
        "budget_amount (number|null, in INR), product_value (number|null, in INR), "
        "deliverables (array of {type: 'reel'|'story'|'static_post'|'carousel'|"
        "'youtube_integration', count: int}), go_live_date (YYYY-MM-DD|null), "
        "response_deadline (YYYY-MM-DD|null), usage_rights_days (int|null), "
        "exclusivity_requested (bool), whitelisting (bool), "
        "payment_advance_pct (number 0-100|null), payment_net_days (int|null). "
        f"Today's reference date is {reference_date.isoformat()} for resolving relative dates."
    )
    user = f"Subject: {subject}\n\nMessage:\n{raw_text}"
    data = _call(system, user)
    if not data:
        return None
    try:
        deliverables = [Deliverable(type=d["type"], count=int(d["count"])) for d in data.get("deliverables", [])]
        fields = [
            "brand", "brand_category", "agency_or_direct", "budget_amount", "budget_type",
            "product_value", "deliverables", "go_live_date", "response_deadline",
            "usage_rights_days", "exclusivity_requested", "whitelisting",
            "payment_advance_pct", "payment_net_days",
        ]
        return Extraction(
            brand=data.get("brand"),
            brand_category=data.get("brand_category"),
            agency_or_direct=data.get("agency_or_direct", "direct"),
            budget_amount=data.get("budget_amount"),
            budget_type="fixed" if data.get("budget_amount") else (
                "barter" if data.get("product_value") else "not_stated"
            ),
            product_value=data.get("product_value"),
            deliverables=deliverables,
            go_live_date=dt.date.fromisoformat(data["go_live_date"]) if data.get("go_live_date") else None,
            response_deadline=dt.date.fromisoformat(data["response_deadline"]) if data.get("response_deadline") else None,
            usage_rights_days=data.get("usage_rights_days"),
            exclusivity_requested=bool(data.get("exclusivity_requested")),
            whitelisting=bool(data.get("whitelisting")),
            payment_advance_pct=data.get("payment_advance_pct"),
            payment_net_days=data.get("payment_net_days"),
            provenance={f: "ai" for f in fields},
        )
    except Exception:  # noqa: BLE001 — malformed AI output -> fall back, never crash
        return None


def infer_brand_category_ai(brand: str, context: str) -> str | None:
    system = (
        "Classify the brand's category in one or two words (e.g. 'personal care', "
        "'nutrition', 'betting', 'crypto', 'travel'). Reply with JSON {\"category\": \"...\"}."
    )
    data = _call(system, f"Brand: {brand}\nContext: {context}")
    return data.get("category") if data else None


def judge_spam_ai(raw_text: str, sender_domain: str) -> bool | None:
    system = (
        "Judge whether this inbound message to a creator is a scam/spam brand-deal "
        "pitch (not a legitimate offer). Reply with JSON {\"is_spam\": true|false, "
        "\"reason\": \"...\"}."
    )
    data = _call(system, f"Sender domain: {sender_domain}\n\nMessage:\n{raw_text}")
    return data.get("is_spam") if data else None


def write_reply_ai(context: dict) -> str | None:
    system = (
        "Write a short, warm, professional reply from a talent agency to a brand, in "
        "the voice given by the recommended_action and quote context. Reply with JSON "
        "{\"reply\": \"...\"} containing only the message body."
    )
    data = _call(system, json.dumps(context))
    return data.get("reply") if data else None


def ocr_screenshot_ai(image_b64: str) -> str | None:
    """Vision OCR for Instagram DM screenshots. Disabled in the MVP per the brief
    ('with AI off, text paste only') — this stub keeps the interface honest for when
    a vision-capable OPENROUTER_VISION_MODEL is wired in.
    """
    cfg = load_config()["ai"]
    api_key = os.environ.get(cfg["api_key_env_var"])
    vision_model = os.environ.get(cfg["vision_model_env_var"])
    if not api_key or not vision_model:
        return None
    try:
        resp = httpx.post(
            _API_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": vision_model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Transcribe all text visible in this Instagram DM screenshot, verbatim."},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                        ],
                    }
                ],
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception:  # noqa: BLE001
        return None
