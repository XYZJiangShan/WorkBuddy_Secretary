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

import math
import time

from PyQt6.QtCore import (
    QObject, QPoint, QRect, QRectF, QSize, QTimer, Qt, pyqtSignal,
)
from PyQt6.QtGui import (
    QColor, QPainter, QLinearGradient, QBrush, QPainterPath, QRegion, QCursor, QPen,
)
from PyQt6.QtWidgets import QApplication, QWidget

logger = logging.getLogger(__name__)

SNAP_THRESHOLD = 40      # 距屏幕边缘多少像素触发吸附
MINI_H = 18              # 迷你条高度（容纳眨眼眼睛动画）
MINI_W = 220             # 迷你条参考宽度（实际全宽由窗口决定）
MINI_RADIUS = 6          # 迷你条圆角半径
HOVER_EXPAND_DELAY = 80  # 悬浮 80ms 后展开

# ---- 眨眼动画参数 ----
BLINK_INTERVAL_MS = 3500   # 眨眼周期：每 3.5s 触发一次
BLINK_DURATION_MS = 180    # 单次眨眼持续：180ms（睁→闭→睁）
ANIM_FRAME_MS = 33         # ~30fps 重绘频率（眨眼+瞳孔跟随）
AUTO_COLLAPSE_DELAY = 100   # 鼠标离开 100ms 后折叠
POLL_INTERVAL = 80       # 鼠标位置轮询间隔


# --------------------------------------------------------------------------- #
#  迷你条配色方案（5 套，可在设置里切换）
# --------------------------------------------------------------------------- #
#
# 每套包含两个主题（dark / light），字段含义：
#   bg_top / bg_bottom   背景纵向渐变
#   accent               强调色（嘴巴、提醒进度条）
#   sclera               眼白
#   iris                 虹膜
#   pupil                瞳孔（深色，用于眼睛中心点）
#   highlight            顶部 1px 高光线
#   eyelid               闭眼时的覆盖色（与背景接近）
#
# 设计原则：bg_top/bg_bottom alpha 都是 255（不透明），避免 layered window 白边
#

