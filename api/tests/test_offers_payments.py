import json
from datetime import date, timedelta

import pytest

from app.core import fake_payments
from app.main import app as fastapi_app
from app.models.application import ApplicationStatus as S
from app.models.payments import Payment
from app.models.user import UserRole
from app.routers.fake_provider import get_webhook_sender
from tests.test_scoring_flow import login_as, make_application, make_job, make_user


@pytest.fixture()
def w(client, db):
    employer = make_user(db, UserRole.employer)
    candidate = make_user(db, UserRole.candidate)
    job = make_job(db, employer)
    app = make_application(db, job, candidate)
    app.status = S.scored
    db.flush()
    login_as(employer)
    client.post(f"/employer/applications/{app.id}/shortlist")
    start = (date.today() + timedelta(days=14)).isoformat()
    offer = client.post(f"/employer/applications/{app.id}/offer", json={
        "role_title": "Backend Engineer", "rate_amount": 150000,
        "rate_period": "month", "start_date": start,
    }).json()
    return type("W", (), dict(employer=employer, candidate=candidate, job=job, app=app, offer=offer))


def fund(client, w, key="key-00000001"):
    login_as(w.employer)
    return client.post(f"/employer/applications/{w.app.id}/offer/fund", headers={"Idempotency-Key": key})


def payment(client, w):
    login_as(w.employer)
    return client.get(f"/employer/applications/{w.app.id}/offer/payment").json()


def webhook(client, intent_id, kind="payment_intent.succeeded", signature=None):
    body = json.dumps({"id": "evt_test", "type": kind, "data": {"intent_id": intent_id}}).encode()
    return client.post("/webhooks/payments", content=body, headers={
        fake_payments.SIGNATURE_HEADER: signature or fake_payments.sign(body),
        "Content-Type": "application/json",
    })


def respond(client, w, action):
    login_as(w.candidate)
    return client.post(f"/candidate/offers/{w.offer['id']}/{action}")


def test_candidate_sees_offer_and_is_notified(client, w, published):
    login_as(w.candidate)
    offers = client.get("/candidate/offers").json()
    assert len(offers) == 1 and offers[0]["job_title"] == "Backend Engineer"
    assert offers[0]["funded"] is False and offers[0]["application_status"] == "offered"
    kinds = [n["kind"] for n in client.get("/notifications").json()]
    assert "offer" in kinds and "shortlisted" in kinds
    assert any(uid == str(w.candidate.id) and e["kind"] == "offer" for uid, e in published)


def test_accept_before_funding_is_conflict(client, w):
    res = respond(client, w, "accept")
    assert res.status_code == 409 and "funded" in res.json()["detail"]


def test_same_payment_request_twice_creates_one_payment(client, db, w):
    a = fund(client, w).json()
    b = fund(client, w).json()
    c = fund(client, w, key="key-00000002").json()  # new key, same offer: still no second charge
    assert a["id"] == b["id"] == c["id"]
    assert a["checkout_url"] == f"/pay/{a['provider_intent_id']}"
    assert db.query(Payment).filter_by(offer_id=a["offer_id"]).count() == 1


def test_full_flow_webhook_then_accept(client, db, w, published):
    p = fund(client, w).json()
    assert p["status"] == "pending"
    assert webhook(client, p["provider_intent_id"]).status_code == 200
    assert webhook(client, p["provider_intent_id"]).status_code == 200  # duplicate delivery is harmless
    assert payment(client, w)["status"] == "succeeded"

    res = respond(client, w, "accept")
    assert res.status_code == 200 and res.json()["status"] == "accepted"
    db.refresh(w.app)
    assert w.app.status == S.accepted
    assert payment(client, w)["status"] == "released"
    assert any(uid == str(w.employer.id) and e["kind"] == "offer_accepted" for uid, e in published)
    assert respond(client, w, "accept").status_code == 409


def test_bad_signature_is_rejected(client, w):
    p = fund(client, w).json()
    assert webhook(client, p["provider_intent_id"], signature="nope").status_code == 400
    assert payment(client, w)["status"] == "pending"


def test_decline_refunds(client, db, w):
    p = fund(client, w).json()
    webhook(client, p["provider_intent_id"])
    res = respond(client, w, "decline")
    assert res.status_code == 200 and res.json()["status"] == "declined"
    db.refresh(w.app)
    assert w.app.status == S.declined
    assert payment(client, w)["status"] == "refunded"


def test_failed_payment_can_be_retried(client, w):
    p = fund(client, w).json()
    webhook(client, p["provider_intent_id"], kind="payment_intent.payment_failed")
    assert payment(client, w)["status"] == "failed"
    q = fund(client, w, key="key-00000003").json()
    assert q["id"] == p["id"] and q["status"] == "pending"
    assert q["provider_intent_id"] != p["provider_intent_id"]


def test_confirm_sends_signed_webhook(client):
    sent = []
    fastapi_app.dependency_overrides[get_webhook_sender] = lambda: sent.append
    assert client.post("/fake-provider/intents/pi_fake_x/confirm").status_code == 202
    event = json.loads(sent[0])
    assert event["type"] == "payment_intent.succeeded" and event["data"]["intent_id"] == "pi_fake_x"


def test_missing_idempotency_key_is_422(client, w):
    login_as(w.employer)
    assert client.post(f"/employer/applications/{w.app.id}/offer/fund").status_code == 422


def test_other_users_get_404(client, db, w):
    login_as(make_user(db, UserRole.candidate))
    assert client.post(f"/candidate/offers/{w.offer['id']}/accept").status_code == 404
    assert client.post(f"/candidate/offers/{w.offer['id']}/decline").status_code == 404
    login_as(make_user(db, UserRole.employer))
    url = f"/employer/applications/{w.app.id}/offer"
    assert client.post(f"{url}/fund", headers={"Idempotency-Key": "key-00000009"}).status_code == 404
    assert client.get(f"{url}/payment").status_code == 404