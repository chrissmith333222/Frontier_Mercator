"""
meridian/scripts/lib/acled_auth.py

Handles ACLED's OAuth authentication flow.

ACLED migrated from a static API key system to OAuth (access token + refresh token)
in late 2025. This module:
  1. Exchanges email/password for an access token (valid ~24 hours) + refresh token
  2. Caches the token locally so we don't re-authenticate on every single API call
  3. Automatically refreshes when the cached token is expired or about to expire

Credentials are read from environment variables (via .env), never hardcoded and
never passed as function arguments from outside this module's own env-reading code.

Reference: https://acleddata.com/api-documentation/getting-started
"""

import os
import json
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

ACLED_BASE_URL = "https://acleddata.com"
TOKEN_ENDPOINT = f"{ACLED_BASE_URL}/oauth/token"

# Local cache so we're not hitting the token endpoint on every script run.
# This file is gitignored (it's under data/) and contains a short-lived token,
# not your actual password.
TOKEN_CACHE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / ".acled_token_cache.json"


class ACLEDAuthError(Exception):
    """Raised when ACLED authentication fails for any reason."""
    pass


def _read_cached_token() -> dict | None:
    if not TOKEN_CACHE_PATH.exists():
        return None
    try:
        with open(TOKEN_CACHE_PATH, "r") as f:
            cache = json.load(f)
        expires_at = datetime.fromisoformat(cache["expires_at"])
        # Refresh 5 minutes early to avoid edge-of-expiry failures mid-request
        if expires_at - timedelta(minutes=5) > datetime.now(timezone.utc):
            return cache
        return None
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


def _write_cached_token(access_token: str, refresh_token: str, expires_in_seconds: int) -> None:
    TOKEN_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in_seconds)
    cache = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at.isoformat(),
    }
    with open(TOKEN_CACHE_PATH, "w") as f:
        json.dump(cache, f)
    # Lock down permissions since this file holds a live (if short-lived) token
    os.chmod(TOKEN_CACHE_PATH, 0o600)


def _request_new_token() -> dict:
    """Exchange email + password for a fresh access token + refresh token."""
    email = os.environ.get("ACLED_EMAIL")
    password = os.environ.get("ACLED_PASSWORD")
    client_id = os.environ.get("ACLED_CLIENT_ID", "acled")

    if not email or not password:
        raise ACLEDAuthError(
            "ACLED_EMAIL and ACLED_PASSWORD must be set in your .env file. "
            "See docs/acled_setup.md for how to register and obtain these."
        )

    response = requests.post(
        TOKEN_ENDPOINT,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "username": email,
            "password": password,
            "grant_type": "password",
            "client_id": client_id,
        },
        timeout=30,
    )

    if response.status_code != 200:
        raise ACLEDAuthError(
            f"ACLED token request failed with status {response.status_code}: "
            f"{response.text[:500]}. Check that ACLED_EMAIL and ACLED_PASSWORD in "
            f"your .env are correct, and that your myACLED account is active."
        )

    payload = response.json()
    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    expires_in = payload.get("expires_in", 86400)  # default 24h if not provided

    if not access_token:
        raise ACLEDAuthError(f"ACLED token response missing access_token: {payload}")

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": expires_in,
    }


def _refresh_token(refresh_token: str) -> dict:
    """Use a refresh token to get a new access token without re-sending password."""
    client_id = os.environ.get("ACLED_CLIENT_ID", "acled")

    response = requests.post(
        TOKEN_ENDPOINT,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
        },
        timeout=30,
    )

    if response.status_code != 200:
        # Refresh failed (e.g. refresh token also expired) — fall back to full re-auth
        return _request_new_token()

    payload = response.json()
    return {
        "access_token": payload.get("access_token"),
        "refresh_token": payload.get("refresh_token", refresh_token),
        "expires_in": payload.get("expires_in", 86400),
    }


def get_access_token(force_refresh: bool = False) -> str:
    """
    Main entry point. Returns a valid ACLED access token, handling caching and
    refresh transparently. This is the only function other scripts should call.
    """
    if not force_refresh:
        cached = _read_cached_token()
        if cached:
            return cached["access_token"]

    # Try refresh first if we have a refresh token sitting in an expired cache
    if TOKEN_CACHE_PATH.exists():
        try:
            with open(TOKEN_CACHE_PATH, "r") as f:
                stale_cache = json.load(f)
            if stale_cache.get("refresh_token"):
                fresh = _refresh_token(stale_cache["refresh_token"])
                _write_cached_token(
                    fresh["access_token"], fresh["refresh_token"], fresh["expires_in"]
                )
                return fresh["access_token"]
        except (json.JSONDecodeError, KeyError):
            pass

    # Full re-authentication from email/password
    fresh = _request_new_token()
    _write_cached_token(fresh["access_token"], fresh["refresh_token"], fresh["expires_in"])
    return fresh["access_token"]


def get_auth_headers() -> dict:
    """Convenience helper — returns the Authorization header dict ready for requests."""
    token = get_access_token()
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
