from enum import Enum
from typing import Callable, Union

from looker_sdk.rtl.auth_token import AccessToken, AuthToken

NewTokenCallback = Callable[[Union[AuthToken, AccessToken]], None]

class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
