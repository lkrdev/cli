from typing import Callable, Union

from looker_sdk.rtl.auth_token import AccessToken, AuthToken

NewTokenCallback = Callable[[Union[AuthToken, AccessToken]], None]
