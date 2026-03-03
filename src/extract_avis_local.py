# src/extract_avis_local.py
import re
from schemas import RidesExtraction, RideRow

KM_PATTERNS = [
    r"Km\s*Parcourus\s*[:\-]?\s*([0-9]+(?:[.,][0-9]+)?)\s*km",
    r"Km\s*Parcours\s*[:\-]?\s*([0-9]+(?:[.,][0-9]+)?)\s*km",
]

def _to_float(s: str) -> float:
    return float(s.replace(",", "."))

def extract_avis_km_from_text(text: str) -> float | None:
    for pat in KM_PATTERNS:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            return _to_float(m.group(1))
    return None

def extract_avis_from_pdf_text(text: str, filename: str) -> RidesExtraction:
    km = extract_avis_km_from_text(text)
    rows = []
    if km is not None:
        rows.append(RideRow(
            cheque_or_course=filename,
            date_time_start=None,
            date_time_end=None,
            pickup_address=None,
            destination_address=None,
            passenger=None,
            reported_km=km
        ))
    return RidesExtraction(rows=rows)
