import pytest

from app.main import app as fastapi_app
from app.models.user import UserRole
from app.routers.employer import get_embedder
from app.services.matching import has_term
from tests.test_scoring_flow import login_as, make_application, make_job, make_user, save_report


@pytest.fixture()
def embed_calls():
    calls = []

    def embed(text):
        calls.append(text)
        t = text.lower()
        return [float("python" in t), float("fastapi" in t), 0.1]

    fastapi_app.dependency_overrides[get_embedder] = lambda: embed
    return calls


@pytest.fixture()
def setup(db):
    employer = make_user(db, UserRole.employer)
    job = make_job(db, employer)
    job.description = "Python and FastAPI backend APIs"
    db.flush()
    return employer, job


def cand(db, job, resume, score=None, rec="maybe"):
    app = make_application(db, job, make_user(db, UserRole.candidate), resume=resume)
    if score is not None:
        save_report(db, app, score, rec)
    return app


def test_ranked_by_interview_and_similarity(client, db, setup, embed_calls):
    employer, job = setup
    a = cand(db, job, "Python FastAPI Postgres", 4.5, "hire")
    b = cand(db, job, "Java Spring", 4.5, "hire")
    c = cand(db, job, "Python FastAPI", 2.0, "no_hire")
    d = cand(db, job, "Python FastAPI")  # not scored
    login_as(employer)

    rows = client.post(f"/employer/jobs/{job.id}/matches/recompute").json()
    assert [r["application_id"] for r in rows] == [str(a.id), str(c.id), str(b.id), str(d.id)]
    assert "Interview 4.5/5 (hire)" in rows[0]["reasons"]
    assert "Interview not scored yet" in rows[-1]["reasons"]
    assert client.get(f"/employer/jobs/{job.id}/matches").json() == rows


def test_missing_must_have_ranks_below(client, db, setup, embed_calls):
    employer, job = setup
    strong = cand(db, job, "Python FastAPI", 4.8, "hire")
    weak = cand(db, job, "Python FastAPI Kubernetes", 2.0, "no_hire")
    login_as(employer)
    client.put(f"/employer/jobs/{job.id}/must-haves", json={"must_haves": ["kubernetes"]})

    rows = client.post(f"/employer/jobs/{job.id}/matches/recompute").json()
    assert [r["application_id"] for r in rows] == [str(weak.id), str(strong.id)]
    assert rows[1]["passed_filters"] is False
    assert "Missing must-have: kubernetes" in rows[1]["reasons"]


def test_resume_embedding_is_cached(client, db, setup, embed_calls):
    employer, job = setup
    cand(db, job, "Python FastAPI", 4.0)
    cand(db, job, "Java", 3.0)
    login_as(employer)
    client.post(f"/employer/jobs/{job.id}/matches/recompute")
    assert len(embed_calls) == 3  # job + 2 résumés
    client.post(f"/employer/jobs/{job.id}/matches/recompute")
    assert len(embed_calls) == 4  # job only


def test_must_haves_are_cleaned(client, setup):
    employer, job = setup
    login_as(employer)
    res = client.put(f"/employer/jobs/{job.id}/must-haves", json={"must_haves": [" Python", "python", ""]})
    assert res.json() == {"must_haves": ["Python"]}


def test_other_employer_gets_404(client, db, setup, embed_calls):
    _, job = setup
    login_as(make_user(db, UserRole.employer))
    assert client.get(f"/employer/jobs/{job.id}/matches").status_code == 404
    assert client.post(f"/employer/jobs/{job.id}/matches/recompute").status_code == 404
    assert client.put(f"/employer/jobs/{job.id}/must-haves", json={"must_haves": []}).status_code == 404


def test_has_term_is_whole_word():
    assert has_term("Go developer", "go")
    assert not has_term("good at things", "go")
    assert has_term("C++ and Rust", "C++")