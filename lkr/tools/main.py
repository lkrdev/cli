import os

import typer
import uvicorn
from fastapi import FastAPI, Request

from lkr.logger import structured_logger as logger
from lkr.tools.classes import AttributeUpdaterResponse, UserAttributeUpdater

__all__ = ["group"]

group = typer.Typer()

if not logger:
    raise Exception("Logger is not available")


@group.command()
def user_attribute_updater(
    host: str = typer.Option(default="127.0.0.1", envvar="HOST"),
    port: int = typer.Option(default=8080, envvar="PORT"),
):
    api = FastAPI()

    @api.post("/identity_token")
    def identity_token(request: Request, body: UserAttributeUpdater):
        try:
            body.get_request_authorization_for_value(request.headers.items())
            body.update_user_attribute_value()
            raw_urls = os.getenv("LOOKER_WHITELISTED_BASE_URLS", "")
            whitelisted_base_urls = (
                [url.strip() for url in raw_urls.split(",") if url.strip()]
                if raw_urls
                else []
            )
            logger.debug(
                "identify_token_user_attribute",
                **body.model_dump(),
                whitelisted_base_urls=whitelisted_base_urls,
            )

            if body.base_url not in whitelisted_base_urls:
                raise Exception(f"Base URL {body.base_url} not whitelisted")

            return AttributeUpdaterResponse(
                success=True, message="User attribute updated"
            )
        except Exception as e:
            return AttributeUpdaterResponse(success=False, message=str(e))

    @api.delete("/value")
    def delete_user_attribute_value(request: Request, body: UserAttributeUpdater):
        try:
            body.delete_user_attribute_value()
            logger.debug(
                "user_attribute_delete",
                **body.model_dump(),
            )
            return AttributeUpdaterResponse(
                success=True, message="User attribute value deleted"
            )
        except Exception as e:
            return AttributeUpdaterResponse(success=False, message=str(e))

    @api.post("/value")
    def update_user_attribute_value(request: Request, body: UserAttributeUpdater):
        try:
            body.update_user_attribute_value()
            logger.debug(
                "user_attribute_update",
                **body.model_dump(),
            )
            return AttributeUpdaterResponse(
                success=True, message="User attribute value updated"
            )
        except Exception as e:
            return AttributeUpdaterResponse(success=False, message=str(e))

    @api.get("")
    def health():
        return {"status": "ok"}

    uvicorn.run(api, host=host, port=port)


if __name__ == "__main__":
    group()
