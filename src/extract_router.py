# src/extract_router.py
from __future__ import annotations

from pdf_text import pdf_to_text
from extract_g7 import extract_g7_rides_from_pdf_bytes
from extract_avis_local import extract_avis_from_pdf_text
from extract_tgv_local import extract_tgv_from_pdf_bytes_local
from extract_rental_local import extract_rental_from_pdf_bytes
from extract_uber_csv import extract_uber_from_csv_bytes


def detect_type_from_text(text: str, filename: str) -> str:
    t = (text or "").lower()
    fn = (filename or "").lower()

    g7_hints = [
        "recapitulatif des courses",
        "récapitulatif des courses",
        "prestations associees",
        "prestations associées",
        "g7",
        "taxi",
        "adresse de prise en charge",
        "personne transportée",
    ]
    if any(h in t for h in g7_hints) or "g7" in fn or "taxi" in fn:
        return "g7"

    tgv_hints = [
        "tgv",
        "inoui",
        "ouigo",
        "ter",
        "intercités",
        "intercites",
        "mon billet",
        "dossier voyage",
        "e-billet",
        "e billet",
    ]
    if any(h in t for h in tgv_hints) or "tgv" in fn or "sncf" in fn:
        return "tgv"

    rental_hints = [
        "detail location",
        "détail location",
        "rental information",
        "location/rental information",
        "enterprise",
        "rent a car",
        "location voiture",
        "kms depart",
        "kms retour",
        "kilométrage",
        "kilometrage",
    ]
    if any(h in t for h in rental_hints) or "rent" in fn or "enterprise" in fn:
        return "rental"

    avis_hints = [
        "avis",
        "detail de la location",
        "détail de la location",
        "km parcour",
        "kms parcour",
    ]
    if any(h in t for h in avis_hints) or "avis" in fn:
        return "avis"

    return "unknown"


def extract_any(
    file_bytes: bytes,
    filename: str,
    debug_tgv: bool = False,
    debug_rental: bool = False,
    debug_g7: bool = False,
):
    fn = (filename or "").lower()

    # ✅ CSV = Uber
    if fn.endswith(".csv"):
        return "uber", extract_uber_from_csv_bytes(file_bytes, filename)

    # ✅ sinon on considère que c'est un PDF
    text = pdf_to_text(file_bytes, max_pages=5)
    doc_type = detect_type_from_text(text, filename)

    if doc_type == "g7":
        try:
            return "g7", extract_g7_rides_from_pdf_bytes(file_bytes, filename, debug=debug_g7)
        except TypeError:
            return "g7", extract_g7_rides_from_pdf_bytes(file_bytes, filename)

    if doc_type == "tgv":
        return "tgv", extract_tgv_from_pdf_bytes_local(file_bytes, filename, debug=debug_tgv)

    if doc_type == "rental":
        return "rental", extract_rental_from_pdf_bytes(file_bytes, filename, debug=debug_rental)

    if doc_type == "avis":
        return "avis", extract_avis_from_pdf_text(text, filename)

    try:
        return "g7", extract_g7_rides_from_pdf_bytes(file_bytes, filename, debug=debug_g7)
    except TypeError:
        return "g7", extract_g7_rides_from_pdf_bytes(file_bytes, filename)