# src/pdf_text.py
import fitz  # PyMuPDF

def pdf_to_text(pdf_bytes: bytes, max_pages: int = 5) -> str:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    txt = []
    for p in range(min(max_pages, doc.page_count)):
        txt.append(doc[p].get_text("text"))
    return "\n".join(txt)
