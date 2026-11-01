import pytest
from sqlalchemy import select

from app.config import settings
from app.main import app as fastapi_app
from app.models.interview_plan import InterviewPlan
from app.routers.plan import get_plan_generator
from app.schemas.plan import InterviewPlanData
from app.services.plan_generator import PlanGenerationFailed

PASSWORD = "abc@12345"
JOB = {
    "title": "Python Developer",
    "description": "Build APIs with FastAPI and Postgres",
    "location": "Remote",
    "employment_type": "full_time",
}
PDF = ("resume.pdf", b"%PDF-1.4 fake pdf content", "application/pdf")

QUESTIONS = [
    {"category": c, "question": f"Question number {i} for the candidate", "why": "test source"}
    for i, c in enumerate(["resume_verification"] * 3 + ["technical_depth"] * 3 + ["behavioral"] * 3)
]


class FakeGenerator:
    def __init__(self, fail_times=0):
        self.calls = []
        self.fail_times = fail_times

    def generate(self, resume_text, job_title, job_description):
        self.calls.append((resume_text, job_title, job_description))
        if len(self.calls) <= self.fail_times:
            raise PlanGenerationFailed("boom")
        return InterviewPlanData(questions=QUESTIONS)


@pytest.fixture()
def fake(client):
    generator = FakeGenerator()
    fastapi_app.dependency_overrides[get_plan_generator] = lambda: generator
    return generator


def make_user(client, email, role):
    client.post("/auth/register", json={"email": email, "password": PASSWORD, "role": role})
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def make_application(client):
    emp = make_user(client, "emp@example.com", "employer")
    cand = make_user(client, "cand@example.com", "candidate")
    job_id = client.post("/jobs", json=JOB, headers=emp).json()["id"]
    return client.post(
        f"/jobs/{job_id}/apply", files={"resume": PDF}, headers=cand
    ).json()["id"]


def internal(key=None):
    return {"X-Internal-Key": key or settings.internal_api_key}


def get_plan(client, application_id, headers=None):
    return client.post(
        f"/internal/applications/{application_id}/plan",
        headers=headers or internal(),
    )


def test_first_call_creates_and_stores_plan(client, db, fake):
    app_id = make_application(client)
    res = get_plan(client, app_id)

    assert res.status_code == 200
    body = res.json()
    assert body["application_id"] == app_id
    assert len(body["questions"]) == 9
    assert len(fake.calls) == 1
    assert len(db.scalars(select(InterviewPlan)).all()) == 1


def test_second_call_returns_same_plan_without_regenerating(client, db, fake):
    app_id = make_application(client)
    first = get_plan(client, app_id).json()
    second = get_plan(client, app_id).json()

    assert first == second
    assert len(fake.calls) == 1
    assert len(db.scalars(select(InterviewPlan)).all()) == 1


def test_generator_receives_job_details(client, fake):
    app_id = make_application(client)
    get_plan(client, app_id)

    _, job_title, job_description = fake.calls[0]
    assert job_title == "Python Developer"
    assert job_description == "Build APIs with FastAPI and Postgres"


def test_missing_application_404(client, fake):
    missing = "00000000-0000-0000-0000-000000000000"
    assert get_plan(client, missing).status_code == 404
    assert fake.calls == []


def test_missing_internal_key_403(client, fake):
    app_id = make_application(client)
    res = client.post(f"/internal/applications/{app_id}/plan")
    assert res.status_code == 403
    assert fake.calls == []


def test_wrong_internal_key_403(client, fake):
    app_id = make_application(client)
    assert get_plan(client, app_id, headers=internal("wrong")).status_code == 403
    assert fake.calls == []


def test_generation_failure_502_stores_nothing_then_retry_works(client, db, fake):
    fake.fail_times = 1
    app_id = make_application(client)

    assert get_plan(client, app_id).status_code == 502
    assert db.scalars(select(InterviewPlan)).all() == []

    assert get_plan(client, app_id).status_code == 200
    assert len(db.scalars(select(InterviewPlan)).all()) == 1