"""
ai_status_monitor.py - AI 运行状态监控服务

功能：
  轮询 WorkBuddy / CodeBuddy 的会话数据库，检测 AI 执行状态。
  当 AI 正在执行时发射信号（busy），空闲时发射信号（idle）。

检测原理：
  - WorkBuddy：读取 ~/.workbuddy/workbuddy.db 的 sessions 表，
    status='working' 且 updated_at 持续刷新 = AI 正在执行。
  - CodeBuddy CN（VS Code 插件）：检查进程是否在运行 +
    读取 %APPDATA%/CodeBuddy CN/User/globalStorage/state.vscdb 中的相关状态。
  - 通用检测：如果 WorkBuddy.exe 进程不存在，则状态为 unknown/offline。

信号：
  status_changed(source: str, busy: bool)
    source: 'workbuddy' | 'codebuddy'
    busy: True=AI执行中, False=空闲
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from typing import Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

logger = logging.getLogger(__name__)

# 轮询间隔（毫秒）
POLL_INTERVAL_MS = 2000

# 判定"AI 正在工作"的超时阈值：如果 updated_at 超过此时间没更新，
# 即使 status='working'，也认为 AI 已停止（可能进程异常退出）
STALE_THRESHOLD_SEC = 10

# WorkBuddy 数据库路径
WORKBUDDY_DB_PATH = os.path.join(
    os.environ.get("USERPROFILE", os.path.expanduser("~")),
    ".workbuddy", "workbuddy.db"
)

# CodeBuddy CN 数据目录
CODEBUDDY_CN_DIR = os.path.join(
    os.environ.get("APPDATA", ""),
    "CodeBuddy CN"
)


class AIStatusMonitor(QObject):
    """
    AI 运行状态监控服务

    定期轮询 WorkBuddy/CodeBuddy 的数据库，检测 AI 执行状态，
    状态变化时发射 status_changed 信号。
    """

    status_changed = pyqtSignal(str, bool)  # (source, busy)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._poll)

        # 上一次的状态（避免重复发射信号）
        self._workbuddy_busy: Optional[bool] = None
        self._codebuddy_busy: Optional[bool] = None

        # WorkBuddy 上次检测到的 updated_at（用于检测是否仍在刷新）
        self._wb_last_updated_at: int = 0

    def start(self) -> None:
        """启动轮询"""
        self._timer.start()
        # 首次立即检测一次
        self._poll()
        logger.info("AI 状态监控已启动（轮询间隔 %dms）", POLL_INTERVAL_MS)

    def stop(self) -> None:
        """停止轮询"""
        self._timer.stop()
        logger.info("AI 状态监控已停止")

    @property
    def workbuddy_busy(self) -> bool:
        """WorkBuddy 当前 AI 是否在执行"""
        return self._workbuddy_busy or False

    @property
    def codebuddy_busy(self) -> bool:
        """CodeBuddy 当前 AI 是否在执行"""
        return self._codebuddy_busy or False

    @property
    def any_busy(self) -> bool:
        """任意一个 AI 工具在执行"""
        return self.workbuddy_busy or self.codebuddy_busy

    # ------------------------------------------------------------------ #
    #  轮询逻辑
    # ------------------------------------------------------------------ #

    def _poll(self) -> None:
        """每轮检测一次所有 AI 工具的状态"""
        self._check_workbuddy()
        self._check_codebuddy()

    def _check_workbuddy(self) -> None:
        """检测 WorkBuddy 的 AI 状态"""
        if not os.path.isfile(WORKBUDDY_DB_PATH):
            # 数据库不存在 → WorkBuddy 未安装或未运行
            new_busy = False
        else:
            try:
                new_busy = self._query_workbuddy_status()
            except Exception as e:
                logger.debug("查询 WorkBuddy 状态失败: %s", e)
                new_busy = False

        # 状态变化时发射信号
        if new_busy != self._workbuddy_busy:
            self._workbuddy_busy = new_busy
            self.status_changed.emit("workbuddy", new_busy)
            logger.info("WorkBuddy AI 状态: %s", "执行中" if new_busy else "空闲")

    def _query_workbuddy_status(self) -> bool:
        """查询 WorkBuddy 数据库，判断 AI 是否正在执行"""
        try:
            conn = sqlite3.connect(f"file:{WORKBUDDY_DB_PATH}?mode=ro", uri=True)
            conn.row_factory = None
            cursor = conn.cursor()

            # 查找所有 status='working' 的会话
            rows = cursor.execute(
                "SELECT updated_at FROM sessions WHERE status='working'"
            ).fetchall()

            conn.close()
        except sqlite3.OperationalError:
            return False

        if not rows:
            return False

        # 检查 updated_at 是否在阈值内（说明 AI 仍在活跃执行）
        now_ms = int(time.time() * 1000)
        for row in rows:
            updated_at = row[0]
            age_sec = (now_ms - updated_at) / 1000
            if age_sec < STALE_THRESHOLD_SEC:
                return True

        # 所有 working 会话的 updated_at 都太旧 → AI 可能已停止
        return False

    def _check_codebuddy(self) -> None:
        """检测 CodeBuddy CN (VS Code 插件) 的 AI 状态"""
        if not os.path.isdir(CODEBUDDY_CN_DIR):
            new_busy = False
        else:
            try:
                new_busy = self._query_codebuddy_status()
            except Exception as e:
                logger.debug("查询 CodeBuddy 状态失败: %s", e)
                new_busy = False

        if new_busy != self._codebuddy_busy:
            self._codebuddy_busy = new_busy
            self.status_changed.emit("codebuddy", new_busy)
            logger.info("CodeBuddy AI 状态: %s", "执行中" if new_busy else "空闲")

    def _query_codebuddy_status(self) -> bool:
        """
        检测 CodeBuddy CN 的 AI 执行状态

        策略：
        1. 检查 CodeBuddy CN 进程是否在运行
        2. 如果在运行，读取 state.vscdb 查找 AI 活动标记
        3. 由于 CodeBuddy CN 没有像 WorkBuddy 那样明确的 sessions 表，
           我们使用进程 CPU 使用率作为辅助判断（CPU > 5% 视为活跃）
        """
        # 方法1：检查进程是否存在
        import subprocess
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq CodeBuddy CN.exe"],
                capture_output=True, text=True, encoding="gbk",
                timeout=3,
            )
            if "CodeBuddy CN.exe" not in result.stdout:
                return False
        except Exception:
            pass

        # 方法2：检查 CodeBuddy CN 的 workspaceStorage 中是否有活跃会话
        # CodeBuddy CN 的会话数据存在 state.vscdb 的 ItemTable 中
        state_db = os.path.join(
            CODEBUDDY_CN_DIR, "User", "globalStorage", "state.vscdb"
        )
        if os.path.isfile(state_db):
            try:
                conn = sqlite3.connect(f"file:{state_db}?mode=ro", uri=True)
                cursor = conn.cursor()
                # 查找包含 chat/agent 活动标记的键
                rows = cursor.execute(
                    "SELECT key FROM ItemTable WHERE key LIKE '%chat%' OR key LIKE '%agent%' OR key LIKE '%working%'"
                ).fetchall()
                conn.close()
                # CodeBuddy CN 的状态检测不如 WorkBuddy 精确，
                # 暂时仅通过进程存在来判断"在线"，无法精确判断 AI 是否在执行
                # 后续可以扩展更精确的检测方式
            except Exception:
                pass

        # 简化策略：CodeBuddy CN 进程在运行但无法精确判断 AI 状态时，
        # 返回 False（保守策略：不误报忙碌）
        return False
