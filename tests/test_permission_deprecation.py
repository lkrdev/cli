import pytest
from unittest.mock import MagicMock, patch
from lkr.tools.permission_deprecation import schedule_download_deprecation

@pytest.fixture
def mock_sdk():
    sdk = MagicMock()
    
    # Mock models
    model_thelook = MagicMock()
    model_thelook.name = "thelook"
    model_finance = MagicMock()
    model_finance.name = "finance"
    sdk.all_lookml_models.return_value = [model_thelook, model_finance]
    
    # User 1: has download_with_limit + access_data on thelook, but ONLY access_data on finance
    # Role 1: target + data on thelook
    role1 = MagicMock()
    role1.id = "1"
    role1.permission_set.permissions = ["download_with_limit", "access_data"]
    role1.model_set.models = ["thelook"]
    
    # Role 2: access_data on finance
    role2 = MagicMock()
    role2.id = "2"
    role2.permission_set.permissions = ["access_data"]
    role2.model_set.models = ["finance"]

    # User 2: has access_data on thelook, no access_data on finance, has download_with_limit globally or on some other model
    # Role 3: download_with_limit on some other model (or we can just use Role 1 but not assign Role 1 to User 2)
    # Role 4: access_data on thelook
    role4 = MagicMock()
    role4.id = "4"
    role4.permission_set.permissions = ["access_data"]
    role4.model_set.models = ["thelook"]
    
    # Role 5: download_with_limit on a model User 2 doesn't have access_data for (e.g. they just have the perm)
    role5 = MagicMock()
    role5.id = "5"
    role5.permission_set.permissions = ["download_with_limit"]
    role5.model_set.models = ["finance"] # they have the target but NO access_data on finance

    sdk.all_roles.return_value = [role1, role2, role4, role5]
    
    return sdk

@patch("lkr.tools.permission_deprecation.get_auth")
def test_user_scenario_with_access_data(mock_get_auth, mock_sdk):
    mock_get_auth.return_value.get_current_sdk.return_value = mock_sdk
    
    # User 1: Role 1 (Target+Data on thelook), Role 2 (Data on finance)
    user1 = MagicMock()
    user1.id = 1
    user1.first_name = "User"
    user1.last_name = "One"
    user1.role_ids = ["1", "2"]
    user1.external_id = None
    
    # User 2: Role 4 (Data on thelook), Role 5 (Target on finance)
    user2 = MagicMock()
    user2.id = 2
    user2.first_name = "User"
    user2.last_name = "Two"
    user2.role_ids = ["4", "5"]
    user2.external_id = None

    def search_side_effect(*args, **kwargs):
        offset = kwargs.get('offset', 0)
        if offset == 0:
            return [user1, user2]
        return []
    mock_sdk.search_users.side_effect = search_side_effect
    
    ctx = MagicMock()
    result = schedule_download_deprecation(ctx, limit=500)
    
    assert result is not None
    
    # User 1 check
    u1 = next(r for r in result.rows if r.user_id == "1")
    assert "download_with_limit" in u1.instance_wide
    # thelook: Role 1 gives both -> ✅
    assert u1.model_permissions["thelook"] == []
    # finance: Role 2 gives access_data, No role gives download_with_limit on finance -> MISSING
    assert "download_with_limit" in u1.model_permissions["finance"]

    # User 2 check
    u2 = next(r for r in result.rows if r.user_id == "2")
    assert "download_with_limit" in u2.instance_wide
    # thelook: Role 4 gives access_data, No role gives target on thelook -> MISSING
    assert "download_with_limit" in u2.model_permissions["thelook"]
    # finance: Role 5 gives target, but NO ONE gives access_data -> N/A
    assert u2.model_permissions["finance"] is None

@patch("lkr.tools.permission_deprecation.get_auth")
def test_schedule_download_deprecation_admin(mock_get_auth, mock_sdk):
    admin_role = MagicMock()
    admin_role.id = "admin_id"
    admin_role.permission_set.name = "Admin"
    admin_role.model_set.models = ["*"]
    
    user = MagicMock()
    user.id = 3
    user.role_ids = ["admin_id"]
    user.external_id = None
    
    mock_sdk.all_roles.return_value = [admin_role]
    
    def search_side_effect(*args, **kwargs):
        offset = kwargs.get('offset', 0)
        if offset == 0:
            return [user]
        return []
    mock_sdk.search_users.side_effect = search_side_effect
    
    mock_get_auth.return_value.get_current_sdk.return_value = mock_sdk
    
    ctx = MagicMock()
    # Default behavior: Admin is filtered out because they have no missing permissions
    result = schedule_download_deprecation(ctx, limit=500)
    assert len(result.rows) == 0

    # With unfiltered=True: Admin should be present
    result_unfiltered = schedule_download_deprecation(ctx, limit=500, unfiltered=True)
    assert len(result_unfiltered.rows) == 1
    for model in result_unfiltered.model_names:
        assert result_unfiltered.rows[0].model_permissions[model] == []

@patch("lkr.tools.permission_deprecation.get_auth")
def test_schedule_download_deprecation_filtering_logic(mock_get_auth, mock_sdk):
    mock_get_auth.return_value.get_current_sdk.return_value = mock_sdk
    
    # User A: Has missing permissions (Should always show)
    # Role 4 gives access_data on 'thelook'
    # Role 5 gives 'download_with_limit' on 'finance' (but not on 'thelook')
    # Result: User A will show 'download_with_limit' MISSING on 'thelook'
    user_a = MagicMock()
    user_a.id = "A"
    user_a.role_ids = ["4", "5"] 
    user_a.external_id = None
    
    # User B: Has all permissions (Should be filtered)
    user_b = MagicMock()
    user_b.id = "B"
    user_b.role_ids = ["1"] # role 1 has target + access_data on thelook
    user_b.external_id = None
    
    # User C: No access data (Should be filtered)
    user_c = MagicMock()
    user_c.id = "C"
    user_c.role_ids = [] # No roles -> All N/A
    user_c.external_id = None

    def search_side_effect(*args, **kwargs):
        offset = kwargs.get('offset', 0)
        if offset == 0:
            return [user_a, user_b, user_c]
        return []
    mock_sdk.search_users.side_effect = search_side_effect
    
    ctx = MagicMock()
    
    # Test Default (Filtered)
    result = schedule_download_deprecation(ctx, limit=500, unfiltered=False)
    # Only User A should remain
    assert len(result.rows) == 1
    assert result.rows[0].user_id == "A"
    
    # Test Unfiltered
    result_unfiltered = schedule_download_deprecation(ctx, limit=500, unfiltered=True)
    # All 3 users should remain
    assert len(result_unfiltered.rows) == 3
    ids = [r.user_id for r in result_unfiltered.rows]
    assert "A" in ids
    assert "B" in ids
    assert "C" in ids
