"""Jest-style LookML snapshot testing to guard tests, access controls, connections, and manifest."""

import difflib
import fnmatch
import json
import os
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from lkr.logger import logger
from lkr.parse.lookml import (
    LookmlExplore,
    LookmlFieldProperties,
    LookmlManifest,
    LookmlProject,
    LookmlTest,
    LookmlView,
    parse_lookml,
)

VALID_SNAPSHOT_OBJECTS = ("tests", "access", "connections", "manifest")


class LookmlSnapshotResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    success: bool
    project: str
    written: int = 0
    updated: int = 0
    passed: int = 0
    failed: int = 0
    total: int = 0
    requires_review: bool = False
    material_changes: list[str] = Field(default_factory=list)
    material_change_files: list[str] = Field(default_factory=list)
    required_reviewers: list[str] = Field(default_factory=list)
    diffs: list[str] = Field(default_factory=list)
    snapshots: dict[str, Any] = Field(default_factory=dict)
    message: str | None = None


def normalize_sql(sql: str | None) -> str | None:
    """Normalize multi-line and irregular whitespace in SQL expressions."""
    if sql is None:
        return None
    return re.sub(r"\s+", " ", sql).strip()


def strip_positions(
    val: Any, keys: tuple[str, ...] = ("line", "position", "$p")
) -> Any:
    """Recursively strip line and position fields for semantic equality comparisons."""
    if isinstance(val, dict):
        return {k: strip_positions(v, keys) for k, v in val.items() if k not in keys}
    if isinstance(val, list):
        return [strip_positions(x, keys) for x in val]
    return val


def _resolve_project_name(project: LookmlProject, path: Path) -> str:
    if project.manifest and project.manifest.project_name:
        return str(project.manifest.project_name)
    if isinstance(project.file, BaseModel):
        man = getattr(project.file, "manifest", None)
        if isinstance(man, LookmlManifest) and man.project_name:
            return str(man.project_name)
    return path.resolve().name or "project"


def _find_position(
    positions: Any,
    file_key: str | None,
    keys: list[str | int],
) -> tuple[str, int]:
    """Traverse positions to find (file, 1-indexed line)."""
    if not positions:
        return (f"{file_key or 'unknown'}.lkml", 1)

    pos_files = getattr(positions, "file", {}) or {}
    matched_file = f"{file_key}.lkml" if file_key and not file_key.endswith(".lkml") else (file_key or "unknown.lkml")
    matched_line = 1

    # Look up in pos_files
    target_files = (
        [matched_file] if matched_file in pos_files else list(pos_files.keys())
    )
    for f_name in target_files:
        curr = pos_files.get(f_name)
        if not isinstance(curr, dict):
            continue
        found = True
        for k in keys:
            if isinstance(curr, dict) and str(k) in curr:
                curr = curr[str(k)]
            else:
                found = False
                break
        if found and isinstance(curr, dict) and "$p" in curr:
            raw_p = curr["$p"]
            if isinstance(raw_p, (list, tuple)) and len(raw_p) >= 2:
                matched_line = int(raw_p[0]) + 1
                matched_file = f_name if f_name.endswith(".lkml") else f"{f_name}.lkml"
                return (matched_file, matched_line)

    return (matched_file, matched_line)


