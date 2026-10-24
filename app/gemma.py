"""Gemma 4 on the Gemini API: field-note extraction and record merging (Tasks 2, 4, 6)."""
import datetime as dt
import json
import logging
import os
import time
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app import DATA_DIR, ROOT
from app import db
from app.schemas import EDITABLE_FIELDS, Extracted, ExtractionResult
from app.validator import missing_fields

log = logging.getLogger(__name__)

MODEL = os.getenv("GEMMA_MODEL", "gemma-4-26b-a4b-it")
FALLBACK_MODEL = "gemma-4-31b-it"
TIMEOUT_S = float(os.getenv("GEMMA_TIMEOUT_S", "30"))   # per request; a hung call fails, then retries
PROMPTS = ROOT / "app" / "prompts"
LOG_PATH = DATA_DIR / "logs" / "gemma.jsonl"

M = TypeVar("M", bound=BaseModel)
_client = None
_plain_json: set[str] = set()   # models that rejected JSON mode: go straight to plain JSON next time


class GemmaError(RuntimeError):
    pass


def _get_client():
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


# --- prompt building ---------------------------------------------------------

def _today() -> dt.date:
    return dt.datetime.now(db.TZ).date()


def _parcels_block() -> str:
    lines = []
    for p in db.get_parcels():
        lines.append(f"- {p['alias']}: crop {p['crop_key']} ({p['variety']}), {p['area_ha']} ha;"
                     f" spoken names: {', '.join(p['spoken_names'])}")
    return "\n".join(lines)


def _keys(type_: str) -> str:
    return ", ".join(v["key"] for v in db.get_vocabulary() if v["type"] == type_)


def _fewshot_block(n: int = 5) -> str:
    rows = db.recent_corrections(n)
    if not rows:
        return ""
    lines = ["## Past corrections (learn from these mistakes)"]
    for c in rows:
        lines.append(f'- Note ({c["lang"]}): "{c["transcript_original"]}" → field `{c["field"]}` was'
                     f' {c["before"]!r}, the correct value is {c["after"]!r}. Reason: {c["reason"]}')
    return "\n".join(lines)


def _common() -> dict:
    today = _today()
    return {
        "today": today.isoformat(),
        "weekday": today.strftime("%A"),
        "parcels": _parcels_block(),
        "activities": _keys("activity"),
        "crops": _keys("crop"),
        "pests": _keys("pest"),
    }


def build_extract_prompt(text: str, lang_hint: str | None) -> str:
    return (PROMPTS / "extract.md").read_text(encoding="utf-8").format(
        **_common(), lang_hint=lang_hint or "unknown", fewshot=_fewshot_block(), text=text)


def build_merge_prompt(current: Extracted, text: str) -> str:
    return (PROMPTS / "merge.md").read_text(encoding="utf-8").format(
        **_common(), record=current.model_dump_json(indent=2), text=text)


# --- model call --------------------------------------------------------------

def _log(entry: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry["ts"] = dt.datetime.now(db.TZ).isoformat(timespec="seconds")
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _parse(text: str, schema: type[M]) -> M:
    """The first JSON object in the reply, ignoring fences or text around it (Gemma sometimes adds
    a stray ``` even in JSON mode). Raises ValidationError if there is no valid object."""
    start = text.find("{")
    if start >= 0:
        try:
            obj, _ = json.JSONDecoder().raw_decode(text, start)
            return schema.model_validate(obj)
        except json.JSONDecodeError:
            pass
    return schema.model_validate_json(text.strip())


def _generate(model: str, prompt: str, schema: type[M], structured: bool) -> str:
    from google.genai import types
    http = types.HttpOptions(timeout=int(TIMEOUT_S * 1000))
    if structured:
        config = types.GenerateContentConfig(temperature=0, response_mime_type="application/json",
                                             response_schema=schema, http_options=http)
    else:  # fallback when the model rejects JSON mode: describe the schema in the prompt
        prompt += ("\n\nReply with only one JSON object matching this JSON schema, no other text:\n"
                   + json.dumps(schema.model_json_schema()))
        config = types.GenerateContentConfig(temperature=0, http_options=http)
    resp = _get_client().models.generate_content(model=model, contents=prompt, config=config)
    return resp.text or ""


def call(prompt: str, schema: type[M], kind: str) -> M:
    """Up to 3 attempts: MODEL, MODEL, FALLBACK_MODEL, each with a TIMEOUT_S limit. JSON mode
    first; if the API refuses the request (4xx), the same attempt retries once with plain JSON
    instructions and that model skips JSON mode from then on. Timeouts and 5xx move on."""
    errors = []
    for model in (MODEL, MODEL, FALLBACK_MODEL):
        modes = (False,) if model in _plain_json else (True, False)
        for structured in modes:
            raw, started, rejected = None, time.monotonic(), False
            try:
                raw = _generate(model, prompt, schema, structured)
                result = _parse(raw, schema)
                if not structured:
                    _plain_json.add(model)
                _log({"kind": kind, "model": model, "structured": structured, "seconds": _since(started),
                      "prompt": prompt, "response": raw, "ok": True})
                return result
            except ValidationError as e:     # model answered but not valid JSON: next attempt
                err = f"invalid JSON: {e.error_count()} errors"
            except Exception as e:           # API error or timeout
                err = f"{type(e).__name__}: {e}"
                rejected = 400 <= (getattr(e, "code", None) or 0) < 500   # e.g. JSON mode not supported
            _log({"kind": kind, "model": model, "structured": structured, "seconds": _since(started),
                  "prompt": prompt, "response": raw, "ok": False, "error": err})
            errors.append(f"{model} structured={structured}: {err}")
            log.warning("gemma %s failed: %s", kind, errors[-1])
            if not rejected:
                break  # plain-JSON mode only helps when the request itself was refused (4xx)
    raise GemmaError("; ".join(errors))


def _since(started: float) -> float:
    return round(time.monotonic() - started, 2)


# --- public API ----------------------------------------------------------------

def _clean(rec: Extracted) -> Extracted:
    aliases = {p["alias"] for p in db.get_parcels()}
    data = rec.model_dump()
    if data["parcel_alias"] not in aliases:
        data["parcel_alias"] = None
    cleaned = Extracted.model_validate(data)
    cleaned.missing_fields = missing_fields(cleaned)
    return cleaned


def extract(text: str, lang_hint: str | None, chat_id: int) -> ExtractionResult:
    """Transcript → one record per activity. chat_id is used for the language hint fallback."""
    hint = lang_hint or db.get_farmer_lang(chat_id)
    result = call(build_extract_prompt(text, hint), ExtractionResult, "extract")
    result.records = [_clean(r) for r in result.records]
    if not result.records:
        result.is_farm_activity = False
    return result


def merge(current: Extracted, text: str) -> Extracted:
    """Apply the farmer's answer or correction to a record; returns the full updated record."""
    updated = call(build_merge_prompt(current, text), Extracted, "merge")
    updated.lang = current.lang
    return _clean(updated)


def changed_fields(before: Extracted, after: Extracted) -> dict:
    """Editable fields whose value differs (what update_field should be called with)."""
    return {f: getattr(after, f) for f in EDITABLE_FIELDS if getattr(before, f) != getattr(after, f)}
