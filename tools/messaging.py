"""Messaging + Streaming MCP tools — messages read/unread/stream via WS RPC only."""

from __future__ import annotations

import json
import time
from config import SHORT_RPC_TIMEOUT, DEFAULT_MSG_LIMIT, STREAM_DEFAULT_TIMEOUT, STREAM_MAX_TIMEOUT, STREAM_POLL_INTERVAL


def register_messaging_tools(mcp, bridge, cursor):
    """Register 7 messaging tools — all via WS RPC (no local DB)."""

    # ── Messages History ──

    @mcp.tool()
    async def hermes_messages_history(
        session_id: str = "",
        limit: int = DEFAULT_MSG_LIMIT,
    ) -> str:
        """Get full conversation history of a session via WS RPC.

        Args:
            session_id: Target session ID (empty = current session)
            limit: Max messages to return (default 50)

        Returns JSON with messages from the Hermes session.
        """
        sid = session_id or bridge.session_id
        if not sid:
            return json.dumps({"error": "No session. Use hermes_session_create first."})

        try:
            r = await bridge.session_history(sid)
            if "error" in r:
                return json.dumps({"error": r["error"]["message"]})

            messages = r.get("result", {}).get("messages", [])
            count = r.get("result", {}).get("count", 0)

            return json.dumps({
                "status": "ok",
                "count": min(count, limit),
                "session_id": sid,
                "messages": messages[-limit:],
            }, indent=2, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)})

    # ── Messages Read ──

    @mcp.tool()
    async def hermes_messages_read(
        session_id: str = "",
        mode: str = "all",
        limit: int = DEFAULT_MSG_LIMIT,
    ) -> str:
        """Read messages from a conversation with read-cursor tracking.

        Args:
            session_id: Target session ID (empty = current session)
            mode: "all" = all messages (no cursor update),
                  "unread" = only new messages since last read (updates cursor)
            limit: Max messages for "all" mode (default 50)

        Returns JSON with:
            status: "ok" | "no_unread"
            count: number of messages
            messages: [{role, text, ...}, ...]
        """
        sid = session_id or bridge.session_id
        if not sid:
            return json.dumps({"error": "No session. Use hermes_session_create first."})

        try:
            r = await bridge.session_history(sid)
            if "error" in r:
                return json.dumps({"error": r["error"]["message"]})

            messages = r.get("result", {}).get("messages", [])

            if mode == "unread":
                result = cursor.read_unread(sid, messages)
            else:
                result = cursor.read_all(sid, messages, limit=limit)

            return json.dumps(result, indent=2, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)})

    # ── Messages Stream (event-driven, batched) ──

    @mcp.tool()
    async def hermes_messages_stream(
        session_id: str = "",
        timeout: int = STREAM_DEFAULT_TIMEOUT,
    ) -> str:
        """Wait for events using long-poll streaming. Returns ALL unread events.

        Each call drains the event buffer, then waits for more events until
        timeout. Consecutive events of the same type (e.g. reasoning.delta)
        are merged into one. Returns immediately if events are buffered.

        Args:
            session_id: Target session (empty = current)
            timeout: Max seconds to wait (default 60, max 300)

        Returns JSON with:
            status: "events" | "timeout"
            events: [...] — list of merged events
            Each event has: event, name, text, input, output, usage, etc.
        """
        timeout = max(1, min(timeout, STREAM_MAX_TIMEOUT))

        # Collect all events: drain buffer + wait for more
        raw_events = []

        # 1. Drain ALL buffered events
        while bridge._events:
            raw_events.append(bridge._events.pop(0))

        # 2. If nothing buffered, wait for at least one event
        if not raw_events:
            start = time.time()
            while time.time() - start < timeout:
                remaining_ms = int((timeout - (time.time() - start)) * 1000)
                ev = await bridge.wait_for_event(timeout_ms=min(3000, max(200, remaining_ms)))
                if ev:
                    raw_events.append(ev)
                    break
            if not raw_events:
                # Still nothing — check if running
                sid = session_id or bridge.session_id
                still_running = False
                if sid:
                    try:
                        status_r = await bridge.session_status(sid)
                        output = status_r.get("result", {}).get("output", "")
                        still_running = "Agent Running: Yes" in output
                    except Exception:
                        pass
                return json.dumps({
                    "status": "timeout",
                    "events": [],
                    "running": still_running,
                }, indent=2)

        # 3. Drain any remaining buffered events (non-blocking)
        while bridge._events:
            raw_events.append(bridge._events.pop(0))

        # 4. Format and merge consecutive identical event types
        events = _format_and_merge(raw_events)

        return json.dumps({
            "status": "events",
            "count": len(events),
            "events": events,
        }, indent=2, ensure_ascii=False)


