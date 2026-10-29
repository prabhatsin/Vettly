
#? What does this file do ??
'''
It takes the résumé a candidate uploads, checks it's a real PDF under 5 MB, saves it to disk under a 
random filename, and returns that filename so the database can store it in resume_path.
'''

import uuid
from pathlib import Path

from fastapi import UploadFile

from app.config import settings

MAX_RESUME_BYTES = 5 * 1024 * 1024


class InvalidResume(Exception):
    pass

def save_resume(file: UploadFile) -> str:
    data = file.file.read(MAX_RESUME_BYTES + 1)
    if len(data) > MAX_RESUME_BYTES:
        raise InvalidResume("File too large (max 5 MB)")
    if not data.startswith(b"%PDF"):
        raise InvalidResume("Only PDF files are allowed")

    folder = Path(settings.upload_dir)
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4()}.pdf"
    (folder / filename).write_bytes(data)
    return filename