def _extract_explore_source_filters(raw_filters: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    items = (
        raw_filters
        if isinstance(raw_filters, list)
        else ([raw_filters] if raw_filters else [])
    )
    for item in items:
        d = (
            item.model_dump(exclude_none=True)
            if isinstance(item, BaseModel)
            else (item if isinstance(item, dict) else {})
        )
        if isinstance(d.get("field"), str) and d["field"]:
            out[d["field"]] = str(d.get("value", "") or "")
        for k, v in d.items():
            if not k.startswith("$") and k not in ("type", "field", "value"):
                out[k] = str(v)
    return dict(sorted(out.items()))


def _build_test_entry(
    test_name: str,
    t: LookmlTest,
    model_name: str,
    file_hint: str,
    positions: Any,
) -> dict[str, Any]:
    exp_sources: dict[str, Any] = {}
    explore_source_val = t.explore_source
    if isinstance(explore_source_val, dict):
        explore_source_dict = explore_source_val
    elif explore_source_val is not None:
        name = getattr(explore_source_val, "name_", None) or "explore_source"
        explore_source_dict = {name: explore_source_val}
    else:
        explore_source_dict = {}

    for exp_name, exp_src in sorted(explore_source_dict.items()):
        col_dict: dict[str, Any] = {}
        if getattr(exp_src, "column", None) and exp_src.column:
            for c_name, c_obj in sorted(exp_src.column.items()):
                col_dict[c_name] = {"field": getattr(c_obj, "field", None)}

        derived_col_dict: dict[str, Any] = {}
        if getattr(exp_src, "derived_column", None) and exp_src.derived_column:
            for dc_name, dc_obj in sorted(exp_src.derived_column.items()):
                derived_col_dict[dc_name] = {
                    "sql": normalize_sql(getattr(dc_obj, "sql", None))
                }

        exp_entry: dict[str, Any] = {
            "explore": exp_name,
            "column": col_dict,
            "derived_column": derived_col_dict if derived_col_dict else None,
            "expression_custom_filter": normalize_sql(
                getattr(exp_src, "expression_custom_filter", None)
            ),
            "limit": getattr(exp_src, "limit", None),
            "timezone": getattr(exp_src, "timezone", None),
        }
        if filters_dict := _extract_explore_source_filters(
            getattr(exp_src, "filters", None)
        ):
            exp_entry["filters"] = filters_dict
        exp_sources[exp_name] = exp_entry

    assert_dict: dict[str, Any] = {}
    if isinstance(t.assert_, dict):
        for a_name, a_obj in sorted(t.assert_.items()):
            assert_dict[a_name] = {
                "expression": normalize_sql(getattr(a_obj, "expression", None))
            }
    elif isinstance(t.assert_, list):
        for a_idx, a_obj in enumerate(t.assert_):
            a_name = getattr(a_obj, "name_", f"assert_{a_idx}") or f"assert_{a_idx}"
            assert_dict[a_name] = {
                "expression": normalize_sql(getattr(a_obj, "expression", None))
            }

    f_path, line_no = _find_position(positions, file_hint, ["test", test_name])
    return {
        "name": test_name,
        "model": model_name,
        "file": f_path,
        "line": line_no,
        "explore_source": exp_sources,
        "assert": assert_dict,
    }


def extract_tests_snapshot(
    project: LookmlProject,
    model_filter: str | None = None,
) -> dict[str, Any]:
    """Extract and normalize all LookML data tests."""
    tests_out: dict[str, Any] = {}
    positions = project.positions
    seen_tests: set[str] = set()

    def _add_tests(
        raw_tests: dict[str, Any] | None, model_name: str, file_hint: str
    ) -> None:
        for test_name, test_val in sorted((raw_tests or {}).items()):
            tests_list = test_val if isinstance(test_val, list) else [test_val]
            for idx, t in enumerate(tests_list):
                if isinstance(t, LookmlTest):
                    key = (
                        f"{model_name}.{test_name}"
                        if len(tests_list) == 1
                        else f"{model_name}.{test_name}_{idx}"
                    )
                    if key in tests_out:
                        continue
                    tests_out[key] = _build_test_entry(
                        test_name, t, model_name, file_hint, positions
                    )
                    seen_tests.add(test_name)

    for model_name, model_obj in sorted((project.model or {}).items()):
        if not model_filter or model_name == model_filter:
            _add_tests(model_obj.test, model_name, f"{model_name}.model")

    if not model_filter and isinstance(project.file, BaseModel):
        default_model = next(iter(sorted(project.model or {})), "standalone")
        for rel_key, file_entry in sorted(
            (getattr(project.file, "test", None) or {}).items()
        ):
            raw = getattr(file_entry, "test", None)
            if isinstance(raw, dict):
                _add_tests(
                    {k: v for k, v in raw.items() if k not in seen_tests},
                    default_model,
                    f"{rel_key}.test",
                )

    return tests_out


def extract_access_snapshot(
    project: LookmlProject,
    model_filter: str | None = None,
) -> dict[str, Any]:
    """Extract and normalize access grants, explore/view/field access controls."""
    grants_out: dict[str, Any] = {}
    explores_out: dict[str, Any] = {}
    views_out: dict[str, Any] = {}
    fields_out: dict[str, Any] = {}

    if not project.model:
        return {
            "access_grants": grants_out,
            "explores": explores_out,
            "views": views_out,
            "fields": fields_out,
        }

    positions = project.positions

    for model_name, model_obj in sorted(project.model.items()):
        if model_filter and model_name != model_filter:
            continue

        model_file_hint = f"{model_name}.model"

        # Model access grants
        raw_grants = getattr(model_obj, "access_grant", None)
        if raw_grants is None and hasattr(model_obj, "__pydantic_extra__") and model_obj.__pydantic_extra__:
            raw_grants = model_obj.__pydantic_extra__.get("access_grant")

        if isinstance(raw_grants, dict):
            for grant_name, grant_val in sorted(raw_grants.items()):
                f_path, line_no = _find_position(
                    positions, model_file_hint, ["access_grant", grant_name]
                )
                allowed_vals = []
                user_attr = None
                if isinstance(grant_val, dict):
                    user_attr = grant_val.get("user_attribute")
                    raw_av = grant_val.get("allowed_values") or []
                    allowed_vals = sorted(raw_av if isinstance(raw_av, list) else [str(raw_av)])
                elif hasattr(grant_val, "user_attribute"):
                    user_attr = getattr(grant_val, "user_attribute", None)
                    raw_av = getattr(grant_val, "allowed_values", []) or []
                    allowed_vals = sorted(raw_av if isinstance(raw_av, list) else [str(raw_av)])

                grants_out[f"{model_name}.{grant_name}"] = {
                    "model": model_name,
                    "name": grant_name,
                    "user_attribute": user_attr,
                    "allowed_values": allowed_vals,
                    "file": f_path,
                    "line": line_no,
                }

        # Explores access
        if model_obj.explore:
            for exp_name, exp_val in sorted(model_obj.explore.items()):
                exp_list = exp_val if isinstance(exp_val, list) else [exp_val]
                for exp_obj in exp_list:
                    if not isinstance(exp_obj, LookmlExplore):
                        continue
                    req_grants = sorted(exp_obj.required_access_grants or [])
                    acc_filter = exp_obj.access_filter
                    if req_grants or acc_filter:
                        f_path, line_no = _find_position(
                            positions, model_file_hint, ["explore", exp_name]
                        )
                        explores_out[f"{model_name}.{exp_name}"] = {
                            "model": model_name,
                            "explore": exp_name,
                            "required_access_grants": req_grants,
                            "access_filter": acc_filter,
                            "file": f_path,
                            "line": line_no,
                        }

        # Views and fields access
        if model_obj.view:
            for v_name, v_val in sorted(model_obj.view.items()):
                v_list = v_val if isinstance(v_val, list) else [v_val]
                for v_obj in v_list:
                    if not isinstance(v_obj, LookmlView):
                        continue

                    view_file_hint = f"{v_name}.view"
                    view_req_grants = sorted(v_obj.required_access_grants or [])
                    view_acc_filter = v_obj.access_filter
                    if view_req_grants or view_acc_filter:
                        f_path, line_no = _find_position(
                            positions, view_file_hint, ["view", v_name]
                        )
                        views_out[f"{model_name}.{v_name}"] = {
                            "model": model_name,
                            "view": v_name,
                            "required_access_grants": view_req_grants,
                            "access_filter": view_acc_filter,
                            "file": f_path,
                            "line": line_no,
                        }

                    # Check all field collections
                    for field_type in (
                        "dimension",
                        "dimension_group",
                        "measure",
                        "filter",
                        "parameter",
                    ):
                        collection = getattr(v_obj, field_type, None)
                        if not collection:
                            continue
                        if isinstance(collection, dict):
                            fields_dict = collection
                        elif isinstance(collection, list):
                            fields_dict = {
                                getattr(x, "name_", None) or f"unnamed_{i}": x
                                for i, x in enumerate(collection)
                                if x
                            }
                        else:
                            fields_dict = {
                                getattr(collection, "name_", "unnamed"): collection
                            }

                        for fld_name, fld_obj in sorted(fields_dict.items()):
                            if not isinstance(fld_obj, LookmlFieldProperties):
                                continue
                            fld_req_grants = sorted(fld_obj.required_access_grants or [])
                            fld_allowed_vals = []
                            if hasattr(fld_obj, "allowed_value") and fld_obj.allowed_value:
                                raw_av = fld_obj.allowed_value
                                if isinstance(raw_av, list):
                                    for av in raw_av:
                                        val_str = getattr(av, "value", None) or (av.get("value") if isinstance(av, dict) else str(av))
                                        if val_str is not None:
                                            fld_allowed_vals.append(val_str)
                                elif isinstance(raw_av, dict):
                                    fld_allowed_vals = [str(k) for k in raw_av]
                                fld_allowed_vals.sort()

                            fld_label = (
                                fld_obj.label if field_type == "measure" else None
                            )
                            if (
                                fld_req_grants
                                or fld_allowed_vals
                                or fld_label is not None
                            ):
                                f_path, line_no = _find_position(
                                    positions,
                                    view_file_hint,
                                    ["view", v_name, field_type, fld_name],
                                )
                                field_entry: dict[str, Any] = {
                                    "model": model_name,
                                    "view": v_name,
                                    "field": fld_name,
                                    "field_type": field_type,
                                    "required_access_grants": fld_req_grants,
                                    "allowed_values": fld_allowed_vals
                                    if fld_allowed_vals
                                    else None,
                                    "file": f_path,
                                    "line": line_no,
                                }
                                if fld_label is not None:
                                    field_entry["label"] = fld_label
                                fields_out[f"{model_name}.{v_name}.{fld_name}"] = (
                                    field_entry
                                )

    return {
        "access_grants": grants_out,
        "explores": explores_out,
        "views": views_out,
        "fields": fields_out,
    }


def extract_connections_snapshot(
    project: LookmlProject,
    model_filter: str | None = None,
) -> dict[str, Any]:
    """Extract and normalize model database connection bindings."""
    connections_out: dict[str, Any] = {}
    if not project.model:
        return connections_out

    positions = project.positions

    for model_name, model_obj in sorted(project.model.items()):
        if model_filter and model_name != model_filter:
            continue
        model_file_hint = f"{model_name}.model"
        f_path, line_no = _find_position(positions, model_file_hint, ["connection"])

        connections_out[model_name] = {
            "model": model_name,
            "connection": model_obj.connection,
            "file": f_path,
            "line": line_no,
        }

    return connections_out


def extract_manifest_snapshot(
    project: LookmlProject,
) -> dict[str, Any]:
    """Extract and normalize project manifest, constants, and extensions."""
    manifest_obj = project.manifest
    positions = project.positions

    if not manifest_obj:
        return {
            "present": False,
            "project_name": None,
        }

    f_path, line_no = _find_position(positions, "manifest", ["project_name"])

    constants_out: dict[str, Any] = {}
    if isinstance(manifest_obj.constant, dict):
        for c_name, c_obj in sorted(manifest_obj.constant.items()):
            cf_path, c_line = _find_position(positions, "manifest", ["constant", c_name])
            c_entry: dict[str, Any] = {
                "name": c_name,
                "value": getattr(c_obj, "value", None),
                "file": cf_path,
                "line": c_line,
            }
            if getattr(c_obj, "export", None) is not None:
                c_entry["export"] = getattr(c_obj, "export", None)
            constants_out[c_name] = c_entry

    includes = sorted(manifest_obj.includes or [])

    return {
        "present": True,
        "project_name": manifest_obj.project_name,
        "timezone": manifest_obj.timezone,
        "includes": includes,
        "constants": constants_out,
        "file": f_path,
        "line": line_no,
    }


def extract_snapshot_for_object(
    obj_name: str,
    project: LookmlProject,
    model_filter: str | None = None,
) -> dict[str, Any]:
    if obj_name == "tests":
        return extract_tests_snapshot(project, model_filter=model_filter)
    if obj_name == "access":
        return extract_access_snapshot(project, model_filter=model_filter)
    if obj_name == "connections":
        return extract_connections_snapshot(project, model_filter=model_filter)
    if obj_name == "manifest":
        return extract_manifest_snapshot(project)
    raise ValueError(f"Unknown snapshot object: {obj_name}")


def format_jest_diff(
    object_name: str,
    snap_path: Path,
    saved_data: dict[str, Any],
    current_data: dict[str, Any],
) -> str:
    """Format a Jest-style - Snapshot / + Received console diff with file/line reference."""
    # Find mismatched keys and their location
    file_ref = str(snap_path)
    line_ref = 1

    # Attempt to locate specific mismatch file and line recursively
    if isinstance(current_data, dict):

        def find_mismatch(curr: Any, saved: Any) -> tuple[str | None, int | None]:
            if isinstance(curr, dict):
                if (
                    "file" in curr
                    and "line" in curr
                    and strip_positions(saved) != strip_positions(curr)
                ):
                    return curr.get("file"), curr.get("line")
                for k, v in curr.items():
                    saved_v = saved.get(k) if isinstance(saved, dict) else None
                    f, l = find_mismatch(v, saved_v)
                    if f is not None:
                        return f, l
            return None, None

        f_ref, l_ref = find_mismatch(current_data, saved_data)
        if f_ref is not None:
            file_ref = f_ref
        if l_ref is not None:
            line_ref = l_ref

    header = f"● {object_name} > {file_ref}:{line_ref}\n"

    saved_str = json.dumps(saved_data, indent=2, sort_keys=True).splitlines()
    curr_str = json.dumps(current_data, indent=2, sort_keys=True).splitlines()

    diff_lines = list(
        difflib.unified_diff(
            saved_str,
            curr_str,
            fromfile="Snapshot",
            tofile="Received",
            lineterm="",
        )
    )

    diff_body = "\n".join(diff_lines) if diff_lines else "Content differed"
    return f"{header}\n- Snapshot\n+ Received\n\n{diff_body}"


_META_KEYS = ("file", "line", "position", "$p")


def _match_codeowner_pattern(pattern: str, rel_path: str) -> bool:
    rel = rel_path.strip("/")
    pat = pattern.strip()
    if not pat:
        return False
    if pat == "*":
        return True
    if pat.endswith("/"):
        prefix = pat.strip("/")
        if pat.startswith("/"):
            return rel == prefix or rel.startswith(f"{prefix}/")
        return (
            rel == prefix
            or rel.startswith(f"{prefix}/")
            or f"/{prefix}/" in f"/{rel}"
        )
    anchored = pat.startswith("/")
    clean = pat.lstrip("/")
    if (
        "/" not in clean
        and not anchored
        and fnmatch.fnmatchcase(Path(rel).name, clean)
    ):
        return True
    if "**" in clean:
        regex = (
            ("^" if anchored else "^(?:.*/)?")
            + re.escape(clean)
            .replace(r"\*\*/", "(?:.+/)?")
            .replace(r"\*\*", ".*")
            .replace(r"\*", "[^/]*")
            .replace(r"\?", "[^/]")
            + "$"
        )
        return bool(re.match(regex, rel))
    return fnmatch.fnmatchcase(rel, clean) or (
        not anchored and fnmatch.fnmatchcase(rel, f"*/{clean}")
    )


def resolve_codeowners(root_path: Path, files: list[str]) -> list[str]:
    """Resolve GitHub CODEOWNERS (last matching pattern wins) for relative file paths."""
    if not files:
        return []
    codeowners_file: Path | None = None
    owner_root = root_path.resolve()
    for base in [owner_root, *owner_root.parents]:
        for rel_candidate in (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"):
            cand = base / rel_candidate
            if cand.is_file():
                codeowners_file = cand
                owner_root = base
                break
        if codeowners_file is not None or (base / ".git").exists():
            break
    if codeowners_file is None:
        return []

    rel_prefix = (
        root_path.resolve().relative_to(owner_root).as_posix()
        if owner_root != root_path.resolve()
        else ""
    )
    rules: list[tuple[str, list[str]]] = []
    for raw_line in codeowners_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if line:
            parts = line.split()
            rules.append(
                (parts[0], [p.lstrip("@") for p in parts[1:] if p.lstrip("@")])
            )

    owners: list[str] = []
    for f in files:
        matched: list[str] = []
        for pat, pat_owners in rules:
            if _match_codeowner_pattern(pat, f) or (
                rel_prefix and _match_codeowner_pattern(pat, f"{rel_prefix}/{f}")
            ):
                matched = pat_owners
        for o in matched:
            if o not in owners:
                owners.append(o)
    return owners


def find_material_changes(
    obj_name: str,
    saved_data: Any,
    current_data: Any,
    files_out: list[str] | None = None,
) -> list[str]:
    """Return human-readable descriptions of material (non-additive) changes between saved and current snapshot data."""
    saved = strip_positions(saved_data)
    current = strip_positions(current_data)
    changes: list[str] = []

    def _record_file(f: str | None) -> None:
        if f and files_out is not None and f not in files_out:
            files_out.append(f)

    if (
        obj_name == "connections"
        and isinstance(saved, dict)
        and isinstance(current, dict)
    ):
        for k in sorted(set(saved) | set(current)):
            f_ref = (saved.get(k) or current.get(k) or {}).get("file")
            if k not in current:
                changes.append(
                    f"connections.{k}: removed (was {saved[k].get('connection')!r})"
                )
                _record_file(f_ref)
            elif k not in saved:
                changes.append(
                    f"connections.{k}: added ({current[k].get('connection')!r})"
                )
                _record_file(f_ref)
            elif strip_positions(saved[k], _META_KEYS) != strip_positions(
                current[k], _META_KEYS
            ):
                changes.append(
                    f"connections.{k}.connection: changed from {saved[k].get('connection')!r} to {current[k].get('connection')!r}"
                )
                _record_file(f_ref)
        return changes

    def _walk(
        s: Any, c: Any, path: str, cur_file: str | None = None
    ) -> None:
        if strip_positions(s, _META_KEYS) == strip_positions(c, _META_KEYS) or (
            s is None and isinstance(c, (dict, list))
        ):
            return
        f_here = (
            (s.get("file") if isinstance(s, dict) else None)
            or (c.get("file") if isinstance(c, dict) else None)
            or cur_file
        )
        if isinstance(s, dict):
            if not isinstance(c, dict):
                changes.append(
                    f"{path}: removed (was {strip_positions(s, _META_KEYS)!r})"
                )
                _record_file(f_here)
                return
            for k, sv in sorted(s.items()):
                if k == "file":
                    continue
                sub = f"{path}.{k}"
                if k not in c:
                    f_sub = (
                        sv.get("file") if isinstance(sv, dict) else None
                    ) or f_here
                    changes.append(
                        f"{sub}: removed (was {strip_positions(sv, _META_KEYS)!r})"
                    )
                    _record_file(f_sub)
                else:
                    _walk(sv, c[k], sub, f_here)
            return
        if isinstance(s, list) and isinstance(c, list) and path == "manifest.includes":
            for item in s:
                if item not in c:
                    changes.append(f"{path}: removed {item!r}")
                    _record_file(f_here)
            return
        changes.append(f"{path}: changed from {s!r} to {c!r}")
        _record_file(f_here)

    _walk(saved, current, obj_name)
    return changes


def run_lookml_snapshot(
    path: Path,
    update: bool = False,
    ci: bool = False,
    only: str | None = None,
    model: str | None = None,
    format_: Literal["console", "json"] = "console",
    allow_additions: bool = False,
    base_path: Path | None = None,
    *,
    manifest: Path | str | None = None,
    constants: dict[str, str] | None = None,
) -> tuple[LookmlSnapshotResult, str]:
    """Execute LookML snapshot comparison and return (result, console_output)."""
    resolved_path = path.resolve()

    def _fail(msg: str) -> tuple[LookmlSnapshotResult, str]:
        logger.error(msg)
        return (
            LookmlSnapshotResult(
                success=False, project=resolved_path.name, failed=1, message=msg
            ),
            msg,
        )

    if not resolved_path.exists() or not resolved_path.is_dir():
        return _fail(f"LookML directory not found: {resolved_path}")

    resolved_base_path: Path | None = None
    base_project: LookmlProject | None = None
    if base_path is not None:
        resolved_base_path = base_path.resolve()
        if not resolved_base_path.exists() or not resolved_base_path.is_dir():
            return _fail(f"Base LookML directory not found: {resolved_base_path}")
        if any(resolved_base_path.rglob("*.lkml")):
            base_project = parse_lookml(path=resolved_base_path, constants=constants)

    ci_mode = ci or os.getenv("CI", "").strip().lower() in ("true", "1")

    if only:
        target_objects = [x.strip() for x in only.split(",") if x.strip()]
        for req in target_objects:
            if req not in VALID_SNAPSHOT_OBJECTS:
                return _fail(
                    f"Invalid snapshot object '{req}'. Allowed objects: {', '.join(VALID_SNAPSHOT_OBJECTS)}"
                )
    else:
        target_objects = list(VALID_SNAPSHOT_OBJECTS)

    project = parse_lookml(path=resolved_path, manifest=manifest, constants=constants)
    proj_name = _resolve_project_name(project, resolved_path)
    snapshot_dir = resolved_path / "__snapshots__"

    def _write_snap(target: Path, data: Any) -> None:
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    written_count = 0
    updated_count = 0
    passed_count = 0
    failed_count = 0
    diff_reports: list[str] = []
    material_changes: list[str] = []
    material_change_files: list[str] = []
    snapshots_out: dict[str, Any] = {}

    for obj_name in target_objects:
        snap_file = snapshot_dir / f"{proj_name}.{obj_name}.snap.strings.json"
        legacy_snap_file = snapshot_dir / f"{proj_name}.{obj_name}.snap.json"
        read_snap_file = (
            snap_file
            if snap_file.exists() or not legacy_snap_file.exists()
            else legacy_snap_file
        )
        current_data = extract_snapshot_for_object(
            obj_name, project, model_filter=model
        )
        snapshots_out[obj_name] = current_data

        saved_data: dict[str, Any] | None = None
        if base_project is not None:
            saved_data = extract_snapshot_for_object(
                obj_name, base_project, model_filter=model
            )
        elif resolved_base_path is not None:
            candidate_snaps = [
                resolved_base_path
                / "__snapshots__"
                / f"{proj_name}.{obj_name}.snap.strings.json",
                resolved_base_path / f"{proj_name}.{obj_name}.snap.strings.json",
                resolved_base_path
                / "__snapshots__"
                / f"{proj_name}.{obj_name}.snap.json",
                resolved_base_path / f"{proj_name}.{obj_name}.snap.json",
            ]
            base_snap = next((p for p in candidate_snaps if p.exists()), None)
            if base_snap is not None:
                try:
                    saved_data = json.loads(base_snap.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError) as e:
                    failed_count += 1
                    diff_reports.append(
                        f"FAIL {obj_name} ({base_snap})\n  Could not read snapshot file: {e}"
                    )
                    continue
            else:
                saved_data = {}

        if model:
            existing = saved_data
            if existing is None and read_snap_file.exists():
                try:
                    existing = json.loads(read_snap_file.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError) as e:
                    logger.debug(f"Could not merge snapshot for model {model}: {e}")
            if isinstance(existing, dict):
                merged = {
                    k: v
                    for k, v in existing.items()
                    if k != model and not k.startswith(f"{model}.")
                }
                for k, v in current_data.items():
                    if isinstance(v, dict) and isinstance(existing.get(k), dict):
                        merged[k] = {
                            **{
                                sk: sv
                                for sk, sv in existing[k].items()
                                if not sk.startswith(f"{model}.")
                            },
                            **v,
                        }
                    else:
                        merged[k] = v
                current_data = merged

        if saved_data is None and not read_snap_file.exists():
            if ci_mode:
                failed_count += 1
                diff_reports.append(
                    f"FAIL {obj_name} ({snap_file})\n  Snapshot file missing in CI mode: {snap_file.name}"
                )
            else:
                _write_snap(snap_file, current_data)
                written_count += 1
        elif update and not allow_additions:
            _write_snap(snap_file, current_data)
            updated_count += 1
        else:
            if saved_data is None:
                try:
                    saved_data = json.loads(read_snap_file.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError) as e:
                    failed_count += 1
                    diff_reports.append(
                        f"FAIL {obj_name} ({read_snap_file})\n  Could not read snapshot file: {e}"
                    )
                    continue

            obj_material = find_material_changes(
                obj_name, saved_data, current_data, files_out=material_change_files
            )
            if obj_material:
                snap_rel = f"__snapshots__/{proj_name}.{obj_name}.snap.strings.json"
                if snap_rel not in material_change_files:
                    material_change_files.append(snap_rel)
            material_changes.extend(obj_material)

            if allow_additions:
                if not obj_material:
                    if update:
                        _write_snap(snap_file, current_data)
                        updated_count += 1
                    else:
                        passed_count += 1
                else:
                    failed_count += 1
                    diff_str = format_jest_diff(
                        obj_name, snap_file, saved_data, current_data
                    )
                    mat_str = "Material changes requiring review:\n" + "\n".join(
                        f"  - {c}" for c in obj_material
                    )
                    diff_reports.append(
                        f"FAIL {obj_name} ({snap_file})\n{mat_str}\n{diff_str}"
                    )
            elif strip_positions(saved_data) == strip_positions(current_data):
                passed_count += 1
            else:
                failed_count += 1
                diff_str = format_jest_diff(
                    obj_name, snap_file, saved_data, current_data
                )
                diff_reports.append(f"FAIL {obj_name} ({snap_file})\n{diff_str}")

    success = failed_count == 0
    requires_review = bool(material_changes)
    required_reviewers = (
        resolve_codeowners(resolved_path, material_change_files)
        if requires_review
        else []
    )
    total = len(target_objects)

    # Build console output message
    console_lines: list[str] = []
    if diff_reports:
        console_lines.extend(diff_reports)
        if required_reviewers:
            console_lines.append(
                f"Required CODEOWNERS: {', '.join(required_reviewers)}"
            )
        console_lines.append("")

    summary_parts: list[str] = []
    if written_count > 0:
        summary_parts.append(
            f"{written_count} snapshot{'s' if written_count != 1 else ''} written"
        )
    if updated_count > 0:
        summary_parts.append(
            f"{updated_count} snapshot{'s' if updated_count != 1 else ''} updated"
        )
    if passed_count > 0:
        summary_parts.append(
            f"{passed_count} snapshot{'s' if passed_count != 1 else ''} passed"
        )
    if failed_count > 0:
        summary_parts.append(
            f"{failed_count} snapshot{'s' if failed_count != 1 else ''} failed"
        )

    summary_msg = (
        f"Snapshots: {', '.join(summary_parts)} ({total} total)"
        if summary_parts
        else "No snapshots evaluated"
    )
    console_lines.append(summary_msg)
    console_output = "\n".join(console_lines)

    result = LookmlSnapshotResult(
        success=success,
        project=proj_name,
        written=written_count,
        updated=updated_count,
        passed=passed_count,
        failed=failed_count,
        total=total,
        requires_review=requires_review,
        material_changes=material_changes,
        material_change_files=material_change_files,
        required_reviewers=required_reviewers,
        diffs=diff_reports,
        snapshots=snapshots_out,
        message=summary_msg,
    )

    return result, console_output
