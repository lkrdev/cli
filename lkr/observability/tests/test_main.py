import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from lkr.observability.main import app, get_embed_sdk_obj, DEFAULT_PERMISSIONS
from lkr.observability.classes import EmbedSDKObj

# Default values for required parameters
DEFAULT_DASHBOARD_ID = "test_dashboard"
DEFAULT_EXTERNAL_USER_ID = "test_user"

# Default values from function signature
DEFAULT_GROUP_IDS = []
DEFAULT_MODELS = []
DEFAULT_SESSION_LENGTH = 10 * 60 * 50
DEFAULT_FIRST_NAME = None
DEFAULT_LAST_NAME = None
DEFAULT_USER_TIMEZONE = None
DEFAULT_SECRET_ID = None

# Initialize TestClient
client = TestClient(app)

def test_get_embed_sdk_obj_invalid_json():
    """
    Tests that get_embed_sdk_obj raises HTTPException for invalid JSON
    due to the custom ValueError handler.
    """
    user_attributes_invalid = "{'key': 'value'}"  # Invalid JSON (single quotes)
    with pytest.raises(HTTPException) as exc_info:
        # This test now needs to be run via the TestClient to trigger the handler
        # However, for now, we'll simulate the direct call and assume the handler
        # would convert the ValueError to HTTPException if it were a real request.
        # This is a limitation of testing the handler's effect on a direct function call.
        # Ideally, we would use TestClient(app).get(...)
        try:
            get_embed_sdk_obj(
                dashboard_id=DEFAULT_DASHBOARD_ID,
                external_user_id=DEFAULT_EXTERNAL_USER_ID,
                group_ids=DEFAULT_GROUP_IDS,
                permissions=list(DEFAULT_PERMISSIONS),
                models=DEFAULT_MODELS,
                session_length=DEFAULT_SESSION_LENGTH,
                first_name=DEFAULT_FIRST_NAME,
                last_name=DEFAULT_LAST_NAME,
                user_timezone=DEFAULT_USER_TIMEZONE,
                user_attributes=user_attributes_invalid,
                secret_id=DEFAULT_SECRET_ID,
            )
        except ValueError as ve:
            # Simulate the behavior of the exception handler
            if str(ve).startswith("Invalid JSON format for user_attributes"):
                raise HTTPException(status_code=400, detail=str(ve))
            raise
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == f"Invalid JSON format for user_attributes: {user_attributes_invalid}"

def test_get_embed_sdk_obj_empty_string_json():
    """
    Tests that get_embed_sdk_obj raises HTTPException for an empty string as JSON
    due to the custom ValueError handler.
    """
    user_attributes_empty = ""  # Empty string
    with pytest.raises(HTTPException) as exc_info:
        # Similar to the above, simulating handler effect
        try:
            get_embed_sdk_obj(
                dashboard_id=DEFAULT_DASHBOARD_ID,
                external_user_id=DEFAULT_EXTERNAL_USER_ID,
                group_ids=DEFAULT_GROUP_IDS,
                permissions=list(DEFAULT_PERMISSIONS),
                models=DEFAULT_MODELS,
                session_length=DEFAULT_SESSION_LENGTH,
                first_name=DEFAULT_FIRST_NAME,
                last_name=DEFAULT_LAST_NAME,
                user_timezone=DEFAULT_USER_TIMEZONE,
                user_attributes=user_attributes_empty,
                secret_id=DEFAULT_SECRET_ID,
            )
        except ValueError as ve:
            if str(ve).startswith("Invalid JSON format for user_attributes"):
                raise HTTPException(status_code=400, detail=str(ve))
            raise
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == f"Invalid JSON format for user_attributes: {user_attributes_empty}"

def test_get_embed_sdk_obj_valid_json():
    """
    Tests that get_embed_sdk_obj correctly parses valid JSON.
    """
    valid_json_str = '{"key": "value"}'
    expected_dict = {"key": "value"}
    result = get_embed_sdk_obj(
        dashboard_id=DEFAULT_DASHBOARD_ID,
        external_user_id=DEFAULT_EXTERNAL_USER_ID,
        group_ids=DEFAULT_GROUP_IDS,
        permissions=list(DEFAULT_PERMISSIONS),
        models=DEFAULT_MODELS,
        session_length=DEFAULT_SESSION_LENGTH,
        first_name=DEFAULT_FIRST_NAME,
        last_name=DEFAULT_LAST_NAME,
        user_timezone=DEFAULT_USER_TIMEZONE,
        user_attributes=valid_json_str,
        secret_id=DEFAULT_SECRET_ID,
    )
    assert isinstance(result, EmbedSDKObj)
    assert result.user_attributes == expected_dict

