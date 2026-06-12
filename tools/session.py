"""Session management MCP tools."""

from __future__ import annotations

import json
import sys
from config import SHORT_RPC_TIMEOUT, DEFAULT_RPC_TIMEOUT

# ws_bridge module imported at runtime by server.py
# We receive bridge via register function


def register_session_tools(mcp, bridge):
    """Register 6 session management tools."""

    @mcp.tool()
    async def hermes_session_create(title: str = "") -> str:
        """Create a new conversation session in Hermes Agent.

        Args:
            title: Optional session title/label
        """
        r = await bridge.call("session.create", {"title": title or "mcp-client"}, timeout=SHORT_RPC_TIMEOUT)
        if "result" in r:
            result = r["result"]
            # TUI Gateway returns both short_id and stored_session_id
            # Use the short_id for subsequent WS RPC calls
            bridge.session_id = result.get("session_id", "")
            bridge._save_session_id(result.get("stored_session_id", bridge.session_id))
            return json.dumps(result, indent=2, ensure_ascii=False)
        return json.dumps({"error": r.get("error", "Unknown error")}, indent=2)

    @mcp.tool()
    async def hermes_session_list() -> str:
        """List all Hermes Agent sessions with metadata (id, title, updated_at, tokens)."""
        r = await bridge.call("session.list", {}, timeout=SHORT_RPC_TIMEOUT)
        if "result" in r:
            return json.dumps(r["result"], indent=2, ensure_ascii=False)
        return json.dumps({"error": r.get("error", "Unknown error")}, indent=2)

    @mcp.tool()
    async def hermes_session_resume(session_id: str) -> str:
        """Switch to an existing session by ID. Subsequent prompts go to this session.

        Args:
            session_id: The session ID to resume (short or stored)
        """
        r = await bridge.call("session.resume", {"session_id": session_id}, timeout=SHORT_RPC_TIMEOUT)
        if "result" in r:
            result = r["result"]
            # Use the short session_id from the resume result
            bridge.session_id = result.get("session_id", session_id)
            bridge._save_session_id(result.get("stored_session_id", session_id))
            return json.dumps(result, indent=2, ensure_ascii=False)
        return json.dumps({"error": r.get("error", "Resume failed")}, indent=2)

    @mcp.tool()
    async def hermes_session_status(session_id: str = "") -> str:
        """Get current session status (running, idle, model, iteration count, etc.).

        Args:
            session_id: Target session (empty = current)
        """
        sid = session_id or bridge.session_id
        if not sid:
            return json.dumps({"error": "No session. Use hermes_session_create first."})
        r = await bridge.call("session.status", {"session_id": sid}, timeout=SHORT_RPC_TIMEOUT)
        if "result" in r:
            return json.dumps(r["result"], indent=2, ensure_ascii=False)
        return json.dumps({"error": r.get("error", "Unknown error")}, indent=2)

    @mcp.tool()
    async def hermes_session_history(session_id: str = "", limit: int = 50) -> str:
        """Read session's message history.

        Args:
            session_id: Target session (empty = current)
            limit: Max messages to return (default 50)
        """
        sid = session_id or bridge.session_id
        if not sid:
            return json.dumps({"error": "No session. Use hermes_session_create first."})
        r = await bridge.call("session.history", {"session_id": sid, "limit": limit}, timeout=SHORT_RPC_TIMEOUT)
        if "result" in r:
            return json.dumps(r["result"], indent=2, ensure_ascii=False)
        return json.dumps({"error": r.get("error", "Unknown error")}, indent=2)

    @mcp.tool()
    async def hermes_session_delete(session_id: str) -> str:
        """Delete a session permanently.

        Args:
            session_id: The session to delete
        """
        r = await bridge.call("session.delete", {"session_id": session_id}, timeout=SHORT_RPC_TIMEOUT)
        if bridge.session_id == session_id:
            bridge.session_id = ""
        return json.dumps({"ok": True, "deleted": session_id}, indent=2)
