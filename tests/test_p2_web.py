"""Task 3: agronomist console API. Uses a temporary database; records are created the way the bot does."""
import pytest
from fastapi.testclient import TestClient

from app import db, seed, web
from app.schemas import Record

AUTH = ("admin", "admin")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("WEB_USER", raising=False)
    monkeypatch.delenv("WEB_PASSWORD", raising=False)
    db.init_db()
    seed.seed()
    with TestClient(web.app) as c:
        yield c


def _record(status: str = "needs_review", **kw) -> int:
    """A record as the bot leaves it: draft -> farmer_confirmed -> judged."""
    fields = dict(lang="es", activity_key="treatment", farmer_chat_id=42, farmer_name="María",
                  date="2026-10-21", parcel_alias="P5", product="Oxicloruro de cobre 50% WP",
                  target_pest_key="fungal_general", quantity=40, unit="kg",
                  transcript_original="Catorce kilos de cobre en los almendros, toda la parcela.")
    rid = db.insert_record(Record(**(fields | kw)))
    if status != "draft":
        db.update_status(rid, "farmer_confirmed", "farmer")
        db.update_status(rid, status)
    return rid


def test_login_required(client):
    assert client.get("/api/records").status_code == 401
    assert client.get("/api/records", auth=("admin", "wrong")).status_code == 401
    assert client.get("/", auth=("x", "admin")).status_code == 401
    assert client.get("/api/health").json() == {"ok": True}  # Docker health check, no login


def test_records_are_enriched(client):
    rid = _record()
    (r,) = client.get("/api/records", auth=AUTH).json()
    assert r["id"] == rid and r["record_id"] == f"R{rid:04d}"
    assert r["sigpac_ref"] == "25-233-0-0-3-102-1"
    assert (r["crop_key"], r["crop_ca"], r["crop_en"]) == ("almond", "Ametller", "Almond")
    assert (r["activity_ca"], r["activity_en"]) == ("Tractament fitosanitari", "Phytosanitary treatment")
    assert (r["crop_es"], r["activity_es"]) == ("Almendro", "Tratamiento fitosanitario")
    assert r["target_pest_en"] == "Fungal diseases (general)"
    assert r["dose_per_ha"] == round(40 / 4.2, 3)  # no area spoken: the parcel's area is used
    assert r["transcript_original"].startswith("Catorce")


def test_records_newest_first(client):
    first, second = _record(), _record()
    assert [r["id"] for r in client.get("/api/records", auth=AUTH).json()] == [second, first]


