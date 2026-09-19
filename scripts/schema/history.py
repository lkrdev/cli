import json
from pathlib import Path
from typing import Annotated, Any

import typer

from lkr.auth_service import get_auth
from lkr.classes import LkrCtxObj
from lkr.schema.builder import build_explore_query_schema
from lkr.schema.validator import validate_batch_queries

DEFAULT_HISTORY_QUERY_SLUG = "eiMJQXpAgoXow2JId7whVy"


def _to_dict(obj: Any) -> dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    from lkr.codemode.main import to_primitive

    res = to_primitive(obj)
    return res if isinstance(res, dict) else {}


def build_history_lookup_query(
    *,
    base_query: dict[str, Any] | None = None,
    model: str | None = None,
    explore: str | None = None,
    query_ids: list[int | str] | None = None,
    require_dynamic_fields: bool = False,
    limit: int = 50,
) -> dict[str, Any]:
    """Build a system__activity::history WriteQuery starting from base_query (e.g. eiMJQXpAgoXow2JId7whVy)."""
    base = dict(base_query) if isinstance(base_query, dict) else {}
    raw_fields = base.get("fields")
    fields: list[str] = (
        [str(f) for f in raw_fields if isinstance(f, str)]
        if isinstance(raw_fields, list)
        else ["query.id"]
    )
    for required_field in (
        "query.id",
        "query.slug",
        "query.model",
        "query.view",
        "query.dynamic_fields",
    ):
        if required_field not in fields:
            fields.append(required_field)

    raw_filters = base.get("filters")
    filters: dict[str, Any] = (
        dict(raw_filters)
        if isinstance(raw_filters, dict)
        else {
            "history.status": "complete",
            "history.workspace_id": "production",
        }
    )
    filters.pop("query.dynamic_fields", None)
    if model:
        filters["query.model"] = model
    if explore:
        filters["query.view"] = explore
    if query_ids:
        filters["query.id"] = ",".join(str(qid) for qid in query_ids)

    sorts = (
        base.get("sorts")
        if isinstance(base.get("sorts"), list)
        else ["query.id desc"]
    )
    out: dict[str, Any] = {
        "model": base.get("model") or "system__activity",
        "view": base.get("view") or "history",
        "fields": fields,
        "filters": filters,
        "sorts": sorts,
        "limit": str(limit),
    }
    if require_dynamic_fields:
        out["filter_expression"] = "length(${query.dynamic_fields}) > 2"
    elif isinstance(base.get("filter_expression"), str) and base["filter_expression"]:
        out["filter_expression"] = base["filter_expression"]
    return out


