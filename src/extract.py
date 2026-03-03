# src/extract.py
import os, sys
SRC_DIR = os.path.dirname(__file__)
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from extract_g7 import extract_g7_rides_from_pdf_bytes, detect_doc_type

def extract_rides_from_pdf_bytes(pdf_bytes: bytes, filename: str, doc_type: str = "g7", anonymize: bool = False):
    return extract_g7_rides_from_pdf_bytes(pdf_bytes, filename, anonymize=anonymize)

__all__ = ["extract_rides_from_pdf_bytes", "detect_doc_type"]
