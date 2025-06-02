from datetime import datetime, timezone
from typing import Annotated, Any, Dict, List, MutableMapping, Optional
from urllib.parse import urljoin

import typer
from fastapi import HTTPException
from looker_sdk.sdk.api40.methods import LookerSDK
from looker_sdk.sdk.api40.models import EmbedSsoParams
from pydantic import BaseModel, ConfigDict, Field

from lkr.logger import structured_logger

DEFAULT_PERMISSIONS = [
    "access_data",
    "see_user_dashboards",
    "see_lookml_dashboards",
    "see_looks",
    "explore",
]


def now():
    return datetime.now(timezone.utc)


class EmbedSDKObj(BaseModel):
    dashboard_id: str = Field(description="The id of the dashboard to check against")
    external_user_id: str = Field(description="The external user id")
    session_length: int = Field(
        default=10 * 60 * 50, description="The length of the session in seconds"
    )  # 10 minutes
    first_name: str | None = Field(
        default=None, description="The first name of the user"
    )
    last_name: str | None = Field(default=None, description="The last name of the user")
    user_timezone: str | None = Field(
        default=None, description="The timezone of the user"
    )
    permissions: Annotated[
        List[str], Field(description="The permissions of the user")
    ] = DEFAULT_PERMISSIONS
    models: Annotated[List[str], Field(description="The models of the user")] = []
    group_ids: Annotated[List[str], Field(description="The group ids of the user")] = []
    external_group_id: Optional[str] = Field(
        default=None, description="The external group id of the user"
    )
    user_attributes: MutableMapping[str, str] = {}
    secret_id: Optional[str] = Field(
        default=None, description="The secret id of the user"
    )

    def to_embed_sso_params(self, embed_domain: str, base_url: str) -> EmbedSsoParams:
        path = f"/embed/dashboards/{self.dashboard_id}"
        target_url = urljoin(base_url, path) + "?embed_domain=" + embed_domain
        return EmbedSsoParams(
            embed_domain=embed_domain,
            target_url=target_url,
            session_length=self.session_length,
            external_user_id=self.external_user_id,
            first_name=self.first_name,
            last_name=self.last_name,
            user_timezone=self.user_timezone,
            permissions=self.permissions,
            models=self.models,
            group_ids=self.group_ids,
            force_logout_login=True,
        )


class LogEvent(BaseModel):
    event_type: str
    event_at: datetime = Field(
        default_factory=now, description="The time the event occurred"
    )
    time_since_start: float = Field(
        default=0, description="The time since the session started"
    )
    payload: dict[str, Any]
    session_id: str
    last_event_type: str | None = None
    last_event_at: datetime | None = None
    time_since_last_event: float | None = None
    external_user_id: str
    dashboard_id: str


class ObservabilityCtxObj(BaseModel):
    event_prefix: str = Field(
        default="lkr-observability", description="The prefix of the event", min_length=1
    )
    model_config = ConfigDict(arbitrary_types_allowed=True)
    sdk: LookerSDK | None = Field(
        default=None, description="The SDK to use for the observability", exclude=True
    )
    base_url: str | None = Field(
        default=None, description="The base url of the looker instance"
    )
    events: Dict[str, List[LogEvent]] = dict()
    start_at: Dict[str, datetime] = dict()
    timeout: int = 5 * 60  # 5 minutes
    origin: str = Field(default="", description="The origin of the request")
    external_user_id: str | None = None
    dashboard_id: str | None = None

    def initialize(
        self,
        ctx: typer.Context,
        *,
        event_prefix: str,
        port: int,
        host: str,
        timeout: int | None = None,
    ):
        from lkr.auth_service import get_auth

        auth = get_auth(ctx)
        self.sdk = auth.get_current_sdk()

        if not self.sdk:
            structured_logger.error("No SDK found")
            raise HTTPException(status_code=500, detail="No SDK found")
        self.base_url = self.sdk.auth.settings.base_url
        self.origin = f"http://{host}:{port}"
        if timeout:
            self.timeout = timeout
        if event_prefix:
            self.event_prefix = event_prefix

    def log_event(self, event: dict[str, Any], event_type: str, session_id: str):
        if session_id not in self.events:
            self.events[session_id] = []
            self.start_at[session_id] = now()
        event_at = now()
        e = LogEvent(
            event_type=":".join([self.event_prefix, event_type]),
            event_at=event_at,
            time_since_start=float(
                (event_at - self.start_at[session_id]).total_seconds()
            ),
            payload=event,
            session_id=session_id,
            external_user_id=self.external_user_id or "",
            dashboard_id=self.dashboard_id or "",
        )
        try:
            last_event = self.events[session_id][-1]
        except IndexError:
            last_event = None
        if last_event:
            e.last_event_type = last_event.event_type
            e.last_event_at = last_event.event_at
            e.time_since_last_event = float(
                (event_at - last_event.event_at).total_seconds()
            )

        structured_logger.info(event_type, **e.model_dump(mode="json"))

        self.events[session_id].append(e)

    def get_events(self, session_id: str):
        events = self.events.pop(session_id, [])
        return [e.model_dump(mode="json") for e in events]


class IframeRequestEvent(BaseModel):
    event_type: str
    event_data: dict[str, Any]
    timestamp: datetime
