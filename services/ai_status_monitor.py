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

# CodeBuddy CN 插件日志的 glob 匹配模式（logs/<时间戳>/<窗口>/exthost/Tencent-Cloud.coding-copilot/*.log）
CODEBUDDY_LOG_GLOB = os.path.join(
    CODEBUDDY_CN_DIR, "logs", "*", "*", "exthost",
    "Tencent-Cloud.coding-copilot", "*.log"
)

# CodeBuddy CN AI 请求检测：
#   插件日志会记录每个 HTTP 请求的 start/end，并带 Trace ID。
#   AI 对话/执行时会发起一个长时间的流式请求（只有 start 迟迟没 end）。
#   通过追踪"未配对的 start"判断 AI 是否在执行。
# 需要排除的后台噪音端点（这些是插件自身的轮询/上报，不代表 AI 在工作）
CODEBUDDY_NOISE_ENDPOINTS = (
    "/v3/config",
    "/v2/report",
    "/v2/market-mcp-server/servers",
    "/api/memory/profile",
    "/console/enterprises",
    "/v2/enterprises",
    "/v2/activity/banner",
    "/v2/billing",
    "/v2/plugin/auth",
    "/v2/login",
    "/v2/account",
    "/v2/quota",
    "/v2/usage",
    "telemetry",
    "/heartbeat",
)

# 未配对 start 超过此时长（秒）仍未 end，视为"陈旧请求"（可能是异常中断），不再算作忙碌
CODEBUDDY_PENDING_STALE_SEC = 180


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

        # ---- CodeBuddy 日志增量监控状态 ----
        # 当前正在追踪的日志文件路径
        self._cb_log_path: Optional[str] = None
        # 上次读取到的文件偏移量（增量读取）
        self._cb_log_offset: int = 0
        # 未配对的 HTTP 请求：{trace_id: 首次出现的时间戳(秒)}
        self._cb_pending: dict[str, float] = {}

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
        检测 CodeBuddy CN 的 AI 执行状态（基于插件日志增量监控）

        原理：
          CodeBuddy CN 插件日志（Tencent-Cloud.coding-copilot/*.log）会记录
          每个 HTTP 请求的开始和结束，格式如下：
            [HTTP STATUS] start POST /xxx | Trace: <id>
            [HTTP STATUS] end POST /xxx | Status: 200 | Trace: <id> | Request: <rid>
          当 AI 正在对话/执行（流式生成）时，会有一个长时间"只有 start 没有 end"
          的请求。通过追踪未配对的 Trace ID 判断 AI 是否在执行。

        策略：
          1. 找到最新的插件日志文件
          2. 增量读取新追加的内容（记录文件偏移量）
          3. 解析每行的 start/end，维护未配对请求集合 _cb_pending
          4. 过滤掉后台噪音端点（config/report/mcp 等轮询请求）
          5. 存在有效未配对请求 → AI 执行中
        """
        # 1) 找最新日志文件
        log_path = self._find_latest_codebuddy_log()
        if not log_path:
            # 没有日志 → 插件未运行
            self._cb_pending.clear()
            return False

        # 2) 日志文件切换（新会话）→ 重置偏移量和未配对集合
        if log_path != self._cb_log_path:
            self._cb_log_path = log_path
            self._cb_log_offset = 0
            self._cb_pending.clear()

        # 3) 增量读取新内容
        try:
            file_size = os.path.getsize(log_path)
            # 文件被截断（日志轮转）→ 从头读
            if file_size < self._cb_log_offset:
                self._cb_log_offset = 0
                self._cb_pending.clear()

            if file_size > self._cb_log_offset:
                with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                    f.seek(self._cb_log_offset)
                    new_lines = f.readlines()
                    self._cb_log_offset = f.tell()
                self._parse_codebuddy_lines(new_lines)
        except Exception as e:
            logger.debug("读取 CodeBuddy 日志失败: %s", e)
            return False

        # 4) 清理陈旧的未配对请求（超时未结束，可能异常中断）
        now = time.time()
        stale = [
            tid for tid, ts in self._cb_pending.items()
            if now - ts > CODEBUDDY_PENDING_STALE_SEC
        ]
        for tid in stale:
            self._cb_pending.pop(tid, None)

        # 5) 还有有效未配对请求 = AI 执行中
        return len(self._cb_pending) > 0

    def _find_latest_codebuddy_log(self) -> Optional[str]:
        """找到最新修改的 CodeBuddy CN 插件日志文件"""
        import glob
        candidates = glob.glob(CODEBUDDY_LOG_GLOB)
        if not candidates:
            return None
        # 只关注最近 5 分钟内有更新的日志（避免追踪已退出会话的旧日志）
        now = time.time()
        active = [c for c in candidates if now - os.path.getmtime(c) < 300]
        pool = active if active else candidates
        return max(pool, key=os.path.getmtime)

    def _parse_codebuddy_lines(self, lines: list[str]) -> None:
        """
        解析日志行，维护未配对的 HTTP 请求集合。

        - 遇到 'start ... Trace: X' → 记录 X（若非噪音端点）
        - 遇到 'end ... Trace: X'   → 移除 X
        """
        now = time.time()
        for line in lines:
            if "[HTTP STATUS]" not in line:
                continue

            # 提取 Trace ID
            trace_idx = line.find("Trace:")
            if trace_idx < 0:
                continue
            trace_id = line[trace_idx + 6:].split("|")[0].strip()
            if not trace_id:
                continue

            if " start " in line:
                # 噪音端点不计入
                if any(noise in line for noise in CODEBUDDY_NOISE_ENDPOINTS):
                    continue
                self._cb_pending[trace_id] = now
            elif " end " in line:
                # 请求结束 → 配对移除
                self._cb_pending.pop(trace_id, None)
