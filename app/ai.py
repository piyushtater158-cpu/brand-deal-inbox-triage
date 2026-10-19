"""The single AI-calling module (Premise 10), with a genuine deterministic fallback for
every task. AI never creates or suppresses a flag and never changes a score (score.py
doesn't import this module at all) — it only fills Extraction fields the rules left
empty and writes reply language, both always shown as editable, never final.

Only free OpenRouter models are ever called: the model lists come from config.yaml
(or a comma-separated OPENROUTER_MODEL / OPENROUTER_VISION_MODEL override) and anything
that isn't a ':free' model is dropped before a request is built. OpenRouter accepts at
most 3 models per request and falls through them on provider errors; a chunk that
errors out or returns unusable output moves on to the next chunk.

Free models are slow, flaky and quota-limited, so every successful answer is cached
in SQLite (keyed by task + prompt) and a rate-limit response pauses AI for a while
instead of making every later click wait on a request that will fail. If
OPENROUTER_API_KEY isn't set, every call returns None immediately and the caller falls
back to rules — "AI on" with no key is indistinguishable from "AI off" to the engine.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import threading
import time

import httpx

from app import db
from app.config_loader import load_config

_API_URL = "https://openrouter.ai/api/v1/chat/completions"
_MAX_MODELS_PER_REQUEST = 3
DELIVERABLE_TYPES = ("reel", "story", "static_post", "carousel", "youtube_integration")

_lock = threading.Lock()
_pause = {"until": 0.0, "reason": ""}


def is_free_model(model: str) -> bool:
    return model.endswith(":free")


def _models(kind: str) -> list[str]:
    cfg = load_config()["ai"]
    override = os.environ.get(cfg["model_env_var" if kind == "text" else "vision_model_env_var"], "")
    configured = [m.strip() for m in override.split(",") if m.strip()] or cfg.get(f"{kind}_models", [])
    return [m for m in configured if is_free_model(m)]


def _api_key() -> str | None:
    return os.environ.get(load_config()["ai"]["api_key_env_var"]) or None


def _pause_for(seconds: float, reason: str) -> None:
    with _lock:
        _pause["until"] = max(_pause["until"], time.time() + seconds)
        _pause["reason"] = reason


def _seconds_to_utc_midnight() -> float:
    now = dt.datetime.now(dt.timezone.utc)
    tomorrow = (now + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return (tomorrow - now).total_seconds()


def status() -> dict:
    """What the chrome shows next to the AI toggle."""
    if not _api_key() or not _models("text"):
        return {"configured": False, "available": False,
                "note": "No AI key configured — rules are doing everything."}
    with _lock:
        remaining = _pause["until"] - time.time()
        reason = _pause["reason"]
    if remaining > 0:
        when = f"{int(remaining // 60) + 1} min" if remaining < 3600 else "00:00 UTC"
        return {"configured": True, "available": False,
                "note": f"{reason} AI paused until {when}; rules are covering."}
    return {"configured": True, "available": True, "note": ""}


def _cache_key(task: str, *parts: str) -> str:
    h = hashlib.sha256(task.encode())
    for p in parts:
        h.update(b"\x00" + p.encode())
    return f"{task}:{h.hexdigest()}"


def _parse_json(content: str) -> dict | None:
    text = (content or "").strip()
    start = text.find("{")
    if start == -1:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def _handle_error(status_code: int, message: str) -> None:
    """Account-level limits pause AI; an upstream provider's 429 only skips that chunk."""
    low = message.lower()
    if status_code == 429 and "upstream" in low:
        return
    if status_code == 429 and ("per-day" in low or "per day" in low or "daily" in low):
        _pause_for(_seconds_to_utc_midnight(), "Free-model daily limit reached.")
    elif status_code == 429:
        _pause_for(60, "Free-model rate limit hit.")
    elif status_code in (401, 403):
        _pause_for(3600, "The AI key was rejected.")
    elif status_code == 402:
        _pause_for(3600, "OpenRouter refused the request (credits).")


