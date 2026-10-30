import jwt

from app.config import settings

PASSWORD = "abc@12345"
JOB = {
    "title": "Python Developer",
    "description": "Build APIs with FastAPI and Postgres",
    "location": "Remote",
    "employment_type": "full_time",
}
PDF = ("resume.pdf", b"%PDF-1.4 fake pdf content", "application/pdf")


def make_user(client, email, role):
    client.post("/auth/register", json={"email": email, "password": PASSWORD, "role": role})
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def make_application(client, employer, candidate):
    job_id = client.post("/jobs", json=JOB, headers=employer).json()["id"]
    res = client.post(f"/jobs/{job_id}/apply", files={"resume": PDF}, headers=candidate)
    return res.json()["id"]


def get_token(client, application_id, headers):
    return client.post(f"/applications/{application_id}/interview-token", headers=headers)


def test_candidate_gets_token_for_own_application(client):
    emp = make_user(client, "emp@example.com", "employer")
    cand = make_user(client, "cand@example.com", "candidate")
    app_id = make_application(client, emp, cand)

    res = get_token(client, app_id, cand)
    assert res.status_code == 200
    body = res.json()
    assert body["room"] == f"interview-{app_id}"
    assert body["url"] == settings.livekit_url
    assert body["token"]


def test_token_is_signed_and_limited_to_that_room(client):
    emp = make_user(client, "emp@example.com", "employer")
    cand = make_user(client, "cand@example.com", "candidate")
    app_id = make_application(client, emp, cand)
    me = client.get("/auth/me", headers=cand).json()

    body = get_token(client, app_id, cand).json()
    claims = jwt.decode(body["token"], settings.livekit_api_secret, algorithms=["HS256"])

    assert claims["iss"] == settings.livekit_api_key
    assert claims["sub"] == me["id"]
    assert claims["video"]["room"] == f"interview-{app_id}"
    assert claims["video"]["roomJoin"] is True


def test_other_candidate_cannot_get_token_404(client):
    emp = make_user(client, "emp@example.com", "employer")
    cand1 = make_user(client, "c1@example.com", "candidate")
    cand2 = make_user(client, "c2@example.com", "candidate")
    app_id = make_application(client, emp, cand1)
    assert get_token(client, app_id, cand2).status_code == 404


def test_employer_cannot_get_token_403(client):
    emp = make_user(client, "emp@example.com", "employer")
    cand = make_user(client, "cand@example.com", "candidate")
    app_id = make_application(client, emp, cand)
    assert get_token(client, app_id, emp).status_code == 403


def test_missing_application_404(client):
    cand = make_user(client, "cand@example.com", "candidate")
    missing = "00000000-0000-0000-0000-000000000000"
    assert get_token(client, missing, cand).status_code == 404


def test_token_without_login_rejected(client):
    missing = "00000000-0000-0000-0000-000000000000"
    res = client.post(f"/applications/{missing}/interview-token")
    assert res.status_code in (401, 403)