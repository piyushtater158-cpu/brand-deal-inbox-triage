"""Field extraction. AI path (ai.py) handles messy/Hinglish text with structured output;
this module is the rules fallback — regex for ₹/k/L/lakh amounts, Hinglish numerals,
dates, deliverable keywords — that keeps the app usable end to end with AI off.

Every extracted field gets a provenance entry so the UI can show the manager which
values came from where. Fields this function couldn't find are left None/default,
still marked provenance="rules" (a deliberate "rules looked and found nothing" is not
the same as "nobody looked").
"""
from __future__ import annotations

import datetime as dt
import re

from app.config_loader import load_config
from app.models import Deliverable, Extraction

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_HINGLISH_NUM = {"ek": 1, "do": 2, "teen": 3, "char": 4, "paanch": 5}

_DELIVERABLE_TYPE_MAP = {
    "reel": "reel", "reels": "reel",
    "story": "story", "stories": "story",
    "static post": "static_post", "static posts": "static_post",
    "post": "static_post", "posts": "static_post",
    "carousel": "carousel", "carousels": "carousel",
    "youtube integration": "youtube_integration",
    "youtube video": "youtube_integration", "youtube videos": "youtube_integration",
}

# A small festival-date lookup — the same spirit as the brand->category lookup:
# a rules fallback for a relative date phrase AI would otherwise resolve.
_FESTIVAL_DATES = {
    "diwali": dt.date(2026, 11, 8),
    "holi": dt.date(2027, 3, 3),
}

_GO_LIVE_ANCHORS = ["go live", "go-live", "launch on", "live by", "live on", "goes live"]
_DEADLINE_ANCHORS = [
    "respond by", "reply by", "response deadline", "let us know by",
    "revert by", "deadline", "revert at the earliest",
]

_MONEY_NUM = r"\d[\d,]*(?:\.\d+)?"  # must start with a digit — a bare comma isn't an amount
_MONEY_RE = re.compile(
    rf"(?:₹\s?|\brs\.?\s?|\binr\s?|\bbudget(?:\s*(?:is|hai|of|:))?\s*(?:₹|rs\.?|inr)?\s?)"
    rf"({_MONEY_NUM})\s?(k|l|lakh|lac|lakhs)?\b",
    re.IGNORECASE,
)
_PRODUCT_VALUE_RE = re.compile(
    rf"(?:product|package|hamper|kit)(?:\s+worth| value(?:d)? at)?\s*(?:₹|\brs\.?|\binr)?\s?"
    rf"({_MONEY_NUM})\s?(k|l|lakh|lac|lakhs)?\b",
    re.IGNORECASE,
)
_DELIVERABLE_RE = re.compile(
    r"(\d+|ek|do|teen|char|paanch)\s*(?:x\s*)?"
    r"(reels?|stories|story|static posts?|posts?|carousels?|youtube integrations?|youtube videos?)",
    re.IGNORECASE,
)
_MONTH_DATE_RE = re.compile(
    r"(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{4})",
    re.IGNORECASE,
)
_NUMERIC_DATE_RE = re.compile(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})")
_WITHIN_HOURS_RE = re.compile(r"within\s+(\d+)\s*hours?", re.IGNORECASE)
_WITHIN_DAYS_RE = re.compile(r"within\s+(\d+)\s*days?", re.IGNORECASE)
_USAGE_DAYS_RE = re.compile(r"usage\s*(?:rights?)?\s*(?:for|of)?\s*(\d+)\s*days?", re.IGNORECASE)
_PERPETUAL_RE = re.compile(r"perpetual|lifetime|unlimited\s+usage", re.IGNORECASE)
_WHITELIST_RE = re.compile(r"whitelist|paid ads?|dark post|boosted ads?", re.IGNORECASE)
_EXCLUSIVITY_RE = re.compile(r"exclusiv", re.IGNORECASE)
_EXCLUSIVITY_DAYS_RE = re.compile(r"exclusiv\w*\s*(?:for)?\s*(\d+)\s*days?", re.IGNORECASE)
_ADVANCE_RE = re.compile(r"(\d+)\s*%\s*advance", re.IGNORECASE)
_NO_ADVANCE_RE = re.compile(r"no advance|\b0%\s*advance|zero advance", re.IGNORECASE)
_NET_DAYS_RE = re.compile(r"net\s*[-]?\s*(\d+)", re.IGNORECASE)
_ON_BEHALF_RE = re.compile(r"on behalf of\s+([A-Z][\w&.\'\- ]{2,40})", re.IGNORECASE)
_BARTER_RE = re.compile(r"\bbarter\b|\bPR package\b", re.IGNORECASE)


