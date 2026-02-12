# -*- coding: utf-8 -*-
"""
本地 Cursor 控制器：创建文件夹、用 Cursor 打开目录、监控/写入输入框。
依赖：pywinauto (UIA)、pyautogui（备用）、config。
"""

import json
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
# projectId -> 该工程对应窗口的文件夹名（用于多窗口时按 projectId 定位）
_project_windows: dict[str, str] = {}


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


def create_folder(
    path: str,
    project_id: Optional[str] = None,
    project_name: Optional[str] = None,
) -> dict[str, Any]:
    """
    创建文件夹（含多级）。路径可为绝对或相对 config.PROJECT_ROOT。
    若传入 project_id，创建成功后在目录下建 .project 子目录，并在其中写入 project.json，
    内容为 {"projectId": "...", "projectName": "..."}；projectName 未传时用目录名。
    """
    try:
        p = Path(path)
        if not p.is_absolute():
            p = config.PROJECT_ROOT / p
        p.mkdir(parents=True, exist_ok=True)
        resolved = str(p.resolve())

        if project_id is not None and project_id != "":
            dot_project = p / ".project"
            dot_project.mkdir(parents=True, exist_ok=True)
            name = (project_name or p.name) if project_name is not None else p.name
            project_json = dot_project / "project.json"
            data = {"projectId": project_id, "projectName": name}
            project_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info("已写入 %s: projectId=%s, projectName=%s", project_json, project_id, name)

        return {"ok": True, "path": resolved}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def open_cursor(folder_path: str, project_id: Optional[str] = None) -> dict[str, Any]:
    """用 Cursor 打开指定文件夹。若传 project_id 则登记到 projectId->窗口 映射表，便于后续按 projectId 操作对应窗口。"""
    global _last_opened_folder_name, _project_windows
    try:
        p = Path(folder_path)
        if not p.is_absolute():
            p = config.PROJECT_ROOT / p
        if not p.is_dir():
            return {"ok": False, "error": f"目录不存在: {p}"}
        path_str = str(p.resolve())
        folder_name = p.name
        _last_opened_folder_name = folder_name
        if project_id:
            _project_windows[project_id] = folder_name
            logger.info("登记 projectId=%s -> 窗口(文件夹名)=%s", project_id, folder_name)
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


def _find_cursor_window(project_id: Optional[str] = None):
    """查找 Cursor 主窗口（UIA）。project_id 为空则用“上次打开的文件夹名”；否则用 projectId 映射表中的文件夹名优先匹配对应窗口。"""
    if not _pywinauto_ok:
        logger.warning("pywinauto 未安装，无法查找 Cursor 窗口")
        return None
    try:
        from pywinauto import Application
        from pywinauto import Desktop
    except Exception as e:
        logger.error("导入 pywinauto 失败: %s", e)
        return None

    preferred_folder = (_project_windows.get(project_id) if project_id else None) or _last_opened_folder_name

    # 1) 枚举标题含 Cursor 的顶层窗口，若有 preferred_folder 则优先选标题含该名的
    try:
        desktop = Desktop(backend="uia")
        cursor_windows = desktop.windows(title_re=".*Cursor.*")
        if cursor_windows and preferred_folder:
            for wnd in cursor_windows:
                try:
                    title = wnd.window_text() or ""
                    if preferred_folder in title:
                        logger.info("按标题匹配到窗口(project_id=%s): %s", project_id, title[:80])
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
            if preferred_folder and wnd.window_text() and preferred_folder not in wnd.window_text():
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


