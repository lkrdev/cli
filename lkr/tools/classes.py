from typing import Literal, Optional, Self, cast

from looker_sdk.sdk.api40.methods import Looker40SDK
from looker_sdk.sdk.api40.models import (
    UserAttributeGroupValue,
    WriteUserAttribute,
    WriteUserAttributeWithValue,
)
from pydantic import BaseModel, Field, model_validator

from lkr.auth_service import init_api_key_sdk
from lkr.classes import LookerApiKey
from lkr.logger import logger


class UserAttributeUpdater(BaseModel):
    client_id: Optional[str] = Field(default=None, exclude=True)
    client_secret: Optional[str] = Field(default=None, exclude=True)
    base_url: Optional[str] = Field(default=None, exclude=False)
    value: Optional[str] = Field(default=None, exclude=True)
    user_attribute: Optional[str]
    user_attribute_id: Optional[str] = None
    update_type: Literal["group", "default", "user"]
    group_name: Optional[str] = None
    group_id: Optional[str] = None
    looker_user_id: Optional[str] = None
    external_user_id: Optional[str] = None
    email: Optional[str] = None

    @model_validator(mode="after")
    def check_variables(self) -> Self:
        if not (bool(self.user_attribute) or bool(self.user_attribute_id)):
            raise ValueError("Either user_attribute or user_attribute_id must be set")
        if self.update_type == "group":
            if not (bool(self.group_name) or bool(self.group_id)):
                raise ValueError("Either group_name or group_id must be set")
        if self.update_type == "user":
            if not (
                bool(self.looker_user_id)
                or bool(self.external_user_id)
                or bool(self.email)
            ):
                raise ValueError(
                    "Either looker_user_id, external_user_id, or email must be set"
                )
        return self

    def get_request_authorization_for_value(self, headers: list[tuple[str, str]]):
        authorization_token = next(
            (header for header in headers if header[0] == "Authorization"), None
        )
        if authorization_token:
            self.value = authorization_token[1]
        else:
            logger.error("No authorization token found")

    def _get_sdk(self):
        api_key: LookerApiKey | None = None
        if self.client_id and self.client_secret and self.base_url:
            api_key = LookerApiKey(
                client_id=self.client_id,
                client_secret=self.client_secret,
                base_url=self.base_url,
            )
        else:
            api_key = LookerApiKey.from_env()
        if not api_key:
            logger.error("No API key found")
            return None
        return init_api_key_sdk(api_key, True)

    def _get_looker_user_id(self, sdk: Looker40SDK) -> str | None:
        if self.looker_user_id:
            return self.looker_user_id
        elif self.email:
            user = sdk.user_for_credential("email", self.email)
            return user.id if user else None
        elif self.external_user_id:
            user = sdk.user_for_credential("embed", self.external_user_id)
            return user.id if user else None
        return None

    def _get_group_id(self, sdk: Looker40SDK) -> str | None:
        if self.group_id:
            return self.group_id
        elif self.group_name:
            groups = sdk.search_groups(name=self.group_name, fields="id")
            if groups:
                return groups[0].id
        return None

    def _get_user_attribute_id(self, sdk: Looker40SDK) -> str | None:
        if self.user_attribute_id:
            return self.user_attribute_id
        elif self.user_attribute:
            user_attributes = cast(
                list[dict], sdk.get("/user_attributes", structure=list[dict])
            )
            for user_attribute in user_attributes or []:
                if user_attribute["name"] == self.user_attribute:
                    return user_attribute["id"]
        return None

    def delete_user_attribute_value(self):
        sdk = self._get_sdk()
        if not sdk:
            raise ValueError("No SDK found")
        user_attribute_id = self._get_user_attribute_id(sdk)
        if not user_attribute_id:
            raise ValueError("User attribute not found")

        if self.update_type == "group":
            group_id = self._get_group_id(sdk)
            if group_id:
                sdk.delete_user_attribute_group_value(
                    group_id=group_id,
                    user_attribute_id=user_attribute_id,
                )
            else:
                raise ValueError("Group not found")
        elif self.update_type == "default":
            user_attribute = sdk.user_attribute(user_attribute_id, "name,label,type")
            sdk.update_user_attribute(
                user_attribute_id,
                WriteUserAttribute(
                    default_value=None,
                    name=user_attribute.name,
                    label=user_attribute.label,
                    type=user_attribute.type,
                ),
            )
        elif self.update_type == "user":
            looker_user_id = self._get_looker_user_id(sdk)
            if not looker_user_id:
                raise ValueError("User not found")
            sdk.delete_user_attribute_user_value(
                user_id=looker_user_id,
                user_attribute_id=user_attribute_id,
            )

    def update_user_attribute_value(self):
        if not self.value:
            raise ValueError("Value is required to update user attribute")

        sdk = self._get_sdk()
        if not sdk:
            raise ValueError("No SDK found")
        user_attribute_id = self._get_user_attribute_id(sdk)

        if not user_attribute_id:
            raise ValueError("User attribute not found")
        user_attribute = sdk.user_attribute(user_attribute_id)
        if not user_attribute:
            raise ValueError("User attribute not found")

        if user_attribute.type != "string":
            raise ValueError("User attribute is not a string")

        if self.update_type == "group":
            group_id = self._get_group_id(sdk)
            if group_id:
                sdk.update_user_attribute_group_value(
                    group_id=group_id,
                    user_attribute_id=user_attribute_id,
                    body=UserAttributeGroupValue(
                        group_id=group_id,
                        user_attribute_id=user_attribute_id,
                        value=self.value,
                    ),
                )
            else:
                raise ValueError("Group not found")
        elif self.update_type == "default":
            sdk.update_user_attribute(
                user_attribute_id,
                WriteUserAttribute(
                    name=user_attribute.name,
                    label=user_attribute.label,
                    type=user_attribute.type,
                    default_value=self.value,
                ),
            )
        elif self.update_type == "user":
            looker_user_id = self._get_looker_user_id(sdk)
            if not looker_user_id:
                raise ValueError("User not found")
            sdk.set_user_attribute_user_value(
                user_id=looker_user_id,
                user_attribute_id=user_attribute_id,
                body=WriteUserAttributeWithValue(
                    value=self.value,
                ),
            )


class AttributeUpdaterResponse(BaseModel):
    success: bool = False
    message: str
