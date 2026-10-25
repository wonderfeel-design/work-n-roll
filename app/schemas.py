"""Shared contract between Person 1 (bot + Gemma) and Person 2 (voice + web + export).

Section 4.1 of CLAUDE_person1.md / CLAUDE_person2.md. Change only by agreement.
Checks live in validators (not Field constraints) so the JSON schema sent to Gemma stays plain.
"""
import datetime as dt
from typing import Literal, Optional

from pydantic import BaseModel, field_validator

Lang = Literal["en", "ru", "ca", "es"]
Activity = Literal["treatment", "fertilization", "irrigation", "harvest", "labour", "sowing", "other"]
Status = Literal["draft", "farmer_confirmed", "auto_approved", "needs_review",
                 "validated", "corrected", "discarded"]
Corrector = Literal["farmer", "agronomist"]

LANGS: tuple[str, ...] = Lang.__args__
ACTIVITIES: tuple[str, ...] = Activity.__args__
STATUSES: tuple[str, ...] = Status.__args__
CORRECTORS: tuple[str, ...] = Corrector.__args__

# Allowed status moves. db.update_status rejects anything else.
STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"farmer_confirmed", "discarded"}),
    "farmer_confirmed": frozenset({"auto_approved", "needs_review", "discarded"}),
    "auto_approved": frozenset({"validated", "corrected", "needs_review", "discarded"}),
    "needs_review": frozenset({"validated", "corrected", "discarded"}),
    "validated": frozenset({"corrected"}),
    "corrected": frozenset({"validated", "corrected"}),
    "discarded": frozenset(),
}

# Fields that update_field may change (and so may appear in corrections.field).
# lang, *_spoken, transcript, status and judge fields are never "corrected".
EDITABLE_FIELDS: tuple[str, ...] = (
    "date", "parcel_alias", "crop_spoken", "activity_key", "product", "target_pest_key",
    "quantity", "unit", "area_ha", "notes_ca", "notes_en",
)


class Extracted(BaseModel):              # what Gemma returns, one per activity
    lang: Lang
    date: Optional[str] = None           # ISO yyyy-mm-dd, resolved ("ayer" -> real date)
    date_spoken: Optional[str] = None
    parcel_spoken: Optional[str] = None
    parcel_alias: Optional[str] = None   # P1..P5 or None
    crop_spoken: Optional[str] = None
    activity_key: Activity
    product: Optional[str] = None        # commercial name, never translated
    target_pest_key: Optional[str] = None  # vocabulary key or "unknown"
    quantity: Optional[float] = None
    unit: Optional[str] = None           # kg, L, t, m3, ...
    area_ha: Optional[float] = None
    notes_ca: Optional[str] = None
    notes_en: Optional[str] = None
    missing_fields: list[str] = []
    confidence: float = 0.0

    @field_validator("date")
    @classmethod
    def _iso_date(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return dt.date.fromisoformat(v).isoformat()  # raises on anything but yyyy-mm-dd

    @field_validator("quantity")
    @classmethod
    def _non_negative(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v < 0:
            raise ValueError("quantity cannot be negative")
        return v

    @field_validator("area_ha")
    @classmethod
    def _positive_area(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v <= 0:
            raise ValueError("area_ha must be greater than 0")
        return v

    @field_validator("confidence")
    @classmethod
    def _unit_interval(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        return v


class ExtractionResult(BaseModel):
    records: list[Extracted]
    is_farm_activity: bool


class Record(Extracted):                 # what is stored
    id: Optional[int] = None
    farmer_chat_id: int
    farmer_name: Optional[str] = None
    transcript_original: str
    status: Status = "draft"
    judge_score: Optional[float] = None
    judge_reason: Optional[str] = None
    confirmed_by: Optional[str] = None
    corrected_by: Optional[str] = None
    created_at: Optional[str] = None

    @field_validator("judge_score")
    @classmethod
    def _score_interval(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not 0.0 <= v <= 1.0:
            raise ValueError("judge_score must be between 0 and 1")
        return v


# --- new plots (bot /newplot and the web form) ----------------------------------

Irrigation = Literal["regadiu", "secà"]   # DUN terms, as in Parcels_DUN
PARCEL_REQUIRED: tuple[str, ...] = ("spoken_names", "crop_key", "area_ha")


class CropLabels(BaseModel):
    """A new crop's name per language. Fixed fields, not a dict: Gemini's JSON mode rejects free-form maps."""
    en: Optional[str] = None
    ca: Optional[str] = None
    es: Optional[str] = None
    ru: Optional[str] = None

    @field_validator("en", "ca", "es", "ru")
    @classmethod
    def _strip(cls, v: Optional[str]) -> Optional[str]:
        return (v or "").strip() or None


class ParcelDraft(BaseModel):
    """A plot to add: what Gemma reads from the farmer's description, or what the web form sends.

    One crop per plot. crop_key is a vocabulary key; for a crop not in the vocabulary yet,
    crop_labels gives its name in en / ca / es / ru and db.add_parcel adds it.
    """
    lang: Lang = "en"
    spoken_names: list[str] = []          # what the farmer calls it, in any language
    crop_key: Optional[str] = None
    crop_labels: Optional[CropLabels] = None
    variety: Optional[str] = None
    area_ha: Optional[float] = None
    irrigation: Optional[Irrigation] = None
    sigpac_ref: Optional[str] = None      # prov-mun-agregat-zona-poligon-parcela-recinte, if known
    missing_fields: list[str] = []

    @field_validator("spoken_names")
    @classmethod
    def _names(cls, v: list[str]) -> list[str]:
        out = []
        for name in (n.strip() for n in v):
            if name and name.lower() not in {o.lower() for o in out}:
                out.append(name[:60])
        return out

    @field_validator("crop_key")
    @classmethod
    def _crop_key(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        key = "_".join(v.strip().lower().replace("-", " ").split())
        return key or None

    @field_validator("crop_labels")
    @classmethod
    def _labels(cls, v: Optional[CropLabels]) -> Optional[CropLabels]:
        return v if v is not None and any(v.model_dump().values()) else None

    @field_validator("area_ha")
    @classmethod
    def _area(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v <= 0:
            raise ValueError("area_ha must be greater than 0")
        return v

    @field_validator("sigpac_ref")
    @classmethod
    def _sigpac(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not v.strip():
            return None
        parts = v.strip().split("-")
        if len(parts) != 7 or not all(p.isdigit() for p in parts):
            raise ValueError("sigpac_ref needs 7 numbers: prov-mun-agregat-zona-poligon-parcela-recinte")
        return "-".join(str(int(p)) for p in parts)
