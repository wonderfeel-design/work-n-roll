"""Shared contract: seeding and the strict correction rules in app/db.py."""
import pytest
from pydantic import ValidationError

from app import db, seed
from app.schemas import Record


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    db.init_db()
    seed.seed()


def _draft(**kw) -> int:
    fields = dict(lang="es", activity_key="treatment", farmer_chat_id=1, date="2026-10-21",
                  parcel_alias="P5", product="Oxicloruro de cobre 50% WP", quantity=40, unit="kg",
                  transcript_original="Catorce kilos de cobre en los almendros.")
    return db.insert_record(Record(**(fields | kw)))


def test_seed_loads_reference_data_only():
    parcels = db.get_parcels()
    assert [p["alias"] for p in parcels] == ["P1", "P2", "P3", "P4", "P5"]
    assert parcels[1]["crop_key"] == "apple" and "второй участок" in parcels[1]["spoken_names"]
    assert parcels[0]["sigpac_ref"] == "25-120-0-0-7-45-1"
    assert db.list_records() == []
    assert db.recent_corrections() == []
    assert db.ui("saved", "ca") == "Desat. Gràcies!"
    assert db.label("crop", "almond", "ru") == "Миндаль"


def test_seed_is_idempotent():
    seed.seed()
    assert len(db.get_parcels()) == 5


def test_ui_falls_back_to_english_and_rejects_unknown_keys():
    assert db.ui("saved", "xx") == "Saved. Thank you!"
    with pytest.raises(KeyError):
        db.ui("no_such_key", "en")


def test_insert_creates_farmer_and_draft():
    rid = _draft()
    rec = db.get_record(rid)
    assert rec.status == "draft" and rec.created_at
    assert db.get_farmer(1)["chat_id"] == 1


def test_insert_rejects_non_draft_and_unknown_parcel():
    with pytest.raises(ValueError):
        db.insert_record(Record(lang="en", activity_key="other", farmer_chat_id=1,
                                transcript_original="x", status="validated"))
    with pytest.raises(db.IntegrityError):
        _draft(parcel_alias="P9")


def test_update_field_writes_correction_atomically():
    rid = _draft()
    db.update_field(rid, "quantity", "14", "Farmer said catorce (14)", "agronomist", reason_lang="en")
    assert db.get_record(rid).quantity == 14.0
    (c,) = db.corrections_for(rid)
    assert (c["field"], c["before"], c["after"], c["corrected_by"]) == ("quantity", "40", "14", "agronomist")
    assert db.recent_corrections(1)[0]["transcript_original"].startswith("Catorce")


@pytest.mark.parametrize("field, value, reason, by", [
    ("status", "validated", "r", "agronomist"),   # not editable
    ("quantity", "14", "  ", "agronomist"),       # empty reason
    ("quantity", "14", "r", "robot"),             # unknown corrector
    ("quantity", "40", "r", "agronomist"),        # no change
    ("date", "21/10/2026", "r", "farmer"),        # not ISO
    ("activity_key", "dancing", "r", "farmer"),   # not an activity
    ("quantity", "-1", "r", "farmer"),            # negative
])
def test_update_field_rejects_bad_corrections(field, value, reason, by):
    rid = _draft()
    with pytest.raises((ValueError, ValidationError)):
        db.update_field(rid, field, value, reason, by)
    assert db.corrections_for(rid) == []


def test_correction_needs_existing_record():
    with pytest.raises(KeyError):
        db.update_field(999, "quantity", "1", "r", "farmer")
    with pytest.raises(db.IntegrityError), db._connect() as conn:
        conn.execute("INSERT INTO corrections (record_id, field, reason, corrected_by, timestamp, before, after)"
                     " VALUES (999, 'quantity', 'r', 'farmer', 'now', '1', '2')")


def test_corrections_are_append_only_and_records_never_deleted():
    rid = _draft()
    db.update_field(rid, "quantity", "14", "typo", "farmer")
    for statement in ("DELETE FROM corrections", "UPDATE corrections SET after = '99'", "DELETE FROM field_log"):
        with pytest.raises(db.IntegrityError), db._connect() as conn:  # one transaction each
            conn.execute(statement)
    cid = db.corrections_for(rid)[0]["id"]
    db.set_fewshot(cid, False)
    assert db.recent_corrections() == []


