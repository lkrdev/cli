import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from lkr.extended_sdk_methods import ExtendedLooker40SDK
from lkr.main import app
from lkr.tools.agents import ARTIFACT_NAMESPACE, dedupe_agent_publications

runner = CliRunner()


def _make_mock_sdk() -> MagicMock:
    sdk = MagicMock(spec=ExtendedLooker40SDK)
    sdk.artifact.return_value = []
    sdk.update_artifacts.return_value = []
    sdk.search_artifacts.return_value = []
    sdk.search_agents.return_value = []
    return sdk


@patch("lkr.tools.agents.get_auth")
def test_agents_publish_updates_artifact(mock_get_auth):
    sdk = _make_mock_sdk()
    sdk.validate_gemini_enterprise_metadata.return_value = {"success": True}
    sdk.publish_agent.return_value = {
        "state": "published",
        "message": "Successfully published Agent agent-123 to gemini_enterprise.",
        "ge_agent_metadata": {
            "ge_gcp_project_number": "123456789012",
            "ge_gcp_location": "global",
            "ge_engine_id": "secondary-engine",
        },
    }
    mock_get_auth.return_value.get_current_sdk.return_value = sdk

    result = runner.invoke(
        app,
        [
            "tools",
            "agents",
            "publish",
            "agent-123",
            "--project-number",
            "123456789012",
            "--location",
            "global",
            "--engine-id",
            "secondary-engine",
            "--validate",
        ],
    )
    assert result.exit_code == 0
    out = json.loads(result.stdout)
    assert out["state"] == "published"
    sdk.update_artifacts.assert_called_once()
    call_kwargs = sdk.update_artifacts.call_args.kwargs
    assert call_kwargs["namespace"] == ARTIFACT_NAMESPACE
    saved_payload = json.loads(call_kwargs["body"][0].value)
    assert saved_payload["agent_id"] == "agent-123"
    assert (
        saved_payload["publications"]["123456789012:global:secondary-engine"][
            "state"
        ]
        == "published"
    )


@patch("lkr.tools.agents.logger")
@patch("lkr.tools.agents.get_auth")
def test_agents_publish_catches_failed_to_register_license_error(
    mock_get_auth, mock_logger
):
    sdk = _make_mock_sdk()
    sdk.publish_agent.side_effect = Exception(
        '{"message":"Failed to register agent with GE."}'
    )
    sdk.get_gemini_enablement.return_value = {
        "ai_ge_service_account_email": "looker-esa-test@looker-external-sa.iam.gserviceaccount.com"
    }
    mock_get_auth.return_value.get_current_sdk.return_value = sdk

    result = runner.invoke(
        app,
        [
            "tools",
            "agents",
            "publish",
            "agent-123",
            "--project-number",
            "123456789012",
            "--location",
            "global",
            "--engine-id",
            "secondary-engine",
        ],
    )
    assert result.exit_code == 1
    sdk.get_gemini_enablement.assert_called_once_with()
    mock_logger.error.assert_called_once()
    err_msg = mock_logger.error.call_args.args[0]
    assert "Gemini Enterprise > Manage Users" in err_msg
    assert "looker-esa-test@looker-external-sa.iam.gserviceaccount.com" in err_msg
    sdk.update_artifacts.assert_not_called()


@patch("lkr.tools.agents.get_auth")
def test_agents_delete_default_singleton_updates_artifact(mock_get_auth):
    sdk = _make_mock_sdk()
    sdk.unpublish_agent.return_value = {
        "state": "unpublished",
        "message": "AGENT_UNPUBLISHED_SUCCESSFULLY",
        "ge_agent_metadata": {
            "ge_gcp_project_number": "111",
            "ge_gcp_location": "global",
            "ge_engine_id": "eng-1",
        },
    }
    mock_get_auth.return_value.get_current_sdk.return_value = sdk

    result = runner.invoke(app, ["tools", "agents", "delete", "agent-123"])
    assert result.exit_code == 0
    out = json.loads(result.stdout)
    assert out["message"] == "AGENT_UNPUBLISHED_SUCCESSFULLY"
    sdk.update_artifacts.assert_called_once()
    saved = json.loads(sdk.update_artifacts.call_args.kwargs["body"][0].value)
    assert saved["publications"]["111:global:eng-1"]["state"] == "unpublished"


