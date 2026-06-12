"""Messaging + Streaming MCP tools — conversations, messages read/unread/stream, send."""

from __future__ import annotations

import json
import time
from config import SHORT_RPC_TIMEOUT, DEFAULT_MSG_LIMIT, STREAM_DEFAULT_TIMEOUT, STREAM_MAX_TIMEOUT, STREAM_POLL_INTERVAL


def register_messaging_tools(mcp, bridge, db, cursor):
    """Register 8 messaging tools with read-cursor support."""

    # ── Conversations ──

    @mcp.tool()
    def hermes_conversations_list(platform: str = "", limit: int = DEFAULT_MSG_LIMIT) -> str:
        """List active messaging conversations across connected platforms.

        Args:
            platform: Filter by platform (telegram, discord, slack, etc.)
            limit: Max conversations (default 50)
        """
        entries = db.get_sessions_index()
        conversations = []

        for key, entry in entries.items():
            origin = entry.get("origin", {})
            p = entry.get("platform") or origin.get("platform", "")
            if platform and p.lower() != platform.lower():
                continue

            display_name = entry.get("display_name", "")
            chat_name = origin.get("chat_name", "")
            conversations.append({
                "session_key": key,
                "session_id": entry.get("session_id", ""),
                "platform": p,
                "chat_type": entry.get("chat_type", origin.get("chat_type", "")),
                "display_name": display_name,
                "chat_name": chat_name,
                "user_name": origin.get("user_name", ""),
                "updated_at": entry.get("updated_at", ""),
            })

        conversations.sort(key=lambda c: c.get("updated_at", ""), reverse=True)
        return json.dumps({
            "count": min(len(conversations), limit),
            "conversations": conversations[:limit],
        }, indent=2, ensure_ascii=False)

    @mcp.tool()
    def hermes_conversation_get(session_key: str) -> str:
        """Get detailed info about one conversation by its session key.

        Args:
            session_key: The session key from hermes_conversations_list
        """
        entry = db.get_session_entry(session_key)
        if not entry:
            return json.dumps({"error": f"Conversation not found: {session_key}"})

        origin = entry.get("origin", {})
        return json.dumps({
            "session_key": session_key,
            "session_id": entry.get("session_id", ""),
            "platform": entry.get("platform") or origin.get("platform", ""),
            "chat_type": entry.get("chat_type", origin.get("chat_type", "")),
            "display_name": entry.get("display_name", ""),
            "user_name": origin.get("user_name", ""),
            "chat_name": origin.get("chat_name", ""),
            "chat_id": origin.get("chat_id", ""),
            "thread_id": origin.get("thread_id"),
            "updated_at": entry.get("updated_at", ""),
            "created_at": entry.get("created_at", ""),
            "input_tokens": entry.get("input_tokens", 0),
            "output_tokens": entry.get("output_tokens", 0),
            "total_tokens": entry.get("total_tokens", 0),
        }, indent=2)

    # ── Messages Read ──

    @mcp.tool()
    def hermes_messages_read(
        session_key: str = "",
        mode: str = "all",
        limit: int = DEFAULT_MSG_LIMIT,
    ) -> str:
        """Read messages from a conversation with read-cursor tracking.

        Args:
            session_key: Target session key (empty = use current session_id)
            mode: "all" = all messages (no cursor update),
                  "unread" = only new messages since last read (updates cursor)
            limit: Max messages for "all" mode (default 50)

        Returns JSON with:
            status: "ok" | "no_unread"
            count: number of messages
            messages: [{id, role, content, timestamp}, ...]
        """
        sid = session_key or bridge.session_id
        if not sid:
            return json.dumps({"error": "No session. Use hermes_session_create first."})

        # Get messages — by key or by id
        if session_key:
            messages = db.get_messages_by_key(session_key, limit=500)
        else:
            # Try as session_id directly
            messages = db.get_messages(sid, limit=500)

        if mode == "unread":
            result = cursor.read_unread(sid, messages)
        else:
            result = cursor.read_all(sid, messages, limit=limit)

        return json.dumps(result, indent=2, ensure_ascii=False)

    # ── Messages Stream ──

    @mcp.tool()
    async def hermes_messages_stream(
        session_key: str = "",
        timeout: int = STREAM_DEFAULT_TIMEOUT,
    ) -> str:
        """Wait for new messages using long-poll streaming.

        Blocks until new messages arrive or the task completes. Use after
        hermes_prompt_background to stream results as they come in.

        Args:
            session_key: Target session (empty = current)
            timeout: Max seconds to wait (default 60, max 300)

        Returns JSON with:
            status: "messages" — new messages arrived
                    "completed" — task finished, no unread messages
                    "running" — task still running, no new messages yet (call again)
                    "timeout" — timed out waiting
            messages: [...] (when status=messages or completed)
        """
        timeout = max(1, min(timeout, STREAM_MAX_TIMEOUT))
        sid = session_key or bridge.session_id
        if not sid:
            return json.dumps({"error": "No session."})

        # 1. Check for unread immediately
        if session_key:
            messages = db.get_messages_by_key(session_key, limit=500)
        else:
            messages = db.get_messages(sid, limit=500)

        unread = cursor.filter_unread(sid, messages)
        if unread:
            cursor.advance(sid, unread)
            return json.dumps({
                "status": "messages",
                "count": len(unread),
                "cursor": cursor.get_cursor(sid),
                "messages": unread,
            }, indent=2, ensure_ascii=False)

        # 2. No unread messages — wait for WS events (including background tasks)
        # Don't check session.status here because background tasks run independently
        start = time.time()
        while time.time() - start < timeout:
            remaining_ms = int((timeout - (time.time() - start)) * 1000)
            ev = await bridge.wait_for_event(timeout_ms=min(5000, max(200, remaining_ms)))

            if ev:
                ev_name = ev.get("event", "")
                # Check for message-related events
                if ev_name in ("message", "response.chunk", "response.completed",
                              "response.error", "background.complete", "background.error"):
                    # Re-read messages
                    if session_key:
                        messages = db.get_messages_by_key(session_key, limit=500)
                    else:
                        messages = db.get_messages(sid, limit=500)

                    unread = cursor.filter_unread(sid, messages)
                    if unread:
                        cursor.advance(sid, unread)
                        return json.dumps({
                            "status": "messages",
                            "count": len(unread),
                            "cursor": cursor.get_cursor(sid),
                            "messages": unread,
                        }, indent=2, ensure_ascii=False)

                    # Completion event with no new text messages
                    if ev_name in ("response.completed", "response.error",
                                   "background.complete", "background.error"):
                        # Include the event data for background tasks
                        result = {
                            "status": "completed",
                            "count": 0,
                            "messages": [],
                        }
                        # Attach background result if available
                        bg_data = ev.get("data", {})
                        if bg_data.get("text"):
                            result["background_result"] = bg_data["text"]
                        return json.dumps(result, indent=2, ensure_ascii=False)

        # 4. Timeout — check if still running
        try:
            status_r = await bridge.call("session.status", {"session_id": sid}, timeout=SHORT_RPC_TIMEOUT)
            still_running = status_r.get("result", {}).get("running", False)
        except Exception:
            still_running = False

        return json.dumps({
            "status": "running" if still_running else "timeout",
            "count": 0,
            "messages": [],
            "hint": "Task still running. Call hermes_messages_stream again." if still_running else "Timed out.",
        }, indent=2)

    # ── Send ──

    @mcp.tool()
    async def hermes_messages_send(target: str, message: str) -> str:
        """Send a message to a platform channel.

        Args:
            target: Platform target in "platform:chat_id" format (e.g. "telegram:6308981865")
            message: The message text to send
        """
        if not target or not message:
            return json.dumps({"error": "Both target and message are required"})
        if ":" not in target:
            return json.dumps({"error": "Target must be 'platform:chat_id' format (e.g. 'telegram:12345')"})

        platform, chat_id = target.split(":", 1)
        if not platform or not chat_id:
            return json.dumps({"error": "Both platform and chat_id are required in target"})

        try:
            r = await bridge.call("message.send", {
                "platform": platform,
                "chat_id": chat_id,
                "message": message,
            }, timeout=SHORT_RPC_TIMEOUT)
            if "result" in r:
                return json.dumps({"ok": True, "target": target, "result": r["result"]}, indent=2)
            return json.dumps({"error": r.get("error", "Send failed")}, indent=2)
        except TimeoutError:
            return json.dumps({"error": f"Send timed out for target: {target}"}, indent=2)
        except Exception as e:
            return json.dumps({"error": f"Send failed: {e}"}, indent=2)

    # ── Channels ──

    @mcp.tool()
    def hermes_channels_list(platform: str = "") -> str:
        """List available messaging channels and targets.

        Args:
            platform: Filter by platform name
        """
        directory = db.get_channel_directory()
        if not directory:
            entries = db.get_sessions_index()
            targets = []
            seen = set()
            for key, entry in entries.items():
                origin = entry.get("origin", {})
                p = entry.get("platform") or origin.get("platform", "")
                chat_id = origin.get("chat_id", "")
                if not p or not chat_id:
                    continue
                if platform and p.lower() != platform.lower():
                    continue
                target_str = f"{p}:{chat_id}"
                if target_str in seen:
                    continue
                seen.add(target_str)
                targets.append({
                    "target": target_str,
                    "platform": p,
                    "name": entry.get("display_name") or origin.get("chat_name", ""),
                    "chat_type": entry.get("chat_type", origin.get("chat_type", "")),
                })
            return json.dumps({"count": len(targets), "channels": targets}, indent=2)

        channels = []
        for plat, entries_list in directory.get("platforms", {}).items():
            if platform and plat.lower() != platform.lower():
                continue
            if isinstance(entries_list, list):
                for ch in entries_list:
                    if isinstance(ch, dict):
                        chat_id = ch.get("id", ch.get("chat_id", ""))
                        channels.append({
                            "target": f"{plat}:{chat_id}" if chat_id else plat,
                            "platform": plat,
                            "name": ch.get("name", ch.get("display_name", "")),
                            "chat_type": ch.get("type", ""),
                        })
        return json.dumps({"count": len(channels), "channels": channels}, indent=2)

    # ── Events ──

    @mcp.tool()
    async def hermes_events_poll(after_cursor: int = 0, limit: int = 20) -> str:
        """Poll for raw events since a cursor position.

        Args:
            after_cursor: Return events after this cursor (0 for all)
            limit: Max events to return
        """
        events = await bridge.collect_events()
        if after_cursor > 0:
            events = [e for e in events if e.get("id", 0) > after_cursor]
        return json.dumps({
            "count": len(events[-limit:]),
            "events": events[-limit:],
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
