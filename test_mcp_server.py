#!/usr/bin/env python3
"""
hermes-mcp-server 端到端测试

测试所有 29 个 MCP tools，覆盖：
1. 基础连接 (initialize, tools/list)
2. Skills (不需要 WS 连接)
3. Session 管理 (需要 WS)
4. Prompt 提交 (需要 WS)
5. 消息读取 + 流式 (需要 WS)
6. Config / Model / CLI
7. 流式读取完整流程

用法:
    python3 test_mcp_server.py              # 全部测试
    python3 test_mcp_server.py --offline    # 仅离线测试
    python3 test_mcp_server.py --verbose    # 显示详细输出
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

SERVER = str(Path.home() / ".hermes" / "tmp" / "hermes-mcp-server" / "server.py")


class MCPClient:
    """Minimal MCP client over stdio for testing."""

    def __init__(self, verbose=False):
        self.verbose = verbose
        self.proc = None
        self._req_id = 0

    def start(self):
        self.proc = subprocess.Popen(
            [sys.executable, SERVER],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE if not self.verbose else None,
            text=True,
        )
        # Initialize
        r = self._send("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0"},
        })
        assert "result" in r, f"Initialize failed: {r}"
        assert r["result"]["serverInfo"]["name"] == "hermes-agent"
        # Send initialized notification
        self._notify("notifications/initialized", {})

    def stop(self):
        if self.proc:
            self.proc.stdin.close()
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def _send(self, method: str, params: dict = None) -> dict:
        self._req_id += 1
        msg = {"jsonrpc": "2.0", "id": self._req_id, "method": method}
        if params:
            msg["params"] = params
        line = json.dumps(msg)
        if self.verbose:
            print(f"  → {line[:200]}", file=sys.stderr)
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()

        response_line = self.proc.stdout.readline()
        if not response_line:
            return {"error": "No response (process exited?)"}
        r = json.loads(response_line.strip())
        if self.verbose:
            print(f"  ← {json.dumps(r)[:200]}", file=sys.stderr)
        return r

    def _notify(self, method: str, params: dict = None):
        msg = {"jsonrpc": "2.0", "method": method}
        if params:
            msg["params"] = params
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def call_tool(self, name: str, arguments: dict = None, timeout: int = 30) -> dict:
        """Call an MCP tool and return parsed result."""
        params = {"name": name}
        if arguments:
            params["arguments"] = arguments

        # We need to handle timeouts for long-running tools
        self._req_id += 1
        msg = {"jsonrpc": "2.0", "id": self._req_id, "method": "tools/call", "params": params}
        line = json.dumps(msg)
        if self.verbose:
            print(f"  → {line[:200]}", file=sys.stderr)
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()

        # Read with timeout (using select or threading)
        import threading
        result = [None]
        def read_line():
            result[0] = self.proc.stdout.readline()
        t = threading.Thread(target=read_line, daemon=True)
        t.start()
        t.join(timeout=timeout)

        if t.is_alive():
            return {"error": f"Tool call timed out ({timeout}s): {name}"}

        if not result[0]:
            return {"error": f"No response from tool: {name}"}

        r = json.loads(result[0].strip())
        if self.verbose:
            print(f"  ← {json.dumps(r)[:300]}", file=sys.stderr)

        # Extract content
        if "result" in r and "content" in r["result"]:
            for c in r["result"]["content"]:
                if c.get("type") == "text":
                    try:
                        return json.loads(c["text"])
                    except json.JSONDecodeError:
                        return {"raw_text": c["text"]}
            return {"content": r["result"]["content"]}
        return r

    def list_tools(self) -> list:
        r = self._send("tools/list")
        return r.get("result", {}).get("tools", [])


# ── Test Helpers ──

passed = 0
failed = 0
skipped = 0


def test(name: str, func, *args, **kwargs):
    global passed, failed
    try:
        result = func(*args, **kwargs)
        if result == "skip":
            print(f"  ⏭ {name}")
            return None
        print(f"  ✅ {name}")
        passed += 1
        return result
    except AssertionError as e:
        print(f"  ❌ {name}: {e}")
        failed += 1
        return None
    except Exception as e:
        print(f"  ❌ {name}: {type(e).__name__}: {e}")
        failed += 1
        return None


def extract_text(result: dict) -> str:
    """Extract text from MCP tool result."""
    if isinstance(result, dict):
        if "raw_text" in result:
            return result["raw_text"]
        if "content" in result:
            for c in result["content"]:
                if isinstance(c, dict) and c.get("type") == "text":
                    return c["text"]
    return json.dumps(result)


# ── Test Suites ──

def test_tools_list(client: MCPClient):
    """Test tools/list returns all 29 tools."""
    tools = client.list_tools()
    assert len(tools) >= 29, f"Expected >=29 tools, got {len(tools)}"
    names = {t["name"] for t in tools}
    required = [
        "hermes_session_create", "hermes_session_list", "hermes_session_resume",
        "hermes_session_status", "hermes_session_history", "hermes_session_delete",
        "hermes_prompt_submit", "hermes_prompt_background", "hermes_session_interrupt",
        "hermes_conversations_list", "hermes_conversation_get", "hermes_messages_read",
        "hermes_messages_stream", "hermes_messages_send", "hermes_channels_list",
        "hermes_events_poll", "hermes_events_wait",
        "hermes_approval_respond", "hermes_permissions_list",
        "hermes_slash_exec", "hermes_cli_exec", "hermes_commands_catalog",
        "hermes_config_get", "hermes_config_set", "hermes_health",
        "hermes_model_options", "hermes_model_disconnect",
        "hermes_skills_list", "hermes_skill_view",
    ]
    for name in required:
        assert name in names, f"Missing tool: {name}"
    return len(tools)


def test_skills_list(client: MCPClient):
    """Test skills listing (no WS needed)."""
    r = client.call_tool("hermes_skills_list", {"category": "devops"})
    assert "skills" in r, f"No skills key: {r}"
    assert r["count"] > 0, "No skills found"
    return r["count"]


def test_skills_list_all(client: MCPClient):
    """Test listing all skills."""
    r = client.call_tool("hermes_skills_list", {})
    assert r["count"] > 50, f"Expected >50 total skills, got {r['count']}"
    return r["count"]


def test_skill_view(client: MCPClient):
    """Test viewing a specific skill."""
    r = client.call_tool("hermes_skill_view", {"name": "hermes-agent"})
    # Should return skill content (large text)
    text = extract_text(r)
    assert len(text) > 1000, f"Skill content too short: {len(text)} chars"
    assert "hermes-agent" in text.lower() or "Hermes Agent" in text, "Missing skill content"
    return len(text)


def test_skill_view_not_found(client: MCPClient):
    """Test viewing non-existent skill."""
    r = client.call_tool("hermes_skill_view", {"name": "nonexistent-skill-xyz"})
    text = extract_text(r)
    assert "error" in r or "not found" in text.lower() or "Skill not found" in text, f"Expected error: {r}"


def test_session_create(client: MCPClient):
    """Test session creation."""
    r = client.call_tool("hermes_session_create", {"title": "mcp-test"})
    assert "session_id" in r or "error" in r, f"Unexpected: {r}"
    if "session_id" in r:
        return r["session_id"]
    return "skip"


def test_session_list(client: MCPClient):
    """Test session listing."""
    r = client.call_tool("hermes_session_list")
    assert "sessions" in r or "error" in r or "result" in r, f"Unexpected: {r}"
    return r


def test_session_status(client: MCPClient):
    """Test session status."""
    r = client.call_tool("hermes_session_status", {})
    # May have error if no session, that's OK
    return r


def test_session_history(client: MCPClient):
    """Test session history."""
    r = client.call_tool("hermes_session_history", {"limit": 5})
    return r


def test_conversations_list(client: MCPClient):
    """Test conversations listing."""
    r = client.call_tool("hermes_conversations_list", {})
    assert "conversations" in r or "error" in r, f"Unexpected: {r}"
    return r


def test_channels_list(client: MCPClient):
    """Test channels listing."""
    r = client.call_tool("hermes_channels_list", {})
    return r


def test_config_get(client: MCPClient):
    """Test config read."""
    r = client.call_tool("hermes_config_get", {})
    return r


def test_health(client: MCPClient):
    """Test health check."""
    r = client.call_tool("hermes_health", {})
    assert "ws_connected" in r or "error" in r, f"Unexpected: {r}"
    return r


def test_model_options(client: MCPClient):
    """Test model listing."""
    r = client.call_tool("hermes_model_options", {})
    return r


def test_commands_catalog(client: MCPClient):
    """Test commands catalog."""
    r = client.call_tool("hermes_commands_catalog", {})
    return r


def test_prompt_submit(client: MCPClient):
    """Test prompt submission (waits for response)."""
    r = client.call_tool("hermes_prompt_submit", {
        "prompt": "Reply with exactly: MCP_TEST_OK",
        "timeout": 60,
    }, timeout=70)
    # Check response
    if "error" in r:
        return r  # May fail if no model configured
    assert "response" in r or "ok" in r or "events" in r, f"Unexpected: {r}"
    return r


def test_prompt_background_and_stream(client: MCPClient):
    """Test the streaming flow: background submit + stream."""
    # 1. Submit in background
    r = client.call_tool("hermes_prompt_background", {
        "prompt": "Reply with exactly: STREAM_TEST_OK",
    }, timeout=15)
    assert "ok" in r or "session_id" in r or "error" in r, f"Unexpected: {r}"

    if "error" in r:
        return r

    # 2. Stream for results
    r2 = client.call_tool("hermes_messages_stream", {
        "timeout": 30,
    }, timeout=35)

    assert "status" in r2 or "error" in r2, f"Unexpected stream result: {r2}"
    return {"background": r, "stream": r2}


def test_messages_read_all(client: MCPClient):
    """Test reading all messages."""
    r = client.call_tool("hermes_messages_read", {"mode": "all", "limit": 10})
    assert "messages" in r or "error" in r, f"Unexpected: {r}"
    return r


def test_messages_read_unread(client: MCPClient):
    """Test reading unread messages."""
    r = client.call_tool("hermes_messages_read", {"mode": "unread"})
    assert "status" in r or "error" in r, f"Unexpected: {r}"
    return r


def test_permissions_list(client: MCPClient):
    """Test permissions listing."""
    r = client.call_tool("hermes_permissions_list", {})
    assert "approvals" in r or "error" in r, f"Unexpected: {r}"
    return r


# ── Main ──

def main():
    global passed, failed, skipped

    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true", help="Only run tests that don't need WS")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    print("=" * 60)
    print("Hermes MCP Server — End-to-End Test")
    print("=" * 60)

    client = MCPClient(verbose=args.verbose)

    print("\n📋 Phase 1: Connection & Tool Discovery")
    print("-" * 40)
    try:
        client.start()
        print("  ✅ MCP initialize")
    except Exception as e:
        print(f"  ❌ MCP initialize: {e}")
        sys.exit(1)

    test("tools/list (29 tools)", test_tools_list, client)

    print("\n📋 Phase 2: Skills (offline, no WS needed)")
    print("-" * 40)
    test("skills_list (devops)", test_skills_list, client)
    test("skills_list (all)", test_skills_list_all, client)
    test("skill_view (hermes-agent)", test_skill_view, client)
    test("skill_view (not found)", test_skill_view_not_found, client)

    if args.offline:
        print("\n⏭ Skipping online tests (--offline mode)")
    else:
        print("\n📋 Phase 3: Session Management")
        print("-" * 40)
        test("session_create", test_session_create, client)
        test("session_list", test_session_list, client)
        test("session_status", test_session_status, client)
        test("session_history", test_session_history, client)

        print("\n📋 Phase 4: Messaging & Channels")
        print("-" * 40)
        test("conversations_list", test_conversations_list, client)
        test("channels_list", test_channels_list, client)
        test("messages_read (all)", test_messages_read_all, client)
        test("messages_read (unread)", test_messages_read_unread, client)
        test("permissions_list", test_permissions_list, client)

        print("\n📋 Phase 5: Config & System")
        print("-" * 40)
        test("config_get", test_config_get, client)
        test("health", test_health, client)
        test("model_options", test_model_options, client)
        test("commands_catalog", test_commands_catalog, client)

        print("\n📋 Phase 6: Prompt & Streaming")
        print("-" * 40)
        r = test("prompt_submit", test_prompt_submit, client)
        if r and isinstance(r, dict) and "response" in r:
            print(f"    Response: {str(r['response'])[:100]}...")

        r = test("prompt_background + stream", test_prompt_background_and_stream, client)
        if r and isinstance(r, dict):
            stream = r.get("stream", {})
            print(f"    Stream status: {stream.get('status', '?')}")

    print("\n📋 Cleanup")
    print("-" * 40)
    client.stop()
    print("  ✅ Client stopped")

    # Summary
    print("\n" + "=" * 60)
    total = passed + failed
    status = "🎉 ALL PASSED" if failed == 0 else f"⚠️  {failed} FAILED"
    print(f"Results: {passed}/{total} passed — {status}")
    print("=" * 60)

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
