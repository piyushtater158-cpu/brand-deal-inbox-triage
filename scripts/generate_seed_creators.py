"""One-off generator for seed/roster_seed.csv. Run again any time the 5 creators'
structural data below changes — do not hand-edit the CSV's JSON columns, they're
fiddly to quote by hand correctly.

Rate-card figures are placeholders pending the Assignment in the design doc: verify
against two real Indian-creator rate-card sources (150-200k follower tier) before
treating these as anything but plausible-looking sample data.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"

CREATORS = [
    {
        "id": "aanya_mehra",
        "name": "Aanya Mehra",
        "ig_handle": "@aanyamehra",
        "email": "aanya.mehra.collabs@kalakaaar.in",
        "niche_json": json.dumps(["beauty", "skincare"]),
        "city": "Mumbai",
        "languages_json": json.dumps(["Hindi", "English"]),
        "followers": 182400,
        "avg_reach": 96000,
        "engagement_rate": 4.1,
        "rate_card_json": json.dumps({
            "reel": 62000, "story": 18000, "static_post": 34000, "carousel": 45000,
            "youtube_integration": None, "bundle_discount_pct": 0.10,
        }),
        "min_acceptable_pct": 0.70,
        "accepts_barter": "false",
        "barter_min_product_value": 0,
        "usage_rights_default_days": 30,
        "max_usage_days_without_extra_fee": 30,
        "partners_json": json.dumps([
            {"brand": "Santoor", "category": "personal care", "exclusive": True,
             "exclusivity_end_date": "2027-03-31"},
        ]),
        "no_go_categories_json": json.dumps(["fairness creams", "tobacco", "alcohol"]),
        "max_paid_deals_per_month": 4,
        "current_booked_this_month": 2,
        "blackout_dates_json": json.dumps([]),
    },
    {
        "id": "rohan_iyer",
        "name": "Rohan Iyer",
        "ig_handle": "@rohan.lifts",
        "email": "rohan.iyer.collabs@kalakaaar.in",
        "niche_json": json.dumps(["fitness"]),
        "city": "Bengaluru",
        "languages_json": json.dumps(["English", "Kannada"]),
        "followers": 143200,
        "avg_reach": 71000,
        "engagement_rate": 5.3,
        "rate_card_json": json.dumps({
            "reel": 48000, "story": 14000, "static_post": 26000, "carousel": 36000,
            "youtube_integration": 55000, "bundle_discount_pct": 0.08,
        }),
        "min_acceptable_pct": 0.70,
        "accepts_barter": "false",
        "barter_min_product_value": 0,
        "usage_rights_default_days": 30,
        "max_usage_days_without_extra_fee": 30,
        "partners_json": json.dumps([
            {"brand": "IronCore Protein", "category": "nutrition", "exclusive": True,
             "exclusivity_end_date": "2026-08-31"},
        ]),
        "no_go_categories_json": json.dumps(["alcohol", "tobacco"]),
        "max_paid_deals_per_month": 4,
        "current_booked_this_month": 1,
        "blackout_dates_json": json.dumps([]),
    },
    {
        "id": "meera_nair",
        "name": "Meera Nair",
        "ig_handle": "@meeracooks",
        "email": "meera.nair.collabs@kalakaaar.in",
        "niche_json": json.dumps(["food"]),
        "city": "Kochi",
        "languages_json": json.dumps(["Malayalam", "English"]),
        "followers": 95800,
        "avg_reach": 48000,
        "engagement_rate": 6.0,
        "rate_card_json": json.dumps({
            "reel": 35000, "story": 10000, "static_post": 20000, "carousel": 28000,
            "youtube_integration": None, "bundle_discount_pct": 0.08,
        }),
        "min_acceptable_pct": 0.65,
        "accepts_barter": "true",
        "barter_min_product_value": 8000,
        "usage_rights_default_days": 30,
        "max_usage_days_without_extra_fee": 30,
        "partners_json": json.dumps([
            {"brand": "Tastybite Snacks", "category": "food", "exclusive": False,
             "exclusivity_end_date": None},
        ]),
        "no_go_categories_json": json.dumps(["alcohol", "tobacco"]),
        "max_paid_deals_per_month": 4,
        "current_booked_this_month": 4,
        "blackout_dates_json": json.dumps([]),
    },
    {
        "id": "kabir_shah",
        "name": "Kabir Shah",
        "ig_handle": "@kabirbuilds",
        "email": "kabir.shah.collabs@kalakaaar.in",
        "niche_json": json.dumps(["tech"]),
        "city": "Pune",
        "languages_json": json.dumps(["English", "Hindi"]),
        "followers": 210500,
        "avg_reach": 110000,
        "engagement_rate": 3.4,
        "rate_card_json": json.dumps({
            "reel": 70000, "story": 20000, "static_post": 38000, "carousel": 50000,
            "youtube_integration": 90000, "bundle_discount_pct": 0.12,
        }),
        "min_acceptable_pct": 0.75,
        "accepts_barter": "false",
        "barter_min_product_value": 0,
        "usage_rights_default_days": 30,
        "max_usage_days_without_extra_fee": 30,
        "partners_json": json.dumps([]),
        "no_go_categories_json": json.dumps(["betting", "tobacco"]),
        "max_paid_deals_per_month": 4,
        "current_booked_this_month": 2,
        "blackout_dates_json": json.dumps([
            {"start": "2026-11-10", "end": "2026-11-20", "reason": "travel"},
        ]),
    },
    {
        "id": "tara_dsouza",
        "name": "Tara Dsouza",
        "ig_handle": "@tararoams",
        "email": "tara.dsouza.collabs@kalakaaar.in",
        "niche_json": json.dumps(["travel"]),
        "city": "Goa",
        "languages_json": json.dumps(["English", "Konkani"]),
        "followers": 120300,
        "avg_reach": 58000,
        "engagement_rate": 4.7,
        "rate_card_json": json.dumps({
            "reel": 45000, "story": 13000, "static_post": 24000, "carousel": 32000,
            "youtube_integration": None, "bundle_discount_pct": 0.10,
        }),
        "min_acceptable_pct": 0.65,
        "accepts_barter": "true",
        "barter_min_product_value": 15000,
        "usage_rights_default_days": 30,
        "max_usage_days_without_extra_fee": 30,
        "partners_json": json.dumps([
            {"brand": "MakeMyTrip", "category": "travel", "exclusive": False,
             "exclusivity_end_date": None},
        ]),
        "no_go_categories_json": json.dumps(["tobacco"]),
        "max_paid_deals_per_month": 4,
        "current_booked_this_month": 1,
        "blackout_dates_json": json.dumps([]),
    },
]

FIELDNAMES = list(CREATORS[0].keys())

if __name__ == "__main__":
    out_path = SEED_DIR / "roster_seed.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for c in CREATORS:
            writer.writerow(c)
    print(f"Wrote {out_path} with {len(CREATORS)} creators")
