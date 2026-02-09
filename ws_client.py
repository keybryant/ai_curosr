# -*- coding: utf-8 -*-
"""
WebSocket 客户端：连接后端，接收 JSON 命令并调用 cursor_controller，返回结果。
协议：后端发 { "id": ?, "cmd": "...", "params": {} }，客户端回 { "id": ?, "type": "result"|"error", "data": {} }。
"""

import asyncio
import json
import logging
from typing import Any, Optional

import websockets
from websockets.exceptions import ConnectionClosed

import config
import cursor_controller as ctrl

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def _run_sync(fn, *args, **kwargs) -> Any:
    """在默认线程池中执行同步函数，供 async 调用。"""
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(None, lambda: fn(*args, **kwargs))


async def handle_command(cmd: str, params: Optional[dict] = None) -> dict[str, Any]:
    """根据 cmd 调用 controller 并返回统一格式的 data。"""
    params = params or {}
    try:
        if cmd == "create_folder":
            path = params.get("path", "")
            result = ctrl.create_folder(path)
            return result
        if cmd == "open_cursor":
            path = params.get("path", "")
            result = await _run_sync(ctrl.open_cursor, path)
            return result
        if cmd == "get_input_state":
            result = await _run_sync(ctrl.get_input_state)
            return result
        if cmd == "write_and_send":
            text = params.get("text", "")
            result = await _run_sync(ctrl.write_and_send, text)
            return result
        if cmd == "get_result":
            result = await _run_sync(ctrl.get_result)
            return result
        return {"ok": False, "error": f"未知命令: {cmd}"}
    except Exception as e:
        logger.exception("执行命令异常")
        return {"ok": False, "error": str(e)}


async def process_message(ws, raw: str) -> None:
    """解析一条后端消息，执行命令并回写一条 JSON。"""
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError as e:
        await ws.send(json.dumps({"type": "error", "data": {"error": f"JSON 解析失败: {e}"}}, ensure_ascii=False))
        return
    msg_id = msg.get("id")
    cmd = msg.get("cmd")
    params = msg.get("params")
    if not cmd:
        await ws.send(json.dumps({"id": msg_id, "type": "error", "data": {"error": "缺少 cmd"}}, ensure_ascii=False))
        return
    data = await handle_command(cmd, params)
    payload = {"id": msg_id, "type": "result", "data": data}
    await ws.send(json.dumps(payload, ensure_ascii=False))


async def run_client():
    """连接后端 WebSocket：ws://<后端地址>/ws/ai-tool/<projectId>，无需登录与 token。"""
    while True:
        try:
            url = config.get_ws_url()
            if not config.PROJECT_ID and not config.WS_URL:
                logger.warning("未配置 CURSOR_PROJECT_ID 或 CURSOR_WS_URL，%s 秒后重试...", config.RECONNECT_INTERVAL)
                await asyncio.sleep(config.RECONNECT_INTERVAL)
                continue
            logger.info("正在连接 %s ...", url)
            async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                logger.info("已连接")
                async for raw in ws:
                    await process_message(ws, raw)
        except ConnectionClosed as e:
            logger.warning("连接关闭: %s", e)
        except Exception as e:
            logger.exception("连接或接收异常: %s", e)
        logger.info("%s 秒后重连...", config.RECONNECT_INTERVAL)
        await asyncio.sleep(config.RECONNECT_INTERVAL)


def main():
    asyncio.run(run_client())


if __name__ == "__main__":
    main()
