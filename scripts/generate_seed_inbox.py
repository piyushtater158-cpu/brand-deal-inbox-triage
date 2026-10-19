"""One-off generator for seed/demo_inbox.json. 30 keyword-matching messages (25 email
+ 5 DM) covering all 18 brief scenarios + the agency-on-behalf-of-brand case, plus 6
non-matching messages that should be skipped by the keyword filter.

Reference date for the whole build is 2026-10-19 (config.yaml's reference_date) — every
relative phrase ("within 48 hours", "respond by") below is authored against that date.
"""
from __future__ import annotations

import json
from pathlib import Path

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"

MESSAGES = [
    # ---- 1. Strong paid deal, fully specified (P1) ---------------------------------
    {
        "id": "msg_001", "creator_id": "aanya_mehra", "source": "email",
        "received_at": "2026-10-13T09:15:00",
        "sender_name": "Devika Rao", "sender_email_or_handle": "devika.rao@lumiereskin.co.in",
        "sender_domain": "lumiereskin.co.in",
        "subject": "Collab opportunity — Lumiere Skin Co. new launch",
        "scenario": "strong_paid_deal_fully_specified",
        "raw_text": (
            "Hi Aanya team,\n\nWe're Lumiere Skin Co. and would love a collaboration for our "
            "new serum launch. We'd like 2 reels and 2 stories from you. Budget: ₹1,50,000. "
            "Go live date: 20 Nov 2026. Please respond by 25 Oct 2026. Usage rights for 30 "
            "days. Payment terms: 50% advance, net 30.\n\nWarm regards,\nDevika Rao, Lumiere Skin Co."
        ),
    },
    # ---- DM duplicate of msg_001 (same brand+creator, within 14 days) --------------
    {
        "id": "msg_015", "creator_id": "aanya_mehra", "source": "dm",
        "received_at": "2026-10-15T18:40:00",
        "sender_name": "lumiereskinco_official", "sender_email_or_handle": "@lumiereskinco_official",
        "sender_domain": "instagram.com",
        "subject": "",
        "scenario": "duplicate_email_and_dm",
        "raw_text": (
            "Hey! Following up here too in case email got buried — we're Lumiere Skin "
            "Co., want to do a collab for our serum launch, 2 reels and 2 stories, budget "
            "₹1,50,000, go live date 20 Nov 2026, usage rights for 30 days. Let us know!"
        ),
    },
    # ---- 2. Paid deal slightly under rate -> counter, + Urgent 48h deadline --------
    {
        "id": "msg_003", "creator_id": "rohan_iyer", "source": "email",
        "received_at": "2026-10-19T08:05:00",
        "sender_name": "Arjun Mehta", "sender_email_or_handle": "arjun@fitfuelindia.com",
        "sender_domain": "fitfuelindia.com",
        "subject": "Quick collab — FitFuel India",
        "scenario": "paid_slightly_under_rate_and_urgent",
        "raw_text": (
            "Hi Rohan team,\n\nFitFuel India here — we need a quick turnaround collab: "
            "1 reel and 2 stories. Budget: ₹60,000. Go live date: 5 Nov 2026. We need you to "
            "respond within 48 hours as this is tied to a flash promo. Usage rights for 30 "
            "days. Payment terms: 50% advance, net 15.\n\nThanks,\nArjun, FitFuel India"
        ),
    },
    # ---- 3. Lowball (<50% of rate) --------------------------------------------------
    {
        "id": "msg_004", "creator_id": "meera_nair", "source": "email",
        "received_at": "2026-10-11T14:00:00",
        "sender_name": "QuickBite Team", "sender_email_or_handle": "hello@quickbitefoods.in",
        "sender_domain": "quickbitefoods.in",
        "subject": "Collab opportunity — QuickBite Foods",
        "scenario": "lowball_under_50pct",
        "raw_text": (
            "Hi Meera team,\n\nWe're QuickBite Foods and would love a quick collab! We'd "
            "like 1 static post. Budget: ₹8,000. Go live date: 10 Nov 2026. Please respond "
            "by 2 Nov 2026. Usage rights for 30 days. Payment terms: 50% advance, net 15.\n\n"
            "Thanks,\nQuickBite Team"
        ),
    },
    # ---- 4a. Barter acceptable -------------------------------------------------------
    {
        "id": "msg_005", "creator_id": "tara_dsouza", "source": "email",
        "received_at": "2026-10-10T10:30:00",
        "sender_name": "Zephyr Travel Co.", "sender_email_or_handle": "partnerships@zephyrtravel.co",
        "sender_domain": "zephyrtravel.co",
        "subject": "Stay + feature collab — Zephyr Travel Co.",
        "scenario": "barter_acceptable",
        "raw_text": (
            "Hi Tara,\n\nZephyr Travel Co. here — we'd love to host you for a weekend stay "
            "in exchange for 1 story. Product worth ₹22,000 (the full stay package). Go "
            "live date: 15 Nov 2026. Usage rights for 30 days.\n\nBest,\nZephyr Travel Co."
        ),
    },
    # ---- 4b. Barter NOT acceptable ---------------------------------------------------
    {
        "id": "msg_006", "creator_id": "rohan_iyer", "source": "email",
        "received_at": "2026-10-09T16:20:00",
        "sender_name": "GearFit Supplements", "sender_email_or_handle": "team@gearfitsupplements.in",
        "sender_domain": "gearfitsupplements.in",
        "subject": "Barter collab — GearFit Supplements",
        "scenario": "barter_not_acceptable",
        "raw_text": (
            "Hi Rohan team,\n\nGearFit Supplements would love to send you our full product "
            "kit in exchange for 1 reel. Product worth ₹5,000 (supplement hamper). Go live "
            "date: 12 Nov 2026. Usage rights for 30 days.\n\nCheers,\nGearFit Supplements"
        ),
    },
    # ---- 5. Competitor conflict: rival soap vs Santoor exclusive ---------------------
    {
        "id": "msg_002", "creator_id": "aanya_mehra", "source": "email",
        "received_at": "2026-10-17T11:42:00",
        "sender_name": "Priya Menon", "sender_email_or_handle": "priya.menon@nivarasoaps.in",
        "sender_domain": "nivarasoaps.in",
        "subject": "Collab opportunity — Nivara Soaps festive campaign",
        "scenario": "competitor_conflict_vs_santoor",
        "raw_text": (
            "Hi Aanya team,\n\nWe run Nivara Soaps and would love a collaboration with Aanya "
            "for our festive campaign! We're looking for 2 reels and 3 stories. Budget: "
            "₹1,50,000. Go live date: 8 Nov 2026. Please respond by 25 Oct 2026. We'd need "
            "usage rights for 90 days with whitelisting for paid ads. Payment terms: no "
            "advance, net 90.\n\nLooking forward to hearing from you!\nWarm regards,\n"
            "Priya Menon, Nivara Soaps"
        ),
    },
    # ---- 6. Expired exclusivity -> no longer a conflict ------------------------------
    {
        "id": "msg_007", "creator_id": "rohan_iyer", "source": "email",
        "received_at": "2026-10-14T13:10:00",
        "sender_name": "MuscleMax Team", "sender_email_or_handle": "partnerships@musclemax.in",
        "sender_domain": "musclemax.in",
        "subject": "Collab — MuscleMax protein range",
        "scenario": "expired_exclusivity_no_longer_conflict",
        "raw_text": (
            "Hi Rohan team,\n\nMuscleMax here — we'd love 2 reels and 2 stories to launch "
            "our new protein range. Budget: ₹1,30,000. Go live date: 25 Nov 2026. Please "
            "respond by 5 Nov 2026. Usage rights for 30 days. Payment terms: 50% advance, "
            "net 30.\n\nBest,\nMuscleMax Team"
        ),
    },
    # ---- 7. No-go category (betting app) ---------------------------------------------
    {
        "id": "msg_008", "creator_id": "kabir_shah", "source": "email",
        "received_at": "2026-10-12T19:00:00",
        "sender_name": "BetKing11 Promotions", "sender_email_or_handle": "promo@betking11.app",
        "sender_domain": "betking11.app",
        "subject": "Huge payout — BetKing11 ambassador campaign",
        "scenario": "no_go_betting",
        "raw_text": (
            "Hi Kabir,\n\nBetKing11 wants you as our brand ambassador! We'd pay ₹2,00,000 "
            "for 2 reels. Go live date: 1 Nov 2026. Usage rights for 30 days. Payment terms: "
            "50% advance, net 15.\n\nBetKing11 Promotions"
        ),
    },
    # ---- 8. Missing budget and dates -> ask for info ---------------------------------
    {
        "id": "msg_009", "creator_id": "tara_dsouza", "source": "email",
        "received_at": "2026-10-08T08:45:00",
        "sender_name": "WanderLuxe Stays", "sender_email_or_handle": "hello@wanderluxestays.com",
        "sender_domain": "wanderluxestays.com",
        "subject": "Collab — WanderLuxe Stays",
        "scenario": "missing_budget_and_dates",
        "raw_text": (
            "Hi Tara,\n\nWe'd love to feature you with 1 reel. Let us know if you're "
            "interested in a collaboration!\n\nWanderLuxe Stays"
        ),
    },
    # ---- 9. Usage rights overreach (perpetual use, paid ads whitelisting) -----------
    {
        "id": "msg_010", "creator_id": "kabir_shah", "source": "email",
        "received_at": "2026-10-16T15:30:00",
        "sender_name": "VoltEdge Electronics", "sender_email_or_handle": "partnerships@voltedge.in",
        "sender_domain": "voltedge.in",
        "subject": "Collab — VoltEdge Electronics launch",
        "scenario": "usage_overreach",
        "raw_text": (
            "Hi Kabir team,\n\nVoltEdge Electronics would like 2 reels and 1 static post for "
            "our new launch. Budget: ₹1,50,000. Go live date: 3 Dec 2026. Please respond by "
            "1 Nov 2026. We need perpetual usage rights with whitelisting for paid ads. "
            "Payment terms: 50% advance, net 30.\n\nVoltEdge Electronics"
        ),
    },
    # ---- 10. Risky payment terms (net 90, no advance) --------------------------------
    {
        "id": "msg_011", "creator_id": "meera_nair", "source": "email",
        "received_at": "2026-10-07T12:00:00",
        "sender_name": "SnackWorks India", "sender_email_or_handle": "team@snackworksindia.com",
        "sender_domain": "snackworksindia.com",
        "subject": "Collab — SnackWorks India",
        "scenario": "risky_payment_terms",
        "raw_text": (
            "Hi Meera team,\n\nSnackWorks India would love 1 reel and 1 static post. Budget: "
            "₹55,000. Go live date: 18 Nov 2026. Please respond by 30 Oct 2026. Usage rights "
            "for 30 days. Payment terms: no advance, net 90.\n\nSnackWorks India"
        ),
    },
    # ---- 11. Scam: pay registration fee ----------------------------------------------
    {
        "id": "msg_012", "creator_id": "aanya_mehra", "source": "email",
        "received_at": "2026-10-06T10:00:00",
        "sender_name": "GlamBoost Promotions", "sender_email_or_handle": "offers@glamboostpromo.co",
        "sender_domain": "glamboostpromo.co",
        "subject": "You've been selected for our ambassador campaign!",
        "scenario": "scam_registration_fee",
        "raw_text": (
            "Congratulations! You've been selected for our exclusive ambassador campaign "
            "worth ₹5,00,000. To confirm your slot, please pay ₹2,999 registration fee to "
            "join our campaign. Reply within 24 hours to claim this collaboration!\n\n"
            "GlamBoost Promotions"
        ),
    },
    # ---- 12. Lookalike domain pretending to be a big brand --------------------------
    {
        "id": "msg_013", "creator_id": "aanya_mehra", "source": "email",
        "received_at": "2026-10-05T09:30:00",
        "sender_name": "Santoor Brand Team", "sender_email_or_handle": "offers@santoor1.in",
        "sender_domain": "santoor1.in",
        "subject": "Collab opportunity — Santoor",
        "scenario": "lookalike_domain",
        "raw_text": (
            "Hi Aanya,\n\nWe're Santoor and would love a collaboration campaign — 2 reels "
            "and 2 stories. Budget: ₹2,00,000. Go live date: 20 Nov 2026. Usage rights for "
            "30 days. Payment terms: 50% advance, net 30.\n\nSantoor Brand Team"
        ),
    },
    # ---- 13. Creator at full capacity ------------------------------------------------
    {
        "id": "msg_016", "creator_id": "meera_nair", "source": "email",
        "received_at": "2026-10-04T11:15:00",
        "sender_name": "HomeChef Kitchenware", "sender_email_or_handle": "hello@homechefkitchenware.in",
        "sender_domain": "homechefkitchenware.in",
        "subject": "Collab — HomeChef Kitchenware",
        "scenario": "capacity_full",
        "raw_text": (
            "Hi Meera team,\n\nHomeChef Kitchenware would love 1 reel and 1 carousel. "
            "Budget: ₹60,000. Go live date: 22 Nov 2026. Please respond by 5 Nov 2026. "
            "Usage rights for 30 days. Payment terms: 50% advance, net 30.\n\nHomeChef Kitchenware"
        ),
    },
    # ---- 14. Blackout clash ----------------------------------------------------------
    {
        "id": "msg_017", "creator_id": "kabir_shah", "source": "email",
        "received_at": "2026-10-03T14:50:00",
        "sender_name": "NexaCharge Team", "sender_email_or_handle": "partnerships@nexacharge.com",
        "sender_domain": "nexacharge.com",
        "subject": "Collab — NexaCharge power banks",
        "scenario": "blackout_clash",
        "raw_text": (
            "Hi Kabir team,\n\nNexaCharge would love 1 reel and 1 static post. Budget: "
            "₹85,000. Go live date: 15 Nov 2026. Please respond by 28 Oct 2026. Usage "
            "rights for 30 days. Payment terms: 50% advance, net 30.\n\nNexaCharge Team"
        ),
    },
    # ---- 15. Hinglish message ---------------------------------------------------------
    {
        "id": "msg_018", "creator_id": "aanya_mehra", "source": "dm",
        "received_at": "2026-10-02T20:10:00",
        "sender_name": "Rhea", "sender_email_or_handle": "@glownest.cosmetics",
        "sender_domain": "instagram.com",
        "subject": "Collab proposal - GlowNest Cosmetics",
        "scenario": "hinglish_message",
        "raw_text": (
            "hi ma'am, humein aapke saath ek collab karna hai. budget 40k hai, ek reel aur "
            "do stories chahiye. diwali se pehle live karna hai."
        ),
    },
    # ---- 16. Non-deal mail with a keyword (newsletter mentioning "campaign") --------
    {
        "id": "msg_019", "creator_id": "meera_nair", "source": "email",
        "received_at": "2026-10-01T07:00:00",
        "sender_name": "Creator Weekly", "sender_email_or_handle": "newsletter@creatorweekly.in",
        "sender_domain": "creatorweekly.in",
        "subject": "Monthly Creator Newsletter — October Campaign Roundup",
        "scenario": "non_deal_with_keyword",
        "raw_text": (
            "This month's roundup: platform algorithm changes, creator meetup recap, and "
            "our October campaign roundup covering the best food content of the month. "
            "Unsubscribe anytime.\n\nCreator Weekly"
        ),
    },
    # ---- 17. Agency inquiry on behalf of a brand -------------------------------------
    {
        "id": "msg_020", "creator_id": "kabir_shah", "source": "email",
        "received_at": "2026-09-30T10:20:00",
        "sender_name": "Vertex Talent Agency", "sender_email_or_handle": "deals@vertextalent.com",
        "sender_domain": "vertextalent.com",
        "subject": "Collab proposal — on behalf of Boat Lifestyle",
        "scenario": "agency_on_behalf_of_brand",
        "raw_text": (
            "Hi Kabir team,\n\nOn behalf of Boat Lifestyle, we at Vertex Talent Agency would "
            "like to propose a collaboration — 2 reels and 1 static post. Budget: "
            "₹1,60,000. Go live date: 25 Nov 2026. Please respond by 10 Nov 2026. Usage "
            "rights for 30 days. Payment terms: 50% advance, net 30.\n\nVertex Talent Agency"
        ),
    },
    # ---- Filler: ordinary paid deals across the roster (pad to ~25 email + 5 DM) ----
    {
        "id": "msg_021", "creator_id": "aanya_mehra", "source": "email",
        "received_at": "2026-09-29T09:00:00",
        "sender_name": "Pure Glow Cosmetics", "sender_email_or_handle": "hello@pureglow.in",
        "sender_domain": "pureglow.in",
        "subject": "Collab — Pure Glow Cosmetics",
        "scenario": "filler_ordinary_deal",
        "raw_text": (
            "Hi Aanya team,\n\nPure Glow Cosmetics would love 1 reel and 1 static post. "
            "Budget: ₹80,000. Go live date: 28 Nov 2026. Please respond by 10 Nov 2026. "
            "Usage rights for 30 days. Payment terms: 50% advance, net 30.\n\nPure Glow Cosmetics"
        ),
    },
    {
        "id": "msg_022", "creator_id": "rohan_iyer", "source": "email",
        "received_at": "2026-09-28T13:40:00",
        "sender_name": "PowerBar Nutrition", "sender_email_or_handle": "team@powerbarnutrition.in",
        "sender_domain": "powerbarnutrition.in",
        "subject": "Collab — PowerBar Nutrition",
        "scenario": "filler_ordinary_deal",
        "raw_text": (
            "Hi Rohan team,\n\nPowerBar Nutrition would love 1 reel and 2 stories. Budget: "
            "₹70,000. Go live date: 30 Nov 2026. Please respond by 12 Nov 2026. Usage "
            "rights for 30 days. Payment terms: 50% advance, net 30.\n\nPowerBar Nutrition"
        ),
    },
    {
        "id": "msg_023", "creator_id": "meera_nair", "source": "dm",
        "received_at": "2026-09-27T17:05:00",
        "sender_name": "kochispiceco", "sender_email_or_handle": "@kochispiceco",
        "sender_domain": "instagram.com",
        "subject": "",
        "scenario": "filler_ordinary_deal",
        "raw_text": (
            "Hi Meera! Kochi Spice Co. here, we'd love a quick collab — 1 static post. "
            "Budget ₹40,000. Go live date: 25 Nov 2026. Usage rights for 30 days."
        ),
    },
    {
        "id": "msg_024", "creator_id": "kabir_shah", "source": "email",
        "received_at": "2026-09-26T11:25:00",
        "sender_name": "TechNova Gadgets", "sender_email_or_handle": "partnerships@technovagadgets.in",
        "sender_domain": "technovagadgets.in",
        "subject": "Collab — TechNova Gadgets",
        "scenario": "filler_ordinary_deal",
        "raw_text": (
            "Hi Kabir team,\n\nTechNova Gadgets would love 2 reels and 1 carousel. Budget: "
            "₹1,70,000. Go live date: 2 Dec 2026. Please respond by 15 Nov 2026. Usage "
            "rights for 30 days. Payment terms: 50% advance, net 30.\n\nTechNova Gadgets"
        ),
    },
    {
        "id": "msg_025", "creator_id": "tara_dsouza", "source": "dm",
        "received_at": "2026-09-25T19:50:00",
        "sender_name": "coastalbreezeresorts", "sender_email_or_handle": "@coastalbreezeresorts",
        "sender_domain": "instagram.com",
        "subject": "",
        "scenario": "filler_ordinary_deal",
        "raw_text": (
            "Hi Tara! Coastal Breeze Resorts here, we'd love a collab — 1 reel and 1 "
            "story. Budget ₹65,000. Go live date: 29 Nov 2026. Usage rights for 30 days."
        ),
    },
    {
        "id": "msg_026", "creator_id": "tara_dsouza", "source": "email",
        "received_at": "2026-09-24T08:15:00",
        "sender_name": "Everest Gear Co.", "sender_email_or_handle": "hello@everestgear.co",
        "sender_domain": "everestgear.co",
        "subject": "Collab — Everest Gear Co.",
        "scenario": "filler_ordinary_deal",
        "raw_text": (
            "Hi Tara team,\n\nEverest Gear Co. would love 1 static post. Budget: ₹20,000. "
            "Go live date: 20 Nov 2026. Please respond by 5 Nov 2026. Usage rights for 30 "
            "days. Payment terms: 50% advance, net 30.\n\nEverest Gear Co."
        ),
    },
    {
        "id": "msg_027", "creator_id": "aanya_mehra", "source": "dm",
        "received_at": "2026-09-23T21:00:00",
        "sender_name": "radiancederma", "sender_email_or_handle": "@radiancederma",
        "sender_domain": "instagram.com",
        "subject": "",
        "scenario": "filler_ordinary_deal",
        "raw_text": (
            "Hi Aanya! Radiance Derma here, we'd love a collab — 1 reel and 1 carousel. "
            "Budget ₹95,000. Go live date: 3 Dec 2026. Usage rights for 30 days."
        ),
    },
    {
        "id": "msg_028", "creator_id": "meera_nair", "source": "email",
        "received_at": "2026-09-22T10:40:00",
        "sender_name": "Urban Kitchen Co.", "sender_email_or_handle": "hello@urbankitchenco.in",
        "sender_domain": "urbankitchenco.in",
        "subject": "Collab — Urban Kitchen Co.",
        "scenario": "filler_ordinary_deal",
        "raw_text": (
            "Hi Meera team,\n\nUrban Kitchen Co. would love 1 reel. Budget: ₹30,000. Go "
            "live date: 27 Nov 2026. Please respond by 8 Nov 2026. Usage rights for 30 "
            "days. Payment terms: 50% advance, net 30.\n\nUrban Kitchen Co."
        ),
    },
    {
        "id": "msg_029", "creator_id": "rohan_iyer", "source": "email",
        "received_at": "2026-09-21T15:00:00",
        "sender_name": "CoreStrength Gear", "sender_email_or_handle": "team@corestrengthgear.in",
        "sender_domain": "corestrengthgear.in",
        "subject": "Collab — CoreStrength Gear",
        "scenario": "filler_ordinary_deal",
        "raw_text": (
            "Hi Rohan team,\n\nCoreStrength Gear would love 1 static post and 1 carousel. "
            "Budget: ₹55,000. Go live date: 1 Dec 2026. Please respond by 14 Nov 2026. "
            "Usage rights for 30 days. Payment terms: 50% advance, net 30.\n\nCoreStrength Gear"
        ),
    },
    {
        "id": "msg_030", "creator_id": "kabir_shah", "source": "email",
        "received_at": "2026-09-20T12:30:00",
        "sender_name": "ChipWorks Semiconductors", "sender_email_or_handle": "partnerships@chipworks.in",
        "sender_domain": "chipworks.in",
        "subject": "Collab — ChipWorks Semiconductors",
        "scenario": "filler_ordinary_deal",
        "raw_text": (
            "Hi Kabir team,\n\nChipWorks Semiconductors would love 1 reel. Budget: "
            "₹75,000. Go live date: 28 Nov 2026. Please respond by 12 Nov 2026. Usage "
            "rights for 30 days. Payment terms: 50% advance, net 30.\n\nChipWorks Semiconductors"
        ),
    },
    {
        "id": "msg_031", "creator_id": "tara_dsouza", "source": "email",
        "received_at": "2026-09-19T09:50:00",
        "sender_name": "Highland Trails Co.", "sender_email_or_handle": "hello@highlandtrails.co",
        "sender_domain": "highlandtrails.co",
        "subject": "Collab — Highland Trails Co.",
        "scenario": "filler_ordinary_deal",
        "raw_text": (
            "Hi Tara team,\n\nHighland Trails Co. would love 1 reel and 1 static post. "
            "Budget: ₹50,000. Go live date: 24 Nov 2026. Please respond by 6 Nov 2026. "
            "Usage rights for 30 days. Payment terms: 50% advance, net 30.\n\nHighland Trails Co."
        ),
    },
]

