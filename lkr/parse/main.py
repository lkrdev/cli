from pathlib import Path
from typing import Annotated, Literal

import typer

from lkr.auth_service import get_auth
from lkr.logger import logger
from lkr.parse.lookml import LookmlProject, parse_lookml
from lkr.parse.lookml_database_compare import (
    format_compare_result,
    parse_lookml_database_compare,
)
from lkr.parse.lookml_snapshot import (
    LookmlSnapshotResult,
    run_lookml_snapshot,
)
from lkr.parse.lookml_to_api import LookmlToApiResult, parse_lookml_to_api
from lkr.parse.sql import SqlParseResult, parse_sql
from lkr.parse.sql_to_lookml import (
    SqlToLookmlResult,
    parse_sql_to_lookml,
)
from lkr.parse.translations import (
    TranslationAnalysisResult,
    analyze_lookml_translations,
    format_translations_console,
    format_translations_text,
)
from lkr.parse.types import LookmlDatabaseCompareResult
from lkr.parse.user_attributes import (
    LookmlUserAttributesResult,
    format_user_attributes,
    parse_user_attributes,
)

__all__ = [
    "group",
    "lookml_command",
    "lookml_database_compare_command",
    "lookml_group",
    "lookml_to_api_command",
    "snapshot_command",
    "sql_command",
    "sql_lookml_compare_command",
    "translations_command",
    "user_attributes_command",
]



group = typer.Typer(
    name="parse",
    help="Parse SQL and LookML into structured components",
    no_args_is_help=True,
)


ManifestOpt = Annotated[
    Path | None,
    typer.Option(
        "--manifest",
        help="Optional path to a manifest.lkml file for constant resolution",
    ),
]
ConstantOpt = Annotated[
    list[str] | None,
    typer.Option(
        "--constant",
        "-C",
        help="Constant override in KEY=VALUE format (repeatable)",
    ),
]


def _write_or_echo(text: str, output: Path | None) -> None:
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    else:
        typer.echo(text)


def _validate_sql_args(
    sql: str | None, file: Path | None, file_flag: str = "--file"
) -> None:
    if (sql is not None) == (file is not None):
        logger.error(f"Specify exactly one of --sql or {file_flag}")
        raise typer.Exit(1)
    if file is not None and not file.exists():
        logger.error(f"SQL file not found: {file}")
        raise typer.Exit(1)


def _validate_lookml_args(
    path: Path | None,
    file: Path | None,
    lookml: str | None,
    file_flag: str = "--file",
    manifest: Path | None = None,
) -> None:
    if sum(x is not None for x in (path, file, lookml)) != 1:
        logger.error(f"Specify exactly one of --path, {file_flag}, or --lookml")
        raise typer.Exit(1)
    for p, label in ((path, "path"), (file, "file"), (manifest, "manifest")):
        if p is not None and not p.exists():
            logger.error(f"LookML {label} not found: {p}")
            raise typer.Exit(1)


def _parse_constant_overrides(
    constant: list[str] | dict[str, str] | None,
    manifest: Path | None = None,
) -> dict[str, str] | None:
    if manifest is not None and not manifest.exists():
        logger.error(f"LookML manifest not found: {manifest}")
        raise typer.Exit(1)
    if not constant:
        return None
    if isinstance(constant, dict):
        return {str(k): str(v) for k, v in constant.items()}
    out: dict[str, str] = {}
    for item in constant:
        k, sep, v = item.partition("=")
        if not sep or not k.strip():
            logger.error(f"Invalid --constant '{item}'; expected KEY=VALUE")
            raise typer.Exit(1)
        out[k.strip()] = v
    return out


@group.command(name="sql")
def sql_command(
    sql: Annotated[
        str | None,
        typer.Option("--sql", "-s", help="Inline SQL string (semicolon-delimited)"),
    ] = None,
    file: Annotated[
        Path | None,
        typer.Option("--file", "-f", help="Path to SQL file (semicolon-delimited)"),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Optional output .json file path"),
    ] = None,
    dialect: Annotated[
        str | None,
        typer.Option(
            "--dialect",
            "-d",
            help="Optional SQLGlot dialect (e.g. bigquery, snowflake)",
        ),
    ] = None,
) -> SqlParseResult:
    """Parse semicolon-delimited SQL queries from --sql or --file into structured JSON."""
    _validate_sql_args(sql, file)
    result = parse_sql(sql=sql, file=file, dialect=dialect)
    _write_or_echo(result.model_dump_json(indent=2), output)
    return result


