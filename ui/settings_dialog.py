"""
settings_dialog.py - 设置弹窗（v2）

四组配置：
  1. AI 接口：API Key / Base URL / 模型名
  2. 提醒配置：间隔分钟数滑块 / 开关
  3. 外观：深色模式开关 / 透明度滑块
  4. 番茄钟：专注时长 / 短休息 / 长休息 / 热键开关
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QSlider, QVBoxLayout, QWidget,
    QScrollArea,
)

from data.settings_repository import SettingsRepository


class SettingsDialog(QDialog):
    """设置弹窗 v2"""

    settings_saved = pyqtSignal()

    def __init__(self, settings: SettingsRepository, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._setup_ui()
        self._load_values()

    # ------------------------------------------------------------------ #
    #  UI 搭建
    # ------------------------------------------------------------------ #

    def _setup_ui(self) -> None:
        self.setWindowTitle("设置")
        self.setFixedWidth(420)
        self.setMaximumHeight(640)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)

        card = QWidget()
        card.setObjectName("SettingsCard")
        card.setStyleSheet("""
            #SettingsCard {
                background: rgba(254, 252, 247, 0.97);
                border-radius: 16px;
                border: 1px solid rgba(108, 99, 255, 0.18);
            }
        """)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        # ---- 标题行 ----
        title_bar = QWidget()
        title_bar.setFixedHeight(52)
        title_row = QHBoxLayout(title_bar)
        title_row.setContentsMargins(20, 0, 16, 0)

        title_lbl = QLabel("⚙️  设置")
        title_lbl.setFont(QFont("Microsoft YaHei", 13, QFont.Weight.Bold))
        title_lbl.setStyleSheet("color: #2D2B3D;")

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(24, 24)
        close_btn.setStyleSheet("""
            QPushButton { background: transparent; border: none;
                color: #A09DB8; font-size: 12px; }
            QPushButton:hover { color: #FF6B6B; }
        """)
        close_btn.clicked.connect(self.close)

        title_row.addWidget(title_lbl)
        title_row.addStretch()
        title_row.addWidget(close_btn)
        card_layout.addWidget(title_bar)

        self._add_divider(card_layout)

        # ---- 滚动内容区 ----
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical { width: 4px; background: transparent; }
            QScrollBar::handle:vertical { background: rgba(108,99,255,0.3); border-radius: 2px; }
        """)

        scroll_widget = QWidget()
        scroll_widget.setStyleSheet("background: transparent;")
        content_layout = QVBoxLayout(scroll_widget)
        content_layout.setContentsMargins(20, 12, 20, 12)
        content_layout.setSpacing(14)

        # ---- 1. AI 配置 ----
        content_layout.addWidget(self._section_label("🤖 AI 接口配置"))

        # AI 总开关
        self._ai_enabled_check = QCheckBox("启用 AI 功能（任务智能解析 / 提醒文案 / 今日复盘）")
        self._ai_enabled_check.setStyleSheet("color: #2D2B3D; font-size: 11px; font-weight: bold;")
        self._ai_enabled_check.setCursor(Qt.CursorShape.PointingHandCursor)
        content_layout.addWidget(self._ai_enabled_check)

        # AI 配置子区域（受总开关控制）
        self._ai_config_group = QWidget()
        ai_group_layout = QVBoxLayout(self._ai_config_group)
        ai_group_layout.setContentsMargins(12, 4, 0, 0)
        ai_group_layout.setSpacing(8)

        self._api_key_input = self._make_line_edit("输入 API Key（sk-...）", password=True)
        ai_group_layout.addWidget(self._field_row("API Key", self._api_key_input))
        self._base_url_input = self._make_line_edit("https://api.deepseek.com/v1")
        ai_group_layout.addWidget(self._field_row("Base URL", self._base_url_input))
        self._model_input = self._make_line_edit("deepseek-chat")
        ai_group_layout.addWidget(self._field_row("模型名称", self._model_input))

        content_layout.addWidget(self._ai_config_group)

        # 总开关联动
        self._ai_enabled_check.toggled.connect(self._ai_config_group.setEnabled)

        self._add_divider(content_layout)

        # ---- 2. 提醒配置 ----
        content_layout.addWidget(self._section_label("🔔 提醒配置"))
        self._enabled_check = QCheckBox("启用定时休息提醒")
        self._enabled_check.setStyleSheet("color: #2D2B3D; font-size: 11px;")
        self._enabled_check.setCursor(Qt.CursorShape.PointingHandCursor)
        content_layout.addWidget(self._enabled_check)

        self._interval_slider, self._interval_value_label = self._make_slider(5, 120, 45, "分钟")
        content_layout.addLayout(self._slider_row("提醒间隔", self._interval_slider, self._interval_value_label))

        self._add_divider(content_layout)

        # ---- 3. 外观配置 ----
        content_layout.addWidget(self._section_label("🎨 外观配置"))

        self._dark_mode_check = QCheckBox("深色模式")
        self._dark_mode_check.setStyleSheet("color: #2D2B3D; font-size: 11px;")
        self._dark_mode_check.setCursor(Qt.CursorShape.PointingHandCursor)
        content_layout.addWidget(self._dark_mode_check)

        self._opacity_slider, self._opacity_value_label = self._make_slider(
            0, 100, 92, "%", scale=0.01, fmt="{:.0f}%"
        )
        content_layout.addLayout(self._slider_row("窗口透明度", self._opacity_slider, self._opacity_value_label))

        self._add_divider(content_layout)

        # ---- 4. 番茄钟配置 ----
        content_layout.addWidget(self._section_label("🍅 番茄钟配置"))

        self._focus_slider, self._focus_value_label = self._make_slider(5, 60, 25, "分钟")
        content_layout.addLayout(self._slider_row("专注时长", self._focus_slider, self._focus_value_label))

        self._short_break_slider, self._short_break_value_label = self._make_slider(1, 15, 5, "分钟")
        content_layout.addLayout(self._slider_row("短休息", self._short_break_slider, self._short_break_value_label))

        self._long_break_slider, self._long_break_value_label = self._make_slider(5, 30, 15, "分钟")
        content_layout.addLayout(self._slider_row("长休息", self._long_break_slider, self._long_break_value_label))

        self._add_divider(content_layout)

        # ---- 5. 热键配置 ----
        content_layout.addWidget(self._section_label("⌨️ 全局热键"))
        self._hotkey_enabled_check = QCheckBox("启用全局热键（Alt+空格 唤出窗口）")
        self._hotkey_enabled_check.setStyleSheet("color: #2D2B3D; font-size: 11px;")
        self._hotkey_enabled_check.setCursor(Qt.CursorShape.PointingHandCursor)
        content_layout.addWidget(self._hotkey_enabled_check)

        # ---- 6. 企业微信文档 Cookie ----
        content_layout.addWidget(self._section_label("🔗 企业微信文档访问"))

        cookie_hint = QLabel(
            "粘贴 Cookie 后可在任务详情中读取企微文档内容供 AI 分析。\n"
            "获取方式：Chrome 打开企微文档 → F12 → Network → 任意请求 → Request Headers → cookie 行"
        )
        cookie_hint.setStyleSheet("color: #6B6880; font-size: 10px;")
        cookie_hint.setWordWrap(True)
        content_layout.addWidget(cookie_hint)

        self._wxwork_cookie_edit = QLineEdit()
        self._wxwork_cookie_edit.setPlaceholderText("粘贴企业微信文档 Cookie（如：pac_uid=xxx; skey=xxx; ...）")
        self._wxwork_cookie_edit.setEchoMode(QLineEdit.EchoMode.Password)  # 隐藏敏感内容
        self._wxwork_cookie_edit.setStyleSheet("""
            QLineEdit {
                border: 1px solid #C0BDDE; border-radius: 6px;
                padding: 6px 10px; font-size: 10px; color: #2D2B3D;
                background: rgba(255,255,255,0.6);
            }
            QLineEdit:focus { border-color: #6C63FF; }
        """)
        content_layout.addWidget(self._wxwork_cookie_edit)

        cookie_status_row = QHBoxLayout()
        self._wxwork_cookie_status = QLabel("未配置")
        self._wxwork_cookie_status.setStyleSheet("color: #A09DB8; font-size: 10px;")
        show_cookie_btn = QPushButton("显示/隐藏")
        show_cookie_btn.setFixedHeight(24)
        show_cookie_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        show_cookie_btn.setStyleSheet("""
            QPushButton { background: transparent; border: 1px solid #C0BDDE;
                border-radius: 4px; color: #6B6880; font-size: 10px; padding: 0 8px; }
            QPushButton:hover { background: #F0EEF8; }
        """)
        show_cookie_btn.clicked.connect(self._toggle_cookie_visibility)
        clear_cookie_btn = QPushButton("清除")
        clear_cookie_btn.setFixedHeight(24)
        clear_cookie_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_cookie_btn.setStyleSheet("""
            QPushButton { background: transparent; border: 1px solid #C0BDDE;
                border-radius: 4px; color: #FF6B6B; font-size: 10px; padding: 0 8px; }
            QPushButton:hover { background: rgba(255,107,107,0.08); }
        """)
        clear_cookie_btn.clicked.connect(lambda: self._wxwork_cookie_edit.clear())
        cookie_status_row.addWidget(self._wxwork_cookie_status)
        cookie_status_row.addStretch()
        cookie_status_row.addWidget(show_cookie_btn)
        cookie_status_row.addWidget(clear_cookie_btn)
        content_layout.addLayout(cookie_status_row)

        content_layout.addStretch()
        scroll.setWidget(scroll_widget)
        card_layout.addWidget(scroll, 1)

        self._add_divider(card_layout)

        # ---- 底部按钮 ----
        btn_area = QWidget()
        btn_area.setFixedHeight(52)
        btn_row = QHBoxLayout(btn_area)
        btn_row.setContentsMargins(20, 0, 20, 0)
        btn_row.setSpacing(8)

        save_btn = QPushButton("保存")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setStyleSheet("""
            QPushButton {
                background: #6C63FF; color: white;
                border: none; border-radius: 8px;
                padding: 6px 20px; font-size: 11px;
            }
            QPushButton:hover { background: #8B85FF; }
        """)
        save_btn.clicked.connect(self._on_save)

        cancel_btn = QPushButton("取消")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background: transparent; color: #6B6880;
                border: 1px solid #C0BDDE; border-radius: 8px;
                padding: 6px 16px; font-size: 11px;
            }
            QPushButton:hover { background: #F0EEF8; }
        """)
        cancel_btn.clicked.connect(self.close)

        btn_row.addStretch()
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        card_layout.addWidget(btn_area)

        root.addWidget(card)

    # ------------------------------------------------------------------ #
    #  辅助构建函数
    # ------------------------------------------------------------------ #

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        label.setStyleSheet("color: #6C63FF;")
        return label

    def _add_divider(self, layout) -> None:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        line.setStyleSheet("background: rgba(108,99,255,0.12); border: none;")
        layout.addWidget(line)

    def _field_row(self, label_text: str, widget: QWidget) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        label = QLabel(label_text)
        label.setStyleSheet("color: #6B6880; font-size: 11px;")
        label.setFixedWidth(72)
        layout.addWidget(label)
        layout.addWidget(widget, 1)
        return row

    def _make_slider(self, min_val: int, max_val: int, default: int,
                     unit: str, scale: float = 1.0, fmt: str = "") -> tuple:
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(min_val, max_val)
        slider.setValue(default)
        slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 4px; background: #E0DEF4; border-radius: 2px;
            }
            QSlider::handle:horizontal {
                width: 14px; height: 14px; margin: -5px 0;
                background: #6C63FF; border-radius: 7px;
            }
            QSlider::sub-page:horizontal {
                background: #6C63FF; border-radius: 2px;
            }
        """)
        value_label = QLabel(f"{default} {unit}")
        value_label.setStyleSheet("color: #6C63FF; font-size: 11px; font-weight: bold;")
        value_label.setFixedWidth(58)

        def update_label(v: int) -> None:
            if fmt:
                value_label.setText(fmt.format(v * scale))
            else:
                value_label.setText(f"{v} {unit}")

        slider.valueChanged.connect(update_label)
        return slider, value_label

    def _slider_row(self, label_text: str, slider: QSlider, value_label: QLabel) -> QHBoxLayout:
        row = QHBoxLayout()
        label = QLabel(label_text)
        label.setStyleSheet("color: #6B6880; font-size: 11px;")
        label.setFixedWidth(72)
        row.addWidget(label)
        row.addWidget(slider, 1)
        row.addWidget(value_label)
        return row

    def _make_line_edit(self, placeholder: str, password: bool = False) -> QLineEdit:
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        edit.setFont(QFont("Microsoft YaHei", 10))
        if password:
            edit.setEchoMode(QLineEdit.EchoMode.Password)
        edit.setStyleSheet("""
            QLineEdit {
                background: rgba(240,238,248,0.7);
                border: 1px solid rgba(108,99,255,0.2);
                border-radius: 6px; padding: 4px 8px; color: #2D2B3D;
            }
            QLineEdit:focus { border: 1px solid #6C63FF; background: rgba(240,238,248,0.95); }
        """)
        return edit

    # ------------------------------------------------------------------ #
    #  数据加载 / 保存
    # ------------------------------------------------------------------ #

    def _load_values(self) -> None:
        ai_enabled = self._settings.get_bool("ai_enabled", True)
        self._ai_enabled_check.setChecked(ai_enabled)
        self._ai_config_group.setEnabled(ai_enabled)
        self._api_key_input.setText(self._settings.get("ai_api_key", ""))
        self._base_url_input.setText(self._settings.get("ai_base_url", "https://api.deepseek.com/v1"))
        self._model_input.setText(self._settings.get("ai_model", "deepseek-chat"))
        self._enabled_check.setChecked(self._settings.get_bool("reminder_enabled", True))
        self._interval_slider.setValue(self._settings.get_int("reminder_interval_minutes", 45))
        self._dark_mode_check.setChecked(self._settings.get("theme", "light") == "dark")
        opacity_pct = int(self._settings.get_float("window_opacity", 0.92) * 100)
        self._opacity_slider.setValue(opacity_pct)
        self._opacity_value_label.setText(f"{opacity_pct}%")
        self._focus_slider.setValue(self._settings.get_int("pomodoro_focus_minutes", 25))
        self._short_break_slider.setValue(self._settings.get_int("pomodoro_short_break_minutes", 5))
        self._long_break_slider.setValue(self._settings.get_int("pomodoro_long_break_minutes", 15))
        self._hotkey_enabled_check.setChecked(self._settings.get_bool("hotkey_enabled", True))
        # 企微 Cookie
        cookie = self._settings.get("wxwork_cookie", "")
        self._wxwork_cookie_edit.setText(cookie)
        if cookie:
            self._wxwork_cookie_status.setText(f"已配置（{len(cookie)} 字符）")
            self._wxwork_cookie_status.setStyleSheet("color: #52C41A; font-size: 10px;")
        else:
            self._wxwork_cookie_status.setText("未配置")
            self._wxwork_cookie_status.setStyleSheet("color: #A09DB8; font-size: 10px;")

    def _toggle_cookie_visibility(self) -> None:
        if self._wxwork_cookie_edit.echoMode() == QLineEdit.EchoMode.Password:
            self._wxwork_cookie_edit.setEchoMode(QLineEdit.EchoMode.Normal)
        else:
            self._wxwork_cookie_edit.setEchoMode(QLineEdit.EchoMode.Password)

    def _on_save(self) -> None:
        self._settings.set_many({
            "ai_enabled": "1" if self._ai_enabled_check.isChecked() else "0",
            "ai_api_key": self._api_key_input.text().strip(),
            "ai_base_url": self._base_url_input.text().strip(),
            "ai_model": self._model_input.text().strip(),
            "reminder_enabled": "1" if self._enabled_check.isChecked() else "0",
            "reminder_interval_minutes": str(self._interval_slider.value()),
            "theme": "dark" if self._dark_mode_check.isChecked() else "light",
            "window_opacity": f"{self._opacity_slider.value() / 100:.2f}",
            "pomodoro_focus_minutes": str(self._focus_slider.value()),
            "pomodoro_short_break_minutes": str(self._short_break_slider.value()),
            "pomodoro_long_break_minutes": str(self._long_break_slider.value()),
            "hotkey_enabled": "1" if self._hotkey_enabled_check.isChecked() else "0",
            "wxwork_cookie": self._wxwork_cookie_edit.text().strip(),
        })
        self.settings_saved.emit()
        self.close()

    # ------------------------------------------------------------------ #
    #  鼠标拖拽
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
