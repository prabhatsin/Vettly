PASSWORD = "abc@12345"

JOB = {
    "title": "Python Developer",
    "description": "Build APIs with FastAPI and Postgres",
    "location": "Remote",
    "employment_type": "full_time",
}


def make_user(client, email, role):
    client.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD, "role": role},
    )
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def post_job(client, headers, **overrides):
    return client.post("/jobs", json={**JOB, **overrides}, headers=headers)


def test_employer_creates_job(client):
    emp = make_user(client, "emp@example.com", "employer")
    res = post_job(client, emp)
    assert res.status_code == 201
    body = res.json()
    assert body["title"] == "Python Developer"
    assert body["is_active"] is True


def test_employer_id_comes_from_token_not_body(client):
    emp = make_user(client, "emp@example.com", "employer")
    me = client.get("/auth/me", headers=emp).json()
    res = post_job(client, emp, employer_id="00000000-0000-0000-0000-000000000000")
    assert res.status_code == 201
    assert res.json()["employer_id"] == me["id"]


def test_candidate_cannot_create_job(client):
    cand = make_user(client, "cand@example.com", "candidate")
    assert post_job(client, cand).status_code == 403


def test_create_job_without_token_rejected(client):
    assert client.post("/jobs", json=JOB).status_code in (401, 403)


def test_create_job_validation_422(client):
    emp = make_user(client, "emp@example.com", "employer")
    assert post_job(client, emp, title="ab").status_code == 422


def test_candidate_sees_active_jobs(client):
    emp = make_user(client, "emp@example.com", "employer")
    cand = make_user(client, "cand@example.com", "candidate")
    post_job(client, emp)
    res = client.get("/jobs", headers=cand)
    assert res.status_code == 200
    assert len(res.json()) == 1


def test_mine_lists_only_own_jobs(client):
    emp1 = make_user(client, "emp1@example.com", "employer")
    emp2 = make_user(client, "emp2@example.com", "employer")
    post_job(client, emp1)
    post_job(client, emp2, title="Other Job")
    res = client.get("/jobs/mine", headers=emp1)
    assert [j["title"] for j in res.json()] == ["Python Developer"]


def test_candidate_cannot_use_mine(client):
    cand = make_user(client, "cand@example.com", "candidate")
    assert client.get("/jobs/mine", headers=cand).status_code == 403


def test_get_job_by_id_and_missing_404(client):
    emp = make_user(client, "emp@example.com", "employer")
    job_id = post_job(client, emp).json()["id"]
    assert client.get(f"/jobs/{job_id}", headers=emp).status_code == 200
    missing = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/jobs/{missing}", headers=emp).status_code == 404


def test_owner_can_update(client):
    emp = make_user(client, "emp@example.com", "employer")
    job_id = post_job(client, emp).json()["id"]
    res = client.put(f"/jobs/{job_id}", json={"title": "Senior Python Dev"}, headers=emp)
    assert res.status_code == 200
    assert res.json()["title"] == "Senior Python Dev"
    assert res.json()["description"] == JOB["description"]


def test_other_employer_cannot_update(client):
    emp1 = make_user(client, "emp1@example.com", "employer")
    emp2 = make_user(client, "emp2@example.com", "employer")
    job_id = post_job(client, emp1).json()["id"]
    res = client.put(f"/jobs/{job_id}", json={"title": "Hacked title"}, headers=emp2)
    assert res.status_code == 403


def test_candidate_cannot_update(client):
    emp = make_user(client, "emp@example.com", "employer")
    cand = make_user(client, "cand@example.com", "candidate")
    job_id = post_job(client, emp).json()["id"]
    res = client.put(f"/jobs/{job_id}", json={"title": "Hacked title"}, headers=cand)
    assert res.status_code == 403


def test_other_employer_cannot_close(client):
    emp1 = make_user(client, "emp1@example.com", "employer")
    emp2 = make_user(client, "emp2@example.com", "employer")
    job_id = post_job(client, emp1).json()["id"]
    assert client.delete(f"/jobs/{job_id}", headers=emp2).status_code == 403


def test_close_hides_job_from_candidates_but_not_owner(client):
    emp = make_user(client, "emp@example.com", "employer")
    cand = make_user(client, "cand@example.com", "candidate")
    job_id = post_job(client, emp).json()["id"]

    res = client.delete(f"/jobs/{job_id}", headers=emp)
    assert res.status_code == 200
    assert res.json()["is_active"] is False

    assert client.get("/jobs", headers=cand).json() == []
    assert client.get(f"/jobs/{job_id}", headers=cand).status_code == 404
    assert client.get(f"/jobs/{job_id}", headers=emp).status_code == 200
    assert len(client.get("/jobs/mine", headers=emp).json()) == 1