@patch("lkr.tools.agents.requests.delete")
@patch("lkr.tools.agents.requests.get")
@patch("lkr.tools.agents.get_auth")
def test_agents_delete_auto_discovers_targets_from_artifact(
    mock_get_auth, mock_requests_get, mock_requests_delete
):
    sdk = _make_mock_sdk()
    sdk.unpublish_agent.return_value = {
        "state": "unpublished",
        "message": "AGENT_NEVER_PUBLISHED",
    }
    sdk.artifact.return_value = [
        {
            "key": "agent-123",
            "version": 3,
            "value": json.dumps(
                {
                    "agent_id": "agent-123",
                    "publications": {
                        "123456789012:us:eng-2": {
                            "ge_gcp_project_number": "123456789012",
                            "ge_gcp_location": "us",
                            "ge_engine_id": "eng-2",
                            "state": "published",
                        }
                    },
                }
            ),
        }
    ]
    mock_get_auth.return_value.get_current_sdk.return_value = sdk

    platform_id = "projects/123456789012/locations/us/collections/default_collection/engines/eng-2/assistants/default_assistant/agents/999"
    mock_list_resp = MagicMock()
    mock_list_resp.json.return_value = {
        "agents": [
            {
                "name": platform_id,
                "a2aAgentDefinition": {
                    "jsonAgentCard": '{"url":"https://looker.example.com/api/4.0/a2a/agents/agent-123/chat"}'
                },
            }
        ]
    }
    mock_requests_get.return_value = mock_list_resp
    mock_requests_delete.return_value = MagicMock()

    result = runner.invoke(
        app,
        [
            "tools",
            "agents",
            "delete",
            "agent-123",
            "--gcp-token",
            "mock-gcp-token",
        ],
    )
    assert result.exit_code == 0
    out = json.loads(result.stdout)
    assert out["message"] == "AGENT_UNPUBLISHED_FROM_DISCOVERY_ENGINE"
    assert out["platform_agent_id"] == platform_id

    sdk.update_artifacts.assert_called_once()
    update_item = sdk.update_artifacts.call_args.kwargs["body"][0]
    assert update_item.version == 3
    saved = json.loads(update_item.value)
    assert (
        saved["publications"]["123456789012:us:eng-2"]["state"] == "unpublished"
    )
    assert (
        saved["publications"]["123456789012:us:eng-2"]["platform_agent_id"]
        == platform_id
    )


