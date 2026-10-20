import json
import re
from io import StringIO
from pathlib import Path
from typing import Any

import typer
from pydantic import BaseModel, Field
from rich.console import Console
from rich.table import Table

from lkr.classes import LkrCtxObj
from lkr.logger import logger
from lkr.parse.lookml import LookmlProject, parse_lookml

__all__ = [
    "LookmlUserAttributesResult",
    "UserAttributeRef",
    "format_user_attributes",
    "parse_user_attributes",
]

LIQUID_USER_ATTR_RE = re.compile(
    r"_?user_attributes(?:\[\s*['\"]([^'\"\}]+)['\"]\s*\]|\.([a-zA-Z0-9_]+))"
)


class UserAttributeRef(BaseModel):
    attribute_name: str
    source_type: str  # "access_grant" | "access_filter" | "liquid" | "dashboard_filter"
    dashboard: str | None = None
    model: str | None = None
    explore: str | None = None
    view: str | None = None
    field: str | None = None
    property: str | None = None
    file: str | None = None
    line: int | None = None
    allowed_values: list[str] | None = None
    valid: bool | None = None


class LookmlUserAttributesResult(BaseModel):
    attributes: list[UserAttributeRef] = Field(default_factory=list)
    missing_attributes: list[str] | None = None


def _first_str(val: Any) -> str | None:
    if isinstance(val, list):
        return str(val[0]) if val else None
    return str(val) if val is not None else None


def _line_from_pos(pos: Any) -> int | None:
    p = pos.get("$p") if isinstance(pos, dict) else None
    return int(p[0]) + 1 if p and len(p) >= 1 else None


def _resolve_file_pos(
    entry: dict[str, Any], positions_dict: dict[str, Any]
) -> dict[str, Any]:
    rel, ftype = _first_str(entry.get("file_rel")), _first_str(entry.get("file_type"))
    cand = f"{rel}.{ftype}" if rel and ftype else None
    for key in (
        cand,
        _first_str(entry.get("file_name")),
        _first_str(entry.get("file_path")),
    ):
        if key and key in positions_dict:
            return positions_dict[key]
    return next(iter(positions_dict.values())) if len(positions_dict) == 1 else {}


def _scan_liquid(
    text: Any,
    prop_name: str,
    prop_pos: Any = None,
    file_path: str | None = None,
    source_type: str = "liquid",
    base_line: int | None = None,
    model: str | None = None,
    explore: str | None = None,
    view: str | None = None,
    field: str | None = None,
    dashboard: str | None = None,
) -> list[UserAttributeRef]:
    if not isinstance(text, str):
        return []
    bline = base_line if base_line is not None else _line_from_pos(prop_pos)
    refs: list[UserAttributeRef] = []
    for m in LIQUID_USER_ATTR_RE.finditer(text):
        attr = (m.group(1) or m.group(2) or "").strip()
        if attr:
            line = bline + text[: m.start()].count("\n") if bline is not None else None
            refs.append(
                UserAttributeRef(
                    attribute_name=attr,
                    source_type=source_type,
                    property=prop_name,
                    file=file_path,
                    line=line,
                    model=model,
                    explore=explore,
                    view=view,
                    field=field,
                    dashboard=dashboard,
                )
            )
    return refs


def _scan_props(
    data: dict[str, Any],
    pos: Any,
    props: tuple[str, ...],
    file_path: str | None,
    prefix: str = "",
    model: str | None = None,
    explore: str | None = None,
    view: str | None = None,
    field: str | None = None,
) -> list[UserAttributeRef]:
    refs: list[UserAttributeRef] = []
    pdict = pos if isinstance(pos, dict) else {}
    for prop in props:
        if prop in data:
            refs.extend(
                _scan_liquid(
                    data[prop],
                    f"{prefix}{prop}",
                    pdict.get(prop),
                    file_path,
                    model=model,
                    explore=explore,
                    view=view,
                    field=field,
                )
            )
    return refs


