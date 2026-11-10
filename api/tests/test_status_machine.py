import asyncio

import pytest

from app.config import settings
from app.models.application import ApplicationStatus as S
from app.models.status_event import ApplicationStatusEvent
from app.models.user import UserRole
from app.services.scoring_runner import ScoringJob
from app.services.status_machine import ApplicationStatusService, InvalidTransition
from tests.test_scoring_flow import (
    PAIRS, add_transcript, good_generate, login_as, make_application, make_job, make_user,
)


@pytest.fixture()
def w(db):
    employer = make_user(db, UserRole.employer)
    candidate = make_user(db, UserRole.candidate)
    job = make_job(db, employer)
    app = make_application(db, job, candidate)
    return type("W", (), dict(employer=employer, candidate=candidate, job=job, app=app))


def events(db, app):
    return (db.query(ApplicationStatusEvent).filter_by(application_id=app.id)
            .order_by(ApplicationStatusEvent.created_at).all())


def test_full_path_is_logged(db, w):
    svc = ApplicationStatusService(db)
    assert svc.system_advance(w.app.id, S.interviewed)
    assert svc.system_advance(w.app.id, S.scored)
    svc.move(w.app, S.shortlisted, w.employer)
    svc.move(w.app, S.offered, w.employer)
    svc.move(w.app, S.accepted, w.candidate)
    log = events(db, w.app)
    assert [e.to_status for e in log] == ["interviewed", "scored", "shortlisted", "offered", "accepted"]
    assert [e.actor_role for e in log] == ["system", "system", "employer", "employer", "candidate"]
    assert log[-1].actor_id == w.candidate.id


@pytest.mark.parametrize("start, target, role", [
    (S.applied, S.accepted, "candidate"),     # skip ahead
    (S.scored, S.offered, "employer"),        # skip shortlist
    (S.shortlisted, S.scored, "employer"),    # backwards
    (S.offered, S.accepted, "employer"),      # wrong role
    (S.scored, S.shortlisted, "candidate"),   # wrong role
    (S.accepted, S.declined, "candidate"),    # terminal
    (S.rejected, S.shortlisted, "employer"),  # terminal
])
def test_invalid_moves_are_rejected(db, w, start, target, role):
    w.app.status = start
    db.flush()
    actor = w.employer if role == "employer" else w.candidate
    with pytest.raises(InvalidTransition):
        ApplicationStatusService(db).move(w.app, target, actor)
    assert w.app.status == start and events(db, w.app) == []


def test_system_advance_is_idempotent(db, w):
    svc = ApplicationStatusService(db)
    assert svc.system_advance(w.app.id, S.interviewed) is True
    assert svc.system_advance(w.app.id, S.interviewed) is False
    assert svc.system_advance(w.app.id, S.shortlisted) is False  # system can't shortlist
    assert len(events(db, w.app)) == 1


def test_interview_end_moves_to_interviewed(client, db, w):
    url = f"/internal/applications/{w.app.id}/transcript"
    headers = {"X-Internal-Key": settings.internal_api_key}
    client.post(url, json={"entries": [{"role": "candidate", "text": "hi"}], "ended": True}, headers=headers)
    db.refresh(w.app)
    assert w.app.status == S.interviewed


def test_scoring_moves_to_scored(db, w):
    w.app.status = S.interviewed
    db.flush()
    add_transcript(db, w.app, PAIRS)
    asyncio.run(ScoringJob(db, good_generate()).run(w.app.id))
    db.refresh(w.app)
    assert w.app.status == S.scored


def test_history_is_owner_only(client, db, w):
    ApplicationStatusService(db).system_advance(w.app.id, S.interviewed)
    login_as(w.employer)
    rows = client.get(f"/employer/applications/{w.app.id}/history").json()
    assert rows[0]["from_status"] == "applied" and rows[0]["to_status"] == "interviewed"
    login_as(make_user(db, UserRole.employer))
    assert client.get(f"/employer/applications/{w.app.id}/history").status_code == 404

