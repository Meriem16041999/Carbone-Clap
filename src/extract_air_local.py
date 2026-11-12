# src/extract_air_local.py
import io
import re
from typing import List, Optional, Tuple

import pdfplumber

from schemas import RidesExtraction, RideRow
from routes import geocode_place, haversine_km
import re
from schemas import RidesExtraction, RideRow

# ---------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------

PATTERN_DATE_HEADER = re.compile(
    r"\b(?:LU|MA|ME|JE|VE|SA|DI)\s+\d{1,2}\s+[A-Za-zéûâîôùàèêëïöüç]+\s+\d{4}\b",
    flags=re.IGNORECASE,
)

PATTERN_EMISSION_DATE = re.compile(
    r"Date d[’']émission\s*:\s*(\d{1,2}\s+[A-Za-zéûâîôùàèêëïöüç]+\s+\d{4})",
    flags=re.IGNORECASE,
)
PATTERN_BOARDING_DATE = re.compile(
    r"^(lun\.|mar\.|mer\.|jeu\.|ven\.|sam\.|dim\.)\s+\d{1,2}\s+[A-Za-zÀ-ÿ]+",
    flags=re.IGNORECASE,
)

PATTERN_BOARDING_ROUTE = re.compile(
    r"^([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s'\-]+?)\s+([A-Z]{1,3}\d{2,5})\s+([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s'\-]+)$"
)

PATTERN_IATA_PAIR = re.compile(r"^[A-Z]{3}\s+[A-Z]{3}$")
PATTERN_DEPART_LINE = re.compile(
    r"^Départ\s+(\d{1,2}[A-Za-zéûâîôùàèêëïöüç]{3,9}\d{2}:\d{2})\s+(.+)$",
    flags=re.IGNORECASE,
)

PATTERN_ARRIVEE_LINE = re.compile(
    r"^Arrivée\s+(\d{1,2}[A-Za-zéûâîôùàèêëïöüç]{3,9}\d{2}:\d{2})\s+(.+)$",
    flags=re.IGNORECASE,
)
PATTERN_TERMINAL = re.compile(r"\bTerminal\s*:\s*[A-Z0-9]+\b", flags=re.IGNORECASE)
PATTERN_DURATION = re.compile(r"^Durée\b", flags=re.IGNORECASE)
PATTERN_VOL = re.compile(r"^Volotea|^Air France|^Transavia|^easyJet|^Ryanair|^Vueling", flags=re.IGNORECASE)

PAT_AIR_DISTANCE = re.compile(
    r"Distance\s+de\s+vol\s*[\r\n\s]+([0-9]+(?:[.,][0-9]+)?)\s*km",
    flags=re.IGNORECASE,
)
AIRPORT_KM = {
    ("ORY", "TLS"): 570.0,
    ("TLS", "ORY"): 570.0,
    ("CDG", "TLS"): 602.0,
    ("TLS", "CDG"): 602.0,
}
# ---------------------------------------------------------------------
# Helpers PDF
# ---------------------------------------------------------------------
def _clean_air_place(s: str) -> str:
    s = _normalize_spaces(s)
    s = s.replace("–", "-").replace("—", "-")
    s = re.sub(r"\bST\b", "SAINT", s)
    s = re.sub(r"\bSTE\b", "SAINTE", s)
    s = re.sub(r"\s+", " ", s).strip(" -")
    return s


def _normalize_boarding_date(s: str) -> str:
    s = _normalize_spaces(s)

    mapping = {
        "lun.": "LUNDI",
        "mar.": "MARDI",
        "mer.": "MERCREDI",
        "jeu.": "JEUDI",
        "ven.": "VENDREDI",
        "sam.": "SAMEDI",
        "dim.": "DIMANCHE",
    }

    parts = s.split()
    if len(parts) >= 3:
        dow = parts[0].lower()
        day = parts[1]
        month = parts[2].upper()
        dow_full = mapping.get(dow, parts[0].upper())
        return f"{dow_full} {day} {month}"

    return s.upper()