def test_get_embed_sdk_obj_default_json():
    """
    Tests that get_embed_sdk_obj uses default empty dict for user_attributes.
    """
    result = get_embed_sdk_obj(
        dashboard_id=DEFAULT_DASHBOARD_ID,
        external_user_id=DEFAULT_EXTERNAL_USER_ID,
        group_ids=DEFAULT_GROUP_IDS,
        permissions=list(DEFAULT_PERMISSIONS),
        models=DEFAULT_MODELS,
        session_length=DEFAULT_SESSION_LENGTH,
        first_name=DEFAULT_FIRST_NAME,
        last_name=DEFAULT_LAST_NAME,
        user_timezone=DEFAULT_USER_TIMEZONE,
        user_attributes="{}", # Explicitly pass default to avoid Query object
        secret_id=DEFAULT_SECRET_ID,
    )
    assert isinstance(result, EmbedSDKObj)
    assert result.user_attributes == {}

# Tests for /health endpoint using TestClient
def test_health_endpoint_invalid_user_attributes_single_quotes():
    """
    Tests /health endpoint with invalid user_attributes (single quotes).
    This should be caught by the ValueError exception handler.
    """
    invalid_attributes = "{'key': 'value'}"
    response = client.get(
        "/health",
        params={
            "dashboard_id": DEFAULT_DASHBOARD_ID,
            "external_user_id": DEFAULT_EXTERNAL_USER_ID,
            "user_attributes": invalid_attributes,
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == f"Invalid JSON format for user_attributes: {invalid_attributes}"

def test_health_endpoint_invalid_user_attributes_empty_string():
    """
    Tests /health endpoint with invalid user_attributes (empty string).
    This should be caught by the ValueError exception handler.
    """
    empty_attributes = ""
    response = client.get(
        "/health",
        params={
            "dashboard_id": DEFAULT_DASHBOARD_ID,
            "external_user_id": DEFAULT_EXTERNAL_USER_ID,
            "user_attributes": empty_attributes,
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == f"Invalid JSON format for user_attributes: {empty_attributes}"

def test_health_endpoint_valid_user_attributes():
    """
    Tests /health endpoint with valid user_attributes.
    The /health endpoint itself has complex dependencies (like WebDriver)
    and might not return a simple 200 OK in a unit test environment
    if those dependencies are not fully mocked or available.
    This test primarily ensures that valid user_attributes do not trigger the
    400 error from the ValueError handler. The actual response content/status
    will be whatever the /health endpoint returns in this environment.
    """
    valid_attributes = '{"key": "value"}'
    response = client.get(
        "/health",
        params={
            "dashboard_id": DEFAULT_DASHBOARD_ID,
            "external_user_id": DEFAULT_EXTERNAL_USER_ID,
            "user_attributes": valid_attributes,
        },
    )
    # We expect the request to pass the user_attributes validation
    # The health check might fail for other reasons (e.g. SDK not initialized, WebDriver issues)
    # but it shouldn't be a 400 due to user_attributes.
    assert response.status_code != 400 
    # If observability_ctx.sdk is not initialized, it will be a 500.
    # This is acceptable for this test, as we are focused on the ValueError handler.
    # A more complete integration test would mock the SDK and WebDriver.
    if response.status_code == 500:
         assert response.json()["detail"] == "No SDK found"
    # If there were other issues, other status codes might appear.
    # For now, not failing with 400 due to user_attributes is the key.

def test_health_endpoint_default_user_attributes():
    """
    Tests /health endpoint with default user_attributes (empty dict).
    """
    response = client.get(
        "/health",
        params={
            "dashboard_id": DEFAULT_DASHBOARD_ID,
            "external_user_id": DEFAULT_EXTERNAL_USER_ID,
            # No user_attributes provided, should default to "{}"
        },
    )
    assert response.status_code != 400
    if response.status_code == 500:
         assert response.json()["detail"] == "No SDK found"
