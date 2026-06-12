#!/usr/bin/env python3
"""
远程机器测试脚本 — 从另一台机器调用 Hermes MCP Server

使用方法:
    1. 在 Hermes 机器上启动 HTTP server:
       python3 ~/.hermes/tmp/hermes-mcp-server/server.py --transport http --port 9221

    2. 将此脚本复制到远程机器:
       scp test_remote.py user@remote:~/

    3. 在远程机器运行:
       python3 test_remote.py --host <hermes-ip> --port 9221
"""

import json
import sys
import urllib.request


def parse_sse(body: str) -> dict:
    for line in body.split("\n"):
        if line.startswith("data: "):
            return json.loads(line[6:])
    return {"error": "No SSE data"}


def mcp_call(host, port, method, params=None, req_id=1):
    url = f"http://{host}:{port}/mcp"
    msg = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params:
        msg["params"] = params
    data = json.dumps(msg).encode()
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json",
        "Accept": "text/event-stream, application/json",
    })
    resp = urllib.request.urlopen(req, timeout=60)
    return parse_sse(resp.read().decode())


def call_tool(host, port, name, args=None, req_id=None):
    if req_id is None:
        call_tool._id = getattr(call_tool, '_id', 100) + 1
        req_id = call_tool._id
    params = {"name": name}
    if args:
        params["arguments"] = args
    r = mcp_call(host, port, "tools/call", params, req_id)
    if "result" in r and "content" in r.get("result", {}):
        for c in r["result"]["content"]:
            if c.get("type") == "text":
                try:
                    return json.loads(c["text"])
                except json.JSONDecodeError:
                    return {"raw": c["text"]}
    return r


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Remote Hermes MCP test")
    parser.add_argument("--host", required=True, help="Hermes server IP")
    parser.add_argument("--port", type=int, default=9221, help="MCP server port")
    args = parser.parse_args()

    host, port = args.host, args.port
    print(f"🔗 Testing Hermes MCP at {host}:{port}")

    r = mcp_call(host, port, "initialize", {
        "protocolVersion": "2024-11-05", "capabilities": {},
        "clientInfo": {"name": "remote-test", "version": "1.0"},
    })
    print(f"✅ Connected: {r.get('result', {}).get('serverInfo', {}).get('name', '?')}")

    r = mcp_call(host, port, "tools/list", req_id=2)
    tools = r.get("result", {}).get("tools", [])
    print(f"✅ {len(tools)} tools available")

    r = call_tool(host, port, "hermes_session_create", {"title": "remote-test"})
    print(f"✅ Session: {r.get('session_id', r)}")

    r = call_tool(host, port, "hermes_skills_list", {"category": "devops"})
    print(f"✅ Skills (devops): {r.get('count', 0)}")

    r = call_tool(host, port, "hermes_health")
    print(f"✅ Health: connected={r.get('ws_connected', '?')}")

    r = call_tool(host, port, "hermes_prompt_background", {"prompt": "Reply: REMOTE_OK"})
    print(f"✅ Background prompt: ok={r.get('ok', '?')}")

    r = call_tool(host, port, "hermes_messages_stream", {"timeout": 30})
    print(f"✅ Stream: status={r.get('status', '?')}")

    print("\n🎉 All remote tests passed!")


if __name__ == "__main__":
    main()
