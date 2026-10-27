from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.auth import LoginRequest, RegisterRequest


class EmailAlreadyRegistered(Exception):
    pass


class InvalidCredentials(Exception):
    pass


class AuthService:
    def __init__(self, db: Session):
        self.users = UserRepository(db)

    def register(self, data: RegisterRequest) -> User:
        email = data.email.lower()
        if self.users.get_by_email(email):
            raise EmailAlreadyRegistered()
        return self.users.create(
            email=email,
            hashed_password=hash_password(data.password),
            role=data.role,
        )

    def login(self, data: LoginRequest) -> str:
        user = self.users.get_by_email(data.email.lower())
        if user is None or not verify_password(data.password, user.hashed_password):
            raise InvalidCredentials()
        return create_access_token(str(user.id), user.role.value)