def _parse_hotkey(hotkey_str: str) -> list[str]:
    """将配置中的热键字符串（如 'Ctrl+L'、'Ctrl+Shift+I'）解析为 pyautogui.hotkey 的参数列表。"""
    if not hotkey_str or not hotkey_str.strip():
        return []
    parts = [p.strip() for p in hotkey_str.split("+") if p.strip()]
    if not parts:
        return []
    key_map = {
        "ctrl": "ctrl", "control": "ctrl",
        "alt": "alt",
        "shift": "shift",
        "win": "win", "windows": "win", "meta": "win", "cmd": "command",
        "command": "command",
    }
    modifiers = []
    main_key = None
    for p in parts:
        lower = p.lower()
        if lower in key_map:
            mod = key_map[lower]
            if mod != "command" or sys.platform != "win32":
                modifiers.append(mod if mod != "command" else "ctrl")
            else:
                modifiers.append("ctrl")
        else:
            main_key = (p.lower() if len(p) == 1 else lower)
            break
    if main_key is None and parts:
        main_key = parts[-1].lower() if len(parts[-1]) > 1 else parts[-1].lower()
    if main_key is None:
        return []
    return [*modifiers, main_key]


def open_new_agent(project_id: Optional[str] = None) -> dict[str, Any]:
    """
    打开新的 Agent（Chat/Composer）：先聚焦对应 projectId 的 Cursor 窗口，再发送配置的热键。
    热键由 config.CURSOR_OPEN_AGENT_HOTKEY 配置，默认 Ctrl+Shift+L。
    """
    if not _pyautogui_ok:
        return {"ok": False, "error": "需要 pyautogui 才能发送热键"}
    keys = _parse_hotkey(config.CURSOR_OPEN_AGENT_HOTKEY)
    if not keys:
        return {"ok": False, "error": f"无效的热键配置: {config.CURSOR_OPEN_AGENT_HOTKEY}"}
    try:
        if _pywinauto_ok:
            wnd = _find_cursor_window(project_id)
            if wnd:
                wnd.set_focus()
                time.sleep(0.2)
        pyautogui.hotkey(*keys)
        return {"ok": True, "hotkey": config.CURSOR_OPEN_AGENT_HOTKEY}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_input_state(project_id: Optional[str] = None) -> dict[str, Any]:
    """
    监控当前输入框状态（Chat/Composer 输入区）。
    project_id 指定时在对应工程窗口内查找；否则用上次打开的窗口。
    """
    out = {"ok": False, "text": "", "focused": False, "method": "none"}
    if not _pywinauto_ok:
        out["error"] = "未安装 pywinauto"
        return out
    try:
        wnd = _find_cursor_window(project_id)
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


def _dump_send_candidates(wnd) -> None:
    """调试用：把窗口中所有可点击的 Button/Hyperlink/Image 的 name、automation_id 打到日志，便于在 Cursor 里找到发送按钮。"""
    if not _pywinauto_ok:
        return
    want_types = ("Button", "Hyperlink", "Image")
    try:
        candidates = []
        for ctrl in wnd.descendants():
            try:
                ct = getattr(ctrl.element_info, "control_type", None)
                if ct not in want_types:
                    continue
                name = (getattr(ctrl.element_info, "name", None) or "") or ""
                auto_id = (getattr(ctrl.element_info, "automation_id", None) or "") or ""
                rect = getattr(ctrl.element_info, "rectangle", None)
                candidates.append((ct, name, auto_id, rect))
            except Exception:
                continue
        if candidates:
            logger.info("发送按钮候选控件（共 %d 个，便于在 Cursor 中确认发送按钮）:", len(candidates))
            for i, (ct, name, auto_id, rect) in enumerate(candidates[:30]):
                logger.info("  [%d] type=%s name=%r automation_id=%r rect=%s", i, ct, name or None, auto_id or None, rect)
            if len(candidates) > 30:
                logger.info("  ... 还有 %d 个未列出", len(candidates) - 30)
    except Exception as e:
        logger.debug("dump 候选控件失败: %s", e)


