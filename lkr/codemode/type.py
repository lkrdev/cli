import json
import os

_swagger_data = None

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

def lookup_type(type_name: str) -> str:
    """Lookup the Type and all nested reference types from swagger.json."""
    swagger = _get_swagger_data()
    definitions = swagger.get('definitions', {})
    
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
