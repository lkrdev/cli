import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from lkr.logger import logger
from lkr.parse.lookml import (
    LookmlAllowedValue,
    LookmlExplore,
    LookmlFile,
    LookmlJoin,
    LookmlLocalizationSettings,
    LookmlManifest,
    LookmlProject,
    LookmlView,
    parse_lookml,
)
from lkr.parse.lookml_to_api import _titleize

LIQUID_LOCALIZATION_REGEX = re.compile(
    r"\{\{\s*_localization\s*\[\s*['\"]([^'\"]+)['\"]\s*\]\s*\}\}"
)


class TranslationUsage(BaseModel):
    object_type: str
    object_name: str
    property: str
    missing_explicit_label: bool = False
    file: str | None = None
    line: int | None = None


class MissingTranslation(BaseModel):
    string: str
    missing_in_default_locale: bool = False
    missing_in_locales: list[str] = Field(default_factory=list)
    bypassed_in_locales: list[str] = Field(default_factory=list)
    usages: list[TranslationUsage] = Field(default_factory=list)


class LocaleSummary(BaseModel):
    locale: str
    file: str
    missing_count: int = 0
    bypassed_due_to_missing_default_locale_count: int = 0


class UnusedKey(BaseModel):
    locale: str
    key: str


class TranslationAnalysisResult(BaseModel):
    default_locale: str
    default_locale_file: str | None = None
    manifest_localization_level: str = "permissive"
    locales_checked: list[LocaleSummary] = Field(default_factory=list)
    missing_translations: list[MissingTranslation] = Field(default_factory=list)
    unused_keys: list[UnusedKey] = Field(default_factory=list)
    missing_explicit_labels_count: int = 0
    total_missing_strings_count: int = 0
    total_bypassed_strings_count: int = 0


def _extract_liquid_localization_keys(text: str | None) -> list[str]:
    if not text or "_localization" not in text:
        return []
    return LIQUID_LOCALIZATION_REGEX.findall(text)


def _is_field_hidden(field: Any, view_fields_hidden_by_default: bool | None) -> bool:
    if getattr(field, "hidden", None) is True:
        return True
    return bool(
        view_fields_hidden_by_default is True
        and getattr(field, "hidden", None) is not False
    )


