from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash

from app.config import settings

password_hash = PasswordHash.recommended()
#A hasher configured with Argon2 and sensible defaults. It adds a random salt automatically, so the same password hashes differently each time.

def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    """
    verify_password: checks a typed password against a stored hash. You can’t “un-hash”, so this 
    re-hashes the input with the same salt and compares.
    """
    return password_hash.verify(password, hashed)


def create_access_token(user_id: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_minutes)
    payload = {"sub": user_id, "role": role, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])

#! Good to know
'''

A JWT is signed, not encrypted. Anyone can read the payload, so never put secrets in it.
We keep the role in the token for convenience, but the database stays the source of truth. 
get_current_user (later) will load the user from the DB.

'''