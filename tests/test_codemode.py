import json
import os
import tempfile
from collections.abc import Iterator
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from looker_sdk import models40 as mdls
from looker_sdk.rtl.auth_session import AuthSession
from looker_sdk.rtl.transport import Transport
from typer.testing import CliRunner

from lkr.codemode.main import run_python_code
from lkr.extended_sdk_methods import ExtendedLooker40SDK
from lkr.main import app


class DummyAuth:
    def __init__(self) -> None:
        self.settings = MagicMock()
        self.settings.base_url = "https://example.looker.com"
        self.settings.agent_tag = "test"

    def authenticate(self, request: object) -> object:
        return request


class MockLookerSDK(ExtendedLooker40SDK):
    def __init__(self) -> None:
        super().__init__(
            auth=cast(AuthSession, DummyAuth()),
            deserialize=MagicMock(),
            serialize=MagicMock(),
            transport=cast(Transport, MagicMock()),
            api_version="4.0",
        )

    def me(self, *args: object, **kwargs: object) -> mdls.User:
        """Get information about the currently calling user."""
        return cast(
            "mdls.User",
            {
                "first_name": "Test",
                "last_name": "User",
                "personal_folder_id": "1",
            },
        )

    def folder(
        self, folder_id: str, *args: object, **kwargs: object
    ) -> mdls.Folder:
        """Get a specific folder."""
        return cast(
            "mdls.Folder",
            {
                "id": folder_id,
                "name": f"Folder {folder_id}",
            },
        )

    def folder_children(
        self, folder_id: str, *args: object, **kwargs: object
    ) -> list[mdls.Folder]:
        """Get the children of a specific folder."""
        if str(folder_id) == "1":
            return cast(
                "list[mdls.Folder]",
                [
                    {
                        "id": "2",
                        "name": "Child Folder 1",
                    }
                ],
            )
        return []

    def update_session(
        self, body: object = None, *args: object, **kwargs: object
    ) -> mdls.ApiSession:
        """Update session workspace."""
        return cast(
            "mdls.ApiSession",
            {
                "workspace_id": body.get("workspace_id", "dev")
                if isinstance(body, dict)
                else "dev"
            },
        )


@pytest.fixture(autouse=True)
def mock_get_mcp_sdk() -> Iterator[None]:
    with patch("lkr.codemode.main.get_mcp_sdk", return_value=MockLookerSDK()):
        yield


def test_sdk_object() -> None:
    code_sdk = """
me_obj = sdk.me()
return me_obj["first_name"]
"""
    result = run_python_code(code_sdk)
    assert result == "Test"

def test_examples() -> None:
    code_examples = """
return examples()
"""
    result = run_python_code(code_examples)
    assert "Find all dashboard-related methods" in result

def test_dev_mode() -> None:
    code_dev = """
return "Dev mode ran"
"""
    result = run_python_code(code_dev, dev_mode=True)
    assert result == "Dev mode ran"

def test_help_search() -> None:
    res_empty = run_python_code("return help()")
    assert "SANDBOX DISCOVERY" in res_empty
    assert 'lookup("run_inline_query")' in res_empty
    assert 'lookup_type("WriteQuery")' in res_empty

    code_help = """
return help('dashboard')
"""
    result = run_python_code(code_help)
    assert "Matches found" in result
    assert "Tip: Use lookup('func_name') or lookup_type('TypeName')" in result

    res_none = run_python_code("return help('zzz_no_such_method_xyz')")
    assert "Try help('*keyword*'), lookup('func_name'), or lookup_type('TypeName')" in res_none

def test_lookup() -> None:
    code_lookup = """
return lookup('me')
"""
    result = run_python_code(code_lookup)
    assert len(result) > 0

def test_readme() -> None:
    code_readme = """
return readme()
"""
    result = run_python_code(code_readme)
    assert "SDK Access" in result

def test_wildcard_search() -> None:
    code_help = """
return help('*dashboard*')
"""
    result = run_python_code(code_help)
    assert "Matches found" in result

