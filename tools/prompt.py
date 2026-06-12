"""Prompt/Chat MCP tools — submit, background, interrupt."""

from __future__ import annotations

import asyncio
import json
import time
from config import DEFAULT_RPC_TIMEOUT, STREAM_POLL_INTERVAL


def register_prompt_tools(mcp, bridge):
    """Register 3 prompt tools."""

    @mcp.tool()
    async def hermes_prompt_submit(prompt: str, timeout: int = DEFAULT_RPC_TIMEOUT) -> str:
        """Send a prompt to Hermes Agent and wait for the full response.

        The agent processes your prompt, uses tools as needed, and returns
        the complete response. Handles approval requests automatically.

        Args:
            prompt: The prompt text to send
            timeout: Max seconds to wait (default 300)
        """
        if not bridge.session_id:
            r = await bridge.call("session.create", {"title": "mcp-auto"}, timeout=15)
            if "result" in r:
                bridge.session_id = r["result"].get("session_id", "")
                bridge._save_session_id(r["result"].get("stored_session_id", bridge.session_id))
            else:
                return json.dumps({"error": "Failed to auto-create session"}, indent=2)

        bridge.clear_events()

        # Submit prompt (returns immediately with streaming status)
        try:
            r = await bridge.call("prompt.submit", {
                "session_id": bridge.session_id,
                "text": prompt,
            }, timeout=30)
        except TimeoutError:
            return json.dumps({
                "error": "prompt.submit RPC timed out",
                "session_id": bridge.session_id,
            }, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

        if "error" in r:
            return json.dumps({"error": r["error"]}, indent=2)

        # Wait for completion events using long-poll
        result = {"ok": True, "session_id": bridge.session_id}
        start = time.time()

        while time.time() - start < timeout:
            # Use long-poll to wait for events (blocks until event or timeout)
            remaining_ms = int((timeout - (time.time() - start)) * 1000)
            ev = await bridge.wait_for_event(timeout_ms=min(10000, max(500, remaining_ms)))

            if ev:
                ev_name = ev.get("event", "")
                ev_data = ev.get("data", {})

                if ev_name == "approval.request":
                    result["approval_required"] = True
                    result["approval"] = {
                        "id": ev_data.get("pattern_key", ev_data.get("id", "")),
                        "command": ev_data.get("command", ""),
                        "description": ev_data.get("description", ""),
                    }
                    result["hint"] = "Use hermes_approval_respond to approve, then call hermes_messages_stream."
                    return json.dumps(result, indent=2, ensure_ascii=False)

                elif ev_name == "message.complete":
                    result["response"] = ev_data.get("text", "")
                    result["usage"] = ev_data.get("usage", {})
                    return json.dumps(result, indent=2, ensure_ascii=False)

                elif ev_name == "tool.complete":
                    result["tool_calls"] = result.get("tool_calls", [])
                    result["tool_calls"].append({
                        "name": ev_data.get("name", ""),
                        "output": ev_data.get("result", {}).get("output", "")[:500],
                    })

                elif ev_name in ("response.error", "background.error"):
                    result["error"] = ev_data.get("message", "Unknown error")
                    return json.dumps(result, indent=2, ensure_ascii=False)

        # Timeout
        result["hint"] = "Timed out. Use hermes_messages_stream for results."
        return json.dumps(result, indent=2, ensure_ascii=False)

    @mcp.tool()
    async def hermes_prompt_background(prompt: str) -> str:
        """Submit a prompt without waiting for completion (fire-and-forget).

        Use hermes_messages_stream afterward to poll for results as they come in.
        This is the recommended way for long-running tasks.

        Args:
            prompt: The prompt text to send
        """
        if not bridge.session_id:
            r = await bridge.call("session.create", {"title": "mcp-bg"}, timeout=15)
            if "result" in r:
                bridge.session_id = r["result"].get("session_id", "")
                bridge._save_session_id(r["result"].get("stored_session_id", bridge.session_id))

        bridge.clear_events()

        try:
            r = await bridge.call("prompt.background", {
                "session_id": bridge.session_id,
                "text": prompt,
            }, timeout=30)
        except TimeoutError:
            return json.dumps({
                "ok": True,
                "session_id": bridge.session_id,
                "hint": "Submit timed out but task may have started. Use hermes_messages_stream.",
            }, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

        if "error" in r:
            return json.dumps({"error": r["error"]}, indent=2)

        return json.dumps({
            "ok": True,
            "session_id": bridge.session_id,
            "hint": "Use hermes_messages_stream to poll for results.",
        }, indent=2)

    @mcp.tool()
    async def hermes_prompt_stream(prompt: str) -> str:
        """Submit a prompt and enable event streaming (non-blocking).

        Unlike hermes_prompt_background (fire-and-forget), this keeps the
        event buffer intact so hermes_messages_stream can read tool calls,
        message chunks, and completion events in real-time.

        Workflow:
            1. hermes_prompt_stream("do something")  → returns immediately
            2. loop: hermes_messages_stream(timeout=5) → returns one event per call
            3. break when event == "completed" or "error"

        Args:
            prompt: The prompt text to send
        """
        if not bridge.session_id:
            r = await bridge.call("session.create", {"title": "mcp-stream"}, timeout=15)
            if "result" in r:
                bridge.session_id = r["result"].get("session_id", "")
                bridge._save_session_id(r["result"].get("stored_session_id", bridge.session_id))

        # Do NOT clear events — let them accumulate for streaming
        try:
            r = await bridge.call("prompt.submit", {
                "session_id": bridge.session_id,
                "text": prompt,
            }, timeout=30)
        except TimeoutError:
            return json.dumps({
                "ok": True,
                "session_id": bridge.session_id,
                "hint": "Submit timed out but task may have started. Use hermes_messages_stream.",
            }, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

        if "error" in r:
            return json.dumps({"error": r["error"]}, indent=2)

        return json.dumps({
            "ok": True,
            "session_id": bridge.session_id,
            "hint": "Use hermes_messages_stream to read events one by one.",
        }, indent=2)

    @mcp.tool()
    async def hermes_session_interrupt() -> str:
        """Interrupt the currently running prompt in the active session."""
        if not bridge.session_id:
            return json.dumps({"error": "No active session."})
        try:
            r = await bridge.call("session.interrupt", {"session_id": bridge.session_id}, timeout=10)
            return json.dumps({"ok": True, "message": "Interrupt signal sent"}, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)
