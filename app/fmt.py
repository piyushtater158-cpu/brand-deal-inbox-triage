"""Display formatting shared by templates, reply drafts and score reasons. Indian digit
grouping everywhere — ₹2,64,330 and 1,82,400 — because that's the first thing an Indian
agency notices when it's wrong.
"""
from __future__ import annotations

import datetime as dt


def group_in(n: float | int) -> str:
    """1823400 -> '18,23,400': last three digits, then pairs."""
    value = int(round(n))
    sign = "-" if value < 0 else ""
    s = str(abs(value))
    if len(s) <= 3:
        return sign + s
    head, last3 = s[:-3], s[-3:]
    pairs = []
    while len(head) > 2:
        pairs.insert(0, head[-2:])
        head = head[:-2]
    if head:
        pairs.insert(0, head)
    return sign + ",".join(pairs + [last3])


def inr(amount: float | int | None, none: str = "—") -> str:
    if amount is None:
        return none
    if amount < 0:
        return "−₹" + group_in(-amount)
    return "₹" + group_in(amount)


def _as_datetime(value) -> dt.datetime | dt.date | None:
    if value is None or value == "":
        return None
    if isinstance(value, (dt.date, dt.datetime)):
        return value
    return dt.datetime.fromisoformat(str(value))


def date_long(value) -> str:
    """'17 Oct 2026'."""
    d = _as_datetime(value)
    return f"{d.day} {d:%b %Y}" if d else "—"


def date_short(value) -> str:
    """'8 Nov'."""
    d = _as_datetime(value)
    return f"{d.day} {d:%b}" if d else "—"


def datetime_long(value) -> str:
    """'17 Oct 2026, 11:42'."""
    d = _as_datetime(value)
    if d is None:
        return "—"
    if not isinstance(d, dt.datetime):
        return date_long(d)
    return f"{d.day} {d:%b %Y, %H:%M}"
