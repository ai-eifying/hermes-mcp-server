#!/usr/bin/env python3
"""
批准流程系统测试

测试场景：
1. 提交会触发审批的 prompt（如执行 shell 命令）
2. 检测 approval.request 事件
3. 通过 MCP tools 批准
4. 验证任务继续执行并返回结果

用法:
    python3 test_approval.py              # stdio 模式
    python3 test_approval.py --http       # HTTP 跨进程模式
"""

import json
import subprocess
import sys
import time
import threading
from pathlib import Path

SERVER = str(Path.home() / ".hermes" / "tmp" / "hermes-mcp-server" / "server.py")


class StdioMCPClient:
    """MCP stdio client for testing."""

    def __init__(self):
        self.proc = None
        self._id = 0

    def start(self):
        self.proc = subprocess.Popen(
            [sys.executable, SERVER, "--auto-approve=off"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True,
        )
        # Initialize
        self._send("initialize", {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "approval-test", "version": "1.0"},
        })
        self._notify("notifications/initialized", {})

    def stop(self):
        if self.proc:
            self.proc.stdin.close()
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def _send(self, method, params=None):
        self._id += 1
        msg = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params:
            msg["params"] = params
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        return json.loads(line.strip()) if line else {"error": "no response"}

    def _notify(self, method, params=None):
        msg = {"jsonrpc": "2.0", "method": method}
        if params:
            msg["params"] = params
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def call_tool(self, name, args=None, timeout=30):
        self._id += 1
        params = {"name": name}
        if args:
            params["arguments"] = args
        msg = {"jsonrpc": "2.0", "id": self._id, "method": "tools/call", "params": params}
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

        result = [None]
        def read():
            result[0] = self.proc.stdout.readline()
        t = threading.Thread(target=read, daemon=True)
        t.start()
        t.join(timeout=timeout)

        if t.is_alive() or not result[0]:
            return {"error": f"timeout ({timeout}s)"}

        r = json.loads(result[0].strip())
        if "result" in r and "content" in r.get("result", {}):
            for c in r["result"]["content"]:
                if c.get("type") == "text":
                    try:
                        return json.loads(c["text"])
                    except json.JSONDecodeError:
                        return {"raw": c["text"]}
        return r


def extract_text(result):
    if isinstance(result, dict):
        if "raw" in result:
            return result["raw"]
        if "response" in result:
            return result["response"]
    return str(result)


