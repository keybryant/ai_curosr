# -*- coding: utf-8 -*-
"""
本地 Cursor 控制客户端入口。
通过 WebSocket 连接后端，接收命令：监控输入框、写入并发送、监控结果、创建文件夹、用 Cursor 打开文件夹。
"""

from ws_client import main

if __name__ == "__main__":
    main()
