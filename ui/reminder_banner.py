"""
reminder_banner.py - 休息提醒横幅组件

在悬浮窗顶部以动画方式滑入/滑出，展示 AI 生成的提醒文案。
设计：奶油色+彩色左边框卡片，带关闭按钮和"稍后提醒"按钮。
"""

from __future__ import annotations

from PyQt6.QtCore import (
    QEasingCurve, QPropertyAnimation, QRect, Qt, pyqtSignal, QSize
)
from PyQt6.QtGui import QColor, QFont, QPainter, QPaintEvent, QPen
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)


class ReminderBanner(QWidget):
    """
    提醒横幅，嵌入 FloatingWindow 的顶部区域。

    Signals:
        closed()           用户点击关闭按钮
        snoozed(seconds)   用户点击"稍后提醒"（默认 300 秒）
    """

    closed = pyqtSignal()
    snoozed = pyqtSignal(int)

    # 彩色左侧边条颜色（循环使用，每次提醒换一个）
    _ACCENT_COLORS = ["#6C63FF", "#FF6B6B", "#FFB347", "#52C41A", "#36CFC9"]
    _color_index: int = 0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._accent = self._ACCENT_COLORS[0]
        self._anim: QPropertyAnimation | None = None
        self._setup_ui()
        self.hide()

    # ------------------------------------------------------------------ #
    #  UI 搭建
    # ------------------------------------------------------------------ #

    def _setup_ui(self) -> None:
        self.setObjectName("ReminderBanner")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("""
            #ReminderBanner {
                background: rgba(255, 252, 245, 0.97);
                border-radius: 10px;
            }
        """)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        # ---- 左边色条 ----
        self._stripe = QWidget(self)
        self._stripe.setFixedWidth(4)
        self._stripe.setObjectName("stripe")

        # ---- 图标 + 文案 ----
        self._icon_label = QLabel("🔔")
        self._icon_label.setFont(QFont("Segoe UI Emoji", 16))
        self._icon_label.setFixedSize(QSize(28, 28))
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._text_label = QLabel()
        self._text_label.setWordWrap(True)
        self._text_label.setFont(QFont("Microsoft YaHei", 10))
        self._text_label.setStyleSheet("color: #2D2B3D;")
        self._text_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        # ---- 按钮区 ----
        self._snooze_btn = QPushButton("稍后")
        self._snooze_btn.setFixedSize(QSize(46, 26))
        self._snooze_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._snooze_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: 1px solid #C0BDDE;
                border-radius: 5px;
                color: #6B6880;
                font-size: 11px;
            }
            QPushButton:hover { background: #F0EEF8; }
        """)

        self._close_btn = QPushButton("✕")
        self._close_btn.setFixedSize(QSize(24, 24))
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: #A09DB8;
                font-size: 12px;
            }
            QPushButton:hover { color: #FF6B6B; }
        """)

        self._snooze_btn.clicked.connect(self._on_snooze)
        self._close_btn.clicked.connect(self._on_close)

        # ---- 布局 ----
        btn_col = QVBoxLayout()
        btn_col.setSpacing(4)
        btn_col.addWidget(self._snooze_btn)
        btn_col.addWidget(self._close_btn)

        content_row = QHBoxLayout()
        content_row.setSpacing(8)
        content_row.addWidget(self._icon_label)
        content_row.addWidget(self._text_label, 1)
        content_row.addLayout(btn_col)

        # 把 stripe + content 水平排列
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 8, 0)
        outer.setSpacing(0)
        outer.addWidget(self._stripe)
        inner_wrap = QWidget()
        inner_layout = QVBoxLayout(inner_wrap)
        inner_layout.setContentsMargins(8, 8, 0, 8)
        inner_layout.setSpacing(0)
        inner_layout.addLayout(content_row)
        outer.addWidget(inner_wrap, 1)

    # ------------------------------------------------------------------ #
    #  公共 API
    # ------------------------------------------------------------------ #

    def show_text(self, text: str) -> None:
        """展示新的提醒文案，带滑入动画"""
        # 轮换口音色
        self._accent = self._ACCENT_COLORS[
            self._color_index % len(self._ACCENT_COLORS)
        ]
        ReminderBanner._color_index += 1

        self._stripe.setStyleSheet(
            f"background: {self._accent}; border-radius: 2px;"
        )
        self._text_label.setText(text)
        self._play_slide_in()

    def dismiss(self) -> None:
        """收起横幅（带滑出动画）"""
        self._play_slide_out()

    # ------------------------------------------------------------------ #
    #  槽
    # ------------------------------------------------------------------ #

    def _on_close(self) -> None:
        self.dismiss()
        self.closed.emit()

    def _on_snooze(self) -> None:
        self.dismiss()
        self.snoozed.emit(300)

    # ------------------------------------------------------------------ #
    #  动画
    # ------------------------------------------------------------------ #

    def _play_slide_in(self) -> None:
        """从上方滑入"""
        self.show()
        target_h = self.sizeHint().height() or 64
        start_rect = QRect(self.x(), -target_h, self.width(), target_h)
        end_rect = QRect(self.x(), 0, self.width(), target_h)

        anim = QPropertyAnimation(self, b"geometry", self)
        anim.setDuration(300)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.setStartValue(start_rect)
        anim.setEndValue(end_rect)
        anim.start()
        self._anim = anim

    def _play_slide_out(self) -> None:
        """向上滑出后 hide"""
        h = self.height() or 64
        start_rect = self.geometry()
        end_rect = QRect(self.x(), -h, self.width(), h)

        anim = QPropertyAnimation(self, b"geometry", self)
        anim.setDuration(250)
        anim.setEasingCurve(QEasingCurve.Type.InCubic)
        anim.setStartValue(start_rect)
        anim.setEndValue(end_rect)
        anim.finished.connect(self.hide)
        anim.start()
        self._anim = anim
