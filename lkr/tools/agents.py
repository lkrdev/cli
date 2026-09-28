import json
import re
import time
from datetime import UTC, datetime
from typing import Annotated, Any

import requests
import typer
from looker_sdk.sdk.api40 import models as models40
from pydash import get

from lkr.auth_service import get_auth
from lkr.extended_sdk_methods import (
    ExtendedLooker40SDK,
    GeminiEnterpriseAgentRequest,
)
from lkr.logger import logger

__all__ = [
    "ARTIFACT_NAMESPACE",
    "LOOKER_A2A_URL_RE",
    "agents_group",
    "dedupe_agent_publications",
]

ARTIFACT_NAMESPACE = "lkr-dev-cli-tools-agents"

LOOKER_A2A_URL_RE = re.compile(
    r"^https?://(?P<looker_host>[^/]+)/api/4\.0/a2a/agents/(?P<looker_agent_guid>[^/]+)(?:/chat)?$"
)

agents_group = typer.Typer(
    name="agents",
    help="Conversational Analytics and Gemini Enterprise agent tools",
    no_args_is_help=True,
)


def _discovery_engine_base_uri(location: str) -> str:
    loc = (location or "global").strip().lower()
    return f"https://{'' if loc == 'global' else f'{loc}-'}discoveryengine.googleapis.com/v1alpha"


def _get_agent_artifact(
    sdk: ExtendedLooker40SDK, agent_id: str
) -> tuple[int | None, dict[str, Any]]:
    """Fetch existing artifact version and parsed payload for agent_id."""
    default_doc: dict[str, Any] = {"agent_id": agent_id, "publications": {}}
    try:
        items = sdk.artifact(namespace=ARTIFACT_NAMESPACE, key=agent_id) or []
        if not items:
            return None, default_doc
        item = items[0]
        version = get(item, "version")
        raw_val = get(item, "value")
        if raw_val:
            parsed = (
                json.loads(raw_val) if isinstance(raw_val, str) else raw_val
            )
            if isinstance(parsed, dict):
                parsed.setdefault("agent_id", agent_id)
                parsed.setdefault("publications", {})
                return version, parsed
        return version, default_doc
    except Exception as e:  # noqa: BLE001
        logger.debug(f"Artifact lookup notice for '{agent_id}': {e}")
        return None, default_doc


