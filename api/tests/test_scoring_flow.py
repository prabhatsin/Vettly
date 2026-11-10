import asyncio
import itertools
import uuid

import pytest

from app.api.deps import get_current_user
from app.main import app as fastapi_app
from app.models.application import Application
from app.models.job import EmploymentType, Job
from app.models.report import InterviewReport
from app.models.transcript import TranscriptEntry
from app.models.user import User, UserRole
from app.repositories.scoring import ReportRepository, RubricRepository
from app.routers.employer import get_scoring_enqueue
from app.schemas.scoring import Criterion, Evidence, ScorerOutput
from app.services.scoring import DEFAULT_RUBRIC, merge_turns
from app.services.scoring_queue import ScoringQueue
from app.services.scoring_runner import ScoringJob
from app.config import settings

_n = itertools.count()


def make_user(db, role):
    user = User(email=f"user{next(_n)}@example.com", hashed_password="x", role=role)
    db.add(user)
    db.flush()
    return user


def make_job(db, employer):
    job = Job(
        employer_id=employer.id, title="Backend Engineer", description="APIs",
        employment_type=EmploymentType.full_time,
    )
    db.add(job)
    db.flush()
    return job


def make_application(db, job, candidate, resume="Built CloudGuard at WESEE"):
    app = Application(
        job_id=job.id, candidate_id=candidate.id, resume_path="r.pdf", resume_text=resume
    )
    db.add(app)
    db.flush()
    return app


def add_transcript(db, application, pairs):
    db.add_all(
        TranscriptEntry(application_id=application.id, seq=i, role=r, text=t)
        for i, (r, t) in enumerate(pairs)
    )
    db.flush()


def login_as(user):
    fastapi_app.dependency_overrides[get_current_user] = lambda: user


def save_report(db, application, score, recommendation="maybe", evidence=None):
    ev = evidence or [Evidence(turn=1, quote="I used the watchdog library")]
    report = {
        "overall_score": score, "recommendation": recommendation, "advice_note": "advice",
        "coverage": 1.0, "strengths": [], "concerns": [],
        "criteria": [{
            "key": "technical_depth", "name": "Technical depth", "weight": 1.0,
            "status": "ok", "score": 4, "reason": "Clear.",
            "evidence": [e.model_dump() for e in ev],
        }],
    }
    ReportRepository(db).save(
        application.id, status="done", overall_score=score,
        recommendation=recommendation, report=report,
    )


PAIRS = [
    ("interviewer", "How did you build the folder monitor?"),
    ("candidate", "I used the watchdog library"),
    ("candidate", "and an event driven design with a timer for deletion."),
    ("interviewer", "How do you avoid blocking the loop?"),
    ("candidate", "I move CPU heavy work to a thread pool executor " + "word " * 30),
]


@pytest.fixture()
def world(db):
    employer = make_user(db, UserRole.employer)
    other = make_user(db, UserRole.employer)
    candidate = make_user(db, UserRole.candidate)
    job = make_job(db, employer)
    application = make_application(db, job, candidate)
    return type("W", (), dict(employer=employer, other=other, candidate=candidate,
                              job=job, application=application))


# ---------- ownership: an employer sees only their own jobs ----------

def test_other_employer_gets_404_everywhere(client, db, world):
    save_report(db, world.application, 4.0)
    login_as(world.other)
    j, a = world.job.id, world.application.id
    fastapi_app.dependency_overrides[get_scoring_enqueue] = lambda: (lambda _id: None)
    assert client.get(f"/employer/jobs/{j}/candidates").status_code == 404
    assert client.get(f"/employer/jobs/{j}/rubric").status_code == 404
    body = {"criteria": [c.model_dump(mode="json") for c in DEFAULT_RUBRIC]}
    assert client.put(f"/employer/jobs/{j}/rubric", json=body).status_code == 404
    assert client.get(f"/employer/applications/{a}/report").status_code == 404
    assert client.get(f"/employer/applications/{a}/replay").status_code == 404
    assert client.post(f"/employer/applications/{a}/rescore").status_code == 404


def test_owner_can_read(client, db, world):
    save_report(db, world.application, 4.0)
    login_as(world.employer)
    assert client.get(f"/employer/jobs/{world.job.id}/candidates").status_code == 200
    assert client.get(f"/employer/applications/{world.application.id}/report").status_code == 200


def test_candidate_role_is_forbidden(client, world):
    login_as(world.candidate)
    assert client.get(f"/employer/jobs/{world.job.id}/candidates").status_code == 403


def test_unknown_ids_are_404(client, world):
    login_as(world.employer)
    assert client.get(f"/employer/jobs/{uuid.uuid4()}/candidates").status_code == 404
    assert client.get(f"/employer/applications/{uuid.uuid4()}/report").status_code == 404


