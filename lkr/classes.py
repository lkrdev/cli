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
                client_id=os.getenv("LOOKERSDK_CLIENT_ID"),
                client_secret=os.getenv("LOOKERSDK_CLIENT_SECRET"),
                base_url=os.getenv("LOOKERSDK_BASE_URL"),
            )
        except Exception:
            return None

        
class LkrCtxObj(BaseModel):
    api_key: LookerApiKey | None

    @property
    def use_sdk(self) -> Literal["oauth", "api_key"]:
        return "oauth" if not self.api_key else "api_key"
    
    def __init__(self, api_key: LookerApiKey | None = None, *args, **kwargs):
        super().__init__(api_key=api_key, *args, **kwargs)
        if not self.api_key:
            self.api_key = LookerApiKey.from_env()
