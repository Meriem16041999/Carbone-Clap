# app.py
import os
import sys

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
# CONFIG PAGE
# -------------------------
st.set_page_config(page_title="Code Carbone – CLAAP", layout="wide")

# -------------------------
# CSS (bleu + sidebar lisible)
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
    # “carte” blanche pour le logo (pour qu’il soit lisible même si logo noir)
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
    "Upload tes PDFs",
    type=["pdf","csv"],
    accept_multiple_files=True,
)

if not uploaded_files:
    st.info("Upload au moins un PDF pour commencer.")
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

# Nettoyage
df["Adresse prise en charge"] = df["Adresse prise en charge"].fillna("").astype(str).str.strip()
df["Destination"] = df["Destination"].fillna("").astype(str).str.strip()

# -------------------------
# CALCUL KM
# -------------------------
# -------------------------
# CALCUL KM
# -------------------------
# -------------------------
# -------------------------
# CALCUL KM
# -------------------------
km_used = []
km_source = []

for _, r in df.iterrows():
    origin = r["Adresse prise en charge"]
    dest = r["Destination"]
    reported = r.get("reported_km")
    precomputed = r.get("km_computed")

    # 1) Priorité au km déclaré
    if use_reported_default and reported not in (None, "", 0):
        km_used.append(float(reported))
        km_source.append("reported")
        continue

    # 2) Reprendre le km déjà calculé par l'extracteur
    if precomputed not in (None, "", 0):
        km_used.append(float(precomputed))
        km_source.append("precomputed")
        continue

    # 3) TGV / AIR -> Haversine
    if r["doc_type"] in ("tgv", "air") and origin and dest:
        origin_coords = geocode_place(origin)
        dest_coords = geocode_place(dest)

        if origin_coords and dest_coords:
            km = haversine_km(origin_coords, dest_coords)
            km_used.append(float(km))
            km_source.append(f"computed_{r['doc_type']}_haversine")
        else:
            km_used.append(None)
            km_source.append("geocode_failed")
        continue

    # 4) Routier -> Google routes
    if origin and dest:
        key = f"{origin}__{dest}"
        cached = cache.get(key)

        if cached is not None:
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
c3.metric("PDFs", df["pdf"].nunique())
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

    # ✅ remplacer use_container_width=True par width="stretch"
    st.dataframe(view, width="stretch", hide_index=True)

    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("Télécharger CSV", csv, "trajets_extraits.csv", mime="text/csv")

with tab2:
    # petite analyse sans plotly
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