@patch("lkr.tools.agents.time.sleep")
@patch("lkr.tools.agents.requests.get")
@patch("lkr.tools.agents.get_auth")
def test_agents_list_merges_and_dedupes_all_three_sources(
    mock_get_auth, mock_requests_get, mock_sleep
):
    sdk = _make_mock_sdk()
    # Looker agents metadata
    sdk.search_agents.return_value = [
        {"id": "agent-123", "name": "Finance Agent", "updated_at": "2026-09-24T10:00:00Z"},
        {"id": "agent-456", "name": "Marketing Agent", "updated_at": "2026-09-24T11:00:00Z"},
    ]
    # Source 1: Artifact has agent-123 on eng-1 (without platform_agent_id)
    sdk.search_artifacts.return_value = [
        {
            "key": "agent-123",
            "value": json.dumps(
                {
                    "agent_id": "agent-123",
                    "publications": {
                        "123456789012:global:eng-1": {
                            "ge_gcp_project_number": "123456789012",
                            "ge_gcp_location": "global",
                            "ge_engine_id": "eng-1",
                            "state": "published",
                            "updated_at": "2026-09-24T19:15:00+00:00",
                        }
                    },
                }
            ),
        }
    ]
    # Source 2 (Method A): Discovery Engine returns agent-123 on eng-1 (with platform_agent_id) AND agent-789 on eng-2
    platform_123 = "projects/123456789012/locations/global/collections/default_collection/engines/eng-1/assistants/default_assistant/agents/111"
    platform_789 = "projects/123456789012/locations/global/collections/default_collection/engines/eng-1/assistants/default_assistant/agents/222"
    mock_de_resp = MagicMock(status_code=200)
    mock_de_resp.json.return_value = {
        "agents": [
            {
                "name": platform_123,
                "displayName": "Finance Agent",
                "updateTime": "2026-09-24T19:20:00Z",
                "a2aAgentDefinition": {
                    "jsonAgentCard": '{"url":"https://instance.looker.com/api/4.0/a2a/agents/agent-123/chat"}'
                },
            },
            {
                "name": platform_789,
                "displayName": "External Secondary Agent",
                "updateTime": "2026-09-24T19:21:00Z",
                "a2aAgentDefinition": {
                    "jsonAgentCard": '{"url":"https://instance.looker.com/api/4.0/a2a/agents/agent-789"}'
                },
            },
        ]
    }
    mock_404_resp = MagicMock(status_code=404)
    mock_requests_get.side_effect = (
        lambda url, **_kwargs: mock_de_resp
        if "/locations/global/" in url
        else mock_404_resp
    )

    # Source 3 (Method B): Looker API returns agent-123 on eng-1 AND agent-456 on eng-1
    def _mock_get_pub(guid: str):
        return {
            "state": "published",
            "message": "ok",
            "ge_agent_metadata": {
                "ge_gcp_project_number": "123456789012",
                "ge_gcp_location": "global",
                "ge_engine_id": "eng-1",
            },
        }

    sdk.get_published_agent.side_effect = _mock_get_pub
    mock_get_auth.return_value.get_current_sdk.return_value = sdk

    res = runner.invoke(
        app,
        [
            "tools",
            "agents",
            "list",
            "--project-number",
            "123456789012",
            "--engine-id",
            "eng-1",
            "--gcp-token",
            "mock-gcp-token",
            "--json",
        ],
    )
    assert res.exit_code == 0
    # Only 1 Looker API call is made (to probe singleton GE config), then Discovery Engine is queried in O(1)
    sdk.get_published_agent.assert_called_once_with("agent-123")
    mock_sleep.assert_not_called()
    rows = json.loads(res.stdout)
    assert len(rows) == 2
    by_id = {r["agent_id"]: r for r in rows}
    assert set(by_id["agent-123"]["discovery_sources"]) == {
        "artifact",
        "discovery_engine",
        "looker_api",
    }
    assert by_id["agent-123"]["platform_agent_id"] == platform_123
    assert by_id["agent-789"]["discovery_sources"] == ["discovery_engine"]


@patch("lkr.tools.agents.time.sleep")
@patch("lkr.tools.agents.get_auth")
def test_agents_list_stops_immediately_on_missing_ge_config(
    mock_get_auth, mock_sleep
):
    sdk = _make_mock_sdk()
    sdk.search_agents.return_value = [
        {"id": f"agent-{i}", "name": f"Agent {i}"} for i in range(98)
    ]
    sdk.get_published_agent.side_effect = Exception(
        "400 Bad Request: MISSING_GE_CONFIGURATION"
    )
    mock_get_auth.return_value.get_current_sdk.return_value = sdk

    res = runner.invoke(app, ["tools", "agents", "list", "--looker-api", "--json"])
    assert res.exit_code == 0
    # Even with --looker-api and 98 agents, MISSING_GE_CONFIGURATION stops after 1 call with 0 sleeps
    sdk.get_published_agent.assert_called_once_with("agent-0")
    mock_sleep.assert_not_called()
    assert json.loads(res.stdout) == []


def test_dedupe_agent_publications_unit():
    recs = [
        {
            "agent_id": "a1",
            "ge_gcp_project_number": "123",
            "ge_gcp_location": "Global",
            "ge_engine_id": "e1",
            "state": "unpublished",
            "discovery_source": "artifact",
        },
        {
            "agent_id": "a1",
            "name": "Agent One",
            "ge_gcp_project_number": "123",
            "ge_gcp_location": "global",
            "ge_engine_id": "e1",
            "state": "published",
            "platform_agent_id": "projects/123/agents/99",
            "discovery_source": "discovery_engine",
        },
    ]
    deduped = dedupe_agent_publications(recs)
    assert len(deduped) == 1
    assert deduped[0]["state"] == "published"
    assert deduped[0]["name"] == "Agent One"
    assert deduped[0]["platform_agent_id"] == "projects/123/agents/99"
    assert deduped[0]["discovery_sources"] == ["artifact", "discovery_engine"]