def _to_amount(num_str: str, suffix: str | None) -> float:
    val = float(num_str.replace(",", ""))
    if suffix:
        s = suffix.lower()
        if s == "k":
            val *= 1_000
        elif s in ("l", "lakh", "lac", "lakhs"):
            val *= 100_000
    return val


def _parse_first_date(window: str) -> dt.date | None:
    m = _MONTH_DATE_RE.search(window)
    if m:
        day, mon, year = m.groups()
        month = _MONTHS[mon.lower()[:3]]
        return dt.date(int(year), month, int(day))
    m = _NUMERIC_DATE_RE.search(window)
    if m:
        day, month, year = m.groups()
        try:
            return dt.date(int(year), int(month), int(day))
        except ValueError:
            return None
    return None


def _find_anchored_date(text: str, anchors: list[str], allow_festival_fallback: bool = False) -> dt.date | None:
    low = text.lower()
    for anchor in anchors:
        idx = low.find(anchor)
        if idx == -1:
            continue
        window = text[idx:idx + 60]
        d = _parse_first_date(window)
        if d:
            return d
    if allow_festival_fallback:
        for name, date_val in _FESTIVAL_DATES.items():
            if name in low:
                return date_val
    return None


def _find_deliverables(text: str) -> list[Deliverable]:
    out: list[Deliverable] = []
    for m in _DELIVERABLE_RE.finditer(text):
        num_raw, type_raw = m.groups()
        if num_raw.lower() in _HINGLISH_NUM:
            count = _HINGLISH_NUM[num_raw.lower()]
        else:
            count = int(num_raw)
        # normalize plural forms explicitly rather than a blind rstrip("s")
        norm = type_raw.lower()
        if norm in _DELIVERABLE_TYPE_MAP:
            dtype = _DELIVERABLE_TYPE_MAP[norm]
        elif norm.rstrip("s") in _DELIVERABLE_TYPE_MAP:
            dtype = _DELIVERABLE_TYPE_MAP[norm.rstrip("s")]
        else:
            continue
        out.append(Deliverable(type=dtype, count=count))
    # merge duplicate types (e.g. "2 reels" mentioned twice) by summing counts
    merged: dict[str, int] = {}
    for d in out:
        merged[d.type] = merged.get(d.type, 0) + d.count
    return [Deliverable(type=t, count=c) for t, c in merged.items()]


_EDIT_TYPE_ALIASES = {
    "static": "static_post",
    "youtube": "youtube_integration", "yt": "youtube_integration",
}
_EDIT_ITEM_RE = re.compile(r"(\d+)\s*(?:[x×*]\s*)?([a-z_][a-z_ ]*)", re.IGNORECASE)


