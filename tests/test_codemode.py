from typing import Any, cast
import pytest
from unittest.mock import patch, MagicMock
from looker_sdk.rtl.auth_session import AuthSession
from looker_sdk.rtl.transport import Transport
from lkr.codemode.main import run_python_code
from lkr.extended_sdk_methods import ExtendedLooker40SDK


class DummyAuth:
    def __init__(self):
        self.settings = MagicMock()
        self.settings.base_url = "https://example.looker.com"
        self.settings.agent_tag = "test"

    def authenticate(self, request):
        return request


class MockLookerSDK(ExtendedLooker40SDK):
    def __init__(self):
        super().__init__(
            auth=cast(AuthSession, DummyAuth()),
            deserialize=cast(Any, MagicMock()),
            serialize=cast(Any, MagicMock()),
            transport=cast(Transport, MagicMock()),
            api_version="4.0",
        )

    def me(self, *args, **kwargs):
        """Get information about the currently calling user."""
        return {
            "first_name": "Test",
            "last_name": "User",
            "personal_folder_id": "1",
        }

    def folder(self, folder_id, *args, **kwargs):
        """Get a specific folder."""
        return {
            "id": folder_id,
            "name": f"Folder {folder_id}",
        }

    def folder_children(self, folder_id, *args, **kwargs):
        """Get the children of a specific folder."""
        if str(folder_id) == "1":
            return [
                {
                    "id": "2",
                    "name": "Child Folder 1",
                }
            ]
        return []


@pytest.fixture(autouse=True)
def mock_get_mcp_sdk():
    with patch("lkr.codemode.main.get_mcp_sdk", return_value=MockLookerSDK()):
        yield


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
    setattr(lkr.codemode.type, "_get_swagger_data", lambda: mock_swagger)
    
    try:
        code = """
return lookup_type('Node')
"""
        result = run_python_code(code)
        assert result.count("Type: Node") == 1
        assert "child: Node (Ref)" in result
    finally:
        setattr(lkr.codemode.type, "_get_swagger_data", original_get_swagger)

def test_basic_usage():
    code = """
me_obj = me()
res = []
res.append("Name: " + me_obj["first_name"] + " " + me_obj["last_name"])
personal_folder = folder(me_obj["personal_folder_id"])
res.append("Folders:")
for f in folder_children(personal_folder["id"]):
    res.append(" - " + f["name"])
return "\\n".join(res)
"""
    result = run_python_code(code)
    assert "Name:" in result
    assert "Folders:" in result

def test_recursive_listing():
    code = """
me_obj = me()
personal_folder_id = me_obj["personal_folder_id"]

res = []
def print_folder(folder_id, indent):
    f = folder(folder_id)
    res.append(indent + "+ Folder: " + f["name"])
    
    children = folder_children(folder_id)
    for child in children:
        print_folder(child["id"], indent + "  ")

print_folder(personal_folder_id, "")
return "\\n".join(res)
"""
    result = run_python_code(code)
    assert "+ Folder:" in result


def test_extended_sdk_methods_present():
    code = """
methods = ['all_project_files', 'get_file_content', 'create_file', 'update_file', 'delete_file', 'create_project_directory', 'delete_project_directory']
for m in methods:
    if m not in dir():
        return "Missing " + m
return "All present"
"""
    result = run_python_code(code)
    assert result == "All present"



