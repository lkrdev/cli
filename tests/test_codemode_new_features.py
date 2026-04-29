from lkr.codemode.main import run_python_code

def test_sdk_object():
    code_sdk = """
me_obj = sdk.me()
return me_obj["first_name"]
"""
    result = run_python_code(code_sdk)
    assert len(result) > 0

def test_examples():
    code_examples = """
return examples()
"""
    result = run_python_code(code_examples)
    assert "Find all dashboard-related methods" in result

def test_dev_mode():
    code_dev = """
return "Dev mode ran"
"""
    result = run_python_code(code_dev, dev_mode=True)
    assert result == "Dev mode ran"

def test_help_search():
    code_help = """
return help('dashboard')
"""
    result = run_python_code(code_help)
    assert "Matches found" in result

def test_lookup():
    code_lookup = """
return lookup('me')
"""
    result = run_python_code(code_lookup)
    assert len(result) > 0

def test_readme():
    code_readme = """
return readme()
"""
    result = run_python_code(code_readme)
    assert "SDK Access" in result

def test_wildcard_search():
    code_help = """
return help('*dashboard*')
"""
    result = run_python_code(code_help)
    assert "Matches found" in result

def test_search_with_lookups():
    code_search = """
return search_with_lookups('board_item')
"""
    result = run_python_code(code_search)
    print(result)
    assert "Function: board_item" in result

def test_lookup_type():
    code_type = """
return lookup_type('User')
"""
    result = run_python_code(code_type)
    assert "Type: User" in result
    assert "CredentialsApi3" in result

def test_help_search_description():
    code_help = """
return help('currently calling')
"""
    result = run_python_code(code_help)
    assert "Matches found" in result
    assert "me" in result

def test_lookup_type_recursion():
    import lkr.codemode.type
    
    mock_swagger = {
        "definitions": {
            "Node": {
                "properties": {
                    "name": {"type": "string"},
                    "child": {"$ref": "#/definitions/Node"}
                }
            }
        }
    }
    
    original_get_swagger = lkr.codemode.type._get_swagger_data
    lkr.codemode.type._get_swagger_data = lambda: mock_swagger
    
    try:
        code = """
return lookup_type('Node')
"""
        result = run_python_code(code)
        assert result.count("Type: Node") == 1
        assert "child: Node (Ref)" in result
    finally:
        lkr.codemode.type._get_swagger_data = original_get_swagger