def test_search_with_lookups() -> None:
    code_search = """
return search_with_lookups('board_item')
"""
    result = run_python_code(code_search)
    assert "Function: board_item" in result

def test_lookup_type() -> None:
    code_type = """
return lookup_type('User')
"""
    result = run_python_code(code_type)
    assert "Type: User" in result
    assert "CredentialsApi3" in result

def test_help_search_description() -> None:
    code_help = """
return help('currently calling')
"""
    result = run_python_code(code_help)
    assert "Matches found" in result
    assert "me" in result

def test_lookup_type_recursion() -> None:
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
    lkr.codemode.type._get_swagger_data = lambda: mock_swagger  # type: ignore
    
    try:
        code = """
return lookup_type('Node')
"""
        result = run_python_code(code)
        assert result.count("Type: Node") == 1
        assert "child: Node (Ref)" in result
    finally:
        lkr.codemode.type._get_swagger_data = original_get_swagger

def test_basic_usage() -> None:
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

def test_recursive_listing() -> None:
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


def test_extended_sdk_methods_present() -> None:
    ext_methods = [
        k for k, v in ExtendedLooker40SDK.__dict__.items() if not k.startswith("_") and callable(v)
    ]
    code = f"""
methods = {ext_methods!r}
for m in methods:
    if m not in dir():
        return "Missing " + m
return "All present"
"""
    result = run_python_code(code)
    assert result == "All present"


def test_extended_models_help_search() -> None:
    code_help = """
return help('ProjectGeneratorTable')
"""
    result = run_python_code(code_help)
    assert "Type: ProjectGeneratorTable" in result
    assert "Property match" in result or "Name match" in result

    code_lookup = """
return lookup('ProjectGeneratorTable')
"""
    result_lookup = run_python_code(code_lookup)
    assert "Type: ProjectGeneratorTable" in result_lookup
    assert "The fully qualified schema" in result_lookup
    assert "primary_key: string" in result_lookup


def test_commit_help_and_lookup() -> None:
    code_help = """
return help('commit')
"""
    result = run_python_code(code_help)
    assert "Function: commit" in result or "Type: ProjectCommitRequest" in result

    code_lookup = """
return lookup('commit')
"""
    result_lookup = run_python_code(code_lookup)
    assert "Function: commit" in result_lookup
    assert "Looker automatically stages and commits all modified" in result_lookup

    code_lookup_model = """
return lookup('ProjectCommitRequest')
"""
    result_model = run_python_code(code_lookup_model)
    assert "Type: ProjectCommitRequest" in result_model
    assert "Looker automatically stages and commits" in result_model


def test_captured_print_json() -> None:
    code = """
print("Hello from stdout")
return {"status": "success"}
"""
    result_raw = run_python_code(code)
    data = json.loads(result_raw)
    assert data["stdout"] == "Hello from stdout\n"
    assert data["result"] == {"status": "success"}

def test_captured_print_json_many() -> None:
    code = """
for i in range(10):
    print(i)
return {"status": "success"}
"""
    result_raw = run_python_code(code)
    data = json.loads(result_raw)
    assert data["stdout"] == "0\n1\n2\n3\n4\n5\n6\n7\n8\n9\n"
    assert data["result"] == {"status": "success"}


def test_parent_runtime_not_polluted(capfd: pytest.CaptureFixture[str]) -> None:
    code = """
print("This should be trapped and not leak to parent stdout")
print("Also checking second print")
return {"status": "clean"}
"""
    result_raw = run_python_code(code)
    data = json.loads(result_raw)
    assert "This should be trapped" in data["stdout"]
    assert "Also checking" in data["stdout"]
    
    out, _err = capfd.readouterr()
    assert out == ""

runner = CliRunner()

def test_cli_code_mode_sandbox_code() -> None:
    result = runner.invoke(app, ["code-mode", "sandbox", "--code", "return me()"])
    assert result.exit_code == 0
    assert "Test" in result.stdout

def test_cli_code_mode_sandbox_sdk_code() -> None:
    result = runner.invoke(app, ["code-mode", "sandbox", "--code", "return sdk.me()"])
    assert result.exit_code == 0
    assert "Test" in result.stdout