def _find_position(
    positions: Any,
    obj_type: str,
    parent_name: str | None,
    item_name: str,
    prop_name: str | None = None,
) -> tuple[str | None, int | None]:
    if not positions:
        return None, 1
    pos_files = getattr(positions, "file", None) or {}
    pos_models = getattr(positions, "model", None) or {}

    if obj_type == "view":
        for f_key, f_val in pos_files.items():
            if (
                isinstance(f_val, dict)
                and "view" in f_val
                and item_name in f_val["view"]
            ):
                v_pos = f_val["view"][item_name]
                file_name = f_key if f_key.endswith(".lkml") else f"{f_key}.lkml"
                line = 1
                if (
                    prop_name
                    and isinstance(v_pos, dict)
                    and prop_name in v_pos
                    and "$p" in v_pos[prop_name]
                ):
                    line = int(v_pos[prop_name]["$p"][0]) + 1
                elif isinstance(v_pos, dict) and "$p" in v_pos:
                    line = int(v_pos["$p"][0]) + 1
                return file_name, line

    elif obj_type in ("dimension", "dimension_group", "measure", "filter", "parameter"):
        for f_key, f_val in pos_files.items():
            if (
                isinstance(f_val, dict)
                and "view" in f_val
                and parent_name
                and parent_name in f_val["view"]
            ):
                v_pos = f_val["view"][parent_name]
                if isinstance(v_pos, dict):
                    for cat in (
                        "dimension",
                        "dimension_group",
                        "measure",
                        "filter",
                        "parameter",
                    ):
                        if isinstance(v_pos.get(cat), dict) and item_name in v_pos[cat]:
                            f_pos = v_pos[cat][item_name]
                            file_name = (
                                f_key if f_key.endswith(".lkml") else f"{f_key}.lkml"
                            )
                            line = 1
                            if (
                                prop_name
                                and isinstance(f_pos, dict)
                                and prop_name in f_pos
                                and "$p" in f_pos[prop_name]
                            ):
                                line = int(f_pos[prop_name]["$p"][0]) + 1
                            elif isinstance(f_pos, dict) and "$p" in f_pos:
                                line = int(f_pos["$p"][0]) + 1
                            return file_name, line

    elif obj_type == "explore":
        for f_key, f_val in pos_files.items():
            if (
                isinstance(f_val, dict)
                and "explore" in f_val
                and item_name in f_val["explore"]
            ):
                e_pos = f_val["explore"][item_name]
                file_name = f_key if f_key.endswith(".lkml") else f"{f_key}.lkml"
                line = 1
                if (
                    prop_name
                    and isinstance(e_pos, dict)
                    and prop_name in e_pos
                    and "$p" in e_pos[prop_name]
                ):
                    line = int(e_pos[prop_name]["$p"][0]) + 1
                elif isinstance(e_pos, dict) and "$p" in e_pos:
                    line = int(e_pos["$p"][0]) + 1
                return file_name, line

        for m_name, m_val in pos_models.items():
            if (
                isinstance(m_val, dict)
                and "explore" in m_val
                and item_name in m_val["explore"]
            ):
                e_pos = m_val["explore"][item_name]
                line = 1
                if (
                    prop_name
                    and isinstance(e_pos, dict)
                    and prop_name in e_pos
                    and "$p" in e_pos[prop_name]
                ):
                    line = int(e_pos[prop_name]["$p"][0]) + 1
                elif isinstance(e_pos, dict) and "$p" in e_pos:
                    line = int(e_pos["$p"][0]) + 1
                return f"models/{m_name}.model.lkml", line

    elif obj_type == "join":
        for f_key, f_val in pos_files.items():
            if (
                isinstance(f_val, dict)
                and "explore" in f_val
                and parent_name
                and parent_name in f_val["explore"]
            ):
                e_pos = f_val["explore"][parent_name]
                if (
                    isinstance(e_pos, dict)
                    and isinstance(e_pos.get("join"), dict)
                    and item_name in e_pos["join"]
                ):
                    j_pos = e_pos["join"][item_name]
                    file_name = f_key if f_key.endswith(".lkml") else f"{f_key}.lkml"
                    line = 1
                    if (
                        prop_name
                        and isinstance(j_pos, dict)
                        and prop_name in j_pos
                        and "$p" in j_pos[prop_name]
                    ):
                        line = int(j_pos[prop_name]["$p"][0]) + 1
                    elif isinstance(j_pos, dict) and "$p" in j_pos:
                        line = int(j_pos["$p"][0]) + 1
                    return file_name, line

    elif obj_type == "model":
        return f"models/{item_name}.model.lkml", 1

    return None, 1


def discover_strings_files(root: Path) -> dict[str, tuple[str, dict[str, Any]]]:
    """Find and parse all *.strings.json files under root."""
    found: dict[str, tuple[str, dict[str, Any]]] = {}
    for f in sorted(root.rglob("*.strings.json")):
        if not f.is_file():
            continue
        locale = f.name[: -len(".strings.json")]
        rel_path = f.relative_to(root).as_posix()
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Could not read strings file {f}: {e}")
            continue

        if not isinstance(data, dict):
            continue

        if locale in found:
            # Merge keys into existing entry
            _existing_rel, existing_dict = found[locale]
            existing_dict.update(data)
        else:
            found[locale] = (rel_path, data)
    return found


def _resolve_manifest_settings(project: LookmlProject) -> tuple[str, str]:
    default_locale = "en"
    localization_level = "permissive"

    manifest = project.manifest
    if manifest is None and isinstance(project.file, LookmlFile):
        manifest = getattr(project.file, "manifest", None)

    if isinstance(manifest, dict):
        for val in manifest.values():
            if isinstance(val, LookmlManifest):
                manifest = val
                break
            sub = getattr(val, "manifest", None)
            if isinstance(sub, LookmlManifest):
                manifest = sub
                break
            if isinstance(sub, dict) and sub:
                first = next(iter(sub.values()))
                if isinstance(first, LookmlManifest):
                    manifest = first
                    break

    if manifest is not None and getattr(manifest, "localization_settings", None):
        ls = manifest.localization_settings
        if isinstance(ls, LookmlLocalizationSettings):
            if ls.default_locale:
                default_locale = ls.default_locale
            if ls.localization_level:
                localization_level = ls.localization_level
        elif isinstance(ls, dict):
            if ls.get("default_locale"):
                default_locale = str(ls["default_locale"])
            if ls.get("localization_level"):
                localization_level = str(ls["localization_level"])

    return default_locale, localization_level


