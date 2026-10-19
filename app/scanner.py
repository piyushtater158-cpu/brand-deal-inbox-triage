"""The inbox scanner sits behind one interface so a real mailbox can be plugged in
later (see README: 'plugging in a real inbox'). Keyword filtering happens in the
pipeline, after fetch(), so it applies identically no matter which scanner is
installed — SampleFolderScanner today, an IMAP/Gmail-API scanner tomorrow.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Protocol

from app.config_loader import load_config
from app.models import Creator, RawMessage

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"


class InboxScanner(Protocol):
    def fetch(self, creator: Creator) -> list[RawMessage]:
        """Return every raw message for this creator, matching or not — keyword
        filtering is the pipeline's job, not the scanner's. A real implementation
        (IMAP, Gmail API, Meta DM export) only needs to fill these same fields:
        id, creator_id, source, received_at, sender_name, sender_email_or_handle,
        sender_domain, subject, raw_text.
        """
        ...


class SampleFolderScanner:
    """MVP scanner: reads seed/demo_inbox.json. Swap this one class (and the
    config line that selects it) for a real mailbox — nothing else in the
    pipeline needs to change.
    """

    def __init__(self, path: Path | None = None):
        self.path = path or (SEED_DIR / "demo_inbox.json")
        self._all: list[RawMessage] | None = None

    def _load_all(self) -> list[RawMessage]:
        if self._all is None:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
            messages = []
            for item in raw:
                messages.append(
                    RawMessage(
                        id=item["id"],
                        creator_id=item["creator_id"],
                        source=item["source"],
                        received_at=dt.datetime.fromisoformat(item["received_at"]),
                        sender_name=item.get("sender_name", ""),
                        sender_email_or_handle=item.get("sender_email_or_handle", ""),
                        sender_domain=item.get("sender_domain", ""),
                        subject=item.get("subject", ""),
                        raw_text=item["raw_text"],
                    )
                )
            self._all = messages
        return self._all

    def fetch(self, creator: Creator) -> list[RawMessage]:
        return [m for m in self._load_all() if m.creator_id == creator.id]

    def fetch_all_creators(self, creators: list[Creator]) -> list[RawMessage]:
        out: list[RawMessage] = []
        for c in creators:
            out.extend(self.fetch(c))
        return out


def matches_keywords(message: RawMessage, keywords: list[str]) -> str | None:
    """Returns the matched keyword, or None if no keyword matched."""
    haystack = f"{message.subject} {message.raw_text}".lower()
    for kw in keywords:
        if kw.lower() in haystack:
            return kw
    return None


def filter_by_keywords(
    messages: list[RawMessage],
) -> tuple[list[RawMessage], list[tuple[RawMessage, str]]]:
    """Returns (matching, skipped) where skipped is [(message, reason), ...]."""
    keywords = load_config()["keywords"]
    matching: list[RawMessage] = []
    skipped: list[tuple[RawMessage, str]] = []
    for m in messages:
        hit = matches_keywords(m, keywords)
        if hit:
            matching.append(m)
        else:
            skipped.append((m, "no brand keywords matched"))
    return matching, skipped
