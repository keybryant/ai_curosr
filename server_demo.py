# -*- coding: utf-8 -*-
"""
演示用 WebSocket 服务端：用于本地测试客户端。
运行方式: python server_demo.py
然后运行: python main.py
再在本终端输入 JSON 命令，例如:
  {"id":1,"cmd":"create_folder","params":{"path":"test_dir"}}
  {"id":2,"cmd":"open_cursor","params":{"path":"test_dir"}}
  {"id":3,"cmd":"get_input_state"}
  {"id":4,"cmd":"write_and_send","params":{"text":"请列出当前目录文件"}}
  {"id":5,"cmd":"get_result"}
"""

import asyncio
import json
import logging

import websockets

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CLIENTS = set()


async def handler(ws):
    CLIENTS.add(ws)
    logger.info("客户端已连接，当前数量: %d", len(CLIENTS))
    try:
        async for raw in ws:
            try:
                msg = json.loads(raw)
                logger.info("客户端回复: %s", json.dumps(msg, ensure_ascii=False, indent=2))
            except Exception:
                logger.info("客户端回复(原始): %s", raw)
    finally:
        CLIENTS.discard(ws)


async def interactive():
    """从标准输入读 JSON 行，发送给第一个已连接的客户端（单客户端测试）。"""
    import sys
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)
    while True:
        line = await reader.readline()
        if not line:
            break
        line = line.decode("utf-8").strip()
        if not line:
            continue
        for client in list(CLIENTS):
            try:
                await client.send(line)
                break
            except Exception as e:
                logger.warning("发送失败: %s", e)
        if not CLIENTS:
            logger.warning("暂无客户端连接，请先运行 main.py")


async def main():
    async with websockets.serve(handler, "127.0.0.1", 8765):
        logger.info("演示服务端 ws://127.0.0.1:8765 已启动，可运行 main.py 连接")
        await interactive()


if __name__ == "__main__":
    asyncio.run(main())
