"""Single source of truth for every tunable in the engine.

Nothing in extract.py / quote.py / score.py hardcodes a weight, fee, threshold or
keyword list — it all comes through here. `/config` reads and writes the same file,
so an edit there recomputes every assessment the next time it's touched.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import yaml

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"

_cache: dict[str, Any] | None = None


def load_config(force_reload: bool = False) -> dict[str, Any]:
    global _cache
    if _cache is None or force_reload:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            _cache = yaml.safe_load(f)
    return _cache


def save_config(cfg: dict[str, Any]) -> None:
    """Write back and invalidate the cache so the next read picks it up."""
    global _cache
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=True)
    _cache = None


def reference_date() -> dt.date:
    """The frozen 'today' every date comparison in the engine uses.

    Falls back to the real today() only if config omits it — see the design doc's
    note on why expected_results.json needs a date that never drifts.
    """
    cfg = load_config()
    raw = cfg.get("reference_date")
    if not raw:
        return dt.date.today()
    return dt.date.fromisoformat(str(raw))
