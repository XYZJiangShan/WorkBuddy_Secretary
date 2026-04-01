"""
hotkey_service.py - 全局热键服务（Windows RegisterHotKey 版）

使用 Windows 原生 RegisterHotKey/UnregisterHotKey API，
完全运行在主线程，通过 Qt nativeEvent 接收消息，
不再使用 keyboard 库的子线程钩子，彻底避免 COM 冲突（0x8001010d）。
"""

from __future__ import annotations

import ctypes
import logging
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal, QAbstractNativeEventFilter, QByteArray
from PyQt6.QtWidgets import QApplication

logger = logging.getLogger(__name__)

# Windows 消息常量
WM_HOTKEY = 0x0312
MOD_ALT   = 0x0001
MOD_CTRL  = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN   = 0x0008

# 热键 ID（任意非零整数，避免与系统冲突）
HOTKEY_ID = 0x7E01

user32 = ctypes.windll.user32


def _parse_hotkey(hotkey_str: str) -> tuple[int, int]:
    """
    把 'alt+space' / 'ctrl+shift+t' 这类字符串解析为 (modifiers, vk_code)
    支持：alt / ctrl / shift / win + 单字母或特殊键名
    """
    import string

    parts = [p.strip().lower() for p in hotkey_str.split("+")]
    mods = 0
    vk = 0

    key_map: dict[str, int] = {
        "space": 0x20, "enter": 0x0D, "esc": 0x1B, "escape": 0x1B,
        "tab": 0x09, "backspace": 0x08, "delete": 0x2E, "insert": 0x2D,
        "home": 0x24, "end": 0x23, "pgup": 0x21, "pgdn": 0x22,
        "pageup": 0x21, "pagedown": 0x22,
        "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73,
        "f5": 0x74, "f6": 0x75, "f7": 0x76, "f8": 0x77,
        "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
    }

    for part in parts:
        if part in ("alt",):
            mods |= MOD_ALT
        elif part in ("ctrl", "control"):
            mods |= MOD_CTRL
        elif part in ("shift",):
            mods |= MOD_SHIFT
        elif part in ("win", "windows"):
            mods |= MOD_WIN
        elif part in key_map:
            vk = key_map[part]
        elif len(part) == 1 and part in string.ascii_lowercase:
            vk = ord(part.upper())  # A-Z 的虚拟键码 = 大写 ASCII
        else:
            logger.warning("未识别的热键部分: %r，忽略", part)

    return mods, vk


class _HotkeyEventFilter(QAbstractNativeEventFilter):
    """Qt 原生事件过滤器，拦截 WM_HOTKEY 消息"""

    def __init__(self, callback):
        super().__init__()
        self._callback = callback

    def nativeEventFilter(self, event_type: QByteArray, message) -> tuple[bool, int]:
        # 仅处理 Windows 消息
        if event_type == b"windows_generic_MSG":
            try:
                import ctypes.wintypes
                msg = ctypes.cast(int(message), ctypes.POINTER(ctypes.wintypes.MSG)).contents
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    self._callback()
                    return True, 0
            except Exception:
                pass
        return False, 0


class HotkeyService(QObject):
    """
    全局热键服务（Windows RegisterHotKey，主线程，无子线程）

    Signals:
        toggle_window()    热键触发，请求切换窗口显示状态
        hotkey_error(msg)  热键注册失败
    """

    toggle_window = pyqtSignal()
    hotkey_error  = pyqtSignal(str)

    def __init__(self, hotkey: str = "alt+space", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._hotkey = hotkey
        self._registered = False
        self._event_filter: Optional[_HotkeyEventFilter] = None
        self._retry_count = 0
        self._MAX_RETRIES = 3

    # ------------------------------------------------------------------ #
    #  公共 API
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        if self._registered:
            return
        self._retry_count = 0
        self._register()

    def stop(self) -> None:
        self._unregister()

    def update_hotkey(self, hotkey: str) -> None:
        self._unregister()
        self._hotkey = hotkey
        self._register()

    # ------------------------------------------------------------------ #
    #  内部
    # ------------------------------------------------------------------ #

    def _register(self) -> None:
        try:
            mods, vk = _parse_hotkey(self._hotkey)
            if vk == 0:
                raise ValueError(f"无法识别热键主键: {self._hotkey!r}")

            ok = user32.RegisterHotKey(None, HOTKEY_ID, mods, vk)
            if not ok:
                err = ctypes.GetLastError()
                # 1409 = ERROR_HOTKEY_ALREADY_REGISTERED，先注销再注册
                if err == 1409:
                    user32.UnregisterHotKey(None, HOTKEY_ID)
                    ok = user32.RegisterHotKey(None, HOTKEY_ID, mods, vk)

            if ok:
                self._registered = True
                # 安装原生事件过滤器
                self._event_filter = _HotkeyEventFilter(self._on_hotkey_fired)
                app = QApplication.instance()
                if app:
                    app.installNativeEventFilter(self._event_filter)
                logger.info("HotkeyService 已启动，热键：%s (mods=0x%x, vk=0x%x)",
                            self._hotkey, mods, vk)
            else:
                err = ctypes.GetLastError()
                # 仍然失败（可能有残留进程占用），最多重试3次
                if err == 1409:
                    self._retry_count += 1
                    if self._retry_count <= self._MAX_RETRIES:
                        logger.warning("热键被占用，%d秒后重试(%d/%d)...",
                                       self._retry_count, self._retry_count, self._MAX_RETRIES)
                        from PyQt6.QtCore import QTimer
                        QTimer.singleShot(self._retry_count * 1000, self._register)
                    else:
                        logger.warning("热键 %s 被其他程序占用，Alt+Space 功能不可用", self._hotkey)
                else:
                    msg = f"RegisterHotKey 失败，错误码: {err}"
                    logger.error(msg)
                    self.hotkey_error.emit(msg)

        except Exception as e:
            msg = f"热键注册异常: {e}"
            logger.error(msg)
            self.hotkey_error.emit(msg)

    def _unregister(self) -> None:
        if self._registered:
            user32.UnregisterHotKey(None, HOTKEY_ID)
            self._registered = False
            logger.info("HotkeyService 已停止")
        if self._event_filter:
            app = QApplication.instance()
            if app:
                app.removeNativeEventFilter(self._event_filter)
            self._event_filter = None

    def _on_hotkey_fired(self) -> None:
        logger.debug("热键触发: %s", self._hotkey)
        self.toggle_window.emit()
