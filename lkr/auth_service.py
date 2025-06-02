import json
import os
import sqlite3
import types
from datetime import datetime, timedelta, timezone
from typing import List, Self, Tuple, Union

import requests
import typer
from looker_sdk.rtl import serialize
from looker_sdk.rtl.api_settings import ApiSettings, SettingsConfig
from looker_sdk.rtl.auth_session import AuthSession, CryptoHash, OAuthSession
from looker_sdk.rtl.auth_token import AccessToken, AuthToken
from looker_sdk.rtl.requests_transport import RequestsTransport
from looker_sdk.rtl.transport import LOOKER_API_ID, HttpMethod
from looker_sdk.sdk.api40.methods import Looker40SDK
from pydantic import BaseModel, Field, computed_field
from pydash import get

from lkr.classes import LkrCtxObj, LookerApiKey
from lkr.constants import LOOKER_API_VERSION, OAUTH_CLIENT_ID, OAUTH_REDIRECT_URI
from lkr.custom_types import NewTokenCallback
from lkr.logger import logger

__all__ = ["get_auth", "ApiKeyAuthSession", "DbOAuthSession"]


def get_auth(ctx: typer.Context | LkrCtxObj) -> Union["SqlLiteAuth", "ApiKeyAuth"]:
    if isinstance(ctx, LkrCtxObj):
        lkr_ctx = ctx
    else:
        lkr_ctx: LkrCtxObj | None = get(ctx, ["obj", "ctx_lkr"])
        if not lkr_ctx:
            logger.error("No Looker context found")
            raise typer.Exit(1)
    if lkr_ctx.use_sdk == "api_key" and lkr_ctx.api_key:
        logger.info("Using API key authentication")
        return ApiKeyAuth(lkr_ctx.api_key, use_production=lkr_ctx.use_production)
    else:
        return SqlLiteAuth(lkr_ctx)


class ApiKeyApiSettings(ApiSettings):
    def __init__(self, api_key: LookerApiKey):
        self.api_key = api_key
        super().__init__()
        self.agent_tag = "lkr-cli-api-key"

    def read_config(self) -> SettingsConfig:
        return SettingsConfig(
            base_url=self.api_key.base_url,
            client_id=self.api_key.client_id,
            client_secret=self.api_key.client_secret,
        )


class OAuthApiSettings(ApiSettings):
    def __init__(self, base_url: str):
        self.base_url = base_url
        super().__init__()
        self.agent_tag = "lkr-cli-oauth"

    def read_config(self) -> SettingsConfig:
        return SettingsConfig(
            base_url=self.base_url,
            looker_url=self.base_url,
            client_id=OAUTH_CLIENT_ID,
            client_secret="",  # PKCE doesn't need client secret
            redirect_uri=OAUTH_REDIRECT_URI,
        )


class ApiKeyAuthSession(AuthSession):
    def __init__(self, *args, use_production: bool, **kwargs):
        super().__init__(*args, **kwargs)
        self.use_production = use_production

    def _login(self, *args, **kwargs):
        super()._login(*args, **kwargs)
        if not self.use_production:
            self._switch_to_dev_mode()

    def _switch_to_dev_mode(self):
        logger.debug("Switching to dev mode")
        config = self.settings.read_config()
        if "base_url" in config:
            url = f"{config['base_url']}/api/{LOOKER_API_VERSION}/session"
            return self.transport.request(
                method=HttpMethod.PATCH,
                path=url,
                body=json.dumps({"workspace_id": "dev"}).encode("utf-8"),
                transport_options={
                    "headers": {
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.token.access_token}",
                    }
                },
            )
        else:
            raise ValueError("Base URL not found in settings")


class DbOAuthSession(OAuthSession):
    def __init__(
        self,
        *args,
        use_production: bool,
        new_token_callback: NewTokenCallback,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.new_token_callback = new_token_callback
        self.use_production = use_production

    def _login(self, *args, **kwargs):
        super()._login(*args, **kwargs)
        if not self.use_production:
            self._switch_to_dev_mode()

        self.new_token_callback(self.token)

    def redeem_auth_code(self, *args, **kwargs):
        super().redeem_auth_code(*args, **kwargs)
        self.new_token_callback(self.token)

    def _switch_to_dev_mode(self):
        logger.debug("Switching to dev mode")
        config = self.settings.read_config()
        if "base_url" in config:
            url = f"{config['base_url']}/api/{LOOKER_API_VERSION}/session"
            return self.transport.request(
                method=HttpMethod.PATCH,
                path=url,
                body=json.dumps({"workspace_id": "dev"}).encode("utf-8"),
                transport_options={
                    "headers": {
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.token.access_token}",
                    }
                },
            )
        else:
            raise ValueError("Base URL not found in settings")