def _extract_boarding_pass_flights(page_text: str, debug: bool = False) -> List[Tuple[Optional[str], str, str]]:
    """
    Format type easyJet boarding pass :
      lun. 23 mars Fermeture de la porte 16:05
      Nice EJU4862 Paris Orly
      NCE ORY
      Départs 16:35 ... Arrivées 18:05
    """
    lines = [_normalize_spaces(l) for l in page_text.splitlines() if _normalize_spaces(l)]

    flight_date: Optional[str] = None
    flights: List[Tuple[Optional[str], str, str]] = []

    for i, line in enumerate(lines):
        # Date boarding pass
        m_date = PATTERN_BOARDING_DATE.match(line)
        if m_date and flight_date is None:
            # ne garde que "lun. 23 mars"
            raw_date = m_date.group(0)
            flight_date = _normalize_boarding_date(raw_date)
            if debug:
                print(f"[AIR][DEBUG] boarding date line={i} -> {flight_date}")
            continue

        # Ligne trajet type "Nice EJU4862 Paris Orly"
        m_route = PATTERN_BOARDING_ROUTE.match(line)
        if m_route:
            origin = _clean_air_place(m_route.group(1))
            flight_no = m_route.group(2)
            dest = _clean_air_place(m_route.group(3))

            # sécurité: éviter faux positifs
            bad_words = [
                "CARTE D’EMBARQUEMENT",
                "CARTE D'EMBARQUEMENT",
                "INFORMATIONS IMPORTANTES",
                "Fermeture de la porte",
            ]
            up_line = line.upper()
            if any(b.upper() in up_line for b in bad_words):
                continue

            if debug:
                print(
                    f"[AIR][DEBUG] boarding route line={i} "
                    f"origin='{origin}' flight='{flight_no}' dest='{dest}'"
                )

            if _looks_like_air_place(origin) and _looks_like_air_place(dest):
                flights.append((flight_date, origin, dest))
                if debug:
                    print(
                        f"[AIR][DEBUG]   ✅ boarding flight kept "
                        f"date='{flight_date}' origin='{origin}' dest='{dest}'"
                    )

    return flights

