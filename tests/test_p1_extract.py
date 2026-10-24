"""Task 2: Gemma extractor. Live tests need GEMINI_API_KEY (pytest -m gemma); the rest run offline."""
import datetime as dt
import json
import os

import pytest

from app import db, gemma, seed
from app.schemas import Extracted


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(gemma, "LOG_PATH", tmp_path / "gemma.jsonl")
    db.init_db()
    seed.seed()


def _today() -> dt.date:
    return dt.datetime.now(db.TZ).date()


# --- live Gemma (Task 2 "done when") -------------------------------------------

LIVE = [
    ("Ahir vaig tirar coure a la parcel·la 3, quatre quilos per les dues hectàrees.",
     "P3", "treatment", 4, "kg", "ca", -1),
    ("Catorce kilos de cobre en los almendros, toda la parcela.",
     "P5", "treatment", 14, "kg", "es", None),
    ("Watered the Gala block today, about 120 cubic metres.",
     "P2", "irrigation", 120, "m3", "en", 0),
    ("Сегодня внёс сто пятьдесят килограммов NPK пятнадцать-пятнадцать-пятнадцать под яблони на втором участке.",
     "P2", "fertilization", 150, "kg", "ru", 0),
]


@pytest.mark.gemma
@pytest.mark.skipif(not os.getenv("GEMINI_API_KEY"), reason="needs GEMINI_API_KEY")
@pytest.mark.parametrize("text,alias,activity,qty,unit,lang,days", LIVE)
def test_extract_live(text, alias, activity, qty, unit, lang, days):
    result = gemma.extract(text, None, chat_id=1)
    assert result.is_farm_activity and len(result.records) == 1
    r = result.records[0]
    assert (r.parcel_alias, r.activity_key, r.quantity, r.unit, r.lang) == (alias, activity, qty, unit, lang)
    if days is not None:
        assert r.date == (_today() + dt.timedelta(days=days)).isoformat()


# --- offline: prompt, cleaning, retry / fallback --------------------------------

def test_prompt_has_live_data_and_keys_only():
    p = gemma.build_extract_prompt("hola", "es")
    assert _today().isoformat() in p
    assert "P3:" in p and "les peres" in p
    assert "treatment" in p and "powdery_mildew" in p
    assert "Tractament fitosanitari" not in p          # keys, never translations
    assert "Past corrections" not in p                  # no corrections yet


def test_prompt_includes_recent_corrections():
    from app.schemas import Record
    rid = db.insert_record(Record(lang="es", activity_key="treatment", farmer_chat_id=1, parcel_alias="P5",
                                  quantity=40, unit="kg", transcript_original="Catorce kilos de cobre"))
    db.update_field(rid, "quantity", 14, reason="catorce = 14", by="agronomist")
    p = gemma.build_extract_prompt("x", None)
    assert "Past corrections" in p and "Catorce kilos de cobre" in p and "'14'" in p


def _answer(**rec) -> str:
    base = dict(lang="en", activity_key="treatment", date=_today().isoformat(), parcel_alias="P3",
                product="copper", quantity=40, unit="L")
    return json.dumps({"records": [base | rec], "is_farm_activity": True})


def test_extract_recomputes_missing_and_drops_unknown_parcel(monkeypatch):
    monkeypatch.setattr(gemma, "_generate", lambda *a: _answer(parcel_alias="P9", missing_fields=[]))
    r = gemma.extract("Sprayed copper today, 40 litres", None, 1).records[0]
    assert r.parcel_alias is None and r.missing_fields == ["parcel_alias"]


def test_retry_then_fallback_model(monkeypatch):
    calls = []

    def fake(model, prompt, schema, structured):
        calls.append((model, structured))
        if model == gemma.FALLBACK_MODEL:
            return _answer()
        return "not json"

    monkeypatch.setattr(gemma, "_generate", fake)
    assert gemma.extract("x", None, 1).records[0].quantity == 40
    assert calls == [(gemma.MODEL, True), (gemma.MODEL, True), (gemma.FALLBACK_MODEL, True)]
    lines = (gemma.LOG_PATH).read_text().splitlines()
    assert len(lines) == 3 and json.loads(lines[-1])["ok"] is True


def test_plain_json_when_json_mode_rejected(monkeypatch):
    def fake(model, prompt, schema, structured):
        if structured:
            raise RuntimeError("400 JSON mode is not enabled for this model")
        return "```json\n" + _answer() + "\n```"

    monkeypatch.setattr(gemma, "_generate", fake)
    assert gemma.extract("x", None, 1).records[0].parcel_alias == "P3"


def test_all_attempts_fail(monkeypatch):
    monkeypatch.setattr(gemma, "_generate", lambda *a: "nope")
    with pytest.raises(gemma.GemmaError):
        gemma.extract("x", None, 1)


def test_no_records_means_not_farm_activity(monkeypatch):
    monkeypatch.setattr(gemma, "_generate", lambda *a: json.dumps({"records": [], "is_farm_activity": True}))
    assert gemma.extract("hello", None, 1).is_farm_activity is False


def test_merge_keeps_lang_and_changed_fields(monkeypatch):
    cur = Extracted(lang="ca", activity_key="treatment", parcel_alias="P3", quantity=40, unit="kg",
                    date=_today().isoformat(), product="coure")
    new = cur.model_dump() | {"quantity": 14, "lang": "en"}
    monkeypatch.setattr(gemma, "_generate", lambda *a: json.dumps(new))
    merged = gemma.merge(cur, "no, eren 14")
    assert merged.lang == "ca"
    assert gemma.changed_fields(cur, merged) == {"quantity": 14}
