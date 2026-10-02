"""
auth.py - Checking who is making each request.

How login works in this app (the "big picture"):
  1. The React app sends the user to Cognito's login page. There they can
     register, log in with email + password, or click "Continue with Google".
  2. Cognito sends them back to the React app with TOKENS. One of them, the
     ACCESS TOKEN, is a JWT: a small signed document that says, roughly,
     "this is user abc-123, issued by our Cognito pool, valid until 3pm".
  3. The React app includes that token in every request to our API:
         Authorization: Bearer <access token>
  4. This file checks the token is genuine before letting the request in.

Why can we trust a token? Cognito SIGNS each token with a private key only it
has, and publishes the matching PUBLIC keys at a web address (the "JWKS" URL).
We download the public keys and check the signature. If anyone edits even one
character of a token, the signature no longer matches and we reject it.

Notice what we DON'T do: we never see or store passwords. Cognito handles all
of that, which is exactly the "don't build login yourself" advice.
"""

from datetime import UTC, datetime

import httpx
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pymongo import ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase

from app.config import Settings, get_settings
from app.db import get_db

# Reads the "Authorization: Bearer <token>" header for us.
# auto_error=False lets us return our own clear 401 message if it's missing.
bearer_scheme = HTTPBearer(auto_error=False)


class TokenVerifier:
    """Checks Cognito access tokens."""

    def __init__(self, settings: Settings):
        self.settings = settings
        # PyJWKClient downloads Cognito's public keys and caches them, so we
        # don't fetch them again on every single request.
        self.jwks_client = jwt.PyJWKClient(settings.cognito_jwks_url, cache_keys=True)

    def verify(self, token: str) -> dict:
        """
        Return the token's contents ("claims") if valid, or raise an error.
        Each check below closes a specific loophole.
        """
        # 1. Find which of Cognito's public keys signed this token.
        signing_key = self.jwks_client.get_signing_key_from_jwt(token)

        # 2. Check the signature, the expiry time, and the issuer.
        #    - algorithms=["RS256"]: only accept the algorithm Cognito uses.
        #      Accepting any algorithm is a classic security hole.
        #    - issuer: the token must come from OUR user pool, not some other
        #      Cognito pool somewhere else in the world.
        #    - expiry ("exp") is checked automatically: old tokens are rejected.
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=self.settings.cognito_issuer,
            options={"require": ["exp", "iss", "sub", "token_use"]},
        )

        # 3. Cognito issues two kinds of token: ID tokens (for the frontend to
        #    read the user's details) and ACCESS tokens (for calling APIs).
        #    APIs should only accept access tokens.
        if claims.get("token_use") != "access":
            raise jwt.InvalidTokenError("Not an access token")

        # 4. The token must be for OUR app. One user pool can serve several
        #    apps; a token meant for another app shouldn't work here.
        if claims.get("client_id") != self.settings.cognito_client_id:
            raise jwt.InvalidTokenError("Token was issued for a different app")

        return claims


_verifier: TokenVerifier | None = None


def get_token_verifier(settings: Settings = Depends(get_settings)) -> TokenVerifier:
    """Create the verifier once, then reuse it (so the key cache is reused too)."""
    global _verifier
    if _verifier is None:
        _verifier = TokenVerifier(settings)
    return _verifier


async def fetch_user_info(settings: Settings, access_token: str) -> dict:
    """
    Access tokens identify a user (by their "sub", a permanent unique ID), but
    don't contain their email or name. Cognito's userInfo endpoint returns
    those when given a valid access token. We only call this the FIRST time
    we see a user, then keep the details in our own database.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            f"{settings.cognito_domain}/oauth2/userInfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        return response.json()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    verifier: TokenVerifier = Depends(get_token_verifier),
    settings: Settings = Depends(get_settings),
    db: AsyncDatabase = Depends(get_db),
) -> dict:
    """
    A FastAPI dependency that protects endpoints. Add
        user: dict = Depends(get_current_user)
    to any endpoint, and it will only run for logged-in users - and it
    receives that user's record from our database.
    """
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not logged in, or your session has expired",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized

    try:
        # verify() uses a normal (blocking) network call to fetch keys the
        # first time, so we run it in a thread to keep the server responsive.
        claims = await run_in_threadpool(verifier.verify, credentials.credentials)
    except jwt.PyJWTError:
        # Deliberately vague: never tell an attacker WHY their token failed.
        raise unauthorized

    # Is this someone we already know?
    user = await db.users.find_one({"cognito_sub": claims["sub"]})
    if user is not None:
        return user

    # First visit: fetch their email/name from Cognito and create their record.
    try:
        info = await fetch_user_info(settings, credentials.credentials)
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Could not load your profile from the login service")

    email = info.get("email", "")
    # find_one_and_update with upsert=True means "update it if it exists,
    # otherwise create it" - safe even if two requests arrive at once.
    user = await db.users.find_one_and_update(
        {"cognito_sub": claims["sub"]},
        {
            "$setOnInsert": {
                "cognito_sub": claims["sub"],
                "email": email,
                "name": info.get("name") or email.split("@")[0],
                "created_at": datetime.now(UTC),
                # Privacy by default: answers stay private until the user
                # explicitly chooses to share them (used in a later phase).
                "share_answers_by_default": False,
            }
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return user