def resolve_history_queries(
    sdk: Any,
    *,
    model: str | None = None,
    explore: str | None = None,
    query_ids: list[int | str] | None = None,
    history_slug: str | None = DEFAULT_HISTORY_QUERY_SLUG,
    require_dynamic_fields: bool = False,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """
    Reusable dev/refinement pipeline:
    1. Optionally fetches the template query (default `eiMJQXpAgoXow2JId7whVy`) from `system__activity::history`.
    2. Runs `run_inline_query` on `system__activity::history` filtered by `model`, `explore`, and/or `query_ids`
       to resolve completed `query.id` -> `query.slug`.
    3. Calls `sdk.query(slug)` (`get_query`) for each resolved query.
    """
    base_query: dict[str, Any] | None = None
    if history_slug and hasattr(sdk, "query_for_slug"):
        try:
            base_query = _to_dict(sdk.query_for_slug(history_slug))
        except Exception:  # noqa: BLE001
            base_query = None

    lookup_body = build_history_lookup_query(
        base_query=base_query,
        model=model,
        explore=explore,
        query_ids=query_ids,
        require_dynamic_fields=require_dynamic_fields,
        limit=limit,
    )

    from looker_sdk.sdk.api40 import models as mdls

    raw_rows = sdk.run_inline_query("json", mdls.WriteQuery(**lookup_body))
    rows: list[dict[str, Any]] = (
        json.loads(raw_rows) if isinstance(raw_rows, str) else list(raw_rows or [])
    )

    resolved: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        qid = row.get("query.id")
        slug = row.get("query.slug")
        dedup_key = str(qid if qid is not None else slug)
        if not slug or dedup_key in seen_ids:
            continue
        seen_ids.add(dedup_key)

        full_query = _to_dict(sdk.query(str(slug)))
        resolved.append(
            {
                "query_id": qid,
                "slug": str(slug),
                "completed_count": row.get("history.completed_Count"),
                "raw_query": full_query,
            }
        )
    return resolved


def validate_history_queries(
    queries: list[dict[str, Any]],
    schema: dict[str, Any],
) -> dict[str, Any]:
    """
    Validate a batch of completed queries (either output of `resolve_history_queries`
    or raw `sdk.query(...)` dicts) against an Explore JSON Schema using the Rust batch validator.
    """
    results: list[dict[str, Any]] = []
    valid_count = 0
    invalid_count = 0

    prepared: list[tuple[Any, Any, dict[str, Any]]] = []
    batch_inputs: list[dict[str, Any] | str] = []
    for item in queries:
        raw_candidate = (
            item.get("raw_query")
            if "raw_query" in item
            else item.get("query")
            if isinstance(item.get("query"), dict)
            else item
        )
        raw_q: dict[str, Any] = (
            raw_candidate if isinstance(raw_candidate, dict) else {}
        )
        qid = item.get("query_id", item.get("id", raw_q.get("id")))
        slug = item.get("slug", raw_q.get("slug"))
        prepared.append((qid, slug, raw_q))
        batch_inputs.append({"body": raw_q})

    batch_results = validate_batch_queries(batch_inputs, schema)
    for (qid, slug, raw_q), val_result in zip(
        prepared, batch_results, strict=False
    ):
        if val_result.valid:
            valid_count += 1
        else:
            invalid_count += 1

        results.append(
            {
                "query_id": qid,
                "slug": slug,
                "valid": val_result.valid,
                "error_count": len(val_result.errors),
                "errors": list(val_result.errors),
                "warnings": list(val_result.warnings),
                "fields": raw_q.get("fields"),
                "pivots": raw_q.get("pivots"),
                "filters": raw_q.get("filters"),
                "has_dynamic_fields": bool(raw_q.get("dynamic_fields")),
            }
        )

    body_props = (
        schema.get("properties", {}).get("body", {}).get("properties", {})
        if isinstance(schema.get("properties"), dict)
        else {}
    )
    return {
        "model": body_props.get("model", {}).get("const")
        if isinstance(body_props.get("model"), dict)
        else None,
        "explore": body_props.get("view", {}).get("const")
        if isinstance(body_props.get("view"), dict)
        else None,
        "total_queries": len(results),
        "valid_queries": valid_count,
        "invalid_queries": invalid_count,
        "results": results,
    }


app = typer.Typer(
    help="Developer harness to fetch completed queries from system__activity::history and validate them."
)


@app.command()
def main(
    oauth_account: Annotated[
        str | None,
        typer.Option(
            "--oauth-account", help="Looker OAuth account name (e.g. prod-demowest)"
        ),
    ] = None,
    model: Annotated[
        str,
        typer.Option("--model", "-m", help="LookML model name"),
    ] = "thelook",
    explore: Annotated[
        str,
        typer.Option("--explore", "-e", help="LookML explore name"),
    ] = "order_items",
    explore_file: Annotated[
        Path | None,
        typer.Option(
            "--explore-file",
            "-f",
            help="Optional local lookml_model_explore JSON file",
        ),
    ] = None,
    schema_file: Annotated[
        Path | None,
        typer.Option(
            "--schema-file", help="Optional pre-generated JSON schema file"
        ),
    ] = None,
    history_slug: Annotated[
        str,
        typer.Option(
            "--history-slug", help="Base system__activity::history query slug"
        ),
    ] = DEFAULT_HISTORY_QUERY_SLUG,
    query_id: Annotated[
        list[str] | None,
        typer.Option(
            "--query-id",
            help="Specific completed query.id(s) from system__activity::history",
        ),
    ] = None,
    require_dynamic_fields: Annotated[
        bool,
        typer.Option(
            "--require-dynamic-fields",
            help="Only fetch queries with non-null dynamic_fields",
        ),
    ] = False,
    limit: Annotated[
        int,
        typer.Option(
            "--limit", "-l", help="Max completed queries to fetch and validate"
        ),
    ] = 25,
) -> None:
    ctx_lkr = LkrCtxObj(oauth_account=oauth_account, force_oauth=bool(oauth_account))
    sdk = get_auth(ctx_lkr).get_current_sdk(prompt_refresh_invalid_token=True)

    if schema_file is not None:
        schema_data = json.loads(schema_file.read_text(encoding="utf-8"))
    elif explore_file is not None:
        explore_data = json.loads(explore_file.read_text(encoding="utf-8"))
        schema_data = build_explore_query_schema(model, explore, explore_data)
    else:
        from lkr.codemode.main import to_primitive

        explore_data = to_primitive(sdk.lookml_model_explore(model, explore))
        schema_data = build_explore_query_schema(model, explore, explore_data)

    resolved = resolve_history_queries(
        sdk,
        model=model,
        explore=explore,
        query_ids=list(query_id) if query_id else None,
        history_slug=history_slug,
        require_dynamic_fields=require_dynamic_fields,
        limit=limit,
    )
    summary = validate_history_queries(resolved, schema_data)
    typer.echo(json.dumps(summary, indent=2))
    if summary["invalid_queries"] > 0:
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
