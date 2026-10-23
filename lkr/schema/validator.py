import functools
import importlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

# ponytail: pure-Python stdlib fallback when Linux _schema_rs.so isn't loadable (Windows/macOS/ARM);
# single-core ~5k queries/s ceiling — switch to maturin + cibuildwheel matrix if non-Linux batch throughput matters.
try:
    _schema_rs: Any = importlib.import_module("lkr.schema._schema_rs")
except ImportError:
    _schema_rs = None

_FIELD_REF_RE = re.compile(r"\$\{([^}]*)\}")
_SORT_ITEM_RE = re.compile(r"^([A-Za-z0-9_.]+)(?:\s+(?:asc|desc))?(?:\s+\d+)?$")
_READ_ONLY_KEYS = frozenset({
    "can", "id", "slug", "client_id", "share_url", "expanded_share_url",
    "url", "has_table_calculations", "filter_config", "visible_ui_sections",
})
_CUSTOM_MEASURE_TYPES = frozenset({
    "average", "average_distinct", "count", "count_distinct", "list", "max", "median",
    "median_distinct", "min", "number", "percent_of_previous", "percent_of_total",
    "percentile", "percentile_distinct", "running_total", "sum", "sum_distinct",
    "string", "yesno", "date",
})


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _str_set(v: Any) -> set[str]:
    return {x for x in v if isinstance(x, str)} if isinstance(v, list) else set()


def _compile_anchor_re(pat: str) -> re.Pattern[str] | None:
    try:
        return re.compile(f"^(?:{pat})\\Z")
    except re.error:
        return None


