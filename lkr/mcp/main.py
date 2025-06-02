# server.py
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Callable, List, Literal, Self, Set

import duckdb
import typer
from fastmcp import FastMCP
from looker_sdk.sdk.api40.models import (
    SqlQueryCreate,
    WriteQuery,
)
from pydantic import BaseModel, Field, computed_field
from pydash import get

from lkr.auth_service import get_auth
from lkr.classes import LkrCtxObj
from lkr.logger import logger

__all__ = ["group"]

current_instance: str | None = None
ctx_lkr: LkrCtxObj | None = None


# Create an MCP server
mcp = FastMCP("lkr:mcp")

group = typer.Typer(name="spectacles")

db_loc: Path | None = None


def get_db_loc() -> Path:
    global db_loc
    if db_loc is None:
        db_path = os.path.expanduser("~/.lkr")
        db_loc = Path(db_path) / "mcp_search_db"
        db_loc.mkdir(exist_ok=True, parents=True)
    return db_loc


def get_database_search_file(prefix: str = "") -> Path:
    p = get_db_loc() / f"{prefix + '.' if prefix else ''}looker_connection_search.jsonl"
    if not p.exists():
        p.touch()
    return p


def get_connection_registry_file(
    type: Literal["connection", "database", "schema", "table"], prefix: str = ""
) -> Path:
    return (
        get_db_loc()
        / f"{prefix + '.' if prefix else ''}looker_connection_registry.{type}.jsonl"
    )


# Initialize DuckDB connection
conn = duckdb.connect(database=":memory:", read_only=False)

# Install and load the FTS extension
conn.execute("INSTALL 'fts'")
conn.execute("LOAD 'fts'")
conn.execute("INSTALL 'json'")
conn.execute("LOAD 'json'")


class SpectaclesResponse(BaseModel):
    success: bool
    result: Any | None = None
    error: str | None = None
    sql: str | None = None
    share_url: str | None = None


class SpectaclesRequest(BaseModel):
    model: Annotated[
        str,
        Field(
            description="the model to run a test query against, you can find this by the filenames in the repository, they will end with .model.lkml. You should not pass in the .model.lkml extension.",
            default="",
        ),
    ]
    explore: Annotated[
        str,
        Field(
            description="the explore to run a test query against, you can find this by finding explore: <name> {} in any file in the repository",
            default="",
        ),
    ]
    fields: Annotated[
        List[str],
        Field(
            description="this should be the list of fields you want to return from the test query. If the user does not provide them, use all that have changed in your current context",
            default=[],
        ),
    ]


def get_mcp_sdk(ctx: LkrCtxObj | typer.Context):
    sdk = get_auth(ctx).get_current_sdk(prompt_refresh_invalid_token=False)
    sdk.auth.settings.agent_tag += "-mcp"
    return sdk


@mcp.tool()
def get_spectacles(
    model: Annotated[
        str,
        Field(
            description="the model to run a test query against, you can find this by the filenames in the repository, they will end with .model.lkml. You should not pass in the .model.lkml extension."
        ),
    ],
    explore: Annotated[
        str,
        Field(
            description="the explore to run a test query against, you can find this by finding explore: <name> {} in any file in the repository"
        ),
    ],
    fields: Annotated[
        List[str],
        Field(
            description="this should be the list of fields you want to return from the test query. If the user does not provide them, use all that have changed in your current context. The syntax of the field should be <view>.<field> name. The view will be the name of the view as it appears in the explore, or aliased from it with from or view_name"
        ),
    ],
):
    """
    run a spectacles query to validate the changes to the model
    """
    req = SpectaclesRequest(model=model, explore=explore, fields=fields)
    global ctx_lkr
    if not ctx_lkr:
        # logger.error("No Looker context found")
        raise typer.Exit(1)
    sdk = get_mcp_sdk(ctx_lkr)
    returned_sql = None
    share_url = None
    try:
        query = sdk.create_query(
            body=WriteQuery(
                model=req.model, view=req.explore, fields=req.fields, limit="0"
            )
        )
        if query.id is None:
            raise Exception("Failed to create query")

        share_url = f"{sdk.auth.settings.base_url}/x/{query.client_id}"
        sql = sdk.run_query(query_id=query.id, result_format="sql")
        new_sql = f"""
SELECT * FROM (
    {sql}
) WHERE 1=2
"""
        returned_sql = new_sql
        create_query = sdk.create_sql_query(
            body=SqlQueryCreate(
                model_name=req.model,
                sql=new_sql,
            )
        )
        if create_query.slug is None:
            raise Exception("Failed to create sql query")
        result = sdk.run_sql_query(
            slug=create_query.slug, result_format="json", download="true"
        )
        return SpectaclesResponse(
            success=True, share_url=share_url, sql=returned_sql, result=result
        )
    except Exception as e:
        return SpectaclesResponse(
            success=False,
            error=str(e),
            share_url=share_url,
            sql=returned_sql,
            result=result,
        )


