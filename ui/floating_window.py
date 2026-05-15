"""
floating_window.py - 主悬浮窗口（v3，统计/深色模式/透明度/休息弹窗）

功能：
  - 标题栏：统计按钮 📊、主题切换 🌙
  - 内容区：统计面板（可展开/收起）
  - 底部窄倒计时进度条（可点击展开休息提醒弹窗）
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
    QColor, QFont, QLinearGradient, QIcon, QPainterPath,
    QPainter, QPaintEvent, QPen, QBrush, QCursor,
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
from ui.task_list_widget import TaskListWidget
from ui.stats_widget import StatsWidget
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
        open_weekly_report()
    """

    open_settings = pyqtSignal()
    open_weekly_report = pyqtSignal()

    def __init__(
        self,
        settings: SettingsRepository,
        task_repo: TaskRepository,
        ai_service: AIService,
        reminder_service: ReminderService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._task_repo = task_repo
        self._note_repo = TaskNoteRepository()
        self._ai = ai_service
        self._reminder = reminder_service
        self._drag_pos: Optional[QPoint] = None
        self._ai_worker: Optional[AIWorker] = None
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

        # ---- 标题栏 ----
        self._title_bar = self._build_title_bar()
        card_layout.addWidget(self._title_bar)

        # ---- 内容区（折叠时隐藏） ----
        self._content = QWidget(self._card)
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # 任务列表
        self._task_list = TaskListWidget(self._content)
        content_layout.addWidget(self._task_list, 1)

        # 统计面板（默认隐藏）
        self._stats_widget = StatsWidget(self._task_repo, self._content)
        self._stats_widget.hide()
        content_layout.addWidget(self._stats_widget)

        # 底部窄倒计时进度条（可点击展开提醒弹窗）
        self._progress_bar = CountdownProgressBar(self._content)
        self._progress_bar.clicked.connect(self._show_reminder_popup)
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

        # 功能按钮组 —— 使用自绘图标
        self._stats_btn = IconButton("stats", "统计", bar)
        self._history_btn = IconButton("history", "历史", bar)
        self._weekly_btn = IconButton("report", "周报", bar)
        self._settings_btn = IconButton("settings", "设置", bar)
        self._close_btn = IconButton("close", "最小化", bar)
        self._close_btn.set_hover_color("#FF6B6B", "rgba(255,107,107,0.15)")

        self._icon_btns = [self._stats_btn, self._history_btn,
                           self._weekly_btn, self._settings_btn]

        for btn in self._icon_btns:
            row.addWidget(btn)
        row.addWidget(self._close_btn)

        return bar

    # ------------------------------------------------------------------ #
    #  信号连接
    # ------------------------------------------------------------------ #

    def _connect_signals(self) -> None:
        # 标题栏按钮
        self._settings_btn.clicked.connect(self.open_settings)
        self._close_btn.clicked.connect(self.hide)
        self._stats_btn.clicked.connect(self._toggle_stats)
        self._history_btn.clicked.connect(self._open_history)
        self._weekly_btn.clicked.connect(self.open_weekly_report)

        # 任务列表
        self._task_list.task_add_requested.connect(self._on_task_add_requested)
        self._task_list.task_confirmed.connect(self._on_task_confirmed)
        self._task_list.task_check_toggled.connect(self._on_task_check_toggled)
        self._task_list.task_deleted.connect(self._on_task_deleted)
        self._task_list.task_detail_requested.connect(self._on_task_detail_requested)
        self._task_list.task_priority_changed.connect(self._on_task_priority_changed)

        # 提醒服务
        self._reminder.reminder_triggered.connect(self._on_reminder_triggered)
        self._reminder.countdown_tick.connect(self._on_countdown_tick)

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
    #  统计面板切换
    # ------------------------------------------------------------------ #

    def _toggle_stats(self) -> None:
        self._show_stats = not self._show_stats
        self._stats_widget.setVisible(self._show_stats)
        if self._show_stats:
            self._stats_widget.refresh()
        self._adjust_height()

    def _adjust_height(self) -> None:
        extra = 0
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
                border-radius: 10px;
                border: 0.5px solid {theme.border};
            }}
        """)

        # ---- 标题栏文字（品牌色固定）----
        self._title_label.setStyleSheet("color: #8B85FF; background: transparent; letter-spacing: 1px;")

        # ---- 标题栏按钮（统一颜色）----
        for btn in self._icon_btns:
            btn.apply_theme(theme)
        self._close_btn.apply_theme(theme)

        # ---- 进度条 ----
        self._progress_bar.apply_theme(theme)

        # ---- 任务列表 ----
        self._task_list.apply_theme(theme)

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
        """提醒触发：保存文案，自动弹出提醒弹窗"""
        self._last_reminder_text = text
        # 迷你模式下先展开
        if hasattr(self, "_snap") and self._snap.is_mini:
            self._mini_bar.show_alert(text)
            self._snap.force_expand()
        self.show()
        self.raise_()
        # 进度条闪烁提示
        self._progress_bar.flash_alert()
        # 自动弹出提醒弹窗
        self._show_reminder_popup()

    def _show_reminder_popup(self) -> None:
        """展开休息提醒弹窗（从进度条正上方弹出）"""
        from ui.reminder_popup import ReminderPopup
        text = getattr(self, "_last_reminder_text", "该休息了，站起来活动一下吧 👀")

        # 如果弹窗已存在，先关掉
        if hasattr(self, "_reminder_popup") and self._reminder_popup is not None:
            try:
                self._reminder_popup.close()
            except RuntimeError:
                pass

        popup = ReminderPopup(text, parent=None)
        popup.dismissed.connect(self._on_popup_dismissed)
        popup.snoozed.connect(self._on_popup_snoozed)

        # 定位到进度条正上方
        bar_global = self._progress_bar.mapToGlobal(
            self._progress_bar.rect().topLeft()
        )
        popup_w = self.width() - 16  # 略窄于主窗口
        popup.setFixedWidth(popup_w)
        popup.adjustSize()
        popup_h = popup.sizeHint().height()

        x = bar_global.x() + (self._progress_bar.width() - popup_w) // 2
        y = bar_global.y() - popup_h - 6

        # 防止超出屏幕上方
        screen = QApplication.primaryScreen()
        if screen:
            screen_geo = screen.availableGeometry()
            if y < screen_geo.top():
                y = bar_global.y() + self._progress_bar.height() + 6

        popup.move(x, y)
        popup.show()
        popup.raise_()
        self._reminder_popup = popup

    def _on_popup_dismissed(self) -> None:
        """弹窗关闭"""
        pass

    def _on_popup_snoozed(self, seconds: int) -> None:
        """弹窗延迟"""
        self._reminder.snooze(seconds)

    def _on_countdown_tick(self, seconds_left: int) -> None:
        total = self._reminder.total_seconds
        self._progress_bar.update_progress(seconds_left, total)
        if hasattr(self, "_mini_bar"):
            self._mini_bar.update_reminder(seconds_left, total)

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
#  自绘图标按钮（替代 emoji，保证视觉一致性）
# --------------------------------------------------------------------------- #

class IconButton(QPushButton):
    """标题栏自绘矢量图标按钮，悬浮显示 tooltip 名称"""

    _ICONS = {
        "stats": "_draw_stats",
        "history": "_draw_history",
        "report": "_draw_report",
        "settings": "_draw_settings",
        "close": "_draw_close",
    }

    def __init__(self, icon_key: str, tooltip: str, parent=None):
        super().__init__(parent)
        self._icon_key = icon_key
        self._draw_fn = self._ICONS.get(icon_key, "_draw_close")
        self.setToolTip(tooltip)
        self.setFixedSize(QSize(26, 26))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._fg_color = QColor("#A09DB8")
        self._hover_fg = QColor("#6C63FF")
        self._hover_bg = QColor(108, 99, 255, 30)  # rgba(108,99,255,0.12)
        self._hovered = False
        self.setStyleSheet("background: transparent; border: none;")

    def set_hover_color(self, fg: str, bg: str) -> None:
        self._hover_fg = QColor(fg)
        self._hover_bg = QColor(bg) if bg else QColor(0, 0, 0, 0)

    def apply_theme(self, theme) -> None:
        self._fg_color = QColor(theme.text_placeholder)
        # 保留自定义 hover 颜色（如 close 按钮的红色）
        if self._icon_key != "close":
            self._hover_fg = QColor(theme.accent)
        self.update()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # 悬浮背景
        if self._hovered:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self._hover_bg)
            p.drawRoundedRect(0, 0, w, h, 5, 5)

        # 图标颜色
        color = self._hover_fg if self._hovered else self._fg_color
        pen = QPen(color, 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)

        # 绘制区域：在 26x26 里居中 14x14
        ox, oy = (w - 14) / 2, (h - 14) / 2
        getattr(self, self._draw_fn)(p, ox, oy, 14, 14)
        p.end()

    # ---- 各图标绘制方法（14x14 画布） ---- #

    def _draw_stats(self, p: QPainter, x, y, w, h):
        """三竖条柱状图"""
        bar_w = 2.5
        gap = (w - bar_w * 3) / 4
        heights = [0.4, 0.75, 0.55]
        for i, ratio in enumerate(heights):
            bx = x + gap + i * (bar_w + gap)
            bh = h * ratio
            by = y + h - bh
            p.drawRoundedRect(int(bx), int(by), int(bar_w), int(bh), 1, 1)
        # 底线
        p.drawLine(int(x + 1), int(y + h - 0.5), int(x + w - 1), int(y + h - 0.5))

    def _draw_history(self, p: QPainter, x, y, w, h):
        """时钟 + 回溯箭头"""
        import math
        cx, cy = x + w / 2, y + h / 2
        r = min(w, h) / 2 - 1
        # 圆
        p.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))
        # 时针 (12点方向偏右)
        p.drawLine(int(cx), int(cy), int(cx), int(cy - r * 0.55))
        # 分针 (3点方向)
        p.drawLine(int(cx), int(cy), int(cx + r * 0.45), int(cy))
        # 回溯箭头（左上角小箭头）
        ax = cx - r * 0.7
        ay = cy - r * 0.7
        al = 2.5
        p.drawLine(int(ax), int(ay), int(ax + al), int(ay))
        p.drawLine(int(ax), int(ay), int(ax), int(ay + al))

    def _draw_report(self, p: QPainter, x, y, w, h):
        """文档图标（折角纸张 + 横线）"""
        # 纸张轮廓（带折角）
        fold = 3.5
        path = QPainterPath()
        path.moveTo(x + 2, y)
        path.lineTo(x + w - 2 - fold, y)
        path.lineTo(x + w - 2, y + fold)
        path.lineTo(x + w - 2, y + h)
        path.lineTo(x + 2, y + h)
        path.closeSubpath()
        p.drawPath(path)
        # 折角线
        p.drawLine(int(x + w - 2 - fold), int(y), int(x + w - 2 - fold), int(y + fold))
        p.drawLine(int(x + w - 2 - fold), int(y + fold), int(x + w - 2), int(y + fold))
        # 横线
        lx1, lx2 = x + 4.5, x + w - 4.5
        for ly in [y + h * 0.36, y + h * 0.54, y + h * 0.72]:
            p.drawLine(int(lx1), int(ly), int(lx2), int(ly))

    def _draw_settings(self, p: QPainter, x, y, w, h):
        """齿轮图标"""
        import math
        cx, cy = x + w / 2, y + h / 2
        r_outer = min(w, h) / 2 - 0.5
        r_inner = r_outer * 0.55
        teeth = 6
        # 中心圆
        p.drawEllipse(int(cx - r_inner), int(cy - r_inner), int(r_inner * 2), int(r_inner * 2))
        # 齿
        for i in range(teeth):
            angle = math.radians(i * 60)
            x1 = cx + r_inner * 0.9 * math.cos(angle)
            y1 = cy + r_inner * 0.9 * math.sin(angle)
            x2 = cx + r_outer * math.cos(angle)
            y2 = cy + r_outer * math.sin(angle)
            p.drawLine(int(x1), int(y1), int(x2), int(y2))

    def _draw_close(self, p: QPainter, x, y, w, h):
        """×"""
        m = 3.5
        p.drawLine(int(x + m), int(y + m), int(x + w - m), int(y + h - m))
        p.drawLine(int(x + w - m), int(y + m), int(x + m), int(y + h - m))


# --------------------------------------------------------------------------- #
#  倒计时进度条（窄条，可点击展开提醒弹窗）
# --------------------------------------------------------------------------- #

class CountdownProgressBar(QWidget):
    """底部窄倒计时进度条，点击可展开提醒弹窗"""

    clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._seconds_left = 0
        self._total_seconds = 1
        self._flash_on = False
        self._flash_timer: Optional[QTimer] = None
        self._flash_count = 0
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setFixedHeight(14)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 4)
        layout.setSpacing(0)

        self._bar = _ProgressBarInner()
        self._bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._bar.setFixedHeight(4)

        layout.addWidget(self._bar, 1)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def update_progress(self, seconds_left: int, total_seconds: int) -> None:
        self._seconds_left = seconds_left
        self._total_seconds = max(total_seconds, 1)
        self._bar.set_ratio(seconds_left / self._total_seconds)
        # 提醒文字 tooltip
        m, s = divmod(seconds_left, 60)
        self.setToolTip(f"下次提醒：{m:02d}:{s:02d}（点击查看）")

    def flash_alert(self) -> None:
        """提醒触发时闪烁 3 次"""
        self._flash_count = 0
        if self._flash_timer is None:
            self._flash_timer = QTimer(self)
            self._flash_timer.setInterval(300)
            self._flash_timer.timeout.connect(self._do_flash)
        self._flash_timer.start()

    def _do_flash(self) -> None:
        self._flash_count += 1
        self._flash_on = not self._flash_on
        self._bar.set_flash(self._flash_on)
        if self._flash_count >= 6:
            if self._flash_timer:
                self._flash_timer.stop()
            self._flash_on = False
            self._bar.set_flash(False)

    def apply_theme(self, theme: Theme) -> None:
        self._bar.set_track_color(theme.progress_track)


class _ProgressBarInner(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._ratio = 1.0
        self._track_color = QColor("#DCD8F0")
        self._flash = False

    def set_ratio(self, ratio: float) -> None:
        self._ratio = max(0.0, min(1.0, ratio))
        self.update()

    def set_track_color(self, color: str) -> None:
        self._track_color = QColor(color)
        self.update()

    def set_flash(self, on: bool) -> None:
        self._flash = on
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
            if self._flash:
                grad = QLinearGradient(0, 0, filled_w, 0)
                grad.setColorAt(0, QColor("#FF6B6B"))
                grad.setColorAt(1, QColor("#FF8E53"))
            else:
                grad = QLinearGradient(0, 0, filled_w, 0)
                grad.setColorAt(0, QColor("#8B85FF"))
                grad.setColorAt(1, QColor("#6C63FF"))
            p.setBrush(QBrush(grad))
            p.drawRoundedRect(0, 0, filled_w, h, h // 2, h // 2)
        p.end()