def parse_deliverables(value: str) -> list[Deliverable]:
    """A manager-typed deliverables list from the inquiry detail page, e.g.
    "2 × Reel, 3 × Story" (the format the page renders) or "1 reel + 2 stories".
    Stricter than _find_deliverables: anything unreadable raises ValueError instead of
    being silently dropped, because a dropped deliverable changes the quote.
    """
    merged: dict[str, int] = {}
    for item in re.split(r"[,+;\n]|\band\b", value or "", flags=re.IGNORECASE):
        item = item.strip()
        if not item:
            continue
        m = _EDIT_ITEM_RE.fullmatch(item)
        if not m:
            raise ValueError(f"Can't read deliverable '{item}' — use a count and a type, e.g. '2 × Reel'")
        count = int(m.group(1))
        name = " ".join(m.group(2).lower().replace("_", " ").split())
        dtype = (
            _DELIVERABLE_TYPE_MAP.get(name)
            or _DELIVERABLE_TYPE_MAP.get(name.rstrip("s"))
            or _EDIT_TYPE_ALIASES.get(name)
        )
        if dtype is None:
            raise ValueError(
                f"Unknown deliverable type '{m.group(2).strip()}' — "
                "use reel, story, static post, carousel or YouTube integration"
            )
        if count < 1:
            raise ValueError(f"Deliverable count must be at least 1, got {count}")
        merged[dtype] = merged.get(dtype, 0) + count
    return [Deliverable(type=t, count=c) for t, c in merged.items()]


def _detect_brand(text: str, subject: str) -> tuple[str | None, str | None]:
    """Brand + category via the config lookup — the brief's named AI-off fallback for
    brand-category inference, reused here to also *find* the brand name: a deliberate,
    controlled simplification for a demo where every seed brand is in the lookup.
    """
    cfg = load_config()
    lookup = cfg["brand_category_lookup"]
    haystack = f"{subject} {text}".lower()
    best: tuple[str, str] | None = None
    for brand, category in lookup.items():
        if brand in haystack:
            if best is None or len(brand) > len(best[0]):
                best = (brand, category)
    if best:
        # Title-case for display, but keep the original config key casing for anything
        # unusual (e.g. "nexacharge").
        display = best[0].title() if best[0].islower() else best[0]
        return display, best[1]
    return None, None


def category_vocabulary() -> list[str]:
    """Every category the engine can act on. Conflict and no-go checks are exact string
    matches, so an AI-supplied category outside this list would silently miss them."""
    cfg = load_config()
    cats = set(cfg["brand_category_lookup"].values()) | set(cfg["global_no_go_categories"])
    for k, v in cfg["category_adjacency"].items():
        cats.add(k)
        cats.update(v)
    return sorted(cats)


def needs_ai(ext: Extraction) -> bool:
    """AI is only asked about a message when the rules left a field the score depends on."""
    return (
        not ext.brand or not ext.brand_category or not ext.deliverables
        or (ext.budget_amount is None and ext.product_value is None)
        or ext.go_live_date is None or ext.usage_rights_days is None
    )


def fill_gaps(ext: Extraction, ai_fields: dict) -> Extraction:
    """Rules first: AI values land only where the rules found nothing, marked 'ai'."""
    for name, value in ai_fields.items():
        if name == "brand_category":
            continue
        current = getattr(ext, name)
        if current is None or current == []:
            if name == "deliverables":
                value = [Deliverable(type=d["type"], count=d["count"]) for d in value]
            setattr(ext, name, value)
            ext.provenance[name] = "ai"
    if not ext.brand_category:
        lookup = load_config()["brand_category_lookup"]
        if ext.brand and ext.brand.lower() in lookup:
            ext.brand_category = lookup[ext.brand.lower()]
            ext.provenance["brand_category"] = ext.provenance.get("brand", "rules")
        elif ai_fields.get("brand_category"):
            ext.brand_category = ai_fields["brand_category"]
            ext.provenance["brand_category"] = "ai"
    if ext.budget_type in ("not_stated", "negotiable"):
        if ext.budget_amount is not None:
            ext.budget_type = "fixed"
            ext.provenance["budget_type"] = ext.provenance["budget_amount"]
        elif ext.product_value is not None:
            ext.budget_type = "barter"
            ext.provenance["budget_type"] = ext.provenance["product_value"]
    return ext


