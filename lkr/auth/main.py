import urllib.parse
from typing import Annotated, List

import typer
from looker_sdk.sdk.api40.models import AccessToken
from pick import Option, pick
from rich.console import Console
from rich.table import Table

from lkr.auth.oauth import OAuth2PKCE
from lkr.auth_service import SqlLiteAuth

__all__ = ["group"]

group = typer.Typer(name="auth", help="Authentication commands for LookML Repository")

@group.command()
def login():
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
    auth = SqlLiteAuth()
    def add_auth(token: AccessToken):
        auth.add_auth(instance_name, origin, token)
    # Initialize OAuth2 PKCE flow
    oauth = OAuth2PKCE(new_token_callback=add_auth)

    # Open browser for authentication and wait for callback
    typer.echo(f"Opening browser for authentication at {origin + '/auth'}...")

    login_response = oauth.initiate_login(origin)
    if login_response["auth_code"]:
        typer.echo("Successfully received authorization code!")
        try:
            # Store the auth code in the OAuth instance
            oauth.auth_code = login_response["auth_code"]
            # Exchange the code for tokens
            token = oauth.exchange_code_for_token()
            if token:
                typer.echo("Successfully authenticated!")
            else:
                typer.echo("Failed to exchange authorization code for tokens", err=True)
                raise typer.Exit(1)
        except Exception as e:
            typer.echo(
                f"Failed to exchange authorization code for tokens: {str(e)}", err=True
            )
            raise typer.Exit(1)
    else:
        typer.echo("Failed to receive authorization code", err=True)
        raise typer.Exit(1)


@group.command()
def logout(
    instance_name: Annotated[
        str | None,
        typer.Option(
            help="Name of the Looker instance to logout from. If not provided, logs out from all instances."
        ),
    ] = None,
):
    """
    Logout and clear saved credentials
    """
    if instance_name:
        message = f"Are you sure you want to logout from instance '{instance_name}'?"
    else:
        message = "Are you sure you want to logout from all instances?"

    if not typer.confirm(message):
        typer.echo("Logout cancelled")
        raise typer.Exit()

    if instance_name:
        typer.echo(f"Logging out from instance: {instance_name}")
    else:
        typer.echo("Logging out from all instances...")
    # TODO: Implement actual logout logic
    typer.echo("Logged out successfully!")


@group.command()
def whoami(ctx: typer.Context):
    """
    Check current authentication
    """
    with SqlLiteAuth() as auth:
        sdk = auth.get_current_sdk(prompt_refresh_invalid_token=True)
        if not sdk:
            typer.echo(
                "Not currently authenticated - use `lkr auth login` or `lkr auth switch` to authenticate",
                err=True,
            )
            raise typer.Exit(1)
        user = sdk.me()
        typer.echo(
            f"Currently authenticated as {user.first_name} {user.last_name} ({user.email}) to {sdk.auth.settings.base_url}"
        )


@group.command()
def switch(
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
    with SqlLiteAuth() as auth:
        all_instances = auth.list_auth()
        if not all_instances:
            typer.echo("No authenticated instances found", err=True)
            raise typer.Exit(1)

        if instance_name:
            # If instance name provided, verify it exists
            instance_names = [name for name, url, current in all_instances]
            if instance_name not in instance_names:
                typer.echo(f"Instance '{instance_name}' not found", err=True)
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
        # Switch to selected instance
        auth.set_current_instance(picked.value)
        sdk = auth.get_current_sdk()
        user = sdk.me()
        typer.echo(
            f"Successfully switched to {picked.value} ({sdk.auth.settings.base_url}) as {user.first_name} {user.last_name} ({user.email})"
        )


@group.command()
def list():
    """
    List all authenticated Looker instances
    """
    console = Console()
    with SqlLiteAuth() as auth:
        all_instances = auth.list_auth()
        if not all_instances:
            typer.echo("No authenticated instances found", err=True)
            raise typer.Exit(1)
        table = Table(" ", "Instance", "URL")
        for instance in all_instances:
            table.add_row("*" if instance[2] else " ", instance[0], instance[1])
        console.print(table)


if __name__ == "__main__":
    group()