def _find_and_click_send_button(wnd) -> bool:
    """
    在 Cursor 窗口内查找“发送”按钮并点击。
    匹配 Button/Hyperlink/Image 的 name 或 automation_id 包含 send、submit、提交、发送、arrow 等。
    返回是否找到并点击成功。未找到时会 dump 候选控件到日志便于调试。
    """
    if not _pywinauto_ok:
        return False
    keywords = ("send", "submit", "提交", "发送", "arrow", "composer", "chat")
    exclude = ("new", "create", "newchat", "新对话", "clear", "stop", "cancel")
    # Cursor 可能是 Button，也可能是 Hyperlink/Image（图标按钮）
    want_types = ("Button", "Hyperlink", "Image")
    try:
        for ctrl in wnd.descendants():
            try:
                ct = ctrl.element_info.control_type
                if ct not in want_types:
                    continue
                name = (getattr(ctrl.element_info, "name", None) or "") or ""
                auto_id = (getattr(ctrl.element_info, "automation_id", None) or "") or ""
                combined = (name + " " + auto_id).lower()
                if any(n in combined for n in exclude):
                    continue
                if any(kw in combined for kw in keywords):
                    ctrl.click()
                    logger.info("已点击发送按钮: type=%s name=%r automation_id=%r", ct, name or None, auto_id or None)
                    return True
            except Exception:
                continue
        # 未找到时输出候选，方便在 Cursor 里对照界面确认发送按钮的 name/automation_id
        _dump_send_candidates(wnd)
        return False
    except Exception as e:
        logger.debug("查找发送按钮失败: %s", e)
        return False


def write_and_send(text: str, project_id: Optional[str] = None) -> dict[str, Any]:
    """
    往输入框写入内容并发送。
    project_id 指定时在对应工程窗口内操作；否则用上次打开的窗口。
    """
    if not text:
        return {"ok": False, "error": "内容为空"}
    if not _pywinauto_ok and not _pyautogui_ok:
        return {"ok": False, "error": "需要 pywinauto 或 pyautogui"}
    # 是否包含非 ASCII（如中文）→ 必须用剪贴板粘贴
    use_clipboard = any(ord(c) > 127 for c in text)
    send_keys = _parse_hotkey(config.CURSOR_SEND_HOTKEY)  # 如 ["ctrl", "shift", "enter"]
    if not send_keys:
        return {"ok": False, "error": f"无效的发送热键配置: {config.CURSOR_SEND_HOTKEY}"}
    try:
        if _pywinauto_ok:
            wnd = _find_cursor_window(project_id)
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
                        # 等待内容落盘后，确保输入框保持焦点，再用 Ctrl+Shift+Enter 发送
                        time.sleep(0.4)
                        wnd.set_focus()
                        time.sleep(0.15)
                        ctrl.set_focus()
                        time.sleep(0.25)  # 留足时间让焦点稳定到输入框，否则热键可能被其它控件吃掉
                        logger.info("write_and_send: 即将发送热键 %s -> %s", config.CURSOR_SEND_HOTKEY, send_keys)
                        if _pyautogui_ok:
                            pyautogui.hotkey(*send_keys)
                        else:
                            # pywinauto type_keys：^=Ctrl +=Shift，主键用 {Enter} 等
                            mod_map = {"ctrl": "^", "shift": "+", "alt": "%", "win": "win"}
                            prefix = "".join(mod_map.get(k, "") for k in send_keys[:-1] if k in mod_map)
                            main = send_keys[-1]
                            key_str = prefix + (main if len(main) > 1 else main.upper())
                            if main in ("enter", "return", "tab", "space", "escape"):
                                key_str = prefix + "{" + main.capitalize() + "}"
                            ctrl.type_keys(key_str)
                        return {"ok": True, "method": "uia"}
                    except Exception:
                        continue
        if _pyautogui_ok:
            if use_clipboard and _pyperclip_ok:
                pyautogui.hotkey("ctrl", "a")
                time.sleep(0.05)
                _paste_text_via_clipboard(text)
                time.sleep(0.15)
            else:
                pyautogui.hotkey("ctrl", "a")
                time.sleep(0.05)
                pyautogui.write(text, interval=0.02)
            time.sleep(0.4)
            # 统一用配置的热键发送（Cursor 默认 Ctrl+Shift+Enter），稍等确保焦点在输入区
            time.sleep(0.2)
            logger.info("write_and_send: 即将发送热键 %s -> %s (method=keyboard)", config.CURSOR_SEND_HOTKEY, send_keys)
            pyautogui.hotkey(*send_keys)
            return {"ok": True, "method": "keyboard"}
        return {"ok": False, "error": "无法写入输入框（UIA 未找到控件且未使用键盘备用）"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


