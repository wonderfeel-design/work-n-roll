"""Create the database and load the reference data from data/satech_dun_field_log_sample.xlsx:
Parcels_DUN, Vocabulary and UI_Strings. Idempotent (re-running updates the reference rows).

The workbook's Field_Log and Corrections rows are format examples and are never imported.

    python -m app.seed           # create tables, load / refresh reference data
    python -m app.seed --reset   # delete the database file first (loses all records)
"""
import sys

from openpyxl import load_workbook

from app import ROOT, db

SAMPLE_XLSX = ROOT / "data" / "satech_dun_field_log_sample.xlsx"
SIGPAC_PARTS = ("sigpac_prov", "sigpac_mun", "sigpac_agregat", "sigpac_zona",
                "sigpac_poligon", "sigpac_parcela", "sigpac_recinte")


def _rows(ws):
    header = [c.value for c in ws[1]]
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] is not None:
            yield dict(zip(header, row))


def _int(v):
    return int(v) if v is not None else None


def seed() -> None:
    wb = load_workbook(SAMPLE_XLSX)
    with db._connect() as conn:
        vocab = [(r["key"], r["type"], r["en"], r["ca"], r["es"], r["ru"]) for r in _rows(wb["Vocabulary"])]
        conn.executemany("INSERT OR REPLACE INTO vocabulary (key, type, en, ca, es, ru) VALUES (?, ?, ?, ?, ?, ?)",
                         vocab)

        strings = [(r["key"], r["en"], r["ca"], r["es"], r["ru"]) for r in _rows(wb["UI_Strings"])]
        conn.executemany("INSERT OR REPLACE INTO ui_strings (key, en, ca, es, ru) VALUES (?, ?, ?, ?, ?)", strings)

        crops = {k for k, t, *_ in vocab if t == "crop"}
        for r in _rows(wb["Parcels_DUN"]):
            if r["crop_key"] not in crops:
                raise ValueError(f"parcel {r['parcel_alias']}: crop_key {r['crop_key']!r} is not in Vocabulary")
            parts = {k: _int(r[k]) for k in SIGPAC_PARTS}
            row = {
                "alias": r["parcel_alias"], "spoken_names": r["spoken_names"], "campaign": str(r["campaign"]),
                "explotacio_id": r["explotacio_id"], **parts,
                "sigpac_ref": "-".join(str(v) for v in parts.values()),
                **{k: r[k] for k in ("sigpac_use", "crop_key", "variety", "area_ha", "irrigation", "tenure",
                                     "eco_scheme")},
            }
            conn.execute(
                f"INSERT OR REPLACE INTO parcels ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})",
                list(row.values()),
            )


def main() -> None:
    if "--reset" in sys.argv:
        for suffix in ("", "-wal", "-shm"):
            db.DB_PATH.with_name(db.DB_PATH.name + suffix).unlink(missing_ok=True)
    db.init_db()
    seed()
    print(f"{db.DB_PATH.relative_to(ROOT)}: {len(db.get_parcels())} parcels, "
          f"{len(db.get_vocabulary())} vocabulary terms, {len(db.list_records())} records")


if __name__ == "__main__":
    main()
