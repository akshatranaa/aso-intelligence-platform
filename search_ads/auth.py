"""Apple Search Ads OAuth 2.0 authentication — certificate-based client credentials flow."""

from __future__ import annotations

import logging
import os
import time

import httpx
import jwt
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

APPLE_TOKEN_URL = "https://appleid.apple.com/auth/oauth2/token"

_CLIENT_ID  = os.getenv("SEARCH_ADS_CLIENT_ID")
_TEAM_ID    = os.getenv("SEARCH_ADS_TEAM_ID")
_KEY_ID     = os.getenv("SEARCH_ADS_KEY_ID")
_KEY_PATH   = os.getenv("SEARCH_ADS_PRIVATE_KEY_PATH")

# Module-level cache — avoids re-authenticating on every API call
_token_cache: dict = {"token": None, "expires_at": 0.0}


def _read_private_key() -> str:
    """
    Read the private key PEM file from disk.

    Returns:
        Raw PEM string contents.

    Raises:
        FileNotFoundError: If the key file path is missing or wrong.
    """
    if not _KEY_PATH:
        raise ValueError("SEARCH_ADS_PRIVATE_KEY_PATH not set in .env")
    with open(_KEY_PATH) as f:
        return f.read()


def _build_jwt() -> str:
    """
    Build and sign a JWT using the private key.

    The JWT proves our identity to Apple without sending the private key.
    Apple verifies the signature against our registered public key.

    Returns:
        Signed JWT string.
    """
    now = int(time.time())
    payload = {
        "iss": _CLIENT_ID,                      # who is making the claim
        "iat": now,                              # issued at
        "exp": now + 3600,                       # expires in 1 hour
        "aud": "https://appleid.apple.com",      # Apple's auth server
        "sub": _CLIENT_ID,                       # subject — same as issuer
    }
    private_key = _read_private_key()
    return jwt.encode(
        payload,
        private_key,
        algorithm="ES256",                       # elliptic curve — Apple requirement
        headers={"kid": _KEY_ID},               # tells Apple which public key to verify with
    )


def _fetch_token() -> str:
    """
    Exchange a signed JWT for an access token from Apple's token endpoint.

    Returns:
        Raw access token string.

    Raises:
        RuntimeError: If Apple rejects the request.
    """
    signed_jwt = _build_jwt()
    try:
        response = httpx.post(
            APPLE_TOKEN_URL,
            data={
                "grant_type":    "client_credentials",
                "client_id":     _CLIENT_ID,
                "client_secret": signed_jwt,     # JWT is the proof of identity
                "scope":         "searchadsorg",
            },
        )
        response.raise_for_status()
        token = response.json()["access_token"]
        logger.info("Successfully fetched new Search Ads access token")
        return token
    except httpx.HTTPStatusError as e:
        logger.error(f"Apple token endpoint returned {e.response.status_code}: {e.response.text}")
        raise RuntimeError("Failed to fetch Search Ads access token") from e
    except Exception as e:
        logger.error(f"Unexpected error fetching access token: {e}")
        raise


def get_access_token() -> str:
    """
    Return a valid Search Ads access token, fetching a new one only when needed.

    Caches the token in memory and reuses it until 60 seconds before expiry.
    This is the only function fetcher.py should call.

    Returns:
        Valid access token string for use as a Bearer token.
    """
    if time.time() < _token_cache["expires_at"] - 60:
        logger.debug("Reusing cached Search Ads access token")
        return _token_cache["token"]

    token = _fetch_token()
    _token_cache["token"] = token
    _token_cache["expires_at"] = time.time() + 3600
    return token
