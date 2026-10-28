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


#! What exactly this services folder do ?? 

'''
The service is the business-rules layer for jobs. It sits between the routes and the repository and 
decides what is allowed, while the repository only knows how to read and write rows.

route (HTTP) -> JobService (rules) -> JobRepository (queries) -> Postgres
'''

#! Why not put this in the route or the repository?

'''

=>Repository: it should stay dumb. If it checked ownership, it would mix business rules with queries.
=>Route: it should only translate HTTP to Python and back. If rules lived there, they would be hard to 
test and would get copied into every new route.

'''