def get_auth_session(
    base_url: str,
    new_token_callback: NewTokenCallback,
    *,
    use_production: bool,
    access_token: AccessToken | None = None,
) -> DbOAuthSession:
    settings = OAuthApiSettings(base_url)
    transport = MonkeyPatchTransport.configure(settings)
    auth = DbOAuthSession(
        settings=settings,
        transport=transport,
        deserialize=serialize.deserialize40,
        serialize=serialize.serialize40,
        crypto=CryptoHash(),
        version=LOOKER_API_VERSION,
        new_token_callback=new_token_callback,
        use_production=use_production,
    )
    if access_token:
        auth.token.set_token(access_token)
    return auth


def init_api_key_sdk(api_key: LookerApiKey, use_production: bool) -> Looker40SDK:
    from looker_sdk.rtl import serialize

    settings = ApiKeyApiSettings(api_key)
    settings.is_configured()
    transport = RequestsTransport.configure(settings)
    return Looker40SDK(
        auth=ApiKeyAuthSession(
            settings,
            transport,
            serialize.deserialize40,  # type: ignore
            LOOKER_API_VERSION,
            use_production=use_production,
        ),
        deserialize=serialize.deserialize40,  # type: ignore
        serialize=serialize.serialize40,  # type: ignore
        transport=transport,
        api_version=LOOKER_API_VERSION,
    )


# monkey patch to remove the LOOKER_API_ID header when exchanging the code for a token
def monkey_patch_prepare_request(session: requests.Session):
    original_prepare_request = session.prepare_request

    def prepare_request(self, request, *args, **kwargs):
        x = original_prepare_request(request, *args, **kwargs)
        if (
            x.headers.get(LOOKER_API_ID)
            and x.path_url.endswith("/api/token")
            and request.method == "POST"
        ):
            x.headers.pop(LOOKER_API_ID)
        return x

    session.prepare_request = types.MethodType(prepare_request, session)


class MonkeyPatchTransport(RequestsTransport):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        monkey_patch_prepare_request(self.session)


def init_oauth_sdk(
    base_url: str,
    new_token_callback: NewTokenCallback,
    *,
    access_token: AccessToken | None = None,
    use_production: bool = False,
) -> Looker40SDK:
    """Default dependency configuration"""
    settings = OAuthApiSettings(base_url)
    settings.is_configured()
    transport = MonkeyPatchTransport.configure(settings)

    auth = get_auth_session(
        base_url,
        new_token_callback,
        access_token=access_token,
        use_production=use_production,
    )
    return Looker40SDK(
        auth=auth,
        deserialize=serialize.deserialize40,  # type: ignore
        serialize=serialize.serialize40,  # type: ignore
        transport=transport,
        api_version=LOOKER_API_VERSION,
    )


