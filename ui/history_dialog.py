"""
history_dialog.py - 历史记录对话框（含任务、日报、周报三个 Tab）

- Tab 1：按日期分组展示所有历史任务
- Tab 2：日报历史列表，点击可展开查看 Markdown 内容
- Tab 3：周报历史列表，点击可展开查看 Markdown 内容
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
    QSizePolicy, QApplication, QTextBrowser, QStackedWidget,
)

from data.task_repository import TaskRepository, Task
from data.task_note_repository import TaskNoteRepository
from data.report_repository import ReportRepository, Report


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
#  可点击报告行
# --------------------------------------------------------------------------- #

class _ClickableReportRow(QWidget):
    """可展开/收起的报告行"""
    clicked = pyqtSignal(int)  # report_id

    def __init__(self, report: Report, parent=None):
        super().__init__(parent)
        self._report = report
        self._expanded = False
        self._setup()

    def _setup(self) -> None:
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setObjectName("ReportRow")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        # 标题行
        header = QHBoxLayout()
        header.setSpacing(8)

        # 类型图标
        icon_text = "📊" if self._report.report_type == "daily" else "📋"
        icon = QLabel(icon_text)
        icon.setFont(QFont("Segoe UI Emoji", 12))
        icon.setFixedWidth(20)

        # 日期
        date_label = QLabel(self._format_date())
        date_label.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        date_label.setStyleSheet("color: #C8C5E8;")

        # 自动/手动标签
        if self._report.auto_generated:
            auto_tag = QLabel("⏰ 自动")
            auto_tag.setStyleSheet("color: #52C41A; font-size: 9px;")
        else:
            auto_tag = QLabel("✋ 手动")
            auto_tag.setStyleSheet("color: #8B85FF; font-size: 9px;")

        # 展开箭头
        self._arrow = QLabel("▸")
        self._arrow.setStyleSheet("color: #6660A0; font-size: 12px;")
        self._arrow.setFixedWidth(14)

        header.addWidget(icon)
        header.addWidget(date_label)
        header.addWidget(auto_tag)
        header.addStretch()
        header.addWidget(self._arrow)
        layout.addLayout(header)

        # 内容区（默认隐藏）
        self._content = QTextBrowser()
        self._content.setFont(QFont("Microsoft YaHei", 9))
        self._content.setOpenExternalLinks(False)
        self._content.setStyleSheet("""
            QTextBrowser {
                background: rgba(30, 27, 48, 0.6);
                border: 1px solid rgba(139,133,255,0.15);
                border-radius: 8px;
                color: #C8C5E8;
                padding: 8px;
            }
        """)
        self._content.setMarkdown(self._report.content)
        self._content.setMaximumHeight(300)
        self._content.hide()
        layout.addWidget(self._content)

        self._update_style(False)

    def _format_date(self) -> str:
        if self._report.report_type == "daily":
            return f"📅 {self._report.report_date}"
        else:
            parts = self._report.report_date.split("~")
            if len(parts) == 2:
                return f"📅 {parts[0]} ~ {parts[1]}"
            return f"📅 {self._report.report_date}"

    def _update_style(self, hovered: bool) -> None:
        bg = "rgba(139,133,255,0.10)" if hovered else "rgba(40, 36, 62, 0.85)"
        self.setStyleSheet(f"""
            #ReportRow {{
                background: {bg};
                border: 1px solid rgba(139,133,255,0.18);
                border-radius: 10px;
            }}
        """)

    def enterEvent(self, event) -> None:
        self._update_style(True)

    def leaveEvent(self, event) -> None:
        self._update_style(False)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._expanded = not self._expanded
            self._content.setVisible(self._expanded)
            self._arrow.setText("▾" if self._expanded else "▸")


# --------------------------------------------------------------------------- #
#  历史对话框
# --------------------------------------------------------------------------- #

class HistoryDialog(QDialog):
    """历史记录弹窗（任务 / 日报 / 周报 三 Tab）"""

    def __init__(self, task_repo: TaskRepository, parent=None):
        super().__init__(parent)
        self._repo = task_repo
        self._note_repo = TaskNoteRepository()
        self._report_repo = ReportRepository()
        self._detail_panels: list = []   # 追踪从历史记录打开的详情面板

        self.setWindowTitle("历史记录 - 桌面小秘书")
        self.setWindowFlags(Qt.WindowType.Dialog)
        self.resize(560, 660)
        self._setup_ui()
        self._load_tasks_tab()

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
        title = QLabel("📋  历史记录")
        title.setFont(QFont("Microsoft YaHei", 13, QFont.Weight.Bold))
        title.setStyleSheet("color: #E8E5FF;")
        root.addWidget(title)

        # ---- Tab 切换按钮行 ----
        tab_row = QHBoxLayout()
        tab_row.setSpacing(6)

        self._tab_btns: list[QPushButton] = []
        tab_labels = ["📝 任务记录", "📊 日报", "📋 周报"]
        for i, label in enumerate(tab_labels):
            btn = QPushButton(label)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(28)
            btn.clicked.connect(lambda checked, idx=i: self._switch_tab(idx))
            self._tab_btns.append(btn)
            tab_row.addWidget(btn)
        tab_row.addStretch()
        root.addLayout(tab_row)

        self._add_line(root)

        # ---- 堆叠页面 ----
        self._stack = QStackedWidget()
        root.addWidget(self._stack, 1)

        # 页面 0: 任务记录
        self._tasks_page = self._make_scroll_page()
        self._stack.addWidget(self._tasks_page)

        # 页面 1: 日报历史
        self._daily_page = self._make_scroll_page()
        self._stack.addWidget(self._daily_page)

        # 页面 2: 周报历史
        self._weekly_page = self._make_scroll_page()
        self._stack.addWidget(self._weekly_page)

        # 初始化选中 tab 0
        self._current_tab = 0
        self._update_tab_styles()

    def _make_scroll_page(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 4, 4, 4)
        layout.setSpacing(10)
        layout.addStretch()

        scroll.setWidget(content)
        return scroll

    def _get_page_layout(self, page: QScrollArea) -> QVBoxLayout:
        return page.widget().layout()

    def _switch_tab(self, index: int) -> None:
        if index == self._current_tab:
            return
        self._current_tab = index
        self._stack.setCurrentIndex(index)
        self._update_tab_styles()

        # 懒加载
        if index == 1:
            self._load_daily_tab()
        elif index == 2:
            self._load_weekly_tab()

    def _update_tab_styles(self) -> None:
        for i, btn in enumerate(self._tab_btns):
            if i == self._current_tab:
                btn.setStyleSheet("""
                    QPushButton {
                        background: rgba(139,133,255,0.2);
                        color: #8B85FF;
                        border: 1px solid rgba(139,133,255,0.4);
                        border-radius: 6px;
                        padding: 4px 12px;
                        font-size: 11px;
                        font-weight: bold;
                    }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton {
                        background: transparent;
                        color: #8885A8;
                        border: 1px solid rgba(139,133,255,0.15);
                        border-radius: 6px;
                        padding: 4px 12px;
                        font-size: 11px;
                    }
                    QPushButton:hover {
                        background: rgba(139,133,255,0.08);
                        color: #B0ABFF;
                    }
                """)

    def _add_line(self, layout: QVBoxLayout) -> None:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        line.setStyleSheet("background: rgba(139,133,255,0.15); border: none;")
        layout.addWidget(line)

    # ------------------------------------------------------------------ #
    #  Tab 0: 任务记录
    # ------------------------------------------------------------------ #

    def _load_tasks_tab(self) -> None:
        layout = self._get_page_layout(self._tasks_page)
        history = self._repo.get_history_by_date()
        today_str = date.today().isoformat()

        if not history:
            empty = QLabel("还没有任何任务记录")
            empty.setStyleSheet("color: #5C5880; font-size: 11px;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.insertWidget(0, empty)
            return

        insert_pos = 0
        for day, tasks in sorted(history.items(), reverse=True):
            block = self._make_day_block(day, tasks, is_today=(day == today_str))
            layout.insertWidget(insert_pos, block)
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
    #  Tab 1: 日报历史
    # ------------------------------------------------------------------ #

    _daily_loaded = False

    def _load_daily_tab(self) -> None:
        if self._daily_loaded:
            return
        self._daily_loaded = True

        layout = self._get_page_layout(self._daily_page)
        reports = self._report_repo.get_reports_by_type("daily", limit=60)

        if not reports:
            empty = QLabel("还没有日报记录\n\n💡 点击「今日复盘」生成日报，或开启自动日报功能")
            empty.setStyleSheet("color: #5C5880; font-size: 11px;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setWordWrap(True)
            layout.insertWidget(0, empty)
            return

        insert_pos = 0
        for report in reports:
            row = _ClickableReportRow(report, self._daily_page.widget())
            layout.insertWidget(insert_pos, row)
            insert_pos += 1

    # ------------------------------------------------------------------ #
    #  Tab 2: 周报历史
    # ------------------------------------------------------------------ #

    _weekly_loaded = False

    def _load_weekly_tab(self) -> None:
        if self._weekly_loaded:
            return
        self._weekly_loaded = True

        layout = self._get_page_layout(self._weekly_page)
        reports = self._report_repo.get_reports_by_type("weekly", limit=30)

        if not reports:
            empty = QLabel("还没有周报记录\n\n💡 点击「周报」按钮生成，或等周日自动生成")
            empty.setStyleSheet("color: #5C5880; font-size: 11px;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setWordWrap(True)
            layout.insertWidget(0, empty)
            return

        insert_pos = 0
        for report in reports:
            row = _ClickableReportRow(report, self._weekly_page.widget())
            layout.insertWidget(insert_pos, row)
            insert_pos += 1

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
