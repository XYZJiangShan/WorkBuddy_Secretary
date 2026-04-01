"""
history_dialog.py - 历史任务记录对话框

- 按日期分组展示所有历史任务
- 点击任务行 → 打开 TaskDetailPanel 查看详情
- 始终置顶（WindowStaysOnTopHint 延迟设置，避免 COM 冲突）
- 深色主题
"""
from __future__ import annotations

from datetime import date
from PyQt6.QtCore import Qt, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QCursor
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QWidget, QFrame,
    QSizePolicy, QApplication,
)

from data.task_repository import TaskRepository, Task
from data.task_note_repository import TaskNoteRepository


# --------------------------------------------------------------------------- #
#  可点击任务行
# --------------------------------------------------------------------------- #

class _ClickableTaskRow(QWidget):
    """带 hover 效果、可点击的任务行"""
    clicked = pyqtSignal(int)   # task_id

    def __init__(self, task: Task, parent=None):
        super().__init__(parent)
        self._task = task
        self._setup()

    def _setup(self) -> None:
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setObjectName("TaskRow")
        self._update_style(False)

        row = QHBoxLayout(self)
        row.setContentsMargins(6, 5, 6, 5)
        row.setSpacing(8)

        # 状态图标
        if self._task.done:
            icon = QLabel("✓")
            icon.setStyleSheet("color: #3DDB6B; font-weight: bold; font-size: 12px;")
        else:
            icon = QLabel("○")
            icon.setStyleSheet("color: #5C5880; font-size: 12px;")
        icon.setFixedWidth(16)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 优先级色点
        dot = QLabel("●")
        dot.setStyleSheet(
            "color: #FF3B3B; font-size: 9px;" if self._task.priority == "high"
            else "color: #3DDB6B; font-size: 9px;"
        )
        dot.setFixedWidth(12)

        # 标题
        title = QLabel(self._task.title)
        title.setFont(QFont("Microsoft YaHei", 10))
        if self._task.done:
            title.setStyleSheet("color: #5C5880; text-decoration: line-through;")
        else:
            title.setStyleSheet("color: #C8C5E8;")
        title.setWordWrap(False)
        title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        # 时间 + 打开箭头
        if self._task.done and self._task.done_at:
            time_lbl = QLabel(self._task.done_at[11:16])
            time_lbl.setStyleSheet("color: #3DDB6B; font-size: 9px;")
        else:
            time_lbl = QLabel(self._task.created_at[11:16])
            time_lbl.setStyleSheet("color: #5C5880; font-size: 9px;")

        arrow = QLabel("›")
        arrow.setStyleSheet("color: #6660A0; font-size: 16px; font-weight: bold;")
        arrow.setFixedWidth(14)

        row.addWidget(icon)
        row.addWidget(dot)
        row.addWidget(title, 1)
        row.addWidget(time_lbl)
        row.addWidget(arrow)

    def _update_style(self, hovered: bool) -> None:
        if hovered:
            self.setStyleSheet("""
                #TaskRow {
                    background: rgba(139,133,255,0.12);
                    border-radius: 6px;
                }
            """)
        else:
            self.setStyleSheet("""
                #TaskRow { background: transparent; border-radius: 6px; }
            """)

    def enterEvent(self, event) -> None:
        self._update_style(True)

    def leaveEvent(self, event) -> None:
        self._update_style(False)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._task.id)


# --------------------------------------------------------------------------- #
#  历史对话框
# --------------------------------------------------------------------------- #

