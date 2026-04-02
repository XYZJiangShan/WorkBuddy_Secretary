"""
tray_icon.py - 系统托盘图标与菜单

提供：
  - 系统托盘常驻图标（程序关闭按钮只隐藏主窗口，不退出进程）
  - 右键菜单：显示/隐藏 | 设置 | 立即休息提醒 | 退出
  - 双击托盘图标显示/隐藏悬浮窗
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap, QFont
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon, QWidget


def _make_default_icon(size: int = 32) -> QIcon:
    """生成一个简单的紫色圆形默认图标（无需外部图片文件）"""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    # 紫色圆形背景
    painter.setBrush(QColor("#6C63FF"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(2, 2, size - 4, size - 4)
    # 白色机器人头像文字（简单符号）
    painter.setPen(QColor("white"))
    font = QFont("Segoe UI Emoji", size // 3)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "秘")
    painter.end()
    return QIcon(pixmap)


def _load_icon() -> QIcon:
    """加载托盘图标，优先使用 assets/icon.png，不存在则生成默认"""
    # 打包后路径兼容
    base = getattr(sys, "_MEIPASS", None)
    if base:
        icon_path = Path(base) / "assets" / "icon.png"
    else:
        icon_path = Path(__file__).parent.parent / "assets" / "icon.png"

    if icon_path.exists():
        return QIcon(str(icon_path))
    return _make_default_icon()


class TrayIcon(QSystemTrayIcon):
    """
    系统托盘图标

    Signals:
        show_window()         请求显示主窗口
        hide_window()         请求隐藏主窗口
        open_settings()       请求打开设置
        trigger_reminder()    立即触发一次提醒
        quit_app()            退出程序
    """

    show_window = pyqtSignal()
    hide_window = pyqtSignal()
    open_settings = pyqtSignal()
    open_weekly_report = pyqtSignal()
    trigger_reminder = pyqtSignal()
    quit_app = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(_load_icon(), parent)
        self._window_visible: bool = True
        self._setup_menu()
        self._connect_signals()
        self.setToolTip("小秘书 - 桌面助手")

    # ------------------------------------------------------------------ #
    #  菜单构建
    # ------------------------------------------------------------------ #

    def _setup_menu(self) -> None:
        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background: rgba(254, 252, 247, 0.98);
                border: 1px solid rgba(108,99,255,0.2);
                border-radius: 10px;
                padding: 4px;
                font-family: "Microsoft YaHei";
                font-size: 12px;
                color: #2D2B3D;
            }
            QMenu::item {
                padding: 6px 18px;
                border-radius: 6px;
            }
            QMenu::item:selected {
                background: rgba(108,99,255,0.12);
                color: #6C63FF;
            }
            QMenu::separator {
                height: 1px;
                background: rgba(108,99,255,0.12);
                margin: 3px 8px;
            }
        """)

        self._toggle_action = QAction("隐藏窗口", menu)
        self._toggle_action.triggered.connect(self._on_toggle_window)
        menu.addAction(self._toggle_action)

        menu.addSeparator()

        settings_action = QAction("⚙️  设置", menu)
        settings_action.triggered.connect(self.open_settings)
        menu.addAction(settings_action)

        weekly_action = QAction("📝  周报", menu)
        weekly_action.triggered.connect(self.open_weekly_report)
        menu.addAction(weekly_action)

        remind_action = QAction("🔔  立即提醒", menu)
        remind_action.triggered.connect(self.trigger_reminder)
        menu.addAction(remind_action)

        menu.addSeparator()

        quit_action = QAction("退出", menu)
        quit_action.triggered.connect(self.quit_app)
        menu.addAction(quit_action)

        self.setContextMenu(menu)

    # ------------------------------------------------------------------ #
    #  信号连接
    # ------------------------------------------------------------------ #

    def _connect_signals(self) -> None:
        self.activated.connect(self._on_activated)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._on_toggle_window()

    def _on_toggle_window(self) -> None:
        if self._window_visible:
            self.hide_window.emit()
        else:
            self.show_window.emit()

    # ------------------------------------------------------------------ #
    #  公共 API
    # ------------------------------------------------------------------ #

    def set_window_visible(self, visible: bool) -> None:
        """同步窗口可见状态，更新菜单文字"""
        self._window_visible = visible
        self._toggle_action.setText("隐藏窗口" if visible else "显示窗口")

    def notify(self, title: str, message: str) -> None:
        """发送系统托盘气泡通知"""
        self.showMessage(
            title,
            message,
            QSystemTrayIcon.MessageIcon.Information,
            4000,  # 显示 4 秒
        )
