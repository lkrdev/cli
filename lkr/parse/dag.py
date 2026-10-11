import re
from collections.abc import Mapping, Sequence
from typing import Any

import sqlglot
from pydantic import BaseModel, Field
from sqlglot import exp
from sqlglot.errors import SqlglotError

from lkr.parse.lookml import LookmlExplore, LookmlJoin, LookmlProject, LookmlView

_LOOKML_REF_RE = re.compile(r"\$\{\s*([a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+)?)\s*\}")


def _extract_lookml_refs(sql: str | None) -> list[str]:
    if not sql:
        return []
    return [
        m.group(1)
        for m in _LOOKML_REF_RE.finditer(sql)
        if m.group(1).upper() not in ("TABLE", "EXTENDED")
    ]


def _as_list(val: Any) -> list[Any]:
    if val is None:
        return []
    if isinstance(val, list):
        return val
    if isinstance(val, dict):
        return list(val.values())
    return [val]


def _qualify_field_ref(ref: str, default_alias: str) -> str:
    clean = ref.strip()
    return clean if "." in clean else f"{default_alias}.{clean}"



def _collect_declarations(
    project: LookmlProject,
    obj_type: str,
    cls: type[Any],
) -> tuple[
    dict[str, list[tuple[str, Any, dict[str, Any]]]],
    dict[str, list[tuple[str, Any, dict[str, Any]]]],
]:
    base_decls: dict[str, list[tuple[str, Any, dict[str, Any]]]] = {}
    ref_decls: dict[str, list[tuple[str, Any, dict[str, Any]]]] = {}

    if not isinstance(project.file, BaseModel):
        return base_decls, ref_decls

    pos_files = project.positions.file if project.positions else {}

    for category in ("view", "model", "explore"):
        cat_dict = getattr(project.file, category, None)
        if not isinstance(cat_dict, dict):
            continue
        for rel_key, file_entry in cat_dict.items():
            fp = getattr(file_entry, "file_path", None)
            file_path = (
                fp[0] if isinstance(fp, list) and fp else fp
            ) or f"{rel_key}.{category}.lkml"

            pos_key = f"{rel_key}.{category}"
            file_pos = pos_files.get(pos_key, {})
            obj_pos_map = file_pos.get(obj_type, {}) if isinstance(file_pos, dict) else {}

            objs_dict = getattr(file_entry, obj_type, None)
            if not isinstance(objs_dict, dict):
                continue

            for o_key, o_val in objs_dict.items():
                if o_key.startswith("+"):
                    target_name = o_key[1:]
                    o_list = o_val if isinstance(o_val, list) else [o_val]
                    p_raw = obj_pos_map.get(o_key, [])
                    p_list = (
                        [p_raw[str(i)] for i in range(len(o_list)) if str(i) in p_raw]
                        if isinstance(p_raw, dict) and "$p" not in p_raw
                        else ([p_raw] if isinstance(p_raw, dict) else p_raw)
                    )
                    for idx, o_item in enumerate(o_list):
                        if isinstance(o_item, cls):
                            p_item = (
                                p_list[idx]
                                if isinstance(p_list, list) and idx < len(p_list)
                                else {}
                            )
                            ref_decls.setdefault(target_name, []).append(
                                (file_path, o_item, p_item if isinstance(p_item, dict) else {})
                            )
                elif isinstance(o_val, cls):
                    p_item = obj_pos_map.get(o_key, {})
                    base_decls.setdefault(o_key, []).append(
                        (file_path, o_val, p_item if isinstance(p_item, dict) else {})
                    )

    return base_decls, ref_decls


def _build_chain(
    name: str,
    base_decls: dict[str, list[tuple[str, Any, dict[str, Any]]]],
    ref_decls: dict[str, list[tuple[str, Any, dict[str, Any]]]],
    visited: set[str] | None = None,
) -> list[tuple[str, Any, dict[str, Any]]]:
    if visited is None:
        visited = set()
    if name in visited:
        return []
    visited.add(name)

    chain: list[tuple[str, Any, dict[str, Any]]] = []
    bases = base_decls.get(name, [])
    refs = ref_decls.get(name, [])

    ext_names = [
        e
        for _, obj, _ in [*bases, *refs]
        for e in _as_list(getattr(obj, "extends", None))
        if isinstance(e, str)
    ]

    for ext in ext_names:
        chain.extend(_build_chain(ext, base_decls, ref_decls, visited))

    chain.extend(bases)
    chain.extend(refs)
    return chain


