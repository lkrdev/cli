import inspect
import json
import os
from pydantic import BaseModel
import lkr.extended_sdk_methods.classes as ext_classes

_swagger_data = None
_ext_definitions_cache = None


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
    except Exception:
        _swagger_data = {}
        
    return _swagger_data


def _get_ext_definitions() -> dict:
    global _ext_definitions_cache
    if _ext_definitions_cache is not None:
        return _ext_definitions_cache

    ext_defs = {}
    for name, cls in inspect.getmembers(ext_classes, predicate=inspect.isclass):
        if issubclass(cls, BaseModel) and cls is not BaseModel:
            properties = {}
            for field_name, field in getattr(cls, 'model_fields', {}).items():
                ann = field.annotation
                origin = getattr(ann, '__origin__', None)
                args = getattr(ann, '__args__', ())
                
                is_array = origin in (list, set)
                
                types_to_check = [ann]
                if origin is not None:
                    types_to_check = list(args)
                    
                ref_model = None
                prop_type = "string"
                
                for t in types_to_check:
                    if t is type(None):
                        continue
                    if inspect.isclass(t) and issubclass(t, BaseModel):
                        ref_model = t
                    elif t in (str, bytes):
                        prop_type = "string"
                    elif t in (int, float):
                        prop_type = t.__name__
                    elif t is bool:
                        prop_type = "boolean"
                    elif hasattr(t, '__origin__') and getattr(t, '__origin__') in (list, set):
                        is_array = True
                        sub_args = getattr(t, '__args__', ())
                        for sub_t in sub_args:
                            if inspect.isclass(sub_t) and issubclass(sub_t, BaseModel):
                                ref_model = sub_t
                            elif sub_t is not type(None):
                                prop_type = getattr(sub_t, '__name__', str(sub_t))
                                
                prop_dict = {}
                if field.description:
                    prop_dict['description'] = field.description
                    
                if is_array:
                    prop_dict['type'] = 'array'
                    if ref_model:
                        prop_dict['items'] = {'$ref': f'#/definitions/{ref_model.__name__}'}
                    else:
                        prop_dict['items'] = {'type': prop_type}
                elif ref_model:
                    prop_dict['$ref'] = f'#/definitions/{ref_model.__name__}'
                else:
                    prop_dict['type'] = prop_type
                    
                properties[field_name] = prop_dict
            ext_defs[name] = {'properties': properties}
    _ext_definitions_cache = ext_defs
    return ext_defs


def lookup_type(type_name: str) -> str:
    """Lookup the Type and all nested reference types from swagger.json."""
    swagger = _get_swagger_data()
    definitions = dict(swagger.get('definitions', {}))
    definitions.update(_get_ext_definitions())
    
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
