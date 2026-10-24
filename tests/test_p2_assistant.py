"""Task 6: voice assistant. Offline tests fake the LLM and TTS; `gemma`-marked tests call the Gemini API."""
import base64
import os

import pytest
from fastapi.testclient import TestClient

from app import assistant, db, seed, voice, web
from app.schemas import Record

AUTH = ("admin", "admin")
CU = "Oxicloruro de cobre 50% WP"


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(assistant, "LOG_PATH", tmp_path / "assistant.jsonl")
    monkeypatch.delenv("WEB_USER", raising=False)
    monkeypatch.delenv("WEB_PASSWORD", raising=False)
    db.init_db()
    seed.seed()


def _add(date, parcel, activity, product, qty, unit, area=None, status="auto_approved"):
    rid = db.insert_record(Record(lang="es", date=date, parcel_alias=parcel, activity_key=activity, product=product,
                                  quantity=qty, unit=unit, area_ha=area, farmer_chat_id=1, transcript_original="x"))
    if status != "draft":
        db.update_status(rid, "farmer_confirmed", "farmer")
        db.update_status(rid, status)
    return rid


def _farm():
    _add("2026-09-12", "P5", "treatment", CU, 10, "kg")             # 10 / 4.2 ha = 2.38 kg/ha
    _add("2026-10-21", "P5", "treatment", CU, 14, "kg")             # 14 / 4.2 ha = 3.33 kg/ha
    _add("2026-10-02", "P3", "treatment", CU, 4, "kg", 2)           # 2 kg/ha
    _add("2026-10-05", "P2", "irrigation", None, 110, "m3", 1.8)
    _add("2026-10-22", "P2", "irrigation", None, 120, "m3", 1.8)
    _add("2026-10-24", "P1", "treatment", "Glyphosate", 99, "l", status="discarded")


def test_aggregates_are_exact():
    _farm()
    rows = assistant._rows()
    assert all(r["product"] != "Glyphosate" for r in rows)         # discarded records are left out
    by_product = {g["group"]: g for g in assistant._aggregate(rows, lambda r: r["product"])}
    cu = by_product[CU]
    assert (cu["applications"], cu["total"], cu["unit"]) == (3, 28.0, "kg")
    assert cu["avg_dose_per_ha"] == round((10 / 4.2 + 14 / 4.2 + 4 / 2) / 3, 2)
    assert (cu["first"], cu["last"]) == ("2026-09-12", "2026-10-21")
    on_p5 = {g["group"]: g for g in assistant._aggregate(rows, lambda r: f"{r['product']} on {r['parcel']}" if r["product"] else None)}
    assert on_p5[f"{CU} on P5"]["total"] == 24.0
    water = {g["group"]: g for g in assistant._aggregate(rows, lambda r: f"{r['activity']} on {r['parcel']}")}
    assert water["irrigation on P2"]["total"] == 230.0


def test_prompt_has_language_data_and_history():
    _farm()
    p = assistant.build_prompt("I quant a les peres?", "ca",
                               [{"role": "user", "text": "Quant coure als ametllers?"}, {"role": "assistant", "text": "24 quilos."}])
    assert "Answer in Catalan" in p and "P5: almond" in p and '"total": 24.0' in p
    assert "Farmer: Quant coure als ametllers?" in p and "Assistant: 24 quilos." in p
    assert p.rstrip().endswith("I quant a les peres?\n\nAnswer:")


def test_answer_is_cleaned_for_speech(monkeypatch):
    class Resp:
        text = "**You used** 24 kilos\n of copper."
    class Models:
        @staticmethod
        def generate_content(**kw):
            return Resp()
    monkeypatch.setattr(assistant, "_get_client", lambda: type("C", (), {"models": Models}))
    assert assistant.answer("How much copper?", "en") == "You used 24 kilos of copper."


