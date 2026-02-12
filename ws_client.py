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
            project_id = params.get("projectId")
            project_name = params.get("projectName")
            result = await _run_sync(ctrl.create_folder, path, project_id, project_name)
            return result
        if cmd == "open_cursor":
            path = params.get("path", "")
            project_id = params.get("projectId")
            result = await _run_sync(ctrl.open_cursor, path, project_id)
            return result
        if cmd == "get_input_state":
            project_id = params.get("projectId")
            result = await _run_sync(ctrl.get_input_state, project_id)
            return result
        if cmd == "write_and_send":
            text = params.get("text", "")
            project_id = params.get("projectId")
            result = await _run_sync(ctrl.write_and_send, text, project_id)
            return result
        if cmd == "open_new_agent":
            project_id = params.get("projectId")
            result = await _run_sync(ctrl.open_new_agent, project_id)
            return result
        return {"ok": False, "error": f"未知命令: {cmd}"}
    except Exception as e:
        logger.exception("执行命令异常")
        return {"ok": False, "error": str(e)}


def _response_payload(msg_id: Any, msg_type: str, data: dict, project_id: Optional[str] = None) -> dict:
    """构造统一响应体，若有 projectId 则一并带上。"""
    payload = {"id": msg_id, "type": msg_type, "data": data}
    if project_id is not None:
        payload["projectId"] = project_id
    return payload


async def process_message(ws, raw: str) -> None:
    """解析一条后端消息，执行命令并回写一条 JSON。"""
    logger.info("[收到] %s", raw)
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError as e:
        out = json.dumps({"type": "error", "data": {"error": f"JSON 解析失败: {e}"}}, ensure_ascii=False)
        logger.info("[发送] %s", out)
        await ws.send(out)
        return
    msg_id = msg.get("id")
    cmd = msg.get("cmd")
    params = msg.get("params") or {}
    project_id = params.get("projectId")
    if not cmd:
        logger.debug("忽略无 cmd 的消息，不向后台发送错误")
        return
    data = await handle_command(cmd, params)
    out = json.dumps(_response_payload(msg_id, "result", data, project_id), ensure_ascii=False)
    logger.info("[发送] %s", out)
    await ws.send(out)


async def run_client():
    """连接后端 WebSocket：ws://<后端地址>/ws/ai-tool，无需登录与 token、无需 projectId。"""
    while True:
        try:
            url = config.get_ws_url()
            if not url or not url.replace("ws://", "").replace("wss://", "").strip():
                logger.warning("未配置 CURSOR_WS_URL 或 CURSOR_BACKEND_ADDRESS，%s 秒后重试...", config.RECONNECT_INTERVAL)
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
