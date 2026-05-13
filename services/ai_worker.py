"""
ai_worker.py - AI 异步工作线程

将 AIService 的同步阻塞调用包装进 QThread，避免 AI 网络请求卡住 Qt UI 主线程。

支持任务类型（task_type）：
  - "parse_task"          : 自然语言 → 结构化任务
  - "reminder_texts"      : 批量生成提醒文案
  - "daily_review"        : 今日复盘报告（v2：含笔记+图片描述）
  - "weekly_report"       : 周报整理（v2）
  - "describe_images"     : 批量图片识别

使用方式（主线程中）：
    worker = AIWorker(ai_service)
    worker.parse_task("明天下午3点开会，比较重要")
    worker.result_ready.connect(on_result)
    worker.error_occurred.connect(on_error)
    worker.start()
"""

from __future__ import annotations

import logging
from typing import Optional, Any

from PyQt6.QtCore import QThread, pyqtSignal

from services.ai_service import AIService

logger = logging.getLogger(__name__)


class AIWorker(QThread):
    """
    通用 AI 异步工作线程。

    Signals:
        result_ready(task_type: str, result: object)
        error_occurred(task_type: str, error_message: str)
        progress_updated(task_type: str, message: str)
    """

    result_ready = pyqtSignal(str, object)
    error_occurred = pyqtSignal(str, str)
    progress_updated = pyqtSignal(str, str)

    def __init__(self, ai_service: AIService, parent=None) -> None:
        super().__init__(parent)
        self._service = ai_service
        self._task_type: str = ""
        self._kwargs: dict = {}

    # ------------------------------------------------------------------ #
    #  公共接口：设置任务后调用 start()
    # ------------------------------------------------------------------ #

    def parse_task(self, user_input: str) -> "AIWorker":
        """配置为"解析自然语言任务"模式"""
        self._task_type = "parse_task"
        self._kwargs = {"user_input": user_input}
        return self

    def generate_reminder_texts(self, count: int = 5) -> "AIWorker":
        """配置为"批量生成提醒文案"模式"""
        self._task_type = "reminder_texts"
        self._kwargs = {"count": count}
        return self

    def generate_daily_review(
        self, done_tasks: list[dict], undone_tasks: list[dict]
    ) -> "AIWorker":
        """配置为"今日复盘"模式（v2：任务可带笔记和图片路径，子线程自动识别）"""
        self._task_type = "daily_review"
        self._kwargs = {"done_tasks": done_tasks, "undone_tasks": undone_tasks}
        return self

    def generate_weekly_report(self, week_summary: dict) -> "AIWorker":
        """配置为"周报整理"模式"""
        self._task_type = "weekly_report"
        self._kwargs = {"week_summary": week_summary}
        return self

    # ------------------------------------------------------------------ #
    #  QThread 入口
    # ------------------------------------------------------------------ #

    def run(self) -> None:
        """在子线程中执行 AI 调用，结果通过 Signal 回传主线程"""
        task_type = self._task_type
        if not task_type:
            logger.error("AIWorker.run() 被调用但未设置任务类型")
            return

        self.progress_updated.emit(task_type, "AI 正在思考中...")

        try:
            result: Any
            if task_type == "parse_task":
                result = self._service.parse_task(**self._kwargs)

            elif task_type == "reminder_texts":
                result = self._service.generate_reminder_texts(**self._kwargs)

            elif task_type == "daily_review":
                # v2：先在子线程批量识别图片，再生成日报
                done_tasks = self._kwargs.get("done_tasks", [])
                undone_tasks = self._kwargs.get("undone_tasks", [])
                self.progress_updated.emit(task_type, "正在识别图片...")
                self._enrich_tasks_with_vision(done_tasks)
                self._enrich_tasks_with_vision(undone_tasks)
                self.progress_updated.emit(task_type, "正在生成日报...")
                result = self._service.generate_daily_review(done_tasks, undone_tasks)

            elif task_type == "weekly_report":
                result = self._service.generate_weekly_report(**self._kwargs)

            else:
                raise ValueError(f"未知的 AI 任务类型: {task_type!r}")

            self.result_ready.emit(task_type, result)
            logger.debug("AIWorker 完成: task_type=%s", task_type)

        except Exception as e:
            error_msg = str(e)
            logger.error("AIWorker 失败: task_type=%s, error=%s", task_type, error_msg)
            self.error_occurred.emit(task_type, error_msg)

    # ------------------------------------------------------------------ #
    #  内部：图片识别（在子线程运行）
    # ------------------------------------------------------------------ #

    def _enrich_tasks_with_vision(self, tasks: list[dict]) -> None:
        """
        遍历任务列表，对含 image_paths 的任务调用 Vision 识别，
        将描述填入 image_descriptions 字段。
        """
        for t in tasks:
            image_paths = t.get("image_paths", [])
            if image_paths:
                descriptions = self._service.describe_images_batch(image_paths)
                t["image_descriptions"] = descriptions


# --------------------------------------------------------------------------- #
#  便捷工厂函数：一次性快速创建并连接 Worker
# --------------------------------------------------------------------------- #

def run_ai_task(
    service: AIService,
    task_type: str,
    on_result,
    on_error=None,
    parent=None,
    **kwargs,
) -> AIWorker:
    """
    工厂函数：创建 AIWorker、连接信号、启动线程。
    """
    worker = AIWorker(service, parent=parent)

    if task_type == "parse_task":
        worker.parse_task(kwargs["user_input"])
    elif task_type == "reminder_texts":
        worker.generate_reminder_texts(kwargs.get("count", 5))
    elif task_type == "daily_review":
        worker.generate_daily_review(
            kwargs.get("done_tasks", []),
            kwargs.get("undone_tasks", []),
        )
    elif task_type == "weekly_report":
        worker.generate_weekly_report(kwargs.get("week_summary", {}))

    worker.result_ready.connect(on_result)
    if on_error:
        worker.error_occurred.connect(on_error)

    worker.start()
    return worker
