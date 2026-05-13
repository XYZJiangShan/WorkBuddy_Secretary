"""
reminder_popup.py - 休息提醒弹窗

从底部进度条点击或倒计时到达时展开的浮动弹窗。
显示 AI 生成的提醒文案 + 延迟选项（2分钟/5分钟/跳过）。
深色风格，与主窗口一致。

使用 show() 模式打开（非 exec()），parent=None 独立窗口。
遵循 Bug 记录 #9 的规则：show() 弹窗延迟设 WindowStaysOnTopHint。
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QSize
from PyQt6.QtGui import QFont, QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)


class ReminderPopup(QWidget):
    """
    休息提醒弹窗

    Signals:
        dismissed()          用户点击关闭
        snoozed(seconds)     用户点击延迟（携带延迟秒数）
    """

    dismissed = pyqtSignal()
    snoozed = pyqtSignal(int)

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text = text
        self._setup_window()
        self._setup_ui()

        # 延迟 200ms 设置置顶（遵循 Bug 记录 #9）
        QTimer.singleShot(200, self._set_top)

        # 30 秒后自动关闭
        self._auto_close_timer = QTimer(self)
        self._auto_close_timer.setSingleShot(True)
        self._auto_close_timer.setInterval(30_000)
        self._auto_close_timer.timeout.connect(self.close)
        self._auto_close_timer.start()

    def _setup_window(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(280)

    def _set_top(self) -> None:
        """延迟设置置顶"""
        if self.isVisible():
            self.raise_()

    def _setup_ui(self) -> None:
        self.setStyleSheet("""
            QWidget {
                background: rgba(30, 27, 48, 0.97);
                border-radius: 12px;
                border: 1px solid rgba(139, 133, 255, 0.3);
            }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        # ---- 标题行 ----
        title_row = QHBoxLayout()
        title_row.setSpacing(6)

        icon = QLabel("🔔")
        icon.setFont(QFont("Segoe UI Emoji", 14))
        icon.setFixedWidth(24)
        icon.setStyleSheet("background: transparent; border: none;")

        title = QLabel("休息提醒")
        title.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        title.setStyleSheet("color: #8B85FF; background: transparent; border: none;")

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(20, 20)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet("""
            QPushButton {
                background: transparent; border: none;
                color: #5C5880; font-size: 11px;
            }
            QPushButton:hover { color: #FF6B6B; }
        """)
        close_btn.clicked.connect(self._on_dismiss)

        title_row.addWidget(icon)
        title_row.addWidget(title)
        title_row.addStretch()
        title_row.addWidget(close_btn)
        root.addLayout(title_row)

        # ---- 文案内容 ----
        self._text_label = QLabel(self._text)
        self._text_label.setWordWrap(True)
        self._text_label.setFont(QFont("Microsoft YaHei", 10))
        self._text_label.setStyleSheet(
            "color: #E8E5FF; background: transparent; border: none; "
            "padding: 4px 0px;"
        )
        self._text_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        root.addWidget(self._text_label)

        # ---- 延迟按钮行 ----
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        btn_2m = self._make_btn("2 分钟后", 120)
        btn_5m = self._make_btn("5 分钟后", 300)
        btn_skip = self._make_btn("知道了", 0)
        btn_skip.setStyleSheet("""
            QPushButton {
                background: rgba(139, 133, 255, 0.2);
                border: 1px solid rgba(139, 133, 255, 0.4);
                border-radius: 6px; color: #8B85FF;
                font-size: 10px; padding: 4px 10px;
            }
            QPushButton:hover {
                background: rgba(139, 133, 255, 0.35);
            }
        """)

        btn_row.addWidget(btn_2m)
        btn_row.addWidget(btn_5m)
        btn_row.addStretch()
        btn_row.addWidget(btn_skip)
        root.addLayout(btn_row)

    def _make_btn(self, text: str, snooze_seconds: int) -> QPushButton:
        btn = QPushButton(text)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: 1px solid rgba(139, 133, 255, 0.25);
                border-radius: 6px; color: #9994C0;
                font-size: 10px; padding: 4px 10px;
            }
            QPushButton:hover {
                background: rgba(139, 133, 255, 0.15);
                color: #E8E5FF;
            }
        """)
        if snooze_seconds > 0:
            btn.clicked.connect(lambda: self._on_snooze(snooze_seconds))
        else:
            btn.clicked.connect(self._on_dismiss)
        return btn

    def _on_dismiss(self) -> None:
        self.dismissed.emit()
        self.close()

    def _on_snooze(self, seconds: int) -> None:
        self.snoozed.emit(seconds)
        self.close()

    def set_text(self, text: str) -> None:
        self._text = text
        self._text_label.setText(text)
