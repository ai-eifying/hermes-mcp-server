"""Approval MCP tools."""

from __future__ import annotations

import json
from config import SHORT_RPC_TIMEOUT


def register_approval_tools(mcp, bridge):

    @mcp.tool()
    async def hermes_approval_respond(approval_id: str, decision: str) -> str:
        """Respond to a pending approval request.

        Args:
            approval_id: The approval ID from events
            decision: One of "approve", "deny"
        """
        if decision not in ("approve", "deny"):
            return json.dumps({"error": f"Invalid decision: {decision}. Use 'approve' or 'deny'."})

        try:
            r = await bridge.call("approval.respond", {
                "session_id": bridge.session_id,
                "approval_id": approval_id,
                "choice": decision,
            }, timeout=SHORT_RPC_TIMEOUT)
            if "result" in r:
                return json.dumps({"ok": True, "approval_id": approval_id, "decision": decision}, indent=2)
            return json.dumps({"error": r.get("error", "Failed")}, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @mcp.tool()
    async def hermes_permissions_list() -> str:
        """List pending approval requests from buffered events."""
        events = await bridge.collect_events()
        approvals = []
        for ev in events:
            if ev.get("event") == "approval.request":
                data = ev.get("data", {})
                approvals.append({
                    "id": data.get("pattern_key", data.get("id", "")),
                    "type": data.get("type", ""),
                    "description": data.get("description", ""),
                    "command": data.get("command", ""),
                })
        return json.dumps({"count": len(approvals), "approvals": approvals}, indent=2)
