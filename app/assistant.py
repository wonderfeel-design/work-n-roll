"""Voice Q&A over the field log (Person 2, Task 6).

    answer(question, lang, history) -> spoken-style answer text in `lang`

The model never queries the database itself: this module computes the numbers in Python (totals, counts,
average dose per hectare by product, parcel and month) and hands the model the records plus those
aggregates. It only reads and phrases, so arithmetic is exact and the database stays read-only.

Models: ASSISTANT_MODELS, tried in order (default gemini-3.5-flash, gemini-3.1-flash-lite,
gemini-3.5-flash-lite, then Gemma 4). Flash answers in ~1.5-2 s with minimal thinking. Gemma answers correctly
too but thinks for 12-18 s on every question, which can't be switched off on the Gemini API: too slow for a
spoken conversation, so it is the last resort. A model that reports its daily free quota used up is skipped
until the quota resets. The bot's extraction still uses Gemma.
"""
import datetime as dt
import json
import logging
import os
import re
import time
from collections import defaultdict

from app import DATA_DIR, db

log = logging.getLogger(__name__)

# Tried in order. The free tier allows ~20 requests per day *per model*, so several Flash models with
# separate allowances keep the assistant answering; Gemma last (slow, but rarely out of quota).
MODELS = tuple(m.strip() for m in (os.getenv("ASSISTANT_MODELS") or
               "gemini-3.5-flash,gemini-3.1-flash-lite,gemini-3.5-flash-lite,gemma-4-26b-a4b-it").split(",") if m.strip())
TIMEOUT_S = float(os.getenv("ASSISTANT_TIMEOUT_S", "15"))   # per Gemini model; Gemma gets GEMMA_TIMEOUT_S
GEMMA_TIMEOUT_S = float(os.getenv("GEMMA_TIMEOUT_S", "30"))
_exhausted: dict[str, float] = {}   # model -> time.time() when its daily quota resets
LOG_PATH = DATA_DIR / "logs" / "assistant.jsonl"
LANG_NAMES = {"en": "English", "ru": "Russian", "ca": "Catalan", "es": "Spanish"}
HISTORY_TURNS = 6

_client = None


class AssistantError(RuntimeError):
    pass


def _get_client():
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


# --- data context ------------------------------------------------------------------

def _rows() -> list[dict]:
    """Every record that isn't discarded, with the parcel's crop and area filled in."""
    parcels = {p["alias"]: p for p in db.get_parcels()}
    out = []
    for r in db.list_records(limit=100_000):
        if r.status == "discarded":
            continue
        p = parcels.get(r.parcel_alias, {})
        area = r.area_ha or p.get("area_ha")
        out.append({
            "id": f"R{r.id:04d}", "date": r.date, "parcel": r.parcel_alias, "crop": p.get("crop_key"),
            "activity": r.activity_key, "product": r.product, "target": r.target_pest_key,
            "quantity": r.quantity, "unit": r.unit, "area_ha": area,
            "dose_per_ha": round(r.quantity / area, 2) if r.quantity is not None and area else None,
            "status": r.status, "notes": r.notes_en,
        })
    return sorted(out, key=lambda x: (x["date"] or "", x["id"]))


def _aggregate(rows: list[dict], key) -> list[dict]:
    """Group rows that have a quantity by key(row) + unit: total, count, average dose per ha, dates."""
    groups = defaultdict(list)
    for r in rows:
        if r["quantity"] is not None and (k := key(r)):
            groups[(k, r["unit"])].append(r)
    out = []
    for (k, unit), rs in sorted(groups.items(), key=lambda kv: str(kv[0])):
        doses = [r["dose_per_ha"] for r in rs if r["dose_per_ha"] is not None]
        dates = sorted(r["date"] for r in rs if r["date"])
        out.append({"group": k, "unit": unit, "applications": len(rs),
                    "total": round(sum(r["quantity"] for r in rs), 2),
                    "avg_dose_per_ha": round(sum(doses) / len(doses), 2) if doses else None,
                    "first": dates[0] if dates else None, "last": dates[-1] if dates else None})
    return out


