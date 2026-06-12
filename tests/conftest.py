"""Pytest fixtures for hermes-mcp-server tests."""

import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

SERVER = str(Path(__file__).parent.parent / "server.py")


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
        r = self._send("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0"},
        })
        assert "result" in r, f"Initialize failed: {r}"
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
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        response_line = self.proc.stdout.readline()
        if not response_line:
            return {"error": "No response"}
        return json.loads(response_line.strip())

    def _notify(self, method: str, params: dict = None):
        msg = {"jsonrpc": "2.0", "method": method}
        if params:
            msg["params"] = params
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def call_tool(self, name: str, arguments: dict = None, timeout: int = 30) -> dict:
        params = {"name": name}
        if arguments:
            params["arguments"] = arguments
        self._req_id += 1
        msg = {"jsonrpc": "2.0", "id": self._req_id, "method": "tools/call", "params": params}
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

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
        if "result" in r and "content" in r["result"]:
            for c in r["result"]["content"]:
                if c.get("type") == "text":
                    try:
                        return json.loads(c["text"])
                    except json.JSONDecodeError:
                        return {"raw_text": c["text"]}
        return r

    def list_tools(self) -> list:
        r = self._send("tools/list")
        return r.get("result", {}).get("tools", [])


@pytest.fixture
def client():
    """Create and start an MCP client, stop after test."""
    c = MCPClient(verbose=False)
    c.start()
    yield c
    c.stop()


@pytest.fixture
def verbose_client():
    """Create a verbose MCP client for debugging."""
    c = MCPClient(verbose=True)
    c.start()
    yield c
    c.stop()