def _scan_filters_block(
    filters_val: Any,
    filters_pos: Any,
    prop_prefix: str,
    file_path: str | None,
    model: str | None = None,
    explore: str | None = None,
    view: str | None = None,
    field: str | None = None,
) -> list[UserAttributeRef]:
    refs: list[UserAttributeRef] = []
    fpos = filters_pos if isinstance(filters_pos, dict) else {}
    for item in filters_val if isinstance(filters_val, list) else [filters_val]:
        if not isinstance(item, dict):
            continue
        pairs = (
            [(_first_str(item.get("field")), item.get("value"), fpos.get("value", fpos))]
            if ("field" in item and "value" in item)
            else [
                (k, v, fpos.get(k, fpos))
                for k, v in item.items()
                if not k.startswith("$")
            ]
        )
        for k, v, p in pairs:
            eff_prop = f"{prop_prefix}[{k}]" if (field and k) else prop_prefix
            refs.extend(
                _scan_liquid(
                    v,
                    eff_prop,
                    p,
                    file_path,
                    model=model,
                    explore=explore,
                    view=view,
                    field=field or k,
                )
            )
    return refs


def _extract_access_filters(
    afs_raw: Any,
    af_pos: Any,
    fpath: str | None,
    model: str | None = None,
    explore: str | None = None,
    view: str | None = None,
) -> list[UserAttributeRef]:
    afs = (
        [afs_raw]
        if isinstance(afs_raw, dict)
        else (afs_raw if isinstance(afs_raw, list) else [])
    )
    refs: list[UserAttributeRef] = []
    for idx, af in enumerate(afs):
        if not (isinstance(af, dict) and "user_attribute" in af):
            continue
        sub_pos = (
            (af_pos[idx] if idx < len(af_pos) else {})
            if isinstance(af_pos, list)
            else (af_pos.get(str(idx), af_pos) if isinstance(af_pos, dict) else {})
        )
        line = _line_from_pos(
            sub_pos.get("user_attribute") if isinstance(sub_pos, dict) else None
        ) or _line_from_pos(sub_pos)
        refs.append(
            UserAttributeRef(
                attribute_name=str(af["user_attribute"]).strip(),
                source_type="access_filter",
                model=model,
                explore=explore,
                view=view,
                field=_first_str(af.get("field")),
                property="user_attribute",
                file=fpath,
                line=line,
            )
        )
    return refs


