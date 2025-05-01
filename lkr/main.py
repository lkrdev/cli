
import typer

from lkr.auth.main import group as auth_group

app = typer.Typer(name="lkr", help="LookML Repository CLI")

app.add_typer(auth_group, name="auth")

if __name__ == "__main__":
    app()

