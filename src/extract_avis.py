# src/extract_avis.py
import tempfile, json, re
from dotenv import load_dotenv
from openai import OpenAI
from schemas import RidesExtraction

load_dotenv()
client = OpenAI()

PROMPT_AVIS = """
Tu lis une facture AVIS de location de voiture.

Retourne UNIQUEMENT un JSON valide :
{
  "rows": [
    {
      "cheque_or_course": "N° Contrat ou N° Facture si présent",
      "date_time_start": "Date de départ si présente",
      "date_time_end": "Date de retour si présente",
      "pickup_address": "Location Départ (lieu) si présent",
      "destination_address": "Location Retour (lieu) si présent",
      "passenger": "Conducteur si présent",
      "reported_km": 774
    }
  ]
}

Règles:
- Cherche explicitement la ligne 'Km Parcours' / 'Km Parcourus' / 'Km Parcours :'.
- 'reported_km' doit être un nombre (sans 'km').
- Si pickup/destination n’existent pas, mets null (mais garde reported_km).
- Ne mets qu’une seule ligne dans rows (la location).
"""

def _safe_json(text: str) -> dict:
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`").replace("json\n", "", 1).strip()
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end != -1 and end > start:
        t = t[start:end+1]
    return json.loads(t)

def extract_avis_from_pdf_bytes(pdf_bytes: bytes, filename: str) -> RidesExtraction:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
        tmp.write(pdf_bytes); tmp.flush()
        with open(tmp.name, "rb") as f:
            uploaded = client.files.create(file=f, purpose="assistants")

    resp = client.responses.create(
        model="gpt-5",
        input=[{
            "role": "user",
            "content": [
                {"type": "input_text", "text": PROMPT_AVIS},
                {"type": "input_file", "file_id": uploaded.id},
            ],
        }],
    )

    out = getattr(resp, "output_text", None) or str(resp)
    data = _safe_json(out)
    return RidesExtraction.model_validate(data)
