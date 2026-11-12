import io
import re
import unicodedata
from typing import Optional, List, Tuple

import pdfplumber

from schemas import RidesExtraction, RideRow
from routes import geocode_place, haversine_km

# ---- Patterns généraux -----------------------------------------------------

PATTERN_LINE_TIME = re.compile(r"^\s*(\d{1,2}[hH]\d{2}|\d{1,2}:\d{2})\b")
PATTERN_TIME = re.compile(r"\b(\d{1,2}[hH]\d{2}|\d{1,2}:\d{2})\b")

PATTERN_DATE = re.compile(
    r"(?:Lundi|Mardi|Mercredi|Jeudi|Vendredi|Samedi|Dimanche)?\s*\d{1,2}\s+[A-Za-zÉÈÊËÀÂÄÎÏÔÖÙÛÜŸéèêëàâäîïôöùûüç\-]+?\s+\d{4}",
    flags=re.IGNORECASE,
)

PATTERN_LABEL_ROUTE = re.compile(
    r"^\s*(.+?)\s*>\s*(.+?)\s*(?:\d{1,3}(?:[.,]\d{2})?\s*(?:€|EUR))?\s*$",
    flags=re.IGNORECASE,
)

PATTERN_STATION_DATETIME = re.compile(
    r"^\s*(.+?)\s+\d{1,2}/\d{1,2}\s+[àa]\s+\d{1,2}h\d{2}\s*$",
    flags=re.IGNORECASE,
)

STOP_TOKENS = {
    "VOITURE",
    "PLACE",
    "BAS",
    "HAUT",
    "DUO",
    "COTE",
    "CÔTÉ",
    "CLASSE",
    "TGV",
    "INOUI",
    "TER",
    "INTERCIT",
    "INTERCITES",
    "INTERCITÉS",
    "BILLET",
    "ITINERAIRE",
    "ITINÉRAIRE",
    "BON",
    "SAVOIR",
    "PRETS",
    "PRÊTS",
    "EMBARQUEZ",
    "TOURISME",
    "AFFAIRES",
    "FCE",
    "DOSSIER",
    "VOYAGE",
    "FLEXIBLE",
    "SECONDE",
    "PREMIERE",
    "PREMIÈRE",
    "ADULTE",
    "ALLER",
    "SIMPLE",
    "OPERE",
    "OPÉRÉ",
    "SIEGE",
    "SIÈGE",
    "SALLE",
    "PAIEMENT",
    "ACHETE",
    "ACHETÉ",
    "DISTANCE",
    "KM",
    "TCN",
    "PAO",
    "STANDARD",
    "TARIF",
    "REMISE",
    "REMISÉ",
    "PRO",
    "NORMAL",
    "GRANDE",
    "VITESSE",
    "TRAIN",
    "BAGAGE",
    "BAGAGES",
    "OBJETS",
    "INTERDITS",
    "PERSONNE",
    "INCLUS",
    "MODELE",
    "MODÈLE",
    "TYPE",
    "PLUS",
    "OUIFI",
    "OUIFUN",
    "RESERVATION",
    "RÉSERVATION",
    "CLUB",
    "QUATRE",
    "VIA",
}

NOISE_PATTERNS = [
    "FLEXIBLE",
    "SECONDE",
    "PREMIERE",
    "PREMIÈRE",
    "BILLET",
    "ALLER",
    "SIMPLE",
    "ADULTE",
    "ITINÉRAIRE",
    "ITINERAIRE",
    "CLASSE",
    "OPÉRÉ",
    "OPERE",
    "VOITURE",
    "PLACE",
    "SALLE",
    "SIÈGE",
    "SIEGE",
    "LE TOURISME",
    "PARADOX VOYAGES",
    "FCE",
    "PAO",
    "TCN",
    "MOYEN",
    "PAIEMENT",
    "ACHETÉ",
    "ACHETE",
    "DISTANCE",
    "PRÊTS",
    "PRETS",
    "EMBARQUEZ",
    "Acheté via l'agence",
    "Prix du billet",
    "Voyageur",
    "Dossier voyage",
    "Nom :",
    "Prénom :",
    "Grande Vitesse train",
    "BAGAGES INCLUS",
    "OBJETS INTERDITS",
    "VOYAGEURS, OPTIONS ET TYPE DE PLACE",
    "Mes essentiels pour un voyage réussi",
    "Total voyageur",
    "réservation",
    "reservation",
    "OUIGO PLUS",
    "Club Quatre",
    "Club Duo",
    "Place prioritaire",
    "Départ / Arrivée",
    "Date / Heure",
    "TGV LYRIA",
]