class CurrentAuth(BaseModel):
    instance_name: str
    access_token: str
    refresh_token: str
    refresh_expires_at: str = Field(
        default_factory=lambda: (
            datetime.now(timezone.utc) + timedelta(days=30)
        ).isoformat()
    )
    token_type: str
    expires_in: int
    base_url: str
    from_db: bool = False
    use_production: bool = False

    @property
    def valid_refresh_token(self) -> bool:
        if not self.refresh_expires_at:
            return False
        return datetime.fromisoformat(self.refresh_expires_at).replace(
            tzinfo=timezone.utc
        ) > (datetime.now(timezone.utc) + timedelta(hours=24))

    @computed_field
    @property
    def expires_at(self) -> str:
        return (
            datetime.now(timezone.utc) + timedelta(seconds=self.expires_in)
        ).isoformat()

    def __add__(self, other: Union[AccessToken, AuthToken]) -> Self:
        self.access_token = other.access_token or ""
        self.refresh_token = other.refresh_token or ""
        self.token_type = other.token_type or ""
        self.expires_in = other.expires_in or 0
        self.refresh_expires_at = (
            datetime.now(timezone.utc) + timedelta(days=30)
        ).isoformat()
        return self

    @classmethod
    def from_access_token(
        cls,
        *,
        access_token: Union[AccessToken, AuthToken],
        instance_name: str,
        base_url: str,
        use_production: bool,
    ) -> "CurrentAuth":
        return cls(
            instance_name=instance_name,
            access_token=access_token.access_token or "",
            refresh_token=access_token.refresh_token or "",
            token_type=access_token.token_type or "",
            expires_in=access_token.expires_in or 0,
            base_url=base_url,
            from_db=False,
            use_production=use_production,
        )

    @classmethod
    def from_db_row(cls, row: sqlite3.Row) -> "CurrentAuth":
        expires_at_dt = datetime.fromisoformat(row["expires_at"])
        if expires_at_dt.tzinfo is None:
            expires_at_dt = expires_at_dt.replace(tzinfo=timezone.utc)
        now_utc = datetime.now(timezone.utc)
        expires_in = int((expires_at_dt - now_utc).total_seconds())
        return cls(
            instance_name=row["instance_name"],
            access_token=row["access_token"],
            refresh_token=row["refresh_token"],
            token_type=row["token_type"],
            expires_in=max(1, expires_in),
            refresh_expires_at=row["refresh_expires_at"],
            base_url=row["base_url"],
            from_db=True,
            use_production=row["use_production"],
        )

    def to_access_token(self) -> AccessToken:
        return AccessToken(
            access_token=self.access_token,
            refresh_token=self.refresh_token,
            token_type=self.token_type,
            expires_in=self.expires_in,
        )

    def update_refresh_expires_at(
        self, connection: sqlite3.Connection, commit: bool = True
    ):
        connection.execute(
            "UPDATE auth SET refresh_expires_at = ? WHERE instance_name = ?",
            (self.refresh_expires_at, self.instance_name),
        )
        if commit:
            connection.commit()

    def set_token(
        self,
        connection: sqlite3.Connection,
        *,
        new_token: Union[AccessToken, AuthToken] | None = None,
        commit: bool = True,
    ):
        expires_at = (
            datetime.now(timezone.utc)
            + timedelta(seconds=(new_token.expires_in or 0) if new_token else 0)
        ).isoformat()
        refresh_expires_at = (
            datetime.fromisoformat(expires_at) + timedelta(days=30)
        ).isoformat()
        if self.from_db and new_token:
            connection.execute(
                "UPDATE auth SET access_token = ?, token_type = ?, expires_at = ? WHERE current_instance = 1",
                (
                    new_token.access_token,
                    new_token.token_type,
                    expires_at,
                ),
            )
        else:
            connection.execute(
                "INSERT INTO auth (instance_name, access_token, refresh_token, refresh_expires_at, token_type, expires_at, current_instance, base_url, use_production) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    self.instance_name,
                    self.access_token,
                    self.refresh_token,
                    refresh_expires_at,
                    self.token_type,
                    expires_at,
                    1,
                    self.base_url,
                    self.use_production,
                ),
            )
        if commit:
            connection.commit()


