"""Password hashing and opaque session tokens: pure functions, no I/O, no SQL."""

import base64
import hashlib
import secrets

import bcrypt

MIN_PASSWORD_LEN = 10
# bcrypt silently truncates past 72 bytes, so two passwords differing only after
# byte 72 would hash identically. Refuse the input instead of truncating it.
MAX_PASSWORD_LEN = 72

_TOKEN_BYTES = 32  # 256 bits: no extra work factor needed when hashing for storage

# A valid bcrypt hash of a never-issued string. Verified against when no user
# matched the username, so a wrong username costs the same as a wrong password.
_DUMMY_HASH = "$2a$12$T48pqD1ZahClpw8nNk/DU.MUNp8TVf134friFNGqQHtmj3SubxPzm"


class PasswordMismatch(Exception):
    pass


class PasswordLengthError(Exception):
    pass


def validate_password(password: str) -> None:
    if not MIN_PASSWORD_LEN <= len(password.encode()) <= MAX_PASSWORD_LEN:
        raise PasswordLengthError("auth: password length out of range")


def hash_password(password: str, cost: int) -> str:
    validate_password(password)
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=cost)).decode()


def verify_password(hashed: str, password: str) -> None:
    """Raise PasswordMismatch on any non-match (including a malformed hash)."""
    try:
        ok = bcrypt.checkpw(password.encode()[:MAX_PASSWORD_LEN], hashed.encode())
    except ValueError:
        ok = False
    if not ok:
        raise PasswordMismatch


def dummy_hash() -> str:
    return _DUMMY_HASH


def hash_session_token(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def new_session_token() -> tuple[str, bytes]:
    """A random 43-char base64url token and its sha256. Only the hash is persisted."""
    token = base64.urlsafe_b64encode(secrets.token_bytes(_TOKEN_BYTES)).rstrip(b"=").decode()
    return token, hash_session_token(token)