def _request(messages: list, kind: str, timeout: float, json_mode: bool) -> str | None:
    """POST through each chunk of up to 3 free models until one returns content."""
    api_key, models = _api_key(), _models(kind)
    if not api_key or not models:
        return None
    deadline = time.time() + timeout
    for i in range(0, len(models), _MAX_MODELS_PER_REQUEST):
        if status()["available"] is False or time.time() >= deadline:
            return None
        chunk = models[i:i + _MAX_MODELS_PER_REQUEST]
        body = {"models": chunk, "messages": messages, "temperature": 0.2}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            resp = httpx.post(
                _API_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
                         "X-Title": "Deal Desk (Kalakaaar triage demo)"},
                json=body, timeout=max(5.0, deadline - time.time()),
            )
        except httpx.HTTPError:
            continue
        try:
            data = resp.json()
        except ValueError:
            _handle_error(resp.status_code, resp.text[:500])
            continue
        error = data.get("error") if isinstance(data, dict) else None
        if resp.status_code != 200 or error:
            code = (error or {}).get("code", resp.status_code)
            message = json.dumps(error or {})
            _handle_error(int(code) if str(code).isdigit() else resp.status_code, message)
            continue
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            continue
        if content and content.strip():
            if not json_mode or _parse_json(content) is not None:
                return content
    return None


def _call_json(task: str, system: str, user: str, *, cached_only: bool = False) -> dict | None:
    key = _cache_key(task, system, user)
    cached = db.ai_cache_get(key)
    if cached is not None:
        return json.loads(cached)
    if cached_only:
        return None
    timeout = float(load_config()["ai"].get("timeout_seconds", 30))
    content = _request(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "text", timeout, json_mode=True,
    )
    data = _parse_json(content) if content else None
    if data is not None:
        db.ai_cache_put(key, json.dumps(data))
    return data


# ---------------------------------------------------------------------------------
# Extraction: fills only what the rules left empty, and only with values that pass
# the same shape checks a manager edit would.
# ---------------------------------------------------------------------------------

def _number(v, lo: float, hi: float) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, str):
        v = v.replace(",", "").replace("₹", "").strip()
        try:
            v = float(v)
        except ValueError:
            return None
    if isinstance(v, (int, float)) and lo <= v <= hi:
        return float(v)
    return None


def _date(v) -> dt.date | None:
    if not isinstance(v, str):
        return None
    try:
        return dt.date.fromisoformat(v.strip()[:10])
    except ValueError:
        return None


def _clean_extraction(data: dict, categories: list[str]) -> dict:
    out: dict = {}
    brand = data.get("brand")
    if isinstance(brand, str) and 1 < len(brand.strip()) <= 80:
        out["brand"] = brand.strip()
    cat = data.get("brand_category")
    if isinstance(cat, str) and cat.strip().lower() in categories:
        out["brand_category"] = cat.strip().lower()
    for field in ("budget_amount", "product_value"):
        v = _number(data.get(field), 1, 10_00_00_000)
        if v is not None:
            out[field] = v
    items = data.get("deliverables")
    if isinstance(items, list):
        merged: dict[str, int] = {}
        for d in items:
            if not isinstance(d, dict) or d.get("type") not in DELIVERABLE_TYPES:
                continue
            n = _number(d.get("count"), 1, 50)
            if n is not None:
                merged[d["type"]] = merged.get(d["type"], 0) + int(n)
        if merged:
            out["deliverables"] = [{"type": t, "count": c} for t, c in merged.items()]
    for field in ("go_live_date", "response_deadline"):
        d = _date(data.get(field))
        if d is not None:
            out[field] = d
    for field, lo, hi in (("usage_rights_days", 1, 36_500), ("payment_advance_pct", 0, 100),
                          ("payment_net_days", 0, 365)):
        v = _number(data.get(field), lo, hi)
        if v is not None:
            out[field] = int(v) if field != "payment_advance_pct" else v
    return out


