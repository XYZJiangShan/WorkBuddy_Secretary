"""
task_list_widget.py - 待办任务列表组件

负责：
  - 展示今日待办（未完成置顶，已完成折叠）
  - 自然语言输入框 → 触发 AI 解析 → 确认卡 → 添加到列表
  - 勾选完成、删除任务
  - 通过信号与外部服务通信，自身不直接依赖数据库
"""

from __future__ import annotations

from typing import Optional
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QTimer, QPointF, QRectF
from PyQt6.QtGui import (
    QFont, QColor, QPalette, QKeyEvent, QPainter, QRadialGradient,
    QLinearGradient, QBrush,
)
from PyQt6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from data.task_repository import Task


# --------------------------------------------------------------------------- #
#  优先级灯泡指示器
# --------------------------------------------------------------------------- #

class PriorityLed(QWidget):
    """
    精致玻璃球风格的优先级指示器。
    - 红色（high）= 高优先级
    - 绿色（low/medium）= 普通
    点击时在红/绿之间切换。
    """

    clicked = pyqtSignal()

    # 颜色方案：(主色, 高光色, 外晕色, 暗边色)
    _COLORS = {
        "high":   (QColor("#FF4444"), QColor("#FF9999"), QColor(255, 60, 60, 50),  QColor("#AA0000")),
        "medium": (QColor("#2DD96B"), QColor("#90F0B0"), QColor(50, 220, 100, 50), QColor("#0A8A3A")),
        "low":    (QColor("#2DD96B"), QColor("#90F0B0"), QColor(50, 220, 100, 50), QColor("#0A8A3A")),
    }

    def __init__(self, priority: str = "medium", parent=None):
        super().__init__(parent)
        self._priority = priority
        self._hovered = False
        self.setFixedSize(QSize(16, 16))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("点击切换优先级（红=高 / 绿=普通）")
        self.setMouseTracking(True)

    def set_priority(self, priority: str) -> None:
        self._priority = priority
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        r = 5.0 * (1.12 if self._hovered else 1.0)

        main_c, highlight_c, glow_c, dark_c = self._COLORS.get(
            self._priority, self._COLORS["medium"]
        )
        p.setPen(Qt.PenStyle.NoPen)

        # ---- 1. 柔和外发光 ----
        glow = QRadialGradient(QPointF(cx, cy), r * 2.5)
        glow.setColorAt(0.0, glow_c)
        glow_mid = QColor(glow_c)
        glow_mid.setAlpha(20)
        glow.setColorAt(0.5, glow_mid)
        glow_edge = QColor(glow_c)
        glow_edge.setAlpha(0)
        glow.setColorAt(1.0, glow_edge)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QRectF(cx - r * 2.5, cy - r * 2.5, r * 5, r * 5))

        # ---- 2. 底部投影（微妙阴影感）----
        shadow = QRadialGradient(QPointF(cx, cy + r * 0.4), r * 1.1)
        shadow.setColorAt(0.0, QColor(0, 0, 0, 30))
        shadow.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(shadow))
        p.drawEllipse(QRectF(cx - r * 1.1, cy - r * 0.7, r * 2.2, r * 2.2))

        # ---- 3. 主球体（三层渐变：高光→主色→暗边）----
        body = QRadialGradient(QPointF(cx - r * 0.25, cy - r * 0.3), r * 1.2)
        body.setColorAt(0.0, highlight_c)
        body.setColorAt(0.35, main_c)
        body.setColorAt(0.85, main_c.darker(130))
        body.setColorAt(1.0, dark_c)
        p.setBrush(QBrush(body))
        p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        # ---- 4. 边缘环光（半透明描边增强立体感）----
        ring = QRadialGradient(QPointF(cx, cy), r)
        ring_c = QColor(255, 255, 255, 0)
        ring.setColorAt(0.0, ring_c)
        ring.setColorAt(0.75, ring_c)
        ring.setColorAt(0.92, QColor(255, 255, 255, 25))
        ring.setColorAt(1.0, QColor(255, 255, 255, 8))
        p.setBrush(QBrush(ring))
        p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        # ---- 5. 主高光（左上白色弧形，模拟窗口反射）----
        hi = QRadialGradient(QPointF(cx - r * 0.3, cy - r * 0.35), r * 0.55)
        hi.setColorAt(0.0, QColor(255, 255, 255, 210))
        hi.setColorAt(0.5, QColor(255, 255, 255, 80))
        hi.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(hi))
        p.drawEllipse(QRectF(cx - r * 0.78, cy - r * 0.8, r * 1.0, r * 0.7))

        # ---- 6. 小光点（增强玻璃质感）----
        dot = QRadialGradient(QPointF(cx - r * 0.15, cy - r * 0.2), r * 0.18)
        dot.setColorAt(0.0, QColor(255, 255, 255, 255))
        dot.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(dot))
        p.drawEllipse(QRectF(cx - r * 0.32, cy - r * 0.38, r * 0.35, r * 0.35))

        p.end()