def _chain_root_pos(
    chain: list[tuple[str, Any, dict[str, Any]]], target_name: str
) -> tuple[str, list[int]]:
    file, pos = "", [0, 0, 0, 0]
    for fpath, item, p_dict in chain:
        if (item.name_ == target_name or not file) and "$p" in p_dict:
            file, pos = fpath, [int(x) for x in p_dict["$p"][:4]]
            if item.name_ == target_name:
                break
    return file, pos


def _expand_field_tokens(
    tokens: Sequence[str | None],
    views_by_alias: dict[str, LookmlView],
    default_alias: str,
    visited_sets: set[tuple[str, str]] | None = None,
) -> list[tuple[str, str, str]]:
    if visited_sets is None:
        visited_sets = set()
    expanded: list[tuple[str, str, str]] = []
    for tok in (r.strip() for r in tokens if r and r.strip()):
        is_excl = tok.startswith("-")
        body = tok[1:].strip() if is_excl else tok
        op = "-" if is_excl else "+"

        if body.upper() == "ALL_FIELDS*":
            expanded.append((op, "*", "*"))
            continue

        if body.endswith("*"):
            set_ref = body[:-1]
            s_alias, s_name = (
                set_ref.split(".", 1) if "." in set_ref else (default_alias, set_ref)
            )
            s_key = (s_alias.lower(), s_name.lower())
            if s_key in visited_sets:
                continue
            visited_sets.add(s_key)
            target_view = views_by_alias.get(s_alias)
            if target_view and target_view.set and s_name in target_view.set:
                for sub_op, sub_alias, sub_field in _expand_field_tokens(
                    list(target_view.set[s_name].fields),
                    views_by_alias,
                    s_alias,
                    visited_sets,
                ):
                    expanded.append(("-" if is_excl else sub_op, sub_alias, sub_field))
            elif "." not in set_ref and any(
                k.lower() == set_ref.lower() for k in views_by_alias
            ):
                expanded.append((op, set_ref.lower(), "*"))
            continue

        field_alias, field_name = (
            body.split(".", 1) if "." in body else (default_alias, body)
        )
        expanded.append((op, field_alias.lower(), field_name.lower()))
    return expanded


def _is_field_allowed_by_spec(
    fields_spec: Sequence[str | None] | None,
    view_alias: str,
    candidate_names: set[str],
    views_by_alias: dict[str, LookmlView],
    default_alias: str,
) -> bool:
    if fields_spec is None:
        return True
    expanded = _expand_field_tokens(fields_spec, views_by_alias, default_alias)
    if not expanded:
        return False

    alias_lower = view_alias.lower()
    has_all = any(op == "+" and a == "*" for op, a, _ in expanded)
    only_exclusions = all(op == "-" for op, _, _ in expanded)
    included = (has_all or only_exclusions) or any(
        op == "+"
        and (
            (a == alias_lower and (fn == "*" or fn in candidate_names))
            or f"{a}.{fn}" in candidate_names
        )
        for op, a, fn in expanded
    )
    if included and any(
        op == "-"
        and (
            a == "*"
            or (a == alias_lower and (fn == "*" or fn in candidate_names))
            or f"{a}.{fn}" in candidate_names
        )
        for op, a, fn in expanded
    ):
        return False
    return included


def _resolve_explore_base(
    exp_name: str,
    exp_obj: LookmlExplore,
    exp_chain: list[tuple[str, Any, dict[str, Any]]],
    model_views: Mapping[str, LookmlView | list[LookmlView]],
) -> tuple[str, str, str, list[int]]:
    exp_file, exp_pos = _chain_root_pos(exp_chain, exp_name)
    own_from: str | None = None
    own_view_name: str | None = None
    for _, e_item, _ in exp_chain:
        if e_item.name_ in (exp_name, f"+{exp_name}"):
            own_from = e_item.from_ or own_from
            own_view_name = e_item.view_name or own_view_name

    ancestor_view = next(
        (
            e_item.name_
            for _, e_item, _ in reversed(exp_chain)
            if e_item.name_ and e_item.name_ in model_views
        ),
        exp_name,
    )
    base_view_name, base_alias = (
        (own_from, exp_name)
        if own_from
        else (own_view_name, own_view_name)
        if own_view_name
        else (exp_name, exp_name)
        if exp_name in model_views
        else (exp_obj.from_, exp_name)
        if exp_obj.from_
        else (exp_obj.view_name, exp_obj.view_name)
        if exp_obj.view_name
        else (ancestor_view, exp_name)
    )
    return base_view_name, base_alias, exp_file, exp_pos


