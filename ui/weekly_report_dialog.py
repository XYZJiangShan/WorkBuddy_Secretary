"""
weekly_report_dialog.py - 周报弹窗

展示 AI 生成的 Markdown 周报，支持选择周区间和一键复制。
风格：奶油白磨砂卡片，独立模态弹窗。
"""

from __future__ import annotations

from datetime import date, timedelta

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QGuiApplication
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QTextBrowser, QVBoxLayout, QWidget, QFrame,
)

from data.settings_repository import SettingsRepository
from data.task_repository import TaskRepository
from data.report_repository import ReportRepository, Report
from services.ai_service import AIService
from services.ai_worker import AIWorker


class WeeklyReportDialog(QDialog):
    """
    周报弹窗

    弹出时先展示加载占位，然后触发 AI 生成周报，
    结果回来后刷新内容区域。支持前后翻周。
    """

    def __init__(
        self,
        ai_service: AIService,
        task_repo: TaskRepository,
        settings: SettingsRepository,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._ai = ai_service
        self._task_repo = task_repo
        self._settings = settings
        self._report_repo = ReportRepository()
        self._worker: AIWorker | None = None
        self._report_text: str = ""

        # 默认显示本周（以今天为截止日）
        self._end_date: date = date.today()

        self._setup_ui()
        # 延迟启动 AI 生成（等 exec() 进入事件循环后再开始，避免 COM 冲突）
        QTimer.singleShot(300, self._start_report)

    # ------------------------------------------------------------------ #
    #  UI 搭建
    # ------------------------------------------------------------------ #

    def _setup_ui(self) -> None:
        self.setWindowTitle("周报")
        self.setFixedWidth(520)
        self.setMaximumHeight(680)
        # wait_ai_idle() 已在调用方（_open_weekly_report）保证 AI 子线程空闲，
        # 所以这里直接设 WindowStaysOnTopHint 是安全的（无 COM 冲突风险）。
        # ⚠️ 不能延迟用 setWindowFlag()：它会 destroy+recreate 窗口，
        #    打断 exec() 的模态事件循环，导致弹窗一闪而过。
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        # ---- 卡片容器（不再依赖 WA_TranslucentBackground，直接做圆角卡片）----
        card = QWidget()
        card.setObjectName("WeeklyCard")
        card.setStyleSheet("""
            #WeeklyCard {
                background: #FEFCF7;
                border-radius: 16px;
                border: 1px solid rgba(108, 99, 255, 0.18);
            }
        """)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 16, 20, 16)
        card_layout.setSpacing(12)

        # ---- 标题行 ----
        header_row = QHBoxLayout()
        emoji_label = QLabel("📋")
        emoji_label.setFont(QFont("Segoe UI Emoji", 18))
        emoji_label.setFixedWidth(32)

        title_label = QLabel("周报")
        title_label.setFont(QFont("Microsoft YaHei", 13, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #2D2B3D;")

        header_row.addWidget(emoji_label)
        header_row.addWidget(title_label)
        header_row.addStretch()
        card_layout.addLayout(header_row)

        # ---- 周选择行 ----
        week_row = QHBoxLayout()
        week_row.setSpacing(8)

        self._prev_btn = QPushButton("◀")
        self._prev_btn.setFixedSize(28, 28)
        self._prev_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._prev_btn.setStyleSheet(self._nav_btn_style())
        self._prev_btn.clicked.connect(self._on_prev_week)

        self._week_label = QLabel()
        self._week_label.setFont(QFont("Microsoft YaHei", 10))
        self._week_label.setStyleSheet("color: #6B6880;")
        self._week_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._next_btn = QPushButton("▶")
        self._next_btn.setFixedSize(28, 28)
        self._next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._next_btn.setStyleSheet(self._nav_btn_style())
        self._next_btn.clicked.connect(self._on_next_week)

        week_row.addWidget(self._prev_btn)
        week_row.addWidget(self._week_label, 1)
        week_row.addWidget(self._next_btn)
        card_layout.addLayout(week_row)

        self._update_week_label()

        # 分割线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: rgba(108,99,255,0.15);")
        card_layout.addWidget(line)

        # ---- 内容滚动区 ----
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical { width: 4px; background: transparent; }
            QScrollBar::handle:vertical {
                background: rgba(108,99,255,0.3); border-radius: 2px;
            }
        """)

        self._content_browser = QTextBrowser()
        self._content_browser.setOpenExternalLinks(False)
        self._content_browser.setFont(QFont("Microsoft YaHei", 10))
        self._content_browser.setStyleSheet("""
            QTextBrowser {
                background: transparent;
                border: none;
                color: #2D2B3D;
            }
        """)
        self._content_browser.setMarkdown("⏳ AI 正在生成周报，请稍候…")
        scroll.setWidget(self._content_browser)
        card_layout.addWidget(scroll, 1)

        # ---- 底部按钮行 ----
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._copy_btn = QPushButton("复制周报")
        self._copy_btn.setEnabled(False)
        self._copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_btn.setStyleSheet("""
            QPushButton {
                background: #6C63FF; color: white;
                border: none; border-radius: 8px;
                padding: 6px 18px; font-size: 11px;
            }
            QPushButton:hover { background: #8B85FF; }
            QPushButton:disabled {
                background: #D4D1F0; color: #A09DB8;
            }
        """)
        self._copy_btn.clicked.connect(self._on_copy)

        self._refresh_btn = QPushButton("重新生成")
        self._refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh_btn.setStyleSheet("""
            QPushButton {
                background: transparent; color: #6C63FF;
                border: 1px solid #6C63FF; border-radius: 8px;
                padding: 6px 18px; font-size: 11px;
            }
            QPushButton:hover { background: rgba(108,99,255,0.08); }
        """)
        self._refresh_btn.clicked.connect(self._start_report)

        close_btn = QPushButton("关闭")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet("""
            QPushButton {
                background: transparent; color: #6B6880;
                border: 1px solid #C0BDDE; border-radius: 8px;
                padding: 6px 18px; font-size: 11px;
            }
            QPushButton:hover { background: #F0EEF8; }
        """)
        close_btn.clicked.connect(self.close)

        btn_row.addStretch()
        btn_row.addWidget(self._refresh_btn)
        btn_row.addWidget(self._copy_btn)
        btn_row.addWidget(close_btn)
        card_layout.addLayout(btn_row)

        root.addWidget(card)

    @staticmethod
    def _nav_btn_style() -> str:
        return """
            QPushButton {
                background: rgba(108,99,255,0.08); color: #6C63FF;
                border: 1px solid rgba(108,99,255,0.2);
                border-radius: 6px; font-size: 11px;
            }
            QPushButton:hover { background: rgba(108,99,255,0.18); }
        """

    def _update_week_label(self) -> None:
        start = self._end_date - timedelta(days=6)
        self._week_label.setText(
            f"{start.strftime('%m月%d日')} ~ {self._end_date.strftime('%m月%d日')}"
        )
        # 不能翻到未来
        self._next_btn.setEnabled(self._end_date < date.today())

    # ------------------------------------------------------------------ #
    #  周导航
    # ------------------------------------------------------------------ #

    def _on_prev_week(self) -> None:
        self._end_date -= timedelta(days=7)
        self._update_week_label()
        self._start_report()

    def _on_next_week(self) -> None:
        self._end_date += timedelta(days=7)
        if self._end_date > date.today():
            self._end_date = date.today()
        self._update_week_label()
        self._start_report()

    # ------------------------------------------------------------------ #
    #  AI 生成
    # ------------------------------------------------------------------ #

    def _start_report(self) -> None:
        self._content_browser.setMarkdown("⏳ AI 正在生成周报，请稍候…")
        self._copy_btn.setEnabled(False)
        self._report_text = ""

        week_summary = self._task_repo.get_week_summary(self._end_date)

        if week_summary["total"] == 0:
            self._report_text = "📭 本周暂无任务记录。\n\n添加一些任务后再来生成周报吧！"
            self._content_browser.setMarkdown(self._report_text)
            self._copy_btn.setEnabled(True)
            return

        worker = AIWorker(self._ai, parent=self)
        worker.generate_weekly_report(week_summary)
        worker.result_ready.connect(self._on_report_ready)
        worker.error_occurred.connect(self._on_report_error)
        worker.start()
        self._worker = worker

    def _on_report_ready(self, task_type: str, result: object) -> None:
        if task_type != "weekly_report":
            return
        text: str = result  # type: ignore
        self._report_text = text
        self._content_browser.setMarkdown(text)
        self._copy_btn.setEnabled(True)
        # 自动保存到 reports 表
        start = self._end_date - timedelta(days=6)
        report_date = f"{start.isoformat()}~{self._end_date.isoformat()}"
        self._report_repo.save_report(Report(
            report_type="weekly",
            report_date=report_date,
            content=text,
            auto_generated=False,
        ))

    def _on_report_error(self, task_type: str, error_msg: str) -> None:
        if task_type != "weekly_report":
            return
        self._content_browser.setMarkdown(
            f"> ⚠️ 生成失败：{error_msg}\n\n请检查 AI 配置后重试。"
        )

    # ------------------------------------------------------------------ #
    #  按钮操作
    # ------------------------------------------------------------------ #

    def _on_copy(self) -> None:
        if self._report_text:
            QGuiApplication.clipboard().setText(self._report_text)
            self._copy_btn.setText("已复制 ✓")
            QTimer.singleShot(2000, lambda: self._copy_btn.setText("复制周报"))

    # ------------------------------------------------------------------ #
    #  鼠标拖拽（弹窗可移动）
    # ------------------------------------------------------------------ #

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:
        if hasattr(self, "_drag_pos") and self._drag_pos and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = None
