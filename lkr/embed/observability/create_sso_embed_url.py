from typing import Any, Dict, List, Optional, TypedDict
from uuid import uuid4

from looker_sdk.sdk.api40.methods import Looker40SDK
from looker_sdk.sdk.api40.models import EmbedSsoParams
from pydantic import BaseModel, Field

from lkr.embed.observability.constants import MAX_SESSION_LENGTH, PERMISSIONS


class CreateSSOEmbedUrlParams(BaseModel):
    external_user_id: Optional[str] = Field(description="The external user id to create the sso embed url for", default_factory=lambda: f"embed-observability-{str(uuid4())}")
    external_group_id: Optional[str] = None
    models: Optional[List[str]] = Field(description="The models to create the sso embed url for")
    permissions: Optional[List[str]] = Field(description="The permissions to create the sso embed url for")
    dashboard: Optional[str] = Field(description="The dashboard to create the sso embed url for")
    user_attribute: Optional[List[str]] = Field(description="The user attributes to create the sso embed url for")
    user_timezone: Optional[str] = Field(description="The user timezone to create the sso embed url for")
    group_ids: Optional[List[str]] = Field(description="The group ids to create the sso embed url for")
    embed_domain: Optional[str] = Field(description="The embed domain to create the sso embed url for")

    def to_embed_sso_params(self) -> EmbedSsoParams:
        all_permissions = list(set(PERMISSIONS + (self.permissions or [])))
        return EmbedSsoParams(
            external_user_id=self.external_user_id,
            external_group_id=self.external_group_id,
            models=self.models,
            permissions=all_permissions,
            target_url=f"/embed/dashboards/{self.dashboard}",
        session_length=MAX_SESSION_LENGTH,
        force_logout_login=True,
        first_name=None,
        last_name=None,
        user_timezone=None,
        group_ids=None,
        user_attributes=None,
        embed_domain=None,

        )
class URLResponse(TypedDict):
    url: str
    external_user_id: str
    
def create_sso_embed_url(sdk: Looker40SDK, *, data: Dict[str, Any]) -> URLResponse:
    params = CreateSSOEmbedUrlParams(
        external_user_id=data.get("external_user_id"),
        external_group_id=data.get("external_group_id"),
        models=data.get("models"),
        permissions=data.get("permissions"),
        dashboard=data.get("dashboard"),
    )
    sso_url = sdk.create_sso_embed_url(body=params.to_embed_sso_params())
    return dict(url=sso_url.url, external_user_id=sso_url.external_user_id)