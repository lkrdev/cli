import pytest
from unittest.mock import MagicMock, patch
import typer
import json

from lkr.db_template.main import no_results
from lkr.db_template.manifest_service import ManifestService, DbTemplateManifest
from lkr.db_template.lookup_service import LookupService


@pytest.fixture
def mock_sdk():
    sdk = MagicMock()
    
    # Mock dashboard
    mock_dashboard = MagicMock()
    mock_dashboard.id = "123"
    mock_dashboard.title = "Test Template Dashboard"
    sdk.dashboard.return_value = mock_dashboard
    
    return sdk


# ==========================================
# CLI VALIDATION & EXECUTION TESTS
# ==========================================

@patch("lkr.db_template.main.get_auth")
def test_no_results_validation_exactly_one_opt(mock_get_auth, mock_sdk):
    """Verify that providing exactly one of the required options succeeds."""
    mock_get_auth.return_value.get_current_sdk.return_value = mock_sdk
    
    ctx = MagicMock()
    
    # 1. Check --looker-user-id
    no_results(
        ctx=ctx,
        template_dashboard_id="123",
        looker_user_id="user_123",
        email=None,
        external_group_id=None,
        external_user_id=None,
        dry_run=False,
        folder_path=None,
    )
    mock_sdk.dashboard.assert_called_with(dashboard_id="123")
    
    # 2. Check --email
    mock_sdk.dashboard.reset_mock()
    no_results(
        ctx=ctx,
        template_dashboard_id="123",
        looker_user_id=None,
        email="test@looker.com",
        external_group_id=None,
        external_user_id=None,
        dry_run=False,
        folder_path=None,
    )
    mock_sdk.dashboard.assert_called_with(dashboard_id="123")


def test_no_results_validation_none_provided():
    """Verify that providing none of the required options raises BadParameter."""
    ctx = MagicMock()
    ctx.args = []
    with pytest.raises(typer.BadParameter) as exc_info:
        no_results(
            ctx=ctx,
            template_dashboard_id="123",
            looker_user_id=None,
            email=None,
            external_group_id=None,
            external_user_id=None,
            dry_run=False,
            folder_path=None,
        )
    assert "At least one of --looker-user-id, --email, --external-group-id, or --external-user-id must be specified" in str(exc_info.value)


def test_no_results_validation_multiple_provided():
    """Verify that providing multiple of the required options raises BadParameter."""
    ctx = MagicMock()
    ctx.args = []
    with pytest.raises(typer.BadParameter) as exc_info:
        no_results(
            ctx=ctx,
            template_dashboard_id="123",
            looker_user_id="user_123",
            email="test@looker.com",
            external_group_id=None,
            external_user_id=None,
            dry_run=False,
            folder_path=None,
        )
    assert "Option --looker-user-id is mutually exclusive with all other options" in str(exc_info.value)


@patch("lkr.db_template.main.get_auth")
def test_no_results_dry_run(mock_get_auth, mock_sdk):
    """Verify that dry_run skips SDK dashboard lookup."""
    mock_get_auth.return_value.get_current_sdk.return_value = mock_sdk
    
    ctx = MagicMock()
    no_results(
        ctx=ctx,
        template_dashboard_id="123",
        looker_user_id="user_123",
        email=None,
        external_group_id=None,
        external_user_id=None,
        dry_run=True,
        folder_path=None,
    )
    mock_sdk.dashboard.assert_not_called()


@patch("lkr.db_template.main.get_auth")
def test_no_results_sdk_error(mock_get_auth, mock_sdk):
    """Verify that SDK lookup failure raises typer.Exit(1)."""
    mock_sdk.dashboard.side_effect = Exception("API Error")
    mock_get_auth.return_value.get_current_sdk.return_value = mock_sdk
    
    ctx = MagicMock()
    with pytest.raises(typer.Exit) as exc_info:
        no_results(
            ctx=ctx,
            template_dashboard_id="123",
            looker_user_id="user_123",
            email=None,
            external_group_id=None,
            external_user_id=None,
            dry_run=False,
            folder_path=None,
        )
    assert exc_info.value.exit_code == 1


# ==========================================
# MANIFEST SERVICE TESTS
# ==========================================

