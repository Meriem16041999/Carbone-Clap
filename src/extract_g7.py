# src/extract_g7.py
import tempfile
import json
from dotenv import load_dotenv
from openai import OpenAI
from schemas import RidesExtraction

load_dotenv()
client = OpenAI()

PROMPT_G7 = """
Tu lis un PDF G7 contenant un tableau "RECAPITULATIF DES COURSES ET PRESTATIONS ASSOCIEES".

Retourne UNIQUEMENT un JSON valide (pas de texte autour), sous la forme:
{
  "rows": [
    {
      "cheque_or_course": "...",
      "date_time_start": "...",
      "date_time_end": "...",
      "pickup_address": "...",
      "destination_address": "...",
      "passenger": "...",
      "reported_km": null
    }
  ]
}

Règles:
- Ignore les lignes "Total ..." ou récapitulatives (pas des courses).
- Ne pas inventer.
- Si pickup ou destination manque: ignore la ligne.
- pickup_address = "Adresse de prise en charge"
- destination_address = "Destination"
- passenger = "Personne transportée"
- cheque_or_course = "N° Chèque ou Course"
- date_time_start/end = "Date Heure Début-Fin" si possible
"""

def detect_doc_type(pdf_bytes: bytes) -> str:
    # Pour l'instant on ne route pas encore par type
    return "g7"

def _safe_json(text: str) -> dict:
    """
    Essaie d'extraire un JSON même si le modèle a ajouté des backticks.
    """
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        # parfois ```json\n...\n```
        t = t.replace("json\n", "", 1).strip()
    # coupe si le modèle a mis du texte avant/après
    start = t.find("{")
    end = t.rfind("}")
    if start != -1 and end != -1 and end > start:
        t = t[start:end+1]
    return json.loads(t)

def extract_g7_rides_from_pdf_bytes(pdf_bytes: bytes, filename: str, anonymize: bool = False) -> RidesExtraction:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
        tmp.write(pdf_bytes)
        tmp.flush()
        with open(tmp.name, "rb") as f:
            uploaded = client.files.create(file=f, purpose="assistants")

    # ✅ IMPORTANT: on n'utilise PAS response_format (compatible SDK)
    resp = client.responses.create(
        model="gpt-5",
        input=[{
            "role": "user",
            "content": [
                {"type": "input_text", "text": PROMPT_G7},
                {"type": "input_file", "file_id": uploaded.id},
            ],
        }],
    )

    # Récupère le texte de sortie
    out = getattr(resp, "output_text", None)
    if not out:
        # fallback si output_text absent
        out = str(resp)

    data = _safe_json(out)
    return RidesExtraction.model_validate(data)
