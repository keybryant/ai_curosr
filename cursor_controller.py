# -*- coding: utf-8 -*-
"""
本地 Cursor 控制器：创建文件夹、用 Cursor 打开目录、监控/写入输入框、监控结果。
依赖：pywinauto (UIA)、pyautogui（备用）、config。
"""

import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

import config

logger = logging.getLogger(__name__)

# 方案 1：优先操作“我开的那个”窗口。Cursor 为 Electron，启动进程会退出，故用“上次打开的文件夹名”匹配窗口标题
_last_opened_folder_name: Optional[str] = None


def _resolve_cursor_exe() -> str:
    """解析 Cursor 可执行文件路径，便于在 Windows 下从 PATH 或带 .exe 的名称正确找到。"""
    exe = config.CURSOR_EXE.strip()
    path = Path(exe)
    if path.is_absolute() and path.exists():
        return str(path)
    # 从 PATH 查找（当前进程环境）
    found = __import__("shutil").which(exe)
    if found:
        return found
    if sys.platform == "win32":
        # Windows 下再尝试 Cursor.exe / cursor.exe
        for name in ("Cursor.exe", "cursor.exe"):
            if name != exe:
                found = __import__("shutil").which(name)
                if found:
                    return found
    return exe

# 可选依赖：UI 自动化失败时不影响其他命令
_pywinauto_ok = False
_pyautogui_ok = False
try:
    from pywinauto import Application
    from pywinauto.findwindows import ElementNotFoundError
    _pywinauto_ok = True
except ImportError:
    pass
try:
    import pyautogui
    _pyautogui_ok = True
except ImportError:
    pass
_pyperclip_ok = False
try:
    import pyperclip
    _pyperclip_ok = True
except ImportError:
    pass