def test_manifest_model_alias():
    """Verify that DbTemplateManifest serializes and deserializes using its aliases."""
    json_data = {
        "template-dashboard-id": "tpl_123",
        "folder-path": "/shared",
        "user-flag": "email",
        "user-flag-value": "test@looker.com",
        "new-dashboard-id": "new_456",
        "created-at": "2026-06-02T18:00:00Z",
        "updated-at": "2026-06-02T18:05:00Z",
        "removed-eleemnts-from-template-dashboard id": ["element_1", "element_2"],
        "dashboard-query-string": "?Date=7 days"
    }
    
    manifest = DbTemplateManifest.model_validate(json_data)
    assert manifest.template_dashboard_id == "tpl_123"
    assert manifest.folder_path == "/shared"
    assert manifest.user_flag == "email"
    assert manifest.user_flag_value == "test@looker.com"
    assert manifest.new_dashboard_id == "new_456"
    assert manifest.removed_elements_from_template_dashboard_id == ["element_1", "element_2"]
    assert manifest.dashboard_query_string == "?Date=7 days"
    
    serialized = manifest.model_dump(by_alias=True, mode="json")
    assert serialized["template-dashboard-id"] == "tpl_123"
    assert serialized["removed-eleemnts-from-template-dashboard id"] == ["element_1", "element_2"]
    assert serialized["dashboard-query-string"] == "?Date=7 days"


def test_manifest_service_get_none():
    """Verify ManifestService.get_manifest returns None when no artifact is found."""
    sdk = MagicMock()
    sdk.artifact.return_value = []
    
    service = ManifestService(sdk)
    manifest = service.get_manifest("email", "test@looker.com", "tpl_123")
    assert manifest is None
    sdk.artifact.assert_called_once()


def test_manifest_service_get_success():
    """Verify ManifestService.get_manifest successfully parses artifact value."""
    sdk = MagicMock()
    mock_artifact = MagicMock()
    mock_artifact.value = (
        '{"template-dashboard-id": "tpl_123", "user-flag": "email", '
        '"user-flag-value": "test@looker.com", "new-dashboard-id": "new_456", '
        '"removed-eleemnts-from-template-dashboard id": ["element_1"], "dashboard-query-string": "?Date=7 days"}'
    )
    sdk.artifact.return_value = [mock_artifact]
    
    service = ManifestService(sdk)
    manifest = service.get_manifest("email", "test@looker.com", "tpl_123")
    
    assert manifest is not None
    assert manifest.template_dashboard_id == "tpl_123"
    assert manifest.user_flag == "email"
    assert manifest.user_flag_value == "test@looker.com"
    assert manifest.new_dashboard_id == "new_456"
    assert manifest.removed_elements_from_template_dashboard_id == ["element_1"]
    assert manifest.dashboard_query_string == "?Date=7 days"


def test_manifest_service_save():
    """Verify ManifestService.save_manifest calls update_artifacts with correct payload."""
    sdk = MagicMock()
    service = ManifestService(sdk)
    
    manifest = DbTemplateManifest(
        template_dashboard_id="tpl_123",
        folder_path="/shared",
        user_flag="email",
        user_flag_value="test@looker.com",
        dashboard_query_string="?Date=7 days"
    )
    
    service.save_manifest(manifest)
    
    sdk.update_artifacts.assert_called_once()
    call_args = sdk.update_artifacts.call_args
    assert call_args is not None
    
    # Verify namespace
    assert call_args.kwargs["namespace"] == "lkr-dev-db-template"
    
    # Verify body artifact content
    body_list = call_args.kwargs["body"]
    assert len(body_list) == 1
    artifact = body_list[0]
    assert artifact.key == "no-results-email-test@looker.com-tpl_123"
    
    payload = json.loads(artifact.value)
    assert payload["template-dashboard-id"] == "tpl_123"
    assert payload["folder-path"] == "/shared"
    assert payload["user-flag"] == "email"
    assert payload["user-flag-value"] == "test@looker.com"
    assert payload["dashboard-query-string"] == "?Date=7 days"


# ==========================================
# CLI DELETION TESTS
# ==========================================

