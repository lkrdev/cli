import copy
import functools
import importlib
import json
import re
import types
from dataclasses import dataclass, field
from typing import cast

from looker_sdk.rtl import transport

from lkr.schema.builder import build_explore_query_schema, normalize_explores_map

# ponytail: pure-Python stdlib fallback when Linux _schema_rs.so isn't loadable (Windows/macOS/ARM);
# single-core ~5k queries/s ceiling — switch to maturin + cibuildwheel matrix if non-Linux batch throughput matters.
try:
    _schema_rs: types.ModuleType | None = importlib.import_module("lkr.schema._schema_rs")
except ImportError:
    _schema_rs = None

_FIELD_REF_RE = re.compile(r"\$\{([^}]*)\}")
_SORT_ITEM_RE = re.compile(r"^([A-Za-z0-9_.]+)(?:\s+(?:asc|desc))?(?:\s+\d+)?$")
_DT_GTE_RE = re.compile(r"^>=\s*(\d{4})(?:[-/](\d{2})[-/](\d{2}))?$")
_DT_GT_RE = re.compile(r"^>\s*(\d{4})[-/](\d{2})[-/](\d{2})$")
_DT_LTE_RE = re.compile(r"^<=\s*(\d{4})(?:[-/](\d{2})[-/](\d{2}))?$")
_DT_BETWEEN_RE = re.compile(r"^(?i:BETWEEN)\s+(\S+)\s+(?i:AND)\s+(\S+)$")
_DT_TF_SUFFIX_RE = re.compile(r"_(?:year|month|quarter|week)$")
_NUM_RANGE_RE = re.compile(
    r"^(?:(?i:BETWEEN)\s+)?(-?\d+(?:\.\d+)?)\s+(?i:to|AND)\s+(-?\d+(?:\.\d+)?)$"
)
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