# ---------- ranking and report ----------

def test_candidates_ranked_best_first_unscored_last(client, db, world):
    best = make_application(db, world.job, make_user(db, UserRole.candidate))
    mid = make_application(db, world.job, make_user(db, UserRole.candidate))
    save_report(db, best, 4.6, "hire")
    save_report(db, mid, 3.1, "maybe")
    save_report(db, world.application, 1.9, "no_hire")
    unscored = make_application(db, world.job, make_user(db, UserRole.candidate))
    login_as(world.employer)

    rows = client.get(f"/employer/jobs/{world.job.id}/candidates").json()
    assert [r["application_id"] for r in rows] == [
        str(best.id), str(mid.id), str(world.application.id), str(unscored.id)
    ]
    assert rows[0]["recommendation"] == "hire" and rows[-1]["report_status"] is None


def test_report_endpoint_returns_stored_report(client, db, world):
    save_report(db, world.application, 4.0, "hire")
    login_as(world.employer)
    data = client.get(f"/employer/applications/{world.application.id}/report").json()
    assert data["status"] == "done" and data["report"]["overall_score"] == 4.0
    assert data["report"]["criteria"][0]["evidence"][0]["turn"] == 1


def test_report_404_before_scoring(client, world):
    login_as(world.employer)
    assert client.get(f"/employer/applications/{world.application.id}/report").status_code == 404


# ---------- replay ----------

def test_replay_merges_fragments_and_lists_evidence(client, db, world):
    add_transcript(db, world.application, PAIRS)
    save_report(db, world.application, 4.0)
    login_as(world.employer)
    data = client.get(f"/employer/applications/{world.application.id}/replay").json()
    assert [t["role"] for t in data["turns"]] == [
        "interviewer", "candidate", "interviewer", "candidate"
    ]
    assert data["turns"][1]["seqs"] == [1, 2]
    assert "event driven design" in data["turns"][1]["text"]
    assert data["evidence"][0]["turn"] == 1


# ---------- rubric ----------

def test_rubric_default_then_custom(client, world):
    login_as(world.employer)
    url = f"/employer/jobs/{world.job.id}/rubric"
    first = client.get(url).json()
    assert first["is_default"] is True and len(first["criteria"]) == len(DEFAULT_RUBRIC)

    one = DEFAULT_RUBRIC[0].model_dump(mode="json")
    assert client.put(url, json={"criteria": [one]}).status_code == 200
    second = client.get(url).json()
    assert second["is_default"] is False and len(second["criteria"]) == 1
    assert second["criteria"][0]["levels"]["5"]


def test_rubric_validation(client, world):
    login_as(world.employer)
    url = f"/employer/jobs/{world.job.id}/rubric"
    one = DEFAULT_RUBRIC[0].model_dump(mode="json")
    assert client.put(url, json={"criteria": []}).status_code == 422
    assert client.put(url, json={"criteria": [one, one]}).status_code == 422
    bad = {**one, "levels": {"1": "only one level"}}
    assert client.put(url, json={"criteria": [bad]}).status_code == 422


# ---------- trigger: the interview ending queues scoring ----------

def test_transcript_save_queues_scoring_only_when_ended(client, world):
    queued = []
    fastapi_app.dependency_overrides[get_scoring_enqueue] = lambda: queued.append
    url = f"/internal/applications/{world.application.id}/transcript"
    headers = {"X-Internal-Key": settings.internal_api_key}
    entries = [{"role": "candidate", "text": "hello there"}]

    assert client.post(url, json={"entries": entries}, headers=headers).status_code == 201
    assert queued == []
    assert client.post(url, json={"entries": entries, "ended": True}, headers=headers).status_code == 201
    assert queued == [str(world.application.id)]


def test_queue_failure_does_not_lose_the_transcript(client, db, world):
    def broken(_id):
        raise RuntimeError("redis down")

    fastapi_app.dependency_overrides[get_scoring_enqueue] = lambda: broken
    url = f"/internal/applications/{world.application.id}/transcript"
    res = client.post(
        url, headers={"X-Internal-Key": settings.internal_api_key},
        json={"entries": [{"role": "candidate", "text": "hello there"}], "ended": True},
    )
    assert res.status_code == 201 and res.json()["saved"] == 1


def test_rescore_endpoint_queues_job(client, world):
    queued = []
    fastapi_app.dependency_overrides[get_scoring_enqueue] = lambda: queued.append
    login_as(world.employer)
    res = client.post(f"/employer/applications/{world.application.id}/rescore")
    assert res.status_code == 202 and queued == [str(world.application.id)]