def test_ask_endpoint_with_text(monkeypatch, tmp_path):
    seen = {}
    def fake_answer(q, lang, history):
        seen.update(q=q, lang=lang, history=history)
        return "Vint-i-quatre quilos."
    mp3 = tmp_path / "a.mp3"
    mp3.write_bytes(b"ID3fake")
    monkeypatch.setattr(assistant, "answer", fake_answer)
    monkeypatch.setattr(voice, "list_voices", lambda: ({"voice_id": "v1", "category": "premade"},))
    monkeypatch.setattr(voice, "tts_mp3", lambda text, lang, voice_id=None: seen.update(voice=voice_id) or mp3)
    with TestClient(web.app) as c:
        assert c.post("/api/ask", data={"text": "hola"}).status_code == 401
        r = c.post("/api/ask", auth=AUTH, data={"text": "Quant coure?", "lang": "ca", "voice_id": "v1",
                                                 "history": '[{"role": "user", "text": "hola"}]'})
        assert r.status_code == 200, r.text
        body = r.json()
        assert (body["question"], body["lang"], body["answer"]) == ("Quant coure?", "ca", "Vint-i-quatre quilos.")
        assert base64.b64decode(body["audio"]) == b"ID3fake" and "total_ms" in body["timings"]
        assert seen["history"] == [{"role": "user", "text": "hola"}] and seen["voice"] == "v1"
        # unknown voice ids fall back to the default voice; empty questions are refused
        c.post("/api/ask", auth=AUTH, data={"text": "x", "voice_id": "not-a-voice"})
        assert seen["voice"] is None
        assert c.post("/api/ask", auth=AUTH, data={"text": "  "}).status_code == 422


def test_ask_reports_llm_failure(monkeypatch):
    def broken(*a):
        raise assistant.AssistantError("503 overloaded")
    monkeypatch.setattr(assistant, "answer", broken)
    with TestClient(web.app) as c:
        r = c.post("/api/ask", auth=AUTH, data={"text": "hola"})
    assert r.status_code == 502 and "503 overloaded" in r.json()["detail"]


@pytest.mark.gemma
@pytest.mark.skipif(not os.getenv("GEMINI_API_KEY"), reason="needs GEMINI_API_KEY")
@pytest.mark.parametrize("lang, question, expected", [
    ("en", "How much copper did I use on the almonds?", "24"),
    ("ca", "Quanta aigua he regat a la parcel·la 2?", "230"),
    ("en", "How much glyphosate did I buy?", None),               # discarded record: must not count
])
def test_live_answers(lang, question, expected):
    _farm()
    text = assistant.answer(question, lang, [])
    if expected:
        assert expected in text, text
    else:
        assert "99" not in text, text


# --- model chain and daily quotas -------------------------------------------------

QUOTA_429 = ("429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'details': [{'quotaId': "
             "'GenerateRequestsPerDayPerProjectPerModel-FreeTier'}, {'retryDelay': '55427s'}]}}")


def _fake_client(monkeypatch, behaviour):
    """behaviour: model -> text to answer, or an Exception to raise. Returns the list of models called."""
    calls = []

    class Models:
        @staticmethod
        def generate_content(model, contents, config):
            calls.append(model)
            out = behaviour[model]
            if isinstance(out, Exception):
                raise out
            return type("R", (), {"text": out})()

    monkeypatch.setattr(assistant, "_get_client", lambda: type("C", (), {"models": Models}))
    monkeypatch.setattr(assistant, "_exhausted", {})
    monkeypatch.setattr(assistant, "MODELS", ("flash", "lite", "gemma-x"))
    return calls


def test_quota_exhausted_model_is_skipped_until_reset(monkeypatch):
    calls = _fake_client(monkeypatch, {"flash": RuntimeError(QUOTA_429), "lite": "24 kilos.", "gemma-x": "x"})
    assert assistant.answer("q", "en") == "24 kilos."
    assert assistant.answer("q", "en") == "24 kilos."
    assert calls == ["flash", "lite", "lite"]                       # flash not retried after its 429
    assert assistant._exhausted["flash"] > assistant.time.time() + 15 * 3600


def test_other_errors_fall_through_without_skipping(monkeypatch):
    calls = _fake_client(monkeypatch, {"flash": RuntimeError("503 UNAVAILABLE"), "lite": "ok", "gemma-x": "x"})
    assistant.answer("q", "en")
    assistant.answer("q", "en")
    assert calls == ["flash", "lite", "flash", "lite"] and assistant._exhausted == {}


def test_all_models_exhausted(monkeypatch):
    _fake_client(monkeypatch, {m: RuntimeError(QUOTA_429) for m in ("flash", "lite", "gemma-x")})
    with pytest.raises(assistant.AssistantError, match="daily quota used up"):
        assistant.answer("q", "en")
    with pytest.raises(assistant.AssistantError, match="enable billing"):
        assistant.answer("q", "en")
