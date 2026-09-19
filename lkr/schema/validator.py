import functools
import importlib
import json
from dataclasses import dataclass, field
from typing import Any

_schema_rs: Any = importlib.import_module("lkr.schema._schema_rs")


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    normalized_query: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        res: dict[str, Any] = {
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
        }
        if self.normalized_query is not None:
            res["normalized_query"] = self.normalized_query
        return res


@functools.lru_cache(maxsize=64)
def _compile_validator(schema_json: str) -> Any:
    return _schema_rs.RustExploreValidator(schema_json)


def get_rust_validator(schema: dict[str, Any]) -> Any:
    """Return a cached Rust `RustExploreValidator` instance for `schema`."""
    return _compile_validator(json.dumps(schema, sort_keys=True))


def validate_batch_queries(
    queries: list[dict[str, Any] | str],
    schema: dict[str, Any],
) -> list[ValidationResult]:
    """Validate a batch of queries in parallel across CPU cores via Rust `rayon`."""
    rust_val = get_rust_validator(schema)
    serialized = [q if isinstance(q, str) else json.dumps(q) for q in queries]
    raw_results = rust_val.validate_batch_json(serialized)
    return [
        ValidationResult(
            valid=is_valid,
            errors=list(errs),
            warnings=list(warns),
            normalized_query=json.loads(norm_json)
            if norm_json is not None
            else None,
        )
        for is_valid, errs, warns, norm_json in raw_results
    ]


def validate_query(
    query_payload: dict[str, Any],
    schema: dict[str, Any],
) -> ValidationResult:
    """Validate `query_payload` against `schema` using the compiled Rust `RustExploreValidator`."""
    return validate_batch_queries([query_payload], schema)[0]