def analyze_lookml_translations(
    path: Path | str,
    locale: str | None = None,
) -> TranslationAnalysisResult:
    """Analyze LookML models, explores, views, and fields for translation completeness and bypasses."""
    root = Path(path).resolve()
    if not root.exists():
        raise FileNotFoundError(f"Path not found: {path}")

    strings_map = discover_strings_files(root)
    if not strings_map:
        raise ValueError("No strings JSON files were found in the project.")

    project = parse_lookml(path=root)
    default_locale, manifest_level = _resolve_manifest_settings(project)

    if locale is not None:
        if locale not in strings_map:
            raise ValueError(f"Strings JSON not found for locale '{locale}'")
        target_locales = [locale]
        if default_locale in strings_map and default_locale not in target_locales:
            target_locales.append(default_locale)
    else:
        target_locales = sorted(strings_map.keys())

    default_locale_file = (
        strings_map[default_locale][0] if default_locale in strings_map else None
    )
    default_locale_strings = (
        strings_map[default_locale][1] if default_locale in strings_map else {}
    )

    positions = project.positions
    collected: list[tuple[str, TranslationUsage]] = []

    # 1. Models & Explores
    seen_explores: set[str] = set()
    for model_name, model_obj in (project.model or {}).items():
        if model_name != "inline":
            m_file, m_line = _find_position(positions, "model", None, model_name)
            if model_obj.label:
                collected.append(
                    (
                        model_obj.label,
                        TranslationUsage(
                            object_type="model",
                            object_name=model_name,
                            property="label",
                            missing_explicit_label=False,
                            file=m_file,
                            line=m_line,
                        ),
                    )
                )
            else:
                collected.append(
                    (
                        _titleize(model_name),
                        TranslationUsage(
                            object_type="model",
                            object_name=model_name,
                            property="label",
                            missing_explicit_label=True,
                            file=m_file,
                            line=m_line,
                        ),
                    )
                )

        for explore_name, exp in (model_obj.explore or {}).items():
            if explore_name in seen_explores:
                continue
            seen_explores.add(explore_name)

            explore_obj = exp[0] if isinstance(exp, list) and exp else exp
            if not isinstance(explore_obj, LookmlExplore) or explore_obj.hidden is True:
                continue

            e_file, e_line = _find_position(positions, "explore", None, explore_name)

            # Explore label
            if explore_obj.label:
                collected.append(
                    (
                        explore_obj.label,
                        TranslationUsage(
                            object_type="explore",
                            object_name=explore_name,
                            property="label",
                            missing_explicit_label=False,
                            file=e_file,
                            line=e_line,
                        ),
                    )
                )
            else:
                collected.append(
                    (
                        _titleize(explore_name),
                        TranslationUsage(
                            object_type="explore",
                            object_name=explore_name,
                            property="label",
                            missing_explicit_label=True,
                            file=e_file,
                            line=e_line,
                        ),
                    )
                )

            # Explore view_label
            if explore_obj.view_label:
                collected.append(
                    (
                        explore_obj.view_label,
                        TranslationUsage(
                            object_type="explore",
                            object_name=explore_name,
                            property="view_label",
                            missing_explicit_label=False,
                            file=e_file,
                            line=e_line,
                        ),
                    )
                )

            # Explore group_label
            if explore_obj.group_label:
                collected.append(
                    (
                        explore_obj.group_label,
                        TranslationUsage(
                            object_type="explore",
                            object_name=explore_name,
                            property="group_label",
                            missing_explicit_label=False,
                            file=e_file,
                            line=e_line,
                        ),
                    )
                )

            # Explore description
            if explore_obj.description:
                collected.append(
                    (
                        explore_obj.description,
                        TranslationUsage(
                            object_type="explore",
                            object_name=explore_name,
                            property="description",
                            missing_explicit_label=False,
                            file=e_file,
                            line=e_line,
                        ),
                    )
                )

            # Liquid in explore
            for txt in (
                explore_obj.description,
                explore_obj.sql_always_where,
                explore_obj.sql_always_having,
            ):
                for lkey in _extract_liquid_localization_keys(txt):
                    collected.append(
                        (
                            lkey,
                            TranslationUsage(
                                object_type="explore",
                                object_name=explore_name,
                                property="liquid",
                                missing_explicit_label=False,
                                file=e_file,
                                line=e_line,
                            ),
                        )
                    )

            # Explore Joins
            for join_name, j in (explore_obj.join or {}).items():
                if not isinstance(j, LookmlJoin):
                    continue
                j_file, j_line = _find_position(
                    positions, "join", explore_name, join_name
                )
                j_qual = f"{explore_name}.{join_name}"
                if j.view_label:
                    collected.append(
                        (
                            j.view_label,
                            TranslationUsage(
                                object_type="join",
                                object_name=j_qual,
                                property="view_label",
                                missing_explicit_label=False,
                                file=j_file,
                                line=j_line,
                            ),
                        )
                    )
                elif j.from_:
                    collected.append(
                        (
                            _titleize(join_name),
                            TranslationUsage(
                                object_type="join",
                                object_name=j_qual,
                                property="view_label",
                                missing_explicit_label=True,
                                file=j_file,
                                line=j_line,
                            ),
                        )
                    )

                for txt in (j.sql_on, j.sql_where):
                    for lkey in _extract_liquid_localization_keys(txt):
                        collected.append(
                            (
                                lkey,
                                TranslationUsage(
                                    object_type="join",
                                    object_name=j_qual,
                                    property="liquid",
                                    missing_explicit_label=False,
                                    file=j_file,
                                    line=j_line,
                                ),
                            )
                        )

    # 2. Views & Fields
    views_to_check: list[tuple[str, LookmlView]] = []
    seen_views: set[str] = set()

    for model_obj in (project.model or {}).values():
        for vname, v in (model_obj.view or {}).items():
            if vname not in seen_views:
                seen_views.add(vname)
                v_obj = v[0] if isinstance(v, list) and v else v
                if isinstance(v_obj, LookmlView):
                    views_to_check.append((vname, v_obj))

    if isinstance(project.file, LookmlFile) and project.file.view:
        for vname, v in project.file.view.items():
            if vname not in seen_views:
                seen_views.add(vname)
                v_obj = v[0] if isinstance(v, list) and v else v
                if isinstance(v_obj, LookmlView):
                    views_to_check.append((vname, v_obj))

    for view_name, view_obj in views_to_check:
        if view_obj.hidden is True:
            continue

        v_file, v_line = _find_position(positions, "view", None, view_name)

        # View label
        if view_obj.label:
            collected.append(
                (
                    view_obj.label,
                    TranslationUsage(
                        object_type="view",
                        object_name=view_name,
                        property="label",
                        missing_explicit_label=False,
                        file=v_file,
                        line=v_line,
                    ),
                )
            )
        else:
            collected.append(
                (
                    _titleize(view_name),
                    TranslationUsage(
                        object_type="view",
                        object_name=view_name,
                        property="label",
                        missing_explicit_label=True,
                        file=v_file,
                        line=v_line,
                    ),
                )
            )

        # View view_label
        if view_obj.view_label:
            collected.append(
                (
                    view_obj.view_label,
                    TranslationUsage(
                        object_type="view",
                        object_name=view_name,
                        property="view_label",
                        missing_explicit_label=False,
                        file=v_file,
                        line=v_line,
                    ),
                )
            )

        # View description
        if view_obj.description:
            collected.append(
                (
                    view_obj.description,
                    TranslationUsage(
                        object_type="view",
                        object_name=view_name,
                        property="description",
                        missing_explicit_label=False,
                        file=v_file,
                        line=v_line,
                    ),
                )
            )

        # Fields
        field_categories = [
            ("dimension", view_obj.dimension or {}),
            ("dimension_group", view_obj.dimension_group or {}),
            ("measure", view_obj.measure or {}),
            (
                "filter",
                view_obj.filter or {} if isinstance(view_obj.filter, dict) else {},
            ),
            ("parameter", view_obj.parameter or {}),
        ]

        for cat_type, cat_dict in field_categories:
            for field_name, f_obj in cat_dict.items():
                if _is_field_hidden(f_obj, view_obj.fields_hidden_by_default):
                    continue

                f_qual = f"{view_name}.{field_name}"
                f_file, f_line = _find_position(
                    positions, cat_type, view_name, field_name
                )

                # Field label
                if getattr(f_obj, "label", None) is not None:
                    collected.append(
                        (
                            str(f_obj.label),
                            TranslationUsage(
                                object_type=cat_type,
                                object_name=f_qual,
                                property="label",
                                missing_explicit_label=False,
                                file=f_file,
                                line=f_line,
                            ),
                        )
                    )
                else:
                    collected.append(
                        (
                            _titleize(field_name),
                            TranslationUsage(
                                object_type=cat_type,
                                object_name=f_qual,
                                property="label",
                                missing_explicit_label=True,
                                file=f_file,
                                line=f_line,
                            ),
                        )
                    )

                # Field view_label
                if getattr(f_obj, "view_label", None) is not None:
                    collected.append(
                        (
                            str(f_obj.view_label),
                            TranslationUsage(
                                object_type=cat_type,
                                object_name=f_qual,
                                property="view_label",
                                missing_explicit_label=False,
                                file=f_file,
                                line=f_line,
                            ),
                        )
                    )

                # Field group_label
                if getattr(f_obj, "group_label", None) is not None:
                    collected.append(
                        (
                            str(f_obj.group_label),
                            TranslationUsage(
                                object_type=cat_type,
                                object_name=f_qual,
                                property="group_label",
                                missing_explicit_label=False,
                                file=f_file,
                                line=f_line,
                            ),
                        )
                    )

                # Field group_item_label
                if getattr(f_obj, "group_item_label", None) is not None:
                    collected.append(
                        (
                            str(f_obj.group_item_label),
                            TranslationUsage(
                                object_type=cat_type,
                                object_name=f_qual,
                                property="group_item_label",
                                missing_explicit_label=False,
                                file=f_file,
                                line=f_line,
                            ),
                        )
                    )

                # Field description
                if getattr(f_obj, "description", None) is not None:
                    collected.append(
                        (
                            str(f_obj.description),
                            TranslationUsage(
                                object_type=cat_type,
                                object_name=f_qual,
                                property="description",
                                missing_explicit_label=False,
                                file=f_file,
                                line=f_line,
                            ),
                        )
                    )

                # Case when/else
                case = getattr(f_obj, "case", None)
                if case:
                    whens = (
                        case.when
                        if isinstance(case.when, list)
                        else ([case.when] if case.when else [])
                    )
                    for w in whens:
                        if getattr(w, "label", None):
                            collected.append(
                                (
                                    w.label,
                                    TranslationUsage(
                                        object_type=cat_type,
                                        object_name=f_qual,
                                        property="when_label",
                                        missing_explicit_label=False,
                                        file=f_file,
                                        line=f_line,
                                    ),
                                )
                            )
                    if isinstance(case.else_, str):
                        collected.append(
                            (
                                case.else_,
                                TranslationUsage(
                                    object_type=cat_type,
                                    object_name=f_qual,
                                    property="else_label",
                                    missing_explicit_label=False,
                                    file=f_file,
                                    line=f_line,
                                ),
                            )
                        )

                # Parameter allowed_values
                avs = getattr(f_obj, "allowed_value", None)
                if avs:
                    av_list = avs if isinstance(avs, list) else [avs]
                    for av in av_list:
                        if isinstance(av, LookmlAllowedValue) and av.label:
                            collected.append(
                                (
                                    av.label,
                                    TranslationUsage(
                                        object_type=cat_type,
                                        object_name=f_qual,
                                        property="allowed_value_label",
                                        missing_explicit_label=False,
                                        file=f_file,
                                        line=f_line,
                                    ),
                                )
                            )

                # Links
                links = getattr(f_obj, "link", None)
                if links:
                    link_list = links if isinstance(links, list) else [links]
                    for lk in link_list:
                        if getattr(lk, "label", None):
                            collected.append(
                                (
                                    lk.label,
                                    TranslationUsage(
                                        object_type=cat_type,
                                        object_name=f_qual,
                                        property="link_label",
                                        missing_explicit_label=False,
                                        file=f_file,
                                        line=f_line,
                                    ),
                                )
                            )

                # Actions
                actions = getattr(f_obj, "action", None)
                if actions:
                    act_list = actions if isinstance(actions, list) else [actions]
                    for act in act_list:
                        if getattr(act, "label", None):
                            collected.append(
                                (
                                    act.label,
                                    TranslationUsage(
                                        object_type=cat_type,
                                        object_name=f_qual,
                                        property="action_label",
                                        missing_explicit_label=False,
                                        file=f_file,
                                        line=f_line,
                                    ),
                                )
                            )

                # Liquid in field sql, html
                for txt in (getattr(f_obj, "sql", None), getattr(f_obj, "html", None)):
                    for lkey in _extract_liquid_localization_keys(txt):
                        collected.append(
                            (
                                lkey,
                                TranslationUsage(
                                    object_type=cat_type,
                                    object_name=f_qual,
                                    property="liquid",
                                    missing_explicit_label=False,
                                    file=f_file,
                                    line=f_line,
                                ),
                            )
                        )

    # Group collected items by string
    string_usages: dict[str, list[TranslationUsage]] = defaultdict(list)
    for s, u in collected:
        string_usages[s].append(u)

    missing_translations: list[MissingTranslation] = []

    for s, usages in string_usages.items():
        missing_in_default = s not in default_locale_strings
        missing_in_locs: list[str] = []
        bypassed_in_locs: list[str] = []

        for loc in target_locales:
            loc_dict = strings_map.get(loc, ("", {}))[1]
            if s not in loc_dict:
                missing_in_locs.append(loc)
            else:
                # String is translated in loc, but if missing in default_locale it is bypassed
                if loc != default_locale and missing_in_default:
                    bypassed_in_locs.append(loc)

        has_missing_explicit = any(u.missing_explicit_label for u in usages)
        if (
            missing_in_default
            or missing_in_locs
            or bypassed_in_locs
            or has_missing_explicit
        ):
            missing_translations.append(
                MissingTranslation(
                    string=s,
                    missing_in_default_locale=missing_in_default,
                    missing_in_locales=missing_in_locs,
                    bypassed_in_locales=bypassed_in_locs,
                    usages=usages,
                )
            )

    # Sort missing translations: bypassed first, then missing_in_default, then string
    missing_translations.sort(
        key=lambda m: (
            not bool(m.bypassed_in_locales),
            not m.missing_in_default_locale,
            m.string.lower(),
        )
    )

    # Detect unused keys
    used_strings = set(string_usages.keys())
    unused_keys: list[UnusedKey] = []
    for loc in target_locales:
        loc_dict = strings_map.get(loc, ("", {}))[1]
        for k in sorted(loc_dict.keys()):
            if k not in used_strings:
                unused_keys.append(UnusedKey(locale=loc, key=k))

    # Locales summary
    locales_checked: list[LocaleSummary] = []
    for loc in target_locales:
        rel_f = strings_map.get(loc, ("", {}))[0]
        missing_cnt = sum(
            1 for m in missing_translations if loc in m.missing_in_locales
        )
        bypassed_cnt = sum(
            1 for m in missing_translations if loc in m.bypassed_in_locales
        )
        locales_checked.append(
            LocaleSummary(
                locale=loc,
                file=rel_f,
                missing_count=missing_cnt,
                bypassed_due_to_missing_default_locale_count=bypassed_cnt,
            )
        )

    missing_explicit_count = sum(
        1 for m in missing_translations for u in m.usages if u.missing_explicit_label
    )
    bypassed_count = sum(1 for m in missing_translations if m.bypassed_in_locales)

    return TranslationAnalysisResult(
        default_locale=default_locale,
        default_locale_file=default_locale_file,
        manifest_localization_level=manifest_level,
        locales_checked=locales_checked,
        missing_translations=missing_translations,
        unused_keys=unused_keys,
        missing_explicit_labels_count=missing_explicit_count,
        total_missing_strings_count=len(missing_translations),
        total_bypassed_strings_count=bypassed_count,
    )


