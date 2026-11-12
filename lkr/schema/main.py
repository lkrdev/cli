import json
from pathlib import Path
from typing import Annotated, cast

import typer
from looker_sdk.sdk.api40.methods import Looker40SDK

from lkr.auth_service import get_auth
from lkr.classes import LkrCtxObj
from lkr.logger import logger
from lkr.schema.builder import build_explore_query_schema, build_schema_context
from lkr.schema.validator import (
    ValidationResult,
    validate_batch_queries,
    validate_merge_query,
    validate_query,
)

__all__ = [
    "context_command",
    "generate_command",
    "group",
    "validate_command",
]

group = typer.Typer(
    name="schema",
    help="Generate and validate strongly-typed Looker Explore query schemas",
    no_args_is_help=True,
)


def _get_sdk(ctx: typer.Context) -> Looker40SDK:
    ctx_lkr = (
        ctx.obj.get("ctx_lkr")
        if (ctx and ctx.obj and "ctx_lkr" in ctx.obj)
        else LkrCtxObj(force_oauth=False)
    )
    return get_auth(ctx_lkr).get_current_sdk(prompt_refresh_invalid_token=True)


def _load_explore_data(
    ctx: typer.Context,
    model: str,
    explore: str,
    explore_file: Path | None = None,
) -> dict[str, object]:
    if explore_file is not None:
        try:
            return cast(
                dict[str, object], json.loads(explore_file.read_text(encoding="utf-8"))
            )
        except FileNotFoundError:
            logger.error(f"Explore file not found: {explore_file}")
            raise typer.Exit(1)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in explore file {explore_file}: {e}")
            raise typer.Exit(1)

    from lkr.codemode.type import to_primitive

    return cast(
        dict[str, object],
        to_primitive(_get_sdk(ctx).lookml_model_explore(model, explore)),
    )


@group.command(name="generate")
def generate_command(
    ctx: typer.Context,
    model: Annotated[
        str,
        typer.Option("--model", "-m", help="LookML model name"),
    ],
    explore: Annotated[
        str,
        typer.Option("--explore", "-e", help="LookML explore name"),
    ],
    explore_file: Annotated[
        Path | None,
        typer.Option(
            "--explore-file",
            "-f",
            help="Path to a local lookml_model_explore JSON file (e.g. tmp/order_items.json)",
        ),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Optional file path to write the generated JSON schema",
        ),
    ] = None,
) -> None:
    """Generate a strongly-typed run_inline_query JSON Schema for --model and --explore."""
    explore_data = _load_explore_data(ctx, model, explore, explore_file)
    formatted = json.dumps(
        build_explore_query_schema(model, explore, explore_data), indent=2
    )
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(formatted + "\n", encoding="utf-8")
    else:
        typer.echo(formatted)


