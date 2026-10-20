"""The chat token rules of chat-director D002. No database needed."""

import base64
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from auth import InvalidToken, TokenVerifier
from conftest import TENANT_A, USER_QUISPE


@pytest.fixture
def verifier(public_keys) -> TokenVerifier:
    return TokenVerifier(public_keys)


def test_a_directors_token_is_accepted(verifier, make_token):
    principal = verifier.verify(make_token(USER_QUISPE, TENANT_A))
    assert principal.user_id == USER_QUISPE
    assert principal.tenant_id == TENANT_A
    assert principal.role == "director"


def unsigned(claims: dict) -> str:
    def part(obj: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    return f"{part({'alg': 'none', 'typ': 'JWT', 'kid': 'k-test'})}.{part(claims)}."


@pytest.mark.parametrize(
    "case",
    [
        "expired",
        "other key",
        "unknown kid",
        "other audience",
        "other issuer",
        "teacher",
        "no tenant",
    ],
)
def test_bad_tokens_are_rejected(verifier, make_token, case):
    token = {
        "expired": lambda: make_token(USER_QUISPE, TENANT_A, ttl=-120),
        "other key": lambda: make_token(USER_QUISPE, TENANT_A, key=Ed25519PrivateKey.generate()),
        "unknown kid": lambda: make_token(USER_QUISPE, TENANT_A, kid="k-gone"),
        "other audience": lambda: make_token(USER_QUISPE, TENANT_A, aud="someone-else"),
        "other issuer": lambda: make_token(USER_QUISPE, TENANT_A, iss="someone-else"),
        "teacher": lambda: make_token(USER_QUISPE, TENANT_A, role="teacher"),
        "no tenant": lambda: make_token(USER_QUISPE, TENANT_A, tenant_id="not-a-uuid"),
    }[case]()
    with pytest.raises(InvalidToken):
        verifier.verify(token)


def test_an_unsigned_token_is_rejected(verifier):
    token = unsigned(
        {
            "iss": "mawta-server",
            "aud": "mawta-chat",
            "sub": str(USER_QUISPE),
            "tenant_id": str(TENANT_A),
            "role": "director",
            "iat": 1,
            "exp": 9999999999,
            "jti": "x",
        }
    )
    with pytest.raises(InvalidToken):
        verifier.verify(token)


def test_a_bad_public_key_stops_startup():
    with pytest.raises(ValueError):
        TokenVerifier({"k1": base64.b64encode(b"short").decode()})
    with pytest.raises(ValueError):
        TokenVerifier({})