# ── Event formatting & merging ──

# Event types that should be merged when consecutive
_MERGEABLE = {"reasoning.delta", "thinking.delta", "response.chunk", "message.delta"}


def _format_and_merge(raw_events: list[dict]) -> list[dict]:
    """Format raw WS events and merge consecutive identical delta events."""
    if not raw_events:
        return []

    result = []
    for ev in raw_events:
        formatted = _format_one(ev)
        # Merge with previous if same type and both are delta events
        if result and result[-1].get("event") == formatted.get("event") \
                and formatted.get("event") in _MERGEABLE:
            prev = result[-1]
            prev["text"] = prev.get("text", "") + formatted.get("text", "")
            if "delta" in formatted:
                prev["delta"] = prev.get("delta", "") + formatted.get("delta", "")
        else:
            result.append(formatted)

    return result


def _format_one(ev: dict) -> dict:
    """Format a single raw WS event into a structured dict."""
    ev_name = ev.get("event", "")
    ev_data = ev.get("data", {})

    # Tool call started
    if ev_name in ("tool.call", "tool.start"):
        return {
            "event": "tool_call",
            "name": ev_data.get("name", ""),
            "input": ev_data.get("args_text", ev_data.get("input", "")),
        }

    # Tool completed
    if ev_name in ("tool.complete", "tool_result"):
        output = ev_data.get("result", "")
        if isinstance(output, dict):
            output = output.get("output", "")[:1000]
        else:
            output = str(output)[:1000]
        return {
            "event": "tool_result",
            "name": ev_data.get("name", ""),
            "output": output,
        }

    # Reasoning / thinking delta
    if ev_name in ("reasoning.delta", "thinking.delta"):
        return {"event": ev_name, "text": ev_data.get("text", "")}

    # Streaming text chunk
    if ev_name in ("response.chunk", "message.delta"):
        return {"event": ev_name, "text": ev_data.get("text", ""), "delta": ev_data.get("delta", "")}

    # Full message completed
    if ev_name == "message.complete":
        return {"event": "completed", "text": ev_data.get("text", ""), "usage": ev_data.get("usage", {})}

    # Background task completed
    if ev_name == "background.complete":
        return {"event": "completed", "text": ev_data.get("text", "")}

    # Errors
    if ev_name in ("response.error", "background.error"):
        return {"event": "error", "message": ev_data.get("message", "Unknown error")}

    # Approval request
    if ev_name == "approval.request":
        return {
            "event": "approval_required",
            "id": ev_data.get("pattern_key", ev_data.get("id", "")),
            "command": ev_data.get("command", ""),
            "description": ev_data.get("description", ""),
        }

    # Pass through
    return {"event": ev_name or "unknown", "data": ev_data}

    # ── Events ──

    @mcp.tool()
    async def hermes_events_poll(after_cursor: int = 0, limit: int = 20) -> str:
        """Poll for raw events since a cursor position.

        Args:
            after_cursor: Return events after this cursor (0 for all)
            limit: Max events to return
        """
        events = bridge._events
        filtered = [e for e in events if True]
        return json.dumps({
            "count": len(filtered[-limit:]),
            "events": filtered[-limit:],
        }, indent=2, ensure_ascii=False)

    @mcp.tool()
    async def hermes_events_wait(after_cursor: int = 0, timeout_ms: int = 30000) -> str:
        """Wait for the next raw event (long-poll).

        Args:
            after_cursor: Wait for events after this cursor
            timeout_ms: Max wait time in milliseconds (default 30000)
        """
        ev = await bridge.wait_for_event(timeout_ms=min(timeout_ms, 300000))
        if ev:
            return json.dumps({"event": ev}, indent=2, ensure_ascii=False)
        return json.dumps({"event": None, "reason": "timeout"}, indent=2)