class HistoryDialog(QDialog):
    """历史任务记录弹窗"""

    def __init__(self, task_repo: TaskRepository, parent=None):
        super().__init__(parent)
        self._repo = task_repo
        self._note_repo = TaskNoteRepository()
        self._detail_panels: list = []   # 追踪从历史记录打开的详情面板

        self.setWindowTitle("历史任务记录 - 桌面小秘书")
        self.setWindowFlags(Qt.WindowType.Dialog)
        self.resize(520, 620)
        self._setup_ui()
        self._load_data()

        # 延迟 200ms 再设置置顶，避免弹出时 COM 冲突
        QTimer.singleShot(200, self._set_on_top)

    def _set_on_top(self) -> None:
        """延迟设置置顶标志，确保窗口已完全初始化"""
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.show()  # 重新 show 让 flag 生效

    # ------------------------------------------------------------------ #
    #  UI
    # ------------------------------------------------------------------ #

    def _setup_ui(self) -> None:
        self.setStyleSheet("""
            QDialog { background: #1E1B30; }
            QLabel  { background: transparent; }
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical { width: 4px; background: transparent; }
            QScrollBar::handle:vertical {
                background: rgba(139,133,255,0.35); border-radius: 2px;
            }
            QWidget#DayBlock {
                background: rgba(40, 36, 62, 0.85);
                border: 1px solid rgba(139,133,255,0.18);
                border-radius: 10px;
            }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        # 标题
        title = QLabel("📋  历史任务记录")
        title.setFont(QFont("Microsoft YaHei", 13, QFont.Weight.Bold))
        title.setStyleSheet("color: #E8E5FF;")
        root.addWidget(title)

        hint = QLabel("点击任务行可查看详情  ·  🔴红=高优先级  ·  ✓绿=已完成  ·  ○灰=未完成")
        hint.setStyleSheet("color: #5C5880; font-size: 10px;")
        root.addWidget(hint)

        self._add_line(root)

        # 滚动内容
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._content_widget = QWidget()
        self._content_widget.setStyleSheet("background: transparent;")
        self._content_layout = QVBoxLayout(self._content_widget)
        self._content_layout.setContentsMargins(0, 4, 4, 4)
        self._content_layout.setSpacing(12)
        self._content_layout.addStretch()

        scroll.setWidget(self._content_widget)
        root.addWidget(scroll, 1)

    def _add_line(self, layout: QVBoxLayout) -> None:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        line.setStyleSheet("background: rgba(139,133,255,0.15); border: none;")
        layout.addWidget(line)

    # ------------------------------------------------------------------ #
    #  数据
    # ------------------------------------------------------------------ #

    def _load_data(self) -> None:
        history = self._repo.get_history_by_date()
        today = date.today().isoformat()

        if not history:
            empty = QLabel("还没有任何任务记录")
            empty.setStyleSheet("color: #5C5880; font-size: 11px;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._content_layout.insertWidget(0, empty)
            return

        insert_pos = 0
        for day, tasks in sorted(history.items(), reverse=True):
            block = self._make_day_block(day, tasks, is_today=(day == today))
            self._content_layout.insertWidget(insert_pos, block)
            insert_pos += 1

    def _make_day_block(self, day: str, tasks: list[Task], is_today: bool) -> QWidget:
        block = QWidget()
        block.setObjectName("DayBlock")
        layout = QVBoxLayout(block)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(2)

        # 日期标题
        date_row = QHBoxLayout()
        label_text = f"📅  今天  {day}" if is_today else f"📅  {day}"
        date_label = QLabel(label_text)
        date_label.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        date_label.setStyleSheet("color: #8B85FF;" if is_today else "color: #9994C0;")

        done_count = sum(1 for t in tasks if t.done)
        stat_label = QLabel(f"{done_count}/{len(tasks)} 已完成")
        stat_label.setStyleSheet("color: #5C5880; font-size: 9px;")

        date_row.addWidget(date_label)
        date_row.addStretch()
        date_row.addWidget(stat_label)
        layout.addLayout(date_row)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        line.setStyleSheet("background: rgba(139,133,255,0.1); border: none;")
        layout.addWidget(line)

        # 未完成在前，已完成在后
        for task in [t for t in tasks if not t.done]:
            row = _ClickableTaskRow(task, block)
            row.clicked.connect(self._on_task_clicked)
            layout.addWidget(row)
        for task in [t for t in tasks if t.done]:
            row = _ClickableTaskRow(task, block)
            row.clicked.connect(self._on_task_clicked)
            layout.addWidget(row)

        return block

    # ------------------------------------------------------------------ #
    #  点击任务 → 打开详情
    # ------------------------------------------------------------------ #

    def _on_task_clicked(self, task_id: int) -> None:
        from ui.task_detail_panel import TaskDetailPanel

        task = self._repo.get_by_id(task_id)
        if not task:
            return

        # 先关掉已打开的详情
        for panel in list(self._detail_panels):
            try:
                if panel.isVisible():
                    panel.close()
            except RuntimeError:
                pass
        self._detail_panels.clear()

        dlg = TaskDetailPanel(task, self._repo, self._note_repo, parent=None)
        self._detail_panels.append(dlg)
        dlg.destroyed.connect(
            lambda: self._detail_panels.remove(dlg) if dlg in self._detail_panels else None
        )

        # 定位：弹在历史弹窗右侧，或屏幕允许的位置
        screen = QApplication.primaryScreen()
        if screen:
            screen_geo = screen.availableGeometry()
            dlg_w, dlg_h = 480, 600
            x = self.x() + self.width() + 8
            y = self.y()
            if x + dlg_w > screen_geo.right():
                x = self.x() - dlg_w - 8
            if y + dlg_h > screen_geo.bottom():
                y = screen_geo.bottom() - dlg_h
            dlg.move(max(screen_geo.left(), x), max(screen_geo.top(), y))

        dlg.show()
        dlg.raise_()

    # ------------------------------------------------------------------ #

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()

    def closeEvent(self, event) -> None:
        # 关闭时一并关掉从历史打开的详情面板
        for panel in list(self._detail_panels):
            try:
                panel.close()
            except RuntimeError:
                pass
        self._detail_panels.clear()
        super().closeEvent(event)
