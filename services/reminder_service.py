"""
reminder_service.py - 定时休息提醒服务

职责：
  1. 维护一个 QTimer 驱动的倒计时，到期后触发 reminder_triggered 信号
  2. 管理"提醒文案缓存池"，用 AIWorker 异步预拉取，保证即时弹出不等待网络
  3. 将每次触发的提醒写入 reminder_history 表（供复盘统计）
  4. 向上层 UI 暴露清晰的 pyqtSignal，UI 层无需知道定时器细节

信号一览：
  reminder_triggered(text: str)
      到了休息时间，携带本次提醒文案
  countdown_tick(seconds_left: int)
      每秒触发一次，用于 UI 倒计时进度条
  cache_refreshing()
      缓存池补充开始（可用于 UI 显示"正在为你准备下一条文案…"）
  settings_changed()
      提醒间隔或开关状态发生变化

使用方式：
    service = ReminderService(ai_service, settings_repo)
    service.reminder_triggered.connect(show_banner)
    service.countdown_tick.connect(update_progress_bar)
    service.start()
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from data.database import get_conn
from data.settings_repository import SettingsRepository
from services.ai_service import AIService, FALLBACK_REMINDER_TEXTS
from services.ai_worker import AIWorker

logger = logging.getLogger(__name__)


class ReminderService(QObject):
    """
    定时休息提醒服务（QObject 子类，运行在 Qt 主线程）

    内部有两个 QTimer：
      _countdown_timer  - 每秒 tick，驱动倒计时 UI
      _remind_timer     - 单次触发，到期后执行"提醒"动作
    """

    # ------------------------------------------------------------------ #
    #  对外信号
    # ------------------------------------------------------------------ #
    reminder_triggered = pyqtSignal(str)   # 到时间了，携带提醒文案
    countdown_tick = pyqtSignal(int)       # 剩余秒数（每秒一次）
    cache_refreshing = pyqtSignal()        # 缓存池开始补充
    settings_changed = pyqtSignal()        # 配置（间隔/开关）已变更

    def __init__(
        self,
        ai_service: AIService,
        settings: Optional[SettingsRepository] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._ai = ai_service
        self._settings = settings or SettingsRepository()

        # ---- 文案缓存池 ----
        self._text_cache: list[str] = []
        self._cache_worker: Optional[AIWorker] = None  # 保持引用防止 GC

        # ---- 倒计时状态 ----
        self._total_seconds: int = 0    # 本轮总秒数
        self._seconds_left: int = 0     # 剩余秒数
        self._running: bool = False

        # ---- 定时器 ----
        self._remind_timer = QTimer(self)
        self._remind_timer.setSingleShot(True)
        self._remind_timer.timeout.connect(self._on_remind_timeout)

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)  # 1 秒
        self._tick_timer.timeout.connect(self._on_tick)

    # ------------------------------------------------------------------ #
    #  公共 API
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """启动提醒服务：读取配置、初始化缓存池、启动定时器"""
        if not self._settings.get_bool("reminder_enabled", True):
            logger.info("ReminderService: 提醒已关闭，跳过启动")
            return

        interval_min = self._settings.get_int("reminder_interval_minutes", 45)
        self._reset_countdown(interval_min * 60)

        # 预拉取文案：延迟 3 秒启动，等 Qt 事件循环稳定后再开子线程
        # 立即启动会与 UI 初始化并发，在 Windows 下触发 COM 冲突（0x8001010d）
        QTimer.singleShot(3000, self._refill_cache_async)
        logger.info("ReminderService 已启动，间隔 %d 分钟", interval_min)

    def stop(self) -> None:
        """停止所有定时器"""
        self._remind_timer.stop()
        self._tick_timer.stop()
        self._running = False
        logger.info("ReminderService 已停止")

    def pause(self) -> None:
        """暂停倒计时（不重置剩余时间）"""
        if self._running:
            self._remind_timer.stop()
            self._tick_timer.stop()
            self._running = False
            logger.debug("ReminderService 已暂停，剩余 %d 秒", self._seconds_left)

    def resume(self) -> None:
        """从暂停中恢复"""
        if not self._running and self._seconds_left > 0:
            self._remind_timer.start(self._seconds_left * 1000)
            self._tick_timer.start()
            self._running = True
            logger.debug("ReminderService 已恢复，剩余 %d 秒", self._seconds_left)

    def skip_and_reset(self) -> None:
        """跳过当前轮次，立即重新开始新的倒计时"""
        interval_min = self._settings.get_int("reminder_interval_minutes", 45)
        self._reset_countdown(interval_min * 60)
        logger.debug("ReminderService 已重置")

    def snooze(self, extra_seconds: int = 300) -> None:
        """推迟提醒（默认再等 5 分钟）"""
        self._reset_countdown(extra_seconds)
        logger.debug("ReminderService 已推迟 %d 秒", extra_seconds)

    def reload_settings(self) -> None:
        """配置更新后调用，重新读取间隔并重启定时器"""
        enabled = self._settings.get_bool("reminder_enabled", True)
        if not enabled:
            self.stop()
        else:
            interval_min = self._settings.get_int("reminder_interval_minutes", 45)
            self._reset_countdown(interval_min * 60)
        self.settings_changed.emit()
        logger.info("ReminderService 配置已重载")

    @property
    def seconds_left(self) -> int:
        return self._seconds_left

    @property
    def total_seconds(self) -> int:
        return self._total_seconds

    @property
    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------ #
    #  内部：定时器回调
    # ------------------------------------------------------------------ #

    def _on_remind_timeout(self) -> None:
        """提醒时间到：弹出文案、记录历史、开始下一轮"""
        text = self._pop_text()
        logger.info("ReminderService 触发提醒: %s", text[:20])

        # 写入历史
        self._save_history(text)

        # 通知 UI
        self.reminder_triggered.emit(text)

        # 开始下一轮倒计时
        interval_min = self._settings.get_int("reminder_interval_minutes", 45)
        self._reset_countdown(interval_min * 60)

        # 如果缓存快用完了，异步补充
        if len(self._text_cache) < 2:
            self._refill_cache_async()

    def _on_tick(self) -> None:
        """每秒触发：更新剩余秒数"""
        if self._seconds_left > 0:
            self._seconds_left -= 1
            self.countdown_tick.emit(self._seconds_left)
        else:
            self._tick_timer.stop()

    # ------------------------------------------------------------------ #
    #  内部：倒计时管理
    # ------------------------------------------------------------------ #

    def _reset_countdown(self, total_seconds: int) -> None:
        """重置并启动倒计时"""
        self._remind_timer.stop()
        self._tick_timer.stop()

        # 最小间隔保护：不能小于 60 秒，防止配置异常导致无限触发
        if total_seconds < 60:
            total_seconds = 60
            logger.warning("提醒间隔过短，已自动修正为 60 秒")

        self._total_seconds = total_seconds
        self._seconds_left = total_seconds
        self._running = True

        self._remind_timer.start(total_seconds * 1000)
        self._tick_timer.start()
        # 立即发射一次让 UI 同步
        self.countdown_tick.emit(self._seconds_left)

    # ------------------------------------------------------------------ #
    #  内部：文案缓存池
    # ------------------------------------------------------------------ #

    def _pop_text(self) -> str:
        """从缓存池取出一条文案，池空时用本地备用"""
        if self._text_cache:
            return self._text_cache.pop(0)
        import random
        fallback = FALLBACK_REMINDER_TEXTS.copy()
        random.shuffle(fallback)
        return fallback[0]

    def _refill_cache_async(self) -> None:
        """异步向 AI 请求新一批提醒文案，填充缓存池"""
        if self._cache_worker and self._cache_worker.isRunning():
            logger.debug("缓存补充 Worker 仍在运行，跳过重复请求")
            return

        count = self._settings.get_int("reminder_cache_size", 5)
        self.cache_refreshing.emit()

        worker = AIWorker(self._ai, parent=self)
        worker.generate_reminder_texts(count=count)
        worker.result_ready.connect(self._on_cache_ready)
        worker.error_occurred.connect(self._on_cache_error)
        worker.start()

        self._cache_worker = worker  # 保持引用
        logger.debug("缓存补充 Worker 已启动，请求 %d 条", count)

    def _on_cache_ready(self, task_type: str, result: object) -> None:
        """AI 返回新文案后填入缓存池"""
        if task_type != "reminder_texts":
            return
        texts: list[str] = result  # type: ignore[assignment]
        self._text_cache.extend(texts)
        logger.info("文案缓存池已补充 %d 条，当前 %d 条", len(texts), len(self._text_cache))

    def _on_cache_error(self, task_type: str, error_msg: str) -> None:
        """AI 获取文案失败，缓存池保持现有内容（下次提醒使用本地降级）"""
        if task_type != "reminder_texts":
            return
        logger.warning("缓存补充失败: %s，将使用本地备用文案", error_msg)

    # ------------------------------------------------------------------ #
    #  内部：历史记录
    # ------------------------------------------------------------------ #

    def _save_history(self, text: str) -> None:
        """将本次提醒写入 reminder_history 表"""
        try:
            conn: sqlite3.Connection = get_conn()
            now = datetime.now().isoformat(sep=" ", timespec="seconds")
            conn.execute(
                "INSERT INTO reminder_history (triggered_at, text) VALUES (?, ?)",
                (now, text),
            )
            conn.commit()
        except Exception as e:
            logger.error("保存提醒历史失败: %s", e)

    def get_today_history(self) -> list[dict]:
        """查询今日提醒历史（供复盘统计）"""
        from datetime import date
        today_str = date.today().isoformat()
        try:
            conn = get_conn()
            rows = conn.execute(
                "SELECT triggered_at, text FROM reminder_history "
                "WHERE triggered_at LIKE ? ORDER BY triggered_at DESC",
                (f"{today_str}%",),
            ).fetchall()
            return [{"triggered_at": r[0], "text": r[1]} for r in rows]
        except Exception as e:
            logger.error("查询提醒历史失败: %s", e)
            return []
