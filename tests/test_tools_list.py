"""Test MCP tool registration and discovery."""

import pytest


def test_tools_list_count(client):
    """All 25 tools should be registered."""
    tools = client.list_tools()
    assert len(tools) >= 25, f"Expected >=25 tools, got {len(tools)}"


def test_tools_list_contains_required(client):
    """Core tools must be present."""
    tools = client.list_tools()
    names = {t["name"] for t in tools}
    required = [
        "hermes_session_create", "hermes_session_list", "hermes_session_resume",
        "hermes_session_status", "hermes_session_history", "hermes_session_delete",
        "hermes_prompt_submit", "hermes_prompt_background", "hermes_prompt_stream",
        "hermes_session_interrupt",
        "hermes_messages_history", "hermes_messages_read", "hermes_messages_stream",
        "hermes_events_poll", "hermes_events_wait",
        "hermes_approval_respond", "hermes_permissions_list",
        "hermes_slash_exec", "hermes_cli_exec", "hermes_commands_catalog",
        "hermes_config_get", "hermes_config_set", "hermes_health",
        "hermes_model_options", "hermes_model_disconnect",
    ]
    for name in required:
        assert name in names, f"Missing tool: {name}"


def test_prompt_stream_registered(client):
    """hermes_prompt_stream must be registered."""
    tools = client.list_tools()
    names = {t["name"] for t in tools}
    assert "hermes_prompt_stream" in names, "hermes_prompt_stream not found"
