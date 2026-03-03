# src/ocr_utils.py
import subprocess
import tempfile
from pathlib import Path

def ocr_pdf_bytes(pdf_bytes: bytes, *, lang: str = "fra+eng") -> bytes:
    """
    Lance OCRmyPDF sur un PDF (bytes) et renvoie un PDF "text-searchable" (bytes).
    Nécessite: ocrmypdf + tesseract installés.
    """
    with tempfile.TemporaryDirectory() as d:
        dpath = Path(d)
        in_pdf = dpath / "in.pdf"
        out_pdf = dpath / "out.pdf"
        in_pdf.write_bytes(pdf_bytes)

        cmd = [
            "ocrmypdf",
                      # si déjà du texte, ne refait pas tout
            "--force-ocr",          # force OCR sur pages image
            "--rotate-pages",       # corrige orientation
            "--deskew",             # redresse
            "--optimize", "1",
            "--output-type", "pdf",
            "-l", "fra+eng",
            str(in_pdf),
             str(out_pdf),
        ]

        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(
                "OCRmyPDF failed\n"
                f"STDOUT:\n{proc.stdout}\n\n"
                f"STDERR:\n{proc.stderr}\n"
    )
        return out_pdf.read_bytes()