def now() -> datetime:
    return datetime.now(timezone.utc)


class Connection(BaseModel):
    connection: str
    updated_at: datetime = Field(default_factory=now)

    @computed_field(return_type=str)
    @property
    def fully_qualified_name(self) -> str:
        return self.connection


class Database(Connection):
    database: str

    @computed_field(return_type=str)
    @property
    def fully_qualified_name(self) -> str:
        return f"{self.connection}.{self.database}"


class Schema(Database):
    database_schema_name: str

    @computed_field(return_type=str)
    @property
    def fully_qualified_name(self) -> str:
        return f"{self.connection}.{self.database}.{self.database_schema_name}"


class Table(Schema):
    database_table_name: str

    @computed_field(return_type=str)
    @property
    def fully_qualified_name(self) -> str:
        return f"{self.connection}.{self.database}.{self.database_schema_name}.{self.database_table_name}"


class Row(Table):
    database_column_name: str
    data_type_database: str
    data_type_looker: str

    @computed_field(return_type=str)
    @property
    def fully_qualified_name(self) -> str:
        return f"{self.connection}.{self.database}.{self.database_schema_name}.{self.database_table_name}.{self.database_column_name}"

    def append(self, base_url: str) -> None:
        with open(get_database_search_file(base_url), "a") as f:
            f.write(self.model_dump_json() + "\n")

    def exists(self, base_url: str) -> bool:
        columns = conn.execute(
            f"SELECT * FROM read_json_auto('{get_database_search_file(base_url)}') WHERE fully_qualified_name = '{self.fully_qualified_name}'"
        ).fetchall()
        return len(columns) > 0


def ok[T](func: Callable[[], T], default: T) -> T:
    try:
        return func()
    except Exception:
        # logger.error(f"Error in {func.__name__}: {str(e)}")
        return default


def conn_registry_path(
    type: Literal["connection", "database", "schema", "table"], prefix: str = ""
) -> Path:
    file_loc = get_connection_registry_file(type, prefix)
    if not file_loc.exists():
        file_loc.touch()
    return file_loc


class ConnectionRegistry(BaseModel):
    connections: Set[str]
    databases: Set[str]
    schemas: Set[str]
    tables: Set[str]
    prefix: str = ""

    def append(self, obj: Connection | Database | Schema | Table) -> None:
        if isinstance(obj, Table):
            self.tables.add(obj.fully_qualified_name)
            with open(get_connection_registry_file("table", self.prefix), "a") as f:
                f.write(obj.model_dump_json() + "\n")
        elif isinstance(obj, Schema):
            self.schemas.add(obj.fully_qualified_name)
            with open(get_connection_registry_file("schema", self.prefix), "a") as f:
                f.write(obj.model_dump_json() + "\n")
        elif isinstance(obj, Database):
            self.databases.add(obj.fully_qualified_name)
            with open(get_connection_registry_file("database", self.prefix), "a") as f:
                f.write(obj.model_dump_json() + "\n")
        elif isinstance(obj, Connection):
            self.connections.add(obj.fully_qualified_name)
            with open(
                get_connection_registry_file("connection", self.prefix), "a"
            ) as f:
                f.write(obj.model_dump_json() + "\n")

    def check(
        self, type: Literal["connection", "database", "schema", "table"], value: str
    ) -> bool:
        if type == "connection":
            return value in self.connections
        elif type == "database":
            return value in self.databases
        elif type == "schema":
            return value in self.schemas
        elif type == "table":
            return value in self.tables
        else:
            raise ValueError(f"Invalid type: {type}")

    def load_connections(self, dt_filter: datetime | None = None) -> None:
        file = conn_registry_path("connection", self.prefix)
        # logger.debug(f"Loading connections from {file}")
        sql = f"SELECT connection FROM read_json_auto('{file}')"
        if dt_filter:
            sql += f" WHERE updated_at > '{dt_filter.isoformat()}'"
        try:
            results = conn.execute(sql).fetchall()
            for row in results:
                connection = Connection(connection=row[0])
                self.connections.add(connection.fully_qualified_name)
        except Exception:
            # logger.error(f"Error loading connections from {file}: {str(e)}")
            return

    def load_databases(self, dt_filter: datetime | None = None) -> None:
        file = conn_registry_path("database", self.prefix)
        sql = f"SELECT connection, database FROM read_json_auto('{file}')"
        if dt_filter:
            sql += f" WHERE updated_at > '{dt_filter.isoformat()}'"
        try:
            results = conn.execute(sql).fetchall()
            for row in results:
                database = Database(connection=row[0], database=row[1])
                self.databases.add(database.fully_qualified_name)
        except Exception:
            # logger.error(f"Error loading databases from {file}: {str(e)}")
            return

    def load_schemas(self, dt_filter: datetime | None = None) -> None:
        file = conn_registry_path("schema", self.prefix)
        sql = f"SELECT connection, database, database_schema_name FROM read_json_auto('{file}')"
        if dt_filter:
            sql += f" WHERE updated_at > '{dt_filter.isoformat()}'"
        try:
            results = conn.execute(sql).fetchall()
            for row in results:
                schema = Schema(
                    connection=row[0], database=row[1], database_schema_name=row[2]
                )
                self.schemas.add(schema.fully_qualified_name)
        except Exception:
            # logger.error(f"Error loading schemas from {file}: {str(e)}")
            return

    def load_tables(self, dt_filter: datetime | None = None) -> None:
        file = conn_registry_path("table", self.prefix)
        sql = f"SELECT connection, database, database_schema_name, database_table_name FROM read_json_auto('{file}')"
        if dt_filter:
            sql += f" WHERE updated_at > '{dt_filter.isoformat()}'"
        try:
            results = conn.execute(sql).fetchall()
            for row in results:
                table = Table(
                    connection=row[0],
                    database=row[1],
                    database_schema_name=row[2],
                    database_table_name=row[3],
                )
                self.tables.add(table.fully_qualified_name)
        except Exception:
            # logger.error(f"Error loading tables from {file}: {str(e)}")
            return

    @classmethod
    def initialize(cls, prefix: str = "") -> Self:
        registry = cls(
            connections=set(),
            databases=set(),
            schemas=set(),
            tables=set(),
            prefix=prefix,
        )
        registry.load_connections()
        registry.load_databases()
        registry.load_schemas()
        registry.load_tables()
        return registry


