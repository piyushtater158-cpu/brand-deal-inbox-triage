"""Adding, editing and removing creators through the real routes, the roster CSV
round-trip, and pasted DMs staying connected to their creator across a rescan.
"""
import csv
import io

import pytest
from fastapi.testclient import TestClient

from app import db
from app.creator_form import new_creator_id, values_from_creator

NEW_CREATOR = {
    "name": "Ishaan Verma", "ig_handle": "ishaan.eats", "email": "ishaan.verma.collabs@kalakaaar.in",
    "niche": "Food, travel", "city": "Delhi", "languages": "Hindi, English",
    "followers": "1,56,000", "avg_reach": "80000", "engagement_rate": "4.8",
    "reel": "₹50,000", "story": "15000", "static_post": "28000", "carousel": "38000",
    "youtube_integration": "", "bundle_discount_pct": "10", "min_acceptable_pct": "70",
    "accepts_barter": "yes", "barter_min_product_value": "10000",
    "usage_rights_default_days": "30", "max_usage_days_without_extra_fee": "30",
    "max_paid_deals_per_month": "4", "current_booked_this_month": "1",
    "no_go_categories": "Alcohol\ntobacco\nalcohol",
    "p_brand": ["Zomato", ""], "p_cat": ["food", ""], "p_excl": ["yes", "no"], "p_end": ["2027-01-31", ""],
    "b_start": ["2026-12-20", ""], "b_end": ["2026-12-31", ""], "b_reason": ["holiday", ""],
}

DM_TEXT = "hi! collab? budget 30k for ek reel, live next month"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "app.db"))
    from app.main import app

    with TestClient(app) as c:
        assert c.post("/scan", follow_redirects=False).status_code == 303
        yield c


def _debug(client):
    return {r["inquiry_id"]: r for r in client.get("/api/debug").json()["inquiries"]}


def _form_for(creator_id, **changes):
    """The edit form exactly as the page would post it, with some values changed."""
    with db.get_conn() as conn:
        v = values_from_creator(db.get_creator(conn, creator_id))
    data = {k: val for k, val in v.items() if k not in ("partners", "blackouts")}
    data.update(
        p_brand=[p["brand"] for p in v["partners"]], p_cat=[p["category"] for p in v["partners"]],
        p_excl=[p["exclusive"] for p in v["partners"]], p_end=[p["end"] for p in v["partners"]],
        b_start=[b["start"] for b in v["blackouts"]], b_end=[b["end"] for b in v["blackouts"]],
        b_reason=[b["reason"] for b in v["blackouts"]],
    )
    data.update(changes)
    return data


def _add_dm(client, creator_id, text=DM_TEXT):
    r = client.post("/dm/commit", follow_redirects=False,
                    data={"creator_id": creator_id, "sender": "@somebrand", "dm_text": text})
    assert r.status_code == 303
    return r.headers["location"].rsplit("/", 1)[-1]


def test_new_creator_id_slugs_and_avoids_clashes():
    assert new_creator_id("Ishaan Verma", set()) == "ishaan_verma"
    assert new_creator_id("Ishaan Verma", {"ishaan_verma"}) == "ishaan_verma_2"
    assert new_creator_id("  D'Souza!! ", set()) == "d_souza"