class LookmlExploreJoinNode(BaseModel):
    name: str
    target_view: str
    view_alias: str
    type: str = "left_outer"
    relationship: str = "many_to_one"
    required_joins: list[str] = Field(default_factory=list)
    always_join: bool = False
    from_view: str | None = None
    equi_joins: list[tuple[tuple[str, str], tuple[str, str]]] = Field(
        default_factory=list
    )
    sql_on: str | None = None
    foreign_key: str | None = None
    sql_foreign_key: str | None = None
    file: str | None = None
    line: int | None = None


class LookmlExploreJoinGraph(BaseModel):
    explore_name: str
    model_name: str | None = None
    base_view: str
    base_alias: str
    always_join: list[str] = Field(default_factory=list)
    joins: dict[str, LookmlExploreJoinNode] = Field(default_factory=dict)


# ponytail: extract simple equi-join pairs from sql_on, foreign_key, sql_foreign_key without full relational algebra optimizer
def _extract_explore_equi_joins(
    sql_on: str | None,
    foreign_key: str | None,
    sql_foreign_key: str | None,
    base_alias: str,
    join_name: str,
    target_view: str,
    views_by_alias: Mapping[str, LookmlView] | None = None,
) -> list[tuple[tuple[str, str], tuple[str, str]]]:
    equi_joins: list[tuple[tuple[str, str], tuple[str, str]]] = []
    views_map = views_by_alias or {}

    def _find_pk(view_key: str) -> str:
        v = views_map.get(view_key)
        if v and isinstance(v, LookmlView) and v.dimension:
            for d_name, d_obj in v.dimension.items():
                if getattr(d_obj, "primary_key", False):
                    return d_name
        return "id"

    if foreign_key:
        fk_clean = foreign_key.strip()
        if "${" in fk_clean:
            refs = _extract_lookml_refs(fk_clean)
            if refs:
                f_view, f_col = refs[0].split(".", 1) if "." in refs[0] else (base_alias, refs[0])
            else:
                f_view, f_col = base_alias, re.sub(r"[\${}\s;]", "", fk_clean)
        elif "." in fk_clean:
            f_view, f_col = fk_clean.split(".", 1)
        else:
            f_view, f_col = base_alias, fk_clean
        pk = _find_pk(join_name) or _find_pk(target_view)
        equi_joins.append(((f_view, f_col), (join_name, pk)))

    if sql_foreign_key:
        refs = _extract_lookml_refs(sql_foreign_key)
        if refs:
            f_view, f_col = refs[0].split(".", 1) if "." in refs[0] else (base_alias, refs[0])
        else:
            cleaned = re.sub(r"[\${}\s;]", "", sql_foreign_key)
            if cleaned.upper().startswith("TABLE."):
                cleaned = cleaned[6:]
            f_view, f_col = base_alias, cleaned
        pk = _find_pk(join_name) or _find_pk(target_view)
        equi_joins.append(((f_view, f_col), (join_name, pk)))

    if sql_on:
        clean_on = re.sub(
            r"\$\{\s*([a-zA-Z0-9_]+)\.([a-zA-Z0-9_]+)\s*\}", r"\1.\2", sql_on
        )
        clean_on = re.sub(r"\$\{\s*([a-zA-Z0-9_]+)\s*\}", rf"{join_name}.\1", clean_on)
        j_low = join_name.lower()
        try:
            parsed = sqlglot.parse_one(clean_on)
            conjuncts: list[exp.Expr] = []

            def _walk_conj(node: exp.Expr | None) -> None:
                if node is None:
                    return
                if isinstance(node, exp.And):
                    _walk_conj(node.left)
                    _walk_conj(node.right)
                elif isinstance(node, exp.Paren):
                    _walk_conj(node.this)
                else:
                    conjuncts.append(node)

            _walk_conj(parsed)
            for conj in conjuncts:
                if (
                    isinstance(conj, exp.EQ)
                    and isinstance(conj.left, exp.Column)
                    and isinstance(conj.right, exp.Column)
                ):
                    cl, cr = conj.left, conj.right
                    tl = (cl.table or "").lower()
                    tr = (cr.table or "").lower()
                    if tr == j_low and tl != j_low:
                        equi_joins.append(
                            ((cl.table or base_alias, cl.name), (cr.table or join_name, cr.name))
                        )
                    elif tl == j_low and tr != j_low:
                        equi_joins.append(
                            ((cr.table or base_alias, cr.name), (cl.table or join_name, cl.name))
                        )
                    else:
                        equi_joins.append(
                            ((cl.table or base_alias, cl.name), (cr.table or join_name, cr.name))
                        )
        except (SqlglotError, ValueError, AttributeError, TypeError, KeyError):
            pattern = re.compile(
                r"\$\{\s*([a-zA-Z0-9_]+)\.([a-zA-Z0-9_]+)\s*\}\s*=\s*\$\{\s*([a-zA-Z0-9_]+)\.([a-zA-Z0-9_]+)\s*\}"
            )
            for m in pattern.finditer(sql_on):
                v1, c1, v2, c2 = m.groups()
                if v2.lower() == j_low:
                    equi_joins.append(((v1, c1), (v2, c2)))
                else:
                    equi_joins.append(((v2, c2), (v1, c1)))

    return equi_joins