lookml_group = typer.Typer(
    name="lookml",
    help="Parse LookML from --path, --file, or --lookml with extensions/refinements and positions.",
    invoke_without_command=True,
    no_args_is_help=False,
)
group.add_typer(lookml_group, name="lookml")


@lookml_group.callback(invoke_without_command=True)
def lookml_callback(
    ctx: typer.Context,
    path: Annotated[
        Path | None,
        typer.Option("--path", "-p", help="Path to a LookML directory"),
    ] = None,
    file: Annotated[
        Path | None,
        typer.Option("--file", "-f", help="Path to a LookML file"),
    ] = None,
    lookml: Annotated[
        str | None,
        typer.Option("--lookml", "-l", help="Inline LookML string"),
    ] = None,
    manifest: ManifestOpt = None,
    constant: ConstantOpt = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Optional output .json file path"),
    ] = None,
) -> LookmlProject | None:
    """Parse LookML from --path, --file, or --lookml with extensions/refinements and positions."""
    if ctx.invoked_subcommand is None:
        return lookml_command(
            path=path,
            file=file,
            lookml=lookml,
            manifest=manifest,
            constant=constant,
            output=output,
        )
    return None


def lookml_command(
    path: Path | None = None,
    file: Path | None = None,
    lookml: str | None = None,
    output: Path | None = None,
    manifest: Path | None = None,
    constant: list[str] | dict[str, str] | None = None,
) -> LookmlProject:
    """Parse LookML from --path, --file, or --lookml with extensions/refinements and positions."""
    _validate_lookml_args(path, file, lookml, manifest=manifest)
    result = parse_lookml(
        path=path,
        file=file,
        lookml=lookml,
        manifest=manifest,
        constants=_parse_constant_overrides(constant),
    )
    _write_or_echo(
        result.model_dump_json(indent=2, by_alias=True, exclude_none=True), output
    )
    return result


@lookml_group.command(name="user-attributes")
def user_attributes_command(
    ctx: typer.Context,
    path: Annotated[
        Path | None,
        typer.Option(
            "--path",
            "-p",
            help="Path to a LookML directory (defaults to '.' when no other input is specified)",
        ),
    ] = None,
    file: Annotated[
        Path | None,
        typer.Option(
            "--file",
            "-f",
            help="Path to a LookML or LookML dashboard (.dashboard.lookml) file",
        ),
    ] = None,
    lookml: Annotated[
        str | None,
        typer.Option("--lookml", "-l", help="Inline LookML string"),
    ] = None,
    dashboard_file: Annotated[
        Path | None,
        typer.Option(
            "--dashboard-file",
            help=(
                "Path to a JSON file containing a Looker DashboardFilter object, "
                "a Dashboard object with dashboard_filters/dashboard_elements "
                "(e.g. looker-cli export), or a JSON array of DashboardFilter/Dashboard objects"
            ),
        ),
    ] = None,
    dashboard_json: Annotated[
        str | None,
        typer.Option(
            "--dashboard-json",
            "--dashboard-filters",
            help=(
                "Inline JSON string containing a DashboardFilter object, "
                "a Dashboard object with dashboard_filters/dashboard_elements, "
                "or a JSON array of DashboardFilter/Dashboard objects"
            ),
        ),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Optional output file path"),
    ] = None,
    validate: Annotated[
        bool,
        typer.Option(
            "--validate", help="Validate user attributes against Looker instance"
        ),
    ] = False,
    format: Annotated[
        str,
        typer.Option("--format", help="Output format (text or json)"),
    ] = "text",
    manifest: ManifestOpt = None,
    constant: ConstantOpt = None,
) -> LookmlUserAttributesResult:
    """Extract all user attributes referenced in a LookML project, LookML dashboards (.dashboard.lookml), or JSON dashboard filters with optional instance validation."""
    effective_path = (
        path
        if any(
            x is not None
            for x in (path, file, lookml, dashboard_file, dashboard_json)
        )
        else Path(".")
    )
    if effective_path is not None and not effective_path.exists():
        logger.error(f"LookML path not found: {effective_path}")
        raise typer.Exit(1)
    if file is not None and not file.exists():
        logger.error(f"LookML file not found: {file}")
        raise typer.Exit(1)
    if dashboard_file is not None and not dashboard_file.exists():
        logger.error(f"Dashboard JSON file not found: {dashboard_file}")
        raise typer.Exit(1)
    if format.lower() not in ("text", "json"):
        logger.error(f"Invalid format: '{format}'. Must be 'text' or 'json'")
        raise typer.Exit(1)

    try:
        result = parse_user_attributes(
            path=effective_path,
            file=file,
            lookml=lookml,
            dashboard_file=dashboard_file,
            dashboard_json=dashboard_json,
            validate=validate,
            ctx=ctx,
            manifest=manifest,
            constants=_parse_constant_overrides(constant, manifest),
        )
    except ValueError as e:
        logger.error(str(e))
        raise typer.Exit(1)

    formatted = format_user_attributes(result, format=format.lower())
    _write_or_echo(formatted, output)
    return result


