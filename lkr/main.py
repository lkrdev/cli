import os

import typer

from lkr.auth.main import group as auth_group
from lkr.classes import LkrCtxObj

app = typer.Typer(name="lkr", help="LookML Repository CLI")

app.add_typer(auth_group, name="auth")

@app.callback()
def callback(
    ctx: typer.Context,
    client_id: str = typer.Option(None, envvar="LOOKERSDK_CLIENT_ID"),
    client_secret: str = typer.Option(None, envvar="LOOKERSDK_CLIENT_SECRET"),
    base_url: str = typer.Option(None, envvar="LOOKERSDK_BASE_URL"),
):
    if client_id:
        os.environ["LOOKERSDK_CLIENT_ID"] = client_id
    if client_secret:
        os.environ["LOOKERSDK_CLIENT_SECRET"] = client_secret
    if base_url:
        os.environ["LOOKERSDK_BASE_URL"] = base_url
    # Initialize ctx.obj as a dictionary if it's None
    if ctx.obj is None:
        ctx.obj = {}
    ctx.obj['ctx_lkr'] = LkrCtxObj()

if __name__ == "__main__":
    app()