def extract_fields(raw_text: str, subject: str, sender_domain: str, reference_date: dt.date) -> Extraction:
    brand, brand_category = _detect_brand(raw_text, subject)

    agency_match = _ON_BEHALF_RE.search(raw_text)
    agency_or_direct = "agency" if agency_match else "direct"

    product_value = None
    m = _PRODUCT_VALUE_RE.search(raw_text)
    if m:
        product_value = _to_amount(m.group(1), m.group(2))

    budget_amount = None
    for m in _MONEY_RE.finditer(raw_text):
        # Skip a match that's actually the product-value sentence, to avoid double count.
        start = m.start()
        window_before = raw_text[max(0, start - 20):start].lower()
        if any(w in window_before for w in ("product", "package", "hamper", "kit")):
            continue
        budget_amount = _to_amount(m.group(1), m.group(2))
        break

    is_barter_phrase = bool(_BARTER_RE.search(raw_text))
    if is_barter_phrase and budget_amount is not None and product_value is None:
        # "PR package" phrasing sometimes puts the value where budget_amount landed.
        product_value, budget_amount = budget_amount, None

    budget_type = "fixed" if budget_amount is not None else (
        "barter" if (product_value is not None or is_barter_phrase) else
        ("negotiable" if "negotiable" in raw_text.lower() else "not_stated")
    )

    deliverables = _find_deliverables(raw_text)

    go_live_date = _find_anchored_date(raw_text, _GO_LIVE_ANCHORS, allow_festival_fallback=True)
    response_deadline = _find_anchored_date(raw_text, _DEADLINE_ANCHORS)

    if response_deadline is None:
        m = _WITHIN_HOURS_RE.search(raw_text)
        if m:
            response_deadline = reference_date + dt.timedelta(hours=int(m.group(1)))
        else:
            m = _WITHIN_DAYS_RE.search(raw_text)
            if m:
                response_deadline = reference_date + dt.timedelta(days=int(m.group(1)))

    usage_rights_days = None
    if _PERPETUAL_RE.search(raw_text):
        usage_rights_days = 36_500  # ~100 years: the engine's representation of "perpetual"
    else:
        m = _USAGE_DAYS_RE.search(raw_text)
        if m:
            usage_rights_days = int(m.group(1))

    whitelisting = bool(_WHITELIST_RE.search(raw_text))

    exclusivity_requested = bool(_EXCLUSIVITY_RE.search(raw_text))
    exclusivity_requested_days = None
    m = _EXCLUSIVITY_DAYS_RE.search(raw_text)
    if m:
        exclusivity_requested_days = int(m.group(1))

    payment_advance_pct = None
    if _NO_ADVANCE_RE.search(raw_text):
        payment_advance_pct = 0
    else:
        m = _ADVANCE_RE.search(raw_text)
        if m:
            payment_advance_pct = int(m.group(1))

    payment_net_days = None
    m = _NET_DAYS_RE.search(raw_text)
    if m:
        payment_net_days = int(m.group(1))

    fields = [
        "brand", "brand_category", "agency_or_direct", "budget_amount", "budget_type",
        "product_value", "deliverables", "go_live_date", "response_deadline",
        "usage_rights_days", "exclusivity_requested", "whitelisting",
        "payment_advance_pct", "payment_net_days",
    ]
    provenance = {f: "rules" for f in fields}

    return Extraction(
        brand=brand,
        brand_category=brand_category,
        agency_or_direct=agency_or_direct,
        budget_amount=budget_amount,
        budget_type=budget_type,
        product_value=product_value,
        deliverables=deliverables,
        go_live_date=go_live_date,
        response_deadline=response_deadline,
        usage_rights_days=usage_rights_days,
        exclusivity_requested=exclusivity_requested,
        exclusivity_requested_days=exclusivity_requested_days,
        whitelisting=whitelisting,
        payment_advance_pct=payment_advance_pct,
        payment_net_days=payment_net_days,
        provenance=provenance,
    )
