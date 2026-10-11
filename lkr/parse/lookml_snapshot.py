"""Jest-style LookML snapshot testing to guard tests, access controls, connections, and manifest."""

import difflib
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
    diffs: list[str] = Field(default_factory=list)
    snapshots: dict[str, Any] = Field(default_factory=dict)
    message: str | None = None


def normalize_sql(sql: str | None) -> str | None:
    """Normalize multi-line and irregular whitespace in SQL expressions."""
    if sql is None:
        return None
    return re.sub(r"\s+", " ", sql).strip()


def strip_positions(val: Any) -> Any:
    """Recursively strip line and position fields for semantic equality comparisons."""
    if isinstance(val, dict):
        return {
            k: strip_positions(v)
            for k, v in val.items()
            if k not in ("line", "position", "$p")
        }
    if isinstance(val, list):
        return [strip_positions(x) for x in val]
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


def extract_tests_snapshot(
    project: LookmlProject,
    model_filter: str | None = None,
) -> dict[str, Any]:
    """Extract and normalize all LookML data tests."""
    tests_out: dict[str, Any] = {}
    if not project.model:
        return tests_out

    positions = project.positions

    for model_name, model_obj in sorted(project.model.items()):
        if model_filter and model_name != model_filter:
            continue
        if not model_obj.test:
            continue

        for test_name, test_val in sorted(model_obj.test.items()):
            tests_list = test_val if isinstance(test_val, list) else [test_val]
            for idx, t in enumerate(tests_list):
                if not isinstance(t, LookmlTest):
                    continue

                snap_key = f"{model_name}.{test_name}" if len(tests_list) == 1 else f"{model_name}.{test_name}_{idx}"

                # Extract explore_source
                exp_sources: dict[str, Any] = {}
                explore_source_val = t.explore_source
                if isinstance(explore_source_val, dict):
                    explore_source_dict = explore_source_val
                elif explore_source_val is not None:
                    name = (
                        getattr(explore_source_val, "name_", None) or "explore_source"
                    )
                    explore_source_dict = {name: explore_source_val}
                else:
                    explore_source_dict = {}

                for exp_name, exp_src in sorted(explore_source_dict.items()):
                    col_dict: dict[str, Any] = {}
                    if getattr(exp_src, "column", None) and exp_src.column:
                        for c_name, c_obj in sorted(exp_src.column.items()):
                            col_dict[c_name] = {"field": getattr(c_obj, "field", None)}

                    derived_col_dict: dict[str, Any] = {}
                    if (
                        getattr(exp_src, "derived_column", None)
                        and exp_src.derived_column
                    ):
                        for dc_name, dc_obj in sorted(
                            exp_src.derived_column.items()
                        ):
                            derived_col_dict[dc_name] = {
                                "sql": normalize_sql(getattr(dc_obj, "sql", None))
                            }

                    exp_sources[exp_name] = {
                        "explore": exp_name,
                        "column": col_dict,
                        "derived_column": derived_col_dict
                        if derived_col_dict
                        else None,
                        "expression_custom_filter": normalize_sql(
                            getattr(exp_src, "expression_custom_filter", None)
                        ),
                        "limit": getattr(exp_src, "limit", None),
                        "timezone": getattr(exp_src, "timezone", None),
                    }

                # Extract assertions
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

                # Position lookup
                file_hint = f"{model_name}.model"
                f_path, line_no = _find_position(positions, file_hint, ["test", test_name])

                tests_out[snap_key] = {
                    "name": test_name,
                    "model": model_name,
                    "file": f_path,
                    "line": line_no,
                    "explore_source": exp_sources,
                    "assert": assert_dict,
                }

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

                            if fld_req_grants or fld_allowed_vals:
                                f_path, line_no = _find_position(
                                    positions, view_file_hint, ["view", v_name, field_type, fld_name]
                                )
                                fields_out[f"{model_name}.{v_name}.{fld_name}"] = {
                                    "model": model_name,
                                    "view": v_name,
                                    "field": fld_name,
                                    "field_type": field_type,
                                    "required_access_grants": fld_req_grants,
                                    "allowed_values": fld_allowed_vals if fld_allowed_vals else None,
                                    "file": f_path,
                                    "line": line_no,
                                }

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
            constants_out[c_name] = {
                "name": c_name,
                "value": getattr(c_obj, "value", None),
                "file": cf_path,
                "line": c_line,
            }

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