MINI_PALETTES: dict[str, dict] = {
    # E - 极光蓝紫（默认推荐）：冷静专业，长时间不疲劳
    "aurora": {
        "label": "🫐 极光蓝紫",
        "dark": {
            "bg_top":    (26, 31, 54),    # 深蓝 #1A1F36
            "bg_bottom": (14, 20, 38),    # 更深 #0E1426
            "accent":    (125, 211, 252), # 天青 #7DD3FC
            "sclera":    (240, 248, 255),
            "iris":      (96, 165, 250),  # 蓝紫 #60A5FA
            "pupil":     (15, 23, 42),
            "highlight": (45, 60, 100),
            "eyelid":    (20, 26, 45),
        },
        "light": {
            "bg_top":    (240, 245, 255),
            "bg_bottom": (215, 226, 245),
            "accent":    (37, 99, 235),
            "sclera":    (255, 255, 255),
            "iris":      (59, 130, 246),
            "pupil":     (30, 41, 59),
            "highlight": (190, 210, 240),
            "eyelid":    (225, 232, 248),
        },
    },
    # A - 深海蓝绿：科技感、深邃
    "ocean": {
        "label": "🌊 深海蓝绿",
        "dark": {
            "bg_top":    (15, 32, 39),    # #0F2027
            "bg_bottom": (32, 58, 67),    # #203A43
            "accent":    (127, 232, 213), # 薄荷绿 #7FE8D5
            "sclera":    (235, 250, 248),
            "iris":      (78, 205, 196),  # #4ECDC4
            "pupil":     (10, 22, 28),
            "highlight": (40, 75, 85),
            "eyelid":    (20, 40, 47),
        },
        "light": {
            "bg_top":    (230, 248, 245),
            "bg_bottom": (200, 232, 226),
            "accent":    (15, 118, 110),
            "sclera":    (255, 255, 255),
            "iris":      (20, 184, 166),
            "pupil":     (15, 42, 38),
            "highlight": (180, 220, 215),
            "eyelid":    (210, 235, 230),
        },
    },
    # B - 暮光暖橙：温暖放松，晚间友好
    "twilight": {
        "label": "🌅 暮光暖橙",
        "dark": {
            "bg_top":    (45, 27, 46),    # 暗紫红 #2D1B2E
            "bg_bottom": (26, 15, 31),    # #1A0F1F
            "accent":    (255, 176, 136), # 蜜桃 #FFB088
            "sclera":    (255, 245, 235),
            "iris":      (245, 158, 110), # 暖橙
            "pupil":     (35, 18, 22),
            "highlight": (75, 45, 65),
            "eyelid":    (32, 22, 35),
        },
        "light": {
            "bg_top":    (255, 244, 235),
            "bg_bottom": (250, 220, 200),
            "accent":    (217, 119, 87),
            "sclera":    (255, 255, 255),
            "iris":      (234, 140, 100),
            "pupil":     (74, 38, 30),
            "highlight": (235, 215, 195),
            "eyelid":    (245, 225, 210),
        },
    },
    # C - 森林墨绿：自然克制，不抢眼
    "forest": {
        "label": "🌲 森林墨绿",
        "dark": {
            "bg_top":    (31, 45, 42),    # #1F2D2A
            "bg_bottom": (14, 26, 23),    # #0E1A17
            "accent":    (168, 213, 186), # 鼠尾草绿 #A8D5BA
            "sclera":    (240, 248, 240),
            "iris":      (134, 188, 156),
            "pupil":     (12, 22, 18),
            "highlight": (45, 65, 58),
            "eyelid":    (20, 32, 28),
        },
        "light": {
            "bg_top":    (235, 245, 235),
            "bg_bottom": (210, 228, 215),
            "accent":    (52, 124, 84),
            "sclera":    (255, 255, 255),
            "iris":      (90, 160, 110),
            "pupil":     (20, 50, 32),
            "highlight": (190, 215, 195),
            "eyelid":    (215, 232, 220),
        },
    },
    # D - 莫兰迪奶咖：温柔高级感、护眼
    "morandi": {
        "label": "🪵 莫兰迪奶咖",
        "dark": {
            "bg_top":    (43, 38, 32),    # 暖灰棕 #2B2620
            "bg_bottom": (26, 22, 18),    # #1A1612
            "accent":    (232, 220, 196), # 米白 #E8DCC4
            "sclera":    (252, 247, 235),
            "iris":      (200, 175, 145),
            "pupil":     (40, 30, 22),
            "highlight": (75, 65, 55),
            "eyelid":    (35, 28, 22),
        },
        "light": {
            "bg_top":    (250, 245, 235),
            "bg_bottom": (228, 218, 200),
            "accent":    (138, 110, 78),
            "sclera":    (255, 255, 255),
            "iris":      (175, 142, 105),
            "pupil":     (66, 50, 35),
            "highlight": (220, 208, 188),
            "eyelid":    (238, 225, 205),
        },
    },
    # 紫色（保留原配色，作为兼容选项）
    "purple": {
        "label": "💜 经典紫（原版）",
        "dark": {
            "bg_top":    (42, 36, 70),
            "bg_bottom": (22, 19, 42),
            "accent":    (139, 133, 255),
            "sclera":    (245, 243, 255),
            "iris":      (108, 99, 230),
            "pupil":     (20, 17, 40),
            "highlight": (70, 62, 130),
            "eyelid":    (28, 24, 52),
        },
        "light": {
            "bg_top":    (248, 246, 255),
            "bg_bottom": (228, 224, 245),
            "accent":    (108, 99, 255),
            "sclera":    (255, 255, 255),
            "iris":      (108, 99, 255),
            "pupil":     (40, 35, 80),
            "highlight": (200, 195, 240),
            "eyelid":    (238, 234, 250),
        },
    },
}

DEFAULT_PALETTE = "aurora"