@patch("lkr.db_template.main.get_auth")
def test_delete_no_manifest(mock_get_auth, mock_sdk):
    """Verify that --delete does nothing if no manifest exists."""
    mock_sdk.artifact.return_value = []
    mock_get_auth.return_value.get_current_sdk.return_value = mock_sdk
    
    ctx = MagicMock()
    no_results(
        ctx=ctx,
        template_dashboard_id="123",
        looker_user_id=None,
        email="test@looker.com",
        external_group_id=None,
        external_user_id=None,
        dry_run=False,
        folder_path=None,
        delete=True,
    )
    mock_sdk.delete_dashboard.assert_not_called()
    mock_sdk.delete_artifact.assert_not_called()


@patch("lkr.db_template.main.get_auth")
def test_delete_with_manifest_no_dash_id(mock_get_auth, mock_sdk):
    """Verify that --delete deletes only manifest when no dashboard ID is present in the manifest."""
    mock_artifact = MagicMock()
    mock_artifact.value = (
        '{"template-dashboard-id": "123", "user-flag": "email", '
        '"user-flag-value": "test@looker.com", "new-dashboard-id": null}'
    )
    mock_sdk.artifact.return_value = [mock_artifact]
    mock_get_auth.return_value.get_current_sdk.return_value = mock_sdk
    
    ctx = MagicMock()
    no_results(
        ctx=ctx,
        template_dashboard_id="123",
        looker_user_id=None,
        email="test@looker.com",
        external_group_id=None,
        external_user_id=None,
        dry_run=False,
        folder_path=None,
        delete=True,
    )
    mock_sdk.delete_dashboard.assert_not_called()
    mock_sdk.delete_artifact.assert_called_once_with(
        namespace="lkr-dev-db-template",
        key="no-results-email-test@looker.com-123"
    )


@patch("lkr.db_template.main.get_auth")
def test_delete_with_manifest_and_dash_id(mock_get_auth, mock_sdk):
    """Verify that --delete deletes both dashboard and manifest when dashboard ID is present."""
    mock_artifact = MagicMock()
    mock_artifact.value = (
        '{"template-dashboard-id": "123", "user-flag": "email", '
        '"user-flag-value": "test@looker.com", "new-dashboard-id": "new_dash_789"}'
    )
    mock_sdk.artifact.return_value = [mock_artifact]
    mock_get_auth.return_value.get_current_sdk.return_value = mock_sdk
    
    ctx = MagicMock()
    no_results(
        ctx=ctx,
        template_dashboard_id="123",
        looker_user_id=None,
        email="test@looker.com",
        external_group_id=None,
        external_user_id=None,
        dry_run=False,
        folder_path=None,
        delete=True,
    )
    mock_sdk.delete_dashboard.assert_called_once_with(dashboard_id="new_dash_789")
    mock_sdk.delete_artifact.assert_called_once_with(
        namespace="lkr-dev-db-template",
        key="no-results-email-test@looker.com-123"
    )


@patch("lkr.db_template.main.get_auth")
def test_delete_dry_run(mock_get_auth, mock_sdk):
    """Verify that --delete in --dry-run skips deletion."""
    mock_get_auth.return_value.get_current_sdk.return_value = mock_sdk
    
    ctx = MagicMock()
    no_results(
        ctx=ctx,
        template_dashboard_id="123",
        looker_user_id=None,
        email="test@looker.com",
        external_group_id=None,
        external_user_id=None,
        dry_run=True,
        folder_path=None,
        delete=True,
    )
    mock_sdk.artifact.assert_not_called()
    mock_sdk.delete_dashboard.assert_not_called()
    mock_sdk.delete_artifact.assert_not_called()


# ==========================================
# LOOKUP SERVICE TESTS
# ==========================================

def test_lookup_service_get_user_id():
    """Verify LookupService.get_user_id resolves various user identification flags correctly."""
    sdk = MagicMock()
    
    # 1. looker-user-id
    service = LookupService(sdk, "looker-user-id", "user_abc")
    assert service.get_user_id() == "user_abc"
    
    # 2. email search_users success
    sdk.search_users.return_value = [MagicMock(id="user_456")]
    service = LookupService(sdk, "email", "test@looker.com")
    assert service.get_user_id() == "user_456"
    sdk.search_users.assert_called_once_with(email="test@looker.com", fields="id")
    
    # 3. email search fallback to user_for_credential
    sdk.search_users.reset_mock()
    sdk.search_users.return_value = []
    sdk.user_for_credential.return_value = MagicMock(id="user_789")
    assert service.get_user_id() == "user_789"
    sdk.user_for_credential.assert_called_once_with(credential_type="email", credential_id="test@looker.com", fields="id")
    
    # 4. external-user-id search
    sdk.user_for_credential.reset_mock()
    sdk.user_for_credential.return_value = MagicMock(id="user_embed_123")
    service = LookupService(sdk, "external-user-id", "ext_123")
    assert service.get_user_id() == "user_embed_123"
    sdk.user_for_credential.assert_called_once_with(credential_type="embed", credential_id="ext_123", fields="id")