def format_translations_text(result: TranslationAnalysisResult) -> str:
    """Format missing translation keys as newline-delimited text."""
    unique_strings = sorted({t.string for t in result.missing_translations})
    return "\n".join(unique_strings)


def format_translations_console(result: TranslationAnalysisResult) -> str:
    """Format analysis result as a human-readable console report."""
    lines: list[str] = [
        "=" * 80,
        "LookML Translation & Localization Analysis",
        "=" * 80,
        f"Default Locale:              {result.default_locale} ({result.default_locale_file or 'not found'})",
        f"Manifest Localization Level: {result.manifest_localization_level}",
    ]
    locs_str = ", ".join(
        f"{ls.locale} ({ls.missing_count} missing"
        + (
            f", {ls.bypassed_due_to_missing_default_locale_count} bypassed"
            if ls.bypassed_due_to_missing_default_locale_count
            else ""
        )
        + ")"
        for ls in result.locales_checked
    )
    lines.append(f"Locales Checked:             {locs_str}")
    lines.append("")

    # Section 1: Bypassed Translations
    bypassed_list = [m for m in result.missing_translations if m.bypassed_in_locales]
    if bypassed_list:
        lines.append("-" * 80)
        lines.append(
            f"1. Bypassed Translations (translated in foreign locales but missing in '{result.default_locale}'):"
        )
        lines.append("-" * 80)
        for m in bypassed_list:
            b_locs = ", ".join(m.bypassed_in_locales)
            lines.append(f'  * "{m.string}"')
            lines.append(
                f"    - Bypassed in: {b_locs} (missing in default locale '{result.default_locale}')"
            )
            for u in m.usages:
                loc_info = f" in {u.file}:{u.line}" if u.file else ""
                lines.append(
                    f"    - Usage: {u.object_type} {u.object_name} ({u.property}){loc_info}"
                )
        lines.append("")

    # Section 2: Missing Explicit Labels on Visible Objects
    unlabeled = [
        u
        for m in result.missing_translations
        for u in m.usages
        if u.missing_explicit_label
    ]
    if unlabeled:
        lines.append("-" * 80)
        lines.append("2. Visible LookML Objects Lacking Explicit 'label':")
        lines.append("-" * 80)
        for u in unlabeled:
            loc_info = f" in {u.file}:{u.line}" if u.file else ""
            sug = _titleize(u.object_name.split(".")[-1])
            lines.append(
                f'  * {u.object_type} {u.object_name}{loc_info} -> suggested label: "{sug}"'
            )
        lines.append("")

    # Section 3: Missing Translations in Locale Files
    missing_in_files = [m for m in result.missing_translations if m.missing_in_locales]
    if missing_in_files:
        lines.append("-" * 80)
        lines.append("3. Missing Translations in Strings Catalogs:")
        lines.append("-" * 80)
        for m in missing_in_files:
            m_locs = ", ".join(m.missing_in_locales)
            lines.append(f'  * "{m.string}"')
            lines.append(f"    - Missing in locales: {m_locs}")
            for u in m.usages:
                loc_info = f" in {u.file}:{u.line}" if u.file else ""
                lines.append(
                    f"    - Usage: {u.object_type} {u.object_name} ({u.property}){loc_info}"
                )
        lines.append("")

    # Section 4: Unused Keys
    if result.unused_keys:
        lines.append("-" * 80)
        lines.append("4. Unused Keys in Strings Catalogs:")
        lines.append("-" * 80)
        by_loc: dict[str, list[str]] = defaultdict(list)
        for uk in result.unused_keys:
            by_loc[uk.locale].append(uk.key)
        for loc, keys in sorted(by_loc.items()):
            lines.append(f"  * [{loc}] {len(keys)} unused keys:")
            for k in keys:
                lines.append(f'    - "{k}"')
        lines.append("")

    # Summary
    lines.append("-" * 80)
    lines.append("Summary:")
    lines.append("-" * 80)
    lines.append(
        f"  - Total Missing Strings:       {result.total_missing_strings_count}"
    )
    lines.append(
        f"  - Total Bypassed Translations: {result.total_bypassed_strings_count}"
    )
    lines.append(
        f"  - Missing Explicit Labels:     {result.missing_explicit_labels_count}"
    )
    lines.append(f"  - Unused String Keys:          {len(result.unused_keys)}")
    lines.append("=" * 80)

    return "\n".join(lines)
