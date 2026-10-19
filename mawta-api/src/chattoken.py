"""Issues the short-lived token a director's browser hands to the chat service.

A compact JWS: header {"alg":"EdDSA","typ":"JWT","kid":...}, the claims below and
an Ed25519 signature. This service only signs; mawta-chat holds the public key.
"""

import base64
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

TOKEN_ISSUER = "mawta-server"  # pinned by mawta-chat's verifier
TOKEN_AUDIENCE = "mawta-chat"


class Issuer:
    def __init__(self, seed_b64: str, key_id: str, ttl_seconds: float) -> None:
        try:
            seed = base64.b64decode(seed_b64.strip(), validate=True)
        except ValueError as exc:
            raise ValueError("chattoken: the signing key is not valid base64") from exc
        if len(seed) != 32:
            raise ValueError(f"chattoken: the signing key must be 32 bytes, got {len(seed)}")
        if not key_id.strip():
            raise ValueError("chattoken: a key id is required")
        if ttl_seconds <= 0:
            raise ValueError("chattoken: the token lifetime must be positive")
        self._key = Ed25519PrivateKey.from_private_bytes(seed)
        self._key_id = key_id.strip()
        self._ttl = timedelta(seconds=ttl_seconds)

    def public_key(self) -> bytes:
        return self._key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

    def issue(
        self, user_id: uuid.UUID, tenant_id: uuid.UUID, role: str, now: datetime | None = None
    ) -> tuple[str, datetime]:
        now = now or datetime.now(UTC)
        expires = (now + self._ttl).replace(microsecond=0)
        claims = {
            "iss": TOKEN_ISSUER,
            "aud": TOKEN_AUDIENCE,
            "sub": str(user_id),
            "tenant_id": str(tenant_id),
            "role": role,
            "iat": int(now.timestamp()),
            "exp": int(expires.timestamp()),
            "jti": str(uuid.uuid4()),
        }
        token = jwt.encode(claims, self._key, algorithm="EdDSA", headers={"kid": self._key_id})
        return token, expires.astimezone(UTC)


def generate_key() -> tuple[str, str]:
    """(base64 seed for mawta-api, base64 raw public key for the chat service)."""
    private = Ed25519PrivateKey.generate()
    seed = private.private_bytes_raw()
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.b64encode(seed).decode(), base64.b64encode(public).decode()