# --------------------------------------------------------------------------- #
#  单条任务行
# --------------------------------------------------------------------------- #

class TaskItemWidget(QWidget):
    """单条任务的行展示组件"""

    check_toggled = pyqtSignal(int, bool)       # (task_id, done)
    delete_clicked = pyqtSignal(int)            # task_id
    detail_requested = pyqtSignal(int, int, int)  # (task_id, global_x, global_bottom_y)
    priority_changed = pyqtSignal(int, str)     # (task_id, new_priority)

    def __init__(self, task: Task, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._task = task
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setObjectName("TaskItem")
        self.setStyleSheet("""
            #TaskItem {
                background: rgba(255,255,255,0.5);
                border-radius: 8px;
                margin: 2px 0;
            }
            #TaskItem:hover { background: rgba(255,255,255,0.75); }
        """)

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(6)

        # 优先级灯泡（可点击红/绿切换）
        led = PriorityLed(self._task.priority, self)
        led.clicked.connect(self._on_priority_clicked)
        self._dot_btn = led

        # 勾选框
        check = QCheckBox()
        check.setChecked(self._task.done)
        check.setFixedSize(QSize(18, 18))
        check.setCursor(Qt.CursorShape.PointingHandCursor)
        check.stateChanged.connect(
            lambda state: self.check_toggled.emit(
                self._task.id, bool(state)
            )
        )
        self._check = check

        # 标题（可点击展开详情）
        title = QLabel(self._task.title)
        title_font = QFont("Microsoft YaHei", 10)
        if self._task.done:
            title_font.setStrikeOut(True)
        title.setFont(title_font)
        title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        title.setWordWrap(False)
        title.setCursor(Qt.CursorShape.PointingHandCursor)
        # tooltip 显示完整标题 + 操作提示
        tip = f"{self._task.title}\n─────────────\n点击查看详情 / 添加笔记和附件"
        title.setToolTip(tip)
        title.mousePressEvent = lambda e: self._emit_detail_with_pos()
        self._title_lbl = title

        # 截止时间
        widgets_right: list[QWidget] = []
        self._due_label = None
        if self._task.due_time:
            due_label = QLabel(self._task.due_time[5:16])  # MM-DD HH:MM
            due_label.setStyleSheet("color: #A09DB8; font-size: 9px;")
            widgets_right.append(due_label)
            self._due_label = due_label

        # 详情按钮（右侧小箭头）
        detail_btn = QPushButton("›")
        detail_btn.setFixedSize(QSize(16, 16))
        detail_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        detail_btn.setToolTip("展开详情")
        detail_btn.setStyleSheet("""
            QPushButton { background: transparent; border: none;
                          color: transparent; font-size: 13px; font-weight: bold; }
            QPushButton:hover { color: #6C63FF; }
        """)
        detail_btn.clicked.connect(self._emit_detail_with_pos)

        # 删除按钮（hover 才显示）
        del_btn = QPushButton("✕")
        del_btn.setFixedSize(QSize(18, 18))
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.setStyleSheet("""
            QPushButton { background: transparent; border: none;
                          color: transparent; font-size: 10px; }
            QPushButton:hover { color: #FF6B6B; }
        """)
        del_btn.clicked.connect(lambda: self.delete_clicked.emit(self._task.id))

        row.addWidget(led)
        row.addWidget(check)
        row.addWidget(title, 1)
        for w in widgets_right:
            row.addWidget(w)
        row.addWidget(detail_btn)
        row.addWidget(del_btn)

        self._del_btn = del_btn
        self._detail_btn = detail_btn
        self.setMouseTracking(True)

    def _emit_detail_with_pos(self) -> None:
        """发送 detail_requested 信号，附带本任务行底部的全局坐标"""
        global_bottom_left = self.mapToGlobal(self.rect().bottomLeft())
        self.detail_requested.emit(
            self._task.id,
            global_bottom_left.x(),
            global_bottom_left.y(),
        )

    def _on_priority_clicked(self) -> None:
        """红绿两档切换：high（红）↔ medium（绿）"""
        new_priority = "medium" if self._task.priority == "high" else "high"
        self._task.priority = new_priority
        # 更新灯泡颜色
        self._dot_btn.set_priority(new_priority)
        self.priority_changed.emit(self._task.id, new_priority)

    def enterEvent(self, event) -> None:
        self._del_btn.setStyleSheet("""
            QPushButton { background: transparent; border: none;
                          color: #C0BDDE; font-size: 10px; }
            QPushButton:hover { color: #FF6B6B; }
        """)
        self._detail_btn.setStyleSheet("""
            QPushButton { background: transparent; border: none;
                          color: #C0BDDE; font-size: 13px; font-weight: bold; }
            QPushButton:hover { color: #6C63FF; }
        """)

    def leaveEvent(self, event) -> None:
        self._del_btn.setStyleSheet("""
            QPushButton { background: transparent; border: none;
                          color: transparent; font-size: 10px; }
            QPushButton:hover { color: #FF6B6B; }
        """)
        self._detail_btn.setStyleSheet("""
            QPushButton { background: transparent; border: none;
                          color: transparent; font-size: 13px; }
            QPushButton:hover { color: #6C63FF; }
        """)

    def apply_theme(self, theme) -> None:
        """响应主题切换"""
        # 任务行背景
        self.setStyleSheet(f"""
            #TaskItem {{
                background: {theme.bg_task_item};
                border-radius: 8px;
                margin: 2px 0;
            }}
            #TaskItem:hover {{ background: {theme.bg_hover}; }}
        """)
        # 灯泡优先级指示器（自绘，无需 stylesheet 干预）
        self._dot_btn.set_priority(self._task.priority)
        # 标题文字色
        if self._task.done:
            self._title_lbl.setStyleSheet(f"color: {theme.text_placeholder};")
        else:
            self._title_lbl.setStyleSheet(f"color: {theme.text_primary};")
        # 截止时间色
        if self._due_label:
            self._due_label.setStyleSheet(
                f"color: {theme.text_placeholder}; font-size: 9px;"
            )
        # checkbox 在深色下强制用白色文字（QSS 控制 indicator）
        if theme.name == "dark":
            self._check.setStyleSheet("""
                QCheckBox::indicator { border: 1px solid #6660A0; border-radius: 3px;
                    background: rgba(60,55,90,0.8); }
                QCheckBox::indicator:checked { background: #8B85FF;
                    border-color: #8B85FF; }
            """)
        else:
            self._check.setStyleSheet("")


# --------------------------------------------------------------------------- #
#  AI 解析结果确认卡
# --------------------------------------------------------------------------- #

class ParseResultCard(QWidget):
    """AI 解析结果确认卡，嵌入输入框下方"""

    confirmed = pyqtSignal(dict)   # 用户确认，传出解析结果
    cancelled = pyqtSignal()

    _PRIORITY_COLORS = {"high": "#FF6B6B", "medium": "#FFB347", "low": "#52C41A"}
    _PRIORITY_LABELS = {"high": "高优先", "medium": "中优先", "low": "低优先"}

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._parsed: dict = {}
        self._setup_ui()
        self.hide()

    def _setup_ui(self) -> None:
        self.setObjectName("ParseCard")
        self.setStyleSheet("""
            #ParseCard {
                background: rgba(240, 238, 248, 0.97);
                border: 1px solid #D4D1F0;
                border-radius: 10px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        # 标题行
        header = QLabel("AI 解析结果")
        header.setStyleSheet("color: #6C63FF; font-size: 10px; font-weight: bold;")
        layout.addWidget(header)

        # 信息行
        self._title_label = QLabel()
        self._title_label.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        self._title_label.setStyleSheet("color: #2D2B3D;")
        self._title_label.setWordWrap(True)
        layout.addWidget(self._title_label)

        info_row = QHBoxLayout()
        info_row.setSpacing(8)

        self._priority_badge = QLabel()
        self._priority_badge.setFixedHeight(20)
        self._priority_badge.setStyleSheet(
            "border-radius: 4px; padding: 0 6px; font-size: 10px; color: white;"
        )

        self._due_label = QLabel()
        self._due_label.setStyleSheet("color: #6B6880; font-size: 10px;")

        info_row.addWidget(self._priority_badge)
        info_row.addWidget(self._due_label)
        info_row.addStretch()
        layout.addLayout(info_row)

        # 按钮行
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        confirm_btn = QPushButton("✓ 确认添加")
        confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        confirm_btn.setStyleSheet("""
            QPushButton {
                background: #6C63FF; color: white;
                border: none; border-radius: 6px;
                padding: 4px 12px; font-size: 11px;
            }
            QPushButton:hover { background: #8B85FF; }
        """)

        cancel_btn = QPushButton("重新输入")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background: transparent; color: #6B6880;
                border: 1px solid #C0BDDE; border-radius: 6px;
                padding: 4px 10px; font-size: 11px;
            }
            QPushButton:hover { background: #F0EEF8; }
        """)

        confirm_btn.clicked.connect(self._on_confirm)
        cancel_btn.clicked.connect(self._on_cancel)

        btn_row.addWidget(confirm_btn)
        btn_row.addWidget(cancel_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def show_result(self, parsed: dict) -> None:
        """展示解析结果"""
        self._parsed = parsed
        self._title_label.setText(parsed.get("title", ""))
        priority = parsed.get("priority", "medium")
        color = self._PRIORITY_COLORS.get(priority, "#FFB347")
        label = self._PRIORITY_LABELS.get(priority, "中优先")
        self._priority_badge.setText(label)
        self._priority_badge.setStyleSheet(
            f"border-radius: 4px; padding: 0 6px; font-size: 10px; "
            f"color: white; background: {color};"
        )
        due = parsed.get("due_time")
        self._due_label.setText(f"⏰ {due}" if due else "无截止时间")
        self.show()

    def show_error(self, msg: str) -> None:
        """显示解析错误提示"""
        self._title_label.setText(f"解析失败：{msg}")
        self._priority_badge.hide()
        self._due_label.hide()
        self.show()

    def _on_confirm(self) -> None:
        self.confirmed.emit(self._parsed)
        self.hide()

    def _on_cancel(self) -> None:
        self.cancelled.emit()
        self.hide()


# --------------------------------------------------------------------------- #
#  任务列表主组件
# --------------------------------------------------------------------------- #

class TaskListWidget(QWidget):
    """
    完整的任务列表组件，包含：
    - 任务滚动列表（未完成 + 已完成折叠区）
    - 底部自然语言输入框
    - AI 解析确认卡

    Signals:
        task_add_requested(text: str)   用户回车，请求 AI 解析
        task_confirmed(parsed: dict)    用户确认解析结果，请求添加任务
        task_check_toggled(id, done)    勾选状态变化
        task_deleted(id)                删除任务
        review_requested()              用户点击"今日复盘"
    """

    task_add_requested = pyqtSignal(str)
    task_confirmed = pyqtSignal(dict)
    task_check_toggled = pyqtSignal(int, bool)
    task_deleted = pyqtSignal(int)
    review_requested = pyqtSignal()
    task_detail_requested = pyqtSignal(int, int, int)  # (task_id, global_x, global_bottom_y)
    task_priority_changed = pyqtSignal(int, str)        # (task_id, new_priority)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tasks: list[Task] = []
        self._ai_mode: bool = True
        self._current_theme = None   # 缓存当前主题，新建任务行时立即应用
        self._setup_ui()

    # ------------------------------------------------------------------ #
    #  UI 搭建
    # ------------------------------------------------------------------ #

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- 标题栏 ----
        header = QHBoxLayout()
        header.setContentsMargins(12, 8, 12, 4)

        today_label = QLabel("今日待办")
        today_label.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        today_label.setStyleSheet("color: #2D2B3D;")
        self._today_label = today_label   # 供 apply_theme 使用

        self._count_label = QLabel("0 项")
        self._count_label.setStyleSheet("color: #A09DB8; font-size: 10px;")

        review_btn = QPushButton("今日复盘 ✨")
        review_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        review_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: 1px solid #C0BDDE;
                border-radius: 5px;
                color: #6C63FF;
                font-size: 10px;
                padding: 2px 8px;
            }
            QPushButton:hover { background: #F0EEF8; }
        """)
        review_btn.clicked.connect(self.review_requested)
        self._review_btn = review_btn   # 保存引用，供 set_ai_mode 使用

        header.addWidget(today_label)
        header.addWidget(self._count_label)
        header.addStretch()
        header.addWidget(review_btn)
        root.addLayout(header)

        # ---- 分隔线 ----
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: rgba(108,99,255,0.15);")
        self._divider = line   # 供 apply_theme 使用
        root.addWidget(line)

        # ---- 任务滚动区 ----
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical {
                width: 4px; background: transparent;
            }
            QScrollBar::handle:vertical {
                background: rgba(108,99,255,0.3); border-radius: 2px;
            }
        """)

        self._list_container = QWidget()
        self._list_container.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(8, 4, 8, 4)
        self._list_layout.setSpacing(2)
        self._list_layout.addStretch()

        # 空状态提示
        self._empty_label = QLabel("还没有待办事项\n在下方输入任务开始吧 👇")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet("color: #C0BDDE; font-size: 10px;")
        self._list_layout.insertWidget(0, self._empty_label)

        scroll.setWidget(self._list_container)
        root.addWidget(scroll, 1)

        # ---- AI 解析确认卡 ----
        self._parse_card = ParseResultCard(self)
        self._parse_card.confirmed.connect(self.task_confirmed)
        self._parse_card.cancelled.connect(self._on_parse_cancelled)
        root.addWidget(self._parse_card)

        # ---- 输入区 ----
        input_area = QWidget()
        input_area.setStyleSheet("""
            background: rgba(255,255,255,0.6);
            border-top: 1px solid rgba(108,99,255,0.12);
        """)
        self._input_area = input_area   # 供 apply_theme 使用
        input_row = QHBoxLayout(input_area)
        input_row.setContentsMargins(10, 7, 10, 7)
        input_row.setSpacing(6)

        self._input = QLineEdit()
        self._input.setPlaceholderText("用自然语言输入任务，回车 AI 解析…")
        self._input.setFont(QFont("Microsoft YaHei", 10))
        self._input.setStyleSheet("""
            QLineEdit {
                border: none;
                background: transparent;
                color: #2D2B3D;
            }
        """)
        self._input.returnPressed.connect(self._on_input_enter)

        add_btn = QPushButton("→")
        add_btn.setFixedSize(QSize(28, 28))
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setStyleSheet("""
            QPushButton {
                background: #6C63FF; color: white;
                border: none; border-radius: 6px; font-size: 14px;
            }
            QPushButton:hover { background: #8B85FF; }
        """)
        add_btn.clicked.connect(self._on_input_enter)
        self._add_btn = add_btn   # 供 apply_theme 使用

        # AI 加载提示
        self._loading_label = QLabel("AI 解析中…")
        self._loading_label.setStyleSheet("color: #6C63FF; font-size: 10px;")
        self._loading_label.hide()

        input_row.addWidget(self._input, 1)
        input_row.addWidget(self._loading_label)
        input_row.addWidget(add_btn)
        root.addWidget(input_area)

    # ------------------------------------------------------------------ #
    #  公共 API
    # ------------------------------------------------------------------ #

    def load_tasks(self, tasks: list[Task]) -> None:
        """加载（刷新）任务列表"""
        self._tasks = tasks
        self._rebuild_list()

    def set_ai_mode(self, enabled: bool) -> None:
        """
        切换 AI 模式。
        enabled=True  → 输入框触发 AI 解析，显示复盘按钮
        enabled=False → 输入框直接添加任务，隐藏复盘按钮和 AI 相关 UI
        """
        self._ai_mode = enabled
        if enabled:
            self._input.setPlaceholderText("用自然语言输入任务，回车 AI 解析…")
            self._review_btn.show()
            self._loading_label.hide()
        else:
            self._input.setPlaceholderText("输入任务名称，回车快速添加…")
            self._review_btn.hide()
            self._loading_label.hide()
            self._parse_card.hide()

    def show_ai_loading(self, loading: bool) -> None:
        """显示/隐藏 AI 解析中提示"""
        if self._ai_mode:
            self._loading_label.setVisible(loading)
            self._input.setEnabled(not loading)

    def show_parse_result(self, parsed: dict) -> None:
        """展示 AI 解析结果确认卡"""
        if self._ai_mode:
            self.show_ai_loading(False)
            self._parse_card.show_result(parsed)

    def show_parse_error(self, msg: str) -> None:
        """展示解析错误"""
        if self._ai_mode:
            self.show_ai_loading(False)
            self._parse_card.show_error(msg)

    # ------------------------------------------------------------------ #
    #  内部：列表重建
    # ------------------------------------------------------------------ #

    def _rebuild_list(self) -> None:
        """清空并重新渲染所有任务行"""
        # 移除所有动态添加的 widget（除了空状态标签和 stretch）
        for i in reversed(range(self._list_layout.count())):
            item = self._list_layout.itemAt(i)
            if item and item.widget():
                w = item.widget()
                if w is self._empty_label:
                    continue  # 保留空状态提示
                self._list_layout.removeWidget(w)
                w.deleteLater()

        undone = [t for t in self._tasks if not t.done]
        done = [t for t in self._tasks if t.done]
        total = len(undone)

        self._count_label.setText(f"{total} 项待完成")
        self._empty_label.setVisible(len(self._tasks) == 0)

        # 未完成任务
        insert_pos = 0
        for task in undone:
            item = TaskItemWidget(task)
            if self._current_theme:
                item.apply_theme(self._current_theme)
            item.check_toggled.connect(self.task_check_toggled)
            item.delete_clicked.connect(self.task_deleted)
            item.detail_requested.connect(self.task_detail_requested)
            item.priority_changed.connect(self.task_priority_changed)
            self._list_layout.insertWidget(insert_pos, item)
            insert_pos += 1

        # 已完成分隔
        if done:
            sep_label = QLabel(f"已完成 ({len(done)})")
            color = self._current_theme.text_placeholder if self._current_theme else "#A09DB8"
            sep_label.setStyleSheet(
                f"color: {color}; font-size: 9px; margin: 4px 8px 2px; background: transparent;"
            )
            self._list_layout.insertWidget(insert_pos, sep_label)
            insert_pos += 1
            for task in done:
                item = TaskItemWidget(task)
                if self._current_theme:
                    item.apply_theme(self._current_theme)
                item.check_toggled.connect(self.task_check_toggled)
                item.delete_clicked.connect(self.task_deleted)
                item.detail_requested.connect(self.task_detail_requested)
                self._list_layout.insertWidget(insert_pos, item)
                insert_pos += 1

    # ------------------------------------------------------------------ #
    #  槽
    # ------------------------------------------------------------------ #

    def _on_input_enter(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()

        if not self._ai_mode:
            # 纯本地模式：直接以文本作为任务标题，无需 AI 解析
            self.task_confirmed.emit({"title": text, "priority": "medium", "due_time": None})
        else:
            self.show_ai_loading(True)
            self.task_add_requested.emit(text)

    def _on_parse_cancelled(self) -> None:
        self._input.setFocus()

    def apply_theme(self, theme) -> None:
        """响应主题切换，全量重新应用所有子组件样式"""
        self._current_theme = theme   # 缓存，供 _rebuild_list 使用
        is_dark = theme.name == "dark"

        # 滚动区容器
        self._list_container.setStyleSheet("background: transparent;")

        # 空状态提示
        self._empty_label.setStyleSheet(
            f"color: {theme.text_placeholder}; font-size: 10px;"
        )

        # 标题区标签
        self._today_label.setStyleSheet(
            f"color: {theme.text_primary}; background: transparent;"
        )
        self._count_label.setStyleSheet(
            f"color: {theme.text_placeholder}; font-size: 10px; background: transparent;"
        )

        # 复盘按钮
        self._review_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 1px solid {theme.border_accent};
                border-radius: 5px;
                color: {theme.accent};
                font-size: 10px;
                padding: 2px 8px;
            }}
            QPushButton:hover {{ background: rgba(108,99,255,0.12); }}
        """)

        # 分隔线
        self._divider.setStyleSheet(f"color: {theme.border};")

        # 输入区背景
        self._input_area.setStyleSheet(f"""
            background: {theme.bg_input};
            border-top: 1px solid {theme.border};
        """)

        # 输入框文字
        self._input.setStyleSheet(f"""
            QLineEdit {{
                border: none;
                background: transparent;
                color: {theme.text_primary};
            }}
        """)

        # 发送按钮
        self._add_btn.setStyleSheet(f"""
            QPushButton {{
                background: {theme.accent}; color: white;
                border: none; border-radius: 6px; font-size: 14px;
            }}
            QPushButton:hover {{ background: {theme.accent_hover}; }}
        """)

        # AI loading 提示
        self._loading_label.setStyleSheet(
            f"color: {theme.accent}; font-size: 10px;"
        )

        # 刷新已有任务行的样式
        self._rebuild_list_theme(theme)

    def _rebuild_list_theme(self, theme) -> None:
        """对已渲染的任务行重新设置颜色（避免整体重建）"""
        for i in range(self._list_layout.count()):
            item = self._list_layout.itemAt(i)
            if item and item.widget():
                w = item.widget()
                if isinstance(w, TaskItemWidget):
                    w.apply_theme(theme)
                elif not isinstance(w, type(self._empty_label)):
                    # 已完成分隔线标签
                    w.setStyleSheet(
                        f"color: {theme.text_placeholder}; font-size: 9px; "
                        f"margin: 4px 8px 2px; background: transparent;"
                    )
