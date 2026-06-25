# Hermes MCP Server

Hermes Agent 的 MCP 服务器实现，通过 WS JSON-RPC 协议连接到 Hermes Dashboard 的 TUI Gateway。

## 项目结构

```
hermes-mcp-server/
├── server.py              # MCP server 主入口（stdio + http 模式）
├── config.py              # 配置常量
├── ws_bridge.py           # WS 连接管理、JSON-RPC 通信、ReadCursor
├── tools/                 # MCP tools 实现
│   ├── __init__.py        # 工具注册导出
│   ├── session.py         # Session 管理 tools (6)
│   ├── prompt.py          # Prompt 提交 tools (4: submit/background/stream/interrupt)
│   ├── messaging.py       # 消息读取/流式 tools (5)
│   ├── approval.py        # 审批 tools (2)
│   ├── cli.py             # CLI 命令 tools (3)
│   ├── config_tools.py    # 配置 tools (3)
│   └── model.py           # 模型 tools (2)
├── tests/                 # pytest 测试
│   ├── conftest.py        # MCPClient fixture
│   ├── test_tools_list.py # 工具注册测试
│   ├── test_read_cursor.py # ReadCursor 测试
│   ├── test_events.py     # 事件格式化+合并测试
│   └── test_streaming.py  # 流式集成测试
├── SKILL.md               # 本文件
└── README.md              # 项目文档
```

## 核心设计

### 纯 WS RPC 架构

所有数据访问通过 WS JSON-RPC 调用 Hermes Dashboard，**无需本地 DB 访问**。

```
MCP Client ──MCP──► hermes-mcp-server ──WS JSON-RPC──► Hermes Dashboard
                              │
                              └── 可部署在远程机器
```

### 主要 RPC 方法

| 方法 | 说明 |
|------|------|
| `session.create` | 创建新 session |
| `session.resume` | 切换到已有 session |
| `session.list` | 列出所有 session |
| `session.history` | 获取完整对话历史 |
| `session.status` | 获取 session 状态 |
| `session.delete` | 删除 session |
| `prompt.submit` | 同步提交 prompt |
| `prompt.background` | 异步提交 prompt |
| `session.interrupt` | 中断运行中的 prompt |
| `approval.respond` | 响应审批请求 |
| `slash.exec` | 执行 slash 命令 |
| `cli.exec` | 执行 CLI 命令 |
| `commands.catalog` | 获取命令目录 |
| `config.get` / `config.set` | 配置读写 |
| `model.options` | 获取模型列表 |
| `model.disconnect` | 断开模型连接 |

## 最佳实践

### 1. 流式提交（推荐）— `prompt_stream` + `messages_stream`

**提交 prompt，批量读取事件**。每次 `messages_stream` 返回所有未读事件，连续 delta 事件自动合并。

```python
# 1. 提交 prompt（非阻塞，保留事件缓冲）
hermes_prompt_stream("查看天气...")

# 2. 批量读取事件
while True:
    r = hermes_messages_stream(timeout=5)
    status = r.get("status")

    if status == "events":
        for ev in r["events"]:
            t = ev.get("event")
            if t == "tool_call":
                print(f"🔧 {ev['name']}({ev.get('input', '')})")
            elif t == "tool_result":
                print(f"✅ {ev['name']} → {ev.get('output', '')[:200]}")
            elif t == "message.delta":
                print(f"💬 {ev.get('text', '')}")  # 已合并
            elif t == "completed":
                print(f"🏁 {ev.get('text', '')}")
            elif t == "error":
                print(f"❌ {ev.get('message', '')}")

        # 检查是否完成
        if any(e.get("event") == "completed" for e in r["events"]):
            break

    elif status == "timeout":
        if not r.get("running"):
            break
```

**返回格式**：
```json
{
  "status": "events",
  "count": 5,
  "events": [
    {"event": "reasoning.delta", "text": "用户想查天气..."},  // 已合并
    {"event": "tool_call", "name": "web_search", "input": "..."},
    {"event": "tool_result", "name": "web_search", "output": "..."},
    {"event": "message.delta", "text": "今天北京晴..."},  // 已合并
    {"event": "completed", "text": "今天北京晴...", "usage": {...}}
  ]
}
```

