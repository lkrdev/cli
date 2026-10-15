import sqlite3

import pytest
import typer
from looker_sdk.rtl.auth_token import AccessToken

from lkr.auth_service import SqlLiteAuth
from lkr.classes import LkrCtxObj


@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "auth.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE auth (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            instance_name TEXT, 
            access_token TEXT, 
            refresh_token TEXT, 
            refresh_expires_at TEXT, 
            token_type TEXT, 
            expires_at TEXT, 
            current_instance BOOLEAN, 
            base_url TEXT, 
            use_production BOOLEAN
        )
        """
    )
    # Insert two records
    conn.execute(
        "INSERT INTO auth (instance_name, access_token, refresh_token, refresh_expires_at, token_type, current_instance, base_url, use_production, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "active-inst",
            "token-active",
            "refresh-active",
            "2030-02-01T00:00:00Z",
            "Bearer",
            1,
            "https://active.looker.com",
            1,
            "2030-01-01T00:00:00Z",
        ),
    )
    conn.execute(
        "INSERT INTO auth (instance_name, access_token, refresh_token, refresh_expires_at, token_type, current_instance, base_url, use_production, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "target-inst",
            "token-target",
            "refresh-target",
            "2030-02-01T00:00:00Z",
            "Bearer",
            0,
            "https://target.looker.com",
            1,
            "2030-01-01T00:00:00Z",
        ),
    )
    conn.commit()
    conn.close()
    return str(db_path)


def test_get_current_auth_default(temp_db):
    ctx = LkrCtxObj(force_oauth=False)
    auth_service = SqlLiteAuth(ctx, db_path=temp_db)
    curr = auth_service._get_current_auth()
    assert curr is not None
    assert curr.instance_name == "active-inst"
    assert curr.access_token == "token-active"


def test_get_current_auth_oauth_account(temp_db):
    ctx = LkrCtxObj(force_oauth=False, oauth_account="target-inst")
    auth_service = SqlLiteAuth(ctx, db_path=temp_db)
    curr = auth_service._get_current_auth()
    assert curr is not None
    assert curr.instance_name == "target-inst"
    assert curr.access_token == "token-target"


def test_get_current_auth_oauth_account_not_found(temp_db):
    ctx = LkrCtxObj(force_oauth=False, oauth_account="non-existent")
    auth_service = SqlLiteAuth(ctx, db_path=temp_db)
    with pytest.raises(typer.Exit) as exc_info:
        auth_service._get_current_auth()
    assert exc_info.value.exit_code == 1


def test_set_token_refreshes_lookedup_account(temp_db):
    ctx = LkrCtxObj(force_oauth=False, oauth_account="target-inst")
    auth_service = SqlLiteAuth(ctx, db_path=temp_db)
    curr = auth_service._get_current_auth()
    assert curr is not None
    assert curr.instance_name == "target-inst"

    # Refresh the token
    new_token = AccessToken(
        access_token="token-refreshed",
        refresh_token="refresh-target-new",
        token_type="Bearer",
        expires_in=3600,
    )
    curr.set_token(auth_service.conn, new_token=new_token, commit=True)

    # Verify that target-inst was updated
    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT access_token, refresh_token, current_instance FROM auth WHERE instance_name = 'target-inst'"
    ).fetchone()
    assert row["access_token"] == "token-refreshed"
    assert row["refresh_token"] == "refresh-target-new"
    assert row["current_instance"] == 0  # Still not active!

    # Verify that active-inst was NOT touched
    row_active = conn.execute(
        "SELECT access_token, current_instance FROM auth WHERE instance_name = 'active-inst'"
    ).fetchone()
    assert row_active["access_token"] == "token-active"
    assert row_active["current_instance"] == 1
    conn.close()


def test_parse_auth_code_input():
    from lkr.auth.oauth import parse_auth_code_input

    assert parse_auth_code_input("  raw-code-123  ") == "raw-code-123"
    assert (
        parse_auth_code_input(
            "https://www.lkr.dev/oauth/callback/?code=url-code-456&state=s1",
            expected_state="s1",
        )
        == "url-code-456"
    )
    assert (
        parse_auth_code_input(
            "localhost:8000/callback?code=schemeless-789&state=s1",
            expected_state="s1",
        )
        == "schemeless-789"
    )
    with pytest.raises(ValueError, match="state mismatch"):
        parse_auth_code_input(
            "https://www.lkr.dev/oauth/callback/?code=abc&state=wrong",
            expected_state="expected",
        )
    with pytest.raises(ValueError, match="state mismatch"):
        parse_auth_code_input(
            "https://www.lkr.dev/oauth/callback/?code=abc",
            expected_state="expected",
        )
    with pytest.raises(ValueError, match="Looker OAuth error: access_denied"):
        parse_auth_code_input(
            "https://www.lkr.dev/oauth/callback/?error=access_denied&error_description=nope"
        )


def test_oauth_api_settings_default_redirect_uri(monkeypatch):
    from lkr.auth_service import OAuthApiSettings
    from lkr.constants import OAUTH_REDIRECT_URI

    monkeypatch.delenv("LKR_OAUTH_REDIRECT_URI", raising=False)
    settings = OAuthApiSettings("https://acme.cloud.looker.com")
    config = settings.read_config()
    assert config["redirect_uri"] == OAUTH_REDIRECT_URI

    monkeypatch.setenv("LKR_OAUTH_REDIRECT_URI", "http://localhost:3000/oauth/callback")
    local_settings = OAuthApiSettings("https://acme.cloud.looker.com")
    assert (
        local_settings.read_config()["redirect_uri"]
        == "http://localhost:3000/oauth/callback"
    )


def test_oauth_pkce_localhost_callback_wins_race(monkeypatch):
    import socket
    import threading
    import time
    import urllib.request

    from lkr.auth.oauth import OAuth2PKCE

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("localhost", 0))
        free_port = s.getsockname()[1]

    monkeypatch.setattr("lkr.auth.oauth.kill_process_on_port", lambda _p: None)
    monkeypatch.setattr("lkr.auth.oauth.webbrowser.open", lambda _u: True)

    oauth = OAuth2PKCE(
        new_token_callback=lambda _t: None,
        use_production=False,
        port=free_port,
    )

    def send_callback():
        for _ in range(30):
            if oauth.server is not None:
                break
            time.sleep(0.05)
        with urllib.request.urlopen(
            f"http://localhost:{free_port}/callback?code=auto_cb_code&state={oauth.state}"
        ) as resp:
            assert resp.status == 200
            assert resp.headers.get("Access-Control-Allow-Origin") == "*"
            assert resp.headers.get("Access-Control-Allow-Private-Network") == "true"

    t = threading.Thread(target=send_callback, daemon=True)
    t.start()

    result = oauth.initiate_login("https://acme.cloud.looker.com")
    t.join(timeout=2.0)

    assert result["auth_code"] == "auto_cb_code"
    assert result["code_verifier"]
    assert oauth.server is None


def test_oauth_pkce_stdin_paste_wins_race(monkeypatch):
    import io
    import socket

    from lkr.auth.oauth import OAuth2PKCE

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("localhost", 0))
        free_port = s.getsockname()[1]

    monkeypatch.setattr("lkr.auth.oauth.kill_process_on_port", lambda _p: None)
    monkeypatch.setattr("lkr.auth.oauth.webbrowser.open", lambda _u: True)
    monkeypatch.setattr("sys.stdin", io.StringIO("pasted_vm_code_999\n"))

    oauth = OAuth2PKCE(
        new_token_callback=lambda _t: None,
        use_production=False,
        port=free_port,
    )

    result = oauth.initiate_login("https://acme.cloud.looker.com")

    assert result["auth_code"] == "pasted_vm_code_999"
    assert result["code_verifier"]
    assert oauth.server is None


def test_refresh_token_under_2h_rotates_and_preserves_in_memory(temp_db, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from lkr.auth_service import DbOAuthSession

    under_2h = (datetime.now(UTC) + timedelta(minutes=90)).isoformat()
    past_access = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    auth_service = SqlLiteAuth(LkrCtxObj(force_oauth=False), db_path=temp_db)
    auth_service.conn.execute(
        "UPDATE auth SET refresh_expires_at = ?, expires_at = ? WHERE instance_name = 'active-inst'",
        (under_2h, past_access),
    )
    auth_service.conn.commit()

    curr = auth_service._get_current_auth()
    assert curr is not None and curr.valid_refresh_token

    # 1) >= 2h response (refresh_token omitted) preserves refresh_token + refresh_expires_at in db & session
    monkeypatch.setattr(
        DbOAuthSession,
        "_request_token",
        lambda self, params, transport_options: AccessToken(
            access_token="token-refreshed-1",
            refresh_token=None,
            token_type="Bearer",
            expires_in=3600,
        ),
    )
    sdk = auth_service.get_current_sdk(prompt_refresh_invalid_token=True)
    assert isinstance(sdk.auth, DbOAuthSession)
    assert sdk.auth.token.access_token == "token-refreshed-1"
    assert sdk.auth.token.refresh_token == "refresh-active"
    row = auth_service.conn.execute(
        "SELECT access_token, refresh_token, refresh_expires_at, expires_at FROM auth WHERE instance_name = 'active-inst'"
    ).fetchone()
    assert row["access_token"] == "token-refreshed-1"
    assert row["refresh_token"] == "refresh-active"
    assert row["refresh_expires_at"] == under_2h
    assert row["expires_at"] > past_access

    # 2) < 2h response (refresh_token rotated) updates refresh_token + extends refresh_expires_at in db & session
    monkeypatch.setattr(
        DbOAuthSession,
        "_request_token",
        lambda self, params, transport_options: AccessToken(
            access_token="token-refreshed-2",
            refresh_token="refresh-rotated",
            token_type="Bearer",
            expires_in=3600,
        ),
    )
    sdk.auth._login({})
    assert sdk.auth.token.access_token == "token-refreshed-2"
    assert sdk.auth.token.refresh_token == "refresh-rotated"
    row2 = auth_service.conn.execute(
        "SELECT access_token, refresh_token, refresh_expires_at FROM auth WHERE instance_name = 'active-inst'"
    ).fetchone()
    assert row2["access_token"] == "token-refreshed-2"
    assert row2["refresh_token"] == "refresh-rotated"
    assert row2["refresh_expires_at"] > under_2h

    # 3) CurrentAuth.__add__ preserves refresh_token when omitted
    prev_exp = curr.refresh_expires_at
    curr + AccessToken(access_token="token-3", refresh_token=None, expires_in=3600)
    assert curr.refresh_token == "refresh-active"
    assert curr.refresh_expires_at == prev_exp

