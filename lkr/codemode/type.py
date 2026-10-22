import enum
import inspect
import json
import os
from collections.abc import Mapping, Sequence
from typing import get_args, get_origin

from looker_sdk.sdk.api40 import models as sdk_models
from pydantic import BaseModel

import lkr.extended_sdk_methods.classes as ext_classes

_swagger_data = None
_ext_definitions_cache = None


def to_primitive(obj):
    seen = set()

    def _to_primitive(o):
        if isinstance(o, (str, int, float, bool, type(None))):
            return o

        obj_id = id(o)
        if obj_id in seen:
            return f"<Circular reference to {type(o).__name__}>"
        seen.add(obj_id)

        try:
            if isinstance(o, list):
                return [_to_primitive(item) for item in o]
            if isinstance(o, dict):
                return {k: _to_primitive(v) for k, v in o.items()}
            try:
                return _to_primitive(vars(o))
            except Exception:  # noqa: BLE001
                return str(o)
        finally:
            seen.remove(obj_id)

    return _to_primitive(obj)


def _get_swagger_data():
    global _swagger_data
    if _swagger_data is not None:
        return _swagger_data
        
    current_dir = os.path.dirname(os.path.abspath(__file__))
    swagger_path = os.path.join(current_dir, 'swagger.json')
    
    if not os.path.exists(swagger_path):
        _swagger_data = {}
        return _swagger_data
        
    try:
        with open(swagger_path, 'r') as f:
            _swagger_data = json.load(f)
    except Exception:  # noqa: BLE001
        _swagger_data = {}
        
    return _swagger_data


def _annotation_to_prop(ann, description: str | None = None) -> dict:
    while (args := [a for a in get_args(ann) if a is not type(None)]) and not (
        inspect.isclass(o := get_origin(ann)) and issubclass(o, (Sequence, Mapping))
    ):
        ann = args[0]
    origin = get_origin(ann)
    is_arr = (
        inspect.isclass(origin)
        and issubclass(origin, Sequence)
        and not issubclass(origin, (str, bytes))
    )
    leaf = next((a for a in get_args(ann) if a is not type(None)), ann) if is_arr else ann
    ref = (
        leaf
        if isinstance(leaf, str)
        and leaf not in ("str", "bytes", "int", "float", "bool", "list", "dict", "set", "tuple", "Any", "None")
        else getattr(leaf, "__forward_arg__", None)
        or (
            leaf.__name__
            if inspect.isclass(leaf)
            and (issubclass(leaf, BaseModel) or leaf.__module__ == sdk_models.__name__)
            and not issubclass(leaf, (enum.Enum, Sequence, Mapping))
            else None
        )
    )
    ptype = (
        "object"
        if inspect.isclass(m := (origin or leaf)) and issubclass(m, Mapping)
        else {bool: "boolean", int: "integer", float: "float"}.get(leaf, "string")
    )
    prop: dict = {"description": description} if description else {}
    target = {"$ref": f"#/definitions/{ref}"} if ref else {"type": ptype}
    return {**prop, "type": "array", "items": target} if is_arr else {**prop, **target}


def _get_ext_definitions() -> dict:
    global _ext_definitions_cache
    if _ext_definitions_cache is not None:
        return _ext_definitions_cache

    swagger_defs = _get_swagger_data().get("definitions", {})
    ext_defs = {}

    for name, cls in inspect.getmembers(sdk_models, predicate=inspect.isclass):
        if cls.__module__ != sdk_models.__name__ or name in swagger_defs:
            continue
        if issubclass(cls, enum.Enum):
            vals = [str(e.value) for e in cls if e.value != "invalid_api_enum_value"]
            ext_defs[name] = {
                "properties": {
                    "values": {"type": "string", "description": ", ".join(vals)}
                }
            }
        elif anns := getattr(cls, "__annotations__", None):
            base_props = (
                swagger_defs.get(name[5:], {}).get("properties", {})
                if name.startswith("Write")
                else {}
            )
            ext_defs[name] = {
                "properties": {
                    fname: base_props[fname]
                    if fname in base_props
                    else _annotation_to_prop(fann)
                    for fname, fann in anns.items()
                }
            }

    for name, cls in inspect.getmembers(ext_classes, predicate=inspect.isclass):
        if issubclass(cls, BaseModel) and cls is not BaseModel:
            ext_defs[name] = {
                "properties": {
                    fname: _annotation_to_prop(field.annotation, field.description)
                    for fname, field in getattr(cls, "model_fields", {}).items()
                }
            }
    _ext_definitions_cache = ext_defs
    return ext_defs


def lookup_type(type_name: str) -> str:
    """Lookup the Type and all nested reference types from swagger.json."""
    swagger = _get_swagger_data()
    definitions = dict(_get_ext_definitions())
    definitions.update(swagger.get('definitions', {}))
    
    if type_name not in definitions:
        type_name = next(
            (k for k in definitions if k.lower() == type_name.lower()), type_name
        )
    if type_name not in definitions:
        return f"Type '{type_name}' not found."
        
    seen_types = set()
    result_lines = []
    
    def _resolve_type(name, def_obj):
        if name in seen_types:
            return
        seen_types.add(name)
        
        result_lines.append(f"Type: {name}")
        properties = def_obj.get('properties', {})
        if not properties:
            result_lines.append("  (No properties)")
            return
            
        for prop_name, prop_val in properties.items():
            prop_type = prop_val.get('type', '')
            description = prop_val.get('description', '')
            ref = prop_val.get('$ref', '')
            
            if ref:
                ref_type = ref.split('/')[-1]
                result_lines.append(f"  - {prop_name}: {ref_type} (Ref)")
            elif prop_type == 'array':
                items = prop_val.get('items', {})
                item_ref = items.get('$ref', '')
                item_type = items.get('type', '')
                if item_ref:
                    ref_type = item_ref.split('/')[-1]
                    result_lines.append(f"  - {prop_name}: Array of {ref_type}")
                else:
                    result_lines.append(f"  - {prop_name}: Array of {item_type}")
            else:
                result_lines.append(f"  - {prop_name}: {prop_type}")
                
            if description:
                desc_lines = description.strip().split('\n')
                for dl in desc_lines:
                    result_lines.append(f"      # {dl}")
                    
        # Now resolve references
        for prop_name, prop_val in properties.items():
            ref = prop_val.get('$ref', '')
            if ref:
                ref_type = ref.split('/')[-1]
                if ref_type in definitions and ref_type not in seen_types:
                    result_lines.append("")
                    _resolve_type(ref_type, definitions[ref_type])
            
            if prop_val.get('type') == 'array':
                items = prop_val.get('items', {})
                item_ref = items.get('$ref', '')
                if item_ref:
                    ref_type = item_ref.split('/')[-1]
                    if ref_type in definitions and ref_type not in seen_types:
                        result_lines.append("")
                        _resolve_type(ref_type, definitions[ref_type])
                        
    _resolve_type(type_name, definitions[type_name])
    return "\n".join(result_lines)
