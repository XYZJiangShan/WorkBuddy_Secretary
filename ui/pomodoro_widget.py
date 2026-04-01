"""
pomodoro_widget.py - 番茄钟 UI 面板（支持主题切换）
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import (
    QColor, QFont, QPainter, QPen, QBrush, QLinearGradient
)
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

from services.pomodoro_service import PomodoroService, PomodoroState


# --------------------------------------------------------------------------- #
#  番茄钟进度大圆环
# --------------------------------------------------------------------------- #

class _PomodoroRing(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._ratio = 1.0
        self._seconds_left = 0
        self._state = PomodoroState.IDLE
        self._text_color = QColor("#2D2B3D")       # 随主题变
        self._track_color = QColor("#E8E6F5")      # 随主题变
        self.setFixedSize(110, 110)

    def set_theme_colors(self, text_color: str, track_color: str) -> None:
        self._text_color = QColor(text_color)
        self._track_color = QColor(track_color)
        self.update()

    def update_state(self, state: PomodoroState, seconds_left: int, total: int) -> None:
        self._state = state
        self._seconds_left = seconds_left
        self._ratio = seconds_left / total if total > 0 else 1.0
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w // 2, h // 2
        r = min(w, h) // 2 - 10

        # 背景轨道
        p.setPen(QPen(self._track_color, 8))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(cx - r, cy - r, r * 2, r * 2)

        # 进度弧
        if self._ratio > 0 and self._state != PomodoroState.IDLE:
            colors = {
                PomodoroState.FOCUS: ("#FF6B6B", "#FF8E53"),
                PomodoroState.SHORT_BREAK: ("#52C41A", "#95DE64"),
                PomodoroState.LONG_BREAK: ("#36CFC9", "#5CDBD3"),
            }
            c1, _ = colors.get(self._state, ("#6C63FF", "#8B85FF"))
            pen = QPen(QColor(c1), 8)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            span = int(-self._ratio * 360 * 16)
            p.drawArc(cx - r, cy - r, r * 2, r * 2, 90 * 16, span)

        # 时间文字
        m, s = divmod(self._seconds_left, 60)
        time_str = f"{m:02d}:{s:02d}" if self._state != PomodoroState.IDLE else "--:--"
        p.setPen(self._text_color)
        p.setFont(QFont("Microsoft YaHei", 16, QFont.Weight.Bold))
        p.drawText(self.rect().adjusted(0, -8, 0, -8), Qt.AlignmentFlag.AlignCenter, time_str)

        # 状态 emoji
        emoji = {"focus": "🍅", "short_break": "☕", "long_break": "🌿", "idle": "▶"}.get(
            self._state.value, ""
        )
        p.setFont(QFont("Segoe UI Emoji", 13))
        p.drawText(self.rect().adjusted(0, 26, 0, 26), Qt.AlignmentFlag.AlignCenter, emoji)
        p.end()


# --------------------------------------------------------------------------- #
#  番茄钟面板
# --------------------------------------------------------------------------- #

class PomodoroWidget(QWidget):
    """
    番茄钟完整控制面板，支持 apply_theme(theme) 响应深色/浅色切换

    Signals:
        closed()  用户点击关闭隐藏面板
    """

    closed = pyqtSignal()

    def __init__(self, pomodoro: PomodoroService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pomodoro = pomodoro
        self._setup_ui()
        self._connect_signals()
        self._update_buttons()

    def _setup_ui(self) -> None:
        self.setObjectName("PomodoroWidget")
        self.setStyleSheet("""
            #PomodoroWidget {
                background: rgba(255, 250, 245, 0.95);
                border-radius: 14px;
                border: 1px solid rgba(255, 107, 107, 0.2);
            }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(8)

        # ---- 标题行 ----
        title_row = QHBoxLayout()
        self._title_lbl = QLabel("🍅 番茄钟")
        self._title_lbl.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        self._title_lbl.setStyleSheet("color: #2D2B3D;")

        self._tomato_count_lbl = QLabel("今日 0 个")
        self._tomato_count_lbl.setStyleSheet("color: #FF6B6B; font-size: 10px; font-weight: bold;")

        self._close_btn = QPushButton("✕")
        self._close_btn.setFixedSize(QSize(20, 20))
        self._close_btn.setStyleSheet("""
            QPushButton { background: transparent; border: none;
                color: #A09DB8; font-size: 11px; }
            QPushButton:hover { color: #FF6B6B; }
        """)
        self._close_btn.clicked.connect(self.closed)

        title_row.addWidget(self._title_lbl)
        title_row.addWidget(self._tomato_count_lbl)
        title_row.addStretch()
        title_row.addWidget(self._close_btn)
        root.addLayout(title_row)

        # ---- 圆环 ----
        ring_row = QHBoxLayout()
        ring_row.addStretch()
        self._ring = _PomodoroRing()
        ring_row.addWidget(self._ring)
        ring_row.addStretch()
        root.addLayout(ring_row)

        # ---- 状态标签 ----
        self._state_lbl = QLabel("准备开始")
        self._state_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._state_lbl.setStyleSheet("color: #6B6880; font-size: 10px;")
        root.addWidget(self._state_lbl)

        # ---- 按钮行 ----
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._start_btn = QPushButton("开始专注")
        self._start_btn.setStyleSheet(self._btn_primary_style())

        self._pause_btn = QPushButton("暂停")
        self._pause_btn.setStyleSheet(self._btn_secondary_style())
        self._pause_btn.setEnabled(False)

        self._stop_btn = QPushButton("停止")
        self._stop_btn.setStyleSheet(self._btn_secondary_style())
        self._stop_btn.setEnabled(False)

        btn_row.addWidget(self._start_btn)
        btn_row.addWidget(self._pause_btn)
        btn_row.addWidget(self._stop_btn)
        root.addLayout(btn_row)

    # ------------------------------------------------------------------ #
    #  主题
    # ------------------------------------------------------------------ #

    def apply_theme(self, theme) -> None:
        """响应主题切换，更新所有颜色"""
        is_dark = theme.name == "dark"

        # 面板背景
        if is_dark:
            self.setStyleSheet("""
                #PomodoroWidget {
                    background: rgba(35, 30, 55, 0.97);
                    border-radius: 14px;
                    border: 1px solid rgba(255, 107, 107, 0.25);
                }
            """)
        else:
            self.setStyleSheet("""
                #PomodoroWidget {
                    background: rgba(255, 250, 245, 0.95);
                    border-radius: 14px;
                    border: 1px solid rgba(255, 107, 107, 0.2);
                }
            """)

        # 圆环文字色 & 轨道色
        self._ring.set_theme_colors(
            text_color=theme.text_primary,
            track_color=theme.progress_track,
        )

        # 标题文字
        self._title_lbl.setStyleSheet(f"color: {theme.text_primary};")

        # 状态标签
        self._state_lbl.setStyleSheet(f"color: {theme.text_secondary}; font-size: 10px;")

        # 关闭按钮
        self._close_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; border: none;
                color: {theme.text_placeholder}; font-size: 11px; }}
            QPushButton:hover {{ color: #FF6B6B; }}
        """)

        # 次要按钮（暂停/停止）
        self._pause_btn.setStyleSheet(self._btn_secondary_style(theme))
        self._stop_btn.setStyleSheet(self._btn_secondary_style(theme))

    # ------------------------------------------------------------------ #
    #  按钮样式
    # ------------------------------------------------------------------ #

    def _btn_primary_style(self) -> str:
        return """
            QPushButton {
                background: #FF6B6B; color: white;
                border: none; border-radius: 8px;
                padding: 6px 16px; font-size: 11px; font-weight: bold;
            }
            QPushButton:hover { background: #FF8E8E; }
            QPushButton:disabled { background: #5a5575; color: #7a7595; }
        """

    def _btn_secondary_style(self, theme=None) -> str:
        if theme and theme.name == "dark":
            return f"""
                QPushButton {{
                    background: transparent; color: {theme.text_primary};
                    border: 1px solid {theme.border_accent}; border-radius: 8px;
                    padding: 5px 12px; font-size: 11px;
                }}
                QPushButton:hover {{ background: rgba(139,133,255,0.15); }}
                QPushButton:disabled {{ color: {theme.text_placeholder};
                    border-color: {theme.border}; }}
            """
        return """
            QPushButton {
                background: transparent; color: #6B6880;
                border: 1px solid #C0BDDE; border-radius: 8px;
                padding: 5px 12px; font-size: 11px;
            }
            QPushButton:hover { background: #F0EEF8; }
            QPushButton:disabled { color: #C0BDDE; }
        """

    # ------------------------------------------------------------------ #
    #  信号连接
    # ------------------------------------------------------------------ #

    def _connect_signals(self) -> None:
        self._start_btn.clicked.connect(self._on_start)
        self._pause_btn.clicked.connect(self._on_pause_resume)
        self._stop_btn.clicked.connect(self._pomodoro.stop)

        self._pomodoro.state_changed.connect(self._on_state_changed)
        self._pomodoro.tick.connect(self._on_tick)
        self._pomodoro.phase_completed.connect(self._on_phase_completed)

    # ------------------------------------------------------------------ #
    #  槽
    # ------------------------------------------------------------------ #

    def _on_start(self) -> None:
        state = self._pomodoro.state
        if state == PomodoroState.IDLE:
            self._pomodoro.start_focus()
        elif state in (PomodoroState.SHORT_BREAK, PomodoroState.LONG_BREAK):
            self._pomodoro.stop()
            self._pomodoro.start_focus()

    def _on_pause_resume(self) -> None:
        if self._pomodoro.is_running:
            self._pomodoro.pause()
            self._pause_btn.setText("继续")
        else:
            self._pomodoro.resume()
            self._pause_btn.setText("暂停")

    def _on_state_changed(self, state_value: str, label: str) -> None:
        self._state_lbl.setText(label)
        self._update_buttons()

    def _on_tick(self, seconds_left: int, total: int) -> None:
        self._ring.update_state(self._pomodoro.state, seconds_left, total)

    def _on_phase_completed(self, state_value: str, count: int) -> None:
        self._tomato_count_lbl.setText(f"今日 {count} 个")
        self._update_buttons()

    def _update_buttons(self) -> None:
        state = self._pomodoro.state
        is_idle = state == PomodoroState.IDLE

        self._start_btn.setEnabled(True)
        self._pause_btn.setEnabled(not is_idle)
        self._stop_btn.setEnabled(not is_idle)

        if is_idle:
            self._start_btn.setText("开始专注")
            self._pause_btn.setText("暂停")
        elif state == PomodoroState.FOCUS:
            self._start_btn.setText("进行中…")
            self._start_btn.setEnabled(False)
        elif state in (PomodoroState.SHORT_BREAK, PomodoroState.LONG_BREAK):
            self._start_btn.setText("跳过休息")
