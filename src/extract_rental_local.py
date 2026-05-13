# src/extract_rental_local.py
import io
import re
from typing import Optional, List, Tuple

from pdf_text import pdf_to_text
from schemas import RidesExtraction, RideRow
from ocr_utils import ocr_pdf_bytes


# ============ Helpers ============

def _norm_spaces(s: str) -> str:
    return (s or "").replace("\u00A0", " ").replace("\u202F", " ")

def _to_int(num: str) -> int:
    num = _norm_spaces(str(num))
    digits = re.sub(r"[^\d]", "", num)
    return int(digits) if digits else 0

def _dbg(debug: bool, *args):
    if debug:
        print("[RENTAL][DEBUG]", *args)

def _make_row(filename: str, reported_km: Optional[float]) -> RideRow:
    return RideRow(
        cheque_or_course=filename,
        date_time_start=None,
        date_time_end=None,
        pickup_address=None,
        destination_address=None,
        passenger=None,
        reported_km=reported_km,
    )


# ============ Patterns ============

PATTERN_ENTERPRISE_BLOCK = re.compile(
    r"(?:km\s*/?\s*m|km\s*/?\s*km|km/m)?\s*"
    r"depart\s*/\s*retour\s*/\s*total"
    r"[\s\S]{0,250}?"
    r"([0-9][0-9\s\u00A0\u202F]*)\s*/\s*"
    r"([0-9][0-9\s\u00A0\u202F]*)\s*/\s*"
    r"([0-9][0-9\s\u00A0\u202F]*)",
    flags=re.IGNORECASE,
)

PAT_KMS_PARCOURUS = re.compile(
    r"\bkm(?:s)?\s*parcour(?:u|us)\s*[:\-]?\s*([0-9][0-9\s\u00A0\u202F\.,]{1,20})\b",
    flags=re.IGNORECASE,
)

PAT_KMS_FACTURES = re.compile(
    r"\bkm(?:s)?\s*factur(?:é|es)\s*[:\-]?\s*([0-9][0-9\s\u00A0\u202F]{1,20})\b",
    flags=re.IGNORECASE,
)

PAT_KMS_DEPART = re.compile(
    r"\bkm(?:s)?\s*(?:départ|depart)\s*[:\-]?\s*([0-9][0-9\s\u00A0\u202F\.,]{1,20})\b",
    flags=re.IGNORECASE,
)
PAT_KMS_RETOUR = re.compile(
    r"\bkm(?:s)?\s*(?:retour)\s*[:\-]?\s*([0-9][0-9\s\u00A0\u202F\.,]{1,20})\b",
    flags=re.IGNORECASE,
)

PAT_KM_OUT = re.compile(
    r"\b(?:km|kms|mileage|odometer|compteur)\s*"
    r"(?:out|sort(?:ant)?|départ|depart)\b.*?([0-9][0-9\s\u00A0\u202F]{1,20})",
    flags=re.IGNORECASE | re.DOTALL,
)
PAT_KM_IN = re.compile(
    r"\b(?:km|kms|mileage|odometer|compteur)\s*"
    r"(?:in|entrant|retour)\b.*?([0-9][0-9\s\u00A0\u202F]{1,20})",
    flags=re.IGNORECASE | re.DOTALL,
)
PAT_EUROPCAR_KM_PARCOURUS = re.compile(
    r"Kilom[\wèéêë]*\s+Parcourus\s*[:\-]?\s*([0-9]{1,6})",
    flags=re.IGNORECASE,
)
PAT_LCD_KM_PARCOURUS = re.compile(
    r"Km\s*Parcourus\s*([0-9]{1,6})",
    flags=re.IGNORECASE,
)

# ============ LCD : TABLE extraction (le vrai fix) ============

