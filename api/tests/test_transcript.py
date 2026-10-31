
PASSWORD = "abc@12345"
JOB = {
    "title": "Python Developer",
    "description": "Build APIs with FastAPI and Postgres",
    "location": "Remote",
    "employment_type": "full_time",
}
PDF = ("resume.pdf", b"%PDF-1.4 fake pdf content", "application/pdf")
ENTRIES = {
    "entries": [
        {"role": "interviewer", "text": "Hi, please introduce yourself."},
        {"role": "candidate", "text": "I am a Python developer."},
    ]
}


def make_user(client, email, role):
    client.post("/auth/register", json={"email": email, "password": PASSWORD, "role": role})
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def setup(client):
    emp = make_user(client, "emp@example.com", "employer")
    cand = make_user(client, "cand@example.com", "candidate")
    job_id = client.post("/jobs", json=JOB, headers=emp).json()["id"]
    app_id = client.post(
        f"/jobs/{job_id}/apply", files={"resume": PDF}, headers=cand
    ).json()["id"]
    return emp, cand, app_id


def internal(key=None):
    from app.config import settings

    return {"X-Internal-Key": key or settings.internal_api_key}


def save(client, app_id, body=ENTRIES, headers=None):
    return client.post(
        f"/internal/applications/{app_id}/transcript",
        json=body,
        headers=headers or internal(),
    )


def test_save_without_key_rejected(client):
    _, _, app_id = setup(client)
    res = client.post(f"/internal/applications/{app_id}/transcript", json=ENTRIES)
    assert res.status_code == 403


def test_save_with_wrong_key_rejected(client):
    _, _, app_id = setup(client)
    assert save(client, app_id, headers=internal("wrong")).status_code == 403


def test_save_and_candidate_reads_in_order(client):
    _, cand, app_id = setup(client)
    assert save(client, app_id).status_code == 201

    res = client.get(f"/applications/{app_id}/transcript", headers=cand)
    assert res.status_code == 200
    assert [e["role"] for e in res.json()] == ["interviewer", "candidate"]
    assert res.json()[1]["text"] == "I am a Python developer."


def test_save_twice_replaces_not_duplicates(client):
    _, cand, app_id = setup(client)
    save(client, app_id)
    save(client, app_id)
    res = client.get(f"/applications/{app_id}/transcript", headers=cand)
    assert len(res.json()) == 2


def test_save_marks_application_interviewed(client):
    _, cand, app_id = setup(client)
    save(client, app_id)
    apps = client.get("/applications/mine", headers=cand).json()
    assert apps[0]["status"] == "interviewed"


def test_agent_only_speech_keeps_status_submitted(client):
    _, cand, app_id = setup(client)
    body = {"entries": [{"role": "interviewer", "text": "Hello?"}]}
    save(client, app_id, body=body)
    apps = client.get("/applications/mine", headers=cand).json()
    assert apps[0]["status"] == "submitted"


def test_owner_employer_can_read(client):
    emp, _, app_id = setup(client)
    save(client, app_id)
    assert client.get(f"/applications/{app_id}/transcript", headers=emp).status_code == 200


def test_other_candidate_and_other_employer_get_404(client):
    _, _, app_id = setup(client)
    save(client, app_id)
    other_cand = make_user(client, "c2@example.com", "candidate")
    other_emp = make_user(client, "e2@example.com", "employer")
    assert client.get(f"/applications/{app_id}/transcript", headers=other_cand).status_code == 404
    assert client.get(f"/applications/{app_id}/transcript", headers=other_emp).status_code == 404


def test_save_missing_application_404(client):
    missing = "00000000-0000-0000-0000-000000000000"
    assert save(client, missing).status_code == 404


def test_empty_text_rejected_422(client):
    _, _, app_id = setup(client)
    body = {"entries": [{"role": "candidate", "text": ""}]}
    assert save(client, app_id, body=body).status_code == 422