@lookml_group.command(name="snapshot")
def snapshot_command(
    path: Annotated[
        Path,
        typer.Option("--path", "-p", help="Path to LookML directory to snapshot"),
    ],
    update: Annotated[
        bool,
        typer.Option(
            "--update",
            "-u",
            help="Update snapshots in place with received data",
        ),
    ] = False,
    ci: Annotated[
        bool,
        typer.Option(
            "--ci",
            help="CI mode: fail on missing or mismatched snapshots without writing",
        ),
    ] = False,
    only: Annotated[
        str | None,
        typer.Option(
            "--only",
            help="Comma-separated list of objects to snapshot (tests, access, measures, connections, manifest)",
        ),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option(
            "--model", "-m", help="Optional model name filter for snapshot"
        ),
    ] = None,
    format: Annotated[
        Literal["console", "json"],
        typer.Option("--format", help="Output format: console or json"),
    ] = "console",
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Optional output file path"),
    ] = None,
    allow_additions: Annotated[
        bool,
        typer.Option(
            "--allow-additions",
            help="Pass on additive snapshot changes; fail only on material modifications or removals",
        ),
    ] = False,
    base_path: Annotated[
        Path | None,
        typer.Option(
            "--base-path",
            help="Optional base LookML or snapshot directory to compare against instead of <path>/__snapshots__",
        ),
    ] = None,
    manifest: ManifestOpt = None,
    constant: ConstantOpt = None,
) -> LookmlSnapshotResult:
    """Jest-style LookML snapshot testing to guard tests, access controls, measure labels, connections, and manifest changes."""
    result, console_output = run_lookml_snapshot(
        path=path,
        update=update,
        ci=ci,
        only=only,
        model=model,
        format_=format,
        allow_additions=allow_additions,
        base_path=base_path,
        manifest=manifest,
        constants=_parse_constant_overrides(constant, manifest),
    )
    if format == "json":
        _write_or_echo(result.model_dump_json(indent=2), output)
    else:
        _write_or_echo(console_output, output)

    if not result.success:
        raise typer.Exit(1)
    return result


@lookml_group.command(name="translations")
def translations_command(
    path: Annotated[
        Path,
        typer.Option("--path", "-p", help="Path to a LookML directory"),
    ],
    locale: Annotated[
        str | None,
        typer.Option("--locale", "-l", help="Optional specific locale to evaluate"),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Optional output file path"),
    ] = None,
    format: Annotated[
        str,
        typer.Option("--format", help="Output format: console, json, or text"),
    ] = "console",
    strict: Annotated[
        bool,
        typer.Option(
            "--strict",
            help="Exit non-zero if missing or bypassed translations or missing labels are detected",
        ),
    ] = False,
    validate: Annotated[
        bool,
        typer.Option(
            "--validate",
            help="Alias for --strict",
        ),
    ] = False,
    manifest: ManifestOpt = None,
    constant: ConstantOpt = None,
) -> TranslationAnalysisResult:
    """Detect missing and bypassed locale strings across LookML models, explores, views, and fields."""
    if not path.exists():
        logger.error(f"LookML path not found: {path}")
        raise typer.Exit(1)

    try:
        result = analyze_lookml_translations(
            path=path,
            locale=locale,
            manifest=manifest,
            constants=_parse_constant_overrides(constant, manifest),
        )
    except (ValueError, FileNotFoundError) as e:
        logger.error(str(e))
        raise typer.Exit(1)

    fmt = format.lower()
    if fmt == "json":
        text = result.model_dump_json(indent=2)
    elif fmt in ("text", "txt"):
        text = format_translations_text(result)
    elif fmt == "console":
        text = format_translations_console(result)
    else:
        logger.error(
            f"Invalid format '{format}'. Supported formats: console, json, text"
        )
        raise typer.Exit(1)

    _write_or_echo(text, output)

    if (strict or validate) and result.missing_translations:
        raise typer.Exit(1)

    return result
