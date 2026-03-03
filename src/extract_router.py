# src/extract_router.py
from pdf_text import pdf_to_text

from extract_g7 import extract_g7_rides_from_pdf_bytes
from extract_avis_local import extract_avis_from_pdf_text
from extract_tgv_local import extract_tgv_from_pdf_bytes_local
from extract_rental_local import extract_rental_from_pdf_bytes

def detect_type_from_text(text: str, filename: str) -> str:
    t = (text or "").lower()
    fn = (filename or "").lower()

    # ---------- 1) G7 / Taxi ----------
    g7_hints = [
        "recapitulatif des courses",
        "récapitulatif des courses",
        "prestations associees",
        "prestations associées",
        "g7",
        "taxi",
        "courses",
        "attente/service",
        "adresse de prise en charge",
        "personne transportée",
    ]
    if any(h in t for h in g7_hints) or "g7" in fn or "taxi" in fn:
        return "g7"

    # ---------- 2) Location voiture (Enterprise / Avis / Salva / etc.) ----------
    rental_hints = [
        "detail location",
        "détail location",
        "detail de la location",
        "détail de la location",
        "location de voiture",
        "avis location",
        "avis location de voitures",
        "rental information",
        "location/rental information",
        "vehicules/rental vehicles",
        "véhicules/rental vehicles",
        "km parcourus",
        "kms depart",
        "kms retour",
        "km départ",
        "km retour",
        "kilométrage",
        "kilometrage",
        "enterprise",
        "rent a car",
        "loueur",
    ]
    if any(h in t for h in rental_hints) or "rent" in fn or "enterprise" in fn or "avis" in fn:
        return "rental"

    # ---------- 3) TGV / SNCF ----------
    tgv_strong_hints = [
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
        "prêts ? embarquez",
        "prets ? embarquez",
    ]
    if any(h in t for h in tgv_strong_hints) or "tgv" in fn or ("sncf" in fn and "taxi" not in fn):
        return "tgv"

    # ---------- 4) AVIS (si tu veux garder un type distinct) ----------
    # Perso je te conseille de tout mettre dans "rental" pour AVIS.
    return "unknown"
 


def extract_any(
    pdf_bytes: bytes,
    filename: str,
    debug_tgv: bool = False,
    debug_rental: bool = False,
    debug_g7: bool = False,
):
    """
    Retourne: (doc_type, extraction)
    doc_type in {"g7", "tgv", "rental", "avis", "unknown"}
    """
    text = pdf_to_text(pdf_bytes, max_pages=5)
    doc_type = detect_type_from_text(text, filename)

    if doc_type == "g7":
        try:
            return "g7", extract_g7_rides_from_pdf_bytes(pdf_bytes, filename, debug=debug_g7)
        except TypeError:
            return "g7", extract_g7_rides_from_pdf_bytes(pdf_bytes, filename)

    if doc_type == "tgv":
        return "tgv", extract_tgv_from_pdf_bytes_local(pdf_bytes, filename, debug=debug_tgv)

    if doc_type == "rental":
        return "rental", extract_rental_from_pdf_bytes(pdf_bytes, filename, debug=debug_rental)

    if doc_type == "avis":
        return "avis", extract_avis_from_pdf_text(text, filename)

    # fallback: essaye G7
    try:
        return "g7", extract_g7_rides_from_pdf_bytes(pdf_bytes, filename, debug=debug_g7)
    except TypeError:
        return "g7", extract_g7_rides_from_pdf_bytes(pdf_bytes, filename)