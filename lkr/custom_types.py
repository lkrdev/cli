from collections.abc import Callable
from enum import Enum

from looker_sdk.rtl.auth_token import AccessToken, AuthToken

NewTokenCallback = Callable[[AuthToken | AccessToken], None]

class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
