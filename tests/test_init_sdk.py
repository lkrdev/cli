import os
import sqlite3
from unittest.mock import MagicMock, patch
import pytest

from lkr_dev_cli import init_sdk
from lkr.auth_service import ApiKeyApiSettings, SqlLiteAuth
from lkr.classes import LkrCtxObj, LookerApiKey


def test_init_sdk_explicit_args(monkeypatch):
    mock_sdk = MagicMock()
    with patch("lkr.auth_service.init_api_key_sdk", return_value=mock_sdk) as mock_init:
        sdk = init_sdk(
            base_url="https://explicit.looker.com",
            client_id="test_id",
            client_secret="test_secret",
            verify_ssl=False,
        )
        assert sdk == mock_sdk
        mock_init.assert_called_once()
        api_key, use_prod = (
            mock_init.call_args[0][0],
            mock_init.call_args[1]["use_production"],
        )
        assert api_key.base_url == "https://explicit.looker.com"
        assert api_key.client_id == "test_id"
        assert api_key.client_secret == "test_secret"
        assert api_key.verify_ssl is False
        assert use_prod is True


def test_init_sdk_env_vars(monkeypatch):
    monkeypatch.setenv("LOOKERSDK_BASE_URL", "https://env.looker.com")
    monkeypatch.setenv("LOOKERSDK_CLIENT_ID", "env_id")
    monkeypatch.setenv("LOOKERSDK_CLIENT_SECRET", "env_secret")
    monkeypatch.setenv("LOOKERSDK_VERIFY_SSL", "false")

    mock_sdk = MagicMock()
    with patch("lkr.auth_service.init_api_key_sdk", return_value=mock_sdk) as mock_init:
        sdk = init_sdk()
        assert sdk == mock_sdk
        mock_init.assert_called_once()
        api_key = mock_init.call_args[0][0]
        assert api_key.base_url == "https://env.looker.com"
        assert api_key.client_id == "env_id"
        assert api_key.client_secret == "env_secret"
        assert api_key.verify_ssl is False


def test_api_key_api_settings():
    api_key = LookerApiKey(
        client_id="my_id",
        client_secret="my_secret",
        base_url="https://settings.looker.com",
        verify_ssl=False,
    )
    settings = ApiKeyApiSettings(api_key)
    config = settings.read_config()
    assert config["base_url"] == "https://settings.looker.com"
    assert config["client_id"] == "my_id"
    assert config["client_secret"] == "my_secret"
    assert config["verify_ssl"] == "false"


def test_init_sdk_db_auth_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("LOOKERSDK_BASE_URL", raising=False)
    monkeypatch.delenv("LOOKERSDK_CLIENT_ID", raising=False)
    monkeypatch.delenv("LOOKERSDK_CLIENT_SECRET", raising=False)

    db_path = tmp_path / "auth.db"

    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS auth (
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
    conn.execute(
        """
        INSERT INTO auth (instance_name, access_token, refresh_token, refresh_expires_at, token_type, expires_at, current_instance, base_url, use_production)
        VALUES ('my_db_instance', 'acc_tok', 'ref_tok', '2030-01-01T00:00:00+00:00', 'Bearer', '2030-01-01T00:00:00+00:00', 1, 'https://db.looker.com', 1)
        """
    )
    conn.commit()
    conn.close()

    mock_sdk = MagicMock()
    with patch(
        "lkr.auth_service.SqlLiteAuth.get_current_sdk", return_value=mock_sdk
    ) as mock_get_sdk:
        with patch("lkr.auth_service.os.path.expanduser", return_value=str(db_path)):
            sdk = init_sdk(instance_name="my_db_instance")
            assert sdk == mock_sdk
            mock_get_sdk.assert_called_once()


def test_sqlite_auth_match_instance_name(tmp_path, monkeypatch):
    db_path = tmp_path / "auth.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS auth (
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
    conn.execute(
        """
        INSERT INTO auth (instance_name, access_token, refresh_token, refresh_expires_at, token_type, expires_at, current_instance, base_url, use_production)
        VALUES ('matched_inst', 'acc_tok', 'ref_tok', '2030-01-01T00:00:00+00:00', 'Bearer', '2030-01-01T00:00:00+00:00', 0, 'https://matchme.looker.com', 1)
        """
    )
    conn.commit()
    conn.close()

    ctx = LkrCtxObj(force_oauth=True, oauth_account="matched_inst")
    with patch("lkr.auth_service.os.path.expanduser", return_value=str(db_path)):
        sql_auth = SqlLiteAuth(ctx, db_path=str(db_path))
        current_auth = sql_auth._get_current_auth()
        assert current_auth is not None
        assert current_auth.instance_name == "matched_inst"
        assert current_auth.base_url == "https://matchme.looker.com"

