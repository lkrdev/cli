import os

OAUTH_CLIENT_ID = "lkr-cli"
LOOKER_API_VERSION = "4.0"
OAUTH_REDIRECT_URI = os.getenv(
    "LKR_OAUTH_REDIRECT_URI", "https://www.lkr.dev/oauth/callback/"
)