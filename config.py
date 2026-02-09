# -*- coding: utf-8 -*-
"""配置：WebSocket 地址、Cursor 路径等"""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# 从环境变量读取，默认值供本地开发
# WebSocket: ws://<后端地址>/ws/ai-tool/<projectId>，无需登录与 token
BACKEND_ADDRESS = os.getenv("CURSOR_BACKEND_ADDRESS", "localhost:8080/aiProject")  # 仅 host:port，如 localhost:8080
PROJECT_ID = os.getenv("CURSOR_PROJECT_ID", "16")  # 项目 ID，必填
WS_URL = os.getenv("CURSOR_WS_URL", "")  # 若配置则直接使用，否则用 BACKEND_ADDRESS + PROJECT_ID 拼接
# Cursor 可执行文件路径（若在 PATH 中可写 cursor）
CURSOR_EXE = os.getenv("CURSOR_EXE", "cursor")
# 连接重试间隔（秒）
RECONNECT_INTERVAL = float(os.getenv("RECONNECT_INTERVAL", "5"))
# 等待 Cursor 窗口/输入框就绪的超时（秒）
CURSOR_UI_TIMEOUT = int(os.getenv("CURSOR_UI_TIMEOUT", "15"))
# 发送消息的热键：Enter 或 Ctrl+Enter（Cursor Composer 通常为 Ctrl+Enter）
CURSOR_SEND_HOTKEY = os.getenv("CURSOR_SEND_HOTKEY", "Ctrl+Enter")

# 项目根目录（用于默认工作目录）
PROJECT_ROOT = Path(__file__).resolve().parent


def get_ws_url() -> str:
    """得到 WebSocket 地址：ws://<后端地址>/ws/ai-tool/<projectId>。"""
    if WS_URL:
        return WS_URL
    base = BACKEND_ADDRESS.strip()
    if base.startswith("http://"):
        base = base[7:]
    elif base.startswith("https://"):
        base = base[8:]
    if not base.startswith("ws://") and not base.startswith("wss://"):
        base = "ws://" + base
    return base.rstrip("/") + f"/ws/ai-tool/{PROJECT_ID}"
