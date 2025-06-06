import typer
import uvicorn
from fastapi import FastAPI, Request

from lkr.tools.classes import AttributeUpdaterResponse, UserAttributeUpdater

__all__ = ["group"]

group = typer.Typer()


@group.command()
def user_attribute_updater(
    ctx: typer.Context,
    host: str = typer.Option(default="127.0.0.1", envvar="HOST"),
    port: int = typer.Option(default=8080, envvar="PORT"),
):
    api = FastAPI()

    @api.post("/identity_token")
    def identity_token(request: Request, body: UserAttributeUpdater):
        try:
            body.get_request_authorization_for_value(request)
            body.update_user_attribute_value()
            return AttributeUpdaterResponse(
                success=True, message="User attribute updated"
            )
        except Exception as e:
            return AttributeUpdaterResponse(success=False, message=str(e))

    @api.delete("/value")
    def delete_user_attribute_value(request: Request, body: UserAttributeUpdater):
        try:
            body.delete_user_attribute_value()
            return AttributeUpdaterResponse(
                success=True, message="User attribute value deleted"
            )
        except Exception as e:
            return AttributeUpdaterResponse(success=False, message=str(e))

    @api.post("/value")
    def update_user_attribute_value(request: Request, body: UserAttributeUpdater):
        try:
            body.update_user_attribute_value()
            return AttributeUpdaterResponse(
                success=True, message="User attribute value updated"
            )
        except Exception as e:
            return AttributeUpdaterResponse(success=False, message=str(e))

    uvicorn.run(api, host=host, port=port)


if __name__ == "__main__":
    group()