**事件类型**：`reasoning.delta → tool_call → tool_result → message.delta → completed`

**合并规则**：连续相同类型的 delta 事件（`reasoning.delta`、`thinking.delta`、`message.delta`）自动合并为一个，`text` 字段拼接。

### 2. 后台任务 — `prompt_background` + `messages_stream`

**fire-and-forget**，适合不关心中间过程的长任务：

```python
hermes_prompt_background("执行复杂分析...")

while True:
    r = hermes_messages_stream(timeout=5)
    if r.get("status") == "events":
        for ev in r["events"]:
            if ev.get("event") == "completed":
                print(ev.get("text", ""))
                break
    elif r.get("status") == "timeout" and not r.get("running"):
        break
```

### 3. 同步提交（简单场景）

```python
# 直接等待完整响应（含工具调用摘要）
r = hermes_prompt_submit("Reply: hello", timeout=60)
print(r["response"])
if r.get("tool_calls"):
    for tc in r["tool_calls"]:
        print(f"  工具: {tc['name']}")
```

### 4. 审批流程

```python
hermes_prompt_stream("执行 bash 命令...")

while True:
    r = hermes_messages_stream(timeout=5)
    if r.get("status") == "events":
        for ev in r["events"]:
            if ev.get("event") == "approval_required":
                hermes_approval_respond(
                    approval_id=ev["id"],
                    decision="approve"
                )
            elif ev.get("event") == "completed":
                print(ev.get("text", ""))
        if any(e.get("event") == "completed" for e in r["events"]):
            break
    elif r.get("status") == "timeout" and not r.get("running"):
        break
```

### 5. 读取完整历史

```python
# 获取完整对话历史
r = hermes_messages_history(session_id="xxx", limit=100)
for msg in r["messages"]:
    print(f"[{msg['role']}]: {msg['text']}")
```

### 6. 错误处理

```python
try:
    r = hermes_prompt_submit("执行任务", timeout=30)
    if "error" in r:
        print(f"错误: {r['error']}")
    else:
        print(r["response"])
except TimeoutError:
    print("任务超时")
except Exception as e:
    print(f"异常: {e}")
```

### 7. Session 管理

```python
# 创建 session
r = hermes_session_create(title="my-task")
session_id = r["session_id"]

# 切换 session
hermes_session_resume(session_id=session_id)

# 获取状态
status = hermes_session_status(session_id=session_id)

# 删除 session
hermes_session_delete(session_id=session_id)
```

### 8. CLI 命令执行

```python
# 执行 slash 命令
r = hermes_slash_exec(command="/model")
print(r["output"])

# 执行 CLI 命令
r = hermes_cli_exec(command="ls -la")
print(r["output"])
```

## 使用方式

### stdio 模式（Claude Code / Cursor）

```bash
python3 ~/.hermes/tmp/hermes-mcp-server/server.py
```

MCP 客户端配置：
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

### HTTP/SSE 模式（跨进程/跨机器）

```bash
python3 ~/.hermes/tmp/hermes-mcp-server/server.py --transport http --port 9221
```

MCP 客户端配置：
```json
{
  "mcpServers": {
    "hermes-agent": {
      "type": "http",
      "url": "http://<hermes-ip>:9221/mcp"
    }
  }
}
```

### 关闭自动批准

```bash
python3 ~/.hermes/tmp/hermes-mcp-server/server.py --auto-approve off
```

### 调试模式

```bash
python3 ~/.hermes/tmp/hermes-mcp-server/server.py --verbose
```

## 测试

```bash
# 离线测试（不需要 Dashboard 运行）
python3 ~/.hermes/tmp/hermes-mcp-server/test_mcp_server.py --offline

# 在线测试（需要 Dashboard 运行）
python3 ~/.hermes/tmp/hermes-mcp-server/test_mcp_server.py

# 跨进程测试
python3 ~/.hermes/tmp/hermes-mcp-server/test_cross_process.py

# 远程测试
python3 ~/.hermes/tmp/hermes-mcp-server/test_remote.py --host <hermes-ip> --port 9221
```

## 依赖

```bash
pip install mcp websockets aiohttp
```

## 关键实现细节

### WS 连接管理

