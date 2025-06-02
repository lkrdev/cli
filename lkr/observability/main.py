import json
import os
from typing import Annotated
from urllib.parse import quote
from uuid import uuid4

import typer
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydash import get
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from lkr.logger import structured_logger
from lkr.observability.classes import (
    EmbedSDKObj,
    IframeRequestEvent,
    ObservabilityCtxObj,
)

app = FastAPI(title="observability")

DEFAULT_PERMISSIONS = set(
    [
        "access_data",
        "see_user_dashboards",
        "see_lookml_dashboards",
        "see_looks",
        "explore",
    ]
)


observability_ctx = ObservabilityCtxObj()


def get_embed_sdk_obj(
    dashboard_id: str = Query(...),
    external_user_id: str = Query(...),
    group_ids: list[str] = Query(default=[]),
    permissions: list[str] = Query(default=list(DEFAULT_PERMISSIONS)),
    models: list[str] = Query(default=[]),
    session_length: int = Query(default=10 * 60 * 50),
    first_name: str = Query(default=None),
    last_name: str = Query(default=None),
    user_timezone: str = Query(default=None),
    user_attributes: str = Query(default="{}"),
    secret_id: str = Query(default=None),
):
    try:
        user_attributes_dict = json.loads(user_attributes)
    except json.JSONDecodeError as e:
        structured_logger.error(
            "JSONDecodeError: Invalid user attributes",
            error=str(e),
            user_attributes=user_attributes,
        )
        return None
    except Exception:
        return None
    return EmbedSDKObj(
        dashboard_id=dashboard_id,
        external_user_id=external_user_id,
        group_ids=group_ids,
        permissions=permissions,
        models=models,
        session_length=session_length,
        first_name=first_name,
        last_name=last_name,
        user_timezone=user_timezone,
        user_attributes=user_attributes_dict,
        secret_id=secret_id,
    )


@app.post("/log_event")
def log_event(body: IframeRequestEvent, session_id: str = Query(...)):
    observability_ctx.log_event(
        body.model_dump(mode="json"), body.event_type, session_id
    )


@app.get("/settings")
def settings():
    if not observability_ctx.sdk:
        raise HTTPException(status_code=500, detail="No SDK found")
    else:
        settings = observability_ctx.sdk.get_setting("embed_config")
        if not settings.embed_config:
            raise HTTPException(status_code=500, detail="No embed config found")
        else:
            embed_domain_ok = (
                observability_ctx.origin in list(settings.embed_config.domain_allowlist)
                if settings.embed_config.domain_allowlist
                else False
            )
            if not embed_domain_ok:
                return JSONResponse(
                    content=dict(
                        embed_domain=observability_ctx.origin,
                        domain_allowlist=settings.embed_config.domain_allowlist,
                        ok=False,
                        message="Embed domain not in allowlist",
                    ),
                    status_code=400,
                )
            elif not settings.embed_config.embed_enabled:
                return JSONResponse(
                    content=dict(
                        embed_domain=observability_ctx.origin,
                        domain_allowlist=settings.embed_config.domain_allowlist,
                        ok=False,
                        message="Embed is not enabled",
                    ),
                    status_code=400,
                )
            else:
                return JSONResponse(
                    content=dict(
                        embed_domain=observability_ctx.origin,
                        domain_allowlist=settings.embed_config.domain_allowlist,
                        ok=True,
                    ),
                    status_code=200,
                )


@app.get("/health")
def health_check(
    request: Request,
    params: EmbedSDKObj | None = Depends(get_embed_sdk_obj),
    open: bool = Query(default=False),
):
    """
    Launch a headless browser, open the embed container, and wait for the completion indicator.
    Returns health status and timing info.
    """
    if not params:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid parameters: {str(request.query_params)}",
        )
    session_id = str(uuid4())
    redirect = False
    observability_ctx.external_user_id = params.external_user_id
    observability_ctx.dashboard_id = params.dashboard_id
    driver: WebDriver | None = None
    if not observability_ctx.sdk:
        raise HTTPException(status_code=500, detail="No SDK found")
    try:
        observability_ctx.log_event(
            params.model_dump(mode="json"), "health_check_start", session_id
        )
        chrome_options = Options()
        chrome_options.set_capability("goog:loggingPrefs", {"browser": "ALL"})
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--enable-logging")
        chrome_options.add_argument("--v=1")

        chrome_options.add_experimental_option(
            "prefs",
            {
                "profile.default_content_settings.cookies": 1,
                "profile.cookie_controls_mode": 0,
            },
        )
        driver = webdriver.Chrome(options=chrome_options)
        url = observability_ctx.sdk.create_sso_embed_url(
            body=params.to_embed_sso_params(
                observability_ctx.origin, observability_ctx.base_url or ""
            )
        )
        observability_ctx.log_event(
            {"sso_url": url.url}, "create_sso_embed_url", session_id
        )

        if not (url and url.url):
            raise HTTPException(status_code=500, detail="No URL found")
        if open:
            redirect = True
            return RedirectResponse(url=url.url)
        else:
            quoted_url = quote(url.url, safe="")
            embed_url = f"{observability_ctx.origin}/?iframe_url={quoted_url}&session_id={session_id}"
            driver.get(embed_url)
            observability_ctx.log_event(
                {"url": embed_url}, "chromium_driver_get", session_id
            )
            WebDriverWait(driver, observability_ctx.timeout).until(
                EC.presence_of_element_located((By.ID, "completion-indicator"))
            )
            observability_ctx.log_event(
                {"session_id": session_id}, "chromium_driver_get_complete", session_id
            )

    except TimeoutException:
        observability_ctx.log_event(
            {
                **params.model_dump(mode="json"),
                "error": f"Timed out: {observability_ctx.timeout}",
            },
            "health_check_timeout",
            session_id,
        )
        settings = observability_ctx.sdk.get_setting("embed_config")
        if observability_ctx.origin not in get(
            settings, ["embed_config", "domain_allowlist"], []
        ):
            observability_ctx.log_event(
                {
                    **params.model_dump(mode="json"),
                    "error": "Embed domain not in allowlist",
                },
                "health_check_error",
                session_id,
            )
    except Exception as e:
        observability_ctx.log_event(
            {**params.model_dump(mode="json"), "error": str(e)},
            "health_check_error",
            session_id,
        )
    finally:
        observability_ctx.log_event(
            {"session_id": session_id}, "health_check_complete", session_id
        )
        if driver:
            driver.quit()
        if not redirect:
            return observability_ctx.get_events(session_id)


@app.get("/", response_class=HTMLResponse)
def root():
    """Serve the embed_container.html file as the root HTML page."""
    html_path = os.path.join(os.path.dirname(__file__), "embed_container.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)


group = typer.Typer(name="observability")


@group.command()
def embed(
    ctx: typer.Context = typer.Option(..., help="Context to use for observability"),
    host: str = typer.Option("0.0.0.0", help="Host to bind to", envvar="HOST"),
    port: int = typer.Option(8080, help="Port to bind to", envvar="PORT"),
    timeout: int = typer.Option(
        2 * 60, help="Timeout for the health check", envvar="TIMEOUT"
    ),
    event_prefix: Annotated[
        str, typer.Option(help="Event prefix", envvar="EVENT_PREFIX")
    ] = "lkr-observability",
):
    """Start the observability FastAPI server."""
    observability_ctx.initialize(
        ctx, port=port, host=host, timeout=timeout, event_prefix=event_prefix
    )
    uvicorn.run(
        "lkr.observability.main:app",
        host=host,
        port=port,
        reload=False,
        access_log=False,
    )
