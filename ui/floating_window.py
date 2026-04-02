"""
floating_window.py - 主悬浮窗口（v2，含番茄钟/统计/深色模式/透明度）

新增：
  - 标题栏：番茄钟按钮 🍅、统计按钮 📊、主题切换 🌙
  - 内容区：番茄钟面板（可展开/收起）、统计面板（可展开/收起）
  - 主题：响应 ThemeManager.theme_changed 信号，动态重绘
  - 透明度：启动时从 settings 读取并应用
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import (
    QPoint, QSize, Qt, pyqtSignal, QTimer,
)
from PyQt6.QtGui import (
    QColor, QFont, QLinearGradient,
    QPainter, QPaintEvent, QPen, QBrush,
)
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget, QFrame, QStackedWidget,
)

from data.settings_repository import SettingsRepository
from data.task_repository import Task, TaskRepository
from data.task_note_repository import TaskNoteRepository
from services.ai_service import AIService
from services.ai_worker import AIWorker
from services.reminder_service import ReminderService
from services.pomodoro_service import PomodoroService, PomodoroState
from ui.reminder_banner import ReminderBanner
from ui.task_list_widget import TaskListWidget
from ui.stats_widget import StatsWidget
from ui.pomodoro_widget import PomodoroWidget
from ui.theme import theme_manager, Theme
from ui.edge_snap import EdgeSnapManager, MiniBar

logger = logging.getLogger(__name__)

WINDOW_W = 310
WINDOW_H_FULL = 520


class FloatingWindow(QWidget):
    """
    桌面悬浮主窗口 v2

    Signals:
        open_settings()
        open_review()
    """

    open_settings = pyqtSignal()
    open_review = pyqtSignal()

    def __init__(
        self,
        settings: SettingsRepository,
        task_repo: TaskRepository,
        ai_service: AIService,
        reminder_service: ReminderService,
        pomodoro_service: Optional[PomodoroService] = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._task_repo = task_repo
        self._note_repo = TaskNoteRepository()
        self._ai = ai_service
        self._reminder = reminder_service
        self._pomodoro = pomodoro_service or PomodoroService(self)
        self._drag_pos: Optional[QPoint] = None
        self._ai_worker: Optional[AIWorker] = None
        self._show_pomodoro: bool = False
        self._show_stats: bool = False
        self._detail_panels: list = []  # 追踪所有打开的任务详情面板

        self._setup_window_flags()
        self._apply_opacity()
        self._setup_ui()
        self._connect_signals()
        self._restore_position()
        self._load_tasks()
        self._apply_theme(theme_manager.current)

        # 初始化时同步 AI 模式
        ai_enabled = settings.get_bool("ai_enabled", True)
        self._task_list.set_ai_mode(ai_enabled)

        # 边缘吸附管理器（setup_ui 完成后初始化）
        self._snap = EdgeSnapManager(self, WINDOW_H_FULL, self)
        self._snap.mini_mode_entered.connect(self._on_mini_entered)
        self._snap.mini_mode_exited.connect(self._on_mini_exited)

        # 迷你状态条（覆盖在卡片上，默认隐藏）
        from ui.edge_snap import MINI_H
        self._mini_bar = MiniBar(self)
        self._mini_bar.setGeometry(0, 0, self.width(), MINI_H)
        self._mini_bar.hide()
        self._mini_bar.apply_theme(theme_manager.current)

        # 开启鼠标追踪，支持边缘检测光标变化
        self.setMouseTracking(True)
        self._card.setMouseTracking(True)

    # ------------------------------------------------------------------ #
    #  窗口属性
    # ------------------------------------------------------------------ #

    def _setup_window_flags(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setMinimumSize(QSize(240, 280))
        self.resize(WINDOW_W, WINDOW_H_FULL)

    def showEvent(self, event) -> None:
        super().showEvent(event)



    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        # 主窗口被彻底隐藏（点✕/托盘）时才关闭详情面板
        # 注意：detail panel 获焦时不会触发主窗口 hide，此处仅处理真正隐藏
        if not self.isVisible():
            self._close_all_detail_panels()

    def _apply_opacity(self) -> None:
        opacity = self._settings.get_float("window_opacity", 0.92)
        # 支持 0~1 全范围，0 时仍保留 0.05 以防窗口完全不可见
        self.setWindowOpacity(max(0.05, min(1.0, opacity)))

    # ------------------------------------------------------------------ #
    #  UI 搭建
    # ------------------------------------------------------------------ #

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._card = QWidget(self)
        self._card.setObjectName("Card")
        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        # ---- 提醒横幅 ----
        self._banner = ReminderBanner(self._card)
        card_layout.addWidget(self._banner)

        # ---- 标题栏 ----
        self._title_bar = self._build_title_bar()
        card_layout.addWidget(self._title_bar)

        # ---- 内容区（折叠时隐藏） ----
        self._content = QWidget(self._card)
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # 番茄钟面板（默认隐藏）
        self._pomodoro_widget = PomodoroWidget(self._pomodoro, self._content)
        self._pomodoro_widget.hide()
        self._pomodoro_widget.closed.connect(self._hide_pomodoro)
        content_layout.addWidget(self._pomodoro_widget)

        # 任务列表
        self._task_list = TaskListWidget(self._content)
        content_layout.addWidget(self._task_list, 1)

        # 统计面板（默认隐藏）
        self._stats_widget = StatsWidget(self._task_repo, self._content)
        self._stats_widget.hide()
        content_layout.addWidget(self._stats_widget)

        # 倒计时进度条
        self._progress_bar = CountdownProgressBar(self._content)
        content_layout.addWidget(self._progress_bar)

        card_layout.addWidget(self._content, 1)

        root.addWidget(self._card)

    def _build_title_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(44)
        bar.setCursor(Qt.CursorShape.SizeAllCursor)
        bar.setStyleSheet("background: transparent;")

        row = QHBoxLayout(bar)
        row.setContentsMargins(12, 0, 8, 0)
        row.setSpacing(4)

        icon_label = QLabel("✦")
        icon_label.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        icon_label.setStyleSheet("color: #8B85FF;")
        icon_label.setFixedWidth(20)

        self._title_label = QLabel("DeskSec")
        self._title_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self._title_label.setStyleSheet("color: #8B85FF; letter-spacing: 1px;")

        row.addWidget(icon_label)
        row.addWidget(self._title_label)
        row.addStretch()

        # 功能按钮组
        self._pomodoro_btn = self._make_icon_btn("🍅", "番茄钟专注模式")
        self._stats_btn = self._make_icon_btn("📊", "今日统计")
        self._history_btn = self._make_icon_btn("📋", "历史任务记录")
        self._settings_btn = self._make_icon_btn("⚙", "打开设置")
        self._close_btn = self._make_icon_btn("✕", "最小化到托盘")
        self._close_btn.setStyleSheet("""
            QPushButton {
                background: transparent; border: none;
                color: #A09DB8; font-size: 12px;
                width: 24px; height: 24px; border-radius: 5px;
            }
            QPushButton:hover { background: rgba(255,107,107,0.15); color: #FF6B6B; }
        """)

        for btn in [self._pomodoro_btn, self._stats_btn, self._history_btn,
                    self._settings_btn]:
            row.addWidget(btn)
        row.addWidget(self._close_btn)

        return bar

    def _make_icon_btn(self, text: str, tooltip: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setToolTip(tooltip)
        btn.setFixedSize(QSize(24, 24))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet("""
            QPushButton {
                background: transparent; border: none;
                color: #A09DB8; font-size: 12px; border-radius: 5px;
            }
            QPushButton:hover { background: rgba(108,99,255,0.12); color: #6C63FF; }
        """)
        return btn

    # ------------------------------------------------------------------ #
    #  信号连接
    # ------------------------------------------------------------------ #

    def _connect_signals(self) -> None:
        # 标题栏按钮
        self._settings_btn.clicked.connect(self.open_settings)
        self._close_btn.clicked.connect(self.hide)
        self._pomodoro_btn.clicked.connect(self._toggle_pomodoro)
        self._stats_btn.clicked.connect(self._toggle_stats)
        self._history_btn.clicked.connect(self._open_history)

        # 横幅
        self._banner.closed.connect(self._on_banner_closed)
        self._banner.snoozed.connect(self._reminder.snooze)

        # 任务列表
        self._task_list.task_add_requested.connect(self._on_task_add_requested)
        self._task_list.task_confirmed.connect(self._on_task_confirmed)
        self._task_list.task_check_toggled.connect(self._on_task_check_toggled)
        self._task_list.task_deleted.connect(self._on_task_deleted)
        self._task_list.review_requested.connect(self.open_review)
        self._task_list.task_detail_requested.connect(self._on_task_detail_requested)
        self._task_list.task_priority_changed.connect(self._on_task_priority_changed)

        # 提醒服务
        self._reminder.reminder_triggered.connect(self._on_reminder_triggered)
        self._reminder.countdown_tick.connect(self._on_countdown_tick)

        # 番茄钟连接休息提醒
        self._pomodoro.reminder_pause_requested.connect(self._reminder.pause)
        self._pomodoro.reminder_resume_requested.connect(self._reminder.resume)
        self._pomodoro.phase_completed.connect(self._on_pomodoro_phase_completed)
        self._pomodoro.state_changed.connect(self._on_pomodoro_state_changed)
        self._pomodoro.tick.connect(self._on_pomodoro_tick)

        # 主题
        theme_manager.theme_changed.connect(self._apply_theme)

    # ------------------------------------------------------------------ #
    #  公共 API
    # ------------------------------------------------------------------ #

    def reload_tasks(self) -> None:
        self._load_tasks()

    def show_reminder(self, text: str) -> None:
        self._on_reminder_triggered(text)

    def apply_settings(self) -> None:
        """设置保存后刷新外观（透明度、主题、AI 模式等）"""
        self._apply_opacity()
        theme_name = self._settings.get("theme", "light")
        theme_manager.set_theme(theme_name)
        # 同步 AI 模式到任务列表
        ai_enabled = self._settings.get_bool("ai_enabled", True)
        self._task_list.set_ai_mode(ai_enabled)

    # ------------------------------------------------------------------ #
    #  番茄钟 / 统计面板切换
    # ------------------------------------------------------------------ #

    def _toggle_pomodoro(self) -> None:
        self._show_pomodoro = not self._show_pomodoro
        self._pomodoro_widget.setVisible(self._show_pomodoro)
        self._adjust_height()

    def _hide_pomodoro(self) -> None:
        self._show_pomodoro = False
        self._pomodoro_widget.hide()
        self._adjust_height()

    def _toggle_stats(self) -> None:
        self._show_stats = not self._show_stats
        self._stats_widget.setVisible(self._show_stats)
        if self._show_stats:
            self._stats_widget.refresh()
        self._adjust_height()


    def _adjust_height(self) -> None:
        extra = 0
        if self._show_pomodoro:
            extra += 200
        if self._show_stats:
            extra += 180
        self.resize(WINDOW_W, WINDOW_H_FULL + extra)

    # ------------------------------------------------------------------ #
    #  主题切换
    # ------------------------------------------------------------------ #

    def _apply_theme(self, theme: Theme) -> None:

        # ---- 主卡片 ----
        self._card.setStyleSheet(f"""
            #Card {{
                background: {theme.bg_card};
                border-radius: 16px;
                border: 1px solid {theme.border};
            }}
        """)

        # ---- 标题栏文字（品牌色固定）----
        self._title_label.setStyleSheet("color: #8B85FF; background: transparent; letter-spacing: 1px;")

        # ---- 标题栏按钮（统一颜色）----
        btn_style = f"""
            QPushButton {{
                background: transparent; border: none;
                color: {theme.text_placeholder}; font-size: 12px; border-radius: 5px;
            }}
            QPushButton:hover {{ background: rgba(108,99,255,0.15); color: {theme.accent}; }}
        """
        for btn in [self._pomodoro_btn, self._stats_btn, self._history_btn,
                    self._settings_btn]:
            btn.setStyleSheet(btn_style)
        self._close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: none;
                color: {theme.text_placeholder}; font-size: 12px;
                width: 24px; height: 24px; border-radius: 5px;
            }}
            QPushButton:hover {{ background: rgba(255,107,107,0.15); color: #FF6B6B; }}
        """)

        # ---- 进度条 ----
        self._progress_bar.apply_theme(theme)

        # ---- 任务列表 ----
        self._task_list.apply_theme(theme)

        # ---- 番茄钟面板 ----
        self._pomodoro_widget.apply_theme(theme)

        # ---- 迷你条 ----
        if hasattr(self, "_mini_bar"):
            self._mini_bar.apply_theme(theme)

    # ------------------------------------------------------------------ #
    #  数据操作
    # ------------------------------------------------------------------ #

    def _load_tasks(self) -> None:
        tasks = self._task_repo.get_today(include_done=True)
        self._task_list.load_tasks(tasks)

    def _on_task_add_requested(self, text: str) -> None:
        if self._ai_worker and self._ai_worker.isRunning():
            return
        worker = AIWorker(self._ai, parent=self)
        worker.parse_task(text)
        worker.result_ready.connect(self._on_ai_parse_result)
        worker.error_occurred.connect(self._on_ai_parse_error)
        worker.start()
        self._ai_worker = worker

    def _on_ai_parse_result(self, task_type: str, result: object) -> None:
        if task_type != "parse_task":
            return
        self._task_list.show_parse_result(result)  # type: ignore

    def _on_ai_parse_error(self, task_type: str, error_msg: str) -> None:
        if task_type != "parse_task":
            return
        self._task_list.show_parse_error(error_msg)

    def _on_task_confirmed(self, parsed: dict) -> None:
        task = Task(
            title=parsed["title"],
            priority=parsed.get("priority", "medium"),
            due_time=parsed.get("due_time"),
        )
        self._task_repo.add(task)
        self._load_tasks()

    def _on_task_check_toggled(self, task_id: int, done: bool) -> None:
        if done:
            self._task_repo.mark_done(task_id)
        else:
            self._task_repo.mark_undone(task_id)
        self._load_tasks()
        if self._show_stats:
            self._stats_widget.refresh()

    def _on_task_deleted(self, task_id: int) -> None:
        self._task_repo.delete(task_id)
        self._load_tasks()

    def _on_task_priority_changed(self, task_id: int, new_priority: str) -> None:
        """优先级切换：更新数据库并刷新列表（高优先级自动置顶）"""
        task = self._task_repo.get_by_id(task_id)
        if task:
            task.priority = new_priority
            self._task_repo.update(task)
            self._load_tasks()

    # ------------------------------------------------------------------ #
    #  提醒服务回调
    # ------------------------------------------------------------------ #

    def _on_reminder_triggered(self, text: str) -> None:
        # 迷你模式下展开
        if hasattr(self, "_snap") and self._snap.is_mini:
            self._mini_bar.show_alert(text)
            self._snap.force_expand()
        self.show()
        self.raise_()
        self._banner.show_text(text)

    def _on_banner_closed(self) -> None:
        pass

    def _on_countdown_tick(self, seconds_left: int) -> None:
        total = self._reminder.total_seconds
        self._progress_bar.update_progress(seconds_left, total)
        if hasattr(self, "_mini_bar"):
            self._mini_bar.update_reminder(seconds_left, total)

    def _on_pomodoro_phase_completed(self, state_value: str, count: int) -> None:
        if self._show_stats:
            self._stats_widget.set_tomato_count(count)

    # ------------------------------------------------------------------ #
    #  折叠 / 展开
    # ------------------------------------------------------------------ #


    # ------------------------------------------------------------------ #
    #  历史记录
    # ------------------------------------------------------------------ #

    def _open_history(self) -> None:
        from ui.history_dialog import HistoryDialog
        # 若已存在且可见，移到前台即可
        if hasattr(self, "_history_dlg") and self._history_dlg is not None:
            try:
                if self._history_dlg.isVisible():
                    self._history_dlg.raise_()
                    self._history_dlg.activateWindow()
                    return
            except RuntimeError:
                # C++ 对象已销毁（WA_DeleteOnClose），重新创建
                pass

        self._history_dlg = HistoryDialog(self._task_repo, parent=None)

        # 定位到标题栏历史按钮正下方
        screen = QApplication.primaryScreen()
        if screen and hasattr(self, "_history_btn"):
            screen_geo = screen.availableGeometry()
            btn_global = self._history_btn.mapToGlobal(
                self._history_btn.rect().bottomLeft()
            )
            dlg_w, dlg_h = 520, 620
            x = btn_global.x()
            y = btn_global.y() + 6
            # 防止超出屏幕右边
            if x + dlg_w > screen_geo.right():
                x = screen_geo.right() - dlg_w
            # 防止超出屏幕下边
            if y + dlg_h > screen_geo.bottom():
                y = btn_global.y() - dlg_h - 6
            self._history_dlg.move(x, y)

        self._history_dlg.show()
        self._history_dlg.raise_()

    # ------------------------------------------------------------------ #
    #  任务详情
    # ------------------------------------------------------------------ #

    def _on_task_detail_requested(self, task_id: int, global_x: int, global_bottom_y: int) -> None:
        from ui.task_detail_panel import TaskDetailPanel
        task = self._task_repo.get_by_id(task_id)
        if not task:
            return

        # 先关掉其他已打开的详情面板
        self._close_all_detail_panels()

        # parent=None：独立顶层窗口，完全不受主窗口 hide/resize/移动影响
        dlg = TaskDetailPanel(task, self._task_repo, self._note_repo, parent=None)
        dlg.task_updated.connect(lambda _: self._load_tasks())

        # 定位到任务行正下方，紧邻点击的任务
        screen = QApplication.primaryScreen()
        if screen:
            screen_geo = screen.availableGeometry()
            dlg_w, dlg_h = 480, 600

            # X：与主窗口左边对齐，防止超出屏幕右边
            x = global_x
            if x + dlg_w > screen_geo.right():
                x = screen_geo.right() - dlg_w

            # Y：任务行底部往下 4px
            y = global_bottom_y + 4
            if y + dlg_h > screen_geo.bottom():
                # 如果下方放不下，放到任务行上方
                y = global_bottom_y - dlg_h - 4

            dlg.move(x, y)

        # 追踪，面板关闭时从列表移除，并重启折叠检测（吸附状态下）
        self._detail_panels.append(dlg)

        def _on_dlg_closed():
            if dlg in self._detail_panels:
                self._detail_panels.remove(dlg)
            # 如果当前处于吸附展开状态，重启轮询检测鼠标是否已离开
            if hasattr(self, "_snap") and self._snap.is_snapped and not self._snap.is_mini:
                self._snap.restart_poll_after_dialog()

        dlg.destroyed.connect(_on_dlg_closed)
        dlg.show()

    def _close_all_detail_panels(self) -> None:
        """关闭所有已打开的任务详情面板"""
        for panel in list(self._detail_panels):
            try:
                panel.close()
            except Exception:
                pass
        self._detail_panels.clear()

    # ------------------------------------------------------------------ #
    #  番茄钟迷你条同步
    # ------------------------------------------------------------------ #

    def _on_pomodoro_state_changed(self, state_value: str, label: str) -> None:
        colors = {
            "focus": "#FF6B6B",
            "short_break": "#52C41A",
            "long_break": "#36CFC9",
            "idle": "#A09DB8",
        }
        color = colors.get(state_value, "#A09DB8")
        self._mini_bar.update_pomodoro(label, color)

    def _on_pomodoro_tick(self, seconds_left: int, total: int) -> None:
        # 迷你条只显示专注阶段倒计时
        if self._pomodoro.state.value == "focus":
            m, s = divmod(seconds_left, 60)
            self._mini_bar.update_pomodoro(f"🍅 {m:02d}:{s:02d}", "#FF6B6B")

    # ------------------------------------------------------------------ #
    #  边缘吸附 / 迷你模式
    # ------------------------------------------------------------------ #

    def _on_mini_entered(self) -> None:
        """进入迷你模式：解除最小高度限制，隐藏卡片，显示迷你条"""
        # 注意：不再自动关闭 detail panel，避免用户正在查看时被强制关闭
        from ui.edge_snap import MINI_H
        # 必须先降低 minimumSize，否则 edge_snap 的 resize(w, MINI_H) 会被 Qt 忽略
        self.setMinimumSize(QSize(240, MINI_H))
        self._card.hide()
        self._mini_bar.setGeometry(0, 0, self.width(), MINI_H)
        self._mini_bar.show()

    def _on_mini_exited(self) -> None:
        """退出迷你模式：恢复最小高度，显示卡片，隐藏迷你条"""
        # 恢复最小高度，再让 edge_snap 的 _do_expand 去 resize
        self.setMinimumSize(QSize(240, 280))
        self._mini_bar.hide()
        self._card.show()

    def enterEvent(self, event) -> None:
        self._snap.on_mouse_enter()

    def leaveEvent(self, event) -> None:
        self._snap.on_mouse_leave()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_mini_bar"):
            from ui.edge_snap import MINI_H
            self._mini_bar.setGeometry(0, 0, self.width(), MINI_H)

    # ------------------------------------------------------------------ #
    #  鼠标拖拽（含边缘吸附）
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    #  鼠标拖拽移动 + 边缘缩放（纯 Python，无 Win32 依赖）
    # ------------------------------------------------------------------ #

    _RESIZE_MARGIN = 10

    def _edge_at(self, pos) -> str:
        x, y, w, h, m = pos.x(), pos.y(), self.width(), self.height(), self._RESIZE_MARGIN
        r = x > w - m
        b = y > h - m
        l = x < m
        t = y < m
        if r and b: return "rb"
        if l and b: return "lb"
        if r and t: return "rt"
        if l and t: return "lt"
        if r: return "r"
        if b: return "b"
        if l: return "l"
        if t: return "t"
        return ""

    _CURSORS = {
        "r": Qt.CursorShape.SizeHorCursor, "l": Qt.CursorShape.SizeHorCursor,
        "b": Qt.CursorShape.SizeVerCursor, "t": Qt.CursorShape.SizeVerCursor,
        "rb": Qt.CursorShape.SizeFDiagCursor, "lt": Qt.CursorShape.SizeFDiagCursor,
        "lb": Qt.CursorShape.SizeBDiagCursor, "rt": Qt.CursorShape.SizeBDiagCursor,
    }

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._resize_edge = self._edge_at(event.position().toPoint())
            if self._resize_edge:
                self._drag_pos = None
                self._resize_origin = event.globalPosition().toPoint()
                self._resize_origin_geo = self.geometry()
            else:
                self._resize_edge = ""
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:
        pos = event.position().toPoint()
        if event.buttons() == Qt.MouseButton.LeftButton:
            if getattr(self, "_resize_edge", ""):
                self._do_resize(event.globalPosition().toPoint())
            elif self._drag_pos:
                self.move(event.globalPosition().toPoint() - self._drag_pos)
        else:
            edge = self._edge_at(pos)
            self.setCursor(self._CURSORS.get(edge, Qt.CursorShape.ArrowCursor))

    def _do_resize(self, gpos) -> None:
        edge = self._resize_edge
        og = self._resize_origin_geo
        dx = gpos.x() - self._resize_origin.x()
        dy = gpos.y() - self._resize_origin.y()
        min_w, min_h = 240, 280
        nx, ny, nw, nh = og.x(), og.y(), og.width(), og.height()
        if "r" in edge: nw = max(min_w, og.width() + dx)
        if "b" in edge: nh = max(min_h, og.height() + dy)
        if "l" in edge:
            nw = max(min_w, og.width() - dx)
            nx = og.x() + og.width() - nw
        if "t" in edge:
            nh = max(min_h, og.height() - dy)
            ny = og.y() + og.height() - nh
        self.setGeometry(nx, ny, nw, nh)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._resize_edge = ""
            self._drag_pos = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            if hasattr(self, "_snap"):
                self._snap.on_drag_end(self.frameGeometry())
            self._settings.set_many({
                "window_x": str(self.x()),
                "window_y": str(self.y()),
                "window_width": str(self.width()),
                "window_height": str(self.height()),
            })

    # ------------------------------------------------------------------ #
    #  位置恢复
    # ------------------------------------------------------------------ #

    def _restore_position(self) -> None:
        # 恢复宽高
        saved_w = self._settings.get_int("window_width", WINDOW_W)
        saved_h = self._settings.get_int("window_height", WINDOW_H_FULL)
        saved_w = max(260, saved_w)
        saved_h = max(300, saved_h)
        self.resize(saved_w, saved_h)

        # 恢复位置
        x = self._settings.get_int("window_x", -1)
        y = self._settings.get_int("window_y", -1)
        screen = QApplication.primaryScreen()
        if screen and x >= 0 and y >= 0:
            geo = screen.availableGeometry()
            x = min(x, geo.width() - self.width())
            y = min(y, geo.height() - self.height())
            self.move(x, y)
        else:
            if screen:
                geo = screen.availableGeometry()
                self.move(geo.width() - self.width() - 20, geo.height() - self.height() - 40)

    # ------------------------------------------------------------------ #
    #  绘制背景（无阴影）
    # ------------------------------------------------------------------ #

    def paintEvent(self, event: QPaintEvent) -> None:
        pass  # 透明背景，无需绘制阴影外圈


