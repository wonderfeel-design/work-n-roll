"""Task 3: rule-based judge."""
import datetime as dt

import pytest

from app import db, seed, validator
from app.schemas import Record


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    seed.seed()


def _today(days: int = 0) -> str:
    return (dt.datetime.now(db.TZ).date() + dt.timedelta(days=days)).isoformat()


def _rec(**kw) -> Record:
    base = dict(lang="ca", activity_key="treatment", farmer_chat_id=1, date=_today(-1), parcel_alias="P3",
                crop_spoken=None, product="coure", quantity=4, unit="kg", area_ha=2,
                transcript_original="Ahir vaig tirar coure a la parcel·la 3, quatre quilos per les dues hectàrees.")
    return Record(**(base | kw))


def test_r0001_style_passes():
    score, reason = validator.validate(_rec())
    assert score >= validator.THRESHOLD and reason == "all checks passed"
    assert validator.status_for(score) == "auto_approved"


def test_r0004_style_40kg_copper_on_p5_needs_review():
    rec = _rec(lang="es", parcel_alias="P5", quantity=40, area_ha=None, crop_spoken="almendros",
               product="cobre", transcript_original="Cuarenta kilos de cobre en los almendros.")
    score, reason = validator.validate(rec)
    assert score < validator.THRESHOLD and "dose" in reason
    assert validator.status_for(score) == "needs_review"


def test_dose_uses_parcel_area_when_not_said():
    assert validator.dose_per_ha(_rec(parcel_alias="P5", quantity=42, area_ha=None)) == pytest.approx(10)


@pytest.mark.parametrize("spoken,key", [("almendros", "almond"), ("яблони", "apple"), ("les peres", "pear"),
                                        ("Gala block", None), ("peaches", "peach"), (None, None)])
def test_crop_key_for(spoken, key):
    assert validator.crop_key_for(spoken) == key


def test_each_penalty():
    assert validator.validate(_rec(crop_spoken="almendros"))[0] == 0.7      # P3 is pear
    assert validator.validate(_rec(date=_today(3)))[0] == 0.7
    assert validator.validate(_rec(target_pest_key="unknown"))[0] == 0.8
    assert validator.validate(_rec(product=None, parcel_alias=None, quantity=None))[0] == 0.7
    score, reason = validator.validate(_rec(quantity=400, date=_today(2), target_pest_key="unknown",
                                            parcel_alias=None, product=None))
    assert score == 0.0 and "future" in reason


def test_missing_fields_rules():
    assert validator.missing_fields(_rec(parcel_alias=None, quantity=None)) == ["parcel_alias", "quantity"]
    assert validator.missing_fields(_rec(activity_key="irrigation", product=None, quantity=None)) == []
