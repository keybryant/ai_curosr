# Cursor 本地控制客户端

在本地运行，通过 WebSocket 与后端连接，由后端下发命令控制本机 Cursor：监控输入框、写入并发送、创建文件夹、用 Cursor 打开指定文件夹。

## 环境

- Windows
- Python 3.10+
- 已安装 Cursor，且已配置命令行（安装时勾选 “添加到 PATH” 或手动将 Cursor 加入 PATH）

## 安装

```powershell
cd d:\develop\aiCode\ai_cursor
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 配置

在项目根目录创建 `.env`（可参考 `.env.example`）或设置环境变量：

- **WebSocket**（无需登录与 token，不再需要 projectId）
  - 连接地址：`ws://<后端地址>/ws/ai-tool`
  - `CURSOR_BACKEND_ADDRESS`: 后端地址（仅 host:port），如 `localhost:8080`
  - `CURSOR_WS_URL`: 若需写死完整 WS 地址可配置此项（一般不配）
- `CURSOR_EXE`: Cursor 可执行路径，默认 `cursor`（依赖 PATH）
- `RECONNECT_INTERVAL`: 断线重连间隔（秒），默认 5
- `CURSOR_UI_TIMEOUT`: 等待 Cursor 窗口/控件的超时（秒），默认 15
- `CURSOR_SEND_HOTKEY`: 发送消息热键，默认 `Ctrl+Enter`
- `CURSOR_OPEN_AGENT_HOTKEY`: 打开新 Agent 的热键，默认 `Ctrl+L`

## 运行

1. 启动你的后端 WebSocket 服务（见下方协议说明）。
2. 在本地运行客户端：

```powershell
python main.py
```

客户端会持续连接后端，断线后按 `RECONNECT_INTERVAL` 自动重连。

### 本地演示（可选）

用自带的演示服务端测试时，可设置 `CURSOR_WS_URL=ws://127.0.0.1:8765`：

- 终端 1：`python server_demo.py`（启动 ws://127.0.0.1:8765）
- 终端 2：`python main.py`（连接演示服务端）
- 在终端 1 输入 JSON 命令并回车，例如：

```json
{"id":1,"cmd":"create_folder","params":{"path":"test_dir"}}
{"id":2,"cmd":"open_cursor","params":{"path":"test_dir"}}
{"id":3,"cmd":"get_input_state"}
{"id":4,"cmd":"write_and_send","params":{"text":"请列出当前目录文件"}}
```

## 协议（后端 → 客户端）

后端发送单行 JSON：

```json
{
  "id": 1,
  "cmd": "create_folder | open_cursor | get_input_state | write_and_send | open_new_agent",
  "params": { ... }
}
```

| cmd | 说明 | params |
|-----|------|--------|
| `create_folder` | 创建文件夹（可多级）；传 `projectId` 时会在目录下建 `.project/project.json` 保存 projectId 与 projectName | `{ "path": "路径", "projectId": "可选", "projectName": "可选，默认用目录名" }` |
| `open_cursor` | 用 Cursor 打开指定文件夹；传 `projectId` 则登记到「projectId→窗口」映射表 | `{ "path": "路径", "projectId": "可选，工程 ID" }` |
| `get_input_state` | 获取当前输入框状态（内容等） | `{ "projectId": "可选，指定操作哪个工程窗口" }` |
| `write_and_send` | 在输入框写入内容并发送 | `{ "text": "要发送的文本", "projectId": "可选" }` |
| `open_new_agent` | 打开新的 Agent（Chat/Composer） | `{ "projectId": "可选" }` |

**多窗口与 projectId**：`params` 中可带 `projectId`。先用 `open_cursor` 带 `projectId` 打开某目录，客户端会维护「projectId → 该窗口对应文件夹名」的映射；后续 `get_input_state`、`write_and_send`、`open_new_agent` 传同一 `projectId` 时，会在对应 Cursor 窗口上操作。不传 `projectId` 时沿用“上次打开的窗口”行为。

## 协议（客户端 → 后端）

客户端回复单行 JSON：

```json
{
  "id": 1,
  "type": "result",
  "data": { ... }
}
```

或错误：

```json
{
  "id": 1,
  "type": "error",
  "data": { "error": "错误信息" }
}
```

`data` 内容与 `cursor_controller` 各函数返回值一致（如 `ok`、`path`、`text`、`error` 等）。

## 输入框说明

- **监控/写入输入框**：依赖 Windows UI 自动化（pywinauto UIA）。若 Cursor 的 Chat/Composer 输入框无法被识别，会尝试键盘模拟（需先手动将焦点放到输入框）。

## 项目结构

```
ai_cursor/
  config.py           # 配置（登录、WS 路径、Cursor 等）
  cursor_controller.py # 本地控制：文件夹、打开 Cursor、输入框
  ws_client.py        # WebSocket 客户端与命令分发
  main.py             # 入口
  server_demo.py      # 演示用 WebSocket 服务端
  requirements.txt
  README.md
```