def _extract_from_file_entries(
    file_dict: dict[str, Any], positions_dict: dict[str, Any]
) -> list[UserAttributeRef]:
    refs: list[UserAttributeRef] = []
    for cat in ("model", "explore", "view"):
        entries = file_dict.get(cat, {})
        if not isinstance(entries, dict):
            continue
        for entry_key, entry in entries.items():
            if not isinstance(entry, dict):
                continue
            fpath = _first_str(entry.get("file_path")) or f"{entry_key}.lkml"
            fpos = _resolve_file_pos(entry, positions_dict)
            mname = _first_str(entry.get("file_name")) if cat == "model" else None

            # 1. access_grant
            grants = entry.get("access_grant", {})
            if isinstance(grants, dict):
                for gname, gdata in grants.items():
                    if not (isinstance(gdata, dict) and "user_attribute" in gdata):
                        continue
                    avals = gdata.get("allowed_values")
                    av_list = (
                        [avals]
                        if isinstance(avals, str)
                        else ([str(v) for v in avals] if isinstance(avals, list) else None)
                    )
                    gpos = fpos.get("access_grant", {}).get(gname, {})
                    line = _line_from_pos(
                        gpos.get("user_attribute") if isinstance(gpos, dict) else None
                    ) or _line_from_pos(gpos)
                    refs.append(
                        UserAttributeRef(
                            attribute_name=str(gdata["user_attribute"]).strip(),
                            source_type="access_grant",
                            model=mname,
                            property="user_attribute",
                            file=fpath,
                            line=line,
                            allowed_values=av_list,
                        )
                    )

            # 2. explore
            explores = entry.get("explore", {})
            if isinstance(explores, dict):
                for ename_raw, edata_or_list in explores.items():
                    elist = (
                        edata_or_list
                        if isinstance(edata_or_list, list)
                        else [edata_or_list]
                    )
                    epos_cand = (
                        fpos.get("explore", {}).get(ename_raw, {})
                        if isinstance(fpos, dict)
                        else {}
                    )
                    ename = ename_raw.lstrip("+")
                    for e_idx, edata in enumerate(elist):
                        if not isinstance(edata, dict):
                            continue
                        epos = (
                            (epos_cand[e_idx] if e_idx < len(epos_cand) else {})
                            if isinstance(epos_cand, list)
                            else epos_cand
                        )
                        epos_d = epos if isinstance(epos, dict) else {}

                        refs.extend(
                            _extract_access_filters(
                                edata.get("access_filter"),
                                epos_d.get("access_filter", {}),
                                fpath,
                                model=mname,
                                explore=ename,
                            )
                        )
                        for fb in ("always_filter", "conditionally_filter"):
                            fbd = edata.get(fb)
                            if isinstance(fbd, dict) and "filters" in fbd:
                                refs.extend(
                                    _scan_filters_block(
                                        fbd["filters"],
                                        epos_d.get(fb, {}).get("filters", {}),
                                        f"{fb}.filters",
                                        fpath,
                                        model=mname,
                                        explore=ename,
                                    )
                                )
                        queries = edata.get("query", {})
                        if isinstance(queries, dict):
                            for qn, qd in queries.items():
                                if isinstance(qd, dict) and "filters" in qd:
                                    refs.extend(
                                        _scan_filters_block(
                                            qd["filters"],
                                            epos_d.get("query", {})
                                            .get(qn, {})
                                            .get("filters", {}),
                                            f"query.{qn}.filters",
                                            fpath,
                                            model=mname,
                                            explore=ename,
                                        )
                                    )
                        refs.extend(
                            _scan_props(
                                edata,
                                epos_d,
                                (
                                    "sql_always_where",
                                    "sql_always_having",
                                    "description",
                                    "label",
                                ),
                                fpath,
                                model=mname,
                                explore=ename,
                            )
                        )
                        joins = edata.get("join", {})
                        if isinstance(joins, dict):
                            for jname, jdata in joins.items():
                                if isinstance(jdata, dict):
                                    refs.extend(
                                        _scan_props(
                                            jdata,
                                            epos_d.get("join", {}).get(jname, {}),
                                            ("sql_on", "sql_where", "sql", "sql_table_name"),
                                            fpath,
                                            model=mname,
                                            explore=ename,
                                            view=jname,
                                        )
                                    )

            # 3. view
            views = entry.get("view", {})
            if isinstance(views, dict):
                for vname_raw, vdata_or_list in views.items():
                    vlist = (
                        vdata_or_list
                        if isinstance(vdata_or_list, list)
                        else [vdata_or_list]
                    )
                    vname = vname_raw.lstrip("+")
                    vpos_cand = (
                        fpos.get("view", {}).get(vname_raw, {})
                        if isinstance(fpos, dict)
                        else {}
                    )
                    for v_idx, vdata in enumerate(vlist):
                        if not isinstance(vdata, dict):
                            continue
                        vpos = (
                            (vpos_cand[v_idx] if v_idx < len(vpos_cand) else {})
                            if isinstance(vpos_cand, list)
                            else vpos_cand
                        )
                        vpos_d = vpos if isinstance(vpos, dict) else {}

                        refs.extend(
                            _extract_access_filters(
                                vdata.get("access_filter"),
                                vpos_d.get("access_filter", {}),
                                fpath,
                                model=mname,
                                view=vname,
                            )
                        )
                        refs.extend(
                            _scan_props(
                                vdata,
                                vpos_d,
                                ("sql_table_name", "sql_always_where", "sql_always_having"),
                                fpath,
                                model=mname,
                                view=vname,
                            )
                        )
                        dt = vdata.get("derived_table", {})
                        if isinstance(dt, dict):
                            dt_pos = vpos_d.get("derived_table", {})
                            refs.extend(
                                _scan_props(
                                    dt,
                                    dt_pos,
                                    ("sql", "sql_trigger_value"),
                                    fpath,
                                    prefix="derived_table.",
                                    model=mname,
                                    view=vname,
                                )
                            )
                            es_map = dt.get("explore_source", {})
                            if isinstance(es_map, dict):
                                for es_name, es_data in es_map.items():
                                    if isinstance(es_data, dict) and "filters" in es_data:
                                        es_pos = (
                                            dt_pos.get("explore_source", {})
                                            .get(es_name, {})
                                            .get("filters", {})
                                            if isinstance(dt_pos, dict)
                                            else {}
                                        )
                                        refs.extend(
                                            _scan_filters_block(
                                                es_data["filters"],
                                                es_pos,
                                                "derived_table.explore_source.filters",
                                                fpath,
                                                model=mname,
                                                explore=es_name,
                                                view=vname,
                                            )
                                        )
                        for fcat in (
                            "dimension",
                            "dimension_group",
                            "measure",
                            "filter",
                            "parameter",
                        ):
                            fdict = vdata.get(fcat, {})
                            if not isinstance(fdict, dict):
                                continue
                            for fname, fdata in fdict.items():
                                if not isinstance(fdata, dict):
                                    continue
                                fpos_d = vpos_d.get(fcat, {}).get(fname, {})
                                refs.extend(
                                    _scan_props(
                                        fdata,
                                        fpos_d,
                                        (
                                            "sql",
                                            "html",
                                            "label",
                                            "description",
                                            "sql_start",
                                            "sql_end",
                                            "default_value",
                                        ),
                                        fpath,
                                        model=mname,
                                        view=vname,
                                        field=fname,
                                    )
                                )
                                if "filters" in fdata:
                                    refs.extend(
                                        _scan_filters_block(
                                            fdata["filters"],
                                            fpos_d.get("filters")
                                            if isinstance(fpos_d, dict)
                                            else {},
                                            "filters",
                                            fpath,
                                            model=mname,
                                            view=vname,
                                            field=fname,
                                        )
                                    )
    return refs


