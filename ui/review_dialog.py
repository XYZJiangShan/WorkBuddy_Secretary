"""
review_dialog.py - 今日复盘弹窗

展示 AI 生成的 Markdown 复盘报告，支持一键复制。
风格：奶油白磨砂卡片，独立模态弹窗，最大高度 600px 内滚动。
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QFont, QClipboard, QGuiApplication
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QTextBrowser,
    QVBoxLayout, QWidget, QFrame,
)

from data.settings_repository import SettingsRepository
from data.task_repository import TaskRepository
from services.ai_service import AIService
from services.ai_worker import AIWorker


class ReviewDialog(QDialog):
    """
    今日复盘弹窗

    弹出时先展示加载占位，然后触发 AI 生成，
    结果回来后刷新内容区域。
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
        self._worker: AIWorker | None = None
        self._report_text: str = ""

        self._setup_ui()
        # 延迟启动 AI 生成（等 exec() 进入事件循环后再开始，避免 COM 冲突）
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(300, self._start_review)

    # ------------------------------------------------------------------ #
    #  UI 搭建
    # ------------------------------------------------------------------ #

    def _setup_ui(self) -> None:
        self.setWindowTitle("今日复盘")
        self.setFixedWidth(480)
        self.setMaximumHeight(600)
        # ⚠️ 不在 __init__ 设 WindowStaysOnTopHint（Bug #9），
        #    不用 FramelessWindowHint + WA_TranslucentBackground（与 AI 子线程 COM 冲突）
        self.setWindowFlags(Qt.WindowType.Dialog)
        # 延迟 200ms 再设置置顶，避免 COM 冲突崩溃
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(200, self._apply_stay_on_top)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        # ---- 卡片容器（不再依赖 WA_TranslucentBackground，直接做圆角卡片）----
        card = QWidget()
        card.setObjectName("ReviewCard")
        card.setStyleSheet("""
            #ReviewCard {
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
        emoji_label = QLabel("📊")
        emoji_label.setFont(QFont("Segoe UI Emoji", 18))
        emoji_label.setFixedWidth(32)

        title_label = QLabel("今日复盘")
        title_label.setFont(QFont("Microsoft YaHei", 13, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #2D2B3D;")

        from datetime import date
        date_label = QLabel(date.today().strftime("%Y年%m月%d日"))
        date_label.setStyleSheet("color: #A09DB8; font-size: 11px;")
        date_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        header_row.addWidget(emoji_label)
        header_row.addWidget(title_label)
        header_row.addStretch()
        header_row.addWidget(date_label)
        card_layout.addLayout(header_row)

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
        self._content_browser.setMarkdown("⏳ AI 正在生成复盘报告，请稍候…")
        scroll.setWidget(self._content_browser)
        card_layout.addWidget(scroll, 1)

        # ---- 底部按钮行 ----
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._copy_btn = QPushButton("复制报告")
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
        btn_row.addWidget(self._copy_btn)
        btn_row.addWidget(close_btn)
        card_layout.addLayout(btn_row)

        root.addWidget(card)

    # ------------------------------------------------------------------ #
    #  AI 生成
    # ------------------------------------------------------------------ #

    def _apply_stay_on_top(self) -> None:
        """延迟设置 WindowStaysOnTopHint，避免 COM 冲突"""
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.show()

    def _start_review(self) -> None:
        done_tasks = [
            {"title": t.title, "priority": t.priority, "done_at": t.done_at}
            for t in self._task_repo.get_today_done()
        ]
        undone_tasks = [
            {"title": t.title, "priority": t.priority, "due_time": t.due_time}
            for t in self._task_repo.get_today(include_done=False)
        ]

        worker = AIWorker(self._ai, parent=self)
        worker.generate_daily_review(done_tasks, undone_tasks)
        worker.result_ready.connect(self._on_review_ready)
        worker.error_occurred.connect(self._on_review_error)
        worker.start()
        self._worker = worker

    def _on_review_ready(self, task_type: str, result: object) -> None:
        if task_type != "daily_review":
            return
        text: str = result  # type: ignore
        self._report_text = text
        self._content_browser.setMarkdown(text)
        self._copy_btn.setEnabled(True)

    def _on_review_error(self, task_type: str, error_msg: str) -> None:
        if task_type != "daily_review":
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
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(2000, lambda: self._copy_btn.setText("复制报告"))

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
