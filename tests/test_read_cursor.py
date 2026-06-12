"""Test ReadCursor — message tracking without 'id' fields."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ws_bridge import ReadCursor


def test_initial_cursor_is_zero():
    c = ReadCursor()
    assert c.get_cursor("s1") == 0


def test_advance_with_id_field():
    c = ReadCursor()
    msgs = [{"id": 1, "text": "a"}, {"id": 2, "text": "b"}]
    c.advance("s1", msgs)
    assert c.get_cursor("s1") == 2


def test_advance_without_id_field():
    """Messages without 'id' should use list length."""
    c = ReadCursor()
    msgs = [{"text": "a"}, {"text": "b"}, {"text": "c"}]
    c.advance("s1", msgs)
    assert c.get_cursor("s1") == 3


def test_filter_unread_with_id():
    c = ReadCursor()
    msgs = [{"id": 1, "text": "a"}, {"id": 2, "text": "b"}, {"id": 3, "text": "c"}]
    c.advance("s1", [{"id": 1, "text": "a"}])
    unread = c.filter_unread("s1", msgs)
    assert len(unread) == 2
    assert unread[0]["id"] == 2


def test_filter_unread_without_id():
    """Messages without 'id' should use index-based tracking."""
    c = ReadCursor()
    msgs = [{"text": "a"}, {"text": "b"}, {"text": "c"}]
    # Read first message
    c.advance("s1", msgs[:1])
    assert c.get_cursor("s1") == 1

    # Get unread
    unread = c.filter_unread("s1", msgs)
    assert len(unread) == 2
    assert unread[0]["text"] == "b"
    assert unread[1]["text"] == "c"


def test_filter_unread_empty():
    c = ReadCursor()
    assert c.filter_unread("s1", []) == []


def test_read_unread_returns_dict():
    c = ReadCursor()
    msgs = [{"text": "a"}, {"text": "b"}]
    result = c.read_unread("s1", msgs)
    assert result["status"] == "messages"
    assert result["count"] == 2


def test_read_unread_no_new():
    c = ReadCursor()
    msgs = [{"text": "a"}]
    c.advance("s1", msgs)
    result = c.read_unread("s1", msgs)
    assert result["status"] == "no_unread"
    assert result["count"] == 0


def test_multiple_sessions():
    c = ReadCursor()
    c.advance("s1", [{"text": "a"}, {"text": "b"}])
    c.advance("s2", [{"text": "x"}])
    assert c.get_cursor("s1") == 2
    assert c.get_cursor("s2") == 1


def test_read_all_returns_all():
    c = ReadCursor()
    msgs = [{"text": "a"}, {"text": "b"}, {"text": "c"}]
    result = c.read_all("s1", msgs, limit=10)
    assert result["status"] == "ok"
    assert result["count"] == 3
    assert len(result["messages"]) == 3
