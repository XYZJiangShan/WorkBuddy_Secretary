"""
stats_widget.py - 数据统计面板组件

展示：
  - 今日待办完成率（进度环 + 数字）
  - 本周每日完成数迷你柱状图（纯字符）
  - 今日休息提醒次数
  - 累计专注番茄数
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QLinearGradient
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)

from data.task_repository import TaskRepository
from data.database import get_conn


# --------------------------------------------------------------------------- #
#  迷你进度环
# --------------------------------------------------------------------------- #

class _RingWidget(QWidget):
    """圆环进度指示器"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ratio = 0.0
        self._done = 0
        self._total = 0
        self.setFixedSize(72, 72)

    def set_data(self, done: int, total: int) -> None:
        self._done = done
        self._total = total
        self._ratio = done / total if total > 0 else 0.0
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy, r = w // 2, h // 2, min(w, h) // 2 - 6

        # 背景圆环
        p.setPen(QPen(QColor("#E8E6F5"), 7))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(cx - r, cy - r, r * 2, r * 2)

        # 进度弧
        if self._ratio > 0:
            pen = QPen(QColor("#6C63FF"), 7)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            span = int(-self._ratio * 360 * 16)
            p.drawArc(cx - r, cy - r, r * 2, r * 2, 90 * 16, span)

        # 中间文字
        p.setPen(QColor("#2D2B3D"))
        font = QFont("Microsoft YaHei", 13, QFont.Weight.Bold)
        p.setFont(font)
        p.drawText(
            self.rect().adjusted(0, -4, 0, -4),
            Qt.AlignmentFlag.AlignCenter,
            str(self._done),
        )
        p.setPen(QColor("#A09DB8"))
        small = QFont("Microsoft YaHei", 7)
        p.setFont(small)
        p.drawText(
            self.rect().adjusted(0, 20, 0, 20),
            Qt.AlignmentFlag.AlignCenter,
            f"/{self._total}" if self._total else "0",
        )
        p.end()


# --------------------------------------------------------------------------- #
#  迷你柱状图（字符画）
# --------------------------------------------------------------------------- #

