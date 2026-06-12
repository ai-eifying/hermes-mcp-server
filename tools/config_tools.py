"""Config MCP tools."""

from __future__ import annotations

import json
from config import SHORT_RPC_TIMEOUT


def register_config_tools(mcp, bridge):

    @mcp.tool()
    async def hermes_config_get(path: str = "") -> str:
        """Get Hermes configuration. Returns full config or a specific key path.

        Args:
            path: Optional dot-separated config path (e.g. "models.default", "platforms.telegram")
        """
        params = {}
        if path:
            params["path"] = path
        try:
            r = await bridge.call("config.get", params, timeout=SHORT_RPC_TIMEOUT)
            if "result" in r:
                return json.dumps(r["result"], indent=2, ensure_ascii=False)
            return json.dumps({"error": r.get("error", "Failed")}, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @mcp.tool()
    async def hermes_config_set(path: str, value: str) -> str:
        """Set a Hermes configuration value.

        Args:
            path: Dot-separated config path (e.g. "models.default")
            value: New value (will be parsed as JSON if possible, otherwise string)
        """
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            parsed = value

        try:
            r = await bridge.call("config.set", {"path": path, "value": parsed}, timeout=SHORT_RPC_TIMEOUT)
            if "result" in r:
                return json.dumps({"ok": True, "path": path, "value": parsed}, indent=2)
            return json.dumps({"error": r.get("error", "Failed")}, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @mcp.tool()
    async def hermes_health() -> str:
        """Check Hermes Agent health — connection status, session, model info."""
        result = {
            "ws_connected": bridge.connected,
            "session_id": bridge.session_id,
        }

        if bridge.connected:
            try:
                r = await bridge.call("session.status", {"session_id": bridge.session_id}, timeout=10)
                if "result" in r:
                    result["session"] = r["result"]
            except Exception:
                pass

            try:
                r = await bridge.call("setup.status", {}, timeout=10)
                if "result" in r:
                    result["setup"] = r["result"]
            except Exception:
                pass

        return json.dumps(result, indent=2, ensure_ascii=False)