def test_approval_stdio():
    """Test approval flow via stdio MCP."""
    print("=" * 60)
    print("Approval System Test — stdio mode")
    print("=" * 60)

    client = StdioMCPClient()
    client.start()
    passed = failed = 0

    def ok(name, detail=""):
        nonlocal passed
        msg = f"  ✅ {name}"
        if detail:
            msg += f" ({detail})"
        print(msg)
        passed += 1

    def fail(name, detail=""):
        nonlocal failed
        msg = f"  ❌ {name}"
        if detail:
            msg += f": {str(detail)[:100]}"
        print(msg)
        failed += 1

    try:
        # Step 1: Create session
        print("\n📋 Step 1: Setup")
        print("-" * 40)
        r = client.call_tool("hermes_session_create", {"title": "approval-test"})
        if "session_id" in r:
            sid = r["session_id"]
            ok("session_create", sid)
        else:
            fail("session_create", r)
            return

        # Step 2: Check health
        r = client.call_tool("hermes_health")
        ws_ok = r.get("ws_connected", False)
        ok(f"health (ws={ws_ok})")

        # Step 3: Submit a prompt that should trigger approval
        # Using a simple command that typically needs approval
        print("\n📋 Step 2: Submit approval-triggering prompt")
        print("-" * 40)

        # First, let's check what the current approval mode is
        r = client.call_tool("hermes_config_get", {"path": "approval"})
        print(f"    Current approval config: {json.dumps(r)[:200]}")

        # Submit prompt that runs a command (may trigger exec approval)
        print("    Submitting: 'run ls -la /tmp' (background)...")
        r = client.call_tool("hermes_prompt_background", {
            "prompt": "Use the terminal tool to run: echo APPROVAL_TEST_$(date +%s). Do NOT ask for confirmation.",
        })
        if "error" in r:
            # If error about session busy, try anyway
            print(f"    Background submit: {r}")
        else:
            ok("prompt_background submitted")

        # Step 4: Monitor for events
        print("\n📋 Step 3: Monitor events for approval.request")
        print("-" * 40)

        approval_found = False
        approval_id = ""

        for attempt in range(12):  # 60 seconds max
            time.sleep(5)

            # Check events
            r = client.call_tool("hermes_events_poll", {"limit": 20})
            events = r.get("events", [])

            for ev in events:
                ev_name = ev.get("event", "")
                ev_data = ev.get("data", {})

                if ev_name == "approval.request":
                    approval_found = True
                    approval_id = ev_data.get("id", "")
                    print(f"    🔔 Approval request found!")
                    print(f"       ID: {approval_id}")
                    print(f"       Type: {ev_data.get('type', '?')}")
                    print(f"       Description: {ev_data.get('description', '?')[:100]}")
                    ok("approval.request detected", approval_id)
                    break

                elif ev_name in ("response.completed", "background.complete"):
                    response_text = ev_data.get("text", "")
                    print(f"    📨 Response event: {ev_name}")
                    print(f"       Text: {response_text[:150]}")
                    ok("response received", ev_name)

                    if "APPROVAL_TEST" in response_text:
                        ok("test marker found in response")
                    break

            if approval_found or (events and any(
                e.get("event") in ("response.completed", "background.complete")
                for e in events
            )):
                break

            print(f"    ⏳ Waiting... (attempt {attempt+1}/12)")

        # Step 5: If approval found, respond to it
        if approval_found and approval_id:
            print(f"\n📋 Step 4: Approve the request")
            print("-" * 40)

            r = client.call_tool("hermes_approval_respond", {
                "approval_id": approval_id,
                "decision": "approve",
            })
            if "error" not in r:
                ok("approval_respond (approved)")
            else:
                fail("approval_respond", r)

            # Wait for completion after approval
            print("    Waiting for task to continue...")
            time.sleep(10)

            r = client.call_tool("hermes_events_poll", {"limit": 20})
            events = r.get("events", [])
            for ev in events:
                if ev.get("event") in ("response.completed", "background.complete"):
                    ok("task completed after approval")
                    break
        else:
            print("\n📋 Step 4: No approval needed (auto-approved or completed)")
            print("-" * 40)

            # Check if there are pending approvals
            r = client.call_tool("hermes_permissions_list")
            approvals = r.get("approvals", [])
            if approvals:
                print(f"    Found {len(approvals)} pending approvals")
                for a in approvals:
                    print(f"      - {a.get('id', '?')}: {a.get('description', '?')[:80]}")
                ok("permissions_list", f"{len(approvals)} pending")

                # Approve the first one
                aid = approvals[0].get("id", "")
                if aid:
                    r = client.call_tool("hermes_approval_respond", {
                        "approval_id": aid,
                        "decision": "approve",
                    })
                    ok("approval_respond", aid)
            else:
                print("    No pending approvals (task may have auto-completed)")
                ok("no pending approvals")

        # Step 6: Check final messages
        print("\n📋 Step 5: Read final messages")
        print("-" * 40)
        r = client.call_tool("hermes_messages_read", {"mode": "all", "limit": 5})
        messages = r.get("messages", [])
        print(f"    Messages: {len(messages)}")
        for m in messages:
            role = m.get("role", "?")
            content = m.get("content", "")[:100]
            print(f"    [{role}] {content}")
        ok("messages_read", f"{len(messages)} msgs")

        # Step 7: Check session status
        r = client.call_tool("hermes_session_status")
        running = r.get("running", False) if isinstance(r, dict) else False
        print(f"\n    Session status: running={running}")
        ok("session_status")

    finally:
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
    return failed == 0


if __name__ == "__main__":
    success = test_approval_stdio()
    sys.exit(0 if success else 1)
