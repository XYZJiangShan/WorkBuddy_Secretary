"""
edge_snap.py - 边缘吸附与迷你模式管理器

功能：
  1. 窗口拖拽结束时检测是否靠近屏幕边缘（阈值 40px），自动吸附
  2. 吸附后折叠为"迷你条"（高 48px，全宽贴边），显示：
       - 番茄钟倒计时（或状态图标）
       - 休息提醒倒计时进度
       - 当前时间
  3. 鼠标悬浮在迷你条上时，展开为完整窗口（延迟 200ms 防误触）
  4. 鼠标离开展开区域后，延迟 1.5s 重新折叠
  5. 提醒触发时，迷你条也会短暂高亮 + 显示文案
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Optional

from PyQt6.QtCore import (
    QObject, QPoint, QRect, QSize, QTimer, Qt, pyqtSignal,
)
from PyQt6.QtGui import (
    QColor, QPainter, QLinearGradient, QBrush,
)
from PyQt6.QtWidgets import QApplication, QWidget

logger = logging.getLogger(__name__)

SNAP_THRESHOLD = 40      # 距屏幕边缘多少像素触发吸附
MINI_H = 14              # 迷你条高度（紧凑但可放装饰元素，避免极薄窗口的渲染问题）
MINI_W = 220             # 迷你条参考宽度（实际全宽由窗口决定）
HOVER_EXPAND_DELAY = 80  # 悬浮 80ms 后展开
AUTO_COLLAPSE_DELAY = 100   # 鼠标离开 100ms 后折叠
POLL_INTERVAL = 80       # 鼠标位置轮询间隔


class SnapEdge(Enum):
    NONE = "none"
    LEFT = "left"
    RIGHT = "right"
    TOP = "top"
    BOTTOM = "bottom"


class EdgeSnapManager(QObject):
    """
    边缘吸附管理器，挂载到 FloatingWindow 上使用。

    Signals:
        snapped(edge)        吸附到某边缘
        unsnapped()          脱离吸附
        mini_mode_entered()  进入迷你模式
        mini_mode_exited()   退出迷你模式
    """

    snapped = pyqtSignal(str)
    unsnapped = pyqtSignal()
    mini_mode_entered = pyqtSignal()
    mini_mode_exited = pyqtSignal()

    def __init__(self, window: QWidget, full_h: int, parent=None):
        super().__init__(parent)
        self._win = window
        self._full_h = full_h
        self._edge = SnapEdge.NONE
        self._mini = False
        self._expanded = False   # 吸附中且已展开（有别于完全没有吸附）
        self._screen_geo: Optional[QRect] = None

        # 展开延迟（悬浮后 200ms 才展开，防误触）
        self._expand_timer = QTimer(self)
        self._expand_timer.setSingleShot(True)
        self._expand_timer.setInterval(HOVER_EXPAND_DELAY)
        self._expand_timer.timeout.connect(self._do_expand)

        # 折叠延迟（离开后 1.5s 折叠）
        self._collapse_timer = QTimer(self)
        self._collapse_timer.setSingleShot(True)
        self._collapse_timer.setInterval(AUTO_COLLAPSE_DELAY)
        self._collapse_timer.timeout.connect(self._do_collapse)

        # 鼠标位置轮询（迷你状态下检测进入，展开状态下检测离开）
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(POLL_INTERVAL)
        self._poll_timer.timeout.connect(self._poll_mouse)

    # ------------------------------------------------------------------ #
    #  公共 API（由 FloatingWindow 调用）
    # ------------------------------------------------------------------ #

    def on_drag_end(self, window_rect: QRect) -> bool:
        """
        拖拽结束时调用，判断是否应该吸附。
        返回 True 表示发生了吸附（窗口位置已被修改）。
        """
        screen = QApplication.primaryScreen()
        if not screen:
            return False
        geo = screen.availableGeometry()
        self._screen_geo = geo
        x, y = window_rect.x(), window_rect.y()
        w, h = window_rect.width(), window_rect.height()
        edge = SnapEdge.NONE

        if x <= SNAP_THRESHOLD:
            edge = SnapEdge.LEFT
            new_x = 0
            new_y = max(geo.top(), min(y, geo.bottom() - MINI_H))
        elif x + w >= geo.right() - SNAP_THRESHOLD:
            edge = SnapEdge.RIGHT
            new_x = geo.right() - w
            new_y = max(geo.top(), min(y, geo.bottom() - MINI_H))
        elif y <= SNAP_THRESHOLD:
            edge = SnapEdge.TOP
            new_x = max(geo.left(), min(x, geo.right() - w))
            new_y = geo.top()
        elif y + h >= geo.bottom() - SNAP_THRESHOLD:
            edge = SnapEdge.BOTTOM
            new_x = max(geo.left(), min(x, geo.right() - w))
            new_y = geo.bottom() - MINI_H
        else:
            if self._edge != SnapEdge.NONE:
                self._leave_snap()
            return False

        if edge != SnapEdge.NONE:
            self._enter_snap(edge, new_x, new_y)
            return True
        return False

    def on_mouse_enter(self) -> None:
        """鼠标进入窗口区域（由 FloatingWindow.enterEvent 调用，作为辅助触发）"""
        if self._edge == SnapEdge.NONE:
            return
        self._collapse_timer.stop()
        # 迷你状态下，enterEvent 可能不稳定，轮询是主要触发方式
        # 这里作为额外补充：直接启动展开计时
        if self._mini and not self._expand_timer.isActive():
            self._expand_timer.start()

    def on_mouse_leave(self) -> None:
        """鼠标离开窗口区域（由 FloatingWindow.leaveEvent 调用，作为辅助触发）"""
        if self._edge == SnapEdge.NONE:
            return
        if self._mini:
            # 迷你状态：取消展开
            self._expand_timer.stop()
        # 展开状态由轮询负责检测，leaveEvent 不够可靠，不单独处理

    def _poll_mouse(self) -> None:
        """
        统一轮询逻辑：
        - 迷你状态：检测鼠标是否进入 → 触发展开
        - 展开状态：检测鼠标是否离开 → 触发折叠
        """
        if self._edge == SnapEdge.NONE:
            self._poll_timer.stop()
            return

        from PyQt6.QtGui import QCursor
        cursor_pos = QCursor.pos()
        win_rect = self._win.frameGeometry()

        if self._mini:
            # 迷你模式：鼠标进入窗口范围则启动展开计时
            hover_rect = win_rect.adjusted(-4, -4, 4, 4)  # 留4px容差
            if hover_rect.contains(cursor_pos):
                if not self._expand_timer.isActive():
                    self._expand_timer.start()
            else:
                self._expand_timer.stop()

        elif self._expanded:
            # 展开模式：检测鼠标是否离开
            # 如果有子对话框（如任务详情面板）打开，暂停所有折叠行为
            if self._has_visible_child_dialog():
                self._collapse_timer.stop()
                # 继续轮询，等子对话框关闭后恢复正常检测
                return

            leave_rect = win_rect.adjusted(-8, -8, 8, 8)  # 留8px容差防抖
            if not leave_rect.contains(cursor_pos):
                self._poll_timer.stop()
                if not self._collapse_timer.isActive():
                    self._collapse_timer.start()
            else:
                self._collapse_timer.stop()

        else:
            self._poll_timer.stop()

    def restart_poll_after_dialog(self) -> None:
        """子对话框关闭后重启折叠检测轮询"""
        if self._expanded and not self._poll_timer.isActive():
            self._poll_timer.start()

    def _has_visible_child_dialog(self) -> bool:
        """检查主窗口是否有可见的关联对话框（通过 _detail_panels 列表）"""
        panels = getattr(self._win, "_detail_panels", [])
        return any(p.isVisible() for p in panels if p is not None)

    def force_expand(self) -> None:
        """提醒触发时强制展开（无论当前是迷你还是已展开，都确保可见）"""
        if self._mini:
            self._do_expand()
        # 已展开时取消折叠计时，保持展开
        self._collapse_timer.stop()

    @property
    def edge(self) -> SnapEdge:
        return self._edge

    @property
    def is_mini(self) -> bool:
        """True = 当前处于折叠迷你状态"""
        return self._mini

    @property
    def is_snapped(self) -> bool:
        """True = 当前处于吸附状态（无论折叠还是展开）"""
        return self._edge != SnapEdge.NONE

    # ------------------------------------------------------------------ #
    #  内部
    # ------------------------------------------------------------------ #

    def _enter_snap(self, edge: SnapEdge, x: int, y: int) -> None:
        self._edge = edge
        self._win.move(x, y)
        self._do_collapse()
        self.snapped.emit(edge.value)
        logger.debug("吸附到 %s 边缘", edge.value)

    def _leave_snap(self) -> None:
        self._edge = SnapEdge.NONE
        self._mini = False
        self._expanded = False
        self._expand_timer.stop()
        self._collapse_timer.stop()
        self._poll_timer.stop()
        self._restore_full()
        self.unsnapped.emit()

    def _do_collapse(self) -> None:
        """折叠为迷你条"""
        self._collapse_timer.stop()
        # 有子对话框打开时不折叠（用户正在查看详情）
        if self._has_visible_child_dialog():
            # 重启轮询，等子对话框关闭后再继续检测
            if not self._poll_timer.isActive():
                self._poll_timer.start()
            return
        if not self._mini:
            self._mini = True
            self._expanded = False
            # 记录原始宽度，展开时恢复
            self._original_w = self._win.width()
            # ① 先发信号：让 FloatingWindow 降低 minimumSize + 隐藏卡片
            self.mini_mode_entered.emit()
            # ② 再 resize（此时 minimumSize 已被 _on_mini_entered 降低，resize 生效）
            self._win.resize(self._original_w, MINI_H)
        # 迷你模式下启动轮询，检测鼠标何时悬浮进入
        if not self._poll_timer.isActive():
            self._poll_timer.start()

    def _do_expand(self) -> None:
        """展开为完整窗口"""
        self._expand_timer.stop()
        if self._mini:
            self._mini = False
            self._expanded = True   # 标记：吸附中 + 已展开
            geo = self._screen_geo or QApplication.primaryScreen().availableGeometry()

            # ① 先发信号：让 FloatingWindow 恢复 minimumSize + 隐藏 minibar
            self.mini_mode_exited.emit()

            # ② 再 resize（此时 minimumSize 已恢复，resize 到完整高度生效）
            restore_w = getattr(self, '_original_w', 310)
            self._win.resize(restore_w, self._full_h)

            # 确保不超出屏幕
            wx, wy = self._win.x(), self._win.y()
            if self._edge == SnapEdge.BOTTOM:
                wy = geo.bottom() - self._full_h
            self._win.move(
                max(geo.left(), min(wx, geo.right() - restore_w)),
                max(geo.top(), min(wy, geo.bottom() - self._full_h)),
            )
            # 展开后立即启动轮询，监视鼠标是否离开
            self._poll_timer.start()

    def _restore_full(self) -> None:
        self._win.resize(self._win.width(), self._full_h)


# --------------------------------------------------------------------------- #
#  迷你状态栏 Widget（浮在窗口顶部）
# --------------------------------------------------------------------------- #

class MiniBar(QWidget):
    """
    吸附后显示的迷你信息条（高 MINI_H = 10px，纯色细条，不显示任何文字）

    鼠标悬浮时展开为完整窗口。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(MINI_H)
        self._is_dark = False
        self._reminder_ratio = 1.0

    # ------------------------------------------------------------------ #
    #  主题
    # ------------------------------------------------------------------ #

    def apply_theme(self, theme) -> None:
        """随主题切换背景色"""
        self._is_dark = theme.name == "dark"
        self.update()  # 重绘背景

    # ------------------------------------------------------------------ #
    #  数据更新（保留接口兼容，但不再显示内容）
    # ------------------------------------------------------------------ #

    def update_pomodoro(self, text: str, color: str = "#FF6B6B") -> None:
        pass  # 迷你条不显示文字

    def update_reminder(self, seconds_left: int, total: int) -> None:
        self._reminder_ratio = seconds_left / total if total > 0 else 1.0
        self.update()  # 可能改变颜色

    def show_alert(self, text: str) -> None:
        pass  # 提醒时直接展开，不在迷你条显示

    # ------------------------------------------------------------------ #
    #  绘制背景（纯色细条 + 品牌色指示线）
    # ------------------------------------------------------------------ #

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        # 关闭抗锯齿：直角矩形避免边缘出现半透明像素
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        w, h = self.width(), self.height()

        # ---- 1) 背景：纵向渐变（顶亮底暗，营造质感）----
        # 关键约束：所有像素必须 alpha=255，禁止贴近窗口边缘画彩色装饰
        bg_grad = QLinearGradient(0, 0, 0, h)
        if self._is_dark:
            bg_grad.setColorAt(0.0, QColor(38, 33, 62))      # 顶部稍亮
            bg_grad.setColorAt(1.0, QColor(22, 19, 42))      # 底部深沉
            accent = QColor(139, 133, 255)                    # 品牌紫 #8B85FF
            # 预混色：品牌色 30% 叠加在背景顶部色上（避免使用 alpha）
            highlight = QColor(60, 55, 120)                   # 偏紫的亮色
        else:
            bg_grad.setColorAt(0.0, QColor(248, 246, 255))
            bg_grad.setColorAt(1.0, QColor(228, 224, 245))
            accent = QColor(108, 99, 255)                     # 品牌紫 #6C63FF
            highlight = QColor(200, 195, 240)                 # 偏紫的浅亮色
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(bg_grad))
        p.drawRect(0, 0, w, h)

        # ---- 2) 顶部 1px 高光线（不透明预混色，营造玻璃感）----
        # 距离左右边缘各 12px，避免贴边外溢
        p.setBrush(QBrush(highlight))
        p.drawRect(12, 0, w - 24, 1)

        # ---- 3) 左右对称品牌色装饰小块（距边缘 8px，距上下各 4px）----
        # 永远不贴近任何窗口边缘 —— layered window 渲染安全
        block_w = 28
        block_h = h - 8         # 上下各留 4px 边距
        margin = 8              # 距左右边缘 8px
        p.setBrush(QBrush(accent))
        p.drawRect(margin, 4, block_w, block_h)
        p.drawRect(w - margin - block_w, 4, block_w, block_h)

        # ---- 4) 中心提醒进度（仅当倒计时 < 30% 时显示，作为"即将触发"提示）----
        if self._reminder_ratio < 0.3:
            center_y = h // 2
            # 可填充区域：左右两个 block + margin + 8px 间距
            inner_left = margin + block_w + 8
            inner_right = w - margin - block_w - 8
            inner_w = max(0, inner_right - inner_left)
            fill_w = int(inner_w * (1.0 - self._reminder_ratio / 0.3))
            fill_w = max(0, min(fill_w, inner_w))
            if fill_w > 0:
                start_x = inner_left + (inner_w - fill_w) // 2
                p.setBrush(QBrush(accent))
                p.drawRect(start_x, center_y - 1, fill_w, 2)

        p.end()
