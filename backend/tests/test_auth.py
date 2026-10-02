"""
Tests for token checking - the most security-critical code in the app.

We can't get real Cognito tokens in a test, so we create our own RSA key
pair, sign test tokens with the private key, and make the verifier use the
matching public key. That lets us check every rule in TokenVerifier.verify.
"""

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth import TokenVerifier
from app.config import get_settings

PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeSigningKey:
    key = PRIVATE_KEY.public_key()


@pytest.fixture
def verifier(monkeypatch):
    v = TokenVerifier(get_settings())
    # Instead of downloading Cognito's public keys, use our test public key.
    monkeypatch.setattr(v.jwks_client, "get_signing_key_from_jwt", lambda token: FakeSigningKey())
    return v


def make_token(key=PRIVATE_KEY, **overrides):
    settings = get_settings()
    claims = {
        "sub": "user-1",
        "iss": settings.cognito_issuer,
        "client_id": settings.cognito_client_id,
        "token_use": "access",
        "exp": int(time.time()) + 3600,
    }
    claims.update(overrides)
    return jwt.encode(claims, key, algorithm="RS256")


def test_valid_token_is_accepted(verifier):
    assert verifier.verify(make_token())["sub"] == "user-1"


def test_expired_token_is_rejected(verifier):
    with pytest.raises(jwt.ExpiredSignatureError):
        verifier.verify(make_token(exp=int(time.time()) - 10))


def test_token_signed_with_another_key_is_rejected(verifier):
    with pytest.raises(jwt.InvalidSignatureError):
        verifier.verify(make_token(key=OTHER_PRIVATE_KEY))


def test_token_from_another_user_pool_is_rejected(verifier):
    with pytest.raises(jwt.InvalidIssuerError):
        verifier.verify(make_token(iss="https://cognito-idp.eu-west-2.amazonaws.com/someone-else"))


def test_id_token_is_rejected(verifier):
    with pytest.raises(jwt.InvalidTokenError):
        verifier.verify(make_token(token_use="id"))


def test_token_for_another_app_is_rejected(verifier):
    with pytest.raises(jwt.InvalidTokenError):
        verifier.verify(make_token(client_id="some-other-app"))
