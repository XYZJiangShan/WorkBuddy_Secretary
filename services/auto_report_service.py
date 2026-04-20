"""
auto_report_service.py - 定时自动生成日报/周报服务

功能：
  - 每日指定时刻（默认 22:00）自动生成当天日报并保存到 reports 表
  - 每周日 22:00 自动生成周报并保存
  - 使用 QTimer 驱动，每分钟检查一次是否到点
  - 生成过程在 AIWorker 子线程中执行，不阻塞 UI
"""

from __future__ import annotations

import logging
from datetime import datetime, date, timedelta

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from data.report_repository import ReportRepository, Report
from data.task_repository import TaskRepository
from data.settings_repository import SettingsRepository
from services.ai_service import AIService
from services.ai_worker import AIWorker

logger = logging.getLogger(__name__)


class AutoReportService(QObject):
    """定时自动生成日报/周报"""

    # 生成完成后发信号，UI 可选择弹通知
    daily_report_generated = pyqtSignal(str)   # 日报日期
    weekly_report_generated = pyqtSignal(str)  # 周报日期范围

    def __init__(
        self,
        ai_service: AIService,
        task_repo: TaskRepository,
        settings: SettingsRepository,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._ai = ai_service
        self._task_repo = task_repo
        self._settings = settings
        self._report_repo = ReportRepository()
        self._worker: AIWorker | None = None

        # 每分钟检查一次
        self._timer = QTimer(self)
        self._timer.setInterval(60_000)  # 60 秒
        self._timer.timeout.connect(self._check_schedule)

        # 记录今天是否已生成（避免重复触发）
        self._daily_done_today: str = ""
        self._weekly_done_this_week: str = ""

    def start(self) -> None:
        """启动定时检查"""
        if not self._timer.isActive():
            self._timer.start()
            logger.info("AutoReportService 已启动（每分钟检查）")

    def stop(self) -> None:
        self._timer.stop()

    @property
    def auto_daily_hour(self) -> int:
        """自动日报触发时刻（小时），默认 22 点"""
        return self._settings.get_int("auto_report_daily_hour", 22)

    def _check_schedule(self) -> None:
        """每分钟调用，检查是否需要生成日报/周报"""
        now = datetime.now()
        today_str = date.today().isoformat()
        trigger_hour = self.auto_daily_hour

        # 已有 worker 在跑就跳过
        if self._worker and self._worker.isRunning():
            return

        # ---- 日报检查 ----
        if (
            now.hour == trigger_hour
            and now.minute < 2  # 前 2 分钟内触发
            and self._daily_done_today != today_str
            and self._settings.get_bool("auto_report_daily_enabled", True)
        ):
            # 检查是否已有今天的日报
            existing = self._report_repo.get_report("daily", today_str)
            if not existing:
                logger.info("AutoReport: 开始生成今日日报 (%s)", today_str)
                self._generate_daily(today_str)
                return

            self._daily_done_today = today_str

        # ---- 周报检查（每周日） ----
        if (
            now.weekday() == 6  # 周日
            and now.hour == trigger_hour
            and now.minute < 2
            and self._settings.get_bool("auto_report_weekly_enabled", True)
        ):
            end_d = date.today()
            start_d = end_d - timedelta(days=6)
            week_key = f"{start_d.isoformat()}~{end_d.isoformat()}"
            if self._weekly_done_this_week != week_key:
                existing = self._report_repo.get_report("weekly", week_key)
                if not existing:
                    logger.info("AutoReport: 开始生成本周周报 (%s)", week_key)
                    self._generate_weekly(end_d, week_key)
                    return
                self._weekly_done_this_week = week_key

    # ------------------------------------------------------------------ #
    #  生成日报
    # ------------------------------------------------------------------ #

    def _generate_daily(self, today_str: str) -> None:
        done_tasks = [
            {"title": t.title, "priority": t.priority, "done_at": t.done_at}
            for t in self._task_repo.get_today_done()
        ]
        undone_tasks = [
            {"title": t.title, "priority": t.priority, "due_time": t.due_time}
            for t in self._task_repo.get_today(include_done=False)
        ]

        if not done_tasks and not undone_tasks:
            logger.info("AutoReport: 今日无任务，跳过日报生成")
            self._daily_done_today = today_str
            return

        worker = AIWorker(self._ai, parent=self)
        worker.generate_daily_review(done_tasks, undone_tasks)
        worker.result_ready.connect(
            lambda tt, result: self._on_daily_ready(tt, result, today_str)
        )
        worker.error_occurred.connect(
            lambda tt, err: self._on_daily_error(tt, err, today_str)
        )
        worker.start()
        self._worker = worker

    def _on_daily_ready(self, task_type: str, result: object, today_str: str) -> None:
        if task_type != "daily_review":
            return
        text: str = result  # type: ignore
        self._report_repo.save_report(Report(
            report_type="daily",
            report_date=today_str,
            content=text,
            auto_generated=True,
        ))
        self._daily_done_today = today_str
        self._worker = None
        logger.info("AutoReport: 今日日报已自动生成并保存")
        self.daily_report_generated.emit(today_str)

    def _on_daily_error(self, task_type: str, err: str, today_str: str) -> None:
        if task_type != "daily_review":
            return
        logger.warning("AutoReport: 日报生成失败: %s", err)
        # 失败也标记为已尝试，避免反复重试
        self._daily_done_today = today_str
        self._worker = None

    # ------------------------------------------------------------------ #
    #  生成周报
    # ------------------------------------------------------------------ #

    def _generate_weekly(self, end_date: date, week_key: str) -> None:
        week_summary = self._task_repo.get_week_summary(end_date)
        if week_summary["total"] == 0:
            logger.info("AutoReport: 本周无任务，跳过周报生成")
            self._weekly_done_this_week = week_key
            return

        worker = AIWorker(self._ai, parent=self)
        worker.generate_weekly_report(week_summary)
        worker.result_ready.connect(
            lambda tt, result: self._on_weekly_ready(tt, result, week_key)
        )
        worker.error_occurred.connect(
            lambda tt, err: self._on_weekly_error(tt, err, week_key)
        )
        worker.start()
        self._worker = worker

    def _on_weekly_ready(self, task_type: str, result: object, week_key: str) -> None:
        if task_type != "weekly_report":
            return
        text: str = result  # type: ignore
        self._report_repo.save_report(Report(
            report_type="weekly",
            report_date=week_key,
            content=text,
            auto_generated=True,
        ))
        self._weekly_done_this_week = week_key
        self._worker = None
        logger.info("AutoReport: 本周周报已自动生成并保存")
        self.weekly_report_generated.emit(week_key)

    def _on_weekly_error(self, task_type: str, err: str, week_key: str) -> None:
        if task_type != "weekly_report":
            return
        logger.warning("AutoReport: 周报生成失败: %s", err)
        self._weekly_done_this_week = week_key
        self._worker = None
