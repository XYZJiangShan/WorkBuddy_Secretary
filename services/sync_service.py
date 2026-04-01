"""
services/sync_service.py - GitHub 数据同步服务

将 SQLite 数据库文件（desk_secretary.db）同步到用户指定的
GitHub 私有仓库，实现多设备数据共享。

配置项（存储在 settings 表）：
  sync_enabled          "1" / "0"
  sync_github_repo      "https://<token>@github.com/user/repo.git"
  sync_interval_minutes 同步间隔（默认 30）
  sync_last_at          上次同步时间（ISO8601，程序自动写入）

工作流：
  启动时 → pull（若本地 hash 落后则覆盖本地 db）
  定时   → push（每隔 N 分钟 commit+push）
  退出时 → push（保证最新数据上传）
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

logger = logging.getLogger(__name__)

# 同步仓库中 db 文件的相对路径
_REMOTE_DB_PATH = "desk_secretary.db"


class SyncResult:
    """单次同步操作的结果"""
    def __init__(self, success: bool, message: str = "", pulled: bool = False):
        self.success = success
        self.message = message
        self.pulled = pulled   # True = 从远端拉取了新数据


class SyncService(QObject):
    """
    GitHub 同步服务

    信号：
      sync_done(success, message)  每次同步完成后触发
    """

    sync_done = pyqtSignal(bool, str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_timer)
        self._busy = False

    # ------------------------------------------------------------------ #
    #  公共控制
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """根据配置启动定时同步"""
        if not self.is_enabled():
            return
        interval_ms = self._settings.get_int("sync_interval_minutes", 30) * 60 * 1000
        self._timer.start(interval_ms)
        logger.info("SyncService started, interval=%d min", interval_ms // 60000)

    def stop(self) -> None:
        self._timer.stop()

    def reload_settings(self) -> None:
        """设置保存后重新加载（interval 可能改变）"""
        self.stop()
        self.start()

    def is_enabled(self) -> bool:
        return (
            self._settings.get_bool("sync_enabled", False)
            and bool(self._get_repo_url())
        )

    # ------------------------------------------------------------------ #
    #  同步操作
    # ------------------------------------------------------------------ #

    def push_now(self) -> SyncResult:
        """立即将本地 db 推送到 GitHub（commit + push）"""
        if self._busy:
            return SyncResult(False, "上次同步尚未完成，请稍候")
        return self._run_sync(direction="push")

    def pull_on_startup(self) -> SyncResult:
        """启动时从 GitHub 拉取（若远端更新则覆盖本地 db）"""
        if not self.is_enabled():
            return SyncResult(True, "同步未启用")
        return self._run_sync(direction="pull")

    def sync_now(self) -> SyncResult:
        """完整同步：先 pull，再 push"""
        if self._busy:
            return SyncResult(False, "上次同步尚未完成")
        return self._run_sync(direction="both")

    # ------------------------------------------------------------------ #
    #  核心实现
    # ------------------------------------------------------------------ #

    def _run_sync(self, direction: str) -> SyncResult:
        """
        在临时目录 clone 仓库，操作 db 文件，再 push 回去。
        clone 使用 --depth=1 减少流量。
        """
        self._busy = True
        result = SyncResult(False, "未知错误")
        tmp_dir = None

        try:
            repo_url = self._get_repo_url()
            if not repo_url:
                return SyncResult(False, "请先在设置中配置 GitHub 同步仓库地址")

            from data.database import get_db_path, get_app_data_dir
            local_db = Path(get_db_path())

            # 建临时目录并 clone
            tmp_dir = Path(tempfile.mkdtemp(prefix="desksec_sync_"))
            repo_dir = tmp_dir / "repo"

            self._git(["clone", "--depth=1", repo_url, str(repo_dir)])

            remote_db = repo_dir / _REMOTE_DB_PATH

            if direction in ("pull", "both"):
                # 远端有 db 且比本地新（按文件大小/内容粗判断）
                if remote_db.exists():
                    if not local_db.exists() or self._remote_is_newer(remote_db, local_db):
                        # 关闭数据库连接后再覆盖
                        from data.database import close_db, get_conn
                        close_db()
                        shutil.copy2(str(remote_db), str(local_db))
                        get_conn()   # 重新打开
                        result.pulled = True
                        logger.info("DB pulled from GitHub")
                    else:
                        logger.info("Remote DB not newer, skip pull")
                else:
                    logger.info("No remote DB found, skip pull")

            if direction in ("push", "both"):
                if not local_db.exists():
                    return SyncResult(False, "本地数据库文件不存在，无法推送")

                # 复制 db 到仓库目录
                shutil.copy2(str(local_db), str(remote_db))

                # git config（临时）
                self._git(["config", "user.name", "DeskSecretary"], cwd=repo_dir)
                self._git(["config", "user.email", "sync@desksec.local"], cwd=repo_dir)

                # 检查是否有变更
                status = self._git_output(["status", "--porcelain"], cwd=repo_dir).strip()
                if not status:
                    result = SyncResult(True, "数据无变化，无需推送")
                    self._update_last_sync_time()
                    return result

                now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                self._git(["add", _REMOTE_DB_PATH], cwd=repo_dir)
                self._git(["commit", "-m", f"sync: auto backup {now_str}"], cwd=repo_dir)
                self._git(["push"], cwd=repo_dir)
                self._update_last_sync_time()
                logger.info("DB pushed to GitHub")

            msg = ""
            if direction == "pull":
                msg = "已从 GitHub 拉取最新数据" if result.pulled else "本地数据已是最新"
            elif direction == "push":
                msg = "已同步到 GitHub"
            else:
                msg = "同步完成" + ("（已更新本地数据）" if result.pulled else "")

            result = SyncResult(True, msg, result.pulled)

        except subprocess.CalledProcessError as e:
            err = (e.stderr or b"").decode("utf-8", errors="replace").strip()
            result = SyncResult(False, f"Git 操作失败: {err or str(e)}")
            logger.error("sync error: %s", result.message)
        except Exception as e:
            result = SyncResult(False, f"同步异常: {e}")
            logger.error("sync error: %s", e)
        finally:
            self._busy = False
            if tmp_dir and tmp_dir.exists():
                try:
                    shutil.rmtree(tmp_dir)
                except Exception:
                    pass

        self.sync_done.emit(result.success, result.message)
        return result

    # ------------------------------------------------------------------ #
    #  辅助工具
    # ------------------------------------------------------------------ #

    def _get_repo_url(self) -> str:
        return self._settings.get("sync_github_repo", "").strip()

    def _update_last_sync_time(self) -> None:
        self._settings.set("sync_last_at", datetime.now().isoformat())

    def get_last_sync_time(self) -> str:
        t = self._settings.get("sync_last_at", "")
        if t:
            try:
                return datetime.fromisoformat(t).strftime("%m-%d %H:%M")
            except Exception:
                pass
        return "从未"

    @staticmethod
    def _remote_is_newer(remote: Path, local: Path) -> bool:
        """简单判断：文件大小不同则认为远端更新（可换成 hash 对比）"""
        return remote.stat().st_size != local.stat().st_size

    @staticmethod
    def _git(args: list, cwd: Optional[Path] = None) -> None:
        subprocess.run(
            ["git"] + args,
            cwd=str(cwd) if cwd else None,
            check=True,
            capture_output=True,
        )

    @staticmethod
    def _git_output(args: list, cwd: Optional[Path] = None) -> str:
        result = subprocess.run(
            ["git"] + args,
            cwd=str(cwd) if cwd else None,
            check=True,
            capture_output=True,
        )
        return result.stdout.decode("utf-8", errors="replace")

    def _on_timer(self) -> None:
        if self.is_enabled():
            logger.info("定时同步触发")
            self._run_sync(direction="push")
