# src/extract_uber_csv.py
import io
import csv
import pandas as pd
from schemas import RidesExtraction, RideRow


def _miles_to_km(x):
    try:
        if x is None or str(x).strip() == "":
            return None
        s = str(x).strip().replace(",", ".")
        return float(s) * 1.60934
    except Exception:
        return None


def _read_csv_auto(csv_bytes: bytes, header=None) -> pd.DataFrame:
    """
    Lit un CSV en détectant automatiquement :
    - l'encodage
    - le séparateur
    """
    text = None

    for enc in ["utf-8-sig", "utf-8", "latin1", "cp1252"]:
        try:
            text = csv_bytes.decode(enc)
            break
        except Exception:
            continue

    if text is None:
        raise ValueError("Impossible de décoder le CSV")

    sample = text[:5000]

    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        sep = dialect.delimiter
    except Exception:
        # fallback fréquent pour exports FR
        sep = ";"

    return pd.read_csv(
        io.StringIO(text),
        sep=sep,
        header=header,
        dtype=str,
        engine="python",
        on_bad_lines="skip",
    )


def _find_header_row(df_preview: pd.DataFrame) -> int:
    for i, row in df_preview.iterrows():
        vals = [str(v).strip().lower() for v in row.tolist()]
        joined = " | ".join(vals)

        if (
            "adresse de prise en charge" in joined
            and "destination" in joined
            and "distance" in joined
        ):
            return i

    raise ValueError("Impossible de trouver l'en-tête du CSV Uber")


def extract_uber_from_csv_bytes(csv_bytes: bytes, filename: str) -> RidesExtraction:
    preview = _read_csv_auto(csv_bytes, header=None)
    header_row = _find_header_row(preview)

    df = _read_csv_auto(csv_bytes, header=header_row)
    df.columns = [str(c).strip() for c in df.columns]

    rows = []

    for _, r in df.iterrows():
        pickup = str(r.get("Adresse de prise en charge", "")).strip()
        dest = str(r.get("Destination", "")).strip()

        date_start = str(r.get("Date et heure de la transaction (UTC)", "")).strip()
        if not date_start:
            date_start = str(r.get("Date de la commande (UTC)", "")).strip()

        distance_raw = r.get("Distance (mi)")
        if distance_raw is None:
            distance_raw = r.get("Distance")

        reported_km = _miles_to_km(distance_raw)

        if not pickup and not dest:
            continue

        row = RideRow(
            cheque_or_course=filename,
            date_time_start=date_start or None,
            date_time_end=None,
            pickup_address=pickup or None,
            destination_address=dest or None,
            passenger=None,
            reported_km=reported_km,
        )
        rows.append(row)

    return RidesExtraction(rows=rows)