def get_palette_options() -> list[tuple[str, str]]:
    """返回 [(palette_id, label), ...] 用于设置弹窗下拉填充"""
    # 推荐顺序：极光 → 深海 → 森林 → 暮光 → 莫兰迪 → 经典紫
    order = ["aurora", "ocean", "forest", "twilight", "morandi", "purple"]
    return [(pid, MINI_PALETTES[pid]["label"]) for pid in order if pid in MINI_PALETTES]


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
        self._palette_id = DEFAULT_PALETTE      # 当前配色方案 id
        self._reminder_ratio = 1.0

        # 眨眼动画状态
        self._blink_phase = 0.0          # 0.0=睁眼 → 1.0=完全闭眼
        self._next_blink_at = time.monotonic() * 1000 + BLINK_INTERVAL_MS
        self._blink_start_at: Optional[float] = None  # 当前正在眨眼则为开始时刻 ms

        # 鼠标位置追踪（瞳孔跟随）
        self.setMouseTracking(True)
        self._mouse_pos = QPoint(-9999, -9999)  # 全局坐标系

        # 帧驱动定时器（30fps）
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(ANIM_FRAME_MS)
        self._anim_timer.timeout.connect(self._tick)
        self._anim_timer.start()

    # ------------------------------------------------------------------ #
    #  动画驱动
    # ------------------------------------------------------------------ #

    def _tick(self) -> None:
        """每帧推进眨眼动画 + 触发重绘"""
        now_ms = time.monotonic() * 1000

        # 是否进入眨眼周期
        if self._blink_start_at is None and now_ms >= self._next_blink_at:
            self._blink_start_at = now_ms

        # 计算眨眼相位（0=睁→1=闭→0=睁，正弦曲线，更柔和）
        if self._blink_start_at is not None:
            elapsed = now_ms - self._blink_start_at
            if elapsed >= BLINK_DURATION_MS:
                self._blink_phase = 0.0
                self._blink_start_at = None
                self._next_blink_at = now_ms + BLINK_INTERVAL_MS
            else:
                # 半正弦：0→π 对应睁→闭→睁
                self._blink_phase = math.sin(math.pi * (elapsed / BLINK_DURATION_MS))

        # 取鼠标全局位置用于瞳孔跟随
        self._mouse_pos = QCursor.pos()

        self.update()

    # ------------------------------------------------------------------ #
    #  圆角 mask（每次大小变化时同步）
    # ------------------------------------------------------------------ #

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # 用 QRegion 给自身做圆角裁剪 —— 圆角外的像素不参与合成，避免半透明白边
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self.width(), self.height()),
                            float(MINI_RADIUS), float(MINI_RADIUS))
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    # ------------------------------------------------------------------ #
    #  主题
    # ------------------------------------------------------------------ #

    def apply_theme(self, theme) -> None:
        """随主题切换背景色"""
        self._is_dark = theme.name == "dark"
        self.update()  # 重绘背景

    def apply_palette(self, palette_id: str) -> None:
        """切换配色方案。palette_id 必须是 MINI_PALETTES 的 key。"""
        if palette_id in MINI_PALETTES:
            self._palette_id = palette_id
            self.update()

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
        # 开启抗锯齿：圆角 + 椭圆眼睛需要平滑边缘
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()

        # ---- 1) 圆角背景：纵向渐变（顶亮底暗，营造质感）----
        # 因为外层有 setMask 圆角裁剪，这里直接画 roundedRect 双重保险
        # 配色从 MINI_PALETTES 取，按当前 palette_id + dark/light 选择
        palette_set = MINI_PALETTES.get(self._palette_id, MINI_PALETTES[DEFAULT_PALETTE])
        colors = palette_set["dark"] if self._is_dark else palette_set["light"]

        bg_top = QColor(*colors["bg_top"])
        bg_bottom = QColor(*colors["bg_bottom"])
        accent = QColor(*colors["accent"])
        sclera = QColor(*colors["sclera"])
        iris = QColor(*colors["iris"])
        pupil = QColor(*colors["pupil"])
        highlight = QColor(*colors["highlight"])
        eyelid = QColor(*colors["eyelid"])

        bg_grad = QLinearGradient(0, 0, 0, h)
        bg_grad.setColorAt(0.0, bg_top)
        bg_grad.setColorAt(1.0, bg_bottom)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(bg_grad))
        p.drawRoundedRect(QRectF(0, 0, w, h), float(MINI_RADIUS), float(MINI_RADIUS))

        # ---- 2) 顶部 1px 高光线（圆角内距左右 14px）----
        p.setBrush(QBrush(highlight))
        p.drawRect(14, 1, w - 28, 1)

        # ---- 3) 左右两只眼睛 ----
        eye_w = 14.0
        eye_h = max(6.0, h - 8.0)        # 眼睛高度比条少 8（上下各 4 边距）
        eye_y = (h - eye_h) / 2.0
        margin = 12.0                    # 距左右边缘
        left_cx = margin + eye_w / 2.0
        right_cx = w - margin - eye_w / 2.0

        for cx in (left_cx, right_cx):
            self._draw_eye(p, cx, eye_y + eye_h / 2.0, eye_w, eye_h,
                           sclera, iris, pupil, eyelid)

        # ---- 4) 嘴巴：两眼之间的微笑弧线 ----
        # 仅在不显示"提醒进度条"时绘制（进度条会占用中央区域）
        if self._reminder_ratio >= 0.3:
            # 使用 accent（亮紫）而非 pupil（暗黑）：在深色背景上对比度更高
            self._draw_mouth(p, w, h, left_cx, right_cx, accent)

        # ---- 5) 中心提醒进度（仅当倒计时 < 30% 时显示）----
        if self._reminder_ratio < 0.3:
            center_y = h // 2
            inner_left = int(margin + eye_w + 8)
            inner_right = int(w - margin - eye_w - 8)
            inner_w = max(0, inner_right - inner_left)
            fill_w = int(inner_w * (1.0 - self._reminder_ratio / 0.3))
            fill_w = max(0, min(fill_w, inner_w))
            if fill_w > 0:
                start_x = inner_left + (inner_w - fill_w) // 2
                p.setBrush(QBrush(accent))
                p.drawRect(start_x, center_y - 1, fill_w, 2)

        p.end()

    # ------------------------------------------------------------------ #
    #  绘制单只眼睛（眼白 + 虹膜 + 瞳孔 + 眨眼时的眼睑覆盖）
    # ------------------------------------------------------------------ #

    def _draw_eye(self, p: QPainter, cx: float, cy: float, w: float, h: float,
                  sclera: QColor, iris: QColor, pupil: QColor, eyelid: QColor) -> None:
        """以 (cx, cy) 为中心画一只眼睛，宽 w 高 h（h 在眨眼时被压扁）"""
        # 眨眼：phase=0 → 完全睁开；phase=1 → 完全闭合（高度趋近 0）
        open_ratio = 1.0 - self._blink_phase
        cur_h = max(0.6, h * open_ratio)

        # ---- 眼白（椭圆）----
        eye_rect = QRectF(cx - w / 2.0, cy - cur_h / 2.0, w, cur_h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(sclera))
        p.drawEllipse(eye_rect)

        # 完全闭眼时不画虹膜
        if open_ratio < 0.15:
            return

        # ---- 瞳孔目标位置（跟随鼠标）----
        # 取鼠标全局坐标转换到本 widget 坐标
        mouse_local = self.mapFromGlobal(self._mouse_pos)
        dx = mouse_local.x() - cx
        dy = mouse_local.y() - cy
        # 限制瞳孔在虹膜半径内移动
        max_off_x = w * 0.18
        max_off_y = cur_h * 0.18
        # 归一化方向
        dist = max(1e-3, math.hypot(dx, dy))
        ndx = dx / dist
        ndy = dy / dist
        # 距离越近偏移越小（避免鼠标紧贴时抖动）
        intensity = min(1.0, dist / 200.0)
        off_x = ndx * max_off_x * intensity
        off_y = ndy * max_off_y * intensity

        # ---- 虹膜 ----
        iris_w = w * 0.55
        iris_h = cur_h * 0.75
        iris_rect = QRectF(cx + off_x - iris_w / 2.0,
                           cy + off_y - iris_h / 2.0,
                           iris_w, iris_h)
        p.setBrush(QBrush(iris))
        p.drawEllipse(iris_rect)

        # ---- 瞳孔 ----
        if open_ratio > 0.4:
            pupil_w = w * 0.25
            pupil_h = cur_h * 0.45
            pupil_rect = QRectF(cx + off_x - pupil_w / 2.0,
                                cy + off_y - pupil_h / 2.0,
                                pupil_w, pupil_h)
            p.setBrush(QBrush(pupil))
            p.drawEllipse(pupil_rect)

            # 高光小圆点（仅完全睁眼时）
            if open_ratio > 0.7:
                hl_d = w * 0.12
                hl_rect = QRectF(cx + off_x - pupil_w * 0.15,
                                 cy + off_y - pupil_h * 0.45,
                                 hl_d, hl_d)
                p.setBrush(QBrush(QColor(255, 255, 255)))
                p.drawEllipse(hl_rect)

    # ------------------------------------------------------------------ #
    #  绘制嘴巴（两眼中间一道向上弯的弧线，构成微笑）
    # ------------------------------------------------------------------ #

    def _draw_mouth(self, p: QPainter, w: int, h: int,
                    left_cx: float, right_cx: float, color: QColor) -> None:
        """在两眼正中画一道二次贝塞尔微笑弧线。

        眨眼时嘴角会轻微上扬一点点（联动表情），强度 0.0-1.0。
        """
        # 嘴宽：两眼内缘之间距离的 22%（中等宽度，不会撞到眼睛也不会太小）
        # 加上下限保护：最小 14px、最大 32px
        gap = right_cx - left_cx
        mouth_w = gap * 0.22
        mouth_w = max(14.0, min(mouth_w, 32.0))

        # 嘴巴中心 X：两眼正中
        center_x = (left_cx + right_cx) / 2.0

        # 嘴巴垂直位置：略低于条中线（更自然的"微笑脸"比例）
        # 18px 高度下，中线 9，嘴巴端点放在 11-12 之间
        mouth_y = h / 2.0 + 2.5

        # 眨眼时嘴角上扬幅度（眨眼瞬间更"灿烂"）
        smile_boost = 1.0 + self._blink_phase * 0.5

        # 弧线起点/终点 + 控制点（QuadTo 二次贝塞尔）
        x1 = center_x - mouth_w / 2.0
        x2 = center_x + mouth_w / 2.0
        # 控制点 Y 高于起终点 → 弧线向下凸 → 视觉上是"嘴角上翘的微笑"
        # 注意 Qt 坐标系 Y 向下增长，所以"向下凸"的曲线就是微笑
        ctrl_y = mouth_y + 3.0 * smile_boost

        path = QPainterPath()
        path.moveTo(x1, mouth_y)
        path.quadTo(center_x, ctrl_y, x2, mouth_y)

        pen = QPen(color)
        pen.setWidthF(2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