def test_cli_code_mode_sandbox_file() -> None:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False) as f:
        f.write("return me()")
        temp_path = f.name
        
    try:
        result = runner.invoke(app, ["code-mode", "sandbox", "--file", temp_path])
        assert result.exit_code == 0
        assert "Test" in result.stdout
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

def test_cli_code_mode_sandbox_both_error() -> None:
    result = runner.invoke(app, ["code-mode", "sandbox", "--code", "return me()", "--file", "dummy.py"])
    assert result.exit_code == 1

def test_cli_code_mode_sandbox_neither_error() -> None:
    result = runner.invoke(app, ["code-mode", "sandbox"])
    assert result.exit_code == 1


def test_update_session_blocked_by_default() -> None:
    code = """
update_session(body={"workspace_id": "dev"})
"""
    result = run_python_code(code)
    assert "update_session is disabled in code-mode by default" in result
    assert "calling update_session affects anyone using this OAuth token/session" in result


def test_update_session_allowed_with_flag(caplog: pytest.LogCaptureFixture) -> None:
    code = """
res = update_session(body={"workspace_id": "dev"})
return res["workspace_id"]
"""
    result = run_python_code(code, allow_update_session=True)
    assert result == "dev"
    assert "Calling update_session will affect API clients using this access token" in caplog.text


def test_cli_code_mode_sandbox_update_session_blocked() -> None:
    result = runner.invoke(
        app,
        ["code-mode", "sandbox", "--code", 'update_session(body={"workspace_id": "dev"})'],
    )
    assert "update_session is disabled in code-mode by default" in result.stdout
    assert "calling update_session affects anyone using this OAuth token/session" in result.stdout



def test_cli_code_mode_sandbox_update_session_allowed() -> None:
    result = runner.invoke(
        app,
        ["code-mode", "sandbox", "--allow-update-session", "--code", 'return update_session(body={"workspace_id": "dev"})["workspace_id"]'],
    )
    assert result.exit_code == 0
    assert "dev" in result.stdout


def test_cli_code_mode_discovery_offline() -> None:
    with patch("lkr.codemode.main.get_mcp_sdk", side_effect=AssertionError("should not authenticate")):
        res_group_help = runner.invoke(app, ["code-mode", "--help"])
        assert res_group_help.exit_code == 0
        assert "lkr code-mode type WriteQuery" in res_group_help.stdout

        res_default = runner.invoke(app, ["code-mode", "help"])
        assert res_default.exit_code == 0
        assert "SDK Access" in res_default.stdout
        assert "lkr code-mode help run_inline_query" in res_default.stdout

        res_exact = runner.invoke(app, ["code-mode", "help", "run_lookml_test"])
        assert res_exact.exit_code == 0
        assert "Function: run_lookml_test" in res_exact.stdout
        assert "Optional[str]" in res_exact.stdout
        assert "Sequence[LookmlTestResult]" in res_exact.stdout

        res_exact_with_others = runner.invoke(app, ["code-mode", "help", "dashboard"])
        assert res_exact_with_others.exit_code == 0
        assert "Function: dashboard" in res_exact_with_others.stdout
        assert "Other matches for 'dashboard':" in res_exact_with_others.stdout
        assert "search_dashboards" in res_exact_with_others.stdout

        res_pattern = runner.invoke(app, ["code-mode", "help", "*dashboard*"])
        assert res_pattern.exit_code == 0
        assert "Matches found for '*dashboard*':" in res_pattern.stdout

        res_search = runner.invoke(app, ["code-mode", "search", "board_item"])
        assert res_search.exit_code == 0
        assert "Function: board_item" in res_search.stdout

        res_search_none = runner.invoke(app, ["code-mode", "search", "zzz_no_such_method_xyz"])
        assert res_search_none.exit_code == 0
        assert "No matches found" in res_search_none.stdout

        res_type = runner.invoke(app, ["code-mode", "type", "writequery"])
        assert res_type.exit_code == 0
        assert "Type: WriteQuery" in res_type.stdout
        assert "model: string" in res_type.stdout


