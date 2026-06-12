from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from lkr.main import app
from lkr.extended_sdk_methods import ExtendedLooker40SDK, FileContent

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