def _pdf_to_pages_text(pdf_bytes: bytes, max_pages: int = 10) -> List[str]:
    pages: List[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for p in pdf.pages[:max_pages]:
            text = p.extract_text() or ""
            text = text.strip()
            if text:
                pages.append(text)
    return pages


# ---------------------------------------------------------------------
# Helpers nettoyage
# ---------------------------------------------------------------------

def _normalize_spaces(s: str) -> str:
    s = (s or "").replace("\xa0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _normalize_station_or_airport_label(s: str) -> str:
    s = _normalize_spaces(s)

    # enlever terminal
    s = PATTERN_TERMINAL.sub("", s).strip()

    # enlever ponctuation de fin parasite
    s = re.sub(r"[\.\,\;\:\-\s]+$", "", s).strip()

    # harmonisations utiles
    s = re.sub(r"\bST\b", "SAINT", s)
    s = re.sub(r"\bSTE\b", "SAINTE", s)

    # cas fréquents d'aéroports / villes collés
    s = re.sub(r"\bLourdesTarbes\b", "Lourdes Tarbes", s, flags=re.IGNORECASE)
    s = re.sub(r"\bParis,\(Orly\)\(\+\)", "Paris Orly", s, flags=re.IGNORECASE)
    s = re.sub(r"\bParis,\(CDG\)\(\+\)", "Paris CDG", s, flags=re.IGNORECASE)

    # simplifier parenthèses
    s = s.replace("(Pyrenees)", "Pyrenees")
    s = s.replace("(+)", "")
    s = s.replace("(", " ").replace(")", " ")
    s = s.replace(",", " ")

    s = _normalize_spaces(s)
    return s


def _looks_like_air_place(s: str) -> bool:
    if not s:
        return False

    s = _normalize_spaces(s)

    if len(s) < 3 or len(s) > 80:
        return False

    bad_contains = [
        "STATUT DE LA RÉSERVATION",
        "STATUT DE LA RESERVATION",
        "CLASSE",
        "BAGAGES",
        "HEURE LIMITE",
        "ENREGISTREMENT",
        "ÉQUIPEMENT",
        "EQUIPEMENT",
        "DURÉE",
        "DUREE",
        "CHECK-IN",
        "CHECK IN",
        "CONFIRMÉ",
        "CONFIRME",
    ]
    up = s.upper()
    if any(b in up for b in bad_contains):
        return False

    # éviter lignes trop techniques
    if re.search(r"\b\d{2}:\d{2}\b", s):
        return False

    return True


def _find_first_date_on_page(page_text: str) -> Optional[str]:
    m = PATTERN_DATE_HEADER.search(page_text)
    return m.group(0).strip() if m else None


def _compute_km_haversine(origin: str, dest: str) -> Optional[float]:
    try:
        o = geocode_place(origin)
        d = geocode_place(dest)
        if o and d:
            return float(haversine_km(o, d))
    except Exception as e:
        print(f"[AIR][DEBUG] geocode/haversine failed for '{origin}' -> '{dest}': {e}")
    return None


# ---------------------------------------------------------------------
# Parsing lignes vol
# ---------------------------------------------------------------------

def _extract_place_from_line(raw_rest: str) -> str:
    """
    Reçoit la partie après l'horodatage.
    Ex:
      'LourdesTarbes,(Pyrenees)(+)'
      'Paris,(Orly)(+) Terminal:1A'
    """
    s = _normalize_station_or_airport_label(raw_rest)

    # retirer tout ce qui ressemble à des infos terminal résiduelles
    s = PATTERN_TERMINAL.sub("", s).strip()

    # nettoyage final
    s = _normalize_spaces(s)
    return s


def _parse_depart_arrivee_lines(lines: List[str], debug: bool = False) -> List[Tuple[Optional[str], str, str]]:
    """
    Retourne une liste de tuples:
      (date_header, origin, destination)
    date_header = date textuelle trouvée au-dessus du bloc vol, si dispo
    """
    flights: List[Tuple[Optional[str], str, str]] = []
    current_date: Optional[str] = None
    pending_depart: Optional[str] = None

    for i, raw_line in enumerate(lines):
        line = _normalize_spaces(raw_line)

        if not line:
            continue

        m_date = PATTERN_DATE_HEADER.match(line)
        if m_date:
            current_date = m_date.group(0).strip()
            if debug:
                print(f"[AIR][DEBUG] date header line={i} -> {current_date}")
            continue

        m_dep = PATTERN_DEPART_LINE.match(line)
        if m_dep:
            raw_dt = m_dep.group(1)
            raw_place = m_dep.group(2)
            place = _extract_place_from_line(raw_place)

            if debug:
                print(
                    f"[AIR][DEBUG] depart line={i} raw_dt='{raw_dt}' "
                    f"raw_place='{raw_place}' -> place='{place}'"
                )

            if _looks_like_air_place(place):
                pending_depart = place
            else:
                pending_depart = None
            continue

        m_arr = PATTERN_ARRIVEE_LINE.match(line)
        if m_arr:
            raw_dt = m_arr.group(1)
            raw_place = m_arr.group(2)
            place = _extract_place_from_line(raw_place)

            if debug:
                print(
                    f"[AIR][DEBUG] arrivee line={i} raw_dt='{raw_dt}' "
                    f"raw_place='{raw_place}' -> place='{place}'"
                )

            if pending_depart and _looks_like_air_place(place):
                flights.append((current_date, pending_depart, place))
                if debug:
                    print(
                        f"[AIR][DEBUG]   ✅ flight kept date='{current_date}' "
                        f"origin='{pending_depart}' dest='{place}'"
                    )
            pending_depart = None
            continue

    return flights


def _extract_flights_from_page(page_text: str, debug: bool = False) -> List[Tuple[Optional[str], str, str]]:
    lines = [l.strip() for l in page_text.splitlines() if l.strip()]

    # 1) format "itinerary / billet"
    flights = _parse_depart_arrivee_lines(lines, debug=debug)
    if flights:
        if debug:
            print(f"[AIR][DEBUG] page flights={flights}")
        return flights

    # 2) format boarding pass
    flights = _extract_boarding_pass_flights(page_text, debug=debug)
    if flights:
        if debug:
            print(f"[AIR][DEBUG] boarding page flights={flights}")
        return flights

    if debug:
        print("[AIR][DEBUG] page flights=[]")

    return []


# ---------------------------------------------------------------------
# Fonction principale
# ---------------------------------------------------------------------

def extract_air_from_pdf_bytes_local(
    pdf_bytes: bytes,
    filename: str,
    debug: bool = False,
) -> RidesExtraction:
    pages = _pdf_to_pages_text(pdf_bytes, max_pages=10)

    if debug:
        print(f"[AIR][DEBUG] ===== {filename} =====")
        print("[AIR][DEBUG] NB pages détectées:", len(pages))

    rows: List[RideRow] = []

    for page_idx, page_text in enumerate(pages):
        if debug:
            print(f"\n[AIR][DEBUG] --- PAGE {page_idx + 1} ---")
            print(page_text)

        flights = _extract_flights_from_page(page_text, debug=debug)

        for flight_date, origin_name, dest_name in flights:
            km_computed = _compute_km_haversine(origin_name, dest_name)

            if debug:
                print(
                    f"[AIR][DEBUG] geocode origin='{origin_name}' "
                    f"dest='{dest_name}' -> km={km_computed}"
                )

            row = RideRow(
                cheque_or_course=filename,
                date_time_start=flight_date or _find_first_date_on_page(page_text),
                date_time_end=None,
                pickup_address=origin_name,
                destination_address=dest_name,
                passenger=None,
                reported_km=None,
            )
            setattr(row, "km_computed", km_computed)

            rows.append(row)

    return RidesExtraction(rows=rows)
 

 


def _to_float(s: str) -> float:
    return float(s.replace(",", "."))
def extract_transavia_boarding_pass(
    text: str,
    filename: str,
    debug: bool = False,
) -> RidesExtraction:

    # Format :
    # PARIS (ORLY) (ORY)  PERPIGNAN (PGF)

    pattern = re.compile(
        r"PARIS\s*\(ORLY\)\s*\(ORY\)\s+"
        r"PERPIGNAN\s*\(PGF\)",
        flags=re.IGNORECASE,
    )

    match = pattern.search(text or "")

    if not match:
        return RidesExtraction(rows=[])

    # Date au format JJ-MM-AAAA
    date_match = re.search(
        r"\b\d{2}-\d{2}-\d{4}\b",
        text,
    )

    date = date_match.group(0) if date_match else None

    origin = "Aéroport de Paris-Orly, France"
    destination = "Aéroport de Perpignan-Rivesaltes, France"

    # Calcul de la distance aérienne
    km = None

    try:
        coords_origin = geocode_place(origin)
        coords_destination = geocode_place(destination)

        if coords_origin and coords_destination:
            km = haversine_km(
                coords_origin,
                coords_destination,
            )

    except Exception as e:
        if debug:
            print("[AIR][DEBUG] Erreur géocodage :", e)

    if debug:
        print("[AIR][DEBUG] Transavia détecté")
        print("[AIR][DEBUG] Origine :", origin)
        print("[AIR][DEBUG] Destination :", destination)
        print("[AIR][DEBUG] Distance :", km)

    row = RideRow(
        cheque_or_course=filename,
        date_time_start=date,
        date_time_end=None,
        pickup_address=origin,
        destination_address=destination,
        passenger=None,
        reported_km=None,
    )

    setattr(row, "km_computed", km)

    return RidesExtraction(rows=[row])

def extract_air_from_pdf_text(
    text: str,
    filename: str,
    debug: bool = False
) -> RidesExtraction:

    text = text or ""
    rows = []

    if debug:
        print(f"[AIR][DEBUG] ===== {filename} =====")

    # ==================================================
    # CAS 1 : BOARDING PASS TRANSAVIA
    # ==================================================

    if "TRANSAVIA" in text.upper():

        if debug:
            print("[AIR][DEBUG] Boarding pass Transavia détecté")

        extraction = extract_transavia_boarding_pass(
            text,
            filename,
            debug=debug,
        )

        if extraction.rows:
            return extraction

        if debug:
            print("[AIR][DEBUG] Transavia : aucun trajet extrait")

    # ==================================================
    # CAS 2 : DISTANCE DÉCLARÉE (AIR FRANCE)
    # ==================================================

    matches = PAT_AIR_DISTANCE.findall(text)

    if debug:
        print("[AIR][DEBUG] distances trouvées:", matches)

    if matches:

        for km_str in matches:

            try:
                km = float(
                    km_str.replace(" ", "").replace(",", ".")
                )

                if km <= 0:
                    continue

                rows.append(
                    RideRow(
                        cheque_or_course=filename,
                        date_time_start=None,
                        date_time_end=None,
                        pickup_address=None,
                        destination_address=None,
                        passenger=None,
                        reported_km=km,
                    )
                )

            except (ValueError, TypeError) as e:
                if debug:
                    print(
                        "[AIR][DEBUG] Distance invalide:",
                        km_str,
                        e,
                    )

        if rows:
            return RidesExtraction(rows=rows)

    # ==================================================
    # CAS 3 : FALLBACK BOARDING PASS AIR FRANCE
    # ==================================================

    AIRPORT_KM = {
        ("ORY", "TLS"): 570.0,
        ("TLS", "ORY"): 570.0,
        ("CDG", "TLS"): 602.0,
        ("TLS", "CDG"): 602.0,
    }

    allowed_codes = {
        "ORY", "TLS", "CDG", "BOD",
        "MRS", "NCE", "LYS", "PGF",
    }

    code_matches = re.findall(
        r"\b([A-Z]{3})\b",
        text.upper(),
    )

    codes = [
        code for code in code_matches
        if code in allowed_codes
    ]

    if debug:
        print("[AIR][DEBUG] airport codes:", codes)

    for i in range(len(codes) - 1):

        pair = (codes[i], codes[i + 1])
        km = AIRPORT_KM.get(pair)

        if km is None:
            continue

        rows.append(
            RideRow(
                cheque_or_course=filename,
                date_time_start=None,
                date_time_end=None,
                pickup_address=pair[0],
                destination_address=pair[1],
                passenger=None,
                reported_km=km,
            )
        )

        if debug:
            print(
                f"[AIR][DEBUG] Trajet détecté : "
                f"{pair[0]} -> {pair[1]} = {km} km"
            )

    if debug:
        print(
            f"[AIR][DEBUG] Nombre de trajets extraits : "
            f"{len(rows)}"
        )

    return RidesExtraction(rows=rows)