# --------------------------------------------------------------------------- #
#  倒计时进度条
# --------------------------------------------------------------------------- #

class CountdownProgressBar(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._seconds_left = 0
        self._total_seconds = 1
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setFixedHeight(28)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 4)
        layout.setSpacing(8)

        self._time_label = QLabel("休息提醒：45:00")
        self._time_label.setStyleSheet("color: #A09DB8; font-size: 9px;")

        self._bar = _ProgressBarInner()
        self._bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._bar.setFixedHeight(4)

        layout.addWidget(self._time_label)
        layout.addWidget(self._bar, 1)

    def update_progress(self, seconds_left: int, total_seconds: int) -> None:
        self._seconds_left = seconds_left
        self._total_seconds = max(total_seconds, 1)
        m, s = divmod(seconds_left, 60)
        self._time_label.setText(f"下次提醒：{m:02d}:{s:02d}")
        self._bar.set_ratio(seconds_left / self._total_seconds)

    def apply_theme(self, theme: Theme) -> None:
        self._time_label.setStyleSheet(f"color: {theme.text_placeholder}; font-size: 9px;")
        self._bar.set_track_color(theme.progress_track)


class _ProgressBarInner(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._ratio = 1.0
        self._track_color = QColor("#DCD8F0")

    def set_ratio(self, ratio: float) -> None:
        self._ratio = max(0.0, min(1.0, ratio))
        self.update()

    def set_track_color(self, color: str) -> None:
        self._track_color = QColor(color)
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._track_color)
        p.drawRoundedRect(0, 0, w, h, h // 2, h // 2)
        filled_w = int(w * self._ratio)
        if filled_w > 0:
            grad = QLinearGradient(0, 0, filled_w, 0)
            grad.setColorAt(0, QColor("#8B85FF"))
            grad.setColorAt(1, QColor("#6C63FF"))
            p.setBrush(QBrush(grad))
            p.drawRoundedRect(0, 0, filled_w, h, h // 2, h // 2)
        p.end()