def _extract_lcd_from_tables(pdf_bytes: bytes, filename: str, debug: bool) -> Optional[float]:
    """
    Cherche une table avec header contenant Km Départ / Km Retour / Km Parcourus,
    puis lit la valeur de la colonne Km Parcourus sur la ligne de données.
    """
    try:
        import pdfplumber
    except Exception as e:
        _dbg(debug, "pdfplumber missing:", repr(e))
        return None

    def norm_cell(x: object) -> str:
        return _norm_spaces(str(x or "")).strip().lower()

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for p_i, page in enumerate(pdf.pages[:3]):
            tables = page.extract_tables() or []
            for t_i, table in enumerate(tables):
                if not table:
                    continue

                # trouver une ligne header
                header_idx = None
                col_dep = col_ret = col_par = None

                for r_i, row in enumerate(table):
                    row_norm = [norm_cell(c) for c in (row or [])]
                    joined = " ".join(row_norm)

                    if ("km départ" in joined or "km depart" in joined) and "km retour" in joined and "km parcour" in joined:
                        header_idx = r_i

                        # localiser index de colonnes
                        for c_i, c in enumerate(row_norm):
                            if "km départ" in c or "km depart" in c:
                                col_dep = c_i
                            elif "km retour" in c:
                                col_ret = c_i
                            elif "km parcour" in c:
                                col_par = c_i

                        _dbg(debug, f"LCD table header found p{p_i} t{t_i} r{r_i} cols:", col_dep, col_ret, col_par)
                        break

                if header_idx is None or col_par is None:
                    continue

                # lire les lignes après header
                for row in table[header_idx + 1:]:
                    if not row:
                        continue

                    # valeur km parcourus
                    cell_par = row[col_par] if col_par < len(row) else None
                    km_par = _to_int(cell_par)

                    # garde-fou: km parcourus est petit (1..5000)
                    if 1 <= km_par <= 5000:
                        _dbg(debug, "LCD table data row:", row, "-> km_parcourus:", km_par)
                        return float(km_par)

                # si pas trouvé, continuer (autre table)
    return None


# ============ LCD : label->value (fallback texte) ============

_NUM_TOKEN = re.compile(r"(?<![A-Za-z])\d[\d\s\u00A0\u202F\.,]{0,18}(?![A-Za-z])")

def _find_label_candidates(text: str, label_re: re.Pattern, *, max_after: int, max_before: int,
                           debug: bool, name: str) -> List[Tuple[int, str]]:
    t = _norm_spaces(text)
    out: List[Tuple[int, str]] = []

    for m in label_re.finditer(t):
        after = t[m.end(): m.end() + max_after]
        mnum_after = _NUM_TOKEN.search(after)
        if mnum_after:
            raw = mnum_after.group(0)
            val = _to_int(raw)
            ctx = after[max(0, mnum_after.start() - 15): mnum_after.end() + 15]
            if debug:
                _dbg(debug, f"{name} cand after raw={raw!r} val={val} ctx='{ctx.replace(chr(10),' ')}'")
            out.append((val, ctx))

        before_start = max(0, m.start() - max_before)
        before = t[before_start: m.start()]
        nums = list(_NUM_TOKEN.finditer(before))
        if nums:
            mnum_b = nums[-1]
            raw = mnum_b.group(0)
            val = _to_int(raw)
            ctx = before[max(0, mnum_b.start() - 15): mnum_b.end() + 15]
            if debug:
                _dbg(debug, f"{name} cand before raw={raw!r} val={val} ctx='{ctx.replace(chr(10),' ')}'")
            out.append((val, ctx))

    return out

def _pick_km(cands: List[Tuple[int, str]], kind: str) -> Optional[int]:
    def plausible(v: int) -> bool:
        if kind in ("depart", "retour"):
            return 1000 <= v <= 300000
        if kind == "parcourus":
            return 1 <= v <= 5000
        return v > 0

    for v, ctx in cands:
        ctx_l = ctx.lower()
        if "€" in ctx or " eur" in ctx_l or "ttc" in ctx_l:
            continue
        if re.search(r"\b\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}\b", ctx):
            continue
        if re.search(r"\b\d{1,2}:\d{2}\b", ctx):
            continue
        if plausible(v):
            return v

    for v, _ in cands:
        if plausible(v):
            return v
    return None