def extract_with_ai(raw_text: str, subject: str, reference_date: dt.date,
                    categories: list[str]) -> dict | None:
    """Validated partial fields, or None. brand_category is restricted to the config's
    category vocabulary, because conflict and no-go checks are exact matches."""
    system = (
        "Extract brand-deal fields from a creator's inbound message (often Hinglish). "
        "Reply with a single JSON object with exactly these keys: brand (string|null), "
        f"brand_category (one of: {', '.join(categories)}; or null if none fits), "
        "budget_amount (number|null, cash offered in INR — '40k' is 40000, '1.5 lakh' is 150000), "
        "product_value (number|null, INR value of free product for barter), "
        "deliverables (array of {type: 'reel'|'story'|'static_post'|'carousel'|"
        "'youtube_integration', count: int}), go_live_date (YYYY-MM-DD|null), "
        "response_deadline (YYYY-MM-DD|null), usage_rights_days (int|null), "
        "payment_advance_pct (number 0-100|null), payment_net_days (int|null). "
        "Use null for anything the message doesn't say; never guess. "
        f"Today's reference date is {reference_date.isoformat()} for resolving relative dates "
        "(Diwali 2026 is 2026-11-08)."
    )
    data = _call_json("extract", system, f"Subject: {subject}\n\nMessage:\n{raw_text}")
    if not data:
        return None
    cleaned = _clean_extraction(data, categories)
    return cleaned or None


def infer_brand_category_ai(brand: str, context: str) -> str | None:
    system = (
        "Classify the brand's category in one or two words (e.g. 'personal care', "
        "'nutrition', 'betting', 'crypto', 'travel'). Reply with JSON {\"category\": \"...\"}."
    )
    data = _call_json("category", system, f"Brand: {brand}\nContext: {context}")
    return data.get("category") if data else None


def judge_spam_ai(raw_text: str, sender_domain: str) -> bool | None:
    system = (
        "Judge whether this inbound message to a creator is a scam/spam brand-deal "
        "pitch (not a legitimate offer). Reply with JSON {\"is_spam\": true|false, "
        "\"reason\": \"...\"}."
    )
    data = _call_json("spam", system, f"Sender domain: {sender_domain}\n\nMessage:\n{raw_text}")
    return data.get("is_spam") if data else None


def write_reply_ai(context: dict, *, cached_only: bool = False) -> str | None:
    system = (
        "You write replies for an Indian talent agency to brands that pitched one of its "
        "creators. Write a short, warm, professional email body (under 140 words) that "
        "carries out recommended_action. Use only the facts and amounts given — never "
        "invent numbers, dates or terms, and write amounts exactly as given (Indian "
        "format, e.g. ₹2,64,330). Sign off as \"<creator first name>'s team\". "
        "Reply with JSON {\"reply\": \"...\"} containing only the message body."
    )
    data = _call_json("reply", system, json.dumps(context, ensure_ascii=False, sort_keys=True),
                      cached_only=cached_only)
    reply = data.get("reply") if data else None
    if isinstance(reply, str) and 20 <= len(reply.strip()) <= 3000:
        return reply.strip()
    return None


def ocr_screenshot_ai(image_b64: str, mime: str = "image/png") -> str | None:
    """Vision transcription of an Instagram DM screenshot, through free vision models."""
    key = _cache_key("ocr", image_b64)
    cached = db.ai_cache_get(key)
    if cached is not None:
        return json.loads(cached)
    timeout = float(load_config()["ai"].get("vision_timeout_seconds", 45))
    content = _request(
        [{"role": "user", "content": [
            {"type": "text", "text": "Transcribe all text visible in this Instagram DM screenshot, "
                                     "verbatim, keeping line breaks. Output only the transcription."},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
        ]}],
        "vision", timeout, json_mode=False,
    )
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
    if not text:
        return None
    db.ai_cache_put(key, json.dumps(text))
    return text
