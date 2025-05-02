import urllib.parse
from typing import Annotated, List, Union, cast

import typer
from looker_sdk.rtl.auth_token import AccessToken, AuthToken
from pick import Option, pick
from pydash import get
from rich.console import Console
from rich.table import Table

from lkr.auth.oauth import OAuth2PKCE
from lkr.auth_service import get_auth
from lkr.logging import logger

__all__ = ["group"]

group = typer.Typer(name="auth", help="Authentication commands for LookML Repository")

@group.callback()
def callback(ctx: typer.Context):
    if ctx.invoked_subcommand == "whoami":
        return
    if ctx.obj['ctx_lkr'].use_sdk == "api_key":
        logger.error("API key authentication is not supported for auth commands")
        raise typer.Exit(1)

@group.command()
def login(ctx: typer.Context):
    """
    Login to Looker instance using OAuth2 PKCE flow
    """

    base_url = typer.prompt("Enter your Looker instance base URL")
    if not base_url.startswith("http"):
        base_url = f"https://{base_url}"
    # Parse the URL and reconstruct it to get the origin (scheme://hostname[:port])
    parsed_url = urllib.parse.urlparse(base_url)
    origin = urllib.parse.urlunparse(
        (parsed_url.scheme, parsed_url.netloc, "", "", "", "")
    )
    instance_name = typer.prompt(
        "Enter a name for this Looker instance", default=parsed_url.netloc
    )
    auth = get_auth(ctx)
    def add_auth(token: Union[AuthToken, AccessToken]):
        auth.add_auth(instance_name, origin, token)
    # Initialize OAuth2 PKCE flow
    oauth = OAuth2PKCE(new_token_callback=add_auth)

    # Open browser for authentication and wait for callback
    logger.info(f"Opening browser for authentication at {origin + '/auth'}...")

    login_response = oauth.initiate_login(origin)
    if login_response["auth_code"]:
        logger.info("Successfully received authorization code!")
        try:
            # Store the auth code in the OAuth instance
            oauth.auth_code = login_response["auth_code"]
            # Exchange the code for tokens
            token = oauth.exchange_code_for_token()
            if token:
                logger.info("Successfully authenticated!")
            else:
                logger.error("Failed to exchange authorization code for tokens")
                raise typer.Exit(1)
        except Exception as e:
            logger.error(f"Failed to exchange authorization code for tokens: {str(e)}")
            raise typer.Exit(1)
    else:
        logger.error("Failed to receive authorization code")
        raise typer.Exit(1)


@group.command()
def logout(
    ctx: typer.Context,
    instance_name: Annotated[
        str | None,
        typer.Option(
            help="Name of the Looker instance to logout from. If not provided, logs out from all instances."
        ),
    ] = None,
    all: Annotated[
        bool,
        typer.Option(
            "--all", help="Logout from all instances"
        ),
    ] = False,
):
    """
    Logout and clear saved credentials
    """
    auth = get_auth(ctx)
    if instance_name:
        message = f"Are you sure you want to logout from instance '{instance_name}'?"
    elif all:
        message = "Are you sure you want to logout from all instances?"
    else:
        instance_name = auth.get_current_instance()
        if not instance_name:
            logger.error("No instance currently authenticated")
            raise typer.Exit(1)
        message = f"Are you sure you want to logout from instance '{instance_name}'?"

    if not typer.confirm(message, default=False):
        logger.info("Logout cancelled")
        raise typer.Exit()

    if instance_name:   
        logger.info(f"Logging out from instance: {instance_name}")
        auth.delete_auth(instance_name=instance_name)
    else:
        logger.info("Logging out from all instances...")
        all_instances = auth.list_auth()
        for instance in all_instances:
            auth.delete_auth(instance_name=instance[0])
    logger.info("Logged out successfully!")


@group.command()
def whoami(ctx: typer.Context):
    """
    Check current authentication
    """
    auth = get_auth(ctx)
    sdk = auth.get_current_sdk(prompt_refresh_invalid_token=True)
    if not sdk:
        logger.error(
            "Not currently authenticated - use `lkr auth login` or `lkr auth switch` to authenticate"
        )
        raise typer.Exit(1)
    user = sdk.me()
    logger.info(
        f"Currently authenticated as {user.first_name} {user.last_name} ({user.email}) to {sdk.auth.settings.base_url}"
    )


@group.command()
def switch(
    ctx: typer.Context,
    instance_name: Annotated[
        str | None,
        typer.Option(
            "-I", "--instance-name", help="Name of the Looker instance to switch to"
        ),
    ] = None,
):
    """
    Switch to a different authenticated Looker instance
    """
    auth = get_auth(ctx)
    all_instances = auth.list_auth()
    if not all_instances:
        logger.error("No authenticated instances found")
        raise typer.Exit(1)
    
    if instance_name:
        # If instance name provided, verify it exists
        instance_names = [name for name, url, current in all_instances]
        if instance_name not in instance_names:
            logger.error(f"Instance '{instance_name}' not found")
            raise typer.Exit(1)
    else:
        # If no instance name provided, show selection menu
        current_index = 0
        instance_names = []
        options: List[Option] = []
        max_name_length = 0
        for index, (name, _, current) in enumerate(all_instances):
            if current:
                current_index = index
            max_name_length = max(max_name_length, len(name))
            instance_names.append(name)
        options = [
            Option(label=f"{name:{max_name_length}} ({url})", value=name)
            for name, url, _ in all_instances
        ]

        picked = pick(
            options,
            "Select instance to switch to",
            min_selection_count=1,
            default_index=current_index,
            clear_screen=False,
        )[0]
        instance_name = cast(str, get(picked, "value"))
    # Switch to selected instance
    auth.set_current_instance(instance_name)
    sdk = auth.get_current_sdk()
    if not sdk:
        logger.error("No looker instance currently authenticated")
        raise typer.Exit(1)
    user = sdk.me()
    logger.info(
        f"Successfully switched to {instance_name} ({sdk.auth.settings.base_url}) as {user.first_name} {user.last_name} ({user.email})"
    )


@group.command()
def list(ctx: typer.Context):
    """
    List all authenticated Looker instances
    """
    console = Console()
    auth = get_auth(ctx)
    all_instances = auth.list_auth()
    if not all_instances:
        logger.error("No authenticated instances found")
        raise typer.Exit(1)
    table = Table(" ", "Instance", "URL")
    for instance in all_instances:
        table.add_row("*" if instance[2] else " ", instance[0], instance[1])
    console.print(table)


if __name__ == "__main__":
    group()
