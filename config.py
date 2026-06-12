"""Configuration constants for hermes-mcp-server."""

import os
from pathlib import Path

DASHBOARD_WS_URL = "ws://localhost:9119/api/ws"
DASHBOARD_HTTP_URL = "http://localhost:9119"

# WS connection
WS_MAX_SIZE = 10 * 1024 * 1024  # 10MB
WS_OPEN_TIMEOUT = 10
WS_RECONNECT_DELAY = 3
WS_MAX_RECONNECT_DELAY = 30

# RPC
DEFAULT_RPC_TIMEOUT = 300  # seconds
SHORT_RPC_TIMEOUT = 15
LONG_RPC_TIMEOUT = 600

# Stream
STREAM_POLL_INTERVAL = 0.2  # seconds
STREAM_DEFAULT_TIMEOUT = 60
STREAM_MAX_TIMEOUT = 300

# Messages
DEFAULT_MSG_LIMIT = 50
MAX_MSG_LIMIT = 200

# Session file
STATE_FILE = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")) / "tmp" / ".hermes-mcp-session"
