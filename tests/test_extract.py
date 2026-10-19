"""Direct unit tests on the rules-based extractor — independent of the scenario
fixture, these check the regex patterns themselves against representative text.
"""
import datetime as dt

from app.extract import extract_fields

REF = dt.date(2026, 10, 19)


def test_extracts_rupee_amount_with_commas():
    e = extract_fields("Budget: ₹1,50,000. Go live date: 8 Nov 2026.", "", "brand.com", REF)
    assert e.budget_amount == 150000.0


def test_extracts_k_suffix_amount():
    e = extract_fields("Our budget is ₹60k for this.", "", "brand.com", REF)
    assert e.budget_amount == 60000.0


def test_extracts_lakh_suffix_amount():
    e = extract_fields("Budget: 2.5L for the full package.", "", "brand.com", REF)
    assert e.budget_amount == 250000.0


def test_extracts_hinglish_budget_and_deliverables():
    e = extract_fields(
        "budget 40k hai, ek reel aur do stories chahiye.", "", "brand.com", REF,
    )
    assert e.budget_amount == 40000.0
    by_type = {d.type: d.count for d in e.deliverables}
    assert by_type == {"reel": 1, "story": 2}


def test_extracts_deliverables_multiple_types():
    e = extract_fields("We'd like 2 reels and 3 stories from you.", "", "brand.com", REF)
    by_type = {d.type: d.count for d in e.deliverables}
    assert by_type == {"reel": 2, "story": 3}


def test_extracts_month_name_date():
    e = extract_fields("Go live date: 8 Nov 2026. Please respond by 20 Oct 2026.", "", "x.com", REF)
    assert e.go_live_date == dt.date(2026, 11, 8)
    assert e.response_deadline == dt.date(2026, 10, 20)


def test_within_hours_relative_deadline():
    e = extract_fields("Please respond within 48 hours.", "", "x.com", REF)
    assert e.response_deadline == REF + dt.timedelta(days=2)


def test_perpetual_usage_sets_large_sentinel():
    e = extract_fields("We need perpetual usage rights for this.", "", "x.com", REF)
    assert e.usage_rights_days == 36_500


def test_explicit_usage_days():
    e = extract_fields("Usage rights for 90 days please.", "", "x.com", REF)
    assert e.usage_rights_days == 90


def test_whitelisting_detected():
    e = extract_fields("We need whitelisting for paid ads on this content.", "", "x.com", REF)
    assert e.whitelisting is True


def test_exclusivity_detected():
    e = extract_fields("We'd like exclusivity in this category.", "", "x.com", REF)
    assert e.exclusivity_requested is True


def test_payment_terms_no_advance_and_net_days():
    e = extract_fields("Payment terms: no advance, net 90.", "", "x.com", REF)
    assert e.payment_advance_pct == 0
    assert e.payment_net_days == 90


def test_payment_terms_advance_percentage():
    e = extract_fields("Payment terms: 50% advance, net 30.", "", "x.com", REF)
    assert e.payment_advance_pct == 50
    assert e.payment_net_days == 30


def test_agency_on_behalf_of_detected():
    e = extract_fields("On behalf of Boat Lifestyle, we'd like to propose a collab.", "", "x.com", REF)
    assert e.agency_or_direct == "agency"


def test_brand_and_category_from_lookup():
    e = extract_fields("We're Santoor and would love a collab.", "", "santoor.in", REF)
    assert e.brand == "Santoor"
    assert e.brand_category == "personal care"


def test_no_false_positive_on_common_word_rs():
    """'Cheers,' contains the substring 'rs' — the money regex must not treat that as
    a currency marker (regression test for the bug this caught during seed authoring).
    """
    e = extract_fields("Usage rights for 30 days.\n\nCheers,\nGearFit Supplements", "", "x.com", REF)
    assert e.budget_amount is None
