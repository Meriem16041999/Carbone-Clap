# src/extract_avis_local.py
import re
from typing import Optional

from pdf_text import pdf_to_text
from schemas import RidesExtraction, RideRow


KM_PATTERNS = [
    r"Km\s*Parcourus\s*[:\-]?\s*([0-9][0-9\s\.,]*)\s*km",
    r"Km\s*Parcours\s*[:\-]?\s*([0-9][0-9\s\.,]*)\s*km",
]


def _to_float(s: str) -> float:
    s = (s or "").strip().replace(" ", "").replace("\u00A0", "")
    s = s.replace(".", "")
    s = s.replace(",", ".")
    return float(s)


def _make_row(filename: str, km: Optional[float]) -> RideRow:
    return RideRow(
        cheque_or_course=filename,
        date_time_start=None,
        date_time_end=None,
        pickup_address=None,
        destination_address=None,
        passenger=None,
        reported_km=km,
    )


def extract_avis_km_from_text(text: str) -> Optional[float]:
    for pat in KM_PATTERNS:
        m = re.search(pat, text or "", flags=re.IGNORECASE)
        if m:
            return _to_float(m.group(1))
    return None


def extract_avis_from_pdf_text(text: str, filename: str) -> RidesExtraction:
    km = extract_avis_km_from_text(text)
    if km is None:
        return RidesExtraction(rows=[])

    return RidesExtraction(rows=[_make_row(filename, km)])


def extract_avis_from_pdf_bytes(
    pdf_bytes: bytes,
    filename: str,
    debug: bool = False,
) -> RidesExtraction:
    text = pdf_to_text(pdf_bytes, max_pages=3)

    if debug:
        print(f"[AVIS][DEBUG] ===== {filename} =====")
        print("[AVIS][DEBUG] text_len:", len(text or ""))

    km = extract_avis_km_from_text(text)

    if debug:
        print("[AVIS][DEBUG] km:", km)

    if km is None:
        return RidesExtraction(rows=[])

    return RidesExtraction(rows=[_make_row(filename, km)])