# ---------- the scoring job ----------

def good_generate(quote="I used the watchdog library and an event driven design"):
    seen = []

    async def generate(prompt):
        seen.append(prompt)
        return ScorerOutput(
            score=4, reason="Clear explanation with a concrete mechanism.",
            evidence=[Evidence(turn=1, quote=quote)],
        )

    generate.seen = seen
    return generate


def test_job_scores_and_stores_report(db, world):
    add_transcript(db, world.application, PAIRS)
    gen = good_generate()  # quote spans two STT fragments, so it needs the merge
    asyncio.run(ScoringJob(db, gen).run(world.application.id))

    row = ReportRepository(db).get_by_application(world.application.id)
    assert row.status == "done" and row.overall_score == 4.0
    assert row.recommendation == "hire"
    assert len(row.report["criteria"]) == len(DEFAULT_RUBRIC)
    assert all(c["status"] == "ok" for c in row.report["criteria"])
    assert "Built CloudGuard" in gen.seen[0] and "Backend Engineer" in gen.seen[0]


def test_job_rerun_replaces_the_single_report(db, world):
    add_transcript(db, world.application, PAIRS)
    asyncio.run(ScoringJob(db, good_generate()).run(world.application.id))
    asyncio.run(ScoringJob(db, good_generate()).run(world.application.id))
    count = db.query(InterviewReport).filter_by(application_id=world.application.id).count()
    assert count == 1


def test_job_uses_the_jobs_custom_rubric(db, world):
    add_transcript(db, world.application, PAIRS)
    one = Criterion.model_validate(DEFAULT_RUBRIC[2].model_dump(mode="json"))
    RubricRepository(db).upsert(world.job.id, [one.model_dump(mode="json")])
    asyncio.run(ScoringJob(db, good_generate()).run(world.application.id))
    row = ReportRepository(db).get_by_application(world.application.id)
    assert [c["key"] for c in row.report["criteria"]] == [one.key]
    assert [c["key"] for c in row.rubric] == [one.key]


def test_job_fabricated_quotes_end_unverified_not_scored(db, world):
    add_transcript(db, world.application, PAIRS)
    gen = good_generate(quote="I rewrote the Linux kernel scheduler myself")
    asyncio.run(ScoringJob(db, gen).run(world.application.id))
    row = ReportRepository(db).get_by_application(world.application.id)
    assert row.status == "done" and row.overall_score is None
    assert row.recommendation == "insufficient_data"
    assert all(c["status"] == "unverified" for c in row.report["criteria"])


def test_job_with_empty_transcript_is_insufficient_data(db, world):
    gen = good_generate()
    asyncio.run(ScoringJob(db, gen).run(world.application.id))
    row = ReportRepository(db).get_by_application(world.application.id)
    assert row.recommendation == "insufficient_data" and gen.seen == []


def test_job_for_missing_application_does_nothing(db):
    asyncio.run(ScoringJob(db, good_generate()).run(uuid.uuid4()))


# ---------- merge_turns ----------

def test_merge_turns_joins_same_speaker_and_skips_blank():
    turns = merge_turns([
        {"seq": 0, "role": "interviewer", "text": "Q one?"},
        {"seq": 1, "role": "candidate", "text": "part a"},
        {"seq": 2, "role": "candidate", "text": "  "},
        {"seq": 3, "role": "candidate", "text": "part b"},
    ])
    assert [t["role"] for t in turns] == ["interviewer", "candidate"]
    assert turns[1]["text"] == "part a part b" and turns[1]["seqs"] == [1, 3]


# ---------- the Redis queue ----------

@pytest.fixture()
def queue():
    import fakeredis
    return ScoringQueue(fakeredis.FakeRedis(decode_responses=True))


def test_queue_is_fifo_and_deduplicated(queue):
    assert queue.enqueue("a") is True
    assert queue.enqueue("a") is False
    queue.enqueue("b")
    assert queue.reserve(timeout=1) == "a"
    assert queue.reserve(timeout=1) == "b"
    assert queue.reserve(timeout=1) is None


def test_ack_clears_processing_and_allows_requeue(queue):
    queue.enqueue("a")
    queue.reserve(timeout=1)
    queue.ack("a")
    assert queue.r.llen("scoring:processing") == 0
    assert queue.enqueue("a") is True


def test_unfinished_jobs_return_to_the_queue_after_a_crash(queue):
    queue.enqueue("a")
    queue.enqueue("b")
    queue.reserve(timeout=1)  # worker takes "a", then dies without ack
    assert queue.requeue_stale() == 1
    assert queue.reserve(timeout=1) == "a"