def test_lookup_service_lookup_space():
    """Verify LookupService._lookup_space retrieves user personal or home folder correctly."""
    sdk = MagicMock()
    mock_user = MagicMock()
    mock_user.personal_folder_id = "folder_personal_123"
    mock_user.home_folder_id = "folder_home_456"
    sdk.user.return_value = mock_user
    
    service = LookupService(sdk, "looker-user-id", "user_abc")
    assert service._lookup_space() == "folder_personal_123"
    sdk.user.assert_called_once_with(user_id="user_abc", fields="personal_folder_id,home_folder_id,embed_group_folder_id")


def test_lookup_service_folder_path_traversal():
    """Verify folder path resolution walks segments, finds existing folders, and creates missing ones."""
    sdk = MagicMock()
    
    mock_user = MagicMock()
    mock_user.personal_folder_id = "10"
    sdk.user.return_value = mock_user
    
    def search_folders_side_effect(parent_id, name, fields=None):
        if parent_id == "10" and name == "nested":
            return [MagicMock(id="11")]
        if parent_id == "11" and name == "sub":
            return []
        return []
    sdk.search_folders.side_effect = search_folders_side_effect
    
    mock_new_folder = MagicMock()
    mock_new_folder.id = "12"
    sdk.create_folder.return_value = mock_new_folder
    
    service = LookupService(sdk, "looker-user-id", "user_abc", folder_path="nested/sub")
    folder_id = service.get_folder_path_folder_id(create_if_missing=True)
    
    assert folder_id == "12"
    sdk.create_folder.assert_called_once()
    call_args = sdk.create_folder.call_args
    assert call_args.kwargs["body"].name == "sub"
    assert call_args.kwargs["body"].parent_id == "11"


def test_lookup_service_save_new_template():
    """Verify save_new_template copies the dashboard and updates its ownership."""
    sdk = MagicMock()
    
    mock_user = MagicMock()
    mock_user.personal_folder_id = "10"
    sdk.user.return_value = mock_user
    
    mock_new_dash = MagicMock()
    mock_new_dash.id = "dash_new_xyz"
    sdk.copy_dashboard.return_value = mock_new_dash
    
    service = LookupService(sdk, "looker-user-id", "user_abc", folder_path=None)
    new_dash_id = service.save_new_template(template_dashboard_id="dash_template_123")
    
    assert new_dash_id == "dash_new_xyz"
    sdk.copy_dashboard.assert_called_once_with(dashboard_id="dash_template_123", folder_id="10")
    sdk.update_dashboard.assert_called_once_with(dashboard_id="dash_new_xyz", body={"user_id": "user_abc"})


def test_lookup_service_validate_folder_path():
    """Verify validate_folder_path moves dashboard when the folder path changes."""
    sdk = MagicMock()
    
    mock_user = MagicMock()
    mock_user.personal_folder_id = "10"
    sdk.user.return_value = mock_user
    sdk.search_folders.return_value = [MagicMock(id="20")]
    
    service = LookupService(sdk, "looker-user-id", "user_abc", folder_path="new_folder")
    new_folder_id = service.validate_folder_path(dashboard_id="dash_123", current_folder_path="old_folder")
    
    assert new_folder_id == "20"
    sdk.update_dashboard.assert_called_once()
    call_args = sdk.update_dashboard.call_args
    assert call_args.kwargs["body"].folder_id == "20"
    
    sdk.update_dashboard.reset_mock()
    new_folder_id_same = service.validate_folder_path(dashboard_id="dash_123", current_folder_path="new_folder")
    assert new_folder_id_same is None
    sdk.update_dashboard.assert_not_called()


# ==========================================
# RUN TEMPLATED DASHBOARD & QUERY FILTERING TESTS
# ==========================================

