from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from lkr.extended_sdk_methods import ExtendedLooker40SDK, FileContent
from lkr.main import app

runner = CliRunner()


@pytest.fixture
def mock_sdk():
    sdk = MagicMock(spec=ExtendedLooker40SDK)
    return sdk


@pytest.fixture
def mock_auth(mock_sdk):
    auth = MagicMock()
    auth.get_current_sdk.return_value = mock_sdk
    return auth


def test_push_command(tmp_path, mock_sdk, mock_auth):
    # Setup local folder and files
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    
    models_dir = project_dir / "models"
    models_dir.mkdir()
    
    model_file = models_dir / "test.model.lkml"
    model_file.write_text('connection: "my_conn"\ninclude: "/views/**/*.view.lkml"')

    # Mock remote inventory containing an orphan
    mock_sdk.all_project_files.return_value = [
        {"id": "models/test.model.lkml"},
        {"id": "orphan_file.lkml"},
    ]

    with patch("lkr.tools.lookml.get_auth", return_value=mock_auth):
        result = runner.invoke(
            app, ["tools", "lookml", "push", str(project_dir), "--deploy"]
        )
        assert result.exit_code == 0

    # Verify orphan deletion
    mock_sdk.delete_file.assert_called_once_with(
        project_id="test_project", file_path="orphan_file.lkml"
    )

    expected_content = 'connection: "my_conn"\ninclude: "/views/**/*.view.lkml"'
    expected_fc = FileContent(
        path="models/test.model.lkml", content=expected_content
    )
    mock_sdk.create_file.assert_not_called()
    mock_sdk.update_file.assert_called_with(
        project_id="test_project", file_content=expected_fc
    )

    # Verify deploy flags
    mock_sdk.commit.assert_called_once()
    mock_sdk.deploy_to_production.assert_called_once_with(
        project_id="test_project"
    )


def test_pull_command(tmp_path, mock_sdk, mock_auth):
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    
    # Create a local orphan that should be removed
    local_orphan = project_dir / "local_orphan.lkml"
    local_orphan.write_text("old content")

    mock_sdk.all_project_files.return_value = [
        {"id": "models/pulled.model.lkml"},
    ]
    mock_sdk.get_file_content.return_value = "pulled lookml content"

    with patch("lkr.tools.lookml.get_auth", return_value=mock_auth):
        result = runner.invoke(
            app, ["tools", "lookml", "pull", str(project_dir), "--deploy"]
        )
        assert result.exit_code == 0

    # Verify new file created locally
    pulled_file = project_dir / "models" / "pulled.model.lkml"
    assert pulled_file.exists()
    assert pulled_file.read_text() == "pulled lookml content"

    # Verify local orphan deleted
    assert not local_orphan.exists()

    # Verify commit and deploy
    mock_sdk.commit.assert_called_once()
    mock_sdk.deploy_to_production.assert_called_once_with(
        project_id="test_project"
    )


def test_pull_ghost_file(tmp_path, mock_sdk, mock_auth):
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    
    views_dir = project_dir / "views"
    views_dir.mkdir()
    
    affinity_file = views_dir / "affinity.view.lkml"
    affinity_file.write_text("old content")

    mock_sdk.all_project_files.return_value = [
        {"id": "views/affinity.view.lkml"},
    ]
    mock_sdk.get_file_content.side_effect = Exception("Not found")

    with patch("lkr.tools.lookml.get_auth", return_value=mock_auth):
        result = runner.invoke(app, ["tools", "lookml", "pull", str(project_dir)])
        assert result.exit_code == 0

    # Verify ghost file was deleted locally
    assert not affinity_file.exists()


def test_deploy_command(mock_sdk, mock_auth):
    with patch("lkr.tools.lookml.get_auth", return_value=mock_auth):
        result = runner.invoke(
            app, ["tools", "lookml", "deploy", "my_deploy_project"]
        )
        assert result.exit_code == 0

    mock_sdk.commit.assert_called_once()
    mock_sdk.deploy_to_production.assert_called_once_with(
        project_id="my_deploy_project"
    )


