# -*- coding: utf-8 -*-
"""登录获取 accessToken 与 userId，并拼接 WebSocket URL."""

import logging
from typing import Any, Optional
from urllib.parse import quote, urlparse

import config

logger = logging.getLogger(__name__)

# 可选：aiohttp 未安装时仅跳过登录
try:
    import aiohttp
    _AIOHTTP_OK = True
except ImportError:
    _AIOHTTP_OK = False

# 登录返回格式: { "code": 200, "data": { "accessToken": "", "userInfo": { "id": 2, ... } }, "message": "..." }


async def login() -> Optional[dict[str, Any]]:
    """
    调用后端登录接口，返回 { "token": accessToken, "userId": userInfo.id }。
    后端返回格式: code=200, data.accessToken, data.userInfo.id。
    若未配置 LOGIN_URL 或未安装 aiohttp，返回 None。
    """
    if not config.LOGIN_URL or not _AIOHTTP_OK:
        if not config.LOGIN_URL:
            logger.debug("未配置 LOGIN_URL，跳过登录")
        else:
            logger.warning("未安装 aiohttp，无法请求登录接口")
        return None
    username = config.LOGIN_USERNAME
    password = config.LOGIN_PASSWORD
    if not username or not password:
        logger.warning("未配置 CURSOR_LOGIN_USERNAME / CURSOR_LOGIN_PASSWORD，跳过登录")
        return None
    try:
        async with aiohttp.ClientSession() as session:
            payload = {"username": username, "password": password}
            async with session.post(config.LOGIN_URL, json=payload) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error("登录失败 HTTP %s: %s", resp.status, text[:200])
                    return None
                data = await resp.json()
        if not isinstance(data, dict):
            logger.error("登录响应格式异常: %s", type(data))
            return None
        if data.get("code") != 200:
            logger.error("登录失败 code=%s: %s", data.get("code"), data.get("message", ""))
            return None
        inner = data.get("data")
        if not isinstance(inner, dict):
            logger.error("登录响应 data 不是对象: %s", type(inner))
            return None
        token = inner.get("accessToken")
        user_info = inner.get("userInfo")
        if not isinstance(user_info, dict):
            logger.error("登录响应 data.userInfo 不存在或不是对象")
            return None
        user_id = user_info.get("id")
        if token is None or user_id is None:
            logger.error("登录响应中缺少 accessToken 或 userInfo.id")
            return None
        logger.info("登录成功，userId=%s", user_id)
        return {"token": token, "userId": user_id}
    except Exception as e:
        logger.exception("登录请求异常: %s", e)
        return None


def build_ws_url(login_result: Optional[dict[str, Any]]) -> str:
    """
    根据登录结果拼接 WebSocket URL：
    ws://{host}:{port}/aiProject/ws/notification/{userId}?token={token}
    host/port 由 LOGIN_URL 解析；路径使用 config.WS_PATH。
    若未登录或配置了 CURSOR_WS_URL，则返回 config.WS_URL（不包含 userId/token）。
    """
    if config.WS_URL:
        # 显式配置了完整 WS 地址时，仅追加 token（兼容旧用法）
        if login_result and login_result.get("token"):
            base = config.WS_URL
            sep = "&" if "?" in base else "?"
            return f"{base}{sep}token={quote(login_result['token'])}"
        return config.WS_URL
    if not login_result or not login_result.get("token") or login_result.get("userId") is None:
        # 无登录信息时无法拼接，返回默认
        return config.WS_URL or "ws://127.0.0.1:8080"
    parsed = urlparse(config.LOGIN_URL)
    host = parsed.hostname or "localhost"
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    scheme = "wss" if parsed.scheme == "https" else "ws"
    path = config.WS_PATH.rstrip("/")
    user_id = login_result["userId"]
    token = quote(login_result["token"])
    url = f"{scheme}://{host}:{port}{path}/{user_id}?token={token}"
    return url


def build_ws_url_with_token(ws_base_url: str, token: Optional[str]) -> str:
    """在 WebSocket URL 上附加 token（查询参数）。保留给未使用 userId 路径时的兼容。"""
    if not token:
        return ws_base_url
    sep = "&" if "?" in ws_base_url else "?"
    return f"{ws_base_url}{sep}token={quote(token)}"
