"""Test event formatting and merging logic."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.messaging import _format_one, _format_and_merge, _MERGEABLE


# ── _format_one tests ──

def test_format_tool_call():
    ev = {"event": "tool.start", "data": {"name": "web_search", "args_text": '{"q":"test"}'}}
    result = _format_one(ev)
    assert result["event"] == "tool_call"
    assert result["name"] == "web_search"
    assert result["input"] == '{"q":"test"}'


def test_format_tool_call_with_input():
    ev = {"event": "tool.call", "data": {"name": "terminal", "input": "ls"}}
    result = _format_one(ev)
    assert result["event"] == "tool_call"
    assert result["name"] == "terminal"
    assert result["input"] == "ls"


def test_format_tool_result():
    ev = {"event": "tool.complete", "data": {"name": "web_search", "result": {"output": "ok"}}}
    result = _format_one(ev)
    assert result["event"] == "tool_result"
    assert result["name"] == "web_search"
    assert result["output"] == "ok"


def test_format_tool_result_string():
    ev = {"event": "tool_result", "data": {"name": "terminal", "result": "done"}}
    result = _format_one(ev)
    assert result["event"] == "tool_result"
    assert result["output"] == "done"


def test_format_reasoning_delta():
    ev = {"event": "reasoning.delta", "data": {"text": "thinking..."}}
    result = _format_one(ev)
    assert result["event"] == "reasoning.delta"
    assert result["text"] == "thinking..."


def test_format_thinking_delta():
    ev = {"event": "thinking.delta", "data": {"text": "(¬_¬)"}}
    result = _format_one(ev)
    assert result["event"] == "thinking.delta"
    assert result["text"] == "(¬_¬)"


def test_format_message_delta():
    ev = {"event": "message.delta", "data": {"text": "hello"}}
    result = _format_one(ev)
    assert result["event"] == "message.delta"
    assert result["text"] == "hello"


def test_format_response_chunk():
    ev = {"event": "response.chunk", "data": {"text": "chunk", "delta": "d"}}
    result = _format_one(ev)
    assert result["event"] == "response.chunk"
    assert result["text"] == "chunk"
    assert result["delta"] == "d"


def test_format_message_complete():
    ev = {"event": "message.complete", "data": {"text": "done", "usage": {"tokens": 100}}}
    result = _format_one(ev)
    assert result["event"] == "completed"
    assert result["text"] == "done"
    assert result["usage"] == {"tokens": 100}


def test_format_background_complete():
    ev = {"event": "background.complete", "data": {"text": "bg done"}}
    result = _format_one(ev)
    assert result["event"] == "completed"
    assert result["text"] == "bg done"


def test_format_error():
    ev = {"event": "response.error", "data": {"message": "fail"}}
    result = _format_one(ev)
    assert result["event"] == "error"
    assert result["message"] == "fail"


def test_format_approval():
    ev = {"event": "approval.request", "data": {"pattern_key": "shell", "command": "ls"}}
    result = _format_one(ev)
    assert result["event"] == "approval_required"
    assert result["id"] == "shell"
    assert result["command"] == "ls"


def test_format_unknown():
    ev = {"event": "custom.event", "data": {"foo": "bar"}}
    result = _format_one(ev)
    assert result["event"] == "custom.event"
    assert result["data"] == {"foo": "bar"}


# ── _format_and_merge tests ──

def test_merge_empty():
    assert _format_and_merge([]) == []


def test_merge_single_event():
    events = [{"event": "tool.start", "data": {"name": "t"}}]
    result = _format_and_merge(events)
    assert len(result) == 1
    assert result[0]["event"] == "tool_call"


def test_merge_consecutive_reasoning_delta():
    """Consecutive reasoning.delta should merge."""
    events = [
        {"event": "reasoning.delta", "data": {"text": "hello "}},
        {"event": "reasoning.delta", "data": {"text": "world"}},
    ]
    result = _format_and_merge(events)
    assert len(result) == 1
    assert result[0]["text"] == "hello world"


def test_merge_consecutive_message_delta():
    """Consecutive message.delta should merge."""
    events = [
        {"event": "message.delta", "data": {"text": "今天"}},
        {"event": "message.delta", "data": {"text": "天气"}},
        {"event": "message.delta", "data": {"text": "晴"}},
    ]
    result = _format_and_merge(events)
    assert len(result) == 1
    assert result[0]["text"] == "今天天气晴"


def test_merge_consecutive_thinking_delta():
    events = [
        {"event": "thinking.delta", "data": {"text": "(¬_¬) "}},
        {"event": "thinking.delta", "data": {"text": "reasoning..."}},
    ]
    result = _format_and_merge(events)
    assert len(result) == 1
    assert result[0]["text"] == "(¬_¬) reasoning..."


def test_no_merge_different_types():
    """Different event types should not merge."""
    events = [
        {"event": "reasoning.delta", "data": {"text": "thinking"}},
        {"event": "tool.start", "data": {"name": "t"}},
        {"event": "reasoning.delta", "data": {"text": "more"}},
    ]
    result = _format_and_merge(events)
    assert len(result) == 3


def test_no_merge_non_delta_events():
    """Non-delta events should not merge even if same type."""
    events = [
        {"event": "tool.start", "data": {"name": "a"}},
        {"event": "tool.start", "data": {"name": "b"}},
    ]
    result = _format_and_merge(events)
    assert len(result) == 2


def test_merge_mixed_sequence():
    """Real-world sequence: thinking → reasoning → tool → message → completed."""
    events = [
        {"event": "thinking.delta", "data": {"text": "(¬_¬) "}},
        {"event": "thinking.delta", "data": {"text": "reasoning..."}},
        {"event": "reasoning.delta", "data": {"text": "user wants "}},
        {"event": "reasoning.delta", "data": {"text": "weather"}},
        {"event": "tool.start", "data": {"name": "web_search"}},
        {"event": "tool.complete", "data": {"name": "web_search", "result": {"output": ""}}},
        {"event": "message.delta", "data": {"text": "今天"}},
        {"event": "message.delta", "data": {"text": "晴"}},
        {"event": "message.complete", "data": {"text": "今天晴", "usage": {}}},
    ]
    result = _format_and_merge(events)
    assert len(result) == 6  # thinking, reasoning, tool_call, tool_result, message, completed
    assert result[0]["event"] == "thinking.delta"
    assert result[0]["text"] == "(¬_¬) reasoning..."
    assert result[1]["event"] == "reasoning.delta"
    assert result[1]["text"] == "user wants weather"
    assert result[2]["event"] == "tool_call"
    assert result[3]["event"] == "tool_result"
    assert result[4]["event"] == "message.delta"
    assert result[4]["text"] == "今天晴"
    assert result[5]["event"] == "completed"


# ── _MERGEABLE set tests ──

def test_mergeable_contains_expected():
    assert "reasoning.delta" in _MERGEABLE
    assert "thinking.delta" in _MERGEABLE
    assert "message.delta" in _MERGEABLE
    assert "response.chunk" in _MERGEABLE


def test_mergeable_does_not_contain_tool():
    assert "tool.start" not in _MERGEABLE
    assert "tool_call" not in _MERGEABLE
    assert "completed" not in _MERGEABLE
