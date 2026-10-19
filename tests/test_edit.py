"""Manager edits and the screens around them, through the real routes: the
deliverables parser, the live re-score it drives, DM preview -> add, config and
creator saves.
"""
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

from app.extract import parse_deliverables
from app.models import Deliverable
from app.pipeline import parse_amount

HX = {"HX-Request": "true"}


@pytest.mark.parametrize("text, expected", [
    ("2 × Reel, 3 × Story", [Deliverable("reel", 2), Deliverable("story", 3)]),
    ("1 reel + 2 stories", [Deliverable("reel", 1), Deliverable("story", 2)]),
    ("2x reels and 1 carousel", [Deliverable("reel", 2), Deliverable("carousel", 1)]),
    ("1 × Static Post; 1 static", [Deliverable("static_post", 2)]),
    ("1 × Youtube Integration, 1 yt", [Deliverable("youtube_integration", 2)]),
    ("1 reel, 1 reel", [Deliverable("reel", 2)]),
    ("", []),
])
def test_parse_deliverables_accepts_rendered_and_typed_forms(text, expected):
    assert parse_deliverables(text) == expected


@pytest.mark.parametrize("text", ["reel", "2 × Podcast", "0 × Reel", "two reels"])
def test_parse_deliverables_rejects_unreadable_input(text):
    with pytest.raises(ValueError):
        parse_deliverables(text)


@pytest.mark.parametrize("text, expected", [
    ("₹1,50,000", 150000.0), ("150000", 150000.0), ("1.5L", 150000.0),
    ("40k", 40000.0), ("Rs 2,70,000", 270000.0), ("", None),
])
def test_parse_amount_accepts_how_managers_type_money(text, expected):
    assert parse_amount(text) == expected


def test_parse_amount_rejects_words():
    with pytest.raises(ValueError):
        parse_amount("one lakh")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "app.db"))
    from app import config_loader

    original = config_loader.CONFIG_PATH.read_bytes()
    from app.main import app

    with TestClient(app) as c:
        assert c.post("/scan", follow_redirects=False).status_code == 303
        yield c
    config_loader.CONFIG_PATH.write_bytes(original)
    config_loader.load_config(force_reload=True)


def _debug_row(client, inquiry_id):
    return next(r for r in client.get("/api/debug").json()["inquiries"] if r["inquiry_id"] == inquiry_id)


def test_deliverables_edit_rescores_but_conflict_cap_holds(client):
    """Nivara Soaps (msg_002) cut from 2 Reel + 3 Story to 1 Reel for Aanya Mehra.

    base = 1*62,000 = 62,000; 1 deliverable < 3 -> no bundle discount
    usage 90 days -> 2 extra 30-day blocks -> +40%: 62,000 * 0.40 = 24,800
    whitelisting +25%: 62,000 * 0.25 = 15,500
    total = 62,000 + 24,800 + 15,500 = 1,02,300
    The ₹1,50,000 offer now clears the quote, so Lowball goes — but the Santoor
    conflict is about category and dates, not money, so the score stays capped.
    """
    before = _debug_row(client, "msg_002")
    assert before["quote_total"] == 264330.0
    assert "lowball" in before["flags"]

    r = client.post("/inquiry/msg_002/edit", data={"field": "deliverables", "value": "1 × Reel"}, headers=HX)
    assert r.status_code == 200
    assert r.text.lstrip().startswith('<section id="assessment"')
    assert 'id="field-deliverables"' in r.text and 'hx-swap-oob="true"' in r.text
    assert "Cleared since last score" in r.text and "Lowball" in r.text

    after = _debug_row(client, "msg_002")
    assert after["quote_total"] == 102300.0
    assert "lowball" not in after["flags"]
    assert "conflict" in after["flags"]
    assert after["final_score"] <= 20

    page = client.get("/inquiry/msg_002").text
    assert 'value="1 × Reel"' in page
    assert "prov--edited" in page
    assert "₹1,02,300" in page


def test_budget_typed_with_rupee_grouping_saves(client):
    client.post("/inquiry/msg_002/edit", data={"field": "budget_amount", "value": "₹2,70,000"}, headers=HX)
    row = _debug_row(client, "msg_002")
    assert "lowball" not in row["flags"] and "conflict" in row["flags"]


def test_bad_edit_shows_error_and_leaves_assessment_unchanged(client):
    r = client.post("/inquiry/msg_002/edit", data={"field": "deliverables", "value": "2 × Podcast"}, headers=HX)
    assert r.status_code == 200
    assert 'role="alert"' in r.text and "Podcast" in r.text
    assert _debug_row(client, "msg_002")["quote_total"] == 264330.0


