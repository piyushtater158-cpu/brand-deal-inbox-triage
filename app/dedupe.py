"""Duplicate detection (Premise 8): same brand + creator within 14 days across email
or DM merges into one thread, keyed on the earliest message, flags unioned, and the
most-complete extraction wins as canonical.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.config_loader import load_config
from app.models import Extraction, RawMessage


def thread_key(creator_id: str, brand: str | None) -> str:
    normalized = (brand or "unknown").strip().lower()
    return f"{creator_id}::{normalized}"


def _populated_count(ext: Extraction) -> int:
    return sum(
        1
        for v in (
            ext.budget_amount, ext.product_value, ext.deliverables,
            ext.go_live_date, ext.response_deadline, ext.usage_rights_days,
            ext.payment_advance_pct, ext.payment_net_days,
        )
        if v
    )


@dataclass
class MergedInquiry:
    messages: list[RawMessage]
    extraction: Extraction
    is_duplicate: bool


def merge_duplicates(items: list[tuple[RawMessage, Extraction]]) -> list[MergedInquiry]:
    window_days = load_config()["duplicate_window_days"]

    groups: dict[str, list[tuple[RawMessage, Extraction]]] = {}
    for msg, ext in items:
        if ext.brand:
            key = thread_key(msg.creator_id, ext.brand)
        else:
            # Unknown brand can't be confidently matched to another unknown-brand
            # message — "same brand" requires a brand. Each gets its own singleton
            # group instead of colliding with every other unidentified message.
            key = f"{msg.creator_id}::unknown::{msg.id}"
        groups.setdefault(key, []).append((msg, ext))

    out: list[MergedInquiry] = []
    for key, pairs in groups.items():
        pairs.sort(key=lambda p: p[0].received_at)
        cluster: list[tuple[RawMessage, Extraction]] = [pairs[0]]
        for prev, cur in zip(pairs, pairs[1:]):
            gap_days = (cur[0].received_at.date() - prev[0].received_at.date()).days
            if gap_days <= window_days:
                cluster.append(cur)
            else:
                out.append(_finalize_cluster(cluster))
                cluster = [cur]
        out.append(_finalize_cluster(cluster))
    return out


def _finalize_cluster(cluster: list[tuple[RawMessage, Extraction]]) -> MergedInquiry:
    messages = [m for m, _ in cluster]
    # Canonical extraction: most fields populated; ties go to the earliest message.
    best_ext = max(
        (e for _, e in cluster),
        key=lambda e: _populated_count(e),
    )
    return MergedInquiry(messages=messages, extraction=best_ext, is_duplicate=len(cluster) > 1)
