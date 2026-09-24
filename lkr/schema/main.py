import json
from pathlib import Path
from typing import Annotated, Any

import typer

from lkr.auth_service import get_auth
from lkr.classes import LkrCtxObj
from lkr.logger import logger
from lkr.schema.builder import build_explore_query_schema
from lkr.schema.validator import validate_batch_queries, validate_query

__all__ = [
    "generate_command",
    "group",
    "validate_command",
]

group = typer.Typer(
    name="schema",
    help="Generate and validate strongly-typed Looker Explore query schemas",
    no_args_is_help=True,
)


def _get_sdk(ctx: typer.Context) -> Any:
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
) -> dict[str, Any]:
    if explore_file is not None:
        try:
            return json.loads(explore_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            logger.error(f"Explore file not found: {explore_file}")
            raise typer.Exit(1)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in explore file {explore_file}: {e}")
            raise typer.Exit(1)

    from lkr.codemode.main import to_primitive

    return to_primitive(_get_sdk(ctx).lookml_model_explore(model, explore))


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

    if schema is not None:
        schema_data = json.loads(schema)
    elif schema_file is not None:
        schema_data = json.loads(schema_file.read_text(encoding="utf-8"))
    else:
        first_item = (
            query_payload[0]
            if isinstance(query_payload, list) and query_payload
            else query_payload
        )
        body_obj = (
            first_item.get("body")
            if isinstance(first_item, dict) and isinstance(first_item.get("body"), dict)
            else first_item
        )
        resolved_model = model or (
            body_obj.get("model") if isinstance(body_obj, dict) else None
        )
        resolved_explore = explore or (
            body_obj.get("view") if isinstance(body_obj, dict) else None
        )
        if not resolved_model or not resolved_explore:
            logger.error(
                "Must provide --model and --explore (or --schema / --schema-file) to generate schema for validation"
            )
            raise typer.Exit(1)
        explore_data = _load_explore_data(
            ctx, resolved_model, resolved_explore, explore_file
        )
        schema_data = build_explore_query_schema(
            resolved_model, resolved_explore, explore_data
        )

    if isinstance(query_payload, list):
        results = validate_batch_queries(query_payload, schema_data)
        typer.echo(json.dumps([r.to_dict() for r in results], indent=2))
        if not all(r.valid for r in results):
            raise typer.Exit(1)
    else:
        result = validate_query(query_payload, schema_data)
        typer.echo(json.dumps(result.to_dict(), indent=2))
        if not result.valid:
            raise typer.Exit(1)