def populate_looker_connection_search_on_startup(ctx: typer.Context) -> None:
    """
    populate the looker connection search
    """
    global current_instance
    # logger.debug("Populating looker connection search")
    sdk = get_mcp_sdk(ctx)
    if not current_instance:
        # logger.error("No current instance found")
        raise typer.Abort()
    registry = ConnectionRegistry.initialize(prefix=current_instance)
    connections = ok(lambda: sdk.all_connections(), [])
    for connection in connections:
        if not connection.name:
            continue
        elif registry.check("connection", connection.name):
            # logger.debug(
            #     f"Skipping {connection.name} because it already exists in the registry"
            # )
            continue
        # logger.debug(f"Populating looker connection search for {connection.name}")
        databases = ok(lambda: sdk.connection_databases(connection.name or ""), [])
        for database in databases:
            if registry.check("database", database):
                # logger.debug(
                #     f"Skipping {database} because it already exists in the registry"
                # )
                continue
            # logger.debug(f"Populating looker connection search for {database}")
            schemas = ok(
                lambda: sdk.connection_schemas(
                    connection.name or "", database, cache=True, fields="name"
                ),
                [],
            )
            # logger.debug(f"Found {len(schemas)} schemas for {database}")
            for schema in schemas:
                if not schema.name:
                    continue
                elif registry.check("schema", schema.name):
                    logger.debug(
                        f"Skipping {schema.name} because it already exists in the registry"
                    )
                    continue
                logger.debug(f"Populating looker connection search for {schema.name}.")
                schema_tables = ok(
                    lambda: sdk.connection_tables(
                        connection.name,  # type: ignore
                        database=database,
                        schema_name=schema.name,  # type: ignore
                        table_limit=100000,
                    ),
                    [],
                )
                if len(schema_tables) == 0:
                    continue
                schema_name = get(schema_tables, "0.name", None)
                # logger.debug(f"Found {len(schema_tables)} tables for {schema.name}")
                for table in get(schema_tables, "0.tables", []):
                    if registry.check("table", table.name):
                        # logger.debug(
                        #     f"Skipping {table.name} because it already exists in the registry"
                        # )
                        continue
                    schema_columns = ok(
                        lambda: sdk.connection_columns(
                            connection.name,  # type: ignore
                            database=database,
                            schema_name=schema_name,
                            table_names=table.name,
                            cache=True,
                        ),
                        [],
                    )
                    logger.debug(
                        f"Found {len(get(schema_columns, '0.columns', []))} columns in {database}.{schema.name}.{table.name}"
                    )
                    for column in get(schema_columns, "0.columns", []):
                        Row(
                            connection=connection.name,
                            database=database,
                            database_schema_name=schema_name,
                            database_table_name=table.name,
                            database_column_name=column.name,
                            data_type_database=column.data_type_database,
                            data_type_looker=column.data_type_looker,
                        ).append(current_instance)

                    registry.append(
                        Table(
                            connection=connection.name,
                            database=database,
                            database_schema_name=schema_name,
                            database_table_name=table.name,
                        )
                    )
                registry.append(
                    Schema(
                        connection=connection.name,
                        database=database,
                        database_schema_name=schema_name,
                    )
                )
            registry.append(
                Database(
                    connection=connection.name,
                    database=database,
                )
            )

            if connection.dialect is None:
                continue
            if connection.dialect.name == "bigquery_standard_sql":
                database = "looker-private-demo"
                schema = "ecomm"
                ecomm_tables = sdk.connection_tables(
                    connection.name,
                    database=database,
                    schema_name=schema,
                    table_limit=100000,
                )
                if len(ecomm_tables) == 0:
                    continue
                schema_name = get(ecomm_tables, "0.name", None)
                for table in get(ecomm_tables, "0.tables", []):
                    if registry.check("table", table.name):
                        # logger.debug(
                        #     f"Skipping {table.name} because it already exists in the registry"
                        # )
                        continue
                    schema_columns = sdk.connection_columns(
                        connection.name,
                        database=database,
                        schema_name=schema,
                        table_names=table.name,
                    )
                    if len(schema_columns) == 0:
                        continue
                    for column in get(schema_columns, "0.columns", []):
                        Row(
                            connection=connection.name,
                            database=database,
                            database_schema_name=schema,
                            database_table_name=table.name,
                            database_column_name=column.name,
                            data_type_database=column.data_type_database,
                            data_type_looker=column.data_type_looker,
                        ).append(current_instance)

        registry.append(
            Connection(
                connection=connection.name,
            )
        )


