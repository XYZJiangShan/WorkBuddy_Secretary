"""
pomodoro_service.py - 番茄钟专注服务

实现标准番茄工作法：
  - 专注阶段（默认 25 分钟）
  - 短休息（默认 5 分钟）
  - 每 4 个番茄后长休息（默认 15 分钟）

专注期间暂停休息提醒，短休息时恢复。
通过 pyqtSignal 驱动 UI 状态更新。
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

logger = logging.getLogger(__name__)


class PomodoroState(Enum):
    IDLE = "idle"
    FOCUS = "focus"
    SHORT_BREAK = "short_break"
    LONG_BREAK = "long_break"


# 每轮结束后的提示音（Unicode 字符提示，实际播放用 winsound）
_STATE_LABELS = {
    PomodoroState.IDLE: "准备开始",
    PomodoroState.FOCUS: "专注中 🍅",
    PomodoroState.SHORT_BREAK: "短暂休息 ☕",
    PomodoroState.LONG_BREAK: "长休息 🌿",
}


class PomodoroService(QObject):
    """
    番茄钟服务

    Signals:
        state_changed(state: str, label: str)
            状态切换时触发，state 为 PomodoroState.value，label 为中文描述
        tick(seconds_left: int, total: int)
            每秒触发，携带剩余秒数和本阶段总秒数
        phase_completed(state: str, count: int)
            一个阶段完成时触发，count 为累计完成的专注番茄数
        reminder_pause_requested()
            专注开始时通知外部暂停休息提醒
        reminder_resume_requested()
            休息阶段通知外部恢复休息提醒
    """

    state_changed = pyqtSignal(str, str)        # (state_value, label)
    tick = pyqtSignal(int, int)                  # (seconds_left, total)
    phase_completed = pyqtSignal(str, int)       # (state_value, tomato_count)
    reminder_pause_requested = pyqtSignal()
    reminder_resume_requested = pyqtSignal()

    # 默认时长（秒）
    DEFAULT_FOCUS_SEC = 25 * 60
    DEFAULT_SHORT_BREAK_SEC = 5 * 60
    DEFAULT_LONG_BREAK_SEC = 15 * 60
    LONG_BREAK_EVERY = 4  # 每 N 个番茄后长休息

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._state = PomodoroState.IDLE
        self._tomato_count = 0          # 累计完成番茄数
        self._seconds_left = 0
        self._total_seconds = 0
        self._running = False

        # 可配置时长
        self.focus_seconds = self.DEFAULT_FOCUS_SEC
        self.short_break_seconds = self.DEFAULT_SHORT_BREAK_SEC
        self.long_break_seconds = self.DEFAULT_LONG_BREAK_SEC

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._on_tick)

    # ------------------------------------------------------------------ #
    #  公共 API
    # ------------------------------------------------------------------ #

    @property
    def state(self) -> PomodoroState:
        return self._state

    @property
    def tomato_count(self) -> int:
        return self._tomato_count

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def seconds_left(self) -> int:
        return self._seconds_left

    @property
    def total_seconds(self) -> int:
        return self._total_seconds

    def start_focus(self) -> None:
        """开始一个专注阶段"""
        self._switch_state(PomodoroState.FOCUS, self.focus_seconds)
        self.reminder_pause_requested.emit()   # 专注期间暂停休息提醒
        logger.info("番茄钟：开始专注，%d 分钟", self.focus_seconds // 60)

    def start_break(self, force_long: bool = False) -> None:
        """开始休息阶段（自动判断短/长）"""
        if force_long or (self._tomato_count > 0 and self._tomato_count % self.LONG_BREAK_EVERY == 0):
            self._switch_state(PomodoroState.LONG_BREAK, self.long_break_seconds)
            logger.info("番茄钟：长休息，%d 分钟", self.long_break_seconds // 60)
        else:
            self._switch_state(PomodoroState.SHORT_BREAK, self.short_break_seconds)
            logger.info("番茄钟：短休息，%d 分钟", self.short_break_seconds // 60)
        self.reminder_resume_requested.emit()  # 休息期间允许提醒

    def pause(self) -> None:
        """暂停当前阶段"""
        if self._running:
            self._timer.stop()
            self._running = False
            logger.debug("番茄钟已暂停，剩余 %d 秒", self._seconds_left)

    def resume(self) -> None:
        """继续暂停的阶段"""
        if not self._running and self._state != PomodoroState.IDLE:
            self._timer.start()
            self._running = True

    def stop(self) -> None:
        """停止并重置"""
        self._timer.stop()
        self._running = False
        self._state = PomodoroState.IDLE
        self._seconds_left = 0
        self._total_seconds = 0
        self.state_changed.emit(PomodoroState.IDLE.value, _STATE_LABELS[PomodoroState.IDLE])
        self.reminder_resume_requested.emit()
        logger.info("番茄钟已停止")

    def reset_count(self) -> None:
        """重置番茄计数"""
        self._tomato_count = 0

    def update_durations(self, focus_min: int, short_min: int, long_min: int) -> None:
        """更新时长配置"""
        self.focus_seconds = focus_min * 60
        self.short_break_seconds = short_min * 60
        self.long_break_seconds = long_min * 60

    # ------------------------------------------------------------------ #
    #  内部
    # ------------------------------------------------------------------ #

    def _switch_state(self, state: PomodoroState, total_seconds: int) -> None:
        self._timer.stop()
        self._state = state
        self._total_seconds = total_seconds
        self._seconds_left = total_seconds
        self._running = True
        self._timer.start()
        self.state_changed.emit(state.value, _STATE_LABELS[state])
        self.tick.emit(self._seconds_left, self._total_seconds)

    def _on_tick(self) -> None:
        if self._seconds_left > 0:
            self._seconds_left -= 1
            self.tick.emit(self._seconds_left, self._total_seconds)
        else:
            self._on_phase_end()

    def _on_phase_end(self) -> None:
        """当前阶段结束"""
        self._timer.stop()
        self._running = False
        ended_state = self._state

        if ended_state == PomodoroState.FOCUS:
            self._tomato_count += 1
            logger.info("番茄钟：专注完成！累计 %d 个番茄🍅", self._tomato_count)

        self.phase_completed.emit(ended_state.value, self._tomato_count)

        # 自动切换到下一阶段
        if ended_state == PomodoroState.FOCUS:
            self.start_break()
        else:
            # 休息结束 → 回到 IDLE，等用户手动开始下一个
            self._state = PomodoroState.IDLE
            self.state_changed.emit(PomodoroState.IDLE.value, "准备下一个 🍅")
            self.reminder_resume_requested.emit()

    def get_state_label(self) -> str:
        return _STATE_LABELS.get(self._state, "")