def test_lookup_service_get_sudo_user_id_external_group():
    """Verify LookupService.get_sudo_user_id resolves correctly under external-group-id."""
    sdk = MagicMock()
    
    # Mock group search
    mock_group = MagicMock()
    mock_group.id = "group_100"
    sdk.search_groups.return_value = [mock_group]
    
    # Mock group users search
    mock_user = MagicMock()
    mock_user.id = "user_200"
    sdk.all_group_users.return_value = [mock_user]
    
    service = LookupService(sdk, "external-group-id", "ext_grp_name")
    sudo_id = service.get_sudo_user_id()
    
    assert sudo_id == "user_200"
    sdk.search_groups.assert_called_once_with(external_group_id="ext_grp_name", fields="id")
    sdk.all_group_users.assert_called_once_with(group_id="group_100", fields="id")


def test_lookup_service_run_templated_dashboard():
    """Verify run_templated_dashboard successfully applies filters to queries and executes them under sudo user."""
    sdk = MagicMock()
    
    # Create a mock element with query & filterables
    mock_element = MagicMock()
    mock_element.title = "Tile 1"
    mock_element.result_maker.query.id = "q1"
    mock_element.result_maker.query.model = "thelook"
    mock_element.result_maker.query.view = "orders"
    mock_element.result_maker.query.fields = ["orders.count"]
    mock_element.result_maker.query.filters = {"orders.created_date": "7 days"}
    mock_element.result_maker.query.vis_config = None
    
    # Mock listen filters map
    mock_listen = MagicMock()
    mock_listen.dashboard_filter_name = "State"
    mock_listen.field = "users.state"
    
    mock_filterable = MagicMock()
    mock_filterable.listen = [mock_listen]
    mock_element.result_maker.filterables = [mock_filterable]
    
    # Mock dashboard elements
    mock_dashboard = MagicMock()
    mock_dashboard.dashboard_elements = [mock_element]
    sdk.dashboard.return_value = mock_dashboard
    
    # Mock create_query and run_query
    mock_new_query = MagicMock()
    mock_new_query.id = "q_new_999"
    sdk.create_query.return_value = mock_new_query
    sdk.run_query.return_value = '[]' # returns empty rows
    
    service = LookupService(sdk, "looker-user-id", "12")
    service.run_templated_dashboard(
        template_dashboard_id="tpl_dash",
        dashboard_filters={"State": "California"},
        sudo_user_id="12"
    )
    
    # Verify impersonation was started and stopped
    sdk.auth.login_user.assert_called_once_with(sudo_id=12)
    sdk.auth.logout.assert_called_once()
    
    # Verify query modification
    sdk.create_query.assert_called_once()
    call_body = sdk.create_query.call_args.kwargs["body"]
    assert call_body["model"] == "thelook"
    assert call_body["view"] == "orders"
    # Check that California filter was applied!
    assert call_body["filters"]["users.state"] == "California"
    assert call_body["filters"]["orders.created_date"] == "7 days"
    
    # Verify run_query was triggered
    sdk.run_query.assert_called_once_with(query_id="q_new_999", result_format="json")


def test_lookup_service_get_sudo_user_id_external_group_and_user_success():
    """Verify LookupService.get_sudo_user_id resolves correctly when both group and user are provided and user is a member."""
    sdk = MagicMock()
    
    # Mock group search
    mock_group = MagicMock()
    mock_group.id = "group_100"
    sdk.search_groups.return_value = [mock_group]
    
    # Mock group users
    mock_user1 = MagicMock(id="user_200")
    mock_user2 = MagicMock(id="user_300")
    sdk.all_group_users.return_value = [mock_user1, mock_user2]
    
    # Mock user_for_credential lookup
    mock_target = MagicMock(id="user_300")
    sdk.user_for_credential.return_value = mock_target
    
    service = LookupService(sdk, "external-group-id", "ext_grp_name", external_user_id="ext_user_xyz")
    sudo_id = service.get_sudo_user_id()
    
    assert sudo_id == "user_300"
    sdk.user_for_credential.assert_called_once_with(credential_type="embed", credential_id="ext_user_xyz", fields="id")


