"""Model management MCP tools."""

from __future__ import annotations

import json
from config import SHORT_RPC_TIMEOUT


def register_model_tools(mcp, bridge):

    @mcp.tool()
    async def hermes_model_options() -> str:
        """List available models and providers."""
        try:
            r = await bridge.call("model.options", {}, timeout=SHORT_RPC_TIMEOUT)
            if "result" in r:
                return json.dumps(r["result"], indent=2, ensure_ascii=False)
            return json.dumps({"error": r.get("error", "Failed")}, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @mcp.tool()
    async def hermes_model_disconnect() -> str:
        """Disconnect the current model (allows switching)."""
        try:
            r = await bridge.call("model.disconnect", {}, timeout=SHORT_RPC_TIMEOUT)
            return json.dumps({"ok": True}, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)