def load_database_search_file(file_loc: Path) -> None:
    """
    load the database search file into a duckdb table and create FTS index
    """
    conn.execute(
        f"""
        CREATE OR REPLACE TABLE looker_connection_search AS
        SELECT *
        FROM read_json_auto('{file_loc}');
        """
    )

    # Create FTS index on fully_qualified_name
    conn.execute(
        """
        PRAGMA create_fts_index(
            'looker_connection_search', -- table
            'fully_qualified_name', -- index_id
            'fully_qualified_name' -- columns
        );
        """
    )


class SearchFullyQualifiedNamesRequest(BaseModel):
    search_term: str = Field(
        description="The search term to search for within the fully qualified column name. It will be converted to lowercase before searching. The fully quallified column name incluses database, schema, table, and column names."
    )


# Add a dynamic greeting resource
@mcp.tool()
def search_fully_qualified_names(req: SearchFullyQualifiedNamesRequest) -> List[dict]:
    """
    Use lkr to search fully qualified columns which include connection, database, schema, table, column names, and data types
    Returns a list of matching rows with their BM25 scores
    """
    result = conn.execute(
        """
        SELECT 
          connection, 
          database, 
          database_schema_name, 
          database_table_name, 
          database_column_name, 
          data_type_database, 
          data_type_looker, 
          fts_main_looker_connection_search.match_bm25(
            fully_qualified_name,
            ?
          ) AS score
        FROM looker_connection_search
        WHERE score IS NOT NULL
        ORDER BY score DESC
        LIMIT 10000
        """,
        [req.search_term.lower()],
        # [search_term, connections, databases, schemas, tables],
    ).fetchall()
    return [
        Row(
            connection=row[0],
            database=row[1],
            database_schema_name=row[2],
            database_table_name=row[3],
            database_column_name=row[4],
            data_type_database=row[5],
            data_type_looker=row[6],
        ).model_dump()
        for row in result
    ]


@group.callback()
def main(ctx: typer.Context):
    global ctx_lkr
    ctx_lkr = LkrCtxObj(force_oauth=False)
    validate_current_instance_database_search_file(ctx)


@group.command(name="run")
def run():
    mcp.run()


def check_for_database_search_file(ctx: typer.Context) -> None:
    global current_instance
    if current_instance:
        file_loc = get_database_search_file(current_instance)
        populate_looker_connection_search_on_startup(ctx)
        load_database_search_file(file_loc)
    else:
        # logger.error("No current instance found")
        raise typer.Abort()


def validate_current_instance_database_search_file(ctx: typer.Context) -> None:
    global current_instance
    check = get_auth(ctx).get_current_instance()
    if not current_instance:
        current_instance = check
        thread = threading.Thread(target=check_for_database_search_file, args=(ctx,))
        # thread.daemon = True
        thread.start()
    elif current_instance != check:
        current_instance = check
        thread = threading.Thread(target=check_for_database_search_file, args=(ctx,))
        # thread.daemon = True
        thread.start()
    else:
        pass


if __name__ == "__main__":
    current_instance = "d7"
    ctx_lkr = LkrCtxObj(force_oauth=False)
    mcp.run("sse")
