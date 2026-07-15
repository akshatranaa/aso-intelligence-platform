"""Supabase-Auth request authentication for the FastAPI backend.

The browser signs in with Supabase directly and receives a JWT access token.
The Next.js proxy forwards it as `Authorization: Bearer <token>`; these
dependencies verify that token and identify the calling user, so data can be
scoped per account.

Supabase's current signing scheme is asymmetric (ES256/RS256), verified via the
project's public JWKS endpoint — so no shared secret is needed. Older projects
sign with a shared HS256 secret; that path is kept as a fallback.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import jwt
from fastapi import Depends, Header, HTTPException
from jwt import PyJWKClient

import database

logger = logging.getLogger(__name__)

# Public JWKS endpoint, e.g. https://<ref>.supabase.co/auth/v1/.well-known/jwks.json
_JWKS_URL = os.environ.get("SUPABASE_JWKS_URL")
# Legacy HS256 shared secret (only for older projects). Optional.
_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET")

_AUDIENCE = "authenticated"
_ASYMMETRIC_ALGS = ["ES256", "RS256"]

# Caches the signing keys fetched from Supabase's JWKS endpoint.
_jwks_client = PyJWKClient(_JWKS_URL) if _JWKS_URL else None


def get_current_user(authorization: Optional[str] = Header(default=None)) -> dict:
    """
    Verify the Supabase JWT on the request and return the authenticated user.

    Args:
        authorization: The `Authorization: Bearer <token>` request header.

    Returns:
        Dict with the user's Supabase id (UUID string) and email.

    Raises:
        HTTPException: 500 if auth isn't configured, 401 if the token is
        missing, malformed, expired, or otherwise invalid.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()

    try:
        alg = jwt.get_unverified_header(token).get("alg")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Malformed token")

    try:
        if alg == "HS256":
            if not _JWT_SECRET:
                raise HTTPException(
                    status_code=500,
                    detail="Auth not configured (SUPABASE_JWT_SECRET missing)",
                )
            payload = jwt.decode(
                token, _JWT_SECRET, algorithms=["HS256"], audience=_AUDIENCE
            )
        else:
            if not _jwks_client:
                raise HTTPException(
                    status_code=500,
                    detail="Auth not configured (SUPABASE_JWKS_URL missing)",
                )
            signing_key = _jwks_client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=_ASYMMETRIC_ALGS,
                audience=_AUDIENCE,
            )
    except HTTPException:
        raise
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    except Exception as e:  # e.g. JWKS fetch failure
        logger.error(f"Token verification failed: {e}")
        raise HTTPException(status_code=401, detail="Could not verify token")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing subject")
    return {"id": user_id, "email": payload.get("email")}


def require_app_membership(
    app_id: int,
    country: Optional[str] = None,
    user: dict = Depends(get_current_user),
) -> dict:
    """
    Ensure the authenticated user owns (has collected/loaded) the given app.

    When the request carries a country (query param — every country-scoped
    route also declares its own `country`, and FastAPI binds both from the
    same value), ownership is checked at the (app, country) level: a user who
    collected this app for India can't view its US data just because they own
    the app_id in general. Without a country in the request, the coarser
    "owns the app at all" check applies.

    Args:
        app_id:  iTunes numeric app ID from the path.
        country: App Store country from the query string, if the route has one.
        user:    The authenticated user (injected).

    Returns:
        The authenticated user dict.

    Raises:
        HTTPException: 403 if the user doesn't own this app (+ country).
    """
    owns = (
        database.user_owns_app_country(user["id"], app_id, country)
        if country
        else database.user_owns_app(user["id"], app_id)
    )
    if not owns:
        raise HTTPException(
            status_code=403, detail="You don't have access to this app"
        )
    return user