def test_status_flow():
    rid = _draft()
    with pytest.raises(ValueError):
        db.update_status(rid, "validated")               # draft cannot jump to validated
    db.update_status(rid, "farmer_confirmed", "farmer")
    db.update_status(rid, "needs_review")
    with pytest.raises(ValueError):
        db.update_status(rid, "corrected", "agronomist")  # no agronomist correction yet
    db.update_field(rid, "quantity", "14", "heard 40, said 14", "agronomist")
    db.update_status(rid, "corrected", "agronomist")
    rec = db.get_record(rid)
    assert (rec.status, rec.confirmed_by, rec.corrected_by) == ("corrected", "farmer", "agronomist")


def test_discarded_is_final():
    rid = _draft()
    db.update_status(rid, "discarded")
    with pytest.raises(ValueError):
        db.update_status(rid, "draft")
    with pytest.raises(ValueError):
        db.update_field(rid, "quantity", "1", "r", "farmer")


def test_farmer_lang():
    assert db.get_farmer_lang(7) is None
    db.set_farmer_name(7, "Joan")
    db.set_farmer_lang(7, "ca")
    assert db.get_farmer_lang(7) == "ca" and db.get_farmer(7)["name"] == "Joan"


# --- new plots ---------------------------------------------------------------------

from app.schemas import ParcelDraft  # noqa: E402


def test_add_parcel_gets_next_alias_and_is_used_everywhere():
    alias = db.add_parcel(ParcelDraft(spoken_names=["els cirerers", "cherry block"], crop_key="almond",
                                      area_ha=1.5, variety="Lauranne", irrigation="regadiu",
                                      sigpac_ref="25-120-0-0-7-50-1"))
    assert alias == "P6"
    p6 = next(p for p in db.get_parcels() if p["alias"] == "P6")
    assert p6["spoken_names"] == ["els cirerers", "cherry block"] and p6["area_ha"] == 1.5
    assert (p6["sigpac_ref"], p6["sigpac_poligon"], p6["campaign"]) == ("25-120-0-0-7-50-1", 7, "2026")
    rid = _draft(parcel_alias="P6")                       # records can point at it right away
    assert db.get_record(rid).parcel_alias == "P6"
    assert db.add_parcel(ParcelDraft(spoken_names=["la vinya"], crop_key="almond", area_ha=2)) == "P7"


def test_add_parcel_new_crop_needs_its_names():
    with pytest.raises(ValueError, match="not in the vocabulary"):
        db.add_parcel(ParcelDraft(spoken_names=["els cirerers"], crop_key="cherry", area_ha=1.5))
    assert len(db.get_parcels()) == 5                     # nothing half-saved
    db.add_parcel(ParcelDraft(spoken_names=["els cirerers"], crop_key="cherry", area_ha=1.5,
                              crop_labels={"en": "Cherry", "ca": "Cirerer", "es": "Cerezo", "ru": "Вишня"}))
    assert db.label("crop", "cherry", "ca") == "Cirerer"


@pytest.mark.parametrize("draft, error", [
    (dict(spoken_names=[], crop_key="almond", area_ha=1), "spoken_names"),
    (dict(spoken_names=["x"], crop_key=None, area_ha=1), "crop_key"),
    (dict(spoken_names=["x"], crop_key="almond", area_ha=None), "area_ha"),
])
def test_add_parcel_requires_name_crop_area(draft, error):
    with pytest.raises(ValueError, match=error):
        db.add_parcel(ParcelDraft(**draft))


def test_add_parcel_rejects_a_name_another_plot_has():
    with pytest.raises(db.NameTaken) as e:
        db.add_parcel(ParcelDraft(spoken_names=["new one", "Les Peres"], crop_key="pear", area_ha=1))
    assert (e.value.name, e.value.alias) == ("Les Peres", "P3")
    with pytest.raises(db.NameTaken):
        db.add_parcel(ParcelDraft(spoken_names=["p2"], crop_key="pear", area_ha=1))


@pytest.mark.parametrize("bad", [dict(area_ha=0), dict(area_ha=-1), dict(sigpac_ref="25-120-7"),
                                 dict(irrigation="flood")])
def test_parcel_draft_validation(bad):
    with pytest.raises(ValidationError):
        ParcelDraft(spoken_names=["x"], crop_key="almond", **({"area_ha": 1} | bad))