def test_push_warning(tmp_path, mock_sdk, mock_auth):
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    
    # Create an unsupported file locally
    unsupported_file = project_dir / "unsupported.xyz"
    unsupported_file.write_text("random")

    mock_sdk.all_project_files.return_value = [
        {"id": "remote_unsupported.abc"},
    ]

    with patch("lkr.tools.lookml.get_auth", return_value=mock_auth), patch("lkr.tools.lookml.logger.warning") as mock_warn:
        result = runner.invoke(app, ["tools", "lookml", "push", str(project_dir)])
        assert result.exit_code == 0
        
        # Check warnings called for both local and remote unsupported extensions
        mock_warn.assert_any_call(
            "Local file 'unsupported.xyz' has an extension not supported by Looker and will be skipped."
        )
        mock_warn.assert_any_call(
            "Remote file 'remote_unsupported.abc' has an extension not supported by Looker."
        )
        mock_sdk.delete_file.assert_not_called()


def test_pull_warning(tmp_path, mock_sdk, mock_auth):
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    
    # Create an unsupported local orphan
    unsupported_local = project_dir / "unsupported_local.py"
    unsupported_local.write_text("print('hello')")

    mock_sdk.all_project_files.return_value = [
        {"id": "remote_unsupported.doc"},
    ]

    with patch("lkr.tools.lookml.get_auth", return_value=mock_auth), patch("lkr.tools.lookml.logger.warning") as mock_warn:
        result = runner.invoke(app, ["tools", "lookml", "pull", str(project_dir)])
        assert result.exit_code == 0

        # Check warnings called
        mock_warn.assert_any_call(
            "Remote file 'remote_unsupported.doc' has an extension not supported by Looker."
        )
        mock_warn.assert_any_call(
            "Local file 'unsupported_local.py' has an extension not supported by Looker and will not be synchronized or deleted."
        )
        
        # Verify unsupported local orphan was NOT deleted
        assert unsupported_local.exists()


def test_pull_path_traversal(tmp_path, mock_sdk, mock_auth):
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()

    mock_sdk.all_project_files.return_value = [
        {"id": "../outside/traversal.lkml"},
    ]
    mock_sdk.get_file_content.return_value = "malicious content"

    with patch("lkr.tools.lookml.get_auth", return_value=mock_auth), patch(
        "lkr.tools.lookml.logger.warning"
    ) as mock_warn:
        result = runner.invoke(app, ["tools", "lookml", "pull", str(project_dir)])
        assert result.exit_code == 0

        # Verify the file was not written outside
        outside_file = outside_dir / "traversal.lkml"
        assert not outside_file.exists()
        mock_warn.assert_any_call(
            "Path traversal detected and blocked: ../outside/traversal.lkml"
        )


def test_push_orphan_cleanup_after_upload(tmp_path, mock_sdk, mock_auth):
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()

    views_dir = project_dir / "views"
    views_dir.mkdir()

    view_file = views_dir / "my_view.view.lkml"
    view_file.write_text("view: my_view {}")

    mock_sdk.all_project_files.return_value = [
        {"id": "views/my_view.view.lkml"},
        {"id": "my_view.view.lkml"},
    ]

    with patch("lkr.tools.lookml.get_auth", return_value=mock_auth):
        result = runner.invoke(app, ["tools", "lookml", "push", str(project_dir)])
        assert result.exit_code == 0

    mock_sdk.delete_file.assert_called_once_with(
        project_id="test_project", file_path="my_view.view.lkml"
    )


def test_push_create_directory_recursively_fallback(tmp_path, mock_sdk, mock_auth):
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()

    nested_dir = project_dir / "views2" / "subfolder"
    nested_dir.mkdir(parents=True)

    view_file = nested_dir / "my_view.view.lkml"
    view_file.write_text("view: my_view {}")

    mock_sdk.update_file.side_effect = Exception("File not found")
    # First create_file fails (missing directory), second succeeds
    mock_sdk.create_file.side_effect = [Exception("Directory not found"), None]

    with patch("lkr.tools.lookml.get_auth", return_value=mock_auth):
        result = runner.invoke(app, ["tools", "lookml", "push", str(project_dir)])
        assert result.exit_code == 0

    mock_sdk.create_project_directory.assert_any_call(
        project_id="test_project", directory_path="views2"
    )
    mock_sdk.create_project_directory.assert_any_call(
        project_id="test_project", directory_path="views2/subfolder"
    )
    assert mock_sdk.create_file.call_count == 2