STATION_HINTS = {
    "GARE",
    "LYON",
    "PARIS",
    "AUSTERLITZ",
    "LAZARE",
    "DIEU",
    "PERRACHE",
    "PART",
    "BRIVE",
    "GAILLARDE",
    "VIVIEZ",
    "DECAZEVILLE",
    "LISON",
    "SAINT",
    "SAINTE",
    "DIJON",
    "VILLE",
    "AEROPORT",
    "AÉROPORT",
    "BOURGES",
    "MONTLUCON",
    "VALENCE",
    "RHONE",
    "RHÔNE",
    "ALPES",
    "SUD",
}


# ---- Helpers ---------------------------------------------------------------

def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s or "")
        if unicodedata.category(c) != "Mn"
    )


def _normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _tokenize_upper(s: str) -> List[str]:
    up = _strip_accents((s or "").upper())
    return [t for t in re.split(r"[^A-Z]+", up) if t]


def _contains_stop_token(s: str) -> bool:
    tokens = set(_tokenize_upper(s))
    return any(tok in STOP_TOKENS for tok in tokens)


def _clean_station_candidate(s: str) -> str:
    s = (s or "").strip()

    # enlever heure au début
    s = re.sub(r"^\d{1,2}[hH:]\d{2}\s+", "", s, flags=re.IGNORECASE)

    # couper les textes parasites fréquents
    s = re.sub(r"Prix du billet.*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\bPrix\s*:\s*.*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"PR[ÊE]TS\s*\?\s*EMBARQUEZ\s*!.*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"PR[ÊE]TS.*$", "", s, flags=re.IGNORECASE)

    s = re.sub(r"\bTARIF NORMAL\b.*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\bBILLET STRAPONTIN\b.*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\bALLER SIMPLE\b.*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\bITINÉRAIRE\b.*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\bITINERAIRE\b.*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\bNON ÉCHANGEABLE\b.*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\bNON ECHANGEABLE\b.*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\bsans frais.*$", "", s, flags=re.IGNORECASE)

    s = re.sub(r"\bCAR TER\b.*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\bTRAIN TER\b.*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\bNOMAD\b.*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\bOpéré par\b.*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\bOpere par\b.*$", "", s, flags=re.IGNORECASE)

    s = re.sub(r"\bVoiture.*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\bSalle.*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\bPlace.*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\bDuo.*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\bSolo.*$", "", s, flags=re.IGNORECASE)

    # normalisations utiles
    s = re.sub(r"\bPARIS ST LAZARE\b", "PARIS SAINT LAZARE", s, flags=re.IGNORECASE)
    s = re.sub(r"\bPARIS MONTPARNASSE\s+1\s*ET\s*2\b", "PARIS MONTPARNASSE", s, flags=re.IGNORECASE)
    s = re.sub(r"\bAVANTAGIO[' ]?FUT[ÉE]\b.*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\bSEMI FLEX\b.*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\bsur le site SNCF.*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\bUn titre de transport.*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\bValable uniquement.*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\bEchange et remboursement.*$", "", s, flags=re.IGNORECASE)
    # enlever euros / montants
    s = re.sub(r"\d{1,3}(?:[.,]\d{2})?\s*(?:€|EUR)\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"(€|EUR)\b", "", s, flags=re.IGNORECASE)

    s = re.sub(r"\s+", " ", s).strip(" -.:;,")

    return _clean_station(s)


def _pdf_to_pages_text(pdf_bytes: bytes, max_pages: int = 10) -> List[str]:
    pages: List[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for p in pdf.pages[:max_pages]:
            t = p.extract_text() or ""
            t = t.strip()
            if t:
                pages.append(t)
    return pages


def _clean_station(s: str) -> str:
    s = _normalize_text(s)
    s = re.sub(r"\bST\b", "SAINT", s, flags=re.IGNORECASE)
    s = re.sub(r"\bSTE\b", "SAINTE", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _is_noise_line(s: str) -> bool:
    if not s:
        return True

    up = s.upper().strip()

    if any(p.upper() in up for p in NOISE_PATTERNS):
        return True

    if len(s) > 100:
        return True

    return False


def _is_title_case_like_station(s: str) -> bool:
    words = [w for w in re.split(r"[\s\-]+", s.strip()) if w]
    if not words:
        return False

    good = 0
    alpha = 0
    for w in words:
        if re.search(r"[A-Za-zÀ-ÿ]", w):
            alpha += 1
            if w[:1].isupper():
                good += 1

    return alpha > 0 and good / alpha >= 0.7

def _normalize_station_text(s: str) -> str:
    s = (s or "").strip().upper()
    s = s.replace("\u00A0", " ").replace("\u202F", " ")
    s = re.sub(r"\s+", " ", s)
    return s

def _looks_like_station(s: str) -> bool:
    s = _normalize_station_text(s)

    if not s:
        return False

    if len(s) < 2 or len(s) > 80:
        return False

    bad_tokens = [
        "PRÊTS", "EMBARQUEZ",
        "VOITURE", "PLACE",
        "DUO", "SOLO",
        "CÔTÉ", "COTE",
        "PRIX", "EUR",
        "BILLET", "STRAPONTIN",
        "DOSSIER", "VOYAGEUR", "ADULTE",
        "CLASSE",
        "TARIF NORMAL",
        "ALLER SIMPLE",
        "ITINÉRAIRE", "ITINERAIRE",
        "NON ÉCHANGEABLE", "NON ECHANGEABLE",
        "SANS FRAIS",
        "JUSQU", "REMBOURSABLE",
        "CAR TER", "TRAIN TER",
        "OPÉRÉ PAR", "OPERE PAR",
        "SNCF VOYAGEURS",
        "ACHETÉ", "ACHETE",
        "PAIEMENT",
        "INTERNET CONNEXION",
        "DISTANCE",
        "KM0",
        "RÉF", "REF",
    ]
    if any(tok in s for tok in bad_tokens):
        return False

    # lignes manifestement non gare
    if s.startswith(("DE :", "À :", "A :")):
        return False

    # autoriser gares 1 mot ou plus
    words = re.findall(r"[A-ZÀ-ÖØ-Ý0-9\-']{2,}", s)
    if len(words) < 1:
        return False

    # au moins une vraie lettre
    if not re.search(r"[A-ZÀ-ÖØ-Ý]", s):
        return False

    return True

def _find_date(text: str) -> Optional[str]:
    m = PATTERN_DATE.search(text)
    return m.group(0).strip() if m else None


def _find_reported_km(text: str) -> Optional[float]:
    m = re.search(r"Distance\s*:\s*KM\s*0*(\d+)", text, flags=re.IGNORECASE)
    if not m:
        return None

    try:
        value = int(m.group(1))
        if value <= 0:
            return None
        return float(value)
    except Exception:
        return None


def _extract_stations_from_labels(page_text: str, debug: bool = False) -> List[str]:
    origin = None
    dest = None

    for raw_line in page_text.splitlines():
        line = raw_line.strip()

        m_de = re.match(r"^DE\s*:\s*(.+)$", line, flags=re.IGNORECASE)
        if m_de:
            candidate = _clean_station(_clean_station_candidate(m_de.group(1)))
            if _looks_like_station(candidate):
                origin = candidate

        m_a = re.match(r"^[ÀA]\s*:\s*(.+)$", line, flags=re.IGNORECASE)
        if m_a:
            candidate = _clean_station(_clean_station_candidate(m_a.group(1)))
            if _looks_like_station(candidate):
                dest = candidate

    if debug:
        print(f"[TGV][DEBUG] label stations origin={origin} dest={dest}")

    return [s for s in [origin, dest] if s]


def _extract_stations_from_arrow_header(page_text: str, debug: bool = False) -> List[str]:
    for raw_line in page_text.splitlines():
        line = raw_line.strip()
        if ">" not in line:
            continue

        m = PATTERN_LABEL_ROUTE.match(line)
        if not m:
            continue

        origin = _clean_station(_clean_station_candidate(m.group(1)))
        dest = _clean_station(_clean_station_candidate(m.group(2)))

        if _looks_like_station(origin) and _looks_like_station(dest):
            if debug:
                print(f"[TGV][DEBUG] arrow header origin={origin} dest={dest}")
            return [origin, dest]

    return []


def _extract_stations_from_table_rows(page_text: str, debug: bool = False) -> List[str]:
    found: List[str] = []

    for raw_line in page_text.splitlines():
        line = raw_line.strip()
        m = PATTERN_STATION_DATETIME.match(line)
        if not m:
            continue

        candidate = _clean_station(_clean_station_candidate(m.group(1)))
        if _looks_like_station(candidate):
            found.append(candidate)

    out: List[str] = []
    for s in found:
        if not out or s != out[-1]:
            out.append(s)
        if len(out) == 2:
            break

    if debug and out:
        print(f"[TGV][DEBUG] table stations={out}")

    return out


def _extract_station_sequence_from_itinerary(lines: List[str], debug: bool = False) -> List[str]:
    seq: List[str] = []

    for i, line in enumerate(lines):
        if not PATTERN_LINE_TIME.match(line):
            continue

        raw_after = PATTERN_LINE_TIME.sub("", line).strip(" -–—:|•\t")
        inline_candidate = _clean_station(_clean_station_candidate(raw_after))

        if inline_candidate and _looks_like_station(inline_candidate):
            if not seq or seq[-1] != inline_candidate:
                seq.append(inline_candidate)
                if debug:
                    print(f"[TGV][DEBUG] seq inline station='{inline_candidate}'")
            continue

        for j in range(1, 5):
            if i + j >= len(lines):
                break

            nxt_raw = lines[i + j].strip()
            candidate = _clean_station(_clean_station_candidate(nxt_raw))

            if debug:
                print(f"[TGV][DEBUG] seq next+{j} raw='{nxt_raw}' -> candidate='{candidate}'")

            if not candidate:
                continue

            if _is_noise_line(candidate):
                if debug:
                    print(f"[TGV][DEBUG] seq next+{j} skipped noise='{candidate}'")
                continue

            candidate = _clean_station(
                _clean_station_candidate(PATTERN_LINE_TIME.sub("", candidate).strip())
            )

            if candidate and _looks_like_station(candidate):
                if not seq or seq[-1] != candidate:
                    seq.append(candidate)
                    if debug:
                        print(f"[TGV][DEBUG] seq next+{j} station='{candidate}'")
                break

    # dédoublonnage final
    clean_seq: List[str] = []
    for s in seq:
        if not clean_seq or s != clean_seq[-1]:
            clean_seq.append(s)

    return clean_seq


def _extract_stations_from_inline_lines(lines: List[str], debug: bool = False) -> List[str]:
    stations: List[str] = []

    for i, line in enumerate(lines):
        m = PATTERN_LINE_TIME.search(line)
        if not m:
            continue

        raw_after = PATTERN_LINE_TIME.sub("", line).strip(" -–—:|•\t")
        after = _clean_station(_clean_station_candidate(raw_after))

        if debug:
            print(
                f"[TGV][DEBUG] line={i} has time, raw='{line}' "
                f"-> raw_after='{raw_after}' -> after_clean='{after}'"
            )

        if _looks_like_station(after):
            stations.append(after)
            if debug:
                print(f"[TGV][DEBUG]   ✅ station kept: '{after}'")
            continue

        if after:
            if debug:
                print(f"[TGV][DEBUG]   ❌ inline candidate rejected: '{after}'")
            continue

        found = False
        for j in range(1, 7):
            if i + j >= len(lines):
                break

            nxt_raw = lines[i + j].strip()
            candidate = _clean_station(_clean_station_candidate(nxt_raw))

            if debug:
                print(
                    f"[TGV][DEBUG]   fallback next+{j}='{nxt_raw}' "
                    f"-> candidate='{candidate}'"
                )

            if _is_noise_line(candidate):
                if debug:
                    print(f"[TGV][DEBUG]   skipped noise next+{j}: '{candidate}'")
                continue

            candidate = _clean_station(
                _clean_station_candidate(PATTERN_LINE_TIME.sub("", candidate).strip())
            )

            if _looks_like_station(candidate):
                stations.append(candidate)
                found = True
                if debug:
                    print(f"[TGV][DEBUG]   chosen from next+{j}: '{candidate}'")
                break

        if not found and debug:
            print(f"[TGV][DEBUG]   ❌ no station found near line {i}")

    out: List[str] = []
    for s in stations:
        if not out or s != out[-1]:
            out.append(s)

    return out


def _stations_from_page(page_text: str, debug: bool = False) -> List[str]:
    if not page_text:
        return []

    labeled = _extract_stations_from_labels(page_text, debug=debug)
    if len(labeled) >= 2:
        return labeled[:2]

    arrow = _extract_stations_from_arrow_header(page_text, debug=debug)
    if len(arrow) >= 2:
        return arrow[:2]

    table_rows = _extract_stations_from_table_rows(page_text, debug=debug)
    if len(table_rows) >= 2:
        return table_rows[:2]

    lines = [l.strip() for l in page_text.splitlines() if l.strip()]
    stations = _extract_stations_from_inline_lines(lines, debug=debug)

    out: List[str] = []
    for s in stations:
        if not out or s != out[-1]:
            out.append(s)
        if len(out) == 2:
            break

    return out


def _segments_from_page(page_text: str, debug: bool = False) -> List[Tuple[str, str]]:
    """
    Retourne les segments de trajet d'une page.
    Priorité :
      1. labels DE:/À:
      2. header avec >
      3. table rows
      4. séquence d'itinéraire basée sur les heures
    """
    if not page_text:
        return []

    labeled = _extract_stations_from_labels(page_text, debug=debug)
    if len(labeled) >= 2:
        segments = [(labeled[0], labeled[1])]
        if debug:
            print(f"[TGV][DEBUG] using labeled segments={segments}")
        return segments

    arrow = _extract_stations_from_arrow_header(page_text, debug=debug)
    if len(arrow) >= 2:
        segments = [(arrow[0], arrow[1])]
        if debug:
            print(f"[TGV][DEBUG] using arrow segments={segments}")
        return segments

    table_rows = _extract_stations_from_table_rows(page_text, debug=debug)
    if len(table_rows) >= 2:
        segments = [(table_rows[0], table_rows[1])]
        if debug:
            print(f"[TGV][DEBUG] using table segments={segments}")
        return segments

    lines = [l.strip() for l in page_text.splitlines() if l.strip()]
    seq = _extract_station_sequence_from_itinerary(lines, debug=debug)

    if len(seq) >= 2:
        segments = [(seq[i], seq[i + 1]) for i in range(len(seq) - 1)]
        if debug:
            print(f"[TGV][DEBUG] station sequence={seq}")
            print(f"[TGV][DEBUG] segments={segments}")
        return segments

    return []


def _compute_km_haversine(origin: str, dest: str) -> Optional[float]:
    try:
        o = geocode_place(origin)
        d = geocode_place(dest)
        if o and d:
            return float(haversine_km(o, d))
    except Exception as e:
        print(f"[TGV][DEBUG] geocode/haversine failed for '{origin}' -> '{dest}': {e}")
    return None


# ---- Fonction principale ---------------------------------------------------

def extract_tgv_from_pdf_bytes_local(
    pdf_bytes: bytes,
    filename: str,
    debug: bool = False,
) -> RidesExtraction:
    """
    Retourne 1 RideRow par segment trouvé sur chaque page train.
    """
    pages = _pdf_to_pages_text(pdf_bytes, max_pages=10)

    if debug:
        print(f"[TGV][DEBUG] ===== {filename} =====")
        print("[TGV][DEBUG] NB pages détectées:", len(pages))

    rows: List[RideRow] = []

    for page_idx, page_text in enumerate(pages):
        if debug:
            print(f"\n[TGV][DEBUG] --- PAGE {page_idx + 1} ---")
            print(page_text)

        segments = _segments_from_page(page_text, debug=debug)
        # Fallback pour les billets TER / liO
        if not segments:
            stations = _extract_stations_from_labels(
                page_text,
                debug=debug
            )

            if len(stations) == 2:
                segments = [(stations[0], stations[1])]

                if debug:
                    print("[TGV][DEBUG] TER fallback:", segments)

        if debug:
            print(f"[TGV][DEBUG] page {page_idx + 1} segments={segments}")

        if not segments:
            continue

        date = _find_date(page_text)
        reported_km = _find_reported_km(page_text)

        for seg_idx, (origin_name, dest_name) in enumerate(segments):
            km_computed = _compute_km_haversine(origin_name, dest_name)

            if debug:
                print(
                    f"[TGV][DEBUG] segment {seg_idx + 1} origin='{origin_name}' dest='{dest_name}' -> km={km_computed}"
                )

            # On n'utilise le reported_km que s'il n'y a qu'un seul segment
            seg_reported_km = reported_km if len(segments) == 1 else None

            row = RideRow(
                cheque_or_course=filename,
                date_time_start=date,
                date_time_end=None,
                pickup_address=origin_name,
                destination_address=dest_name,
                passenger=None,
                reported_km=seg_reported_km,
            )
            setattr(row, "km_computed", km_computed)

            rows.append(row)

    return RidesExtraction(rows=rows)