class _PyExploreValidator:
    def __init__(self, schema_json: str) -> None:
        schema = json.loads(schema_json)
        defs_re = {
            name: (compiled, pat)
            for name, dval in (schema.get("$defs") or {}).items()
            if isinstance(dval, dict)
            and isinstance(pat := dval.get("pattern"), str)
            and (compiled := _compile_anchor_re(pat))
        }
        top_props = p if isinstance(p := schema.get("properties"), dict) else {}
        self.allowed_top_keys = set(top_props)
        self.allowed_result_formats = _str_set((top_props.get("result_format") or {}).get("enum"))
        top_lim = (top_props.get("limit") or {}).get("default")
        self.default_top_limit = top_lim if _is_int(top_lim) else 500

        b = top_props.get("body")
        body_props = bp if isinstance(b, dict) and isinstance(bp := b.get("properties"), dict) else {}
        self.allowed_body_keys = set(body_props)
        em = (body_props.get("model") or {}).get("const")
        self.expected_model = em if isinstance(em, str) else None
        ev = (body_props.get("view") or {}).get("const")
        self.expected_view = ev if isinstance(ev, str) else None
        bl = (body_props.get("limit") or {}).get("default")
        self.default_body_limit = bl if isinstance(bl, str) else "500"

        self.base_fields_set = _str_set(((body_props.get("fields") or {}).get("items") or {}).get("enum"))
        self.base_pivots_set = _str_set(((body_props.get("pivots") or {}).get("items") or {}).get("enum"))
        self.measure_only_set = self.base_fields_set - self.base_pivots_set

        self.filter_rules: dict[str, tuple[str, Any, str]] = {}
        f_props = (body_props.get("filters") or {}).get("properties")
        if isinstance(f_props, dict):
            for fname, pschema in f_props.items():
                if (
                    isinstance(pschema, dict)
                    and isinstance(ref := pschema.get("$ref"), str)
                    and ref.startswith("#/$defs/")
                    and (hit := defs_re.get(ref[8:]))
                ):
                    self.filter_rules[fname] = ("pattern", hit[0], hit[1])
                elif isinstance(pschema, dict) and isinstance(earr := pschema.get("enum"), list):
                    strs = [x for x in earr if isinstance(x, str)]
                    self.filter_rules[fname] = ("enum", set(strs), "[" + ", ".join(f"'{x}'" for x in strs) + "]")
                elif (
                    isinstance(pschema, dict)
                    and isinstance(pat := pschema.get("pattern"), str)
                    and (cre := _compile_anchor_re(pat))
                ):
                    self.filter_rules[fname] = ("pattern", cre, pat)
                else:
                    self.filter_rules[fname] = ("any", None, "")

        self.schema_all_ref_fields = self.base_fields_set | set(self.filter_rules)

    @staticmethod
    def _sanitize_body(body_map: dict[str, Any]) -> dict[str, Any]:
        return {
            k: str(v) if k in ("limit", "column_limit") and _is_int(v) else v
            for k, v in body_map.items()
            if k not in _READ_ONLY_KEYS and v is not None
        }

    @staticmethod
    def _validate_expr_refs(
        expr: str,
        valid_fields: set[str],
        disallowed_tcs: set[str] | None,
        self_name: str | None,
        path: str,
        errors: list[str],
    ) -> None:
        for m in _FIELD_REF_RE.finditer(expr):
            raw = m.group(1).strip()
            if not raw:
                errors.append(f"{path}: empty field reference '${{}}' is not allowed")
                continue
            norm = (
                raw.removesuffix(":row_total")
                if raw.endswith(":row_total")
                else raw.removesuffix(":total")
            ).strip()
            if self_name is not None and norm == self_name:
                errors.append(
                    f"{path}: dynamic field '{self_name}' cannot reference itself in '${{{raw}}}'"
                )
            elif disallowed_tcs is not None and norm in disallowed_tcs:
                errors.append(
                    f"{path}: SQL expression cannot reference post-query table_calculation '${{{raw}}}'"
                )
            elif norm not in valid_fields:
                errors.append(
                    f"{path}: referenced field '${{{raw}}}' is not a valid visible explore field or dynamic_field .name"
                )

    def _validate_filter_map(
        self, filters_obj: dict[str, Any], path: str, errors: list[str]
    ) -> None:
        for k, v in filters_obj.items():
            prop_path = f"{path}.{k}"
            rule = self.filter_rules.get(k)
            if rule is None:
                errors.append(f"{prop_path}: unknown or hidden field '{k}' is not allowed")
            elif v is None:
                continue
            elif not isinstance(v, str):
                errors.append(f"{prop_path}: expected string filter expression")
            elif rule[0] == "enum" and v not in rule[1]:
                errors.append(f"{prop_path}: value '{v}' is not in allowed values {rule[2]}")
            elif rule[0] == "pattern" and not rule[1].search(v):
                errors.append(
                    f"{prop_path}: value '{v}' does not match filter expression pattern '{rule[2]}'"
                )

    def _validate_single(self, raw_val: Any) -> tuple[bool, list[str], list[str], str | None]:
        if not isinstance(raw_val, dict):
            return (False, ["$: expected query payload to be a JSON object"], [], None)

        payload: dict[str, Any]
        if "body" in raw_val:
            body_val = raw_val["body"]
            if not isinstance(body_val, dict):
                return (False, ["$.body: expected object"], [], None)
            payload = {k: v for k, v in raw_val.items() if k != "body"}
            payload.setdefault("result_format", "json")
            payload["body"] = self._sanitize_body(body_val)
        else:
            payload = {"result_format": "json", "body": self._sanitize_body(raw_val)}

        payload.setdefault("limit", self.default_top_limit)
        body: dict[str, Any] = payload["body"]
        if "model" not in body and self.expected_model is not None:
            body["model"] = self.expected_model
        if "view" not in body and self.expected_view is not None:
            body["view"] = self.expected_view
        body.setdefault("limit", self.default_body_limit)

        errors: list[str] = []
        warnings: list[str] = []
        dim_dyn: list[str] = []
        non_dim_dyn: list[str] = []
        tc_names: set[str] = set()
        dyn_items: list[Any] = []
        dyn_ok = False

        if "dynamic_fields" in body:
            raw_dyn = body["dynamic_fields"]
            if isinstance(raw_dyn, str):
                try:
                    decoded = json.loads(raw_dyn)
                    if isinstance(decoded, list):
                        dyn_items, dyn_ok = decoded, True
                    else:
                        errors.append(
                            "$.body.dynamic_fields: JSON string must decode to a JSON array"
                        )
                except ValueError as e:
                    errors.append(f"$.body.dynamic_fields: invalid JSON string ({e})")
            elif isinstance(raw_dyn, list):
                dyn_items, dyn_ok = list(raw_dyn), True
            elif raw_dyn is not None:
                errors.append(
                    "$.body.dynamic_fields: expected array or JSON-encoded array string"
                )

            if dyn_ok:
                for item in dyn_items:
                    if isinstance(item, dict):
                        if isinstance(d := item.get("dimension"), str) and d:
                            dim_dyn.append(d)
                        elif isinstance(m := item.get("measure"), str) and m:
                            non_dim_dyn.append(m)
                        elif isinstance(tc := item.get("table_calculation"), str) and tc:
                            non_dim_dyn.append(tc)
                            tc_names.add(tc)

        all_ref = self.schema_all_ref_fields | set(dim_dyn) | set(non_dim_dyn)
        all_fields = self.base_fields_set | set(dim_dyn) | set(non_dim_dyn)
        all_pivots = self.base_pivots_set | set(dim_dyn)
        non_dim_set = set(non_dim_dyn)

        if dyn_ok:
            for idx, item in enumerate(dyn_items):
                ipath = f"$.body.dynamic_fields[{idx}]"
                if not isinstance(item, dict):
                    errors.append(f"{ipath}: expected object")
                    continue
                dname = d if isinstance(d := item.get("dimension"), str) and d else None
                mname = m if isinstance(m := item.get("measure"), str) and m else None
                tname = t if isinstance(t := item.get("table_calculation"), str) and t else None
                if (dname is not None) + (mname is not None) + (tname is not None) != 1:
                    errors.append(
                        f"{ipath}: value must match exactly one dynamic field kind (CustomDimension, CustomMeasure, or TableCalculation)"
                    )
                    continue
                self_name = dname or mname or tname
                has_expr = isinstance(e := item.get("expression"), str) and bool(e)
                has_calc = (
                    isinstance(ct := item.get("calculation_type"), str)
                    and bool(ct)
                    and isinstance(item.get("args"), list)
                )
                has_bo = isinstance(bo := item.get("based_on"), str) and bool(bo)

                if dname is not None and not (has_expr or has_calc or has_bo):
                    errors.append(
                        f"{ipath}: CustomDimension must specify 'expression', 'based_on', or 'calculation_type' + 'args'"
                    )
                elif mname is not None:
                    if isinstance(mt := item.get("type"), str) and mt not in _CUSTOM_MEASURE_TYPES:
                        errors.append(
                            f"{ipath}.type: value '{mt}' is not in allowed custom measure types"
                        )
                    if not (has_bo or has_expr):
                        errors.append(
                            f"{ipath}: CustomMeasure must specify 'based_on' or 'expression'"
                        )
                    if (fval := item.get("filters")) is not None:
                        if isinstance(fval, dict):
                            self._validate_filter_map(fval, f"{ipath}.filters", errors)
                        else:
                            errors.append(f"{ipath}.filters: expected object")
                elif tname is not None:
                    if not (has_expr or has_calc):
                        errors.append(
                            f"{ipath}: TableCalculation must specify either 'expression' or 'calculation_type' + 'args'"
                        )
                    if isinstance(sf := item.get("source_field"), str) and sf not in all_ref:
                        errors.append(
                            f"{ipath}.source_field: '{sf}' is not a valid visible explore field or dynamic_field .name"
                        )
                    if isinstance(aarr := item.get("args"), list):
                        for aidx, aval in enumerate(aarr):
                            if isinstance(aval, str) and aval not in all_ref:
                                errors.append(
                                    f"{ipath}.args[{aidx}]: '{aval}' is not a valid visible explore field or dynamic_field .name"
                                )
                if isinstance(bo := item.get("based_on"), str) and bo not in all_ref:
                    errors.append(
                        f"{ipath}.based_on: '{bo}' is not a valid visible explore field or dynamic_field .name"
                    )

                disallowed = None if tname is not None else tc_names
                for ekey in ("expression", "filter_expression"):
                    if isinstance(estr := item.get(ekey), str) and estr:
                        self._validate_expr_refs(
                            estr, all_ref, disallowed, self_name, f"{ipath}.{ekey}", errors
                        )

        if self.expected_model is not None and body.get("model") != self.expected_model:
            errors.append(
                f"$.body.model: expected const '{self.expected_model}', got {body.get('model')!r}"
            )
        if self.expected_view is not None and body.get("view") != self.expected_view:
            errors.append(
                f"$.body.view: expected const '{self.expected_view}', got {body.get('view')!r}"
            )

        if (fval := body.get("fields")) is not None:
            if isinstance(fval, list):
                for idx, item in enumerate(fval):
                    if not isinstance(item, str):
                        errors.append(f"$.body.fields[{idx}]: expected string")
                    elif item not in all_fields:
                        errors.append(
                            f"$.body.fields[{idx}]: '{item}' is not a valid visible dimension, measure, or dynamic_field .name"
                        )
            else:
                errors.append("$.body.fields: expected array")

        if (pval := body.get("pivots")) is not None:
            if isinstance(pval, list):
                for idx, item in enumerate(pval):
                    if not isinstance(item, str):
                        errors.append(f"$.body.pivots[{idx}]: expected string")
                    elif item not in all_pivots:
                        if item in self.measure_only_set:
                            errors.append(
                                f"$.body.pivots[{idx}]: measure '{item}' cannot be used as a pivot (pivots must be dimensions or dimension_like dynamic_fields)"
                            )
                        elif item in non_dim_set:
                            errors.append(
                                f"$.body.pivots[{idx}]: dynamic_field '{item}' is a measure or table_calculation and cannot be used as a pivot"
                            )
                        else:
                            errors.append(
                                f"$.body.pivots[{idx}]: '{item}' is not a valid visible dimension or dimension_like dynamic_field .name"
                            )
            else:
                errors.append("$.body.pivots: expected array")

        if body.get("column_limit") is not None and not (
            isinstance(pv := body.get("pivots"), list) and pv
        ):
            warnings.append(
                "$.body.column_limit: 'column_limit' is set without 'pivots' (column_limit only applies to pivoted queries)"
            )

        if (flt := body.get("filters")) is not None:
            if isinstance(flt, dict):
                self._validate_filter_map(flt, "$.body.filters", errors)
            else:
                errors.append("$.body.filters: expected object")

        if (sval := body.get("sorts")) is not None:
            if isinstance(sval, list):
                for idx, item in enumerate(sval):
                    if not isinstance(item, str):
                        errors.append(f"$.body.sorts[{idx}]: expected string")
                    elif item == "__UNSORTED__":
                        continue
                    elif not (m := _SORT_ITEM_RE.match(item)):
                        errors.append(
                            f"$.body.sorts[{idx}]: invalid sort expression '{item}' (expected '<field>', '<field> desc', '<field> 0', or '__UNSORTED__')"
                        )
                    else:
                        sf = m.group(1)
                        if sf not in all_fields and not (
                            sf.endswith("__sort_") and sf[:-7] in all_pivots
                        ):
                            errors.append(
                                f"$.body.sorts[{idx}]: unknown or hidden sort field '{sf}'"
                            )
            else:
                errors.append("$.body.sorts: expected array")

        for key, arr_err in (
            ("fill_fields", "$.body.fill_fields: expected array"),
            ("subtotals", "$.body.subtotals: expected array of dimensions"),
        ):
            if (aval := body.get(key)) is not None:
                if isinstance(aval, list):
                    for idx, item in enumerate(aval):
                        if not isinstance(item, str):
                            errors.append(
                                f"$.body.{key}[{idx}]: must be a non-hidden dimension or dimension_like dynamic field"
                            )
                        elif item not in all_pivots:
                            errors.append(
                                f"$.body.{key}[{idx}]: '{item}' must be a non-hidden dimension or dimension_like dynamic field"
                            )
                else:
                    errors.append(arr_err)

        if (fe := body.get("filter_expression")) is not None:
            if isinstance(fe, str):
                self._validate_expr_refs(
                    fe, all_ref, tc_names, None, "$.body.filter_expression", errors
                )
            else:
                errors.append("$.body.filter_expression: expected string")

        for k in body:
            if k not in self.allowed_body_keys:
                errors.append(f"$.body.{k}: unknown or hidden field '{k}' is not allowed")

        for k, v in payload.items():
            if k == "body":
                continue
            if k not in self.allowed_top_keys:
                errors.append(f"$.{k}: unknown property '{k}' is not allowed")
            elif (
                k == "result_format"
                and isinstance(v, str)
                and self.allowed_result_formats
                and v not in self.allowed_result_formats
            ):
                errors.append(f"$.result_format: value '{v}' is not in allowed values")

        if errors:
            return (False, errors, warnings, None)

        norm_body = dict(body)
        if isinstance(norm_body.get("dynamic_fields"), list):
            norm_body["dynamic_fields"] = json.dumps(
                norm_body["dynamic_fields"], separators=(",", ":"), sort_keys=True
            )
        return (True, errors, warnings, json.dumps({**payload, "body": norm_body}))

    def validate_batch_json(
        self, queries_json: list[str]
    ) -> list[tuple[bool, list[str], list[str], str | None]]:
        out: list[tuple[bool, list[str], list[str], str | None]] = []
        for q_str in queries_json:
            try:
                out.append(self._validate_single(json.loads(q_str)))
            except ValueError as e:
                out.append((False, [f"Invalid query JSON: {e}"], [], None))
        return out


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
    if _schema_rs is not None:
        return _schema_rs.RustExploreValidator(schema_json)
    return _PyExploreValidator(schema_json)


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