def _is_int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _str_set(v: object) -> set[str]:
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

        self.filter_rules: dict[str, tuple[str, set[str] | re.Pattern[str] | None, str]] = {}
        self.filter_kinds: dict[str, str] = {}
        f_props = (body_props.get("filters") or {}).get("properties")
        if isinstance(f_props, dict):
            for fname, pschema in f_props.items():
                if not isinstance(pschema, dict):
                    self.filter_rules[fname] = ("any", None, "")
                    continue
                ref = pschema.get("$ref")
                if not isinstance(ref, str) and isinstance(any_of := pschema.get("anyOf"), list):
                    ref = next(
                        (
                            x.get("$ref")
                            for x in any_of
                            if isinstance(x, dict) and isinstance(x.get("$ref"), str)
                        ),
                        None,
                    )
                if isinstance(ref, str) and ref.startswith("#/$defs/"):
                    def_name = ref[8:]
                    self.filter_kinds[fname] = def_name
                    if hit := defs_re.get(def_name):
                        self.filter_rules[fname] = ("pattern", hit[0], hit[1])
                    else:
                        self.filter_rules[fname] = ("any", None, "")
                elif isinstance(earr := pschema.get("enum"), list):
                    strs = [x for x in earr if isinstance(x, str)]
                    self.filter_rules[fname] = (
                        "enum",
                        set(strs),
                        "[" + ", ".join(f"'{x}'" for x in strs) + "]",
                    )
                elif isinstance(pat := pschema.get("pattern"), str) and (
                    cre := _compile_anchor_re(pat)
                ):
                    self.filter_rules[fname] = ("pattern", cre, pat)
                else:
                    self.filter_rules[fname] = ("any", None, "")

        self.schema_all_ref_fields = self.base_fields_set | set(self.filter_rules)

    def _coerce_filter_map(self, filters_obj: dict[str, object]) -> dict[str, object]:
        out: dict[str, object] = {}
        for k, v in filters_obj.items():
            if not isinstance(v, str):
                out[k] = v
                continue
            s = v.strip()
            kind = self.filter_kinds.get(k, "")
            new_k, new_v = k, v
            if kind == "DateTimeFilterExpression":
                if m := _DT_GTE_RE.match(s):
                    new_v = f"after {m.group(1)}-{m.group(2) or '01'}-{m.group(3) or '01'}"
                elif m := _DT_GT_RE.match(s):
                    new_v = f"after {m.group(1)}-{m.group(2)}-{m.group(3)}"
                elif m := _DT_LTE_RE.match(s):
                    new_v = f"before {m.group(1)}-{m.group(2) or '12'}-{m.group(3) or '31'}"
                elif m := _DT_BETWEEN_RE.match(s):
                    a = m.group(1).strip("\"'")
                    b = m.group(2).strip("\"'")
                    new_v = f"{a} to {b}"
                if new_v.startswith(("after ", "before ")) and _DT_TF_SUFFIX_RE.search(k):
                    base_date = _DT_TF_SUFFIX_RE.sub("_date", k)
                    if (
                        base_date in self.filter_rules
                        and base_date not in filters_obj
                        and base_date not in out
                    ):
                        new_k = base_date
            elif kind == "NumberFilterExpression":
                if m := _NUM_RANGE_RE.match(s):
                    new_v = f"[{m.group(1)}, {m.group(2)}]"
            elif kind == "StringFilterExpression":
                su = s.upper()
                if su in ("NOT NULL", "IS NOT NULL", "!= NULL", "<> NULL") or s == "-null":
                    new_v = "-NULL"
                elif su in ("IS NULL", "= NULL") or s == "null":
                    new_v = "NULL"
            out[new_k] = new_v
        return out

    @staticmethod
    def _sanitize_body(body_map: dict[str, object]) -> dict[str, object]:
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
            norm = raw.removesuffix(":row_total").removesuffix(":total").strip()
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
        self, filters_obj: dict[str, object], path: str, errors: list[str]
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
            elif rule[0] == "enum" and isinstance(rule[1], set) and v not in rule[1]:
                errors.append(f"{prop_path}: value '{v}' is not in allowed values {rule[2]}")
            elif rule[0] == "pattern" and isinstance(rule[1], re.Pattern) and not rule[1].search(v):
                errors.append(
                    f"{prop_path}: value '{v}' does not match filter expression pattern '{rule[2]}'"
                )

    def _validate_single(self, raw_val: object) -> tuple[bool, list[str], list[str], str | None]:
        if not isinstance(raw_val, dict):
            return (False, ["$: expected query payload to be a JSON object"], [], None)

        payload: dict[str, object]
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
        body = payload["body"]
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
        dyn_items: list[object] = []
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
                norm_dyn: list[object] = []
                tc_ref_fields: list[str] = []
                for item in dyn_items:
                    if isinstance(item, dict):
                        item = dict(item)
                        if isinstance(d := item.get("dimension"), str) and d:
                            item["label"] = item.get("label") or d
                            dim_dyn.append(d)
                        elif isinstance(m := item.get("measure"), str) and m:
                            item["label"] = item.get("label") or m
                            if item.get("filter_expression") in ("", None):
                                item.pop("filter_expression", None)
                            if isinstance(item.get("filters"), dict):
                                item["filters"] = self._coerce_filter_map(item["filters"])
                            non_dim_dyn.append(m)
                        elif isinstance(tc := item.get("table_calculation"), str) and tc:
                            item["label"] = item.get("label") or tc
                            non_dim_dyn.append(tc)
                            tc_names.add(tc)
                            if isinstance(expr := item.get("expression"), str) and expr:
                                for m_ref in _FIELD_REF_RE.finditer(expr):
                                    norm_ref = m_ref.group(1).strip().removesuffix(":row_total").removesuffix(":total").strip()
                                    if norm_ref in self.base_fields_set and norm_ref not in tc_ref_fields:
                                        tc_ref_fields.append(norm_ref)
                    norm_dyn.append(item)
                dyn_items = norm_dyn
                body["dynamic_fields"] = dyn_items
                if isinstance(cur_fields := body.get("fields"), list):
                    synced = [
                        f for f in cur_fields if not (isinstance(f, str) and f in tc_names)
                    ]
                    for name in [
                        *dim_dyn,
                        *(x for x in non_dim_dyn if x not in tc_names),
                        *tc_ref_fields,
                    ]:
                        if name not in synced:
                            synced.append(name)
                    body["fields"] = synced

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
                flt = self._coerce_filter_map(flt)
                body["filters"] = flt
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
    normalized_query: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        res: dict[str, object] = {
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
        }
        if self.normalized_query is not None:
            res["normalized_query"] = self.normalized_query
        return res


