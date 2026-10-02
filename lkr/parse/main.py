from pathlib import Path
from typing import Annotated

import typer

from lkr.logger import logger
from lkr.parse.lookml import LookmlProject, parse_lookml
from lkr.parse.lookml_to_api import LookmlToApiResult, parse_lookml_to_api
from lkr.parse.sql import SqlParseResult, parse_sql
from lkr.parse.sql_to_lookml import SqlToLookmlResult, parse_sql_to_lookml

__all__ = [
    "group",
    "lookml_command",
    "lookml_to_api_command",
    "sql_command",
    "sql_to_api_command",
    "sql_to_lookml_command",
]

group = typer.Typer(
    name="parse",
    help="Parse SQL and LookML into structured components",
    no_args_is_help=True,
)


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
) -> None:
    if sum(x is not None for x in (path, file, lookml)) != 1:
        logger.error(f"Specify exactly one of --path, {file_flag}, or --lookml")
        raise typer.Exit(1)
    for p, label in ((path, "path"), (file, "file")):
        if p is not None and not p.exists():
            logger.error(f"LookML {label} not found: {p}")
            raise typer.Exit(1)


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
            "--dialect", "-d", help="Optional SQLGlot dialect (e.g. bigquery, snowflake)"
        ),
    ] = None,
) -> SqlParseResult:
    """Parse semicolon-delimited SQL queries from --sql or --file into structured JSON."""
    _validate_sql_args(sql, file)
    result = parse_sql(sql=sql, file=file, dialect=dialect)
    _write_or_echo(result.model_dump_json(indent=2), output)
    return result


@group.command(name="lookml")
def lookml_command(
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
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Optional output .json file path"),
    ] = None,
) -> LookmlProject:
    """Parse LookML from --path, --file, or --lookml with modelAssembly, extensions/refinements, and positions."""
    _validate_lookml_args(path, file, lookml)
    result = parse_lookml(path=path, file=file, lookml=lookml)
    _write_or_echo(
        result.model_dump_json(indent=2, by_alias=True, exclude_none=True), output
    )
    return result


@group.command(name="sql-to-lookml")
def sql_to_lookml_command(
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
            "--dialect", "-d", help="Optional SQLGlot dialect (e.g. bigquery, snowflake)"
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
) -> SqlToLookmlResult:
    """Map SQL queries (--sql / --sql-file) to LookML views and fields (--path / --lookml-file / --lookml) with file and line numbers."""
    _validate_sql_args(sql, sql_file, "--sql-file")
    _validate_lookml_args(path, lookml_file, lookml, "--lookml-file")
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
        )
    except ValueError as e:
        logger.error(str(e))
        raise typer.Exit(1)
    _write_or_echo(
        result.model_dump_json(indent=2, by_alias=True, exclude_none=True), output
    )
    return result


@group.command(name="sql-to-api")
def sql_to_api_command(
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
            "--dialect", "-d", help="Optional SQLGlot dialect (e.g. bigquery, snowflake)"
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
) -> SqlToLookmlResult:
    """Map SQL queries (--sql / --sql-file) to LookML views and fields (alias for sql-to-lookml)."""
    return sql_to_lookml_command(
        sql=sql,
        sql_file=sql_file,
        path=path,
        lookml_file=lookml_file,
        lookml=lookml,
        dialect=dialect,
        output=output,
        describe=describe,
        sql_db=sql_db,
        sql_schema=sql_schema,
        lkml_conn=lkml_conn,
        lkml_db=lkml_db,
        lkml_schema=lkml_schema,
    )


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
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Optional output .json file path"),
    ] = None,
) -> LookmlToApiResult:
    """Generate Looker API all_lookml_models and lookml_model_explore responses from LookML."""
    _validate_lookml_args(path, file, lookml)
    result = parse_lookml_to_api(
        path=path,
        file=file,
        lookml=lookml,
        model=model,
        explore=explore,
    )
    _write_or_echo(result.model_dump_json(indent=2, by_alias=True), output)
    return result

