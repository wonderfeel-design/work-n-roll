"""Rule-based judge for a field record (Task 3): judge_score 0-1 and a one-line reason."""
import datetime as dt
import re

from app import db
from app.schemas import Extracted, Record

THRESHOLD = 0.80  # a guess, tune with the agronomist

# (activity_key, unit) -> (min, max) dose per hectare.
# DEMO PLACEHOLDERS, NOT AGRONOMIC ADVICE. Replace with label doses before any real use.
DOSE_RANGES: dict[tuple[str, str], tuple[float, float]] = {
    ("treatment", "kg"): (0.2, 5.0),
    ("treatment", "L"): (0.2, 15.0),
    ("fertilization", "kg"): (20.0, 1000.0),
    ("fertilization", "L"): (10.0, 500.0),
    ("fertilization", "t"): (1.0, 60.0),
    ("irrigation", "m3"): (5.0, 1000.0),
    ("harvest", "kg"): (500.0, 80000.0),
    ("harvest", "t"): (0.5, 80.0),
}


REQUIRED = ("parcel_alias", "activity_key", "date")
REQUIRED_WITH_PRODUCT = ("product", "quantity")   # for treatment and fertilization


def missing_fields(rec: Extracted) -> list[str]:
    """Required fields still empty. Recomputed from the values, never trusted from the model or
    from the stored list (which update_field does not refresh)."""
    required = REQUIRED + (REQUIRED_WITH_PRODUCT if rec.activity_key in ("treatment", "fertilization") else ())
    return [f for f in required if getattr(rec, f) in (None, "")]


def _parcel(alias: str | None) -> dict | None:
    return next((p for p in db.get_parcels() if p["alias"] == alias), None)


def dose_per_ha(rec: Record, parcel: dict | None = None) -> float | None:
    """quantity / area: the area the farmer said, else the parcel's declared area."""
    parcel = parcel or _parcel(rec.parcel_alias)
    area = rec.area_ha or (parcel["area_ha"] if parcel else None)
    if rec.quantity is None or not area:
        return None
    return rec.quantity / area


def _words(s: str) -> list[str]:
    return [w for w in re.findall(r"\w+", s.lower()) if len(w) >= 4]


def _similar(a: str, b: str) -> bool:
    """Same word up to an inflection: almendros/almendro, яблони/яблоня, peres/perera."""
    n = 0
    while n < min(len(a), len(b)) and a[n] == b[n]:
        n += 1
    return n >= 4 and n >= 0.6 * min(len(a), len(b))


def crop_key_for(spoken: str | None) -> str | None:
    """Match the farmer's crop words against the crop vocabulary in every language. None if unsure."""
    if not spoken:
        return None
    said = _words(spoken)
    hits = set()
    for v in db.get_vocabulary():
        if v["type"] != "crop":
            continue
        labels = [v["key"]] + [v[lang] for lang in ("en", "ca", "es", "ru") if v[lang]]
        if any(_similar(s, w) for s in said for lbl in labels for w in _words(lbl)):
            hits.add(v["key"])
    return hits.pop() if len(hits) == 1 else None


def validate(rec: Record) -> tuple[float, str]:
    score, reasons = 1.0, []
    parcel = _parcel(rec.parcel_alias)

    dose = dose_per_ha(rec, parcel)
    rng = DOSE_RANGES.get((rec.activity_key, rec.unit or ""))
    if dose is not None and rng and not rng[0] <= dose <= rng[1]:
        score -= 0.4
        reasons.append(f"dose {dose:g} {rec.unit}/ha outside {rng[0]:g}-{rng[1]:g}")

    spoken_crop = crop_key_for(rec.crop_spoken)
    if parcel and spoken_crop and spoken_crop != parcel["crop_key"]:
        score -= 0.3
        reasons.append(f"crop '{rec.crop_spoken}' ({spoken_crop}) but {parcel['alias']} is {parcel['crop_key']}")

    if rec.date and dt.date.fromisoformat(rec.date) > dt.datetime.now(db.TZ).date():
        score -= 0.3
        reasons.append(f"date {rec.date} is in the future")

    if "unknown" in (rec.target_pest_key, rec.activity_key):
        score -= 0.2
        reasons.append("unknown vocabulary key")

    missing = missing_fields(rec)
    if missing:
        score -= 0.1 * len(missing)
        reasons.append(f"missing {', '.join(missing)}")

    score = round(max(0.0, min(1.0, score)), 2)
    return score, ("; ".join(reasons) if reasons else "all checks passed")


def status_for(score: float) -> str:
    return "auto_approved" if score >= THRESHOLD else "needs_review"
