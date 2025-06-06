# server.py
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from lkr.logger import logger

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


def now() -> datetime:
    return datetime.now(timezone.utc)


def ok[T](func: Callable[[], T], default: T) -> T:
    try:
        return func()
    except Exception as e:
        logger.error(f"Error in {func.__name__}: {str(e)}")
        return default


def conn_registry_path(
    type: Literal["connection", "database", "schema", "table"], prefix: str = ""
) -> Path:
    file_loc = get_connection_registry_file(type, prefix)
    if not file_loc.exists():
        file_loc.touch()
    return file_loc