class _MiniBarChart(QWidget):
    """本周7天完成数柱状图"""

    BAR_COLORS = ["#8B85FF", "#6C63FF"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: list[tuple[str, int]] = []  # [(weekday_label, count), ...]
        self.setFixedHeight(56)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_data(self, data: list[tuple[str, int]]) -> None:
        self._data = data
        self.update()

    def paintEvent(self, event) -> None:
        if not self._data:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        n = len(self._data)
        max_val = max(v for _, v in self._data) or 1

        bar_w = max(4, (w - 8) // n - 4)
        spacing = (w - 8 - bar_w * n) // max(n - 1, 1)
        label_h = 14
        chart_h = h - label_h - 2
        today_idx = n - 1

        for i, (label, val) in enumerate(self._data):
            x = 4 + i * (bar_w + spacing)
            bar_h = max(2, int(chart_h * val / max_val)) if val > 0 else 2
            y = chart_h - bar_h

            # 柱体颜色：今天高亮
            color = QColor("#6C63FF") if i == today_idx else QColor("#C4C1F0")
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(color))
            p.drawRoundedRect(x, y, bar_w, bar_h, 2, 2)

            # 日期标签
            p.setPen(QColor("#A09DB8" if i != today_idx else "#6C63FF"))
            font = QFont("Microsoft YaHei", 7)
            font.setBold(i == today_idx)
            p.setFont(font)
            p.drawText(x - 2, h - label_h, bar_w + 4, label_h,
                       Qt.AlignmentFlag.AlignCenter, label)

        p.end()


# --------------------------------------------------------------------------- #
#  统计卡片
# --------------------------------------------------------------------------- #

class _StatCard(QWidget):
    def __init__(self, icon: str, value: str, label: str, color: str = "#6C63FF", parent=None):
        super().__init__(parent)
        self.setObjectName("StatCard")
        self.setStyleSheet(f"""
            #StatCard {{
                background: rgba(108,99,255,0.07);
                border-radius: 10px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)

        icon_val_row = QHBoxLayout()
        icon_val_row.setSpacing(4)

        icon_lbl = QLabel(icon)
        icon_lbl.setFont(QFont("Segoe UI Emoji", 13))
        icon_lbl.setFixedWidth(22)

        self._value_lbl = QLabel(value)
        self._value_lbl.setFont(QFont("Microsoft YaHei", 16, QFont.Weight.Bold))
        self._value_lbl.setStyleSheet(f"color: {color};")

        icon_val_row.addWidget(icon_lbl)
        icon_val_row.addWidget(self._value_lbl)
        icon_val_row.addStretch()
        layout.addLayout(icon_val_row)

        label_lbl = QLabel(label)
        label_lbl.setStyleSheet("color: #A09DB8; font-size: 9px;")
        layout.addWidget(label_lbl)

    def set_value(self, v: str) -> None:
        self._value_lbl.setText(v)


# --------------------------------------------------------------------------- #
#  主统计面板
# --------------------------------------------------------------------------- #

class StatsWidget(QWidget):
    """
    数据统计面板，嵌入悬浮窗底部（可折叠显示）

    数据来源：TaskRepository + reminder_history 表
    """

    def __init__(self, task_repo: TaskRepository, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._task_repo = task_repo
        self._tomato_count = 0
        self._setup_ui()

        # 定时刷新（每分钟）
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(60_000)
        self._refresh_timer.timeout.connect(self.refresh)
        self._refresh_timer.start()

    # ------------------------------------------------------------------ #
    #  UI 搭建
    # ------------------------------------------------------------------ #

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 10)
        root.setSpacing(10)

        # ---- 标题 ----
        title = QLabel("📊 今日统计")
        title.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        title.setStyleSheet("color: #2D2B3D;")
        root.addWidget(title)

        # ---- 完成率环 + 小卡片 ----
        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        self._ring = _RingWidget()
        ring_wrap = QVBoxLayout()
        ring_wrap.addWidget(self._ring)
        ring_caption = QLabel("任务完成")
        ring_caption.setStyleSheet("color: #A09DB8; font-size: 9px;")
        ring_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ring_wrap.addWidget(ring_caption)
        ring_wrap.setSpacing(2)

        top_row.addLayout(ring_wrap)

        cards_col = QVBoxLayout()
        cards_col.setSpacing(6)

        self._remind_card = _StatCard("🔔", "0", "今日提醒次数", "#FFB347")
        self._tomato_card = _StatCard("🍅", "0", "累计番茄数", "#FF6B6B")

        cards_col.addWidget(self._remind_card)
        cards_col.addWidget(self._tomato_card)
        top_row.addLayout(cards_col, 1)
        root.addLayout(top_row)

        # ---- 本周柱状图 ----
        week_label = QLabel("本周完成趋势")
        week_label.setStyleSheet("color: #6B6880; font-size: 9px; font-weight: bold;")
        root.addWidget(week_label)

        self._bar_chart = _MiniBarChart()
        root.addWidget(self._bar_chart)

    # ------------------------------------------------------------------ #
    #  数据刷新
    # ------------------------------------------------------------------ #

    def refresh(self) -> None:
        """刷新所有统计数据"""
        self._refresh_today()
        self._refresh_week()
        self._refresh_reminders()

    def set_tomato_count(self, count: int) -> None:
        """由外部（PomodoroService）更新番茄数"""
        self._tomato_count = count
        self._tomato_card.set_value(str(count))

    # ------------------------------------------------------------------ #
    #  内部刷新逻辑
    # ------------------------------------------------------------------ #

    def _refresh_today(self) -> None:
        stats = self._task_repo.count_today()
        self._ring.set_data(stats["done"], stats["total"])

    def _refresh_week(self) -> None:
        """查询本周7天的完成数"""
        today = date.today()
        data: list[tuple[str, int]] = []
        weekday_labels = ["一", "二", "三", "四", "五", "六", "日"]

        for i in range(6, -1, -1):
            d = today - timedelta(days=i)
            label = "今" if i == 0 else weekday_labels[d.weekday()]
            count = self._query_done_count(d)
            data.append((label, count))

        self._bar_chart.set_data(data)

    def _refresh_reminders(self) -> None:
        """查询今日提醒次数"""
        today_str = date.today().isoformat()
        try:
            conn = get_conn()
            row = conn.execute(
                "SELECT COUNT(*) FROM reminder_history WHERE triggered_at LIKE ?",
                (f"{today_str}%",),
            ).fetchone()
            count = row[0] if row else 0
            self._remind_card.set_value(str(count))
        except Exception:
            pass

    def _query_done_count(self, d: date) -> int:
        """查询某天完成任务数"""
        try:
            conn = get_conn()
            day_str = d.isoformat()
            row = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE done=1 AND done_at LIKE ?",
                (f"{day_str}%",),
            ).fetchone()
            return row[0] if row else 0
        except Exception:
            return 0