def test_push_single_file_option(tmp_path, mock_sdk, mock_auth):
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()

    views_dir = project_dir / "views"
    views_dir.mkdir()

    view_file = views_dir / "target.view.lkml"
    view_file.write_text("view: target {}")

    other_file = views_dir / "other.view.lkml"
    other_file.write_text("view: other {}")

    with patch("lkr.tools.lookml.get_auth", return_value=mock_auth):
        result = runner.invoke(
            app,
            [
                "tools",
                "lookml",
                "push",
                str(project_dir),
                "--file",
                "views/target.view.lkml",
            ],
        )
        assert result.exit_code == 0

    # Verify update_file was called only for target.view.lkml
    expected_fc = FileContent(
        path="views/target.view.lkml", content="view: target {}"
    )
    mock_sdk.update_file.assert_called_once_with(
        project_id="test_project", file_content=expected_fc
    )
    # Verify no orphan cleanup inventory check occurred
    mock_sdk.all_project_files.assert_not_called()
    mock_sdk.delete_file.assert_not_called()


def test_push_file_as_argument(tmp_path, mock_sdk, mock_auth):
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()

    view_file = project_dir / "standalone.view.lkml"
    view_file.write_text("view: standalone {}")

    with patch("lkr.tools.lookml.get_auth", return_value=mock_auth):
        result = runner.invoke(
            app,
            ["tools", "lookml", "push", str(view_file), "--project", "test_project"],
        )
        assert result.exit_code == 0

    expected_fc = FileContent(
        path="standalone.view.lkml", content="view: standalone {}"
    )
    mock_sdk.update_file.assert_called_once_with(
        project_id="test_project", file_content=expected_fc
    )
    mock_sdk.all_project_files.assert_not_called()


def test_pull_single_file_option(tmp_path, mock_sdk, mock_auth):
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()

    local_orphan = project_dir / "orphan.view.lkml"
    local_orphan.write_text("orphan content")

    mock_sdk.get_file_content.return_value = "view: pulled_single {}"

    with patch("lkr.tools.lookml.get_auth", return_value=mock_auth):
        result = runner.invoke(
            app,
            [
                "tools",
                "lookml",
                "pull",
                str(project_dir),
                "-f",
                "views/single.view.lkml",
            ],
        )
        assert result.exit_code == 0

    pulled_file = project_dir / "views" / "single.view.lkml"
    assert pulled_file.exists()
    assert pulled_file.read_text() == "view: pulled_single {}"

    # Local orphan must NOT be deleted in single file pull mode
    assert local_orphan.exists()
    mock_sdk.all_project_files.assert_not_called()


def test_push_single_file_path_traversal(tmp_path, mock_sdk, mock_auth):
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()

    with patch("lkr.tools.lookml.get_auth", return_value=mock_auth), patch(
        "lkr.tools.lookml.logger.error"
    ) as mock_err:
        result = runner.invoke(
            app,
            [
                "tools",
                "lookml",
                "push",
                str(project_dir),
                "-f",
                "../outside.view.lkml",
            ],
        )
        assert result.exit_code == 1
        mock_err.assert_called_with("Path traversal detected and blocked: ../outside.view.lkml")


def test_pull_single_file_path_traversal(tmp_path, mock_sdk, mock_auth):
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()

    with patch("lkr.tools.lookml.get_auth", return_value=mock_auth), patch(
        "lkr.tools.lookml.logger.error"
    ) as mock_err:
        result = runner.invoke(
            app,
            [
                "tools",
                "lookml",
                "pull",
                str(project_dir),
                "-f",
                "../outside.view.lkml",
            ],
        )
        assert result.exit_code == 1
        mock_err.assert_called_with("Path traversal detected and blocked: ../outside.view.lkml")