def test_edit_without_javascript_redirects_back(client):
    r = client.post("/inquiry/msg_002/edit", data={"field": "budget_amount", "value": "270000"},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/inquiry/msg_002"


def test_each_edit_form_posts_only_its_own_value(client):
    """HTMX posts every input of the enclosing <form>, and every edit input is named
    "value" — so each edit form must hold exactly one, or the server keeps the wrong row.
    """
    class EditForms(HTMLParser):
        def __init__(self):
            super().__init__()
            self.forms = []
            self.current = None

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if tag == "form" and a.get("hx-post", "").endswith("/edit"):
                self.current = {"values": 0, "field": 0}
                self.forms.append(self.current)
            elif self.current is not None and tag in ("input", "select", "textarea"):
                if a.get("name") == "value":
                    self.current["values"] += 1
                if a.get("name") == "field":
                    self.current["field"] += 1

        def handle_endtag(self, tag):
            if tag == "form":
                self.current = None

    parser = EditForms()
    parser.feed(client.get("/inquiry/msg_002").text)
    assert len(parser.forms) >= 10
    assert all(f == {"values": 1, "field": 1} for f in parser.forms)


def test_decision_records_whether_the_reply_was_edited(client):
    r = client.post("/inquiry/msg_002/decision", headers=HX,
                    data={"action": "decline", "reply_text": "Hi team", "draft": "Hi team"})
    assert r.status_code == 200 and "Declined · logged" in r.text and "as drafted" in r.text
    client.post("/inquiry/msg_001/decision", headers=HX,
                data={"action": "accept_and_negotiate", "reply_text": "Edited!", "draft": "Hi"})
    log = client.get("/pipeline").text
    assert "Declined" in log and "Approved" in log


def test_dm_preview_then_add_to_queue(client):
    text = ("hi ma'am, humein aapke saath ek collab karna hai. budget 40k hai, "
            "ek reel aur do stories chahiye. diwali se pehle live karna hai.")
    before = len(client.get("/api/debug").json()["inquiries"])
    preview = client.post("/dm/process", data={"creator_id": "aanya_mehra", "dm_text": text})
    assert preview.status_code == 200 and "Check before adding to the queue" in preview.text
    assert 'value="₹40,000"' in preview.text and 'value="1 × Reel, 2 × Story"' in preview.text
    assert len(client.get("/api/debug").json()["inquiries"]) == before

    r = client.post("/dm/commit", follow_redirects=False, data={
        "creator_id": "aanya_mehra", "sender": "@glowbrand", "dm_text": text,
        "f_brand": "Glow Brand", "o_brand": "", "f_budget_amount": "₹40,000", "o_budget_amount": "₹40,000",
        "f_deliverables": "1 × Reel, 2 × Story", "o_deliverables": "1 × Reel, 2 × Story",
    })
    assert r.status_code == 303 and r.headers["location"].startswith("/inquiry/dm_")
    page = client.get(r.headers["location"]).text
    assert 'value="Glow Brand"' in page and "prov--edited" in page
    assert len(client.get("/api/debug").json()["inquiries"]) == before + 1


def test_config_structured_save_rejects_bad_weights_and_rescores(client):
    r = client.post("/config/update", data={"w_rate_fit": "50", "w_brand_fit": "25",
                                            "w_urgency": "15", "w_completeness": "15"})
    assert r.status_code == 200 and "must total 100" in r.text
    r = client.post("/config/update", data={"whitelisting_fee_pct": "30"}, follow_redirects=False)
    assert r.status_code == 303 and "rescored=" in r.headers["location"]
    assert _debug_row(client, "msg_002")["quote_total"] == 272340.0  # 1,60,200 × 1.70


def test_creator_page_uses_indian_grouping_and_saves_percentages(client):
    page = client.get("/creator/aanya_mehra").text
    assert "1,82,400" in page and "Santoor" in page and "days remaining" in page
    r = client.post("/creator/aanya_mehra/update", data={"min_acceptable_pct": "50"}, follow_redirects=False)
    assert r.status_code == 303
    assert 'value="50"' in client.get("/creator/aanya_mehra").text


@pytest.mark.parametrize("path", ["/creators", "/skipped", "/pipeline", "/config", "/dm"])
def test_supporting_pages_render(client, path):
    r = client.get(path)
    assert r.status_code == 200 and "SAMPLE DATA" in r.text


def test_unknown_ids_return_404(client):
    assert client.get("/inquiry/nope").status_code == 404
    assert client.get("/creator/nope").status_code == 404
    assert client.post("/inquiry/nope/edit", data={"field": "brand", "value": "x"}).status_code == 404