def test_add_creator_saves_every_field_and_joins_dm_intake(client):
    r = client.post("/creators/new", data=NEW_CREATOR, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/creator/ishaan_verma?added=1"

    with db.get_conn() as conn:
        c = db.get_creator(conn, "ishaan_verma")
    assert c.ig_handle == "@ishaan.eats" and c.niche == ["food", "travel"] and c.followers == 156000
    assert c.rate_card.reel == 50000 and c.rate_card.youtube_integration is None
    assert c.rate_card.bundle_discount_pct == pytest.approx(0.10) and c.min_acceptable_pct == pytest.approx(0.70)
    assert c.accepts_barter and c.current_booked_this_month == 1
    assert c.no_go_categories == ["alcohol", "tobacco"]
    assert [(p.brand, p.category, p.exclusive, str(p.exclusivity_end_date)) for p in c.active_partners] == \
        [("Zomato", "food", True, "2027-01-31")]
    assert [(str(b.start), str(b.end), b.reason) for b in c.blackout_dates] == [("2026-12-20", "2026-12-31", "holiday")]

    assert "Ishaan Verma" in client.get("/creators").text
    assert '<option value="ishaan_verma" selected>' in client.get("/dm?creator=ishaan_verma").text
    page = client.get("/creator/ishaan_verma?added=1").text
    assert "Added Ishaan Verma" in page and "No DMs yet" in page and "Zomato" in page


@pytest.mark.parametrize("change, message", [
    ({"name": ""}, "Name is required"),
    ({"email": "not-an-email"}, "Email must look like"),
    ({"followers": "lots"}, "Followers must be a number"),
    ({"min_acceptable_pct": "150"}, "between 0 and 100"),
    ({"p_brand": ["Zomato", ""], "p_cat": ["", ""]}, "Partner row 1 needs both"),
    ({"b_start": ["2026-12-31", ""], "b_end": ["2026-12-20", ""]}, "ends before it starts"),
    ({"ig_handle": "@aanyamehra"}, "already on the roster as Aanya Mehra"),
])
def test_bad_creator_form_rerenders_with_typed_values_and_saves_nothing(client, change, message):
    r = client.post("/creators/new", data={**NEW_CREATOR, **change}, follow_redirects=False)
    assert r.status_code == 200 and message in r.text and "Nothing was saved" in r.text
    assert 'value="Delhi"' in r.text
    with db.get_conn() as conn:
        assert len(db.list_creators(conn)) == 5


def test_reviving_an_exclusivity_turns_a_clean_deal_into_a_conflict(client):
    """Rohan's IronCore (nutrition) exclusivity ended 31 Aug 2026, so the MuscleMax pitch
    (msg_007) scores on merit. Extending it past the go-live date must flip it to Conflict."""
    assert "conflict" not in _debug(client)["msg_007"]["flags"]
    r = client.post("/creator/rohan_iyer/edit", follow_redirects=False,
                    data=_form_for("rohan_iyer", p_end=["2027-03-31"]))
    assert r.status_code == 303 and "rescored=" in r.headers["location"]
    row = _debug(client)["msg_007"]
    assert "conflict" in row["flags"] and row["final_score"] <= 20


def test_blackout_added_in_the_form_flags_the_clash(client):
    assert "blackout_clash" not in _debug(client)["msg_007"]["flags"]
    client.post("/creator/rohan_iyer/edit", data=_form_for(
        "rohan_iyer", b_start=["2026-10-01"], b_end=["2027-12-31"], b_reason=["shoot"]))
    assert "blackout_clash" in _debug(client)["msg_007"]["flags"]


def test_roster_export_loads_back_identically(client, tmp_path):
    client.post("/creators/new", data=NEW_CREATOR)
    r = client.get("/creators/export.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert list(csv.DictReader(io.StringIO(r.text)).fieldnames) == db.CSV_FIELDNAMES
    path = tmp_path / "roster.csv"
    path.write_text(r.text, encoding="utf-8")
    with db.get_conn() as conn:
        live = {c.id: c for c in db.list_creators(conn)}
    loaded = {c.id: c for c in db.load_creators_from_csv(path)}
    assert loaded == live


def test_seed_roster_round_trips_through_the_export_format():
    seed = (db.SEED_DIR / "roster_seed.csv").read_text(encoding="utf-8")
    header = seed.splitlines()[0].split(",")
    assert header == db.CSV_FIELDNAMES
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=db.CSV_FIELDNAMES, lineterminator="\n")
    w.writeheader()
    for c in db.load_creators_from_csv():
        w.writerow(db.creator_to_csv_row(c))
    assert buf.getvalue().strip().splitlines() == seed.strip().splitlines()


def test_pasted_dm_is_listed_on_the_creator_and_survives_a_rescan(client):
    client.post("/creators/new", data=NEW_CREATOR)
    dm_id = _add_dm(client, "ishaan_verma")
    assert dm_id.startswith("dm_")
    page = client.get("/creator/ishaan_verma").text
    assert f'href="/inquiry/{dm_id}"' in page and "Pasted in DM intake" in page

    client.post("/scan")
    rows = _debug(client)
    assert dm_id in rows
    assert len([i for i in rows if not i.startswith("dm_")]) == 29
    assert client.get(f"/inquiry/{dm_id}").status_code == 200


def test_seed_dms_still_rebuild_on_rescan(client):
    page = client.get("/creator/aanya_mehra").text
    assert "Sample inbox" in page  # the Hinglish and Lumiere DMs from seed/
    client.post("/scan")
    assert len(_debug(client)) == 29


def test_removing_a_creator_needs_confirmation_and_takes_their_inquiries(client):
    dm_id = _add_dm(client, "tara_dsouza")
    before = _debug(client)
    tara = {i for i, r in before.items() if r["creator_id"] == "tara_dsouza"}
    assert dm_id in tara

    r = client.post("/creator/tara_dsouza/delete", data={}, follow_redirects=False)
    assert r.status_code == 200 and "Tick the box" in r.text

    r = client.post("/creator/tara_dsouza/delete", data={"confirm": "yes"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/creators?deleted=")
    after = _debug(client)
    assert not (set(after) & tara) and len(after) == len(before) - len(tara)
    assert client.get("/creator/tara_dsouza").status_code == 404
    assert "Removed Tara Dsouza" in client.get(r.headers["location"]).text
    client.post("/scan")
    assert not any(r["creator_id"] == "tara_dsouza" for r in _debug(client).values())


def test_creator_routes_404_for_unknown_ids(client):
    assert client.get("/creator/nope/edit").status_code == 404
    assert client.post("/creator/nope/edit", data=NEW_CREATOR).status_code == 404
    assert client.post("/creator/nope/delete", data={"confirm": "yes"}).status_code == 404