def create_folder(path: str) -> dict[str, Any]:
    """创建文件夹（含多级）。路径可为绝对或相对 config.PROJECT_ROOT。"""
    try:
        p = Path(path)
        if not p.is_absolute():
            p = config.PROJECT_ROOT / p
        p.mkdir(parents=True, exist_ok=True)
        return {"ok": True, "path": str(p.resolve())}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def open_cursor(folder_path: str) -> dict[str, Any]:
    """用 Cursor 打开指定文件夹。使用 config.CURSOR_EXE（会经 _resolve_cursor_exe 解析）。"""
    global _last_opened_folder_name
    try:
        p = Path(folder_path)
        if not p.is_absolute():
            p = config.PROJECT_ROOT / p
        if not p.is_dir():
            return {"ok": False, "error": f"目录不存在: {p}"}
        path_str = str(p.resolve())
        _last_opened_folder_name = p.name  # 用于后续按窗口标题匹配“我开的那个”
        cursor_exe = _resolve_cursor_exe()
        # Windows: 使用列表形式传入，避免路径含空格等问题
        subprocess.Popen(
            [cursor_exe, path_str],
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=config.PROJECT_ROOT,
        )
        return {"ok": True, "path": path_str}
    except FileNotFoundError:
        return {"ok": False, "error": f"未找到 Cursor: {_resolve_cursor_exe()}（请设置 .env 中 CURSOR_EXE 为完整路径，如 D:\\program\\cursor\\Cursor.exe）"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _find_cursor_window():
    """查找 Cursor 主窗口（UIA）。优先匹配“上次打开的文件夹名”在标题中的窗口。"""
    if not _pywinauto_ok:
        logger.warning("pywinauto 未安装，无法查找 Cursor 窗口")
        return None
    try:
        from pywinauto import Application
        from pywinauto import Desktop
    except Exception as e:
        logger.error("导入 pywinauto 失败: %s", e)
        return None

    # 1) 枚举标题含 Cursor 的顶层窗口，若有“上次打开的文件夹名”则优先选标题含该名的
    try:
        desktop = Desktop(backend="uia")
        cursor_windows = desktop.windows(title_re=".*Cursor.*")
        if cursor_windows and _last_opened_folder_name:
            for wnd in cursor_windows:
                try:
                    title = wnd.window_text() or ""
                    if _last_opened_folder_name in title:
                        logger.info("按标题匹配到上次打开的窗口: %s", title[:80])
                        return wnd
                except Exception:
                    continue
        if cursor_windows:
            logger.info("使用第一个 Cursor 窗口: %s", (cursor_windows[0].window_text() or "")[:80])
            return cursor_windows[0]
    except Exception as e:
        logger.debug("枚举 Cursor 窗口失败: %s", e)

    # 2) connect 按标题匹配（任意一个 Cursor 窗口）
    try:
        logger.info("尝试按标题 .*Cursor.* 连接 Cursor 进程")
        app = Application(backend="uia").connect(title_re=".*Cursor.*", timeout=config.CURSOR_UI_TIMEOUT)
        try:
            wnd = app.window(title_re=".*Cursor.*")
            if _last_opened_folder_name and wnd.window_text() and _last_opened_folder_name not in wnd.window_text():
                logger.info("当前连接到的 Cursor 窗口标题: %s", (wnd.window_text() or "")[:80])
            return wnd
        except Exception:
            return app.top_window()
    except Exception as e:
        logger.warning("按标题 .*Cursor.* 查找 Cursor 失败: %s", e)

    # 3) 按可执行文件完整路径连接（path 为精确路径，非正则）
    try:
        exe_path = _resolve_cursor_exe()
        if exe_path and Path(exe_path).exists():
            logger.info("尝试按可执行文件路径连接: %s", exe_path)
            app = Application(backend="uia").connect(path=exe_path, timeout=config.CURSOR_UI_TIMEOUT)
            return app.top_window()
    except Exception as e:
        logger.warning("按 path 连接 Cursor 失败: %s", e)
    return None


def get_input_state() -> dict[str, Any]:
    """
    监控当前输入框状态（Chat/Composer 输入区）。
    优先用 UIA 查找编辑框，失败则用备用逻辑（需先聚焦到输入框）。
    """
    out = {"ok": False, "text": "", "focused": False, "method": "none"}
    if not _pywinauto_ok:
        out["error"] = "未安装 pywinauto"
        return out
    try:
        wnd = _find_cursor_window()
        if not wnd:
            logger.warning("get_input_state: 未找到 Cursor 窗口")
            out["error"] = "未找到 Cursor 窗口或超时"
            return out
        # Cursor/VS Code 类界面：编辑区多为 Edit 或 Document
        try:
            # 尝试多种可能控件类型
            logger.debug("get_input_state: 已找到 Cursor 窗口，开始遍历子控件查找 Edit/Document")
            for ctrl in wnd.descendants():
                try:
                    ctrl_type = ctrl.element_info.control_type
                    if ctrl_type in ("Edit", "Document"):
                        text = ctrl.get_value() if hasattr(ctrl, "get_value") else (ctrl.window_text() or "")
                        if text is None:
                            text = ""
                        out["ok"] = True
                        out["text"] = text
                        out["method"] = "uia"
                        logger.info("get_input_state: 找到输入框控件，当前内容长度=%s", len(text))
                        return out
                except Exception:
                    continue
        except ElementNotFoundError:
            pass
        # 调试：输出前若干个子控件的信息，方便分析 Cursor 输入框的真实控件类型
        try:
            logger.warning("get_input_state: 在 Cursor 窗口中未找到 Edit/Document 类型的输入框控件，开始输出部分子控件信息以便调试")
            for idx, ctrl in enumerate(wnd.descendants()):
                if idx >= 40:  # 避免日志过长，先看前 40 个
                    break
                try:
                    info = ctrl.element_info
                    logger.info(
                        "ctrl[%d]: type=%s, name=%r, auto_id=%r, class_name=%r, rect=%s",
                        idx,
                        getattr(info, "control_type", None),
                        getattr(info, "name", None),
                        getattr(info, "automation_id", None),
                        getattr(info, "class_name", None),
                        getattr(info, "rectangle", None),
                    )
                except Exception as e:
                    logger.debug("dump ctrl[%d] 失败: %s", idx, e)
        except Exception as e:
            logger.debug("遍历并输出子控件信息失败: %s", e)
        logger.warning("get_input_state: 在 Cursor 窗口中未找到 Edit/Document 类型的输入框控件（请查看上方 ctrl[...] 日志以便后续精确匹配）")
        out["error"] = "未在 Cursor 窗口中找到输入框控件（UIA）"
        return out
    except Exception as e:
        out["error"] = str(e)
        return out


def _paste_text_via_clipboard(text: str) -> bool:
    """用剪贴板粘贴文本（支持中文等 Unicode），粘贴后恢复原剪贴板。"""
    if not _pyperclip_ok:
        return False
    try:
        old = pyperclip.paste()
        pyperclip.copy(text)
        time.sleep(0.05)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.05)
        pyperclip.copy(old)
        return True
    except Exception as e:
        logger.debug("剪贴板粘贴失败: %s", e)
        return False