def build_explore_join_graph(
    explore_name: str,
    explore_obj: LookmlExplore,
    explore_chain: list[tuple[str, Any, dict[str, Any]]],
    model_views: Mapping[str, LookmlView | list[LookmlView]],
    model_name: str | None = None,
) -> LookmlExploreJoinGraph:
    base_view_name, base_alias, exp_file, _ = _resolve_explore_base(
        explore_name, explore_obj, explore_chain, model_views
    )
    views_by_alias: dict[str, LookmlView] = {}
    bv = model_views.get(base_view_name)
    if isinstance(bv, LookmlView):
        views_by_alias[base_alias] = bv

    merged_joins: dict[str, tuple[str, LookmlJoin, dict[str, Any]]] = {}
    always_joins: list[str] = []

    items_to_process = list(explore_chain)
    if not any(e_item is explore_obj for _, e_item, _ in items_to_process):
        items_to_process.append((exp_file or "", explore_obj, {}))

    for fpath, e_item, p_dict in items_to_process:
        for aj in _as_list(e_item.always_join):
            if aj and aj not in always_joins:
                always_joins.append(aj)
        join_pos_map = p_dict.get("join", {}) if isinstance(p_dict, dict) else {}
        for j_name, j_obj in (e_item.join or {}).items():
            jp = join_pos_map.get(j_name, {}) if isinstance(join_pos_map, dict) else {}
            if j_name in merged_joins:
                prev_fpath, _, prev_jp = merged_joins[j_name]
                merged_joins[j_name] = (fpath or prev_fpath, j_obj, jp or prev_jp)
            else:
                merged_joins[j_name] = (fpath, j_obj, jp)

    for j_name, (_, j_obj, _) in merged_joins.items():
        jv_name = j_obj.from_ or j_obj.view_name or j_name
        jv = model_views.get(jv_name)
        if isinstance(jv, LookmlView):
            views_by_alias[j_name] = jv

    nodes: dict[str, LookmlExploreJoinNode] = {}
    for j_name, (fpath, j_obj, jp) in merged_joins.items():
        target_view = j_obj.from_ or j_obj.view_name or j_name
        j_type = j_obj.type or "left_outer"
        rel = j_obj.relationship or "many_to_one"
        req_joins = _as_list(j_obj.required_joins)
        is_always = j_name in always_joins
        line = int(jp["$p"][0]) if "$p" in jp and len(jp["$p"]) > 0 else None

        equi_joins = _extract_explore_equi_joins(
            j_obj.sql_on,
            j_obj.foreign_key,
            j_obj.sql_foreign_key,
            base_alias=base_alias,
            join_name=j_name,
            target_view=target_view,
            views_by_alias=views_by_alias,
        )
        from_v = equi_joins[0][0][0] if equi_joins else base_alias

        nodes[j_name] = LookmlExploreJoinNode(
            name=j_name,
            target_view=target_view,
            view_alias=j_name,
            type=j_type,
            relationship=rel,
            required_joins=req_joins,
            always_join=is_always,
            from_view=from_v,
            equi_joins=equi_joins,
            sql_on=j_obj.sql_on,
            foreign_key=j_obj.foreign_key,
            sql_foreign_key=j_obj.sql_foreign_key,
            file=fpath or exp_file,
            line=line,
        )

    return LookmlExploreJoinGraph(
        explore_name=explore_name,
        model_name=model_name,
        base_view=base_view_name,
        base_alias=base_alias,
        always_join=always_joins,
        joins=nodes,
    )


__all__ = [
    "LookmlExploreJoinGraph",
    "LookmlExploreJoinNode",
    "_as_list",
    "_build_chain",
    "_chain_root_pos",
    "_collect_declarations",
    "_expand_field_tokens",
    "_extract_lookml_refs",
    "_is_field_allowed_by_spec",
    "_qualify_field_ref",
    "_resolve_explore_base",
    "build_explore_join_graph",
]
