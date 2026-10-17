"""Verification of the director's chat token (chat-director D002).

mawta-server signs the token with Ed25519; this service holds only the public
keys, so it can check a token but never mint one.
"""

import base64
from dataclasses import dataclass
from uuid import UUID

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

ISSUER = "mawta-server"
AUDIENCE = "mawta-chat"
LEEWAY_SECONDS = 30
REQUIRED_CLAIMS = ["iss", "aud", "sub", "tenant_id", "role", "iat", "exp", "jti"]


class InvalidToken(Exception):
    """The token is missing, malformed, expired, or not a director's."""


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    tenant_id: UUID
    role: str

    @property
    def is_director(self) -> bool:
        return self.role == "director"


class TokenVerifier:
    def __init__(self, public_keys: dict[str, str]) -> None:
        if not public_keys:
            raise ValueError("CHAT_TOKEN_PUBLIC_KEYS has no keys")
        self._keys: dict[str, Ed25519PublicKey] = {}
        for kid, encoded in public_keys.items():
            raw = base64.b64decode(encoded, validate=True)
            if len(raw) != 32:
                raise ValueError(f"public key {kid!r} must be 32 bytes, got {len(raw)}")
            self._keys[kid] = Ed25519PublicKey.from_public_bytes(raw)

    def verify(self, token: str) -> Principal:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise InvalidToken("malformed token") from exc
        # The algorithm is pinned, never taken from the token: this is what
        # rejects "none" and any HMAC confusion.
        if header.get("alg") != "EdDSA":
            raise InvalidToken("unexpected algorithm")
        key = self._keys.get(header.get("kid", ""))
        if key is None:
            raise InvalidToken("unknown key id")
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=["EdDSA"],
                audience=AUDIENCE,
                issuer=ISSUER,
                leeway=LEEWAY_SECONDS,
                options={"require": REQUIRED_CLAIMS},
            )
            principal = Principal(
                user_id=UUID(claims["sub"]),
                tenant_id=UUID(claims["tenant_id"]),
                role=claims["role"],
            )
        except (jwt.PyJWTError, ValueError) as exc:
            raise InvalidToken("invalid token") from exc
        if not principal.is_director:
            raise InvalidToken("not a director")
        return principal