# ---- Non-matching mail: no brand keywords, must be skipped with a reason ------------
SKIPPED = [
    {
        "id": "skip_001", "creator_id": "aanya_mehra", "source": "email",
        "received_at": "2026-10-16T08:00:00",
        "sender_name": "Swiggy", "sender_email_or_handle": "noreply@swiggy.in",
        "sender_domain": "swiggy.in",
        "subject": "Your order has been delivered!",
        "raw_text": "Hi Aanya, your order from Spice Route has been delivered. Enjoy your meal! Rate your experience in the app.",
    },
    {
        "id": "skip_002", "creator_id": "rohan_iyer", "source": "email",
        "received_at": "2026-10-15T07:30:00",
        "sender_name": "Instagram", "sender_email_or_handle": "security@mail.instagram.com",
        "sender_domain": "mail.instagram.com",
        "subject": "New login to your account",
        "raw_text": "We noticed a new login to your Instagram account from a Chrome browser on Windows in Bengaluru. If this was you, no action is needed.",
    },
    {
        "id": "skip_003", "creator_id": "meera_nair", "source": "email",
        "received_at": "2026-10-13T06:45:00",
        "sender_name": "Netflix", "sender_email_or_handle": "info@netflix.com",
        "sender_domain": "netflix.com",
        "subject": "Your payment was successful",
        "raw_text": "Thanks for your payment. Your Netflix subscription has been renewed for another month. Enjoy your shows!",
    },
    {
        "id": "skip_004", "creator_id": "kabir_shah", "source": "email",
        "received_at": "2026-10-11T18:20:00",
        "sender_name": "Rahul", "sender_email_or_handle": "rahul.k@gmail.com",
        "sender_domain": "gmail.com",
        "subject": "Weekend trek?",
        "raw_text": "Hey Kabir, a few of us are planning a trek this weekend near Lonavala. You in? Let me know by Thursday.",
    },
    {
        "id": "skip_005", "creator_id": "tara_dsouza", "source": "email",
        "received_at": "2026-10-09T09:10:00",
        "sender_name": "HDFC Bank", "sender_email_or_handle": "statements@hdfcbank.net",
        "sender_domain": "hdfcbank.net",
        "subject": "Your credit card statement is ready",
        "raw_text": "Your monthly credit card statement is now available. Total amount due: ₹18,432. Due date: 5 Nov 2026.",
    },
    {
        "id": "skip_006", "creator_id": "aanya_mehra", "source": "email",
        "received_at": "2026-10-07T20:00:00",
        "sender_name": "DesignWeekly", "sender_email_or_handle": "news@designweekly.com",
        "sender_domain": "designweekly.com",
        "subject": "You've been unsubscribed",
        "raw_text": "You have successfully been unsubscribed from DesignWeekly. We're sorry to see you go. You can resubscribe anytime from our website.",
    },
]

if __name__ == "__main__":
    all_messages = MESSAGES + SKIPPED
    out_path = SEED_DIR / "demo_inbox.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_messages, f, indent=2, ensure_ascii=False)
    email_count = sum(1 for m in MESSAGES if m["source"] == "email")
    dm_count = sum(1 for m in MESSAGES if m["source"] == "dm")
    print(f"Wrote {out_path}: {len(MESSAGES)} matching ({email_count} email, {dm_count} dm) "
          f"+ {len(SKIPPED)} skipped = {len(all_messages)} total")