def _extract_lcd_km_from_text(text: str, debug: bool) -> Optional[float]:
    re_dep = re.compile(r"\bkm\s*d[ée]part\b", flags=re.IGNORECASE)
    re_ret = re.compile(r"\bkm\s*retour\b", flags=re.IGNORECASE)
    re_par = re.compile(r"\bkm\s*parcour(?:u|us)\b", flags=re.IGNORECASE)

    dep_c = _find_label_candidates(text, re_dep, max_after=140, max_before=80, debug=debug, name="LCD dep")
    ret_c = _find_label_candidates(text, re_ret, max_after=140, max_before=80, debug=debug, name="LCD ret")
    par_c = _find_label_candidates(text, re_par, max_after=140, max_before=80, debug=debug, name="LCD par")

    km_dep = _pick_km(dep_c, "depart")
    km_ret = _pick_km(ret_c, "retour")
    km_par = _pick_km(par_c, "parcourus")

    _dbg(debug, "LCD picked:", {"dep": km_dep, "ret": km_ret, "par": km_par})

    if km_par is not None:
        return float(km_par)

    if km_dep is not None and km_ret is not None:
        diff = abs(km_ret - km_dep)
        if 1 <= diff <= 5000:
            _dbg(debug, "LCD diff fallback:", km_dep, km_ret, "=>", diff)
            return float(diff)

    return None


# ============ Main ============