def _upsert_agent_publication_artifact(
    sdk: ExtendedLooker40SDK,
    agent_id: str,
    state: str,
    message: str,
    project_number: str | None,
    location: str | None,
    engine_id: str | None,
    platform_agent_id: str | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    """Create or update the Looker Artifact tracking publications for agent_id."""
    version, doc = _get_agent_artifact(sdk, agent_id)
    proj = str(project_number).strip() if project_number else "default"
    loc = str(location).strip().lower() if location else "global"
    eng = str(engine_id).strip() if engine_id else "default"
    pub_key = f"{proj}:{loc}:{eng}"

    existing_pub = doc["publications"].get(pub_key, {})
    resolved_platform_id = platform_agent_id or existing_pub.get(
        "platform_agent_id"
    )
    resolved_name = name or existing_pub.get("name") or doc.get("name")
    if resolved_name:
        doc["name"] = resolved_name

    doc["publications"][pub_key] = {
        "ge_gcp_project_number": proj,
        "ge_gcp_location": loc,
        "ge_engine_id": eng,
        "state": state,
        "message": message,
        "platform_agent_id": resolved_platform_id,
        "name": resolved_name,
        "updated_at": datetime.now(UTC).isoformat(),
    }

    update_item = models40.UpdateArtifact(
        key=agent_id,
        value=json.dumps(doc),
        content_type="application/json",
        version=version,
    )
    sdk.update_artifacts(namespace=ARTIFACT_NAMESPACE, body=[update_item])
    return doc


def _fetch_looker_agents_map(
    sdk: ExtendedLooker40SDK,
) -> dict[str, dict[str, Any]]:
    """Call GET /api/4.0/agents/search and return a map keyed by Looker agent GUID."""
    try:
        agents = (
            sdk.search_agents(
                fields="id,name,description,sources,context,created_at,updated_at"
            )
            or []
        )
        return {
            str(get(a, "id")): {
                "id": str(get(a, "id")),
                "name": get(a, "name") or "",
                "updated_at": get(a, "updated_at") or "",
            }
            for a in agents
            if get(a, "id")
        }
    except Exception as e:  # noqa: BLE001
        logger.debug(f"Could not fetch Looker agents via search_agents: {e}")
        return {}


def _search_artifacts_source(
    sdk: ExtendedLooker40SDK, looker_map: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Source 1: Search Looker Artifacts in namespace lkr-dev-cli-tools-agents."""
    try:
        artifacts = (
            sdk.search_artifacts(namespace=ARTIFACT_NAMESPACE, key="%") or []
        )
    except Exception as e:  # noqa: BLE001
        logger.debug(f"Could not search artifacts in {ARTIFACT_NAMESPACE}: {e}")
        return []

    rows: list[dict[str, Any]] = []
    for art in artifacts:
        key = str(get(art, "key", ""))
        raw_val = get(art, "value")
        if not raw_val:
            continue
        try:
            parsed = (
                json.loads(raw_val) if isinstance(raw_val, str) else raw_val
            )
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Skipping invalid artifact JSON for '{key}': {e}")
            continue
        if not isinstance(parsed, dict):
            continue
        agent_id = str(parsed.get("agent_id") or key)
        lkr_meta = looker_map.get(agent_id, {})
        pubs = parsed.get("publications") or {}
        if isinstance(pubs, dict):
            for pub in pubs.values():
                if isinstance(pub, dict):
                    rows.append(
                        {
                            "agent_id": agent_id,
                            "name": str(
                                pub.get("name")
                                or parsed.get("name")
                                or lkr_meta.get("name")
                                or ""
                            ),
                            "ge_gcp_project_number": str(
                                pub.get("ge_gcp_project_number") or "default"
                            ),
                            "ge_gcp_location": str(
                                pub.get("ge_gcp_location") or "global"
                            ).lower(),
                            "ge_engine_id": str(
                                pub.get("ge_engine_id") or "default"
                            ),
                            "state": str(pub.get("state") or ""),
                            "updated_at": str(pub.get("updated_at") or ""),
                            "platform_agent_id": pub.get("platform_agent_id"),
                            "discovery_source": "artifact",
                        }
                    )
    return rows


def _search_method_a_discovery_engine(
    token: str,
    project_number: str,
    engine_ids: list[str],
    looker_map: dict[str, dict[str, Any]],
    location: str | None = None,
    checked_engines: set[tuple[str, str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Source 2 (Method A): Query Discovery Engine assistants.agents.list across GE apps."""
    locs = (location.strip().lower(),) if location else ("global", "us", "eu")
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Goog-User-Project": project_number,
        "Content-Type": "application/json",
    }
    found: list[dict[str, Any]] = []
    norm_proj = str(project_number).strip()

    for eng_id in engine_ids:
        norm_eng = str(eng_id).strip()
        for loc in locs:
            if (
                checked_engines is not None
                and (norm_proj, loc, norm_eng) in checked_engines
            ):
                continue
            base_uri = _discovery_engine_base_uri(loc)
            url = (
                f"{base_uri}/projects/{norm_proj}/locations/{loc}"
                f"/collections/default_collection/engines/{norm_eng}"
                f"/assistants/default_assistant/agents"
            )
            page_token: str | None = None
            while True:
                params: dict[str, Any] = {"pageSize": 100}
                if page_token:
                    params["pageToken"] = page_token
                resp = requests.get(
                    url, headers=headers, params=params, timeout=30
                )
                if resp.status_code == 404 and not location:
                    break
                resp.raise_for_status()
                if checked_engines is not None:
                    checked_engines.add((norm_proj, loc, norm_eng))
                payload = resp.json()

                for item in payload.get("agents", []):
                    raw_card = item.get("a2aAgentDefinition", {}).get(
                        "jsonAgentCard"
                    )
                    if not raw_card:
                        continue
                    try:
                        card = (
                            json.loads(raw_card)
                            if isinstance(raw_card, str)
                            else raw_card
                        )
                    except Exception as e:  # noqa: BLE001
                        logger.debug(
                            f"Skipping invalid A2A agent card JSON: {e}"
                        )
                        continue
                    if not isinstance(card, dict):
                        continue
                    match = LOOKER_A2A_URL_RE.match(card.get("url", ""))
                    if not match:
                        continue
                    guid = match.group("looker_agent_guid")
                    lkr_meta = looker_map.get(guid, {})
                    found.append(
                        {
                            "agent_id": guid,
                            "name": str(
                                item.get("displayName")
                                or lkr_meta.get("name")
                                or card.get("name")
                                or ""
                            ),
                            "ge_gcp_project_number": norm_proj,
                            "ge_gcp_location": loc,
                            "ge_engine_id": norm_eng,
                            "state": "published",
                            "updated_at": str(
                                item.get("updateTime")
                                or item.get("createTime")
                                or ""
                            ),
                            "platform_agent_id": item.get("name"),
                            "discovery_source": "discovery_engine",
                        }
                    )

                page_token = payload.get("nextPageToken")
                if not page_token:
                    break

    return found


def _search_method_b_looker_api(
    sdk: ExtendedLooker40SDK,
    looker_map: dict[str, dict[str, Any]],
    delay_seconds: float = 6.0,
    scan_all: bool = False,
    de_targets: set[tuple[str, str | None, str]] | None = None,
) -> list[dict[str, Any]]:
    """Probe Looker's singleton GE config on 1 agent, or scan all agents when scan_all=True."""
    found: list[dict[str, Any]] = []
    items = list(looker_map.items())
    if not items:
        return found

    if scan_all and len(items) > 1 and delay_seconds > 0:
        logger.info(
            f"Scanning {len(items)} Looker agents via Looker API (paced at 1 request / {delay_seconds:g}s for Looker's 10 req/min rate limit)..."
        )

    for idx, (guid, meta) in enumerate(items):
        if idx > 0 and delay_seconds > 0:
            time.sleep(delay_seconds)
        try:
            res = sdk.get_published_agent(guid)
            if not isinstance(res, dict):
                if not scan_all:
                    break
                continue

            ge_meta = res.get("ge_agent_metadata") or {}
            singleton_proj = str(
                ge_meta.get("ge_gcp_project_number") or ""
            ).strip()
            singleton_loc = (
                str(ge_meta.get("ge_gcp_location") or "global").strip().lower()
            )
            singleton_eng = str(ge_meta.get("ge_engine_id") or "").strip()

            state = str(res.get("state") or "")
            msg = str(res.get("message") or "")
            if state == "published" or (
                state == "unpublished" and msg != "AGENT_NEVER_PUBLISHED"
            ):
                found.append(
                    {
                        "agent_id": guid,
                        "name": str(meta.get("name") or ""),
                        "ge_gcp_project_number": singleton_proj or "default",
                        "ge_gcp_location": singleton_loc or "global",
                        "ge_engine_id": singleton_eng or "default",
                        "state": state,
                        "updated_at": str(meta.get("updated_at") or ""),
                        "platform_agent_id": None,
                        "discovery_source": "looker_api",
                    }
                )

            # First agent call reveals Looker's instance-wide singleton GE target (even when unpublished)
            if idx == 0:
                if (
                    de_targets is not None
                    and singleton_proj
                    and singleton_eng
                ):
                    de_targets.add(
                        (singleton_proj, singleton_loc, singleton_eng)
                    )
                    break
                if not scan_all:
                    if len(items) > 1 and singleton_proj and singleton_eng:
                        logger.warning(
                            f"Looker instance default GE target detected (project={singleton_proj}, "
                            f"location={singleton_loc}, engine={singleton_eng}). "
                            f"Pass --gcp-token $(gcloud auth print-access-token) to list all published agents "
                            f"in 1 call, or pass --looker-api to scan all {len(items)} agents at 10 req/min."
                        )
                    break
        except Exception as e:  # noqa: BLE001
            err_str = str(e)
            logger.debug(f"get_published_agent failed for {guid}: {err_str}")
            # MISSING_GE_CONFIGURATION is an instance-wide singleton error on Looker; stop immediately
            if (
                "MISSING_GE_CONFIGURATION" in err_str
                or "404" in err_str
                or "403" in err_str
                or not scan_all
            ):
                break

    return found


def dedupe_agent_publications(
    records: list[dict[str, Any]],
    checked_engines: set[tuple[str, str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Deduplicate and merge agent publication records across artifact, discovery_engine, and looker_api."""
    merged: dict[tuple[str, str, str, str], dict[str, Any]] = {}

    for rec in records:
        agent_id = str(rec.get("agent_id") or "").strip()
        proj = str(rec.get("ge_gcp_project_number") or "default").strip()
        loc = str(rec.get("ge_gcp_location") or "global").strip().lower()
        eng = str(rec.get("ge_engine_id") or "default").strip()
        key = (agent_id, proj, loc, eng)

        src = str(rec.get("discovery_source") or "artifact")
        state = str(rec.get("state") or "")
        if key not in merged:
            if src == "looker_api" and state == "unpublished":
                continue
            merged[key] = {
                "agent_id": agent_id,
                "name": str(rec.get("name") or ""),
                "ge_gcp_project_number": proj,
                "ge_gcp_location": loc,
                "ge_engine_id": eng,
                "state": state,
                "updated_at": str(rec.get("updated_at") or ""),
                "platform_agent_id": rec.get("platform_agent_id"),
                "discovery_sources": [src],
            }
        else:
            existing = merged[key]
            if src not in existing["discovery_sources"]:
                existing["discovery_sources"].append(src)
            if src in ("discovery_engine", "looker_api"):
                if state == "published":
                    existing["state"] = "published"
                elif (
                    state == "unpublished"
                    and existing.get("state") == "published"
                    and "discovery_engine" not in existing["discovery_sources"]
                ):
                    existing["state"] = "unpublished"
                    existing["_reconciled_from_live"] = True
            if rec.get("platform_agent_id") and not existing.get(
                "platform_agent_id"
            ):
                existing["platform_agent_id"] = rec["platform_agent_id"]
            if rec.get("name") and not existing.get("name"):
                existing["name"] = str(rec["name"])
            if rec.get("updated_at") and (
                not existing.get("updated_at")
                or str(rec["updated_at"]) > str(existing["updated_at"])
            ):
                existing["updated_at"] = str(rec["updated_at"])

    if checked_engines:
        for (_, proj, loc, eng), row in merged.items():
            if (
                row.get("state") == "published"
                and "discovery_engine" not in row["discovery_sources"]
                and (proj, loc, eng) in checked_engines
            ):
                row["state"] = "unpublished"
                row["_reconciled_from_live"] = True

    return list(merged.values())


def _delete_from_discovery_engine(
    agent_id: str,
    token: str,
    project_number: str | None,
    engine_id: str | None,
    location: str | None = None,
    platform_agent_id: str | None = None,
) -> dict[str, Any]:
    target_resource = (
        platform_agent_id.strip().lstrip("/") if platform_agent_id else None
    )
    resolved_loc = location

    if not target_resource:
        if not project_number or not engine_id:
            raise ValueError(
                "Both --project-number and --engine-id (or --platform-agent-id) are required to delete an agent from a specific Gemini Enterprise app."
            )
        matches = [
            r
            for r in _search_method_a_discovery_engine(
                token, project_number, [engine_id], {}, location=location
            )
            if r["agent_id"] == agent_id
        ]
        if not matches or not matches[0].get("platform_agent_id"):
            raise LookupError(
                f"Agent '{agent_id}' not found in Gemini Enterprise engine '{engine_id}' (project '{project_number}')."
            )
        target_resource = matches[0]["platform_agent_id"]
        resolved_loc = matches[0].get("ge_gcp_location") or resolved_loc

    if not resolved_loc and target_resource:
        parts = target_resource.split("/")
        if len(parts) > 3 and parts[2] == "locations":
            resolved_loc = parts[3]
    resolved_loc = resolved_loc or "global"

    delete_url = f"{_discovery_engine_base_uri(resolved_loc)}/{target_resource}"
    del_resp = requests.delete(
        delete_url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    del_resp.raise_for_status()
    return {
        "state": "unpublished",
        "message": "AGENT_UNPUBLISHED_FROM_DISCOVERY_ENGINE",
        "platform_agent_id": target_resource,
        "ge_agent_metadata": {
            "ge_gcp_project_number": project_number,
            "ge_gcp_location": resolved_loc,
            "ge_engine_id": engine_id,
        },
    }


def _validate_project_number(value: str | None) -> str | None:
    try:
        return GeminiEnterpriseAgentRequest._validate_project_number(value)
    except ValueError as e:
        raise typer.BadParameter(str(e)) from e


@agents_group.command(name="publish")
def publish_agent_command(
    ctx: typer.Context,
    agent_id: Annotated[
        str,
        typer.Argument(help="Looker Conversational Analytics Agent ID (GUID)"),
    ],
    project_number: Annotated[
        str | None,
        typer.Option(
            "--project-number",
            "-p",
            envvar="GE_GCP_PROJECT_NUMBER",
            callback=_validate_project_number,
            help="Google Cloud Project Number for Gemini Enterprise",
        ),
    ] = None,
    location: Annotated[
        str | None,
        typer.Option(
            "--location",
            "-l",
            envvar="GE_GCP_LOCATION",
            help="Google Cloud Location for Gemini Enterprise (e.g., global, us, eu)",
        ),
    ] = None,
    engine_id: Annotated[
        str | None,
        typer.Option(
            "--engine-id",
            "-e",
            envvar="GE_ENGINE_ID",
            help="Gemini Enterprise Engine / App ID",
        ),
    ] = None,
    validate: Annotated[
        bool,
        typer.Option(
            "--validate/--no-validate",
            help="Validate Gemini Enterprise metadata before publishing",
        ),
    ] = False,
) -> None:
    """Publish a Looker CA agent to a Gemini Enterprise app and record it in Looker Artifacts."""
    sdk = get_auth(ctx).get_current_sdk()
    if not isinstance(sdk, ExtendedLooker40SDK):
        raise typer.Exit(1)

    loc = location or ("global" if (project_number or engine_id) else None)
    body = GeminiEnterpriseAgentRequest(
        ge_gcp_project_number=project_number,
        ge_gcp_location=loc,
        ge_engine_id=engine_id,
    )

    if validate:
        if not (project_number and loc and engine_id):
            logger.error(
                "--validate requires --project-number, --location, and --engine-id."
            )
            raise typer.Exit(1)
        try:
            val_res = sdk.validate_gemini_enterprise_metadata(body=body)
        except Exception as e:
            logger.error(f"Failed to validate Gemini Enterprise metadata: {e}")
            raise typer.Exit(1) from e
        if not val_res.get("success"):
            logger.error(
                f"Gemini Enterprise metadata validation failed: {val_res.get('message')}"
            )
            raise typer.Exit(1)

    payload = body.model_dump(exclude_none=True)
    try:
        res = sdk.publish_agent(agent_id=agent_id, body=payload)
    except Exception as e:
        if "Failed to register agent with GE" in str(e):
            sa_email = None
            try:
                ge_cfg = sdk.get_gemini_enablement()
                if isinstance(ge_cfg, dict):
                    sa_email = ge_cfg.get("ai_ge_service_account_email")
            except Exception as ge_err:  # noqa: BLE001
                logger.debug(
                    f"Could not fetch Gemini enablement config: {ge_err}"
                )
            sa_desc = (
                f"the Looker service account ({sa_email})"
                if sa_email
                else "the Looker service account"
            )
            logger.error(
                f"Failed to register agent with Gemini Enterprise. "
                f"Make sure {sa_desc} has been given a user license "
                f"in Gemini Enterprise > Manage Users (or enable 'Assign licenses automatically')."
            )
            raise typer.Exit(1) from e
        raise
    meta = res.get("ge_agent_metadata") or {}
    _upsert_agent_publication_artifact(
        sdk,
        agent_id=agent_id,
        state=res.get("state", "published"),
        message=res.get("message", ""),
        project_number=meta.get("ge_gcp_project_number") or project_number,
        location=meta.get("ge_gcp_location") or loc,
        engine_id=meta.get("ge_engine_id") or engine_id,
    )
    typer.echo(json.dumps(res, indent=2))


@agents_group.command(name="delete")
def delete_agent_command(
    ctx: typer.Context,
    agent_id: Annotated[
        str,
        typer.Argument(help="Looker Conversational Analytics Agent ID (GUID)"),
    ],
    project_number: Annotated[
        str | None,
        typer.Option(
            "--project-number",
            "-p",
            envvar="GE_GCP_PROJECT_NUMBER",
            callback=_validate_project_number,
            help="Target Gemini Enterprise GCP Project Number (for multi-app unpublish)",
        ),
    ] = None,
    engine_id: Annotated[
        str | None,
        typer.Option(
            "--engine-id",
            "-e",
            envvar="GE_ENGINE_ID",
            help="Target Gemini Enterprise Engine / App ID (for multi-app unpublish)",
        ),
    ] = None,
    platform_agent_id: Annotated[
        str | None,
        typer.Option(
            "--platform-agent-id",
            help="Full Discovery Engine agent resource name to delete directly",
        ),
    ] = None,
    gcp_token: Annotated[
        str | None,
        typer.Option(
            "--gcp-token",
            envvar="GCP_ACCESS_TOKEN",
            help="GCP OAuth access token, e.g. --gcp-token $(gcloud auth print-access-token)",
        ),
    ] = None,
) -> None:
    """Unpublish/delete a Looker CA agent from Gemini Enterprise and update its Looker Artifact.

    For secondary/multi-app Gemini Enterprise targets, pass `--gcp-token $(gcloud auth print-access-token)`.
    """
    sdk = get_auth(ctx).get_current_sdk()
    if not isinstance(sdk, ExtendedLooker40SDK):
        raise typer.Exit(1)

    has_explicit_ge_target = bool(
        project_number or engine_id or platform_agent_id
    )
    _, artifact_doc = _get_agent_artifact(sdk, agent_id)
    publications: dict[str, Any] = artifact_doc.get("publications", {})

    results: list[dict[str, Any]] = []
    singleton_unpublish_meta: dict[str, Any] = {}

    if not has_explicit_ge_target:
        try:
            res = sdk.unpublish_agent(agent_id=agent_id)
        except Exception as e:
            logger.error(f"Failed to unpublish agent: {e}")
            raise typer.Exit(1) from e
        singleton_meta = res.get("ge_agent_metadata") or {}
        if res.get("message") != "AGENT_NEVER_PUBLISHED":
            singleton_unpublish_meta = singleton_meta
            _upsert_agent_publication_artifact(
                sdk,
                agent_id=agent_id,
                state=res.get("state", "unpublished"),
                message=res.get("message", ""),
                project_number=singleton_meta.get("ge_gcp_project_number"),
                location=singleton_meta.get("ge_gcp_location"),
                engine_id=singleton_meta.get("ge_engine_id"),
            )
            results.append(res)

    if has_explicit_ge_target:
        matched = next(
            (
                pub
                for pub in publications.values()
                if isinstance(pub, dict)
                and (
                    not project_number
                    or pub.get("ge_gcp_project_number") == project_number
                )
                and (not engine_id or pub.get("ge_engine_id") == engine_id)
            ),
            {},
        )
        targets_to_delete = [
            {
                "ge_gcp_project_number": project_number,
                "ge_gcp_location": matched.get("ge_gcp_location"),
                "ge_engine_id": engine_id,
                "platform_agent_id": platform_agent_id
                or matched.get("platform_agent_id"),
            }
        ]
    else:
        singleton_key = (
            f"{singleton_unpublish_meta.get('ge_gcp_project_number')}:"
            f"{str(singleton_unpublish_meta.get('ge_gcp_location') or 'global').lower()}:"
            f"{singleton_unpublish_meta.get('ge_engine_id')}"
            if singleton_unpublish_meta
            else None
        )
        targets_to_delete = [
            pub
            for pub_key, pub in publications.items()
            if pub.get("state") == "published"
            and pub_key != singleton_key
            and pub.get("ge_gcp_project_number")
            and pub.get("ge_engine_id")
        ]

    if not targets_to_delete and results:
        typer.echo(
            json.dumps(results[0] if len(results) == 1 else results, indent=2)
        )
        return

    token = gcp_token.strip() if gcp_token else None
    if not token:
        logger.error(
            "Unpublishing from multiple/secondary Gemini Enterprise apps requires a GCP access token. "
            "Pass --gcp-token $(gcloud auth print-access-token) or set GCP_ACCESS_TOKEN."
        )
        raise typer.Exit(1)

    if not targets_to_delete:
        logger.error(
            f"Agent '{agent_id}' has no active publications tracked in Looker Artifacts or singleton config. "
            "Pass --project-number and --engine-id to target a specific Gemini Enterprise app."
        )
        raise typer.Exit(1)

    try:
        for target in targets_to_delete:
            t_proj = target.get("ge_gcp_project_number")
            t_loc = target.get("ge_gcp_location")
            t_eng = target.get("ge_engine_id")
            t_plat = target.get("platform_agent_id")
            del_res = _delete_from_discovery_engine(
                agent_id=agent_id,
                token=token,
                project_number=t_proj,
                engine_id=t_eng,
                location=t_loc,
                platform_agent_id=t_plat,
            )
            resolved_loc = (
                del_res.get("ge_agent_metadata", {}).get("ge_gcp_location")
                or t_loc
                or "global"
            )
            _upsert_agent_publication_artifact(
                sdk,
                agent_id=agent_id,
                state="unpublished",
                message=del_res["message"],
                project_number=t_proj,
                location=resolved_loc,
                engine_id=t_eng,
                platform_agent_id=del_res.get("platform_agent_id"),
            )
            results.append(del_res)
        typer.echo(
            json.dumps(results[0] if len(results) == 1 else results, indent=2)
        )
    except Exception as e:
        logger.error(str(e))
        raise typer.Exit(1) from e


@agents_group.command(name="list")
def list_agent_artifacts_command(
    ctx: typer.Context,
    project_number: Annotated[
        str | None,
        typer.Option(
            "--project-number",
            "-p",
            envvar="GE_GCP_PROJECT_NUMBER",
            callback=_validate_project_number,
            help="GCP Project Number to enable Discovery Engine search",
        ),
    ] = None,
    engine_id: Annotated[
        str | None,
        typer.Option(
            "--engine-id",
            "-e",
            envvar="GE_ENGINE_ID",
            help="Comma-separated Gemini Enterprise Engine ID(s) for Discovery Engine search",
        ),
    ] = None,
    gcp_token: Annotated[
        str | None,
        typer.Option(
            "--gcp-token",
            envvar="GCP_ACCESS_TOKEN",
            help="GCP OAuth access token, e.g. --gcp-token $(gcloud auth print-access-token)",
        ),
    ] = None,
    looker_api: Annotated[
        bool,
        typer.Option(
            "--looker-api",
            help="Scan all Looker agents sequentially via Looker API (paced at 10 req/min) when --gcp-token is omitted",
        ),
    ] = False,
    update_artifact: Annotated[
        bool,
        typer.Option(
            "--update-artifact/--no-update-artifact",
            help="Sync discovered publication states (including Gemini UI deletions) back to the Looker artifact store",
        ),
    ] = True,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json", help="Output deduplicated agent publications as JSON"
        ),
    ] = False,
) -> None:
    """List and deduplicate published agents across Looker and Gemini Enterprise.

    To also scan Gemini Enterprise Discovery Engine across locations (global, us, eu),
    pass `--project-number`, `--engine-id`, and `--gcp-token $(gcloud auth print-access-token)`.
    """
    sdk = get_auth(ctx).get_current_sdk()
    if not isinstance(sdk, ExtendedLooker40SDK):
        raise typer.Exit(1)

    token = gcp_token.strip() if gcp_token else None
    engine_ids = [e.strip() for e in (engine_id or "").split(",") if e.strip()]
    looker_map = _fetch_looker_agents_map(sdk)
    artifact_records = _search_artifacts_source(sdk, looker_map)
    raw_records = list(artifact_records)
    checked_engines: set[tuple[str, str, str]] = set()
    de_targets: set[tuple[str, str | None, str]] = set()

    raw_records.extend(
        _search_method_b_looker_api(
            sdk,
            looker_map,
            scan_all=looker_api,
            de_targets=de_targets if token else None,
        )
    )

    if token:
        if project_number:
            de_targets.update((project_number, None, e) for e in engine_ids)
        de_targets.update(
            (
                str(r.get("ge_gcp_project_number") or "").strip(),
                str(r.get("ge_gcp_location") or "global").strip().lower(),
                str(r.get("ge_engine_id") or "").strip(),
            )
            for r in artifact_records
            if r.get("state") == "published"
        )
        for t_proj, t_loc, t_eng in sorted(
            de_targets, key=lambda t: (t[0], t[1] or "zzz", t[2])
        ):
            if t_proj and t_proj != "default" and t_eng and t_eng != "default":
                try:
                    raw_records.extend(
                        _search_method_a_discovery_engine(
                            token=token,
                            project_number=t_proj,
                            engine_ids=[t_eng],
                            looker_map=looker_map,
                            location=t_loc,
                            checked_engines=checked_engines,
                        )
                    )
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        f"Discovery Engine search failed for {t_proj}:{t_loc or '*'}:{t_eng}: {e}"
                    )

    if not (token and project_number and engine_ids):
        logger.info(
            "Displayed data may not be accurate if actions to publish or unpublish have been taken "
            "in Looker or in the GCP console. Please run with these flags to fully validate the current state: "
            "--project-number <PROJECT_NUMBER> --engine-id <ENGINE_ID> --gcp-token $(gcloud auth print-access-token)"
        )

    deduped = dedupe_agent_publications(
        raw_records, checked_engines=checked_engines
    )

    for row in deduped:
        reconciled = bool(row.pop("_reconciled_from_live", False))
        if not update_artifact:
            continue
        sources = row.get("discovery_sources") or []
        live_discovered = (
            "discovery_engine" in sources or "looker_api" in sources
        )
        if reconciled or (
            row.get("state") == "published" and live_discovered
        ):
            try:
                _upsert_agent_publication_artifact(
                    sdk,
                    agent_id=row["agent_id"],
                    state=row["state"],
                    message=(
                        "Synced from live discovery (not found in Gemini Enterprise)"
                        if reconciled and row.get("state") == "unpublished"
                        else "Synced from live discovery"
                    ),
                    project_number=row["ge_gcp_project_number"],
                    location=row["ge_gcp_location"],
                    engine_id=row["ge_engine_id"],
                    platform_agent_id=row.get("platform_agent_id"),
                    name=row.get("name"),
                )
            except Exception as e:  # noqa: BLE001
                logger.debug(
                    f"Could not sync artifact for {row['agent_id']}: {e}"
                )

    if json_output:
        typer.echo(json.dumps(deduped, indent=2))
        return

    if not deduped:
        typer.echo("No agent publications found.")
        return

    for i, r in enumerate(deduped):
        if i:
            typer.echo("-" * 40)
        typer.echo(f"Agent ID:   {r['agent_id']}")
        typer.echo(f"Name:       {r.get('name') or ''}")
        typer.echo(f"Project:    {r['ge_gcp_project_number']}")
        typer.echo(f"Location:   {r['ge_gcp_location']}")
        typer.echo(f"Engine ID:  {r['ge_engine_id']}")
        typer.echo(f"State:      {r['state']}")
        typer.echo(f"Sources:    {','.join(r.get('discovery_sources') or [])}")
        typer.echo(f"Updated At: {r['updated_at']}")
