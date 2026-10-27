from app.models.user import UserRole
from app.repositories.user import UserRepository


def test_create_and_get_by_email(db):
    repo = UserRepository(db)

    created = repo.create("a@example.com", "hashed-pw", UserRole.candidate)
    found = repo.get_by_email("a@example.com")

    assert found is not None
    assert found.id == created.id
    assert found.role == UserRole.candidate


def test_get_by_email_missing_returns_none(db):
    assert UserRepository(db).get_by_email("nobody@example.com") is None