`WSBridge` 类维护与 Dashboard 的持久 WS 连接：
- 自动重连（指数退避）
- Token 自动获取（从 Dashboard HTML 解析）
- Session 自动创建/恢复
- 事件缓冲和长轮询

### ReadCursor

`ReadCursor` 类实现基于索引的消息追踪：
- `get_cursor(session_id)` — 获取当前读取位置
- `advance(session_id, messages)` — 推进到最新消息
- `filter_unread(session_id, messages)` — 过滤未读消息
- `read_unread(session_id, messages)` — 读取并推进

### 审批系统

Hermes 的审批是双层的：
- **L1 Agent 层**：LLM 自行判断是否执行危险命令
- **L2 Tool 层**：terminal 工具检查命令安全性

`--auto-approve on`（默认）自动处理 L2 审批。

审批 ID 使用 `pattern_key`（如 `"shell command via -c/-lc flag"`）。

## 性能优化

### 1. 使用 `timeout` 参数

```python
# 短轮询（快速响应）
r = hermes_messages_stream(timeout=2)

# 长轮询（减少请求）
r = hermes_messages_stream(timeout=30)
```

### 2. 批量操作

```python
# 批量读取历史
r = hermes_messages_history(limit=100)  # 一次获取更多
```

### 3. 异步提交

```python
# 使用 background 避免阻塞
hermes_prompt_background("长任务...")
```

## 远程部署

### 1. 安装依赖

```bash
pip install mcp websockets aiohttp
```

### 2. 启动服务

```bash
# 在 Hermes 机器上
python3 ~/.hermes/tmp/hermes-mcp-server/server.py --transport http --port 9221
```

### 3. 客户端配置

```json
{
  "mcpServers": {
    "hermes-agent": {
      "url": "http://<hermes-ip>:9221/mcp"
    }
  }
}
```

### 4. 防火墙

确保端口 9221 可访问：
```bash
# 检查端口
netstat -tlnp | grep 9221

# 开放端口（如果需要）
sudo ufw allow 9221
```

## 已知限制

1. **Skills tools 已移除**：需要本地文件系统访问，远程不可用
2. **Conversations/Channels tools 已移除**：需要本地 DB 访问
3. **Messages Send 已移除**：需要本地 send_message 工具

## ⚠️ Pitfalls

1. **WS 端点是 `/api/ws`**，不是 `/ws/client`
2. **RPC 参数用 `text`**，不是 `prompt`（TUI Gateway 要求）
3. **事件格式**：TUI Gateway 用 `method: "event"` + `params.type`，不是 `event` 字段
4. **审批 ID 是 `pattern_key`**，不是 `id` 字段
5. **background task 不触发审批事件**，只有 `prompt.submit`（同步）才触发
6. **Session ID 有两层**：`session_id`（短 ID）和 `stored_session_id`（DB ID）
7. **远程部署**：MCP Server 可以部署在任何机器上，只需能访问 Hermes Dashboard 的 HTTP/WS 端口
8. **Token 自动获取**：从 Dashboard HTML 解析 `window.__HERMES_SESSION_TOKEN__`
9. **Session 自动恢复**：首次连接自动创建 session，后续自动恢复
10. **事件缓冲**：WS 事件会缓冲，`messages_stream` 会检查缓冲区

## 变更日志

### v1.3.0 (2026-06-12)
- 新增 `hermes_prompt_stream` 工具 — 流式提交，保留事件缓冲
- 重写 `hermes_messages_stream` — 批量返回所有未读事件，连续 delta 自动合并
- 修复 ReadCursor — 消息无 `id` 字段时用列表索引追踪
- 支持 `message.delta` 事件合并（之前只支持 `response.chunk`）
- 更新最佳实践：批量事件格式、合并规则、审批流程

### v1.2.0 (2026-06-12)
- 添加最佳实践指南
- 添加性能优化建议
- 添加远程部署指南
- 添加错误处理示例

### v1.1.0 (2026-06-11)
- 移除 `db_reader.py` 本地 DB 依赖
- 所有数据通过 WS RPC 获取
- 支持远程部署
- 新增 `hermes_messages_history` tool
- 工具总数：29 → 24

### v1.0.0 (2026-06-10)
- 初始版本
- 29 个 MCP tools
- 支持 stdio 和 HTTP/SSE 传输
