# app.py
import os
import sys
import re

# Permet d'importer les modules dans /src
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import streamlit as st
import pandas as pd
from dotenv import load_dotenv

from routes import driving_km, geocode_place, haversine_km
from cache_sqlite import SQLiteCache
from extract_router import extract_any

load_dotenv()

# -------------------------
# HELPERS
# -------------------------
def normalize_place_basic(name: str) -> str:
    s = (name or "").strip()
    s = s.replace("\u00A0", " ").replace("\u202F", " ")
    s = re.sub(r"\s+", " ", s).strip()

    s = re.sub(r"\bGARE\b$", "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r"\bCEDEX\b.*$", "", s, flags=re.IGNORECASE).strip()

    s = s.replace("SAINT LAZARE", "SAINT-LAZARE")
    s = s.replace("PART DIEU", "PART-DIEU")
    s = s.replace("SAINT JEAN", "SAINT-JEAN")

    return s


def geocode_place_smart(name: str, doc_type: str = ""):
    base = normalize_place_basic(name)
    if not base:
        return None

    candidates = [base]

    if doc_type == "tgv":
        candidates += [
            f"{base}, France",
            f"Gare de {base}, France",
            f"{base} gare, France",
        ]
    elif doc_type == "air":
        candidates += [
            f"{base}, France",
            f"Aéroport de {base}, France",
        ]
    else:
        candidates += [
            f"{base}, France",
        ]

    seen = set()
    uniq_candidates = []
    for c in candidates:
        key = c.strip().lower()
        if key not in seen:
            seen.add(key)
            uniq_candidates.append(c)

    for cand in uniq_candidates:
        coords = geocode_place(cand)
        if coords:
            return coords

    return None


# -------------------------
# CONFIG PAGE
# -------------------------
st.set_page_config(page_title="Code Carbone – CLAAP", layout="wide")

# -------------------------
# CSS
# -------------------------
st.markdown(
    """
<style>
:root {
  --brand-blue: #1E4FFF;
}

/* Sidebar background */
section[data-testid="stSidebar"]{
  background: linear-gradient(180deg, #0B0F1A 0%, #0A1024 100%);
  border-right: 1px solid rgba(255,255,255,0.08);
}

/* Sidebar text */
section[data-testid="stSidebar"] *{
  color: #FFFFFF !important;
}

/* Header underline */
h1{
  position: relative;
  padding-bottom: 10px;
  letter-spacing: -0.02em;
}
h1::after{
  content:"";
  position:absolute;
  left:0;
  bottom:0;
  width:120px;
  height:4px;
  border-radius:999px;
  background: var(--brand-blue);
}

/* File uploader */
div[data-testid="stFileUploaderDropzone"]{
  border: 2px dashed rgba(30,79,255,0.45);
  background: rgba(30,79,255,0.06);
}
div[data-testid="stFileUploaderDropzone"]:hover{
  border-color: rgba(30,79,255,0.75);
  background: rgba(30,79,255,0.10);
}

/* Buttons */
.stButton button, .stDownloadButton button{
  background: var(--brand-blue) !important;
  border: none !important;
  border-radius: 12px !important;
  color: white !important;
  font-weight: 600 !important;
}
.stButton button:hover, .stDownloadButton button:hover{
  filter: brightness(1.08);
}

/* Progress bar */
div[data-testid="stProgress"] > div > div{
  background-color: var(--brand-blue) !important;
}

/* KPI cards */
div[data-testid="stMetric"]{
  background: rgba(30,79,255,0.06);
  border: 1px solid rgba(30,79,255,0.15);
  border-radius: 16px;
  padding: 14px;
}
</style>
""",
    unsafe_allow_html=True,
)

# -------------------------
# SIDEBAR
# -------------------------
with st.sidebar:
    st.markdown(
        """
        <div style="
            background: white;
            padding: 14px 12px;
            border-radius: 16px;
            margin-bottom: 12px;
            text-align: center;">
        """,
        unsafe_allow_html=True,
    )
    st.image("assets/fremantle.png", width=220)
    st.markdown("</div>", unsafe_allow_html=True)

    st.header("Paramètres")
    do_distance = st.toggle("Calculer les km (Google)", value=True)
    use_reported_default = st.toggle("Préférer km déclaré", value=True)

    st.divider()
    st.subheader("Debug console")
    debug_tgv = st.toggle("TGV", value=False)
    debug_rental = st.toggle("Rental", value=False)
    debug_g7 = st.toggle("G7", value=False)
    debug_air = st.toggle("Air", value=False)

    st.divider()
    show_all_cols = st.toggle("Afficher toutes les colonnes", value=False)

# -------------------------
# HEADER
# -------------------------
st.title("Code Carbone – Extraction trajets (PDF) + km")
st.caption("Analyse automatisée des déplacements – Fremantle France")

# -------------------------
# UPLOAD
# -------------------------
uploaded_files = st.file_uploader(
    "Upload tes fichiers",
    type=["pdf", "csv"],
    accept_multiple_files=True,
)

if not uploaded_files:
    st.info("Upload au moins un fichier pour commencer.")
    st.stop()

cache = SQLiteCache("distance_cache.sqlite")

all_rows = []
errors = []

# -------------------------
# EXTRACTION
# -------------------------
with st.status("Extraction en cours...", expanded=False) as status:
    progress_bar = st.progress(0)
    n = len(uploaded_files)

    for i, uf in enumerate(uploaded_files, start=1):
        progress_bar.progress(int(i / n * 100))

        try:
            file_bytes = uf.getvalue()
            filename = uf.name

            doc_type, extraction = extract_any(
                file_bytes,
                filename,
                debug_tgv=debug_tgv,
                debug_rental=debug_rental,
                debug_g7=debug_g7,
            )

            for row in extraction.rows:
                all_rows.append(
                    {
                        "pdf": filename,
                        "doc_type": doc_type,
                        "N° Chèque/Course": row.cheque_or_course,
                        "Début": row.date_time_start,
                        "Fin": row.date_time_end,
                        "Adresse prise en charge": row.pickup_address,
                        "Destination": row.destination_address,
                        "Personne transportée": row.passenger,
                        "reported_km": row.reported_km,
                        "km_computed": getattr(row, "km_computed", None),
                    }
                )

        except Exception as e:
            errors.append((uf.name, str(e)))

    status.update(label="Extraction terminée", state="complete")

df = pd.DataFrame(all_rows)

if df.empty:
    st.warning("Aucune course détectée.")
    if errors:
        st.subheader("Erreurs")
        for f, err in errors:
            st.write(f"- {f}: {err}")
    st.stop()

# -------------------------
# NETTOYAGE
# -------------------------
for col in [
    "Adresse prise en charge",
    "Destination",
    "Début",
    "Fin",
    "Personne transportée",
    "doc_type",
    "pdf",
]:
    if col in df.columns:
        df[col] = df[col].fillna("").astype(str).str.strip()

km_used = []
km_source = []

for _, r in df.iterrows():
    origin = r.get("Adresse prise en charge", "")
    dest = r.get("Destination", "")
    reported = r.get("reported_km")
    precomputed = r.get("km_computed")
    doc_type = r.get("doc_type", "")

    # 1) Priorité au km déclaré
    if use_reported_default and pd.notna(reported) and str(reported).strip() not in ("", "0", "0.0"):
        try:
            val = float(reported)
            if pd.notna(val) and val > 0:
                km_used.append(val)
                km_source.append("reported")
                continue
        except Exception:
            pass

    # 2) Reprendre le km déjà calculé par l'extracteur
    if pd.notna(precomputed) and str(precomputed).strip() not in ("", "0", "0.0"):
        try:
            val = float(precomputed)
            if pd.notna(val) and val > 0:
                km_used.append(val)
                km_source.append("precomputed")
                continue
        except Exception:
            pass

    # 3) TGV / AIR -> Haversine
    if doc_type in ("tgv", "air") and origin and dest:
        origin_coords = geocode_place_smart(origin, doc_type)
        dest_coords = geocode_place_smart(dest, doc_type)

        if debug_tgv and doc_type == "tgv":
            print("[TGV][DEBUG] geocode origin raw   :", origin)
            print("[TGV][DEBUG] geocode origin coords:", origin_coords)
            print("[TGV][DEBUG] geocode dest raw     :", dest)
            print("[TGV][DEBUG] geocode dest coords  :", dest_coords)

        if debug_air and doc_type == "air":
            print("[AIR][DEBUG] geocode origin raw   :", origin)
            print("[AIR][DEBUG] geocode origin coords:", origin_coords)
            print("[AIR][DEBUG] geocode dest raw     :", dest)
            print("[AIR][DEBUG] geocode dest coords  :", dest_coords)

        if origin_coords and dest_coords:
            km = haversine_km(origin_coords, dest_coords)
            km_used.append(float(km))
            km_source.append(f"computed_{doc_type}_haversine")
        else:
            km_used.append(None)
            km_source.append("geocode_failed")
        continue

    # 4) Routier -> Google routes
    if origin and dest:
        key = f"{origin}__{dest}"
        cached = cache.get(key)

        if cached is not None and pd.notna(cached):
            km_used.append(float(cached))
            km_source.append("computed_cached")
            continue

        if do_distance:
            try:
                km = driving_km(origin, dest)
                cache.set(key, km)
                km_used.append(float(km))
                km_source.append("computed_google")
            except Exception:
                km_used.append(None)
                km_source.append("error_google")
        else:
            km_used.append(None)
            km_source.append("skipped")
    else:
        km_used.append(None)
        km_source.append("missing_address")

df["km_used"] = km_used
df["km_source"] = km_source

total_km = pd.to_numeric(df["km_used"], errors="coerce").dropna().sum()

# -------------------------
# KPIs
# -------------------------
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total km", f"{total_km:.2f}")
c2.metric("Trajets", len(df))
c3.metric("PDFs", df["pdf"].nunique() if "pdf" in df.columns else 0)
c4.metric("Erreurs", len(errors))

# -------------------------
# TABS
# -------------------------
tab1, tab2, tab3 = st.tabs(["Trajets", "Analyse", "Erreurs"])

with tab1:
    view = df.copy()

    if not show_all_cols:
        cols = [
            "pdf",
            "doc_type",
            "Début",
            "Adresse prise en charge",
            "Destination",
            "km_used",
            "km_source",
        ]
        view = view[[c for c in cols if c in view.columns]]

    st.dataframe(view, width="stretch", hide_index=True)

    csv_export = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Télécharger CSV",
        csv_export,
        "trajets_extraits.csv",
        mime="text/csv",
    )

with tab2:
    agg = (
        df.assign(km_used_num=pd.to_numeric(df["km_used"], errors="coerce"))
        .groupby("doc_type", dropna=False)["km_used_num"]
        .sum()
        .sort_values(ascending=False)
        .reset_index()
        .rename(columns={"km_used_num": "km_total"})
    )

    st.subheader("Km par type de document")
    st.dataframe(agg, width="stretch", hide_index=True)

    if not agg.empty:
        chart_df = agg.set_index("doc_type")[["km_total"]]
        st.bar_chart(chart_df)

with tab3:
    if not errors:
        st.success("Aucune erreur 🎉")
    else:
        for f, err in errors:
            st.error(f"{f} — {err}")