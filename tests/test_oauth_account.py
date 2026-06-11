import sqlite3
import pytest
import typer
from looker_sdk.rtl.auth_token import AccessToken
from lkr.classes import LkrCtxObj
from lkr.auth_service import SqlLiteAuth


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
        access_token="token-refreshed", token_type="Bearer", expires_in=3600
    )
    curr.set_token(auth_service.conn, new_token=new_token, commit=True)

    # Verify that target-inst was updated
    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT access_token, current_instance FROM auth WHERE instance_name = 'target-inst'"
    ).fetchone()
    assert row["access_token"] == "token-refreshed"
    assert row["current_instance"] == 0  # Still not active!

    # Verify that active-inst was NOT touched
    row_active = conn.execute(
        "SELECT access_token, current_instance FROM auth WHERE instance_name = 'active-inst'"
    ).fetchone()
    assert row_active["access_token"] == "token-active"
    assert row_active["current_instance"] == 1
    conn.close()