def test_lookup_service_get_sudo_user_id_external_group_and_user_not_member():
    """Verify LookupService.get_sudo_user_id raises ValueError if target user is not a member of the group."""
    sdk = MagicMock()
    
    # Mock group search
    mock_group = MagicMock()
    mock_group.id = "group_100"
    sdk.search_groups.return_value = [mock_group]
    
    # Mock group users
    mock_user1 = MagicMock(id="user_200")
    sdk.all_group_users.return_value = [mock_user1]
    
    # Mock target user (not a member of the group!)
    mock_target = MagicMock(id="user_999")
    sdk.user_for_credential.return_value = mock_target
    
    service = LookupService(sdk, "external-group-id", "ext_grp_name", external_user_id="ext_user_nonmember")
    
    with pytest.raises(ValueError) as exc_info:
        service.get_sudo_user_id()
    
    assert "does not belong to the external group" in str(exc_info.value)


@patch("lkr.db_template.main.get_auth")
def test_no_results_validation_combined_group_and_user(mock_get_auth, mock_sdk):
    """Verify that providing both --external-group-id and --external-user-id is valid."""
    mock_get_auth.return_value.get_current_sdk.return_value = mock_sdk
    
    ctx = MagicMock()
    ctx.args = []
    
    # Mock external group resolving and impersonation
    mock_group = MagicMock()
    mock_group.id = "group_100"
    mock_sdk.search_groups.return_value = [mock_group]
    
    mock_folder = MagicMock()
    mock_folder.id = "200"
    mock_sdk.search_folders.return_value = [mock_folder]
    
    mock_user1 = MagicMock(id=200)
    mock_user2 = MagicMock(id=300)
    mock_sdk.all_group_users.return_value = [mock_user1, mock_user2]
    
    mock_target = MagicMock(id=300)
    mock_sdk.user_for_credential.return_value = mock_target
    
    no_results(
        ctx=ctx,
        template_dashboard_id="123",
        looker_user_id=None,
        email=None,
        external_group_id="ext_grp_123",
        external_user_id="ext_user_456",
        dry_run=False,
        folder_path=None,
    )
    mock_sdk.dashboard.assert_any_call(dashboard_id="123")


@patch("lkr.db_template.main.get_auth")
def test_no_results_extra_cli_arguments_overwrites(mock_get_auth, mock_sdk):
    """Verify that extra arguments passed on command line overwrite query string filters."""
    mock_get_auth.return_value.get_current_sdk.return_value = mock_sdk
    
    ctx = MagicMock()
    # Simulate passing --Date "30 days" --State "California" in ctx.args
    ctx.args = ["--Date", "30 days", "--State", "California"]
    
    # Mock dashboard element with query and listens
    mock_element = MagicMock()
    mock_element.title = "Tile 1"
    mock_element.result_maker.query.id = "q1"
    mock_element.result_maker.query.model = "thelook"
    mock_element.result_maker.query.view = "orders"
    mock_element.result_maker.query.fields = ["orders.count"]
    mock_element.result_maker.query.filters = {"orders.created_date": "7 days"}
    mock_element.result_maker.query.vis_config = None
    
    mock_listen1 = MagicMock()
    mock_listen1.dashboard_filter_name = "Date"
    mock_listen1.field = "orders.created_date"
    
    mock_listen2 = MagicMock()
    mock_listen2.dashboard_filter_name = "State"
    mock_listen2.field = "users.state"
    
    mock_filterable = MagicMock()
    mock_filterable.listen = [mock_listen1, mock_listen2]
    mock_element.result_maker.filterables = [mock_filterable]
    
    mock_dashboard = MagicMock()
    mock_dashboard.dashboard_elements = [mock_element]
    mock_sdk.dashboard.return_value = mock_dashboard
    
    # Mock create_query and run_query
    mock_new_query = MagicMock()
    mock_new_query.id = "q_new_999"
    mock_sdk.create_query.return_value = mock_new_query
    mock_sdk.run_query.return_value = '[]'
    
    # Run CLI with query string "Date=7 days" but CLI extra args will overwrite it with "30 days"!
    no_results(
        ctx=ctx,
        template_dashboard_id="123",
        looker_user_id="123",
        email=None,
        external_group_id=None,
        external_user_id=None,
        dry_run=False,
        folder_path=None,
        dashboard_query_string="?Date=7 days"
    )
    
    mock_sdk.create_query.assert_called_once()
    call_body = mock_sdk.create_query.call_args.kwargs["body"]
    assert call_body["filters"]["orders.created_date"] == "30 days"
    assert call_body["filters"]["users.state"] == "California"
