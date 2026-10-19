"""Manager edits on the inquiry detail page: the deliverables parser, and the live
re-score it drives through the real /inquiry/<id>/edit route.
"""
import pytest
from fastapi.testclient import TestClient

from app.extract import parse_deliverables
from app.models import Deliverable


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


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "app.db"))
    from app.main import app

    with TestClient(app) as c:
        assert c.post("/scan", follow_redirects=False).status_code == 303
        yield c


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

    r = client.post("/inquiry/msg_002/edit", data={"field": "deliverables", "value": "1 × Reel"})
    assert r.status_code == 200
    assert 'id="assessment"' in r.text

    after = _debug_row(client, "msg_002")
    assert after["quote_total"] == 102300.0
    assert "lowball" not in after["flags"]
    assert "conflict" in after["flags"]
    assert after["final_score"] <= 20

    page = client.get("/inquiry/msg_002").text
    assert 'value="1 × Reel"' in page
    assert "provenance-manual" in page


def test_bad_edit_shows_error_and_leaves_assessment_unchanged(client):
    r = client.post("/inquiry/msg_002/edit", data={"field": "deliverables", "value": "2 × Podcast"})
    assert r.status_code == 200
    assert "edit-error" in r.text and "Podcast" in r.text
    assert _debug_row(client, "msg_002")["quote_total"] == 264330.0


def test_edit_inputs_are_not_inside_a_form(client):
    """HTMX posts every input of an enclosing <form>; every edit input is named "value",
    so a wrapper form makes the server keep the last row's value instead of the edited one.
    """
    from html.parser import HTMLParser

    class EditInputsInForms(HTMLParser):
        def __init__(self):
            super().__init__()
            self.form_depth = 0
            self.edit_inputs = 0
            self.inside_form = []

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if tag == "form":
                self.form_depth += 1
            elif tag == "input" and a.get("hx-post", "").endswith("/edit"):
                self.edit_inputs += 1
                if self.form_depth:
                    self.inside_form.append(a.get("id"))

        def handle_endtag(self, tag):
            if tag == "form":
                self.form_depth -= 1

    parser = EditInputsInForms()
    parser.feed(client.get("/inquiry/msg_002").text)
    assert parser.edit_inputs >= 10
    assert parser.inside_form == []


def test_unknown_ids_return_404(client):
    assert client.get("/inquiry/nope").status_code == 404
    assert client.get("/creator/nope").status_code == 404
    assert client.post("/inquiry/nope/edit", data={"field": "brand", "value": "x"}).status_code == 404