def _extract_from_lookml_dashboard(
    content: str, file_path: str | None = None
) -> list[UserAttributeRef]:
    refs: list[UserAttributeRef] = []
    dash_name: str | None = None
    dash_model: str | None = None
    dash_explore: str | None = None
    section: str | None = None
    section_indent = 0
    current_item: dict[str, Any] | None = None

    def _flush_item() -> None:
        nonlocal current_item
        if not current_item:
            return
        props = current_item["props"]
        item_model = props.get("model") or dash_model
        item_explore = props.get("explore") or dash_explore
        item_field = props.get("field") or props.get("dimension") or props.get("name")
        for attr_name, prop_name, override_field, line_no in current_item["matches"]:
            refs.append(
                UserAttributeRef(
                    attribute_name=attr_name,
                    source_type="dashboard_filter",
                    dashboard=dash_name,
                    model=item_model,
                    explore=item_explore,
                    field=override_field or item_field,
                    property=prop_name,
                    file=file_path,
                    line=line_no,
                )
            )
        current_item = None

    kv_re = re.compile(r"^(\s*)(-\s+)?([a-zA-Z0-9_.\-]+)\s*:\s*(.*)$")
    for line_no, raw_line in enumerate(content.splitlines(), 1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = kv_re.match(raw_line)
        if not m:
            for lmatch in LIQUID_USER_ATTR_RE.finditer(raw_line):
                attr = (lmatch.group(1) or lmatch.group(2) or "").strip()
                if attr and current_item is not None:
                    current_item["matches"].append((attr, "default_value", None, line_no))
            continue

        indent_str, is_list_item, key, val_raw = m.groups()
        indent = len(indent_str)
        effective_indent = indent + (len(is_list_item) if is_list_item else 0)
        val = val_raw.strip().strip("'\"")

        if key == "dashboard" and indent <= 2:
            _flush_item()
            dash_name, dash_model, dash_explore, section = val or None, None, None, None
            continue

        if (
            key in ("filters", "elements")
            and not is_list_item
            and (section is None or indent <= section_indent)
            and indent <= 2
        ):
            _flush_item()
            section, section_indent = key, indent
            continue

        if section is None:
            if key == "model" and val:
                dash_model = val
            elif key == "explore" and val:
                dash_explore = val
            continue

        if is_list_item and indent <= section_indent + 2:
            _flush_item()
            current_item = {
                "props": {},
                "matches": [],
                "in_subfilters": False,
                "subfilters_indent": 0,
            }

        if current_item is None:
            continue

        if current_item["in_subfilters"] and effective_indent <= current_item["subfilters_indent"]:
            current_item["in_subfilters"] = False

        if section == "elements" and key == "filters" and not val:
            current_item["in_subfilters"] = True
            current_item["subfilters_indent"] = effective_indent
            continue

        if current_item["in_subfilters"]:
            for lmatch in LIQUID_USER_ATTR_RE.finditer(val_raw):
                attr = (lmatch.group(1) or lmatch.group(2) or "").strip()
                if attr:
                    current_item["matches"].append((attr, "filters", key, line_no))
            continue

        if (
            key in ("name", "title", "model", "explore", "field", "dimension")
            and val
            and (key not in current_item["props"] or key != "title")
        ):
            current_item["props"][key] = val

        if key == "user_attribute" and val:
            current_item["matches"].append((val, "user_attribute", None, line_no))
        else:
            for lmatch in LIQUID_USER_ATTR_RE.finditer(val_raw):
                attr = (lmatch.group(1) or lmatch.group(2) or "").strip()
                if attr:
                    current_item["matches"].append((attr, key, None, line_no))

    _flush_item()
    return refs


def _extract_from_dashboard_filter_dict(
    fdict: dict[str, Any],
    file_path: str | None = None,
    dash_name: str | None = None,
    default_model: str | None = None,
    default_explore: str | None = None,
) -> list[UserAttributeRef]:
    f_model = _first_str(fdict.get("model")) or default_model
    f_explore = _first_str(fdict.get("explore")) or default_explore
    raw_field = fdict.get("dimension") or fdict.get("field")
    f_field = (
        _first_str(raw_field.get("name") or raw_field.get("dimension"))
        if isinstance(raw_field, dict)
        else _first_str(raw_field)
    ) or _first_str(fdict.get("name") or fdict.get("title"))
    f_dash = dash_name or _first_str(fdict.get("dashboard_id"))

    refs = _scan_liquid(
        fdict.get("default_value"),
        "default_value",
        file_path=file_path,
        source_type="dashboard_filter",
        dashboard=f_dash,
        model=f_model,
        explore=f_explore,
        field=f_field,
    )
    for container, prop_label in (
        (fdict, "user_attribute"),
        (fdict.get("ui_config"), "ui_config.user_attribute"),
    ):
        if isinstance(container, dict):
            ua = _first_str(
                container.get("user_attribute") or container.get("user_attribute_name")
            )
            if ua:
                refs.append(
                    UserAttributeRef(
                        attribute_name=ua.strip(),
                        source_type="dashboard_filter",
                        property=prop_label,
                        file=file_path,
                        dashboard=f_dash,
                        model=f_model,
                        explore=f_explore,
                        field=f_field,
                    )
                )
    return refs


def _extract_from_dashboard_data(
    data: Any,
    file_path: str | None = None,
    dash_name: str | None = None,
    default_model: str | None = None,
    default_explore: str | None = None,
) -> list[UserAttributeRef]:
    refs: list[UserAttributeRef] = []
    if isinstance(data, list):
        for item in data:
            refs.extend(
                _extract_from_dashboard_data(
                    item, file_path, dash_name, default_model, default_explore
                )
            )
        return refs
    if not isinstance(data, dict):
        return refs

    def _scan_fmap(
        fmap: dict[str, Any], m: str | None, e: str | None, d: str | None
    ) -> None:
        for fk, fv in fmap.items():
            refs.extend(
                _scan_liquid(
                    fv,
                    "filters",
                    file_path=file_path,
                    source_type="dashboard_filter",
                    model=m,
                    explore=e,
                    field=str(fk),
                    dashboard=d,
                )
            )

    is_dashboard_obj = any(
        k in data
        for k in ("dashboard_filters", "dashboard_elements", "elements", "dashboard")
    ) or (
        "filters" in data
        and any(k in data for k in ("id", "title", "slug", "layout", "preferred_viewer"))
    )

    if is_dashboard_obj:
        d_name = (
            _first_str(
                data.get("dashboard")
                or data.get("slug")
                or data.get("title")
                or data.get("id")
            )
            or dash_name
        )
        m_raw = data.get("model")
        d_model = (
            (
                _first_str(m_raw.get("name"))
                if isinstance(m_raw, dict)
                else _first_str(m_raw)
            )
            if m_raw is not None
            else default_model
        )
        d_explore = _first_str(data.get("explore")) or default_explore

        for fkey in ("dashboard_filters", "filters"):
            fval = data.get(fkey)
            if isinstance(fval, list):
                for fitem in fval:
                    if isinstance(fitem, dict):
                        refs.extend(
                            _extract_from_dashboard_filter_dict(
                                fitem, file_path, d_name, d_model, d_explore
                            )
                        )
            elif isinstance(fval, dict):
                _scan_fmap(fval, d_model, d_explore, d_name)

        for ekey in ("dashboard_elements", "elements"):
            eval_list = data.get(ekey)
            if not isinstance(eval_list, list):
                continue
            for el in eval_list:
                if not isinstance(el, dict):
                    continue
                q_raw = el.get("query")
                q_obj: dict[str, Any] = q_raw if isinstance(q_raw, dict) else {}
                rm_raw = el.get("result_maker")
                rm_obj: dict[str, Any] = rm_raw if isinstance(rm_raw, dict) else {}
                rm_q_raw = rm_obj.get("query")
                rm_q: dict[str, Any] = rm_q_raw if isinstance(rm_q_raw, dict) else {}

                el_model = (
                    _first_str(
                        el.get("model") or q_obj.get("model") or rm_q.get("model")
                    )
                    or d_model
                )
                el_explore = (
                    _first_str(
                        el.get("explore") or q_obj.get("view") or rm_q.get("view")
                    )
                    or d_explore
                )
                el_name = _first_str(el.get("name") or el.get("title") or el.get("id"))

                refs.extend(
                    _scan_liquid(
                        el.get("default_value"),
                        "default_value",
                        file_path=file_path,
                        source_type="dashboard_filter",
                        model=el_model,
                        explore=el_explore,
                        field=el_name,
                        dashboard=d_name,
                    )
                )
                for fmap in (
                    el.get("filters"),
                    q_obj.get("filters"),
                    rm_q.get("filters"),
                ):
                    if isinstance(fmap, dict):
                        _scan_fmap(fmap, el_model, el_explore, d_name)
        return refs

    if "filters" in data and len(data) == 1:
        f_inner = data["filters"]
        if isinstance(f_inner, list):
            return _extract_from_dashboard_data(
                f_inner, file_path, dash_name, default_model, default_explore
            )
        if isinstance(f_inner, dict):
            _scan_fmap(f_inner, default_model, default_explore, dash_name)
            return refs

    if any(
        k in data
        for k in (
            "default_value",
            "user_attribute",
            "user_attribute_name",
            "dimension",
            "ui_config",
            "allow_multiple_values",
        )
    ) or ("name" in data and "type" in data):
        return _extract_from_dashboard_filter_dict(
            data, file_path, dash_name, default_model, default_explore
        )

    _scan_fmap(data, default_model, default_explore, dash_name)
    return refs


def _extract_from_dashboard_json(
    payload: str | dict[str, Any] | list[Any], file_path: str | None = None
) -> list[UserAttributeRef]:
    if isinstance(payload, str):
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid dashboard filters JSON: {e}") from e
    else:
        data = payload
    return _extract_from_dashboard_data(data, file_path=file_path)


def _extract_from_project(project: LookmlProject) -> list[UserAttributeRef]:
    raw = project.model_dump(by_alias=False, exclude_none=True)
    file_dict = raw.get("file", {})
    positions_dict = project.positions.file if project.positions else {}
    refs = _extract_from_file_entries(file_dict, positions_dict)
    if not refs and raw.get("model"):
        refs = _extract_from_file_entries({"model": raw["model"]}, positions_dict)
    return refs


def parse_user_attributes(
    path: Path | str | None = None,
    file: Path | str | None = None,
    lookml: str | None = None,
    dashboard_file: Path | str | None = None,
    dashboard_json: str | dict[str, Any] | list[Any] | None = None,
    validate: bool = False,
    sdk: Any | None = None,
    ctx: typer.Context | LkrCtxObj | None = None,
    *,
    manifest: Path | str | None = None,
    constants: dict[str, str] | None = None,
) -> LookmlUserAttributesResult:
    """Parse LookML project and/or dashboard filter JSON to extract referenced user attributes.

    Supported dashboard JSON formats (`dashboard_file` or `dashboard_json`):
    1. A filters object: either a single Looker `DashboardFilter` dict
       (`{"name": "Region", "default_value": "{{ _user_attributes['region'] }}", "dimension": "users.region"}`)
       or a `{field: filter_expression}` mapping dict (`{"users.region": "{{ _user_attributes['region'] }}"}`).
    2. A dashboard object containing `dashboard_filters` / `filters` (and optional
       `dashboard_elements` / `elements`), matching `looker-cli` (`dashboard cat` / `space export`)
       and Looker SDK `sdk.dashboard()` exports.
    3. A JSON array of `DashboardFilter` objects (`sdk.dashboard_dashboard_filters()`)
       or an array of exported `Dashboard` objects.

    Instance validation (`--validate`):
    Calls `sdk.all_user_attributes()` (`GET /api/4.0/user_attributes`). Any authenticated Looker
    user can invoke this endpoint, but only users with the `Admin` role or `manage_user_attributes`
    permission receive all user attributes on the instance. Non-admin users without
    `manage_user_attributes` only receive attributes where `user_can_view=True` (User Access set to
    View or Edit); private attributes (`user_can_view=False`) are omitted by Looker and may be
    reported as missing when validated by a non-admin.
    """
    if not any(
        x is not None for x in (path, file, lookml, dashboard_file, dashboard_json)
    ):
        raise ValueError(
            "Specify at least one of 'path', 'file', 'lookml', 'dashboard_file', or 'dashboard_json'"
        )

    refs: list[UserAttributeRef] = []

    if file is not None:
        fpath = Path(file)
        if fpath.name.endswith(".json"):
            refs.extend(
                _extract_from_dashboard_json(
                    fpath.read_text(encoding="utf-8"), file_path=str(file)
                )
            )
            file = None
        elif fpath.name.endswith((".dashboard.lookml", ".dashboard.lkml")):
            refs.extend(
                _extract_from_lookml_dashboard(
                    fpath.read_text(encoding="utf-8"), file_path=str(file)
                )
            )
            file = None

    if lookml is not None and re.match(r"^\s*-?\s*dashboard\s*:", lookml):
        refs.extend(
            _extract_from_lookml_dashboard(lookml, file_path="inline.dashboard.lookml")
        )
        lookml = None

    if path is not None:
        root = Path(path)
        if root.is_file():
            return parse_user_attributes(
                file=root,
                dashboard_file=dashboard_file,
                dashboard_json=dashboard_json,
                validate=validate,
                sdk=sdk,
                ctx=ctx,
                manifest=manifest,
                constants=constants,
            )
        if any(not f.name.endswith(".dashboard.lkml") for f in root.rglob("*.lkml")):
            refs.extend(
                _extract_from_project(
                    parse_lookml(path=root, manifest=manifest, constants=constants)
                )
            )
        for df in sorted(
            {*root.rglob("*.dashboard.lookml"), *root.rglob("*.dashboard.lkml")}
        ):
            if df.is_file():
                refs.extend(
                    _extract_from_lookml_dashboard(
                        df.read_text(encoding="utf-8"),
                        file_path=df.relative_to(root).as_posix(),
                    )
                )
    elif file is not None or lookml is not None:
        refs.extend(
            _extract_from_project(
                parse_lookml(
                    file=file, lookml=lookml, manifest=manifest, constants=constants
                )
            )
        )

    if dashboard_file is not None:
        refs.extend(
            _extract_from_dashboard_json(
                Path(dashboard_file).read_text(encoding="utf-8"),
                file_path=str(dashboard_file),
            )
        )
    if dashboard_json is not None:
        refs.extend(_extract_from_dashboard_json(dashboard_json, file_path=None))

    missing: list[str] | None = None
    if validate:
        if sdk is None:
            if ctx is None:
                raise ValueError("No Looker context provided for --validate")
            from lkr.auth_service import get_auth

            sdk = get_auth(ctx).get_current_sdk(prompt_refresh_invalid_token=True)

        try:
            user_attrs = sdk.all_user_attributes()
        except Exception as e:
            logger.error(
                f"Failed to fetch user attributes from Looker instance: {e}. "
                "Common causes: expired/invalid auth session (401), unreachable instance URL, "
                "or insufficient API permissions (403). Note: non-admin users without the "
                "'manage_user_attributes' permission only receive attributes with 'user_can_view=True'."
            )
            raise

        instance_attrs = {
            str(
                ua.get("name") if isinstance(ua, dict) else getattr(ua, "name", "")
            ).strip()
            for ua in user_attrs
            if (ua.get("name") if isinstance(ua, dict) else getattr(ua, "name", None))
        }
        for ref in refs:
            ref.valid = ref.attribute_name in instance_attrs
        missing = sorted({ref.attribute_name for ref in refs if not ref.valid})

    return LookmlUserAttributesResult(attributes=refs, missing_attributes=missing)


def format_user_attributes(
    result: LookmlUserAttributesResult, format: str = "text"
) -> str:
    """Format user attribute extraction result into Rich text table or JSON."""
    if format.lower() == "json":
        return result.model_dump_json(indent=2)
    if not result.attributes:
        return "No user attributes found in LookML project."

    has_status = any(r.valid is not None for r in result.attributes)
    headers = ["ATTRIBUTE", "SOURCE", "LOCATION", "FILE:LINE"] + (
        ["STATUS"] if has_status else []
    )
    table = Table()
    for h in headers:
        table.add_column(h, no_wrap=True)

    for r in result.attributes:
        loc_parts = [
            f"{k}:{v}"
            for k, v in (
                ("dashboard", r.dashboard),
                ("explore", r.explore),
                ("view", r.view),
                ("field", r.field),
            )
            if v
        ]
        if r.property:
            loc_parts.append(f"({r.property})")
        elif r.model:
            loc_parts.append(f"model:{r.model}")

        location = " ".join(loc_parts) if loc_parts else (r.property or "-")
        file_line = f"{r.file}:{r.line}" if (r.file and r.line) else (r.file or "-")
        row = [r.attribute_name, r.source_type, location, file_line]
        if has_status:
            row.append("VALID" if r.valid else "INVALID")
        table.add_row(*row)

    buf = StringIO()
    Console(file=buf, force_terminal=False, no_color=True, width=200).print(table)
    lines = [buf.getvalue().rstrip("\n")]

    if result.missing_attributes is not None:
        valid_count = sum(1 for r in result.attributes if r.valid)
        invalid_count = len(result.attributes) - valid_count
        lines.extend(
            [
                "",
                "Validation Summary:",
                f"  Total references: {len(result.attributes)}",
                f"  Valid references: {valid_count}",
                f"  Invalid references: {invalid_count}",
                f"  Missing attributes on instance: {', '.join(result.missing_attributes)}"
                if result.missing_attributes
                else "  All referenced attributes exist on instance.",
            ]
        )
    return "\n".join(lines)
