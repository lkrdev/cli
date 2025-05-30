import os
from typing import Literal

from pydantic import BaseModel, Field


class LookerApiKey(BaseModel):
    client_id: str = Field(..., min_length=1)
    client_secret: str = Field(..., min_length=1)
    base_url: str = Field(..., min_length=1)

    @classmethod
    def from_env(cls):
        try:
            return cls(
                client_id=os.environ.get("LOOKERSDK_CLIENT_ID"),  # type: ignore
                client_secret=os.environ.get("LOOKERSDK_CLIENT_SECRET"),  # type: ignore
                base_url=os.environ.get("LOOKERSDK_BASE_URL"),  # type: ignore
            )
        except Exception:
            return None


class LkrCtxObj(BaseModel):
    api_key: LookerApiKey | None
    force_oauth: bool = False
    use_production: bool = True

    @property
    def use_sdk(self) -> Literal["oauth", "api_key"]:
        if self.force_oauth:
            return "oauth"
        return "api_key" if self.api_key else "oauth"

    def __init__(self, api_key: LookerApiKey | None = None, *args, **kwargs):
        super().__init__(api_key=api_key, *args, **kwargs)
        if not self.api_key:
            self.api_key = LookerApiKey.from_env()
