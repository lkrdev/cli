import re
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel

from lkr.parse.lookml import LookmlExplore, LookmlProject, LookmlView

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


__all__ = [
    "_as_list",
    "_build_chain",
    "_chain_root_pos",
    "_collect_declarations",
    "_expand_field_tokens",
    "_extract_lookml_refs",
    "_is_field_allowed_by_spec",
    "_qualify_field_ref",
    "_resolve_explore_base",
]
