
from pathlib import Path

from pypdf import PdfReader

from app.config import settings


def extract_text(filename: str) -> str:
    try:
        reader = PdfReader(Path(settings.upload_dir) / filename)
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages).strip()
    except Exception:
        return ""