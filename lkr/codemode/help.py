import inspect
import json
import os
import re

from lkr.codemode.constant import EXCLUDED_FUNCS

_operation_map = None

def _get_operation_map():
    global _operation_map
    if _operation_map is not None:
        return _operation_map
        
    _operation_map = {}
    current_dir = os.path.dirname(os.path.abspath(__file__))
    swagger_path = os.path.join(current_dir, 'swagger.json')
    
    if not os.path.exists(swagger_path):
        return _operation_map
        
    try:
        with open(swagger_path, 'r') as f:
            swagger = json.load(f)
            paths = swagger.get('paths', {})
            for path_item in paths.values():
                for op in path_item.values():
                    if isinstance(op, dict) and 'operationId' in op:
                        op_id = op['operationId']
                        summary = op.get('summary', '')
                        description = op.get('description', '')
                        if description.startswith('###'):
                            description = description.lstrip('#').strip()
                        _operation_map[op_id] = {
                            'summary': summary,
                            'description': description
                        }
    except (OSError, json.JSONDecodeError):
        pass
        
    return _operation_map

def _get_enhanced_doc(name: str, method) -> str:
    doc = method.__doc__ or ""
    op_map = _get_operation_map()
    if name in op_map:
        op_info = op_map[name]
        summary = op_info['summary']
        description = op_info['description']
        
        parts = []
        if summary:
            parts.append(summary)
        if description:
            parts.append(description)
            
        if parts:
            return "\n".join(parts)
            
    return doc


def _get_matches(query: str, external_funcs: dict, sdk) -> list:
    """Helper to get matching functions with hit details."""
    escaped_query = re.escape(query).replace(r'\*', '.*').replace(r'\?', '.')
    try:
        pattern = re.compile(escaped_query, re.IGNORECASE)
    except re.error:
        pattern = re.compile(re.escape(query), re.IGNORECASE)

    matches = []
    for name in external_funcs:
        if name in EXCLUDED_FUNCS:
            continue
            
        doc = ""
        method = None
        if hasattr(sdk, name):
            method = getattr(sdk, name)
            doc = _get_enhanced_doc(name, method)
            
        hit_in_name = bool(pattern.search(name))
        
        # Search in docstring lines
        matching_lines = []
        if doc:
            for line in doc.split('\n'):
                if pattern.search(line):
                    matching_lines.append(line.strip())
                    
        # Search in parameters (Inputs)
        hit_in_params = False
        if method:
            try:
                sig = inspect.signature(method)
                params = list(sig.parameters.keys())
                if any(pattern.search(p) for p in params):
                    hit_in_params = True
            except Exception:  # noqa: BLE001, S110
                pass
                
        # Search in return type fields (Outputs)
        hit_in_output = False
        output_fields = []
        if method:
            try:
                sig = inspect.signature(method)
                return_type = sig.return_annotation
                if return_type and hasattr(return_type, '__annotations__'):
                    fields = list(return_type.__annotations__.keys())
                    matching_fields = [f for f in fields if pattern.search(f)]
                    if matching_fields:
                        hit_in_output = True
                        output_fields = matching_fields
            except Exception:  # noqa: BLE001, S110
                pass
                
        if hit_in_name or matching_lines or hit_in_params or hit_in_output:
            matches.append({
                'name': name,
                'hit_in_name': hit_in_name,
                'matching_lines': matching_lines,
                'hit_in_params': hit_in_params,
                'output_fields': output_fields
            })
            
    return matches

def _get_type_matches(query: str) -> list:
    escaped_query = re.escape(query).replace(r'\*', '.*').replace(r'\?', '.')
    try:
        pattern = re.compile(escaped_query, re.IGNORECASE)
    except re.error:
        pattern = re.compile(re.escape(query), re.IGNORECASE)

    try:
        from lkr.codemode.type import _get_ext_definitions, _get_swagger_data
        swagger = _get_swagger_data()
        definitions = dict(swagger.get('definitions', {}))
        definitions.update(_get_ext_definitions())
    except Exception:  # noqa: BLE001
        return []

    matches = []
    for type_name, def_obj in definitions.items():
        if not isinstance(def_obj, dict):
            continue
        hit_in_name = bool(pattern.search(type_name))
        
        matching_props = []
        matching_desc = []
        
        properties = def_obj.get('properties', {})
        if isinstance(properties, dict):
            for prop_name, prop_val in properties.items():
                if not isinstance(prop_val, dict):
                    continue
                if pattern.search(prop_name):
                    matching_props.append(prop_name)
                desc = prop_val.get('description', '')
                if desc and pattern.search(desc):
                    matching_desc.append(f"{prop_name}: {desc.strip().splitlines()[0]}")
                
        if hit_in_name or matching_props or matching_desc:
            matches.append({
                'name': type_name,
                'hit_in_name': hit_in_name,
                'matching_props': matching_props,
                'matching_desc': matching_desc
            })
    return sorted(matches, key=lambda x: x['name'])