def write_and_send(text: str) -> dict[str, Any]:
    """
    往输入框写入内容并发送。
    中文等 Unicode 通过剪贴板 Ctrl+V 粘贴；发送优先 Enter，可选 Ctrl+Enter（见配置）。
    """
    if not text:
        return {"ok": False, "error": "内容为空"}
    if not _pywinauto_ok and not _pyautogui_ok:
        return {"ok": False, "error": "需要 pywinauto 或 pyautogui"}
    # 是否包含非 ASCII（如中文）→ 必须用剪贴板粘贴
    use_clipboard = any(ord(c) > 127 for c in text)
    send_hotkey = config.CURSOR_SEND_HOTKEY  # "Enter" 或 "Ctrl+Enter"
    try:
        if _pywinauto_ok:
            wnd = _find_cursor_window()
            if wnd:
                for ctrl in wnd.descendants():
                    try:
                        if ctrl.element_info.control_type not in ("Edit", "Document"):
                            continue
                        ctrl.set_focus()
                        time.sleep(0.25)
                        if use_clipboard and _pyperclip_ok and _pyautogui_ok:
                            _paste_text_via_clipboard(text)
                        else:
                            if hasattr(ctrl, "set_value"):
                                ctrl.set_value(text)
                            elif hasattr(ctrl, "set_edit_text"):
                                ctrl.set_edit_text(text)
                            else:
                                ctrl.type_keys(text.replace("}", "}}").replace("{", "{{"), with_spaces=True)
                        time.sleep(0.2)
                        # 发送：Enter 或 Ctrl+Enter（Cursor  composer 常用 Ctrl+Enter）
                        if send_hotkey == "Ctrl+Enter":
                            ctrl.type_keys("^{Enter}")
                        else:
                            ctrl.type_keys("{Enter}")
                        return {"ok": True, "method": "uia"}
                    except Exception:
                        continue
        if _pyautogui_ok:
            if use_clipboard and _pyperclip_ok:
                pyautogui.hotkey("ctrl", "a")
                time.sleep(0.05)
                _paste_text_via_clipboard(text)
            else:
                pyautogui.hotkey("ctrl", "a")
                time.sleep(0.05)
                pyautogui.write(text, interval=0.02)
            time.sleep(0.15)
            if send_hotkey == "Ctrl+Enter":
                pyautogui.hotkey("ctrl", "enter")
            else:
                pyautogui.press("enter")
            return {"ok": True, "method": "keyboard"}
        return {"ok": False, "error": "无法写入输入框（UIA 未找到控件且未使用键盘备用）"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _get_control_text(ctrl) -> str:
    """从控件取文本（window_text / get_value）。"""
    try:
        if hasattr(ctrl, "get_value"):
            v = ctrl.get_value()
            if v is not None and isinstance(v, str):
                return v
        if hasattr(ctrl, "window_text"):
            t = ctrl.window_text()
            if t is not None and isinstance(t, str):
                return t
    except Exception:
        pass
    return ""


def get_result() -> dict[str, Any]:
    """
    监控最后一条结果（AI 回复区域文本）。
    收集所有子控件中的文本，取最长的一段或合并多段作为结果；长度阈值放宽以便 Electron 多段文本也能命中。
    """
    out = {"ok": False, "text": "", "method": "none"}
    if not _pywinauto_ok:
        out["error"] = "未安装 pywinauto"
        return out
    try:
        wnd = _find_cursor_window()
        if not wnd:
            out["error"] = "未找到 Cursor 窗口"
            return out
        # 收集所有非空文本（长度 > 0），记录 (长度, 文本, 控件类型) 便于优先选 Document/Edit
        candidates = []
        text_by_type = []
        for ctrl in wnd.descendants():
            try:
                t = _get_control_text(ctrl)
                if not t or not t.strip():
                    continue
                ctrl_type = getattr(ctrl.element_info, "control_type", None)
                name = getattr(ctrl.element_info, "name", "") or ""
                auto_id = getattr(ctrl.element_info, "automation_id", "") or ""
                candidates.append((len(t), t.strip(), ctrl_type))
                # 便于调试：记录有内容的控件类型
                if len(t) >= 10:
                    text_by_type.append((ctrl_type, len(t), name[:30], auto_id[:30]))
            except Exception:
                continue
        if not candidates:
            logger.warning("get_result: 未找到任何有文本的控件；请确认 Cursor 已显示 AI 回复")
            out["error"] = "未找到任何结果文本区域"
            return out
        # 优先取最长的一段（通常为 AI 回复区）
        candidates.sort(key=lambda x: -x[0])
        best_len, best_text, _ = candidates[0]
        # 若最长一段仍较短，尝试合并多段（AI 回复可能被拆成多个 Text 控件）
        if best_len < 100 and len(candidates) > 1:
            # 按长度降序取前几段，用换行拼接，过滤掉过短且像 UI 文字的
            parts = []
            seen = set()
            for _, t, _ in candidates[:20]:
                if len(t) < 5 or t in seen:
                    continue
                seen.add(t)
                parts.append(t)
            if parts:
                combined = "\n\n".join(parts)[:12000]
                if len(combined) > best_len:
                    best_text = combined
                    best_len = len(combined)
        out["ok"] = True
        out["text"] = (best_text or "")[:12000]
        out["method"] = "uia"
        if best_len < 50:
            logger.info("get_result: 仅找到较短文本（%s 字），可能并非完整回复", best_len)
        return out
    except Exception as e:
        out["error"] = str(e)
        return out