@group.command(name="sql-lookml-compare")
def sql_lookml_compare_command(
    sql: Annotated[
        str | None,
        typer.Option("--sql", "-s", help="Inline SQL string (semicolon-delimited)"),
    ] = None,
    sql_file: Annotated[
        Path | None,
        typer.Option("--sql-file", help="Path to SQL file (semicolon-delimited)"),
    ] = None,
    path: Annotated[
        Path | None,
        typer.Option("--path", "-p", help="Path to a LookML directory"),
    ] = None,
    lookml_file: Annotated[
        Path | None,
        typer.Option("--lookml-file", "-f", help="Path to a LookML file"),
    ] = None,
    lookml: Annotated[
        str | None,
        typer.Option("--lookml", "-l", help="Inline LookML string"),
    ] = None,
    dialect: Annotated[
        str | None,
        typer.Option(
            "--dialect",
            "-d",
            help="Optional SQLGlot dialect (e.g. bigquery, snowflake)",
        ),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Optional output .json file path"),
    ] = None,
    describe: Annotated[
        bool,
        typer.Option(
            "--describe",
            help="Include high-level property documentation (_doc) in output JSON",
        ),
    ] = False,
    sql_db: Annotated[
        str | None,
        typer.Option(
            "--sql-db",
            envvar="LKR_SQL_DB",
            help="Default database/project for unqualified SQL tables",
        ),
    ] = None,
    sql_schema: Annotated[
        str | None,
        typer.Option(
            "--sql-schema",
            envvar="LKR_SQL_SCHEMA",
            help="Default schema/dataset for unqualified SQL tables",
        ),
    ] = None,
    lkml_conn: Annotated[
        str | None,
        typer.Option(
            "--lkml-conn",
            envvar="LKR_LKML_CONN",
            help="Looker connection name override for LookML views",
        ),
    ] = None,
    lkml_db: Annotated[
        str | None,
        typer.Option(
            "--lkml-db",
            envvar="LKR_LKML_DB",
            help="Database/project override for LookML views",
        ),
    ] = None,
    lkml_schema: Annotated[
        str | None,
        typer.Option(
            "--lkml-schema",
            envvar="LKR_LKML_SCHEMA",
            help="Schema/dataset override for LookML views",
        ),
    ] = None,
    manifest: ManifestOpt = None,
    constant: ConstantOpt = None,
) -> SqlToLookmlResult:
    """Compare and map SQL queries (--sql / --sql-file) to LookML views and fields (--path / --lookml-file / --lookml) with file and line numbers."""
    _validate_sql_args(sql, sql_file, "--sql-file")
    _validate_lookml_args(path, lookml_file, lookml, "--lookml-file", manifest=manifest)
    try:
        result = parse_sql_to_lookml(
            sql=sql,
            sql_file=sql_file,
            path=path,
            lookml_file=lookml_file,
            lookml=lookml,
            dialect=dialect,
            describe=describe,
            sql_db=sql_db,
            sql_schema=sql_schema,
            lkml_conn=lkml_conn,
            lkml_db=lkml_db,
            lkml_schema=lkml_schema,
            manifest=manifest,
            constants=_parse_constant_overrides(constant),
        )
    except ValueError as e:
        logger.error(str(e))
        raise typer.Exit(1)
    _write_or_echo(
        result.model_dump_json(indent=2, by_alias=True, exclude_none=True), output
    )
    return result


