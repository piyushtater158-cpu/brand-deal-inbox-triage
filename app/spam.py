"""Hard-pattern spam/scam detection — the AI-off path for the 'ambiguous spam' task.
Everything here is a literal pattern match against config.yaml's spam_patterns, so it
runs identically whether AI is on or off; AI only gets involved for genuinely
borderline cases this module doesn't already resolve (see ai.py).
"""
from __future__ import annotations

from app.config_loader import load_config


def _edit_distance(a: str, b: str) -> int:
    """Plain Levenshtein distance — no dependency needed for domains this short."""
    if a == b:
        return 0
    m, n = len(a), len(b)
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        cur = [i] + [0] * n
        for j in range(1, n + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[n]


def detect_spam(
    raw_text: str,
    sender_domain: str,
    brand: str | None,
) -> tuple[bool, bool, list[str]]:
    """Returns (is_spam, is_suspicious_sender, reasons).

    is_spam -> hard scam pattern (pay-to-join, crypto/forex, shortened link, lookalike
    domain): type becomes "spam", score 0, regardless of anything else.
    is_suspicious_sender -> softer signal (free mail wearing a big brand's name) that
    adds the suspicious_sender flag and its risk_penalty without forcing type=spam.
    """
    cfg = load_config()["spam_patterns"]
    text = raw_text.lower()
    reasons: list[str] = []
    is_spam = False

    for phrase in cfg["pay_to_join_phrases"]:
        if phrase in text:
            is_spam = True
            reasons.append(f'contains "{phrase}"')
            break

    for term in cfg["crypto_forex_terms"]:
        if term.lower() in text:
            is_spam = True
            reasons.append(f'mentions "{term}"')
            break

    for domain in cfg["shortened_link_domains"]:
        if domain in text:
            is_spam = True
            reasons.append(f"contains a shortened link ({domain})")
            break

    sender_domain_l = (sender_domain or "").lower()
    is_suspicious_sender = False
    for known_brand, real_domain in cfg["known_brand_domains"].items():
        if sender_domain_l and sender_domain_l != real_domain:
            dist = _edit_distance(sender_domain_l, real_domain.lower())
            if 0 < dist <= cfg["lookalike_domain_max_edit_distance"]:
                is_spam = True
                reasons.append(
                    f'sender domain "{sender_domain}" looks like a lookalike of {real_domain}'
                )

    if brand:
        brand_l = brand.lower()
        free_mail = sender_domain_l in [d.lower() for d in cfg["free_mail_domains"]]
        big_brand_claim = any(
            kb in brand_l or brand_l in kb for kb in load_config()["known_brands"]
        )
        if free_mail and big_brand_claim:
            is_suspicious_sender = True
            reasons.append(
                f'claims to be "{brand}" but sends from a free mail domain ({sender_domain})'
            )

    return is_spam, is_suspicious_sender, reasons