@functools.lru_cache(maxsize=64)
def _compile_validator(schema_json: str) -> _PyExploreValidator:
    if _schema_rs is not None:
        return cast(_PyExploreValidator, _schema_rs.RustExploreValidator(schema_json))
    return _PyExploreValidator(schema_json)


def get_rust_validator(schema: dict[str, object]) -> _PyExploreValidator:
    """Return a cached Rust `RustExploreValidator` instance for `schema`."""
    return _compile_validator(json.dumps(schema, sort_keys=True))


def validate_batch_queries(
    queries: list[dict[str, object] | str] | list[dict[str, object]] | list[str],
    schema: dict[str, object],
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
    query_payload: dict[str, object],
    schema: dict[str, object],
) -> ValidationResult:
    """Validate `query_payload` against `schema` using the compiled Rust `RustExploreValidator`."""
    return validate_batch_queries([query_payload], schema)[0]


def _validate_subquery_with_fallback(
    raw_query: dict[str, object],
    model: str,
    cmap: dict[str, dict[str, object]],
    candidates: list[str],
) -> ValidationResult:
    raw_body = raw_query.get("body")
    body = copy.deepcopy(raw_body if isinstance(raw_body, dict) else raw_query)
    body["model"] = model
    explore = str(body.get("view") or (candidates[0] if candidates else ""))
    body["view"] = explore
    res: ValidationResult | None = None
    if (edata := cmap.get(explore)) is not None:
        res = validate_query({"result_format": "json", "body": body}, build_explore_query_schema(model, explore, edata))
        if res.valid:
            return res
    for alt_exp in candidates:
        if alt_exp != explore and (alt_edata := cmap.get(alt_exp)) is not None:
            alt_res = validate_query(
                {"result_format": "json", "body": {**body, "view": alt_exp}},
                build_explore_query_schema(model, alt_exp, alt_edata),
            )
            if alt_res.valid:
                return alt_res
    return res or ValidationResult(valid=False, errors=[f"$.body.view: unknown explore '{explore}'"])


