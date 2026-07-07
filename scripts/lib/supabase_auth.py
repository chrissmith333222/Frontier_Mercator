"""
scripts/lib/supabase_auth.py

Supabase email/password auth for the deployed dashboard -- gates the
Research Assistant chatbot (the only live paid-API surface on the site)
behind a login, while the rest of the site stays open (Chris: "I'm fine
with people accessing the data and interface... login button and login
with username and password to get full functionality").

Talks to Supabase's REST APIs directly with `requests` (GoTrue for auth,
PostgREST for the profiles table) rather than adding the supabase-py SDK
-- two small REST calls don't justify a new dependency tree on the
deployed app.

Security model:
  - The anon key is PUBLIC by design (it's what any browser client ships
    with); row-level security in Postgres is what actually protects data.
    It still lives in .env / Streamlit secrets, not source, so rotating it
    never requires a code change.
  - The profiles table + RLS policies are created once by pasting
    supabase_setup.sql into the Supabase dashboard's SQL editor (the anon
    key deliberately cannot create tables).
  - Admin (member list) visibility is enforced server-side by an RLS
    policy pinned to the admin email -- NOT by a client-side email check
    alone. The dashboard's email check only decides whether to render the
    admin section; the data itself is protected by Postgres.

Usage (as a module):
    from scripts.lib.supabase_auth import sign_up, sign_in, fetch_profiles
"""

import os

import requests

DEFAULT_TIMEOUT = 20
ADMIN_EMAIL_DEFAULT = "chrissmith333222@gmail.com"


def get_config() -> dict | None:
    """Reads Supabase connection settings from the environment (.env
    locally) or Streamlit secrets (deployed). Returns None when not
    configured, so the dashboard can degrade to 'auth not set up yet'
    instead of crashing."""
    from dotenv import load_dotenv
    load_dotenv()
    url = os.environ.get("SUPABASE_URL")
    anon_key = os.environ.get("SUPABASE_ANON_KEY")
    admin_email = os.environ.get("ADMIN_EMAIL", ADMIN_EMAIL_DEFAULT)
    if not url or not anon_key:
        try:
            import streamlit as st
            url = url or st.secrets.get("SUPABASE_URL")
            anon_key = anon_key or st.secrets.get("SUPABASE_ANON_KEY")
            admin_email = st.secrets.get("ADMIN_EMAIL", admin_email)
        except Exception:
            pass
    if not url or not anon_key:
        return None
    return {"url": url.rstrip("/"), "anon_key": anon_key, "admin_email": admin_email}


def _auth_headers(config: dict, access_token: str | None = None) -> dict:
    return {
        "apikey": config["anon_key"],
        "Authorization": f"Bearer {access_token or config['anon_key']}",
        "Content-Type": "application/json",
    }


def sign_up(config: dict, email: str, password: str, full_name: str) -> dict:
    """Creates a Supabase auth user. Returns {"ok": bool, "message": str}.
    Supabase sends a confirmation email by default -- the user must click
    it before their first login works."""
    try:
        response = requests.post(
            f"{config['url']}/auth/v1/signup",
            headers=_auth_headers(config),
            json={"email": email, "password": password,
                  "data": {"full_name": full_name}},
            timeout=DEFAULT_TIMEOUT,
        )
    except requests.RequestException as e:
        return {"ok": False, "message": f"Could not reach the auth service: {e}"}
    if response.status_code == 200:
        return {"ok": True, "message": "Account created. Check your email for a confirmation "
                                        "link, then come back and log in."}
    detail = response.json().get("msg") or response.json().get("error_description") or response.text[:200]
    return {"ok": False, "message": f"Sign-up failed: {detail}"}


def sign_in(config: dict, email: str, password: str) -> dict:
    """Logs in with email/password. Returns {"ok", "message"} plus
    {"access_token", "email", "full_name"} on success."""
    try:
        response = requests.post(
            f"{config['url']}/auth/v1/token?grant_type=password",
            headers=_auth_headers(config),
            json={"email": email, "password": password},
            timeout=DEFAULT_TIMEOUT,
        )
    except requests.RequestException as e:
        return {"ok": False, "message": f"Could not reach the auth service: {e}"}
    if response.status_code != 200:
        detail = response.json().get("error_description") or response.json().get("msg") or "invalid credentials"
        return {"ok": False, "message": f"Login failed: {detail}"}
    payload = response.json()
    user = payload.get("user", {})
    return {
        "ok": True,
        "message": "Logged in.",
        "access_token": payload.get("access_token", ""),
        "email": user.get("email", email),
        "full_name": (user.get("user_metadata") or {}).get("full_name", ""),
    }


def fetch_profiles(config: dict, access_token: str) -> dict:
    """Fetches the member list (admin only -- enforced by RLS, not by this
    client). Returns {"ok", "message"} plus {"profiles": [...]} on success;
    non-admin callers get an empty list back from Postgres, not an error."""
    try:
        response = requests.get(
            f"{config['url']}/rest/v1/profiles",
            headers=_auth_headers(config, access_token),
            params={"select": "full_name,email,created_at", "order": "created_at.desc"},
            timeout=DEFAULT_TIMEOUT,
        )
    except requests.RequestException as e:
        return {"ok": False, "message": f"Could not reach the database: {e}"}
    if response.status_code != 200:
        return {"ok": False, "message": f"Member list unavailable (status {response.status_code}). "
                                         "Has supabase_setup.sql been run in the Supabase SQL editor?"}
    return {"ok": True, "message": "", "profiles": response.json()}