def test_push_reset_and_new_model(tmp_path, mock_sdk, mock_auth):
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    model_file = project_dir / "my_new.model.lkml"
    model_file.write_text('connection: "new_conn"\ninclude: "*.view.lkml"')

    mock_sdk.all_project_files.return_value = []
    mock_sdk.all_lookml_models.return_value = []

    with patch("lkr.tools.lookml.get_auth", return_value=mock_auth):
        result = runner.invoke(
            app, ["tools", "lookml", "push", str(project_dir), "--deploy"]
        )
        assert result.exit_code == 0

    # reset_project_to_production called once before push
    mock_sdk.reset_project_to_production.assert_called_once_with(
        project_id="test_project"
    )
    mock_sdk.create_lookml_model.assert_called_once()
    created_body = mock_sdk.create_lookml_model.call_args.kwargs["body"]
    assert created_body.name == "my_new"
    assert created_body.project_name == "test_project"
    assert created_body.allowed_db_connection_names == ["new_conn"]


def test_push_no_reset(tmp_path, mock_sdk, mock_auth):
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    view_file = project_dir / "orders.view.lkml"
    view_file.write_text("view: orders {}")

    mock_sdk.all_project_files.return_value = []

    with patch("lkr.tools.lookml.get_auth", return_value=mock_auth):
        result = runner.invoke(
            app, ["tools", "lookml", "push", str(project_dir), "--no-reset", "--deploy"]
        )
        assert result.exit_code == 0

    mock_sdk.reset_project_to_production.assert_not_called()


def test_push_update_lookml_model_on_connection_change(tmp_path, mock_sdk, mock_auth):
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    model_file = project_dir / "existing.model.lkml"
    model_file.write_text('connection: "updated_conn"\ninclude: "*.view.lkml"')

    mock_sdk.all_project_files.return_value = []
    mock_sdk.all_lookml_models.return_value = [
        {
            "name": "existing",
            "project_name": "test_project",
            "allowed_db_connection_names": ["old_conn"],
        }
    ]

    with patch("lkr.tools.lookml.get_auth", return_value=mock_auth):
        result = runner.invoke(
            app, ["tools", "lookml", "push", str(project_dir), "--no-reset"]
        )
        assert result.exit_code == 0

    mock_sdk.update_lookml_model.assert_called_once()
    updated_kwargs = mock_sdk.update_lookml_model.call_args.kwargs
    assert updated_kwargs["lookml_model_name"] == "existing"
    assert "updated_conn" in updated_kwargs["body"].allowed_db_connection_names


def test_push_and_pull_include_snap_strings_json_and_skip_generic_json(tmp_path, mock_sdk, mock_auth):
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    (project_dir / "orders.view.lkml").write_text("view: orders {}")
    (project_dir / "en.strings.json").write_text('{"Orders": "Orders"}')
    (project_dir / "ignored.json").write_text("{}")
    snap_dir = project_dir / "__snapshots__"
    snap_dir.mkdir()
    snap_file = snap_dir / "manifest.snap.json.md"
    snap_file.write_text("{}")
    legacy_snap = snap_dir / "legacy.snap.json"
    legacy_snap.write_text("{}")

    mock_sdk.all_project_files.return_value = [{"id": "orders.view.lkml"}]
    mock_sdk.get_file_content.return_value = "view: orders {}"

    with patch("lkr.tools.lookml.get_auth", return_value=mock_auth):
        push_res = runner.invoke(
            app, ["tools", "lookml", "push", str(project_dir), "--no-reset"]
        )
        assert push_res.exit_code == 0
        pushed_paths = {
            call.kwargs["file_content"].path
            for call in mock_sdk.update_file.call_args_list
        }
        assert pushed_paths == {
            "orders.view.lkml",
            "en.strings.json",
            "__snapshots__/manifest.snap.json.md",
        }