def validate_merge_query(
    payload: dict[str, object],
    model: str,
    explores_map: dict[str, object] | list[dict[str, object]] | list[object],
    candidate_explores: list[str] | None = None,
) -> ValidationResult:
    """Validate a single `WriteQuery` or multi-Explore `source_queries` Merged Results spec."""
    if not isinstance(payload, dict):
        return ValidationResult(valid=False, errors=["$: expected query payload to be a JSON object"])
    cmap = normalize_explores_map(model, explores_map)
    candidates = candidate_explores or list(cmap.keys())
    if "source_queries" not in payload:
        return _validate_subquery_with_fallback(payload, model, cmap, candidates)

    errors: list[str] = []
    if (jt := payload.get("join_type")) is not None and str(jt).lower() not in ("left", "inner"):
        errors.append(f"$.join_type: expected 'left' or 'inner', got '{jt}'")
    raw_sqs = payload.get("source_queries")
    if not isinstance(raw_sqs, list) or len(raw_sqs) < 2:
        return ValidationResult(valid=False, errors=["$.source_queries: expected at least 2 source queries", *errors])

    norm_spec = copy.deepcopy(payload)
    for k in ("limit", "column_limit"):
        if _is_int(norm_spec.get(k)):
            norm_spec[k] = str(norm_spec[k])
    if (vc := norm_spec.get("vis_config")) is not None and not isinstance(vc, dict):
        errors.append("$.vis_config: expected object")
    sqs = cast(list[dict[str, object]], norm_spec["source_queries"])
    warnings: list[str] = []

    for idx, sq in enumerate(sqs):
        if not isinstance(sq, dict):
            errors.append(f"$.source_queries[{idx}]: expected object")
        elif not isinstance(sq.get("query"), dict):
            if q_part := {k: v for k, v in sq.items() if k not in ("name", "merge_fields", "join_type")}:
                for k in q_part:
                    sq.pop(k, None)
                sq["query"] = q_part
            else:
                errors.append(f"$.source_queries[{idx}]: expected object with 'query' dict")
    if errors:
        return ValidationResult(valid=False, errors=errors)

    sq0_q = cast(dict[str, object], sqs[0]["query"])
    p0 = cast(dict[str, object], sq0_q["body"] if isinstance(sq0_q.get("body"), dict) else sq0_q)
    p0_fields = p0.setdefault("fields", [])
    for idx, sq in enumerate(sqs[1:], start=1):
        sq_q = cast(dict[str, object], sq["query"])
        q = cast(dict[str, object], sq_q["body"] if isinstance(sq_q.get("body"), dict) else sq_q)
        q_fields = q.setdefault("fields", [])
        mfields = sq.get("merge_fields")
        if not isinstance(mfields, list) or not mfields:
            shared = [f for f in (p0_fields if isinstance(p0_fields, list) else []) if isinstance(f, str) and isinstance(q_fields, list) and f in q_fields]
            if not shared:
                errors.append(f"$.source_queries[{idx}].merge_fields: expected non-empty array")
                continue
            mfields = [{"field_name": f, "source_field_name": f} for f in shared]
            sq["merge_fields"] = mfields
        for mf in (m for m in mfields if isinstance(m, dict)):
            for fn, target in ((mf.get("field_name"), p0_fields), (mf.get("source_field_name"), q_fields)):
                if isinstance(fn, str) and fn and isinstance(target, list) and fn not in target:
                    target.append(fn)

    def _parse_dyn(raw: object) -> list[dict[str, object]]:
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                return []
        return [d for d in raw if isinstance(d, dict)] if isinstance(raw, list) else []

    def _dyn_names(items: list[dict[str, object]]) -> set[str]:
        return {
            n
            for df in items
            for k in ("dimension", "measure", "table_calculation", "name")
            if isinstance(n := df.get(k), str) and n
        }

    top_dyn_items = _parse_dyn(norm_spec.get("dynamic_fields")) + _parse_dyn(norm_spec.get("table_calculations"))
    needs_merge_total = bool(norm_spec.get("total")) or any(
        ":total" in str(df.get("expression", "")) for df in top_dyn_items
    )
    if needs_merge_total:
        norm_spec["total"] = True

    top_sorts = [s for s in raw_ts if isinstance(s, str)] if isinstance(raw_ts := norm_spec.get("sorts"), list) else []
    union_fields: set[str] = _dyn_names(top_dyn_items)
    for idx, sq in enumerate(sqs):
        sub_res = _validate_subquery_with_fallback(cast(dict[str, object], sq["query"]), model, cmap, candidates)
        warnings.extend(sub_res.warnings)
        if not sub_res.valid or sub_res.normalized_query is None:
            errors.extend(f"$.source_queries[{idx}] ({sq.get('name', idx)}): {e}" for e in sub_res.errors)
        else:
            norm_q = cast(dict[str, object], sub_res.normalized_query["body"])
            if norm_q.get("limit") in (None, "500", 500):
                norm_q["limit"] = "5000"
            if needs_merge_total:
                norm_q["total"] = True
            nq_fields = _str_set(norm_q.get("fields"))
            raw_mfs = sq.get("merge_fields")
            m_map = {
                str(mf["field_name"]): str(mf["source_field_name"])
                for mf in (raw_mfs if isinstance(raw_mfs, list) else [])
                if isinstance(mf, dict) and isinstance(mf.get("field_name"), str) and isinstance(mf.get("source_field_name"), str)
            }
            if top_sorts and not norm_q.get("sorts") and (
                sub_sorts := [
                    f"{sub_f}{s[m.end(1):]}"
                    for s in top_sorts
                    if (m := _SORT_ITEM_RE.match(s)) and (sub_f := m_map.get(m.group(1), m.group(1))) in nq_fields
                ]
            ):
                norm_q["sorts"] = sub_sorts
            sq["query"] = norm_q
            union_fields |= nq_fields
            if isinstance(dyn_str := norm_q.get("dynamic_fields"), str):
                union_fields |= _dyn_names(_parse_dyn(dyn_str))

    if (sorts := norm_spec.get("sorts")) is not None:
        if not isinstance(sorts, list):
            errors.append("$.sorts: expected array")
        else:
            for s_idx, s_item in enumerate(sorts):
                m_sort = _SORT_ITEM_RE.match(s_item) if isinstance(s_item, str) else None
                if not isinstance(s_item, str) or (s_item != "__UNSORTED__" and not m_sort):
                    errors.append(f"$.sorts[{s_idx}]: invalid sort expression '{s_item}'")
                elif m_sort and (sf := m_sort.group(1)) not in union_fields:
                    errors.append(f"$.sorts[{s_idx}]: unknown sort field '{sf}'")

    return ValidationResult(valid=not errors, errors=errors, warnings=warnings, normalized_query=None if errors else norm_spec)


