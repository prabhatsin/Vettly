import io

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.core.parsing import extract_text

PASSWORD = "abc@12345"
JOB = {
    "title": "Python Developer",
    "description": "Build APIs with FastAPI and Postgres",
    "location": "Remote",
    "employment_type": "full_time",
}


def make_pdf_with_text(text: str) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=200)

    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )

    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode())
    page[NameObject("/Contents")] = writer._add_object(stream)

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def make_user(client, email, role):
    client.post("/auth/register", json={"email": email, "password": PASSWORD, "role": role})
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_extract_text_reads_pdf(temp_upload_dir):
    (temp_upload_dir / "r.pdf").write_bytes(make_pdf_with_text("Python FastAPI developer"))
    assert "Python FastAPI developer" in extract_text("r.pdf")


def test_extract_text_missing_file_returns_empty(temp_upload_dir):
    assert extract_text("does-not-exist.pdf") == ""


def test_extract_text_corrupt_pdf_returns_empty(temp_upload_dir):
    (temp_upload_dir / "bad.pdf").write_bytes(b"%PDF-1.4 not really a pdf")
    assert extract_text("bad.pdf") == ""


def test_apply_stores_resume_text(client, db):
    from app.models.application import Application
    from sqlalchemy import select

    emp = make_user(client, "emp@example.com", "employer")
    cand = make_user(client, "cand@example.com", "candidate")
    job_id = client.post("/jobs", json=JOB, headers=emp).json()["id"]

    pdf = make_pdf_with_text("Skills: Python Postgres")
    res = client.post(
        f"/jobs/{job_id}/apply",
        files={"resume": ("cv.pdf", pdf, "application/pdf")},
        headers=cand,
    )
    assert res.status_code == 201
    assert "resume_text" not in res.json()

    app_row = db.scalar(select(Application))
    assert "Skills: Python Postgres" in app_row.resume_text


def test_apply_with_unparseable_pdf_still_succeeds(client, db):
    from app.models.application import Application
    from sqlalchemy import select

    emp = make_user(client, "emp@example.com", "employer")
    cand = make_user(client, "cand@example.com", "candidate")
    job_id = client.post("/jobs", json=JOB, headers=emp).json()["id"]

    res = client.post(
        f"/jobs/{job_id}/apply",
        files={"resume": ("cv.pdf", b"%PDF-1.4 fake", "application/pdf")},
        headers=cand,
    )
    assert res.status_code == 201
    assert db.scalar(select(Application)).resume_text in ("", None)