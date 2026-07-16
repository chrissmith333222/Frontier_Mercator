"""
tests/test_supabase_auth.py

Tests the Supabase auth helpers' request/response handling with a stubbed
requests layer -- no live Supabase project needed.

Usage:
    python -m pytest tests/test_supabase_auth.py -v
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scripts.lib.supabase_auth as auth

CONFIG = {"url": "https://example.supabase.co", "anon_key": "anon-key",
          "admin_email": "admin@example.com"}


def _response(status_code: int, payload: dict):
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = payload
    mock.text = str(payload)
    return mock


def test_get_config_returns_none_when_unset(monkeypatch):
    for key in ("SUPABASE_URL", "SUPABASE_ANON_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(auth, "get_config", auth.get_config)  # no-op, keeps import honest
    with patch("dotenv.load_dotenv", lambda *a, **k: None):
        assert auth.get_config() is None
    print("✓ test_get_config_returns_none_when_unset passed")


def test_sign_up_success_message_mentions_email_confirmation():
    with patch.object(auth.requests, "post", return_value=_response(200, {})) as mock_post:
        result = auth.sign_up(CONFIG, "new@user.com", "password123", "New User")
    assert result["ok"]
    assert "confirmation" in result["message"].lower()
    sent = mock_post.call_args.kwargs["json"]
    assert sent["data"]["full_name"] == "New User"
    print("✓ test_sign_up_success_message_mentions_email_confirmation passed")


def test_sign_up_failure_surfaces_supabase_message():
    with patch.object(auth.requests, "post",
                       return_value=_response(422, {"msg": "User already registered"})):
        result = auth.sign_up(CONFIG, "dupe@user.com", "password123", "Dupe")
    assert not result["ok"]
    assert "already registered" in result["message"]
    print("✓ test_sign_up_failure_surfaces_supabase_message passed")


def test_sign_in_success_returns_token_and_upserts_profile():
    payload = {
        "access_token": "jwt-token",
        "user": {"id": "uuid-1", "email": "member@user.com",
                  "user_metadata": {"full_name": "Member"}},
    }
    with patch.object(auth.requests, "post", return_value=_response(200, payload)) as mock_post:
        result = auth.sign_in(CONFIG, "member@user.com", "password123")
    assert result["ok"]
    assert result["access_token"] == "jwt-token"
    assert result["full_name"] == "Member"
    # Second POST = the profiles mirror upsert (replaces the auth.users
    # trigger, which newer Supabase projects reject).
    assert mock_post.call_count == 2
    upsert_call = mock_post.call_args_list[1]
    assert upsert_call.args[0].endswith("/rest/v1/profiles")
    assert upsert_call.kwargs["json"]["id"] == "uuid-1"
    print("✓ test_sign_in_success_returns_token_and_upserts_profile passed")


def test_sign_in_failure_does_not_return_token():
    with patch.object(auth.requests, "post",
                       return_value=_response(400, {"error_description": "Invalid login credentials"})):
        result = auth.sign_in(CONFIG, "member@user.com", "wrong")
    assert not result["ok"]
    assert "access_token" not in result
    print("✓ test_sign_in_failure_does_not_return_token passed")


def test_fetch_profiles_uses_user_token_not_anon_key():
    with patch.object(auth.requests, "get", return_value=_response(200, [])) as mock_get:
        result = auth.fetch_profiles(CONFIG, "user-jwt")
    assert result["ok"]
    headers = mock_get.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer user-jwt"
    assert headers["apikey"] == "anon-key"
    print("✓ test_fetch_profiles_uses_user_token_not_anon_key passed")


def test_fetch_profiles_hints_at_setup_sql_on_error():
    with patch.object(auth.requests, "get", return_value=_response(404, {})):
        result = auth.fetch_profiles(CONFIG, "user-jwt")
    assert not result["ok"]
    assert "supabase_setup.sql" in result["message"]
    print("✓ test_fetch_profiles_hints_at_setup_sql_on_error passed")


def test_record_visit_posts_to_site_visits():
    with patch.object(auth.requests, "post", return_value=_response(201, {})) as mock_post:
        auth.record_visit(CONFIG)
    assert mock_post.call_args.args[0].endswith("/rest/v1/site_visits")
    # Timestamp-only counter: the row body must carry no personal data.
    assert mock_post.call_args.kwargs["json"] == {}
    print("✓ test_record_visit_posts_to_site_visits passed")


def test_record_visit_noop_without_config_and_swallows_errors():
    with patch.object(auth.requests, "post") as mock_post:
        auth.record_visit(None)
    assert mock_post.call_count == 0
    with patch.object(auth.requests, "post", side_effect=auth.requests.RequestException("boom")):
        auth.record_visit(CONFIG)  # must not raise
    print("✓ test_record_visit_noop_without_config_and_swallows_errors passed")


def test_network_errors_degrade_to_message_not_exception():
    with patch.object(auth.requests, "post", side_effect=auth.requests.RequestException("boom")):
        assert not auth.sign_in(CONFIG, "a@b.com", "pw")["ok"]
        assert not auth.sign_up(CONFIG, "a@b.com", "pw", "Name")["ok"]
    with patch.object(auth.requests, "get", side_effect=auth.requests.RequestException("boom")):
        assert not auth.fetch_profiles(CONFIG, "jwt")["ok"]
    print("✓ test_network_errors_degrade_to_message_not_exception passed")


if __name__ == "__main__":
    import inspect
    test_functions = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    print(f"Running {len(test_functions)} tests...\n")
    failures = 0
    for test_fn in test_functions:
        try:
            if "monkeypatch" in inspect.signature(test_fn).parameters:
                continue  # pytest-only fixture; skipped in direct-run mode
            test_fn()
        except AssertionError as e:
            failures += 1
            print(f"✗ {test_fn.__name__} FAILED: {e}")
    print(f"\n{len(test_functions) - failures}/{len(test_functions)} tests passed.")
    if failures:
        sys.exit(1)
