"""WebSocket bridge to Hermes Dashboard TUI Gateway.

Manages:
- WS connection with auto-reconnect and token fetch
- JSON-RPC call/response matching
- Event buffering and long-poll waiting
- Per-session read cursors for unread message tracking
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import ssl
import time
import urllib.request
from collections import deque
from typing import Optional

try:
    import websockets
except ImportError:
    raise ImportError("pip install websockets")

from config import (
    DASHBOARD_HTTP_URL,
    DASHBOARD_WS_URL,
    DEFAULT_RPC_TIMEOUT,
    STATE_FILE,
    STREAM_POLL_INTERVAL,
    WS_MAX_SIZE,
    WS_OPEN_TIMEOUT,
    WS_RECONNECT_DELAY,
    WS_MAX_RECONNECT_DELAY,
)

logger = logging.getLogger("hermes-mcp.ws_bridge")


class WSBridge:
    """Maintains a persistent WS connection to Hermes Dashboard."""

    def __init__(self, auto_approve: bool = True):
        self.ws = None
        self.connected = False
        self.session_id = ""
        self.auto_approve = auto_approve
        self._pending: dict[str, asyncio.Future] = {}
        self._events: deque[dict] = deque()
        self._events_lock = asyncio.Lock()
        self._events_cv: Optional[asyncio.Condition] = None
        self._req_counter = 0
        self._lock = asyncio.Lock()
        self._reconnect_task: Optional[asyncio.Task] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._running = False

    # ── Lifecycle ──

    async def start(self):
        """Start the bridge (connect + reader loop)."""
        self._running = True
        self._events_cv = asyncio.Condition()
        await self._ensure_connected()
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def stop(self):
        """Gracefully shut down."""
        self._running = False
        if self._reader_task:
            self._reader_task.cancel()
        if self._reconnect_task:
            self._reconnect_task.cancel()
        if self.ws:
            await self.ws.close()

    # ── Connection ──

    async def _ensure_connected(self) -> bool:
        if self.connected and self.ws:
            return True
        return await self._connect()

    async def _connect(self) -> bool:
        token = self._fetch_token()
        ws_url = DASHBOARD_WS_URL
        if token:
            ws_url += f"?token={token}"
        try:
            self.ws = await websockets.connect(
                ws_url, max_size=WS_MAX_SIZE, open_timeout=WS_OPEN_TIMEOUT
            )
            self.connected = True
            logger.info("Connected to %s", DASHBOARD_WS_URL)
            # Start reader
            if self._reader_task:
                self._reader_task.cancel()
            self._reader_task = asyncio.create_task(self._reader_loop())
            return True
        except Exception as e:
            logger.warning("Connect failed: %s", e)
            self.connected = False
            return False

    async def _reconnect_loop(self):
        delay = WS_RECONNECT_DELAY
        while self._running:
            if not self.connected:
                ok = await self._connect()
                if ok:
                    delay = WS_RECONNECT_DELAY
                    await self._ensure_session()
                else:
                    delay = min(delay * 2, WS_MAX_RECONNECT_DELAY)
            await asyncio.sleep(delay if not self.connected else 5)

    def _fetch_token(self) -> str:
        url = DASHBOARD_HTTP_URL
        try:
            req = urllib.request.Request(url)
            resp = urllib.request.urlopen(req, timeout=10)
            html = resp.read().decode("utf-8", errors="ignore")
            m = re.search(r'window\.__HERMES_SESSION_TOKEN__\s*=\s*"([^"]+)"', html)
            return m.group(1) if m else ""
        except Exception:
            return ""

    # ── Session ──

    async def _ensure_session(self):
        """Ensure we have an active session."""
        sid = self._load_session_id()
        if sid:
            try:
                r = await self.call("session.resume", {"session_id": sid}, timeout=SHORT_RPC_TIMEOUT)
                if "result" in r:
                    self.session_id = r["result"].get("session_id", sid)
                    return
            except Exception:
                pass

        try:
            r = await self.call("session.create", {"title": "mcp-server"}, timeout=SHORT_RPC_TIMEOUT)
            if "result" in r:
                self.session_id = r["result"].get("session_id", "")
                self._save_session_id(r["result"].get("stored_session_id", self.session_id))
        except Exception as e:
            logger.warning("Failed to create session: %s", e)

    @staticmethod
    def _load_session_id() -> str:
        try:
            if STATE_FILE.exists():
                return STATE_FILE.read_text().strip()
        except Exception:
            pass
        return ""

    @staticmethod
    def _save_session_id(sid: str):
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(sid)

    # ── RPC ──

    def _next_id(self) -> str:
        self._req_counter += 1
        return f"mcp_{self._req_counter}"

    async def call(self, method: str, params: dict = None, timeout: float = DEFAULT_RPC_TIMEOUT) -> dict:
        """Send a JSON-RPC request and wait for the response.
        
        Events received during the wait are buffered for later consumption.
        """
        # Wait for connection if not yet established
        if not self.connected or not self.ws:
            for _ in range(int(timeout * 2)):  # Check every 0.5s
                if self.connected and self.ws:
                    break
                await asyncio.sleep(0.5)
        if not self.connected or not self.ws:
            raise ConnectionError("Not connected to Hermes Dashboard")

        async with self._lock:
            req_id = self._next_id()
            msg = {"jsonrpc": "2.0", "id": req_id, "method": method}
            if params:
                msg["params"] = params

            fut = asyncio.get_event_loop().create_future()
            self._pending[req_id] = fut
            try:
                await self.ws.send(json.dumps(msg))
                result = await asyncio.wait_for(fut, timeout=timeout)
                return result
            except asyncio.TimeoutError:
                self._pending.pop(req_id, None)
                raise TimeoutError(f"RPC {method} timed out ({timeout}s)")
            finally:
                self._pending.pop(req_id, None)

    # ── Reader ──

    async def _reader_loop(self):
        try:
            async for raw in self.ws:
                try:
                    data = json.loads(raw)
                    self._dispatch(data)
                except json.JSONDecodeError:
                    pass
        except websockets.ConnectionClosed:
            logger.warning("WS connection closed")
            self.connected = False
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.error("Reader error: %s", e)
            self.connected = False

    def _dispatch(self, data: dict):
        # RPC response (has id and either result or error)
        if "id" in data and ("result" in data or "error" in data):
            fut = self._pending.pop(str(data["id"]), None)
            if fut and not fut.done():
                fut.set_result(data)
            return

        # Event — TUI Gateway sends events as:
        #   {"jsonrpc":"2.0","method":"event","params":{"type":"...","session_id":"...","payload":{...}}}
        if data.get("method") == "event":
            params = data.get("params", {})
            event = {
                "event": params.get("type", ""),
                "session_id": params.get("session_id", ""),
                "data": params.get("payload", {}),
            }
            asyncio.create_task(self._append_event(event))
            return

        # Legacy event format (direct event field)
        if "event" in data:
            asyncio.create_task(self._append_event(data))

    async def _append_event(self, event: dict):
        """Append event to buffer with lock protection."""
        async with self._events_lock:
            self._events.append(event)
        if event.get("event") == "approval.request" and self.auto_approve:
            asyncio.create_task(self._auto_approve(event))
        if self._events_cv:
            asyncio.create_task(self._notify_events())

    async def _notify_events(self):
        async with self._events_cv:
            self._events_cv.notify_all()

    async def _auto_approve(self, event: dict):
        data = event.get("data", {})
        aid = data.get("pattern_key", data.get("id", ""))
        if aid and self.session_id:
            try:
                await self.call("approval.respond", {
                    "session_id": self.session_id,
                    "approval_id": aid,
                    "choice": "approve",
                }, timeout=15)
                logger.info("Auto-approved: %s", aid)
            except Exception as e:
                logger.warning("Auto-approve failed: %s", e)

    # ── Session RPC shortcuts ──

    async def session_history(self, session_id: str) -> dict:
        """Get full conversation history via WS RPC."""
        return await self.call("session.history", {"session_id": session_id})

    async def session_list(self, limit: int = 50) -> dict:
        """List all sessions via WS RPC."""
        return await self.call("session.list", {"limit": limit})

    async def session_status(self, session_id: str) -> dict:
        """Get session status via WS RPC."""
        return await self.call("session.status", {"session_id": session_id})

    async def session_most_recent(self) -> dict:
        """Get the most recent session via WS RPC."""
        return await self.call("session.most_recent")

    # ── Events ──

    async def clear_events(self):
        async with self._events_lock:
            self._events.clear()

    async def collect_events(self) -> list[dict]:
        async with self._events_lock:
            evs = list(self._events)
            self._events.clear()
        return evs

    async def wait_for_event(self, timeout_ms: int = 30000) -> Optional[dict]:
        """Wait for the next WS event (long-poll)."""
        timeout_s = timeout_ms / 1000
        start = time.time()

        while time.time() - start < timeout_s:
            async with self._events_lock:
                if self._events:
                    return self._events.popleft()
            if self._events_cv:
                remaining = timeout_s - (time.time() - start)
                try:
                    async with self._events_cv:
                        await asyncio.wait_for(
                            self._events_cv.wait(),
                            timeout=max(0.1, remaining)
                        )
                except asyncio.TimeoutError:
                    pass
            else:
                await asyncio.sleep(STREAM_POLL_INTERVAL)

        return None


class ReadCursor:
    """Per-session read position tracking for unread message support.

    Uses message list length as cursor when messages lack 'id' fields.
    """

    def __init__(self):
        self._cursors: dict[str, int] = {}  # session_id -> last_read_count

    def get_cursor(self, session_id: str) -> int:
        return self._cursors.get(session_id, 0)

    def set_cursor(self, session_id: str, value: int):
        self._cursors[session_id] = value

    def advance(self, session_id: str, messages: list[dict]):
        """Advance cursor to the latest message position."""
        if messages:
            # Try message 'id' field first, fall back to list length
            ids = [m.get("id") for m in messages if m.get("id") is not None]
            if ids:
                max_id = max(ids)
                if max_id > self.get_cursor(session_id):
                    self.set_cursor(session_id, max_id)
            else:
                # Messages lack 'id' — use list length as cursor
                self.set_cursor(session_id, len(messages))

    def filter_unread(self, session_id: str, messages: list[dict]) -> list[dict]:
        """Return only messages after the cursor."""
        if not messages:
            return []
        cursor = self.get_cursor(session_id)
        # Try message 'id' field first, fall back to list index
        ids = [m.get("id") for m in messages if m.get("id") is not None]
        if ids:
            return [m for m in messages if m.get("id", 0) > cursor]
        # Messages lack 'id' — treat cursor as count of already-read messages
        return messages[cursor:]

    def read_all(self, session_id: str, messages: list[dict], limit: int = 50) -> dict:
        """Return all messages, don't update cursor."""
        return {
            "status": "ok",
            "count": len(messages[-limit:]),
            "cursor": self.get_cursor(session_id),
            "messages": messages[-limit:],
        }

    def read_unread(self, session_id: str, messages: list[dict]) -> dict:
        """Return unread messages, advance cursor."""
        unread = self.filter_unread(session_id, messages)
        if unread:
            self.advance(session_id, messages)
            return {
                "status": "messages",
                "count": len(unread),
                "cursor": self.get_cursor(session_id),
                "messages": unread,
            }
        return {
            "status": "no_unread",
            "count": 0,
            "cursor": self.get_cursor(session_id),
            "messages": [],
        }
