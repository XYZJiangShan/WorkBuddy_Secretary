"""
theme.py - 主题配色系统

提供浅色 / 深色两套主题的颜色常量，
所有 UI 组件通过 ThemeManager 读取当前主题色，
切换主题时触发信号，UI 组件重新应用样式。
"""

from __future__ import annotations

from dataclasses import dataclass
from PyQt6.QtCore import QObject, pyqtSignal


@dataclass(frozen=True)
class Theme:
    name: str

    # 背景色
    bg_card: str           # 主卡片背景
    bg_input: str          # 输入框背景
    bg_hover: str          # hover 背景
    bg_task_item: str      # 任务行背景
    bg_stats: str          # 统计卡片背景

    # 文字色
    text_primary: str      # 主文字
    text_secondary: str    # 次要文字
    text_placeholder: str  # 占位符

    # 品牌色（不随主题变化，可覆盖）
    accent: str            # 主品牌色（紫）
    accent_hover: str
    danger: str            # 危险/删除（红）
    success: str           # 成功/完成（绿）
    warning: str           # 警告（橙）

    # 边框
    border: str
    border_accent: str

    # 进度条轨道
    progress_track: str


LIGHT = Theme(
    name="light",
    bg_card="rgba(254, 252, 247, 0.93)",
    bg_input="rgba(255,255,255,0.6)",
    bg_hover="rgba(255,255,255,0.75)",
    bg_task_item="rgba(255,255,255,0.5)",
    bg_stats="rgba(108,99,255,0.07)",
    text_primary="#2D2B3D",
    text_secondary="#6B6880",
    text_placeholder="#A09DB8",
    accent="#6C63FF",
    accent_hover="#8B85FF",
    danger="#FF6B6B",
    success="#52C41A",
    warning="#FFB347",
    border="rgba(108, 99, 255, 0.15)",
    border_accent="rgba(108, 99, 255, 0.3)",
    progress_track="#DCD8F0",
)

DARK = Theme(
    name="dark",
    bg_card="rgba(30, 27, 48, 0.96)",
    bg_input="rgba(40, 36, 62, 0.8)",
    bg_hover="rgba(50, 46, 74, 0.85)",
    bg_task_item="rgba(40, 36, 62, 0.6)",
    bg_stats="rgba(108,99,255,0.12)",
    text_primary="#E8E5FF",
    text_secondary="#9994C0",
    text_placeholder="#5C5880",
    accent="#8B85FF",
    accent_hover="#A09AFF",
    danger="#FF8E8E",
    success="#6FD66F",
    warning="#FFD080",
    border="rgba(139, 133, 255, 0.2)",
    border_accent="rgba(139, 133, 255, 0.4)",
    progress_track="#3A3560",
)

THEMES = {"light": LIGHT, "dark": DARK}


class ThemeManager(QObject):
    """
    全局主题管理器（模块级单例，直接使用 theme_manager 实例）

    Signals:
        theme_changed(theme: Theme)  主题切换时广播，UI 监听后重新应用样式
    """

    theme_changed = pyqtSignal(object)  # object = Theme

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current: Theme = LIGHT

    @property
    def current(self) -> Theme:
        return self._current

    @property
    def is_dark(self) -> bool:
        return self._current.name == "dark"

    def set_theme(self, name: str) -> None:
        """切换主题（'light' 或 'dark'）"""
        if name not in THEMES:
            return
        if self._current.name == name:
            return
        self._current = THEMES[name]
        self.theme_changed.emit(self._current)

    def toggle(self) -> None:
        """在深色/浅色间切换"""
        self.set_theme("dark" if self._current.name == "light" else "light")


_theme_manager_instance: "ThemeManager | None" = None


def get_theme_manager() -> "ThemeManager":
    """获取全局 ThemeManager 单例（懒初始化，确保 QApplication 已存在）"""
    global _theme_manager_instance
    if _theme_manager_instance is None:
        _theme_manager_instance = ThemeManager()
    return _theme_manager_instance


# 向后兼容：直接用 theme_manager 的地方通过 property 代理
class _ThemeManagerProxy:
    """代理对象，第一次访问时才真正初始化 ThemeManager"""
    def __getattr__(self, name):
        return getattr(get_theme_manager(), name)


theme_manager = _ThemeManagerProxy()
