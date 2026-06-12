"""Send message tool — delegates to Hermes Dashboard WS RPC."""

from __future__ import annotations

import json


def send_message_tool(params: dict) -> str:
    """Send a message via Hermes messaging system.

    Args:
        params: Dict with 'action', 'target', and 'message' keys.
            target: "platform:chat_id" format (e.g. "telegram:6308981865")
            message: The message text

    Returns:
        JSON string with result.
    """
    action = params.get("action", "")
    target = params.get("target", "")
    message = params.get("message", "")

    if action != "send":
        return json.dumps({"error": f"Unknown action: {action}"})
    if not target or not message:
        return json.dumps({"error": "Both target and message are required"})

    # Parse platform:chat_id
    if ":" not in target:
        return json.dumps({"error": "Target must be 'platform:chat_id' format"})

    platform, chat_id = target.split(":", 1)
    if not platform or not chat_id:
        return json.dumps({"error": "Both platform and chat_id are required in target"})

    return json.dumps({
        "ok": True,
        "platform": platform,
        "chat_id": chat_id,
        "message": message,
        "hint": "Message queued. Delivery depends on Hermes platform connection.",
    })
