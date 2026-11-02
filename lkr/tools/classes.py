from typing import Literal, Self, cast

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
    client_id: str | None = Field(default=None, exclude=True)
    client_secret: str | None = Field(default=None, exclude=True)
    base_url: str | None = Field(default=None, exclude=False)
    value: str | None = Field(default=None, exclude=True)
    user_attribute: str | None
    user_attribute_id: str | None = None
    update_type: Literal["group", "default", "user"]
    group_name: str | None = None
    group_id: str | None = None
    looker_user_id: str | None = None
    external_user_id: str | None = None
    email: str | None = None

    @model_validator(mode="after")
    def check_variables(self) -> Self:
        if not (bool(self.user_attribute) or bool(self.user_attribute_id)):
            raise ValueError("Either user_attribute or user_attribute_id must be set")
        if self.update_type == "group" and not (
            bool(self.group_name) or bool(self.group_id)
        ):
            raise ValueError("Either group_name or group_id must be set")
        if self.update_type == "user" and not (
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

    def _get_sdk(self, sdk: Looker40SDK | None = None) -> Looker40SDK | None:
        if sdk is not None:
            return sdk
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
            try:
                user = sdk.user_for_credential("email", self.email)
                if user and user.id:
                    return user.id
            except Exception as e:  # noqa: BLE001
                logger.debug(f"Credential lookup fallback for '{self.email}': {e}")
            users = sdk.search_users(email=self.email, fields="id")
            return getattr(users[0], "id", None) if users else None
        elif self.external_user_id:
            user = sdk.user_for_credential("embed", self.external_user_id)
            return user.id if user else None
        return None

    def _get_group_id(
        self, sdk: Looker40SDK, *, create_if_missing: bool = False
    ) -> str | None:
        if self.group_id:
            return self.group_id
        elif self.group_name:
            groups = sdk.search_groups(name=self.group_name, fields="id")
            if groups:
                return groups[0].id
            if create_if_missing:
                from looker_sdk.sdk.api40.models import WriteGroup

                created = sdk.create_group(body=WriteGroup(name=self.group_name))
                return created.id if created else None
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
                    return str(user_attribute["id"])
        return None

    def ensure_attribute(
        self,
        sdk: Looker40SDK | None = None,
        *,
        label: str | None = None,
        default_value: str | None = None,
        attr_type: str = "string",
    ) -> str:
        resolved = self._get_sdk(sdk)
        if not resolved or not self.user_attribute:
            raise ValueError("SDK and user_attribute are required")
        attr_id = self._get_user_attribute_id(resolved)
        if attr_id:
            curr = resolved.user_attribute(attr_id, "name,label,type,default_value")
            if curr and (
                (default_value is not None and curr.default_value != default_value)
                or (curr.type != attr_type)
            ):
                resolved.update_user_attribute(
                    attr_id,
                    WriteUserAttribute(
                        name=curr.name or self.user_attribute,
                        label=curr.label or label or self.user_attribute,
                        type=attr_type,
                        default_value=(
                            default_value
                            if default_value is not None
                            else curr.default_value
                        ),
                    ),
                )
            return attr_id
        created = resolved.create_user_attribute(
            WriteUserAttribute(
                name=self.user_attribute,
                label=label or self.user_attribute.replace("_", " ").title(),
                type=attr_type,
                default_value=default_value,
                user_can_view=True,
                user_can_edit=False,
                value_is_hidden=False,
            )
        )
        if not created or not created.id:
            raise ValueError(f"Failed to create user attribute '{self.user_attribute}'")
        self.user_attribute_id = str(created.id)
        return self.user_attribute_id

    def delete_attribute(self, sdk: Looker40SDK | None = None) -> bool:
        resolved = self._get_sdk(sdk)
        if not resolved:
            raise ValueError("No SDK found")
        attr_id = self._get_user_attribute_id(resolved)
        if not attr_id:
            return False
        resolved.delete_user_attribute(attr_id)
        return True

    def delete_user_attribute_value(self, sdk: Looker40SDK | None = None):
        sdk = self._get_sdk(sdk)
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

    def update_user_attribute_value(
        self,
        sdk: Looker40SDK | None = None,
        *,
        create_group_if_missing: bool = False,
    ):
        if self.value is None:
            raise ValueError("Value is required to update user attribute")

        sdk = self._get_sdk(sdk)
        if not sdk:
            raise ValueError("No SDK found")
        user_attribute_id = self._get_user_attribute_id(sdk)

        if not user_attribute_id:
            raise ValueError("User attribute not found")
        user_attribute = sdk.user_attribute(user_attribute_id)
        if not user_attribute:
            raise ValueError("User attribute not found")

        if user_attribute.type not in (
            "string",
            "advanced_filter_string",
            "advanced_filter_number",
            "number",
            "datetime",
            "yesno",
            "zipcode",
        ):
            raise ValueError(
                f"Unsupported user attribute type: {user_attribute.type}"
            )

        if self.update_type == "group":
            group_id = self._get_group_id(sdk, create_if_missing=create_group_if_missing)
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