def test_push_and_pull_skip_dot_directories_unless_sync_hidden(tmp_path, mock_sdk, mock_auth):
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    (project_dir / "main.view.lkml").write_text("view: main {}")
    agent_dir = project_dir / ".agents" / "skills"
    agent_dir.mkdir(parents=True)
    (agent_dir / "doc.md").write_text("# Doc")

    mock_sdk.all_project_files.return_value = [
        {"id": "main.view.lkml"},
        {"id": ".agents/skills/remote_doc.md"},
    ]
    mock_sdk.get_file_content.return_value = "content"

    with patch("lkr.tools.lookml.get_auth", return_value=mock_auth):
        # 1. Push without --sync-hidden ignores .agents
        mock_sdk.update_file.reset_mock()
        res_push_default = runner.invoke(
            app, ["tools", "lookml", "push", str(project_dir), "--no-reset"]
        )
        assert res_push_default.exit_code == 0
        pushed = {
            call.kwargs["file_content"].path
            for call in mock_sdk.update_file.call_args_list
        }
        assert ".agents/skills/doc.md" not in pushed
        assert "main.view.lkml" in pushed

        # 2. Push with --sync-hidden includes .agents
        mock_sdk.update_file.reset_mock()
        res_push_hidden = runner.invoke(
            app, ["tools", "lookml", "push", str(project_dir), "--no-reset", "--sync-hidden"]
        )
        assert res_push_hidden.exit_code == 0
        pushed_hidden = {
            call.kwargs["file_content"].path
            for call in mock_sdk.update_file.call_args_list
        }
        assert ".agents/skills/doc.md" in pushed_hidden

        # 3. Pull without --sync-hidden ignores remote dot-directories
        pull_dir = tmp_path / "pull_project"
        res_pull_default = runner.invoke(
            app, ["tools", "lookml", "pull", str(pull_dir)]
        )
        assert res_pull_default.exit_code == 0
        assert (pull_dir / "main.view.lkml").exists()
        assert not (pull_dir / ".agents" / "skills" / "remote_doc.md").exists()

        # 4. Pull with --sync-hidden pulls remote dot-directories
        res_pull_hidden = runner.invoke(
            app, ["tools", "lookml", "pull", str(pull_dir), "--sync-hidden"]
        )
        assert res_pull_hidden.exit_code == 0
        assert (pull_dir / ".agents" / "skills" / "remote_doc.md").exists()


def test_push_only_changed_and_skills_lock_ignored(tmp_path, mock_sdk, mock_auth):
    project_dir = tmp_path / "sync_project"
    project_dir.mkdir()
    (project_dir / "skills-lock.json").write_text('{"skills": {}}')

    remote_files = {
        "orders.view.lkml": "view: orders {}",
        "users.view.lkml": "view: users {}",
        "skills-lock.json": '{"skills": {}}',
    }
    mock_sdk.all_project_files.side_effect = lambda **_kw: [
        {"id": k} for k in remote_files
    ]
    mock_sdk.get_file_content.side_effect = lambda file_path, **_kw: remote_files[
        file_path
    ]

    with (
        patch("lkr.tools.lookml.get_auth", return_value=mock_auth),
        patch("lkr.tools.lookml.logger.warning") as mock_warn,
    ):
        pull_res = runner.invoke(app, ["tools", "lookml", "pull", str(project_dir)])
        assert pull_res.exit_code == 0

        # Modify one file, add one new file, leave users.view.lkml untouched
        (project_dir / "orders.view.lkml").write_text("view: orders { dimension: id {} }")
        (project_dir / "new.explore.lkml").write_text("explore: orders {}")

        mock_sdk.update_file.reset_mock()
        mock_sdk.delete_file.reset_mock()

        push_res = runner.invoke(
            app,
            ["tools", "lookml", "push", str(project_dir), "--no-reset", "--only-changed"],
        )
        assert push_res.exit_code == 0

        pushed_paths = {
            call.kwargs["file_content"].path
            for call in mock_sdk.update_file.call_args_list
        }
        assert pushed_paths == {"orders.view.lkml", "new.explore.lkml"}
        mock_sdk.delete_file.assert_not_called()
        for call in mock_warn.call_args_list:
            assert "skills-lock.json" not in str(call)