def search_help(query: str, external_funcs: dict, sdk) -> str:
    """Search for functions and return a summary string with snippets."""
    func_matches = _get_matches(query, external_funcs, sdk)
    type_matches = _get_type_matches(query)
    
    if not func_matches and not type_matches:
        return f"No matches found for '{query}'."
        
    lines = []
    for m in func_matches:
        hit_info = []
        if m['hit_in_name']:
            hit_info.append("Name match")
        if m['matching_lines']:
            hit_info.append(f"Doc hit: \"{m['matching_lines'][0]}\"")
        if m['hit_in_params']:
            hit_info.append("Input param match")
        if m['output_fields']:
            hit_info.append(f"Output field match: {', '.join(m['output_fields'][:2])}")
            
        lines.append(f"- Function: {m['name']} ({' | '.join(hit_info)})")
        
    for m in type_matches:
        hit_info = []
        if m['hit_in_name']:
            hit_info.append("Name match")
        if m['matching_props']:
            hit_info.append(f"Property match: {', '.join(m['matching_props'][:2])}")
        if m['matching_desc']:
            hit_info.append(f"Comment hit: \"{m['matching_desc'][0]}\"")
            
        lines.append(f"- Type: {m['name']} ({' | '.join(hit_info)})")
        
    return f"Matches found for '{query}':\n" + "\n".join(lines)

def search_with_lookups(query: str, external_funcs: dict, sdk) -> list:
    """Search for functions and return the array of lookups for matches."""
    func_matches = _get_matches(query, external_funcs, sdk)
    type_matches = _get_type_matches(query)
    
    results = []
    for m in func_matches:
        results.append(lookup_function(m['name'], external_funcs, sdk))
    for m in type_matches:
        try:
            from lkr.codemode.type import lookup_type
            results.append(lookup_type(m['name']))
        except Exception:  # noqa: BLE001, S110
            pass
    return results

def lookup_function(name: str, external_funcs: dict, sdk) -> str:
    """Look up the exact name of a function or type and return its docstring, inputs, and outputs."""
    if name not in external_funcs:
        # Check if it's a type name
        try:
            from lkr.codemode.type import lookup_type
            res = lookup_type(name)
            if not res.startswith("Type '"):
                return res
        except Exception:  # noqa: BLE001, S110
            pass
        return f"Function or type '{name}' not found."
        
    if not hasattr(sdk, name):
        return f"{name} is a built-in helper function."
        
    method = getattr(sdk, name)
    doc = _get_enhanced_doc(name, method) or "No docstring available."
    
    def _get_type_str(t):
        if t == inspect._empty:
            return "Any"
        if hasattr(t, '__name__'):
            return t.__name__
        return str(t)

    try:
        sig = inspect.signature(method)
        
        # Inputs
        inputs = []
        for param_name, param in sig.parameters.items():
            inputs.append(f"- {param_name}: {_get_type_str(param.annotation)}")
        inputs_str = "\n".join(inputs) if inputs else "None"
        
        # Outputs
        return_type = sig.return_annotation
        outputs_str = f"Return Type: {_get_type_str(return_type)}"
        
        if return_type and hasattr(return_type, '__annotations__'):
            fields = []
            for field_name, field_type in return_type.__annotations__.items():
                fields.append(f"  - {field_name}: {_get_type_str(field_type)}")
            if fields:
                outputs_str += "\nFields:\n" + "\n".join(fields)
                
        return f"""
Function: {name}

Docstring:
{doc}

Inputs:
{inputs_str}

Outputs:
{outputs_str}
"""
    except Exception as e:  # noqa: BLE001
        return f"Function: {name}\n\nDocstring:\n{doc}\n\n(Could not inspect signature: {e})"
