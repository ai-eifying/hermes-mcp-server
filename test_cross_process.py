#!/usr/bin/env python3
"""
跨进程测试 — 使用 MCP 官方客户端库

用法:
    python3 test_cross_process.py              # 自动启动 server
    python3 test_cross_process.py --port 9221  # 自定义端口
"""

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

SERVER = str(Path.home() / ".hermes" / "tmp" / "hermes-mcp-server" / "server.py")
DEFAULT_PORT = 9221


async def run_tests(port: int):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    url = f"http://127.0.0.1:{port}/mcp"
    passed = failed = 0

    def ok(name):
        nonlocal passed
        print(f"  ✅ {name}")
        passed += 1

    def fail(name, err=""):
        nonlocal failed
        print(f"  ❌ {name}: {str(err)[:100]}")
        failed += 1

    def extract(result) -> dict:
        for c in result.content:
            if c.type == "text":
                try:
                    return json.loads(c.text)
                except json.JSONDecodeError:
                    return {"raw": c.text}
        return {}

    print("=" * 60)
    print("Cross-Process Test — HTTP/SSE (MCP Client)")
    print("=" * 60)

    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:

            # Phase 1: Connection
            print("\n📋 Phase 1: Connection")
            print("-" * 40)
            try:
                r = await session.initialize()
                ok(f"initialize ({r.serverInfo.name} v{r.serverInfo.version})")
            except Exception as e:
                fail("initialize", e)
                return False

            # Phase 2: Tool Discovery
            print("\n📋 Phase 2: Tool Discovery")
            print("-" * 40)
            try:
                tools = await session.list_tools()
                if len(tools.tools) >= 29:
                    ok(f"tools/list ({len(tools.tools)} tools)")
                else:
                    fail(f"tools/list", f"Only {len(tools.tools)} tools")
            except Exception as e:
                fail("tools/list", e)

            # Phase 3: Skills
            print("\n📋 Phase 3: Skills")
            print("-" * 40)
            try:
                r = await session.call_tool("hermes_skills_list", {"category": "devops"})
                d = extract(r)
                if d.get("count", 0) > 0:
                    ok(f"skills_list ({d['count']} skills)")
                else:
                    fail("skills_list", d)
            except Exception as e:
                fail("skills_list", e)

            try:
                r = await session.call_tool("hermes_skill_view", {"name": "hermes-agent"})
                d = extract(r)
                if len(json.dumps(d)) > 1000:
                    ok("skill_view")
                else:
                    fail("skill_view", "Too short")
            except Exception as e:
                fail("skill_view", e)

            # Phase 4: Session
            print("\n📋 Phase 4: Session Management")
            print("-" * 40)
            try:
                r = await session.call_tool("hermes_session_create", {"title": "cross-proc"})
                d = extract(r)
                if "session_id" in d:
                    ok(f"session_create ({d['session_id']})")
                else:
                    fail("session_create", d)
            except Exception as e:
                fail("session_create", e)

            try:
                r = await session.call_tool("hermes_session_list", {})
                ok("session_list")
            except Exception as e:
                fail("session_list", e)

            try:
                r = await session.call_tool("hermes_session_status", {})
                ok("session_status")
            except Exception as e:
                fail("session_status", e)

            # Phase 5: Config & Health
            print("\n📋 Phase 5: Config & Health")
            print("-" * 40)
            try:
                r = await session.call_tool("hermes_health", {})
                d = extract(r)
                ok(f"health (ws={d.get('ws_connected', '?')})")
            except Exception as e:
                fail("health", e)

            try:
                r = await session.call_tool("hermes_config_get", {})
                ok("config_get")
            except Exception as e:
                fail("config_get", e)

            # Phase 6: Messaging
            print("\n📋 Phase 6: Messaging")
            print("-" * 40)
            try:
                r = await session.call_tool("hermes_conversations_list", {})
                ok("conversations_list")
            except Exception as e:
                fail("conversations_list", e)

            try:
                r = await session.call_tool("hermes_messages_read", {"mode": "all", "limit": 5})
                ok("messages_read")
            except Exception as e:
                fail("messages_read", e)

            try:
                r = await session.call_tool("hermes_messages_read", {"mode": "unread"})
                ok("messages_read (unread)")
            except Exception as e:
                fail("messages_read (unread)", e)

            # Phase 7: Prompt
            print("\n📋 Phase 7: Prompt")
            print("-" * 40)
            try:
                r = await session.call_tool("hermes_prompt_background", {"prompt": "Reply: CROSS_PROC_OK"})
                d = extract(r)
                if d.get("ok") or d.get("session_id"):
                    ok("prompt_background")
                else:
                    fail("prompt_background", d)
            except Exception as e:
                fail("prompt_background", e)

            try:
                r = await session.call_tool("hermes_messages_stream", {"timeout": 15})
                d = extract(r)
                if "status" in d:
                    ok(f"messages_stream (status={d['status']})")
                else:
                    fail("messages_stream", d)
            except Exception as e:
                fail("messages_stream", e)

    # Summary
    print("\n" + "=" * 60)
    total = passed + failed
    status = "🎉 ALL PASSED" if failed == 0 else f"⚠️  {failed} FAILED"
    print(f"Results: {passed}/{total} passed — {status}")
    print("=" * 60)
    return failed == 0


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--external", action="store_true", help="Don't start server (use existing)")
    args = parser.parse_args()

    proc = None
    if not args.external:
        print(f"🚀 Starting server on port {args.port}...")
        proc = subprocess.Popen(
            [sys.executable, SERVER, "--transport", "http", "--port", str(args.port)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        time.sleep(5)
        if proc.poll() is not None:
            print(f"❌ Server failed: {proc.stderr.read()[:500]}")
            sys.exit(1)

    try:
        success = asyncio.run(run_tests(args.port))
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            print("✅ Server stopped")

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
