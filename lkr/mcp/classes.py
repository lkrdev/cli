# server.py
from datetime import datetime
from typing import Annotated, Any, List

import duckdb
from pydantic import BaseModel, Field, computed_field

from lkr.mcp.utils import get_database_search_file
from lkr.observability.classes import now


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

    def exists(self, conn: duckdb.DuckDBPyConnection, *, base_url: str) -> bool:
        columns = conn.execute(
            f"SELECT * FROM read_json_auto('{get_database_search_file(base_url)}') WHERE fully_qualified_name = '{self.fully_qualified_name}'"
        ).fetchall()
        return len(columns) > 0
