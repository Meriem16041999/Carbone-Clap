# src/extract_router.py
import os

from pdf_text import pdf_to_text
from schemas import RidesExtraction

from extract_tgv_local import extract_tgv_from_pdf_bytes_local
from extract_rental_local import extract_rental_from_pdf_bytes
from extract_avis_local import extract_avis_from_pdf_bytes
from extract_g7 import extract_g7_rides_from_pdf_bytes
from extract_uber_csv import extract_uber_from_csv_bytes
from extract_air_local import extract_air_from_pdf_text
 

def extract_any(
    file_bytes: bytes,
    filename: str,
    debug_tgv: bool = False,
    debug_rental: bool = False,
    debug_g7: bool = False,
    debug_air:bool = False
):
    name = filename.lower()
    ext = os.path.splitext(name)[1].lower()

    if ext == ".csv":
        extraction = extract_uber_from_csv_bytes(file_bytes, filename)
        return "uber", extraction

    text = pdf_to_text(file_bytes, max_pages=2)
    text_up = (text or "").upper()
    name_up = filename.upper()
    # LCD / rental AVANT avis
    if (
         "LCD" in name_up
         or "LCD LOCATION" in text_up
         or "LC D LOCATION" in text_up
         or "KM DÉPART" in text_up
         or "KM DEPART" in text_up
         or "KM RETOUR" in text_up
         or "KM PARCOURUS" in text_up
        ):
     return "rental", extract_rental_from_pdf_bytes(
        file_bytes,
        filename,
        debug=debug_rental,
    )
    # AIR : uniquement les vrais documents aériens
    if (
        "AIR FRANCE" in text_up
        or "CHECKMYTRIP" in text_up
        or "COMPAGNIE EMETTRICE" in text_up
        or "COMPAGNIE ÉMETTRICE" in text_up
        or "BOARDING PASS" in text_up
        or "DISTANCE DE VOL" in text_up
        or "TRANSAVIA" in text_up
 
    ):
        print(f"[ROUTER][DEBUG] AIR détecté : {filename}")

        return "air", extract_air_from_pdf_text(
            text,
            filename,
            debug=debug_air,
        )

    # IMPORTANT : AVIS AVANT TGV
    if (
        "AVIS" in name_up
        or "AVIS LOCATION DE VOITURES" in text_up
        or "KM PARCOURUS" in text_up
        or "LOCATION DE VOITURE" in text_up
    ):
        extraction = extract_avis_from_pdf_bytes(
            file_bytes,
            filename,
            debug=debug_rental,
        )
        return "avis", extraction

    if (
        "G7" in name_up
        or "TAXIS G7" in text_up
        or "G7" in text_up
    ):
        extraction = extract_g7_rides_from_pdf_bytes(
            file_bytes,
            filename,
        )
        return "g7", extraction

    if (
        "ENTERPRISE" in text_up
        or "EUROPCAR" in text_up
        or "RENT A CAR" in text_up
        or "SALVA" in text_up
        or "LOCATION" in name_up
    ):
        extraction = extract_rental_from_pdf_bytes(
            file_bytes,
            filename,
            debug=debug_rental,
        )
        return "rental", extraction
    if (
      "EUROPCAR" in name_up
       or "EUROPCAR" in text_up
       or "KILOMÈTRES PARCOURUS" in text_up
       or "KILOMETRES PARCOURUS" in text_up
      ):
     return "rental", extract_rental_from_pdf_bytes(
        file_bytes,
        filename,
        debug=debug_rental,
    )
    if (
        "TGV" in text_up
        or "SNCF" in text_up
        or "MON BILLET" in text_up
        or "TER" in text_up
        or "NOMAD" in text_up
        or "RÉMI" in text_up
        or "REMI" in text_up
        or "ITINÉRAIRE ALLER" in text_up
        or "ITINERAIRE ALLER" in text_up
        or "TRAIN LIO" in text_up
        or "TRAIN TER" in text_up
        or "SNCF VOYAGEURS" in text_up
    ):
        print(f"[ROUTER][DEBUG] TRAIN détecté : {filename}")

        extraction = extract_tgv_from_pdf_bytes_local(
            file_bytes,
            filename,
            debug=debug_tgv,
        )

        print(
            f"[ROUTER][DEBUG] Nombre de trajets : "
            f"{len(extraction.rows)}"
        )

    
        return "tgv", extraction

    return "unknown", RidesExtraction(rows=[])