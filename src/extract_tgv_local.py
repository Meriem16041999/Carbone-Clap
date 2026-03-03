# src/extract_tgv_local.py
import io
import re
from typing import Optional, List

import pdfplumber

from pdf_text import pdf_to_text  # si tu ne l'utilises plus, tu peux le retirer
from schemas import RidesExtraction, RideRow
from routes import geocode_place, haversine_km

# ---- Patterns généraux -----------------------------------------------------

PATTERN_TIME = re.compile(r"\b(\d{1,2}[hH]\d{2}|\d{1,2}:\d{2})\b")
PATTERN_DATE = re.compile(
    r"(?:Lundi|Mardi|Mercredi|Jeudi|Vendredi|Samedi|Dimanche)?\s*\d{1,2}\s+[A-Za-zéûâîôùàèêëïöüç\-]+?\s+\d{4}",
    flags=re.IGNORECASE,
)

# Mots-clés qu'on NE veut pas prendre comme gares
STOP_CONTAINS = [
    "VOITURE", "PLACE", "BAS", "DUO", "CÔTÉ", "COTE", "CLASSE", "TGV", "INOUI",
    "TER", "INTERCIT", "MON BILLET", "ITINÉRAIRE", "ITINERAIRE", "BON À SAVOIR",
    "PRÊTS", "EMBARQUEZ", "TOURISME", "AFFAIRES", "FCE", "DOSSIER", "VOYAGE",
]


# ---- Helpers ---------------------------------------------------------------

def _pdf_to_pages_text(pdf_bytes: bytes, max_pages: int = 10) -> List[str]:
    """Retourne la liste des textes par page avec pdfplumber."""
    pages: List[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for p in pdf.pages[:max_pages]:
            t = p.extract_text() or ""
            t = t.strip()
            if t:
                pages.append(t)
    return pages


def _clean_station(s: str) -> str:
    s = s.strip()
    s = re.sub(r"\s+", " ", s)
    s = s.replace(" ST ", " SAINT ")
    s = s.replace(" STE ", " SAINTE ")
    return s


def _looks_like_station(s: str) -> bool:
    """Heuristique : est-ce que cette chaîne ressemble à un nom de gare ?"""
    if not s or len(s) < 4:
        return False

    up = s.upper()

    # majoritairement en majuscules
    letters = [c for c in s if c.isalpha()]
    if letters:
        upper_letters = sum(
            1 for c in letters if c.isupper() or c in "ÀÂÄÇÉÈÊËÎÏÔÖÙÛÜŸ"
        )
        if upper_letters / max(1, len(letters)) < 0.85:
            return False

    # pas de mots "parasites"
    for bad in STOP_CONTAINS:
        if bad in up:
            return False

    # au moins 1 token de 3+ lettres en majuscules
    tokens = [t for t in re.split(r"[\s\-]+", up) if t]
    big_tokens = [t for t in tokens if len(t) >= 3 and t.isupper()]
    return len(big_tokens) >= 1


def _find_date(text: str) -> Optional[str]:
    m = PATTERN_DATE.search(text)
    return m.group(0).strip() if m else None


def _stations_from_page(page_text: str, debug: bool = False) -> List[str]:
    """
    Sur UNE page : on cherche les 2 lignes de type:
      '15h00 PARIS GARE DE LYON'
      '16h56 LYON PART DIEU'
    et on renvoie [origin, destination].
    """
    if not page_text:
        return []

    lines = [l.strip() for l in page_text.splitlines() if l.strip()]
    stations: List[str] = []

    def _clean_after_text(txt: str) -> str:
        t = txt.strip()
        # retirer une heure éventuelle au début
        t = PATTERN_TIME.sub("", t).strip()
        # enlever 'Prix : ...', montants, etc.
        t = re.sub(r"\bPrix\b.*$", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\d{1,3}(?:[.,]\d{2})?\s*(?:€|EUR)\b", "", t, flags=re.IGNORECASE)
        t = re.sub(r"(€|EUR)\b", "", t, flags=re.IGNORECASE)
        t = re.sub(r"[\:\,\(\)\.\-\/]+$", "", t).strip()
        return _clean_station(t)

    for i, line in enumerate(lines):
        m = PATTERN_TIME.search(line)
        if not m:
            continue

        raw_after = PATTERN_TIME.sub("", line).strip(" -–—:|•\t")
        after = _clean_after_text(raw_after)

        if debug:
            print(
                f"[TGV][DEBUG] line={i} has time, raw='{line}' "
                f"-> raw_after='{raw_after}' -> after_clean='{after}'"
            )

        # si vide ou trop court, on cherche dans les lignes suivantes
        if not after or len(after) < 4:
            found = False
            for j in range(1, 4):  # jusqu'à 3 lignes suivantes
                if i + j >= len(lines):
                    break
                nxt_raw = lines[i + j]
                candidate = PATTERN_TIME.sub("", nxt_raw).strip()
                nxt = _clean_after_text(candidate)
                if debug:
                    print(
                        f"[TGV][DEBUG]   fallback next+{j}='{nxt_raw}' "
                        f"-> candidate='{candidate}' -> '{nxt}'"
                    )
                if _looks_like_station(nxt):
                    after = nxt
                    found = True
                    if debug:
                        print(f"[TGV][DEBUG]   chosen from next+{j}: '{after}'")
                    break
            if not found and debug:
                print(f"[TGV][DEBUG]   ❌ no station found near line {i}")

        if _looks_like_station(after):
            stations.append(after)
            if debug:
                print(f"[TGV][DEBUG]   ✅ station kept: '{after}'")
            if len(stations) == 2:
                break
        else:
            if debug:
                print(f"[TGV][DEBUG]   ❌ rejected as station: '{after}'")

    # dédoublonnage (⚠️ ici tu avais tapé outappend au lieu de out.append)
    out: List[str] = []
    for s in stations:
        if not out or s != out[-1]:
            out.append(s)

    return out


def _compute_km_haversine(origin: str, dest: str) -> Optional[float]:
    """Geocode + distance haversine, avec log en cas d'erreur."""
    try:
        o = geocode_place(origin)
        d = geocode_place(dest)
        if o and d:
            return float(haversine_km(o, d))
    except Exception as e:
        print(f"[TGV][DEBUG] geocode/haversine failed for '{origin}' -> '{dest}': {e}")
    return None


# ---- Fonction principale appelée par extract_router ------------------------

def extract_tgv_from_pdf_bytes_local(
    pdf_bytes: bytes,
    filename: str,
    debug: bool = False,
) -> RidesExtraction:
    """
    Retourne 1 RideRow par page TGV trouvée (souvent aller + retour).
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

        stations = _stations_from_page(page_text, debug=debug)

        if debug:
            print(f"[TGV][DEBUG] page {page_idx + 1} stations={stations}")

        if len(stations) < 2:
            continue

        origin_name, dest_name = stations[0], stations[1]
        date = _find_date(page_text)

        km_computed = _compute_km_haversine(origin_name, dest_name)

        if debug:
            print(
                f"[TGV][DEBUG] geocode origin='{origin_name}' -> km={km_computed}"
            )

        row = RideRow(
            cheque_or_course=filename,
            date_time_start=date,
            date_time_end=None,
            pickup_address=origin_name,
            destination_address=dest_name,
            passenger=None,
            reported_km=None,
        )
        setattr(row, "km_computed", km_computed)

        rows.append(row)

    return RidesExtraction(rows=rows)