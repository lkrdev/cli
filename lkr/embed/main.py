from typing import Annotated

import typer

from lkr.auth_service import get_auth
from lkr.embed.observability.embed_server import run_server

__all__ = ["group"]

group = typer.Typer(name="embed", help="Embed commands for LookML Repository")


@group.command()
def observability(
    ctx: typer.Context,
    port: Annotated[
        int, typer.Option("--port", help="Port to run the API on", envvar="PORT")
    ] = 8080,
    log_event_prefix: Annotated[
        str, typer.Option("--log-event-prefix", help="Prefix to use for the log events")
    ] = "lkr:embed:observability",
):
    """
    Spin up an API to do embed observability. **Important:** requires a user with the `admin` role. This will create
    an endpoint where you can send embed user properties to it, it will create the sso embed url, then load it up into a selenium
    browser. The browser will log the user in using the sso embed url, then it will navigate to the dashboard and start the observability tests. It will log structured payloads
    with metadata in each step. You can then ingest these using tools your of choice
    """
    sdk = get_auth(ctx).get_current_sdk()

    run_server(sdk=sdk, port=port, log_event_prefix=log_event_prefix)
