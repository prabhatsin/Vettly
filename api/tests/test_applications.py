PASSWORD = "abc@12345"

JOB = {
    "title": "Python Developer",
    "description": "Build APIs with FastAPI and Postgres",
    "location": "Remote",
    "employment_type": "full_time",
}

PDF = ("resume.pdf", b"%PDF-1.4 fake pdf content", "application/pdf")
NOT_PDF = ("resume.pdf", b"just plain text", "application/pdf")


def make_user(client, email, role):
    client.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD, "role": role},
    )
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def make_job(client, employer):
    return client.post("/jobs", json=JOB, headers=employer).json()["id"]


def apply(client, job_id, headers, file=PDF):
    return client.post(
        f"/jobs/{job_id}/apply", files={"resume": file}, headers=headers
    )


def test_candidate_applies_201(client, temp_upload_dir):
    emp = make_user(client, "emp@example.com", "employer")
    cand = make_user(client, "cand@example.com", "candidate")
    job_id = make_job(client, emp)

    res = apply(client, job_id, cand)
    assert res.status_code == 201
    body = res.json()
    assert body["job_id"] == job_id
    assert body["status"] == "submitted"
    assert "resume_path" not in body
    assert len(list(temp_upload_dir.glob("*.pdf"))) == 1


def test_duplicate_application_409_and_no_orphan_file(client, temp_upload_dir):
    emp = make_user(client, "emp@example.com", "employer")
    cand = make_user(client, "cand@example.com", "candidate")
    job_id = make_job(client, emp)

    apply(client, job_id, cand)
    assert apply(client, job_id, cand).status_code == 409
    assert len(list(temp_upload_dir.glob("*.pdf"))) == 1


def test_non_pdf_rejected_400(client):
    emp = make_user(client, "emp@example.com", "employer")
    cand = make_user(client, "cand@example.com", "candidate")
    job_id = make_job(client, emp)
    assert apply(client, job_id, cand, file=NOT_PDF).status_code == 400


def test_too_large_rejected_400(client):
    emp = make_user(client, "emp@example.com", "employer")
    cand = make_user(client, "cand@example.com", "candidate")
    job_id = make_job(client, emp)
    big = ("big.pdf", b"%PDF" + b"0" * (5 * 1024 * 1024 + 1), "application/pdf")
    assert apply(client, job_id, cand, file=big).status_code == 400


def test_employer_cannot_apply_403(client):
    emp = make_user(client, "emp@example.com", "employer")
    job_id = make_job(client, emp)
    assert apply(client, job_id, emp).status_code == 403


def test_apply_to_missing_job_404(client):
    cand = make_user(client, "cand@example.com", "candidate")
    missing = "00000000-0000-0000-0000-000000000000"
    assert apply(client, missing, cand).status_code == 404


def test_apply_to_closed_job_404(client):
    emp = make_user(client, "emp@example.com", "employer")
    cand = make_user(client, "cand@example.com", "candidate")
    job_id = make_job(client, emp)
    client.delete(f"/jobs/{job_id}", headers=emp)
    assert apply(client, job_id, cand).status_code == 404


def test_candidate_lists_only_own_applications(client):
    emp = make_user(client, "emp@example.com", "employer")
    cand1 = make_user(client, "c1@example.com", "candidate")
    cand2 = make_user(client, "c2@example.com", "candidate")
    job_id = make_job(client, emp)
    apply(client, job_id, cand1)
    apply(client, job_id, cand2)

    res = client.get("/applications/mine", headers=cand1)
    assert res.status_code == 200
    assert len(res.json()) == 1


def test_employer_cannot_use_applications_mine(client):
    emp = make_user(client, "emp@example.com", "employer")
    assert client.get("/applications/mine", headers=emp).status_code == 403


def test_owner_sees_job_applications(client):
    emp = make_user(client, "emp@example.com", "employer")
    cand = make_user(client, "cand@example.com", "candidate")
    job_id = make_job(client, emp)
    apply(client, job_id, cand)

    res = client.get(f"/jobs/{job_id}/applications", headers=emp)
    assert res.status_code == 200
    assert len(res.json()) == 1


def test_other_employer_cannot_see_applications_403(client):
    emp1 = make_user(client, "emp1@example.com", "employer")
    emp2 = make_user(client, "emp2@example.com", "employer")
    job_id = make_job(client, emp1)
    res = client.get(f"/jobs/{job_id}/applications", headers=emp2)
    assert res.status_code == 403


def test_candidate_cannot_see_job_applications_403(client):
    emp = make_user(client, "emp@example.com", "employer")
    cand = make_user(client, "cand@example.com", "candidate")
    job_id = make_job(client, emp)
    res = client.get(f"/jobs/{job_id}/applications", headers=cand)
    assert res.status_code == 403