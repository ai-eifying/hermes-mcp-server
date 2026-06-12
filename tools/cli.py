"""CLI / Slash command MCP tools."""

from __future__ import annotations

import json
from config import DEFAULT_RPC_TIMEOUT


def register_cli_tools(mcp, bridge):

    @mcp.tool()
    async def hermes_slash_exec(command: str) -> str:
        """Execute a Hermes slash command.

        Available commands:
            /model <name>    — Switch model
            /reset           — Reset session
            /compact         — Compress context
            /undo            — Undo last exchange
            /save            — Save session
            /close           — Close session
            /branch          — Branch session
            /usage           — Show token usage
            /status          — Show status
            /config          — Show config
            /reload          — Reload plugins/MCP
            /plugins         — List plugins
            /cron            — Cron jobs
            /steer <text>    — Steer agent direction
            /interrupt       — Interrupt running task

        Args:
            command: The slash command (with or without leading /)
        """
        if not command.startswith("/"):
            command = "/" + command

        try:
            r = await bridge.call("slash.exec", {
                "session_id": bridge.session_id,
                "command": command,
            }, timeout=DEFAULT_RPC_TIMEOUT)
            if "result" in r:
                return json.dumps(r["result"], indent=2, ensure_ascii=False)
            return json.dumps({"error": r.get("error", "Command failed")}, indent=2)
        except TimeoutError:
            return json.dumps({"error": f"Command timed out: {command}"}, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @mcp.tool()
    async def hermes_cli_exec(command: str) -> str:
        """Execute a Hermes CLI command (same as 'hermes <command>' in terminal).

        Args:
            command: The CLI command to execute
        """
        try:
            r = await bridge.call("cli.exec", {"command": command}, timeout=DEFAULT_RPC_TIMEOUT)
            if "result" in r:
                return json.dumps(r["result"], indent=2, ensure_ascii=False)
            return json.dumps({"error": r.get("error", "Command failed")}, indent=2)
        except TimeoutError:
            return json.dumps({"error": f"Command timed out: {command}"}, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @mcp.tool()
    async def hermes_commands_catalog() -> str:
        """List all available slash commands with descriptions."""
        try:
            r = await bridge.call("commands.catalog", {}, timeout=15)
            if "result" in r:
                return json.dumps(r["result"], indent=2, ensure_ascii=False)
            return json.dumps({"error": r.get("error", "Failed")}, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)