def extract_rental_from_pdf_bytes(pdf_bytes: bytes, filename: str, debug: bool = False) -> RidesExtraction:
    text = _norm_spaces(pdf_to_text(pdf_bytes, max_pages=5))

    _dbg(debug, "=====", filename, "=====")
    _dbg(debug, "text_len:", len(text))

    # pdfplumber fallback si texte vide
    if not text.strip():
        _dbg(debug, "⚠️ texte vide via pdf_to_text -> tentative pdfplumber fallback")
        try:
            import pdfplumber
            chunks = []
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page in pdf.pages[:5]:
                    chunks.append(page.extract_text() or "")
            text = _norm_spaces("\n".join(chunks))
        except Exception as e:
            _dbg(debug, "pdfplumber fallback failed:", repr(e))

    # OCR fallback si toujours vide
    if not text.strip():
        _dbg(debug, "⚠️ texte toujours vide -> tentative OCR (ocrmypdf)")
        try:
            ocr_bytes = ocr_pdf_bytes(pdf_bytes, lang="eng")  # "fra+eng" si dispo
            text = _norm_spaces(pdf_to_text(ocr_bytes, max_pages=5))
            _dbg(debug, "text_len_after_ocr:", len(text))
        except Exception as e:
            _dbg(debug, "❌ OCR failed:", repr(e))
            return RidesExtraction(rows=[])
        if not text.strip():
            _dbg(debug, "❌ OCR ok mais toujours aucun texte détecté")
            return RidesExtraction(rows=[])

    # Debug lignes intéressantes
    if debug:
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        keys = ("km", "kms", "depart", "retour", "total", "parcourus")
        hits = [l for l in lines if any(k in l.lower() for k in keys)]
        _dbg(debug, f"nb lignes intéressantes: {len(hits)}")
        for l in hits[:120]:
            _dbg(debug, " ", l)
    
    # ============================================================
    # 1) LCD TABLE MODE (PRIORITÉ ABSOLUE) => récupère 764
    # ============================================================
    lcd_table_km = _extract_lcd_from_tables(pdf_bytes, filename, debug)
    if lcd_table_km is not None:
        return RidesExtraction(rows=[_make_row(filename, lcd_table_km)])

    # ============================================================
    # 2) LCD texte fallback
    # ============================================================
    lcd_text_km = _extract_lcd_km_from_text(text, debug)
    if lcd_text_km is not None:
        return RidesExtraction(rows=[_make_row(filename, lcd_text_km)])
        # EUROPCAR : "Kilomètres Parcourus 77"
    m_euro = PAT_EUROPCAR_KM_PARCOURUS.search(text)
    if m_euro:
        km = _to_int(m_euro.group(1))
        if km > 0:
            _dbg(debug, "EUROPCAR km parcourus:", m_euro.group(0), "->", km)
            return RidesExtraction(rows=[_make_row(filename, float(km))])
    # LCD (tableau) : "Km Parcourus 439"
    m_lcd = PAT_LCD_KM_PARCOURUS.search(text)
    if m_lcd:
         km = _to_int(m_lcd.group(1))
         if km > 0:
            _dbg(debug, "LCD km parcourus:", m_lcd.group(0), "->", km)
            return RidesExtraction(rows=[_make_row(filename, float(km))])   

    # LCD fallback multi-ligne
    m_lcd_block = re.search(
     r"Km\s*Parcourus\s*[\n\r\s]+([0-9]{1,6})",
    text,
     flags=re.IGNORECASE,
    )
    if m_lcd_block:
     km = _to_int(m_lcd_block.group(1))
    if km > 0:
        _dbg(debug, "LCD km parcourus (block):", km)
        return RidesExtraction(rows=[_make_row(filename, float(km))])
    # ============================================================
    # 3) Enterprise
    # ============================================================
    m_ent = PATTERN_ENTERPRISE_BLOCK.search(text)
    if m_ent:
        km_depart = _to_int(m_ent.group(1))
        km_retour = _to_int(m_ent.group(2))
        km_total = _to_int(m_ent.group(3))
        diff = abs(km_retour - km_depart)

        if km_total >= 10 and abs(diff - km_total) <= 3:
            return RidesExtraction(rows=[_make_row(filename, float(km_total))])
        if 1 <= diff <= 5000:
            return RidesExtraction(rows=[_make_row(filename, float(diff))])

    # ============================================================
    # 4) Salva depart/retour
    # ============================================================
    m_dep = PAT_KMS_DEPART.search(text)
    m_ret = PAT_KMS_RETOUR.search(text)
    if m_dep and m_ret:
        km_depart = _to_int(m_dep.group(1))
        km_retour = _to_int(m_ret.group(1))
        diff = abs(km_retour - km_depart)
        if diff > 0:
            return RidesExtraction(rows=[_make_row(filename, float(diff))])
    # EUROPCAR : "Kilomètres Parcourus 77"
    m_euro = PAT_EUROPCAR_KM_PARCOURUS.search(text)
    if m_euro:
        km = _to_int(m_euro.group(1))
        if km > 0:
            _dbg(debug, "Europcar kilomètres parcourus:", m_euro.group(0), "->", km)
            return RidesExtraction(rows=[_make_row(filename, float(km))])
    # ============================================================
    # 5) kms parcourus / facturés
    # ============================================================
    m_parc = PAT_KMS_PARCOURUS.search(text)
    if m_parc:
        km = _to_int(m_parc.group(1))
        if 1 <= km <= 5000:
            return RidesExtraction(rows=[_make_row(filename, float(km))])

    m_fact = PAT_KMS_FACTURES.search(text)
    if m_fact:
        km = _to_int(m_fact.group(1))
        if km > 0:
            return RidesExtraction(rows=[_make_row(filename, float(km))])

    # ============================================================
    # 6) OUT/IN en dernier (strict)
    # ============================================================
    m_out = PAT_KM_OUT.search(text)
    m_in = PAT_KM_IN.search(text)
    if m_out and m_in:
        out_km = _to_int(m_out.group(1))
        in_km = _to_int(m_in.group(1))
        diff = abs(in_km - out_km)
        if out_km >= 1000 and in_km >= 1000 and 1 <= diff <= 5000:
            return RidesExtraction(rows=[_make_row(filename, float(diff))])
        _dbg(debug, "out/in ignoré (diff hors plage):", out_km, in_km, diff)

    _dbg(debug, "❌ aucun km détecté")
    return RidesExtraction(rows=[])