def execute_looker_query(
    sdk: object,
    spec: dict[str, object] | list[dict[str, object]],
    model: str | None = None,
    explores_data: dict[str, object] | list[dict[str, object]] | list[object] | None = None,
    candidate_explores: list[str] | None = None,
    transport_options: transport.TransportOptions | None = None,
) -> list[dict[str, object]]:
    """Validate a query or merge spec when explore metadata is available and execute via ExtendedLooker40SDK."""
    from lkr.extended_sdk_methods.main import ExtendedLooker40SDK

    payload: dict[str, object] | list[dict[str, object]] = {"source_queries": spec} if isinstance(spec, list) and spec else spec
    if isinstance(payload, dict) and payload:
        sqs = payload.get("source_queries")
        qs = [sq.get("query", sq) for sq in sqs if isinstance(sq, dict)] if isinstance(sqs, list) else [payload]
        bodies = [q.get("body", q) for q in qs if isinstance(q, dict)]
        raw_model = model or payload.get("model") or next((b.get("model") for b in bodies if isinstance(b, dict) and b.get("model")), None)
        resolved_model = str(raw_model) if raw_model else None
        exp_map: dict[str, object] | list[dict[str, object]] | list[object] | None = explores_data
        if exp_map is None and resolved_model and hasattr(sdk, "lookml_model_explore"):
            fetched: dict[str, object] = {}
            for b in bodies:
                if isinstance(b, dict) and isinstance(v := b.get("view"), str) and v and v not in fetched:
                    try:
                        ed = cast(ExtendedLooker40SDK, sdk).lookml_model_explore(str(b.get("model") or resolved_model), v)
                        ed_dict = ed if isinstance(ed, dict) else (ed.__dict__ if hasattr(ed, "__dict__") else {})
                        if isinstance(ed_dict, dict) and "fields" in ed_dict:
                            fetched[v] = ed_dict
                    except Exception:  # noqa: BLE001, S110
                        pass
            if fetched:
                exp_map = fetched
        if exp_map is not None and resolved_model:
            val_res = validate_merge_query(payload, resolved_model, exp_map, candidate_explores)
            if not val_res.valid or val_res.normalized_query is None:
                raise ValueError("; ".join(val_res.errors))
            payload = val_res.normalized_query

    if hasattr(sdk, "execute_looker_query"):
        return cast(ExtendedLooker40SDK, sdk).execute_looker_query(
            payload, transport_options=transport_options
        )
    return ExtendedLooker40SDK.execute_looker_query(
        cast(ExtendedLooker40SDK, sdk),
        payload,
        transport_options=transport_options,
    )


execute_validated_looker_queries = execute_looker_query
