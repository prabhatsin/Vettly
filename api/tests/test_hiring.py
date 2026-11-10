from datetime import date, datetime, timedelta, timezone

import pytest

from app.models.application import ApplicationStatus as S
from app.models.offer import Offer
from app.models.user import UserRole
from tests.test_scoring_flow import login_as, make_application, make_job, make_user


@pytest.fixture()
def w(db):
    employer = make_user(db, UserRole.employer)
    job = make_job(db, employer)
    app = make_application(db, job, make_user(db, UserRole.candidate))
    app.status = S.scored
    db.flush()
    login_as(employer)
    return type("W", (), dict(employer=employer, job=job, app=app))


def offer_body(**over):
    body = {"role_title": "Backend Engineer", "rate_amount": 150000, "rate_period": "month",
            "start_date": (date.today() + timedelta(days=14)).isoformat()}
    return {**body, **over}


def url(w, action):
    return f"/employer/applications/{w.app.id}/{action}"


def test_shortlist_then_offer(client, w):
    assert client.post(url(w, "shortlist")).json()["status"] == "shortlisted"
    res = client.post(url(w, "offer"), json=offer_body())
    assert res.status_code == 201
    offer = res.json()
    assert offer["status"] == "pending"
    expires = datetime.fromisoformat(offer["expires_at"])
    assert timedelta(days=6, hours=23) < expires - datetime.now(timezone.utc) <= timedelta(days=7)
    assert client.get(url(w, "offer")).json()["id"] == offer["id"]


def test_offer_requires_shortlist(client, w):
    res = client.post(url(w, "offer"), json=offer_body())
    assert res.status_code == 409 and "scored to offered" in res.json()["detail"]


def test_offer_twice_is_conflict(client, w):
    client.post(url(w, "shortlist"))
    assert client.post(url(w, "offer"), json=offer_body()).status_code == 201
    assert client.post(url(w, "offer"), json=offer_body()).status_code == 409


def test_shortlist_before_scoring_is_conflict(client, db, w):
    w.app.status = S.applied
    db.flush()
    assert client.post(url(w, "shortlist")).status_code == 409


def test_rejected_cannot_be_offered(client, w):
    client.post(url(w, "shortlist"))
    assert client.post(url(w, "reject"), json={"note": "not a fit"}).json()["status"] == "rejected"
    assert client.post(url(w, "offer"), json=offer_body()).status_code == 409


def test_offer_validation(client, w):
    client.post(url(w, "shortlist"))
    past = (date.today() - timedelta(days=1)).isoformat()
    assert client.post(url(w, "offer"), json=offer_body(start_date=past)).status_code == 422
    assert client.post(url(w, "offer"), json=offer_body(rate_amount=0)).status_code == 422
    assert client.post(url(w, "offer"), json=offer_body(expires_in_days=90)).status_code == 422


def test_expired_offer_declines_application(client, db, w):
    client.post(url(w, "shortlist"))
    client.post(url(w, "offer"), json=offer_body())
    offer = db.query(Offer).filter_by(application_id=w.app.id).one()
    offer.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.flush()

    assert client.get(url(w, "offer")).json()["status"] == "expired"
    db.refresh(w.app)
    assert w.app.status == S.declined
    last = client.get(url(w, "history")).json()[-1]
    assert last["to_status"] == "declined" and last["actor_role"] == "system"


def test_other_employer_gets_404(client, db, w):
    login_as(make_user(db, UserRole.employer))
    assert client.post(url(w, "shortlist")).status_code == 404
    assert client.post(url(w, "reject")).status_code == 404
    assert client.post(url(w, "offer"), json=offer_body()).status_code == 404
    assert client.get(url(w, "offer")).status_code == 404