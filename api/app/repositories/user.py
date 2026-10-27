import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User, UserRole


class UserRepository:
    """All database access for users: get by email, get by id, create."""
    def __init__(self, db: Session):
        self.db = db

    def get_by_email(self, email: str) -> User | None:
        return self.db.scalar(select(User).where(User.email == email))

    def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return self.db.get(User, user_id)

    def create(self, email: str, hashed_password: str, role: UserRole) -> User:
        user = User(email=email, hashed_password=hashed_password, role=role)
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user



'''
UserRepository is the one place that knows how to read and write the users table. Everything else
in the app (routes, auth logic) calls these three methods instead of writing database code.

=>get_by_email: find a user by email (login will use this).
=>get_by_id: find a user by primary key (used when a JWT identifies who is calling).
=>create: insert a new user row.

# Earlier we had this create logic written in signup , now we made one scrip which does everything 
related to one table users , ... whether querry or writing something into it 

'''
#! Flow
#? :: route -> auth service (checks, hashing) -> repository.create() -> database

