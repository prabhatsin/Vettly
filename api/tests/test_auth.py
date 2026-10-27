from app.models.user import UserRole
from app.repositories.user import UserRepository
from app.core.security import hash_password
from app.api.deps import require_role
from app.main import app

PASSWORD = "abc@12345"


def register(client, email="a@example.com", role="candidate"):
    return client.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD, "role": role},
    )


def login_token(client, email="a@example.com"):
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    return res.json()["access_token"]


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def test_register_success_hides_password(client):
    res = register(client)
    assert res.status_code == 201
    body = res.json()
    assert body["email"] == "a@example.com"
    assert body["role"] == "candidate"
    assert "hashed_password" not in body
    assert "password" not in body


def test_register_duplicate_email_409(client):
    register(client)
    assert register(client).status_code == 409


def test_register_duplicate_email_is_case_insensitive(client):
    register(client, email="a@example.com")
    assert register(client, email="A@Example.com").status_code == 409


def test_register_short_password_422(client):
    res = client.post(
        "/auth/register",
        json={"email": "a@example.com", "password": "short", "role": "candidate"},
    )
    assert res.status_code == 422


def test_register_invalid_role_422(client):
    assert register(client, role="admin").status_code == 422


def test_login_success_returns_token(client):
    register(client)
    res = client.post(
        "/auth/login", json={"email": "a@example.com", "password": PASSWORD}
    )
    assert res.status_code == 200
    assert res.json()["token_type"] == "bearer"
    assert res.json()["access_token"]


def test_login_wrong_password_401(client):
    register(client)
    res = client.post(
        "/auth/login", json={"email": "a@example.com", "password": "wrong-pass"}
    )
    assert res.status_code == 401


def test_login_unknown_email_401(client):
    res = client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}
    )
    assert res.status_code == 401


def test_me_with_token(client):
    register(client)
    token = login_token(client)
    res = client.get("/auth/me", headers=auth_header(token))
    assert res.status_code == 200
    assert res.json()["email"] == "a@example.com"


def test_me_without_token_rejected(client):
    assert client.get("/auth/me").status_code in (401, 403)


def test_me_with_garbage_token_401(client):
    res = client.get("/auth/me", headers=auth_header("not-a-real-token"))
    assert res.status_code == 401


def test_require_role_blocks_wrong_role(client):
    @app.get("/_employer-only")
    def employer_only(user=__import__("fastapi").Depends(require_role(UserRole.employer))):
        return {"ok": True}

    register(client, email="cand@example.com", role="candidate")
    register(client, email="emp@example.com", role="employer")

    cand = login_token(client, "cand@example.com")
    emp = login_token(client, "emp@example.com")

    assert client.get("/_employer-only", headers=auth_header(cand)).status_code == 403
    assert client.get("/_employer-only", headers=auth_header(emp)).status_code == 200