def run_lookml_snapshot(
    path: Path,
    update: bool = False,
    ci: bool = False,
    only: str | None = None,
    model: str | None = None,
    format_: Literal["console", "json"] = "console",
) -> tuple[LookmlSnapshotResult, str]:
    """Execute LookML snapshot comparison and return (result, console_output)."""
    resolved_path = path.resolve()
    if not resolved_path.exists() or not resolved_path.is_dir():
        msg = f"LookML directory not found: {resolved_path}"
        logger.error(msg)
        return (
            LookmlSnapshotResult(
                success=False,
                project=resolved_path.name,
                failed=1,
                message=msg,
            ),
            msg,
        )

    # Determine CI mode from argument or environment variable
    ci_mode = ci or os.getenv("CI", "").strip().lower() in ("true", "1")

    # Determine objects to process
    if only:
        requested = [x.strip() for x in only.split(",") if x.strip()]
        for req in requested:
            if req not in VALID_SNAPSHOT_OBJECTS:
                msg = f"Invalid snapshot object '{req}'. Allowed objects: {', '.join(VALID_SNAPSHOT_OBJECTS)}"
                logger.error(msg)
                return (
                    LookmlSnapshotResult(
                        success=False,
                        project=resolved_path.name,
                        failed=1,
                        message=msg,
                    ),
                    msg,
                )
        target_objects = requested
    else:
        target_objects = list(VALID_SNAPSHOT_OBJECTS)

    # Parse LookML project
    project = parse_lookml(path=resolved_path)
    proj_name = _resolve_project_name(project, resolved_path)

    snapshot_dir = resolved_path / "__snapshots__"

    written_count = 0
    updated_count = 0
    passed_count = 0
    failed_count = 0
    diff_reports: list[str] = []
    snapshots_out: dict[str, Any] = {}

    for obj_name in target_objects:
        snap_file = snapshot_dir / f"{proj_name}.{obj_name}.snap"
        current_data = extract_snapshot_for_object(obj_name, project, model_filter=model)
        snapshots_out[obj_name] = current_data

        if not snap_file.exists():
            if ci_mode:
                failed_count += 1
                diff_reports.append(
                    f"FAIL {obj_name} ({snap_file})\n  Snapshot file missing in CI mode: {snap_file.name}"
                )
            else:
                # First run locally: write snapshot
                snapshot_dir.mkdir(parents=True, exist_ok=True)
                snap_file.write_text(
                    json.dumps(current_data, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                written_count += 1
        elif update:
            # Update existing snapshot in place
            if model and snap_file.exists():
                try:
                    existing_data = json.loads(snap_file.read_text(encoding="utf-8"))
                    if isinstance(existing_data, dict):
                        # Merge model-scoped entries (supporting nested structures like access snapshots)
                        merged = dict(existing_data)
                        for k, v in current_data.items():
                            if isinstance(v, dict) and isinstance(merged.get(k), dict):
                                merged_sub = dict(merged[k])
                                for sub_k, sub_v in v.items():
                                    merged_sub[sub_k] = sub_v
                                merged[k] = merged_sub
                            else:
                                merged[k] = v
                        current_data = merged
                except (json.JSONDecodeError, OSError) as e:
                    logger.debug(f"Could not merge snapshot for model {model}: {e}")

            snapshot_dir.mkdir(parents=True, exist_ok=True)
            snap_file.write_text(
                json.dumps(current_data, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            updated_count += 1
        else:
            # Verify against existing snapshot
            try:
                saved_data = json.loads(snap_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                failed_count += 1
                diff_reports.append(
                    f"FAIL {obj_name} ({snap_file})\n  Could not read snapshot file: {e}"
                )
                continue

            # Semantic equality check (excluding line numbers)
            if strip_positions(saved_data) == strip_positions(current_data):
                passed_count += 1
            else:
                failed_count += 1
                diff_str = format_jest_diff(obj_name, snap_file, saved_data, current_data)
                diff_reports.append(f"FAIL {obj_name} ({snap_file})\n{diff_str}")

    success = failed_count == 0
    total = len(target_objects)

    # Build console output message
    console_lines: list[str] = []
    if diff_reports:
        console_lines.extend(diff_reports)
        console_lines.append("")

    summary_parts: list[str] = []
    if written_count > 0:
        summary_parts.append(f"{written_count} snapshot{'s' if written_count != 1 else ''} written")
    if updated_count > 0:
        summary_parts.append(f"{updated_count} snapshot{'s' if updated_count != 1 else ''} updated")
    if passed_count > 0:
        summary_parts.append(f"{passed_count} snapshot{'s' if passed_count != 1 else ''} passed")
    if failed_count > 0:
        summary_parts.append(f"{failed_count} snapshot{'s' if failed_count != 1 else ''} failed")

    summary_msg = f"Snapshots: {', '.join(summary_parts)} ({total} total)" if summary_parts else "No snapshots evaluated"
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
        diffs=diff_reports,
        snapshots=snapshots_out,
        message=summary_msg,
    )

    return result, console_output