def build_context() -> str:
    rows = _rows()
    parcels = [f"{p['alias']}: {p['crop_key']} ({p['variety']}), {p['area_ha']} ha, spoken as "
               f"{', '.join(p['spoken_names'])}" for p in db.get_parcels()]
    sections = {
        "Parcels": "\n".join(parcels),
        "Totals by product (all parcels)": _aggregate(rows, lambda r: r["product"]),
        "Totals by product and parcel": _aggregate(rows, lambda r: f"{r['product']} on {r['parcel']}" if r["product"] else None),
        "Totals by activity and parcel": _aggregate(rows, lambda r: f"{r['activity']} on {r['parcel']}"),
        "Totals by product and month": _aggregate(rows, lambda r: f"{r['product']} in {r['date'][:7]}" if r["product"] and r["date"] else None),
        "All records (oldest first)": rows,
    }
    parts = []
    for title, body in sections.items():
        if not isinstance(body, str):
            body = "\n".join(json.dumps(x, ensure_ascii=False) for x in body) or "(none)"
        parts.append(f"## {title}\n{body}")
    return "\n\n".join(parts)


PROMPT = """You are the voice assistant of a farm's field log. The farmer or agronomist asks about products
applied, quantities, doses and work done. Answer ONLY from the data below; if the data doesn't contain the
answer, say so briefly. The farm records what was APPLIED in the field, not what was bought: treat
"bought" or "purchased" as "used".

Rules:
- Answer in {language}. Product names stay exactly as written in the data.
- This is spoken aloud: 1 to 3 short sentences, no lists, no markdown, no record ids, no JSON keys.
- Use the precomputed totals and averages; do not do your own arithmetic when a total exists.
- Round to at most one decimal. Say units in words (kilos, litres, tonnes, cubic metres, hectares).
- Records with status draft or needs_review are not final; mention it only if it matters for the answer.
- Today is {today} (Europe/Madrid).

# Data
{context}

# Conversation so far
{history}

# Question
{question}

Answer:"""


def build_prompt(question: str, lang: str, history: list[dict] | None = None) -> str:
    turns = [f"{'Farmer' if h.get('role') == 'user' else 'Assistant'}: {h.get('text', '')}"
             for h in (history or [])[-HISTORY_TURNS:] if h.get("text")]
    return PROMPT.format(language=LANG_NAMES.get(lang, "English"), today=dt.datetime.now(db.TZ).date(),
                         context=build_context(), history="\n".join(turns) or "(start)", question=question.strip())


def _clean(text: str) -> str:
    text = re.sub(r"[*_#`]+", "", text or "")       # spoken text: no markdown
    return re.sub(r"\s+", " ", text).strip()


def _log(entry: dict) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": dt.datetime.now(db.TZ).isoformat(timespec="seconds"), **entry},
                               ensure_ascii=False) + "\n")
    except OSError:
        log.exception("could not write %s", LOG_PATH)


def _quota_reset(error: Exception) -> float | None:
    """For a 429 'per day' quota error, the time.time() when it resets; None for any other error."""
    msg = str(error)
    if "RESOURCE_EXHAUSTED" not in msg or "PerDay" not in msg:
        return None
    m = re.search(r"'retryDelay': '(\d+)s'", msg)
    return time.time() + (int(m.group(1)) if m else 3600)


def available_models() -> list[str]:
    now = time.time()
    return [m for m in MODELS if _exhausted.get(m, 0) <= now]


def answer(question: str, lang: str, history: list[dict] | None = None) -> str:
    """The first answer from MODELS, in `lang`. Models out of daily quota are skipped until they reset.

    Raises AssistantError when every model fails.
    """
    from google.genai import types

    prompt = build_prompt(question, lang, history)
    errors = []
    models = available_models()
    if not models:
        raise AssistantError("every assistant model is out of its daily free quota; try again later "
                             "or enable billing on the Gemini API key")
    for model in models:
        # Gemini models take a thinking level; Gemma rejects any thinking setting
        gemma = model.startswith("gemma")
        thinking = None if gemma else types.ThinkingConfig(thinking_level="minimal")
        http = types.HttpOptions(timeout=int((GEMMA_TIMEOUT_S if gemma else TIMEOUT_S) * 1000))
        config = types.GenerateContentConfig(temperature=0.2, http_options=http, thinking_config=thinking)
        started = time.monotonic()
        try:
            resp = _get_client().models.generate_content(model=model, contents=prompt, config=config)
            text = _clean(resp.text)
            if not text:
                raise AssistantError("empty answer")
        except Exception as e:
            if (reset := _quota_reset(e)) is not None:
                _exhausted[model] = reset
                errors.append(f"{model}: daily quota used up")
            else:
                errors.append(f"{model}: {str(e)[:160]}")
            _log({"model": model, "ok": False, "ms": round((time.monotonic() - started) * 1000),
                  "question": question, "error": str(e)[:300]})
            continue
        _log({"model": model, "ok": True, "ms": round((time.monotonic() - started) * 1000), "lang": lang,
              "question": question, "answer": text, "prompt_chars": len(prompt)})
        return text
    raise AssistantError("; ".join(errors))