class SqlLiteAuth:
    def __init__(self, ctx: LkrCtxObj, db_path: str = "~/.lkr/auth.db"):
        self.db_path = os.path.expanduser(db_path)
        # Ensure the directory exists
        db_dir = os.path.dirname(self.db_path)
        os.makedirs(db_dir, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
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
        self.conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_auth_instance_name ON auth(instance_name)"
        )
        self.conn.commit()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        pass

    def add_auth(
        self,
        instance_name: str,
        base_url: str,
        access_token: Union[AuthToken, AccessToken],
        use_production: bool,
    ):
        self.conn.execute("UPDATE auth SET current_instance = 0")
        CurrentAuth.from_access_token(
            access_token=access_token,
            instance_name=instance_name,
            base_url=base_url,
            use_production=use_production,
        ).set_token(self.conn, commit=False, new_token=access_token)
        self.conn.commit()

    def set_current_instance(self, instance_name: str):
        self.conn.execute(
            "UPDATE auth SET current_instance = CASE WHEN instance_name = ? THEN 1 ELSE 0 END",
            (instance_name,),
        )
        self.conn.commit()

    def _get_current_auth(self) -> CurrentAuth | None:
        cursor = self.conn.execute(
            "SELECT instance_name, access_token, refresh_token, refresh_expires_at, token_type, expires_at, base_url, use_production FROM auth WHERE current_instance = 1"
        )
        row = cursor.fetchone()
        if row:
            return CurrentAuth.from_db_row(row)
        return None

    def get_current_instance(self) -> str | None:
        current_auth = self._get_current_auth()
        if current_auth:
            return current_auth.instance_name
        return None

    def get_current_sdk(self, prompt_refresh_invalid_token: bool = True) -> Looker40SDK:
        current_auth = self._get_current_auth()
        if current_auth:
            if not current_auth.valid_refresh_token:
                from lkr.exceptions import InvalidRefreshTokenError

                if prompt_refresh_invalid_token:
                    self._cli_confirm_refresh_token(current_auth, quiet=True)
                else:
                    raise InvalidRefreshTokenError(current_auth.instance_name)

            def refresh_current_token(token: Union[AccessToken, AuthToken]):
                current_auth.set_token(self.conn, new_token=token, commit=True)

            return init_oauth_sdk(
                current_auth.base_url,
                new_token_callback=refresh_current_token,
                access_token=current_auth.to_access_token(),
            )

        else:
            logger.error("No current instance found, please login")
            raise typer.Exit(1)

    def delete_auth(self, instance_name: str):
        self.conn.execute("DELETE FROM auth WHERE instance_name = ?", (instance_name,))
        self.conn.commit()

    def list_auth(self) -> List[Tuple[str, str, bool, bool]]:
        cursor = self.conn.execute(
            "SELECT instance_name, base_url, current_instance, use_production FROM auth ORDER BY instance_name ASC"
        )
        rows = cursor.fetchall()
        return [
            (
                row["instance_name"],
                row["base_url"],
                row["current_instance"],
                row["use_production"],
            )
            for row in rows
        ]

    def _cli_confirm_refresh_token(self, current_auth: CurrentAuth, quiet: bool = True):
        from typer import confirm

        from lkr.auth.oauth import OAuth2PKCE
        from lkr.exceptions import InvalidRefreshTokenError

        confirmed = (
            True
            if quiet
            else confirm(
                f"Press enter to refresh the token for {current_auth.instance_name}",
                default=True,
            )
        )
        if confirmed:

            def add_auth(token: Union[AccessToken, AuthToken]):
                current_auth + token
                current_auth.update_refresh_expires_at(self.conn, commit=False)
                current_auth.set_token(self.conn, commit=True, new_token=token)

            # Initialize OAuth2 PKCE flow
            oauth = OAuth2PKCE(
                new_token_callback=add_auth, use_production=current_auth.use_production
            )
            login_response = oauth.initiate_login(current_auth.base_url)
            oauth.auth_code = login_response["auth_code"]
            token = oauth.exchange_code_for_token()
            if not token:
                raise InvalidRefreshTokenError(current_auth.instance_name)
            else:
                from lkr.logger import logger

                logger.info(
                    f"Successfully refreshed token for {current_auth.instance_name}"
                )
                return self.get_current_sdk(prompt_refresh_invalid_token=False)


class ApiKeyAuth:
    def __init__(self, api_key: LookerApiKey, use_production: bool):
        self.api_key = api_key
        self.use_production = use_production

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        pass

    def add_auth(
        self,
        instance_name: str,
        base_url: str,
        access_token: Union[AuthToken, AccessToken],
        use_production: bool,
    ):
        raise NotImplementedError("ApiKeyAuth does not support adding auth")

    def delete_auth(self, instance_name: str):
        raise NotImplementedError("ApiKeyAuth does not support deleting auth")

    def list_auth(self) -> List[Tuple[str, str, bool, bool]]:
        raise NotImplementedError("ApiKeyAuth does not support listing auth")

    def set_current_instance(self, instance_name: str):
        raise NotImplementedError(
            "ApiKeyAuth does not support setting current instance"
        )

    def _get_current_auth(self) -> CurrentAuth | None:
        raise NotImplementedError("ApiKeyAuth does not support getting current auth")

    def _cli_confirm_refresh_token(self, current_auth: CurrentAuth, quiet: bool = True):
        raise NotImplementedError(
            "ApiKeyAuth does not support confirming refresh token"
        )

    def get_current_sdk(self, **kwargs) -> Looker40SDK:
        return init_api_key_sdk(self.api_key, self.use_production)

    def get_current_instance(self) -> str | None:
        raise NotImplementedError(
            "ApiKeyAuth does not support getting current instance"
        )