@group.command(name="validate")
def validate_command(
    ctx: typer.Context,
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="LookML model name"),
    ] = None,
    explore: Annotated[
        str | None,
        typer.Option("--explore", "-e", help="LookML explore name"),
    ] = None,
    explore_file: Annotated[
        Path | None,
        typer.Option(
            "--explore-file",
            "-f",
            help="Path to a local lookml_model_explore JSON file (e.g. tmp/order_items.json)",
        ),
    ] = None,
    schema: Annotated[
        str | None,
        typer.Option(
            "--schema",
            help="Inline JSON schema string (optional; if omitted, generates schema from --model and --explore)",
        ),
    ] = None,
    schema_file: Annotated[
        Path | None,
        typer.Option(
            "--schema-file",
            help="Path to a generated JSON schema file (optional; if omitted, generates schema from --model and --explore)",
        ),
    ] = None,
    query: Annotated[
        str | None,
        typer.Option(
            "--query",
            "-q",
            help="Inline query JSON string (either full run_inline_query payload or body WriteQuery)",
        ),
    ] = None,
    query_file: Annotated[
        Path | None,
        typer.Option(
            "--query-file",
            help="Path to a query JSON file (either full run_inline_query payload or body WriteQuery)",
        ),
    ] = None,
) -> None:
    """Validate a query (--query or --query-file) against an Explore schema."""
    if bool(query) == bool(query_file):
        logger.error("Specify exactly one of --query or --query-file")
        raise typer.Exit(1)
    if schema and schema_file:
        logger.error("Cannot specify both --schema and --schema-file")
        raise typer.Exit(1)

    if query is not None:
        query_payload = json.loads(query)
    elif query_file is not None:
        query_payload = json.loads(query_file.read_text(encoding="utf-8"))
    else:
        raise typer.Exit(1)

    if (
        isinstance(query_payload, dict)
        and "source_queries" in query_payload
        and explore_file is not None
    ):
        sqs = query_payload.get("source_queries")
        first_q = (
            (sqs[0].get("query") if isinstance(sqs[0].get("query"), dict) else sqs[0])
            if isinstance(sqs, list) and sqs and isinstance(sqs[0], dict)
            else {}
        )
        resolved_model = model or (
            first_q.get("model") if isinstance(first_q, dict) else None
        )
        if not resolved_model:
            logger.error("Must provide --model for source_queries validation")
            raise typer.Exit(1)
        explore_data = _load_explore_data(ctx, resolved_model, "", explore_file)
        result = validate_merge_query(query_payload, resolved_model, explore_data)
        typer.echo(json.dumps(result.to_dict(), indent=2))
        if not result.valid:
            raise typer.Exit(1)
        return

    is_query_map = (
        isinstance(query_payload, dict)
        and bool(query_payload)
        and not any(
            k in query_payload
            for k in ("source_queries", "body", "fields", "view", "model", "result_format")
        )
        and all(isinstance(v, dict) for v in query_payload.values())
    )
    items = (
        list(query_payload.values())
        if is_query_map
        else (query_payload if isinstance(query_payload, list) else [query_payload])
    )
    if schema is not None or schema_file is not None:
        schema_data = (
            json.loads(schema)
            if schema is not None
            else json.loads(cast(Path, schema_file).read_text(encoding="utf-8"))
        )
        results = (
            validate_batch_queries(items, schema_data)
            if is_query_map or isinstance(query_payload, list)
            else [validate_query(query_payload, schema_data)]
        )
    else:
        cached_file_data = (
            _load_explore_data(ctx, model or "", explore or "", explore_file)
            if explore_file is not None
            else None
        )
        schema_cache: dict[tuple[str, str], dict[str, object] | str] = {}

        def _validate_one(item: object) -> ValidationResult:
            if not isinstance(item, dict):
                return ValidationResult(valid=False, errors=["Query payload must be a JSON object"])
            body_obj = b if isinstance(b := item.get("body"), dict) else item
            rm = model or body_obj.get("model")
            rexp = explore or body_obj.get("view")
            if not isinstance(rm, str) or not rm or not isinstance(rexp, str) or not rexp:
                logger.error(
                    "Must provide --model and --explore (or --schema / --schema-file) to generate schema for validation"
                )
                raise typer.Exit(1)
            key = (rm, rexp)
            if key not in schema_cache:
                edata = (
                    cached_file_data
                    if cached_file_data is not None
                    else _load_explore_data(ctx, rm, rexp, None)
                )
                if isinstance(lme := edata.get("lookml_model_explores"), dict) and (
                    f"{rm}::{rexp}" not in lme and rexp not in lme
                ):
                    schema_cache[key] = f"$.body.view: unknown explore '{rexp}' in model '{rm}'"
                else:
                    schema_cache[key] = build_explore_query_schema(rm, rexp, edata)
            sc = schema_cache[key]
            if isinstance(sc, str):
                return ValidationResult(valid=False, errors=[sc])
            return validate_query(cast(dict[str, object], item), sc)

        results = [_validate_one(it) for it in items]

    out = (
        {k: r.to_dict() for k, r in zip(query_payload.keys(), results)}
        if is_query_map
        else ([r.to_dict() for r in results] if isinstance(query_payload, list) else results[0].to_dict())
    )
    typer.echo(json.dumps(out, indent=2))
    if not all(r.valid for r in results):
        raise typer.Exit(1)


@group.command(name="context")
def context_command(
    ctx: typer.Context,
    model: Annotated[
        str,
        typer.Option("--model", "-m", help="LookML model name"),
    ],
    path: Annotated[
        Path | None,
        typer.Option("--path", help="Path to local LookML repository directory"),
    ] = None,
    explore_file: Annotated[
        Path | None,
        typer.Option(
            "--explore-file",
            "-f",
            help="Path to a local lookml-to-api JSON file",
        ),
    ] = None,
    prompt: Annotated[
        str | None,
        typer.Option("--prompt", "-p", help="User analytics question for BM25 ranking"),
    ] = None,
    top_explores: Annotated[
        int,
        typer.Option("--top-explores", help="Number of top Explores to include"),
    ] = 3,
    max_fields_per_view: Annotated[
        int,
        typer.Option(
            "--max-fields-per-view",
            help="Maximum dimensions/measures to include per view when --prompt is set",
        ),
    ] = 35,
) -> None:
    """Prune LookML Explores and fields into a compact local BM25 context catalog."""
    if explore_file is not None:
        explores_data = _load_explore_data(ctx, model, "", explore_file)
    else:
        from lkr.parse.lookml_to_api import parse_lookml_to_api

        repo_dir = path if path is not None else Path(".")
        explores_data = parse_lookml_to_api(
            repo_dir, model=model, exclude_hidden=True
        ).model_dump(exclude_none=True)
    catalog = build_schema_context(
        model,
        explores_data,
        prompt=prompt,
        top_explores=top_explores,
        max_fields_per_view=max_fields_per_view,
    )
    typer.echo(json.dumps(catalog, indent=2))
