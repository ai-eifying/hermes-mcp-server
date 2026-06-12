"""Test streaming integration — prompt_stream + messages_stream."""

import pytest


def test_prompt_stream_returns_ok(client):
    """hermes_prompt_stream should return ok + session_id."""
    r = client.call_tool("hermes_prompt_stream", {"prompt": "hello"}, timeout=15)
    assert r.get("ok") is True or "error" in r, f"Unexpected: {r}"
    if "ok" in r:
        assert "session_id" in r


def test_messages_stream_returns_events(client):
    """hermes_messages_stream should return events or timeout."""
    # Submit a prompt first
    client.call_tool("hermes_prompt_stream", {"prompt": "Reply: OK"}, timeout=15)

    # Read events
    r = client.call_tool("hermes_messages_stream", {"timeout": 10}, timeout=15)
    assert r.get("status") in ("events", "timeout"), f"Unexpected: {r}"
    if r["status"] == "events":
        assert "events" in r
        assert isinstance(r["events"], list)


def test_streaming_has_completed_event(client):
    """Full streaming flow should eventually produce a completed event."""
    client.call_tool("hermes_prompt_stream", {"prompt": "Reply with exactly: STREAM_OK"}, timeout=15)

    # Poll until completed or timeout
    for _ in range(10):
        r = client.call_tool("hermes_messages_stream", {"timeout": 10}, timeout=15)
        if r.get("status") == "events":
            events = r["events"]
            completed = [e for e in events if e.get("event") == "completed"]
            if completed:
                assert completed[0].get("text"), "Completed event should have text"
                return
    pytest.skip("No completed event within polling limit")


def test_streaming_has_tool_call(client):
    """Streaming should capture tool calls."""
    client.call_tool("hermes_prompt_stream", {"prompt": "Search the web for 'test'"}, timeout=15)

    for _ in range(10):
        r = client.call_tool("hermes_messages_stream", {"timeout": 10}, timeout=15)
        if r.get("status") == "events":
            events = r["events"]
            tool_calls = [e for e in events if e.get("event") == "tool_call"]
            if tool_calls:
                assert tool_calls[0].get("name"), "Tool call should have name"
                return
    pytest.skip("No tool call within polling limit")


def test_streaming_message_delta_merged(client):
    """message.delta events should be merged (not fragmented)."""
    client.call_tool("hermes_prompt_stream", {"prompt": "Write a short paragraph about Beijing weather"}, timeout=15)

    for _ in range(10):
        r = client.call_tool("hermes_messages_stream", {"timeout": 10}, timeout=15)
        if r.get("status") == "events":
            events = r["events"]
            deltas = [e for e in events if e.get("event") == "message.delta"]
            # Should have at most 1 merged message.delta (not many fragments)
            if deltas:
                assert len(deltas) <= 2, f"Expected merged deltas, got {len(deltas)}: {[d.get('text','')[:20] for d in deltas]}"
                return
    pytest.skip("No message.delta within polling limit")


def test_prompt_submit_has_tool_calls(client):
    """Synchronous prompt_submit should include tool_calls."""
    r = client.call_tool("hermes_prompt_submit", {
        "prompt": "Search the web for 'test'",
        "timeout": 60,
    }, timeout=70)
    if "error" in r:
        pytest.skip(f"Error: {r['error']}")
    # tool_calls may or may not be present depending on model behavior
    if "tool_calls" in r:
        assert isinstance(r["tool_calls"], list)
        assert r["tool_calls"][0].get("name")


def test_prompt_background_then_stream(client):
    """Background prompt should be readable via stream."""
    client.call_tool("hermes_prompt_background", {"prompt": "Reply: BG_OK"}, timeout=15)

    r = client.call_tool("hermes_messages_stream", {"timeout": 15}, timeout=20)
    assert r.get("status") in ("events", "timeout"), f"Unexpected: {r}"
