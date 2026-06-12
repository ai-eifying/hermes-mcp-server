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
      "url": "http://localhost:9221/mcp"
    }
  }
}
```

## Tools (29)

### Session Management (6)
| Tool | Description |
|------|-------------|
| `hermes_session_create` | Create new session |
| `hermes_session_list` | List all sessions |
| `hermes_session_resume` | Switch to session |
| `hermes_session_status` | Get session status |
| `hermes_session_history` | Read message history |
| `hermes_session_delete` | Delete session |

### Prompt / Chat (3)
| Tool | Description |
|------|-------------|
| `hermes_prompt_submit` | Send prompt, wait for response |
| `hermes_prompt_background` | Send prompt, don't wait (fire-and-forget) |
| `hermes_session_interrupt` | Interrupt running prompt |

### Messaging + Streaming (9)
| Tool | Description |
|------|-------------|
| `hermes_conversations_list` | List cross-platform conversations |
| `hermes_conversation_get` | Get conversation details |
| `hermes_messages_read` | Read messages (`mode=all` or `mode=unread`) |
| `hermes_messages_stream` | Long-poll for new messages (streaming) |
| `hermes_messages_send` | Send message to platform |
| `hermes_channels_list` | List available channels |
| `hermes_events_poll` | Poll raw events |
| `hermes_events_wait` | Long-poll raw events |

### Streaming Example

```python
# Submit task without waiting
hermes_prompt_background("Analyze this codebase...")

# Stream results
while True:
    result = hermes_messages_stream(timeout=30)
    # result.status: "messages" | "completed" | "running" | "timeout"
    
    if result["status"] == "messages":
        for msg in result["messages"]:
            print(msg["content"])
    elif result["status"] == "completed":
        break
    elif result["status"] == "running":
        continue  # Still running, poll again
    else:
        break  # Timeout
```

### Read Cursor Tracking

Each session maintains a read cursor for unread message tracking:

- `hermes_messages_read(mode="all")` — All messages, cursor unchanged
- `hermes_messages_read(mode="unread")` — Messages after cursor, cursor advances
- `hermes_messages_stream()` — Wait for new messages, auto-advances cursor

### Approval (2)
| Tool | Description |
|------|-------------|
| `hermes_approval_respond` | Respond to approval (approve/deny) |
| `hermes_permissions_list` | List pending approvals |

### CLI / Commands (3)
| Tool | Description |
|------|-------------|
| `hermes_slash_exec` | Execute slash command (/model, /reset, etc.) |
| `hermes_cli_exec` | Execute CLI command |
| `hermes_commands_catalog` | List available commands |

### Config (3)
| Tool | Description |
|------|-------------|
| `hermes_config_get` | Get config value |
| `hermes_config_set` | Set config value |
| `hermes_health` | Health check |

### Model (2)
| Tool | Description |
|------|-------------|
| `hermes_model_options` | List models/providers |
| `hermes_model_disconnect` | Disconnect model |

### Skills (2)
| Tool | Description |
|------|-------------|
| `hermes_skills_list` | List installed skills |
| `hermes_skill_view` | View skill SKILL.md |

## Architecture

```
MCP Client (Claude Code, Cursor, etc.)
    │ MCP protocol (stdio or HTTP)
    ▼
hermes-mcp-server (this)
    │ WS JSON-RPC + SQLite direct read
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
├── db_reader.py       # SessionDB direct reader
├── tools/
│   ├── __init__.py
│   ├── session.py     # 6 session tools
│   ├── prompt.py      # 3 prompt tools
│   ├── messaging.py   # 8 messaging + streaming tools
│   ├── approval.py    # 2 approval tools
│   ├── cli.py         # 3 CLI tools
│   ├── config_tools.py # 3 config tools
│   ├── model.py       # 2 model tools
│   └── skills.py      # 2 skill tools
└── README.md
```

## Requirements

- Python 3.11+
- `mcp` package
- `websockets` package
- Hermes Agent running with Dashboard enabled (`hermes dashboard --tui --port 9119`)
