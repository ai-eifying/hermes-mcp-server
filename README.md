# Hermes Agent MCP Server

Full Hermes Agent control via MCP protocol. 29 tools covering sessions, prompts, messaging, approvals, CLI, config, models, and skills.

## Quick Start

```bash
# Install dependencies
pip install mcp websockets aiohttp

# Test (stdio mode)
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}
{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | python3 ~/.hermes/tmp/hermes-mcp-server/server.py
```

## MCP Client Configuration

### Claude Code / Cursor / Codex (stdio)

```json
{
  "mcpServers": {
    "hermes-agent": {
      "command": "python3",
      "args": ["~/.hermes/tmp/hermes-mcp-server/server.py"]
    }
  }
}
```

### Remote (HTTP/SSE)

```bash
# Start server in HTTP mode
python3 ~/.hermes/tmp/hermes-mcp-server/server.py --transport http --port 9221
```

```json
{
  "mcpServers": {
    "hermes-agent": {
      "type": "http",
      "url": "http://localhost:9221/mcp"
    }
  }
}
```

## Architecture

```
MCP Client (Claude Code, Cursor, etc.)
    │ MCP protocol (stdio or HTTP)
    ▼
hermes-mcp-server (this)
    │ WS JSON-RPC (no local DB)
    ▼
Hermes Dashboard (ws://localhost:9119)
    │
    ▼
Hermes Agent (run_agent.py)
```

## Files

```
~/.hermes/tmp/hermes-mcp-server/
├── server.py          # Entry point
├── config.py          # Constants
├── ws_bridge.py       # WS connection + RPC + ReadCursor
├── tools/
│   ├── __init__.py
│   ├── session.py     # 6 session tools
│   ├── prompt.py      # 4 prompt tools
│   ├── messaging.py   # 8 messaging + streaming + event tools
│   ├── approval.py    # 2 approval tools
│   ├── cli.py         # 3 CLI tools
│   ├── config_tools.py # 3 config tools
│   └── model.py       # 2 model tools
└── README.md
```

## Requirements

- Python 3.11+
- `mcp` package
- `websockets` package
- Hermes Agent running with Dashboard enabled (`hermes dashboard --tui --port 9119`)