def test_patch_creates_correction_and_marks_corrected(client):
    rid = _record()
    r = client.patch(f"/api/records/{rid}", auth=AUTH,
                     json={"field": "quantity", "value": "14", "reason": "Farmer said catorce (14)",
                           "by": "agronomist"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["quantity"] == 14 and body["status"] == "corrected" and body["corrected_by"] == "agronomist"
    (c,) = body["corrections"]
    assert (c["field"], c["before"], c["after"], c["reason"]) == ("quantity", "40", "14", "Farmer said catorce (14)")
    assert client.get("/api/corrections", auth=AUTH).json()[0]["record_id"] == rid
    # survives a reload
    assert client.get(f"/api/records/{rid}", auth=AUTH).json()["status"] == "corrected"


@pytest.mark.parametrize("payload, code", [
    ({"field": "status", "value": "validated", "reason": "r"}, 400),        # not in the whitelist
    ({"field": "transcript_original", "value": "x", "reason": "r"}, 400),   # never editable
    ({"field": "quantity", "value": "14", "reason": "r", "by": "farmer"}, 400),
    ({"field": "quantity", "value": "14", "reason": "  "}, 422),            # reason required
    ({"field": "quantity", "value": "40", "reason": "r"}, 422),             # no change
    ({"field": "quantity", "value": "-3", "reason": "r"}, 422),
    ({"field": "date", "value": "21/10/2026", "reason": "r"}, 422),
    ({"field": "activity_key", "value": "dancing", "reason": "r"}, 422),
])
def test_patch_rejects_bad_corrections(client, payload, code):
    rid = _record()
    assert client.patch(f"/api/records/{rid}", auth=AUTH, json=payload).status_code == code
    rec = client.get(f"/api/records/{rid}", auth=AUTH).json()
    assert rec["corrections"] == [] and rec["status"] == "needs_review"


def test_patch_unknown_parcel_is_rejected(client):
    rid = _record()
    r = client.patch(f"/api/records/{rid}", auth=AUTH, json={"field": "parcel_alias", "value": "P9", "reason": "r"})
    assert r.status_code == 422
    assert client.get(f"/api/records/{rid}", auth=AUTH).json()["corrections"] == []


def test_patch_on_farmer_draft_is_refused_without_side_effects(client):
    rid = _record(status="draft")
    r = client.patch(f"/api/records/{rid}", auth=AUTH, json={"field": "quantity", "value": "14", "reason": "r"})
    assert r.status_code == 409
    rec = client.get(f"/api/records/{rid}", auth=AUTH).json()
    assert rec["quantity"] == 40 and rec["corrections"] == []


def test_approve(client):
    rid = _record()
    r = client.post(f"/api/records/{rid}/approve", auth=AUTH)
    assert r.status_code == 200 and r.json()["status"] == "validated"
    assert client.post(f"/api/records/{rid}/approve", auth=AUTH).status_code == 409  # already validated
    assert client.post(f"/api/records/{_record(status='draft')}/approve", auth=AUTH).status_code == 409


def test_missing_record(client):
    assert client.get("/api/records/999", auth=AUTH).status_code == 404
    assert client.patch("/api/records/999", auth=AUTH,
                        json={"field": "quantity", "value": "1", "reason": "r"}).status_code == 404
    assert client.post("/api/records/999/approve", auth=AUTH).status_code == 404


def test_reference_data(client):
    assert len(client.get("/api/parcels", auth=AUTH).json()) == 5
    assert any(v["key"] == "almond" for v in client.get("/api/vocabulary", auth=AUTH).json())


def test_branding_and_public_icons(client):
    r = client.get("/api/records")
    assert r.status_code == 401 and r.headers["www-authenticate"] == 'Basic realm="Work\'n\'Roll"'
    for name in ("favicon-64.png", "icon-512.png", "logo.png"):      # browsers fetch these without the login
        icon = client.get(f"/static/{name}")
        assert icon.status_code == 200 and icon.headers["content-type"] == "image/png", name
    page = client.get("/", auth=AUTH).text
    assert "<title>Work'n'Roll · Epic Reporting</title>" in page and 'href="static/favicon-64.png"' in page
    assert "Field Voice" not in page
    assert client.get("/static/../app/db.py").status_code == 404           # only the icon folder is public


def test_add_parcel_from_the_console(client):
    body = {"spoken_names": ["els cirerers", "cherry block"], "crop_key": "cherry", "area_ha": 1.5,
            "crop_labels": {"en": "Cherry", "ca": "Cirerer", "es": "Cerezo", "ru": "Вишня"},
            "variety": "Lapins", "irrigation": "regadiu"}
    assert client.post("/api/parcels", json=body).status_code == 401
    r = client.post("/api/parcels", auth=AUTH, json=body)
    assert r.status_code == 201, r.text
    assert (r.json()["alias"], r.json()["crop_key"]) == ("P6", "cherry")
    assert any(v["key"] == "cherry" for v in client.get("/api/vocabulary", auth=AUTH).json())
    # same name again -> 409; missing area -> 422; bad irrigation -> 422; nothing added
    assert client.post("/api/parcels", auth=AUTH, json=body | {"spoken_names": ["Cherry Block"]}).status_code == 409
    assert client.post("/api/parcels", auth=AUTH, json=body | {"spoken_names": ["x"], "area_ha": None}).status_code == 422
    assert client.post("/api/parcels", auth=AUTH, json=body | {"spoken_names": ["y"], "irrigation": "flood"}).status_code == 422
    assert [p["alias"] for p in client.get("/api/parcels", auth=AUTH).json()] == ["P1", "P2", "P3", "P4", "P5", "P6"]
    # a record can use the new plot straight away
    rid = _record(parcel_alias="P6")
    assert client.get(f"/api/records/{rid}", auth=AUTH).json()["crop_en"] == "Cherry"
