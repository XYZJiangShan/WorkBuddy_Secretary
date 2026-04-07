"""
task_detail_panel.py - 任务详情面板

点击任务行后从右侧滑出（或在下方展开），支持：
  - 查看/编辑任务标题、优先级、截止时间
  - 文字结论：可编辑的文本区（自动保存）
  - 图片附件：缩略图网格，点击全屏预览，支持删除
  - 视频附件：列表展示，点击用系统默认播放器打开
  - 拖拽 / 点击按钮 添加图片或视频
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import (
    Qt, pyqtSignal, QSize, QTimer, QMimeData,
)
from PyQt6.QtGui import (
    QColor, QFont, QIcon, QPixmap, QPainter,
    QDragEnterEvent, QDropEvent,
)
from PyQt6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QSizePolicy, QTextEdit,
    QVBoxLayout, QWidget, QGridLayout, QSplitter,
    QMessageBox,
)

from data.task_repository import Task, TaskRepository
from data.task_note_repository import TaskNote, TaskNoteRepository


# 支持的文件类型
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".webm"}
DOC_EXTS   = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".txt", ".md", ".csv", ".zip", ".rar", ".7z",
}

# 文档类型图标映射
def _doc_icon(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    icons = {
        ".pdf": "📄", ".doc": "📝", ".docx": "📝",
        ".xls": "📊", ".xlsx": "📊", ".csv": "📊",
        ".ppt": "📑", ".pptx": "📑",
        ".txt": "📃", ".md": "📃",
        ".zip": "📦", ".rar": "📦", ".7z": "📦",
    }
    return icons.get(ext, "📎")


# --------------------------------------------------------------------------- #
#  文档/链接行
# --------------------------------------------------------------------------- #

class _DocRow(QWidget):
    """单条文档链接/本地文件行"""
    delete_requested = pyqtSignal(int)
    fetch_content_requested = pyqtSignal(str)  # url

    def __init__(self, note, parent=None):
        super().__init__(parent)
        self._note = note
        self.setObjectName("DocRow")
        self.setStyleSheet("""
            #DocRow { background: rgba(139,99,255,0.06); border-radius: 8px; }
            #DocRow:hover { background: rgba(139,99,255,0.14); }
        """)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._setup_ui()

    def _setup_ui(self) -> None:
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 7, 8, 7)
        row.setSpacing(8)

        # 图标
        if self._note.is_link:
            icon_txt = self._link_icon(self._note.content or "")
        else:
            icon_txt = _doc_icon(self._note.file_name or "")
        icon = QLabel(icon_txt)
        icon.setFont(QFont("Segoe UI Emoji", 14))
        icon.setFixedWidth(22)

        # 信息列
        info_col = QVBoxLayout()
        info_col.setSpacing(1)

        display = self._note.file_name or self._note.content or ""
        name_lbl = QLabel(display[:50] + "…" if len(display) > 50 else display)
        name_lbl.setStyleSheet("color: #C8C5E8; font-size: 10px; font-weight: bold;")
        name_lbl.setToolTip(self._note.content or "")
        info_col.addWidget(name_lbl)

        if self._note.is_link:
            url_lbl = QLabel(self._note.content or "")
            url_lbl.setStyleSheet("color: #8B85FF; font-size: 9px;")
            url_lbl.setToolTip(self._note.content or "")
            info_col.addWidget(url_lbl)
        elif self._note.file_size:
            size_lbl = QLabel(f"{self._note.file_size / 1024:.1f} KB")
            size_lbl.setStyleSheet("color: #5C5880; font-size: 9px;")
            info_col.addWidget(size_lbl)

        # 打开按钮
        open_btn = QPushButton("🔗 打开" if self._note.is_link else "▶ 打开")
        open_btn.setFixedSize(QSize(64, 24))
        open_btn.setStyleSheet("""
            QPushButton { background: rgba(139,133,255,0.2); color: #C8C5E8;
                border: none; border-radius: 5px; font-size: 10px; }
            QPushButton:hover { background: #8B85FF; color: white; }
        """)
        open_btn.clicked.connect(self._open)

        row.addWidget(icon)
        row.addLayout(info_col, 1)

        # 「读取内容」按钮：仅对企微/飞书等支持的链接显示
        if self._note.is_link:
            url = self._note.content or ""
            if any(h in url for h in ["weixin.qq.com", "feishu.cn", "larksuite.com", "notion.so", "kdocs.cn"]):
                fetch_btn = QPushButton("📥 读取")
                fetch_btn.setFixedSize(QSize(60, 24))
                fetch_btn.setToolTip("读取文档内容，可供 AI 分析")
                fetch_btn.setStyleSheet("""
                    QPushButton { background: rgba(60,200,100,0.15); color: #3DDB6B;
                        border: none; border-radius: 5px; font-size: 10px; }
                    QPushButton:hover { background: rgba(60,200,100,0.3); }
                """)
                fetch_btn.clicked.connect(lambda: self.fetch_content_requested.emit(self._note.content or ""))
                row.addWidget(fetch_btn)

        row.addWidget(open_btn)

        del_btn = QPushButton("✕")
        del_btn.setFixedSize(20, 20)
        del_btn.setStyleSheet("""
            QPushButton { background: transparent; border: none; color: #5C5880; font-size: 11px; }
            QPushButton:hover { color: #FF6B6B; }
        """)
        del_btn.clicked.connect(lambda: self.delete_requested.emit(self._note.id))
        row.addWidget(del_btn)

    def _link_icon(self, url: str) -> str:
        if "weixin" in url or "wxwork" in url or "qyapi" in url:
            return "💬"
        if "feishu" in url or "larksuite" in url:
            return "🪶"
        if "notion" in url:
            return "📓"
        if "docs.google" in url or "sheets.google" in url:
            return "📊"
        if "github" in url:
            return "🐙"
        return "🔗"

    def _open(self) -> None:
        import webbrowser
        target = self._note.content or ""
        if self._note.is_link:
            webbrowser.open(target)
        elif target and Path(target).exists():
            os.startfile(target)
        else:
            QMessageBox.warning(self, "文件不存在", f"找不到文件:\n{target}")

    def mousePressEvent(self, event) -> None:
        """点击整行等同于点「打开」按钮"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._open()
        super().mousePressEvent(event)




class _ThumbCard(QWidget):
    """单张图片缩略图卡片"""

    delete_requested = pyqtSignal(int)   # note_id
    preview_requested = pyqtSignal(str)  # file_path

    def __init__(self, note: TaskNote, parent=None):
        super().__init__(parent)
        self._note = note
        self.setFixedSize(72, 72)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setObjectName("ThumbCard")
        self.setStyleSheet("""
            #ThumbCard { border-radius: 8px; background: #F0EEF8; }
            #ThumbCard:hover { background: #E4E2F5; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)

        # 缩略图
        self._img_label = QLabel()
        self._img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_label.setFixedSize(68, 52)
        self._img_label.setScaledContents(False)
        layout.addWidget(self._img_label)

        # 文件名
        name_lbl = QLabel(self._note.file_name or "")
        name_lbl.setStyleSheet("font-size: 8px; color: #A09DB8;")
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_lbl.setWordWrap(False)
        name_lbl.setFixedWidth(68)
        layout.addWidget(name_lbl)

        # 加载缩略图
        self._load_thumb()

        # 删除按钮（hover 时显示）
        self._del_btn = QPushButton("✕", self)
        self._del_btn.setFixedSize(16, 16)
        self._del_btn.move(54, 2)
        self._del_btn.setStyleSheet("""
            QPushButton { background: rgba(255,107,107,0.85); border: none;
                color: white; border-radius: 8px; font-size: 9px; }
            QPushButton:hover { background: #FF6B6B; }
        """)
        self._del_btn.hide()
        self._del_btn.clicked.connect(lambda: self.delete_requested.emit(self._note.id))

    def _load_thumb(self) -> None:
        path = self._note.content
        if not path or not Path(path).exists():
            self._img_label.setText("？")
            return
        px = QPixmap(path)
        if px.isNull():
            self._img_label.setText("图")
            return
        scaled = px.scaled(68, 52, Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
        self._img_label.setPixmap(scaled)

    def enterEvent(self, e):
        self._del_btn.show()

    def leaveEvent(self, e):
        self._del_btn.hide()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._note.content:
            self.preview_requested.emit(self._note.content)


# --------------------------------------------------------------------------- #
#  图片全屏预览
# --------------------------------------------------------------------------- #

class ImagePreviewDialog(QDialog):
    def __init__(self, image_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("图片预览")
        # ⚠️ Bug #9：不在 __init__ 直接设 WindowStaysOnTopHint
        self.setWindowFlags(Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(900, 680)
        # 延迟 200ms 设置置顶
        QTimer.singleShot(200, self._apply_stay_on_top)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: #1a1a2e; }")

        self._label = QLabel()
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet("background: #1a1a2e;")
        self._label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        px = QPixmap(image_path)
        if not px.isNull():
            screen = QApplication.primaryScreen()
            max_w = screen.availableGeometry().width() - 100 if screen else 1200
            max_h = screen.availableGeometry().height() - 100 if screen else 800
            if px.width() > max_w or px.height() > max_h:
                px = px.scaled(max_w, max_h, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
            self._label.setPixmap(px)

        scroll.setWidget(self._label)
        layout.addWidget(scroll)

        close_btn = QPushButton("关闭")
        close_btn.setStyleSheet("""
            QPushButton { background: #6C63FF; color: white;
                border: none; border-radius: 6px; padding: 5px 18px; }
            QPushButton:hover { background: #8B85FF; }
        """)
        close_btn.clicked.connect(self.close)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close()

    def _apply_stay_on_top(self) -> None:
        """延迟设置 WindowStaysOnTopHint，避免 COM 冲突（Bug #9）"""
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.show()


# --------------------------------------------------------------------------- #
#  视频行
# --------------------------------------------------------------------------- #

class _VideoRow(QWidget):
    delete_requested = pyqtSignal(int)

    def __init__(self, note: TaskNote, parent=None):
        super().__init__(parent)
        self._note = note
        self.setObjectName("VideoRow")
        self.setStyleSheet("""
            #VideoRow { background: rgba(108,99,255,0.06);
                border-radius: 8px; }
            #VideoRow:hover { background: rgba(108,99,255,0.12); }
        """)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._setup_ui()

    def _setup_ui(self) -> None:
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 7, 8, 7)
        row.setSpacing(8)

        icon = QLabel("🎬")
        icon.setFont(QFont("Segoe UI Emoji", 14))
        icon.setFixedWidth(22)

        info_col = QVBoxLayout()
        name_lbl = QLabel(self._note.file_name or "视频")
        name_lbl.setStyleSheet("color: #2D2B3D; font-size: 10px; font-weight: bold;")
        size_str = f"{self._note.file_size / 1024 / 1024:.1f} MB" if self._note.file_size else ""
        size_lbl = QLabel(size_str)
        size_lbl.setStyleSheet("color: #A09DB8; font-size: 9px;")
        info_col.addWidget(name_lbl)
        info_col.addWidget(size_lbl)
        info_col.setSpacing(1)

        open_btn = QPushButton("▶ 打开")
        open_btn.setFixedSize(QSize(60, 24))
        open_btn.setStyleSheet("""
            QPushButton { background: #6C63FF; color: white;
                border: none; border-radius: 5px; font-size: 10px; }
            QPushButton:hover { background: #8B85FF; }
        """)
        open_btn.clicked.connect(self._open_video)

        del_btn = QPushButton("✕")
        del_btn.setFixedSize(20, 20)
        del_btn.setStyleSheet("""
            QPushButton { background: transparent; border: none;
                color: #C0BDDE; font-size: 11px; }
            QPushButton:hover { color: #FF6B6B; }
        """)
        del_btn.clicked.connect(lambda: self.delete_requested.emit(self._note.id))

        row.addWidget(icon)
        row.addLayout(info_col, 1)
        row.addWidget(open_btn)
        row.addWidget(del_btn)

    def _open_video(self) -> None:
        path = self._note.content
        if path and Path(path).exists():
            os.startfile(path)  # Windows
        else:
            QMessageBox.warning(self, "文件不存在", f"找不到文件:\n{path}")


# --------------------------------------------------------------------------- #
#  主详情面板
# --------------------------------------------------------------------------- #

class TaskDetailPanel(QDialog):
    """
    任务详情弹窗

    Signals:
        task_updated(task_id)  任务信息被修改时通知父组件刷新列表
    """

    task_updated = pyqtSignal(int)

    def __init__(
        self,
        task: Task,
        task_repo: TaskRepository,
        note_repo: TaskNoteRepository,
        parent=None,
    ):
        super().__init__(parent)
        self._task = task
        self._task_repo = task_repo
        self._note_repo = note_repo
        self._text_note_id: Optional[int] = None
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(800)  # 800ms 防抖自动保存
        self._save_timer.timeout.connect(self._auto_save_text)

        self.setWindowTitle(f"任务详情 — {task.title}")
        # ⚠️ Bug #9：不在 __init__ 直接设 WindowStaysOnTopHint
        #    FramelessWindowHint 可保留（此面板不需要 WA_TranslucentBackground，风险低）
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
        )
        self.setAcceptDrops(True)
        self.resize(480, 600)

        self._setup_ui()
        self._load_notes()

        # 延迟 200ms 设置置顶，避免 COM 冲突崩溃
        QTimer.singleShot(200, self._apply_stay_on_top)

    def _apply_stay_on_top(self) -> None:
        """延迟设置 WindowStaysOnTopHint，避免 COM 冲突（Bug #9）"""
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.show()

    # ------------------------------------------------------------------ #
    #  UI 搭建
    # ------------------------------------------------------------------ #

    def _setup_ui(self) -> None:
        self.setStyleSheet("""
            QDialog {
                background: #1E1B30;
            }
            QLabel { color: #E8E5FF; background: transparent; }
            QLineEdit {
                background: rgba(40,36,62,0.8);
                border: 1px solid rgba(139,133,255,0.2);
                border-radius: 6px;
                color: #E8E5FF;
                padding: 4px 8px;
            }
            QLineEdit:focus { border-color: #8B85FF; }
            QTextEdit {
                background: rgba(40,36,62,0.8);
                border: 1px solid rgba(139,133,255,0.15);
                border-radius: 8px;
                color: #E8E5FF;
                padding: 8px;
            }
            QTextEdit:focus { border-color: #8B85FF; }
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical { width: 4px; background: transparent; }
            QScrollBar::handle:vertical { background: rgba(139,133,255,0.3); border-radius: 2px; }
        """)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)
        card_layout = root

        # ---- 顶部：标题 + 关闭 ----
        top_row = QHBoxLayout()

        priority_colors = {"high": "#FF6B6B", "medium": "#FFB347", "low": "#52C41A"}
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {priority_colors.get(self._task.priority, '#FFB347')}; font-size: 12px;")
        dot.setFixedWidth(16)

        self._title_edit = QLineEdit(self._task.title)
        self._title_edit.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        self._title_edit.setStyleSheet("""
            QLineEdit { border: none; background: transparent; color: #E8E5FF; }
            QLineEdit:focus { border-bottom: 1px solid #8B85FF; }
        """)
        self._title_edit.editingFinished.connect(self._save_title)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(24, 24)
        close_btn.setStyleSheet("""
            QPushButton { background: transparent; border: none;
                color: #A09DB8; font-size: 12px; }
            QPushButton:hover { color: #FF6B6B; }
        """)
        close_btn.clicked.connect(self.close)

        top_row.addWidget(dot)
        top_row.addWidget(self._title_edit, 1)
        top_row.addWidget(close_btn)
        card_layout.addLayout(top_row)

        # 创建时间
        time_lbl = QLabel(f"创建于 {self._task.created_at[:16]}")
        time_lbl.setStyleSheet("color: #A09DB8; font-size: 9px;")
        card_layout.addWidget(time_lbl)

        self._add_divider(card_layout)

        # ---- 文字结论 ----
        note_header = QLabel("📝 文字结论")
        note_header.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        note_header.setStyleSheet("color: #6C63FF;")
        card_layout.addWidget(note_header)

        self._text_edit = QTextEdit()
        self._text_edit.setPlaceholderText("在这里记录任务结论、心得或备注…（自动保存）")
        self._text_edit.setFont(QFont("Microsoft YaHei", 10))
        self._text_edit.setFixedHeight(110)
        self._text_edit.setStyleSheet("""
            QTextEdit {
                background: rgba(40,36,62,0.8);
                border: 1px solid rgba(139,133,255,0.2);
                border-radius: 8px;
                padding: 8px;
                color: #E8E5FF;
            }
            QTextEdit:focus { border: 1px solid #8B85FF; }
        """)
        self._text_edit.textChanged.connect(self._on_text_changed)
        card_layout.addWidget(self._text_edit)

        self._add_divider(card_layout)

        # ---- 图片区 ----
        img_header_row = QHBoxLayout()
        img_hdr = QLabel("🖼 图片附件")
        img_hdr.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        img_hdr.setStyleSheet("color: #6C63FF;")

        add_img_btn = QPushButton("+ 添加图片")
        add_img_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_img_btn.setStyleSheet("""
            QPushButton { background: transparent; border: 1px dashed #C0BDDE;
                border-radius: 6px; color: #6C63FF; font-size: 10px; padding: 3px 10px; }
            QPushButton:hover { background: #F0EEF8; }
        """)
        add_img_btn.clicked.connect(self._pick_image)

        img_header_row.addWidget(img_hdr)
        img_header_row.addStretch()
        img_header_row.addWidget(add_img_btn)
        card_layout.addLayout(img_header_row)

        # 缩略图网格
        img_scroll = QScrollArea()
        img_scroll.setWidgetResizable(True)
        img_scroll.setFixedHeight(82)
        img_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        img_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        img_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self._img_container = QWidget()
        self._img_container.setStyleSheet("background: transparent;")
        self._img_grid = QHBoxLayout(self._img_container)
        self._img_grid.setContentsMargins(0, 0, 0, 0)
        self._img_grid.setSpacing(6)
        self._img_grid.addStretch()

        img_scroll.setWidget(self._img_container)
        card_layout.addWidget(img_scroll)

        # 拖拽 + 粘贴提示
        self._drag_hint = QLabel("💡 也可以直接将图片/视频拖拽到此窗口，或按 Ctrl+V 粘贴截图")
        self._drag_hint.setStyleSheet("color: #C0BDDE; font-size: 9px;")
        self._drag_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self._drag_hint)

        self._add_divider(card_layout)

        # ---- 视频区 ----
        vid_header_row = QHBoxLayout()
        vid_hdr = QLabel("🎬 视频附件")
        vid_hdr.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        vid_hdr.setStyleSheet("color: #6C63FF;")

        add_vid_btn = QPushButton("+ 添加视频")
        add_vid_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_vid_btn.setStyleSheet("""
            QPushButton { background: transparent; border: 1px dashed #C0BDDE;
                border-radius: 6px; color: #6C63FF; font-size: 10px; padding: 3px 10px; }
            QPushButton:hover { background: #F0EEF8; }
        """)
        add_vid_btn.clicked.connect(self._pick_video)

        vid_header_row.addWidget(vid_hdr)
        vid_header_row.addStretch()
        vid_header_row.addWidget(add_vid_btn)
        card_layout.addLayout(vid_header_row)

        # 视频列表
        vid_scroll = QScrollArea()
        vid_scroll.setWidgetResizable(True)
        vid_scroll.setFixedHeight(100)
        vid_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self._vid_container = QWidget()
        self._vid_container.setStyleSheet("background: transparent;")
        self._vid_list_layout = QVBoxLayout(self._vid_container)
        self._vid_list_layout.setContentsMargins(0, 0, 0, 0)
        self._vid_list_layout.setSpacing(4)
        self._vid_list_layout.addStretch()

        vid_scroll.setWidget(self._vid_container)
        card_layout.addWidget(vid_scroll)

        self._add_divider(card_layout)

        # ---- 文档链接区 ----
        doc_header_row = QHBoxLayout()
        doc_hdr = QLabel("🔗 文档 & 链接")
        doc_hdr.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        doc_hdr.setStyleSheet("color: #8B85FF;")

        add_link_btn = QPushButton("+ 粘贴链接")
        add_link_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_link_btn.setStyleSheet("""
            QPushButton { background: transparent; border: 1px dashed rgba(139,133,255,0.4);
                border-radius: 6px; color: #8B85FF; font-size: 10px; padding: 3px 10px; }
            QPushButton:hover { background: rgba(139,133,255,0.1); }
        """)
        add_link_btn.clicked.connect(self._add_link_from_clipboard)

        add_file_btn = QPushButton("+ 本地文件")
        add_file_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_file_btn.setStyleSheet("""
            QPushButton { background: transparent; border: 1px dashed rgba(139,133,255,0.4);
                border-radius: 6px; color: #8B85FF; font-size: 10px; padding: 3px 10px; }
            QPushButton:hover { background: rgba(139,133,255,0.1); }
        """)
        add_file_btn.clicked.connect(self._pick_doc_file)

        doc_header_row.addWidget(doc_hdr)
        doc_header_row.addStretch()
        doc_header_row.addWidget(add_link_btn)
        doc_header_row.addWidget(add_file_btn)
        card_layout.addLayout(doc_header_row)

        # 文档列表
        doc_scroll = QScrollArea()
        doc_scroll.setWidgetResizable(True)
        doc_scroll.setFixedHeight(110)
        doc_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self._doc_container = QWidget()
        self._doc_container.setStyleSheet("background: transparent;")
        self._doc_list_layout = QVBoxLayout(self._doc_container)
        self._doc_list_layout.setContentsMargins(0, 0, 0, 0)
        self._doc_list_layout.setSpacing(4)
        self._doc_list_layout.addStretch()

        doc_scroll.setWidget(self._doc_container)
        card_layout.addWidget(doc_scroll)

        # 提示
        self._link_hint = QLabel("💡 支持企业微信/飞书/Notion 链接，或粘贴任意 URL；也可拖拽 PDF/Word/Excel 等文件")
        self._link_hint.setStyleSheet("color: rgba(139,133,255,0.5); font-size: 9px;")
        self._link_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self._link_hint)

    def _add_divider(self, layout) -> None:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        line.setStyleSheet("background: rgba(108,99,255,0.1); border: none;")
        layout.addWidget(line)

    # ------------------------------------------------------------------ #
    #  数据加载
    # ------------------------------------------------------------------ #

    def _load_notes(self) -> None:
        notes = self._note_repo.get_by_task(self._task.id)

        # 文字结论
        text_note = next((n for n in notes if n.is_text), None)
        if text_note:
            self._text_note_id = text_note.id
            self._text_edit.blockSignals(True)
            self._text_edit.setPlainText(text_note.content or "")
            self._text_edit.blockSignals(False)

        # 图片
        images = [n for n in notes if n.is_image]
        for note in images:
            self._add_thumb(note)

        # 视频
        videos = [n for n in notes if n.is_video]
        for note in videos:
            self._add_video_row(note)

        # 链接 & 文档文件
        docs = [n for n in notes if n.is_link or n.is_doc_file]
        for note in docs:
            self._add_doc_row(note)

    # ------------------------------------------------------------------ #
    #  文字保存
    # ------------------------------------------------------------------ #

    def _on_text_changed(self) -> None:
        self._save_timer.start()  # 防抖

    def _auto_save_text(self) -> None:
        text = self._text_edit.toPlainText().strip()
        if self._text_note_id is not None:
            self._note_repo.update_text(self._text_note_id, text)
        else:
            if text:
                note = self._note_repo.add_text(self._task.id, text)
                self._text_note_id = note.id

    def _save_title(self) -> None:
        new_title = self._title_edit.text().strip()
        if new_title and new_title != self._task.title:
            self._task.title = new_title
            self._task_repo.update(self._task)
            self.task_updated.emit(self._task.id)

    # ------------------------------------------------------------------ #
    #  图片操作
    # ------------------------------------------------------------------ #

    def _pick_image(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择图片", "",
            "图片文件 (*.png *.jpg *.jpeg *.gif *.webp *.bmp)"
        )
        for p in paths:
            self._add_image_file(p)

    def _add_image_file(self, path: str) -> None:
        try:
            note = self._note_repo.add_file(self._task.id, path, "image")
            self._add_thumb(note)
        except Exception as e:
            QMessageBox.warning(self, "添加失败", str(e))

    def _add_thumb(self, note: TaskNote) -> None:
        card = _ThumbCard(note, self._img_container)
        card.delete_requested.connect(self._delete_note)
        card.preview_requested.connect(self._preview_image)
        # 插在 stretch 之前
        count = self._img_grid.count()
        self._img_grid.insertWidget(count - 1, card)

    def _preview_image(self, path: str) -> None:
        dlg = ImagePreviewDialog(path, self)
        dlg.exec()

    # ------------------------------------------------------------------ #
    #  视频操作
    # ------------------------------------------------------------------ #

    def _pick_video(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择视频", "",
            "视频文件 (*.mp4 *.mov *.avi *.mkv *.wmv *.flv *.webm)"
        )
        for p in paths:
            self._add_video_file(p)

    def _add_video_file(self, path: str) -> None:
        try:
            note = self._note_repo.add_file(self._task.id, path, "video")
            self._add_video_row(note)
        except Exception as e:
            QMessageBox.warning(self, "添加失败", str(e))

    def _add_video_row(self, note: TaskNote) -> None:
        row = _VideoRow(note, self._vid_container)
        row.delete_requested.connect(self._delete_note)
        count = self._vid_list_layout.count()
        self._vid_list_layout.insertWidget(count - 1, row)

    # ------------------------------------------------------------------ #
    #  链接 & 文档操作
    # ------------------------------------------------------------------ #

    def _add_link_from_clipboard(self) -> None:
        """从剪贴板读取 URL，支持企业微信/飞书/Notion/任意链接"""
        clipboard = QApplication.clipboard()
        text = clipboard.text().strip()
        if not text:
            QMessageBox.information(self, "提示", "剪贴板为空，请先复制链接")
            return
        if not (text.startswith("http://") or text.startswith("https://")
                or text.startswith("wxwork://") or text.startswith("feishu://")):
            # 尝试补全 https://
            if "." in text and " " not in text:
                text = "https://" + text
            else:
                QMessageBox.warning(self, "格式错误", "请复制有效的网址链接（http/https）")
                return
        try:
            note = self._note_repo.add_link(self._task.id, text)
            self._add_doc_row(note)
            self._show_link_hint("✓ 链接已添加", success=True)
        except Exception as e:
            QMessageBox.warning(self, "添加失败", str(e))

    def _pick_doc_file(self) -> None:
        """选择本地文档文件"""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择文档文件", "",
            "文档文件 (*.pdf *.doc *.docx *.xls *.xlsx *.ppt *.pptx *.txt *.md *.csv *.zip *.rar);;所有文件 (*)"
        )
        for p in paths:
            try:
                note = self._note_repo.add_doc_file(self._task.id, p)
                self._add_doc_row(note)
            except Exception as e:
                QMessageBox.warning(self, "添加失败", str(e))

    def _add_doc_row(self, note: TaskNote) -> None:
        row = _DocRow(note, self._doc_container)
        row.delete_requested.connect(self._delete_note)
        row.fetch_content_requested.connect(self._fetch_doc_content)
        count = self._doc_list_layout.count()
        self._doc_list_layout.insertWidget(count - 1, row)

    def _fetch_doc_content(self, url: str) -> None:
        """读取文档内容并追加到文字结论区"""
        from services.wxwork_doc_service import WxWorkDocService
        # 获取 settings（通过 task_repo 间接获取，或直接导入）
        try:
            from data.settings_repository import SettingsRepository
            settings = SettingsRepository()
        except Exception:
            settings = None

        service = WxWorkDocService(settings)
        if not service.has_cookie():
            self._show_link_hint("请先在「设置 → 企业微信文档」中配置 Cookie", success=False)
            return

        self._show_link_hint("正在读取文档内容...", success=True)
        QTimer.singleShot(100, lambda: self._do_fetch(service, url))

    def _do_fetch(self, service, url: str) -> None:
        info = service.fetch_doc(url)
        if info.success:
            # 把文档内容追加到文字结论里
            existing = self._text_edit.toPlainText().strip()
            separator = f"\n\n--- 文档内容（{info.title or url}）---\n"
            self._text_edit.setPlainText(
                (existing + separator + info.content) if existing else (separator.strip() + "\n" + info.content)
            )
            self._show_link_hint(f"已读取：{info.title or '文档'}", success=True)
        else:
            self._show_link_hint(info.error or "读取失败", success=False)

    def _show_link_hint(self, msg: str, success: bool = False) -> None:
        color = "#3DDB6B" if success else "#FF6B6B"
        self._link_hint.setText(msg)
        self._link_hint.setStyleSheet(f"color: {color}; font-size: 9px; font-weight: bold;")
        QTimer.singleShot(3000, self._reset_link_hint)

    def _reset_link_hint(self) -> None:
        self._link_hint.setText("💡 支持企业微信/飞书/Notion 链接，或粘贴任意 URL；也可拖拽 PDF/Word/Excel 等文件")
        self._link_hint.setStyleSheet("color: rgba(139,133,255,0.5); font-size: 9px;")

    # ------------------------------------------------------------------ #
    #  删除
    # ------------------------------------------------------------------ #

    def _delete_note(self, note_id: int) -> None:
        if self._text_note_id == note_id:
            self._text_note_id = None
        self._note_repo.delete(note_id)
        # 刷新视图
        self._clear_attachments()
        self._load_notes()

    def _clear_attachments(self) -> None:
        """清空图片、视频、文档 UI（不清文字）"""
        for i in reversed(range(self._img_grid.count())):
            item = self._img_grid.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), _ThumbCard):
                item.widget().deleteLater()
                self._img_grid.removeItem(item)

        for i in reversed(range(self._vid_list_layout.count())):
            item = self._vid_list_layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), _VideoRow):
                item.widget().deleteLater()
                self._vid_list_layout.removeItem(item)

        for i in reversed(range(self._doc_list_layout.count())):
            item = self._doc_list_layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), _DocRow):
                item.widget().deleteLater()
                self._doc_list_layout.removeItem(item)

    # ------------------------------------------------------------------ #
    #  拖拽文件到窗口
    # ------------------------------------------------------------------ #

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path:
                ext = Path(path).suffix.lower()
                if ext in IMAGE_EXTS:
                    self._add_image_file(path)
                elif ext in VIDEO_EXTS:
                    self._add_video_file(path)
                elif ext in DOC_EXTS:
                    try:
                        note = self._note_repo.add_doc_file(self._task.id, path)
                        self._add_doc_row(note)
                    except Exception as e:
                        QMessageBox.warning(self, "添加失败", str(e))
            else:
                # 拖入的是网络 URL
                link = url.toString()
                if link.startswith("http"):
                    try:
                        note = self._note_repo.add_link(self._task.id, link)
                        self._add_doc_row(note)
                        self._show_link_hint("✓ 链接已添加", success=True)
                    except Exception as e:
                        QMessageBox.warning(self, "添加失败", str(e))

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

    def keyPressEvent(self, event) -> None:
        # Ctrl+V 粘贴剪贴板图片
        if event.key() == Qt.Key.Key_V and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            self._paste_from_clipboard()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.close()

    def _paste_from_clipboard(self) -> None:
        """从剪贴板粘贴图片（支持截图工具直接复制的位图）"""
        clipboard = QApplication.clipboard()
        mime = clipboard.mimeData()

        # 优先取图片数据（QPixmap）
        if mime.hasImage():
            px = clipboard.pixmap()
            if not px.isNull():
                self._save_pixmap_as_attachment(px)
                return

        # 其次取文件路径（如从文件管理器复制的图片文件）
        if mime.hasUrls():
            for url in mime.urls():
                path = url.toLocalFile()
                if Path(path).suffix.lower() in IMAGE_EXTS:
                    self._add_image_file(path)
            return

        # 都没有则提示
        self._show_paste_hint("剪贴板中没有图片，请先截图或复制图片文件")

    def _save_pixmap_as_attachment(self, px: "QPixmap") -> None:
        """把剪贴板 QPixmap 保存为 PNG 文件并直接入库（不再二次复制）"""
        from data.task_note_repository import get_attachments_dir, TaskNote
        from datetime import datetime

        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        dest_name = f"t{self._task.id}_paste_{ts}.png"
        dest = get_attachments_dir() / dest_name

        if px.save(str(dest), "PNG"):
            # 文件已存在于附件目录，直接插入数据库记录，不再调用 add_file（避免二次复制）
            note = TaskNote(
                task_id=self._task.id,
                note_type="image",
                content=str(dest),
                file_name=dest_name,
                file_size=dest.stat().st_size,
            )
            saved = self._note_repo._insert(note)
            self._add_thumb(saved)
            self._show_paste_hint("✓ 截图已粘贴", success=True)
        else:
            self._show_paste_hint("图片保存失败，请重试")

    def _show_paste_hint(self, msg: str, success: bool = False) -> None:
        """在拖拽提示行短暂显示粘贴结果"""
        color = "#52C41A" if success else "#FF6B6B"
        self._drag_hint.setText(msg)
        self._drag_hint.setStyleSheet(f"color: {color}; font-size: 9px; font-weight: bold;")
        # 3 秒后恢复原始提示
        QTimer.singleShot(3000, self._reset_hint)

    def _reset_hint(self) -> None:
        self._drag_hint.setText("💡 也可以直接将图片/视频拖拽到此窗口，或按 Ctrl+V 粘贴截图")
        self._drag_hint.setStyleSheet("color: #C0BDDE; font-size: 9px;")

    def closeEvent(self, event) -> None:
        # 关闭时确保文字保存
        self._save_timer.stop()
        self._auto_save_text()
        super().closeEvent(event)