@patch("lkr.tools.agents.requests.get")
@patch("lkr.tools.agents.get_auth")
def test_agents_list_reconciles_ui_deletion_and_respects_no_update_artifact(
    mock_get_auth, mock_requests_get
):
    sdk = _make_mock_sdk()
    sdk.search_agents.return_value = [{"id": "agent-123", "name": "Deleted In UI"}]
    sdk.search_artifacts.return_value = [
        {
            "key": "agent-123",
            "version": 2,
            "value": json.dumps(
                {
                    "agent_id": "agent-123",
                    "publications": {
                        "123456789012:global:eng-1": {
                            "ge_gcp_project_number": "123456789012",
                            "ge_gcp_location": "global",
                            "ge_engine_id": "eng-1",
                            "state": "published",
                            "updated_at": "2026-09-24T19:15:00+00:00",
                        }
                    },
                }
            ),
        }
    ]
    sdk.artifact.return_value = sdk.search_artifacts.return_value
    sdk.get_published_agent.return_value = {
        "state": "unpublished",
        "message": "AGENT_NEVER_PUBLISHED",
        "ge_agent_metadata": {
            "ge_gcp_project_number": "123456789012",
            "ge_gcp_location": "global",
            "ge_engine_id": "eng-1",
        },
    }
    # Discovery Engine returns 200 OK with empty agents list (deleted in Gemini UI)
    mock_de_resp = MagicMock(status_code=200)
    mock_de_resp.json.return_value = {"agents": []}
    mock_requests_get.return_value = mock_de_resp
    mock_get_auth.return_value.get_current_sdk.return_value = sdk

    # 1. With --no-update-artifact, state is reported as unpublished but artifact is not written
    res_no_sync = runner.invoke(
        app,
        [
            "tools",
            "agents",
            "list",
            "--gcp-token",
            "mock-gcp-token",
            "--no-update-artifact",
            "--json",
        ],
    )
    assert res_no_sync.exit_code == 0
    rows_no_sync = json.loads(res_no_sync.stdout)
    assert len(rows_no_sync) == 1
    assert rows_no_sync[0]["state"] == "unpublished"
    sdk.update_artifacts.assert_not_called()

    # 2. Default (update-artifact enabled) updates the artifact to unpublished
    res_sync = runner.invoke(
        app,
        [
            "tools",
            "agents",
            "list",
            "--gcp-token",
            "mock-gcp-token",
            "--json",
        ],
    )
    assert res_sync.exit_code == 0
    rows_sync = json.loads(res_sync.stdout)
    assert rows_sync[0]["state"] == "unpublished"
    sdk.update_artifacts.assert_called_once()
    saved = json.loads(sdk.update_artifacts.call_args.kwargs["body"][0].value)
    assert (
        saved["publications"]["123456789012:global:eng-1"]["state"]
        == "unpublished"
    )


def test_project_number_validation_rejects_string_project_id():
    import pytest
    from pydantic import ValidationError

    from lkr.extended_sdk_methods import GeminiEnterpriseAgentRequest

    req = GeminiEnterpriseAgentRequest(ge_gcp_project_number="974752897662")
    assert req.ge_gcp_project_number == "974752897662"
    assert isinstance(req.ge_gcp_project_number, str)

    with pytest.raises(ValidationError, match="numeric GCP project number"):
        GeminiEnterpriseAgentRequest(ge_gcp_project_number="my-gcp-project-id")

    res = runner.invoke(
        app,
        ["tools", "agents", "publish", "agent-123", "-p", "my-gcp-project-id"],
    )
    assert res.exit_code != 0
    assert "numeric GCP project number" in (res.stdout + (res.stderr or ""))