@group.command(name="lookml-to-api")
def lookml_to_api_command(
    path: Annotated[
        Path | None,
        typer.Option("--path", "-p", help="Path to a LookML directory"),
    ] = None,
    file: Annotated[
        Path | None,
        typer.Option("--file", "-f", help="Path to a LookML file"),
    ] = None,
    lookml: Annotated[
        str | None,
        typer.Option("--lookml", "-l", help="Inline LookML string"),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Optional LookML model name filter"),
    ] = None,
    explore: Annotated[
        str | None,
        typer.Option("--explore", "-e", help="Optional LookML explore name filter"),
    ] = None,
    exclude_hidden: Annotated[
        bool,
        typer.Option(
            "--exclude-hidden",
            help="Exclude hidden explores and hidden fields from output",
        ),
    ] = False,
    validate: Annotated[
        bool,
        typer.Option(
            "--validate",
            help="Fail with non-zero exit code on duplicate field logic, alias collisions, '* 100' paired with literal '%' value_format, or raw percentile/stddev/variance SQL in type: number measures",
        ),
    ] = False,
    manifest: ManifestOpt = None,
    constant: ConstantOpt = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Optional output .json file path"),
    ] = None,
) -> LookmlToApiResult:
    """Generate Looker API all_lookml_models and lookml_model_explore responses from LookML."""
    _validate_lookml_args(path, file, lookml, manifest=manifest)
    result = parse_lookml_to_api(
        path=path,
        file=file,
        lookml=lookml,
        model=model,
        explore=explore,
        exclude_hidden=exclude_hidden,
        manifest=manifest,
        constants=_parse_constant_overrides(constant),
    )
    _write_or_echo(result.model_dump_json(indent=2, by_alias=True), output)
    if validate:
        dup_msgs = [
            f"Explore '{exp_id}': {err.get('message', err)}"
            for exp_id, exp_obj in result.lookml_model_explores.items()
            for err in (exp_obj.errors or [])
        ]
        if dup_msgs:
            for msg in dup_msgs:
                logger.error(msg)
            raise typer.Exit(1)
    return result


@group.command(name="lookml-database-compare")
def lookml_database_compare_command(
    ctx: typer.Context,
    path: Annotated[
        Path | None,
        typer.Option("--path", "-p", exists=True, help="Path to a LookML directory"),
    ] = None,
    lookml_file: Annotated[
        Path | None,
        typer.Option("--lookml-file", "-f", exists=True, help="Path to a LookML file"),
    ] = None,
    lookml: Annotated[
        str | None,
        typer.Option("--lookml", "-l", help="Inline LookML string"),
    ] = None,
    model: Annotated[
        list[str] | None,
        typer.Option("--model", "-m", help="Filter to one or more LookML models (repeatable)"),
    ] = None,
    explore: Annotated[
        list[str] | None,
        typer.Option("--explore", "-e", help="Filter to one or more LookML explores (repeatable)"),
    ] = None,
    columns: Annotated[
        bool,
        typer.Option("--columns", "-c", help="Include physical columns referenced on each table"),
    ] = False,
    validate: Annotated[
        bool,
        typer.Option("--validate", help="Compare compiled LookML tables against the database schema"),
    ] = False,
    validate_columns: Annotated[
        bool,
        typer.Option("--validate-columns", help="Validate compiled tables and columns against the database schema"),
    ] = False,
    db_schema_file: Annotated[
        Path | None,
        typer.Option(
            "--db-schema-file",
            exists=True,
            help="Path to JSON file containing database schema for offline validation",
        ),
    ] = None,
    format: Annotated[
        Literal["console", "json", "txt"],
        typer.Option("--format", help="Output format: console, json, txt"),
    ] = "console",
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Optional output file path"),
    ] = None,
    manifest: ManifestOpt = None,
    constant: ConstantOpt = None,
) -> LookmlDatabaseCompareResult:
    """Compile explore SQL and validate tables and columns against the database.

    Complements Looker's CI/CD and `spectacles` SQL Validator: while SQL validators
    verify that LookML fields generate runnable SQL across transformations, this
    command checks bidirectional schema coverage—verifying both that all database
    tables and columns are modeled in LookML (`unmodeled_in_lookml`) and that LookML
    references exist in the database (`missing_in_database`).
    """
    _validate_lookml_args(path, lookml_file, lookml, "--lookml-file", manifest=manifest)
    sdk = None
    try:
        auth = get_auth(ctx)
        if auth.get_current_instance():
            sdk = auth.get_current_sdk(prompt_refresh_invalid_token=False)
    except (Exception, typer.Exit):  # noqa: BLE001
        sdk = None

    try:
        result = parse_lookml_database_compare(
            path=path,
            lookml_file=lookml_file,
            lookml=lookml,
            model=model,
            explore=explore,
            columns=columns,
            validate=validate,
            validate_columns=validate_columns,
            db_schema_file=db_schema_file,
            sdk=sdk,
            manifest=manifest,
            constants=_parse_constant_overrides(constant),
        )
    except (ValueError, FileNotFoundError) as e:
        logger.error(str(e))
        raise typer.Exit(1)

    formatted = format_compare_result(result, fmt=format)
    _write_or_echo(formatted, output)
    return result
