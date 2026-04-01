"""
database.py - SQLite 数据库初始化与连接管理

- 提供单例数据库连接
- 负责建表（tasks、settings）
- 数据库文件存储在 %APPDATA%/DeskSecretary/ 目录，升级不覆盖数据
"""

import sqlite3
import os
import sys
from pathlib import Path


def get_app_data_dir() -> Path:
    """获取应用数据目录（%APPDATA%/DeskSecretary/），不存在时自动创建"""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path.home() / ".config"
    app_dir = base / "DeskSecretary"
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def get_db_path() -> str:
    """返回 SQLite 数据库文件路径"""
    return str(get_app_data_dir() / "desk_secretary.db")


class Database:
    """SQLite 数据库单例，线程内复用同一连接"""

    _instance: "Database | None" = None
    _conn: sqlite3.Connection | None = None

    def __new__(cls) -> "Database":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def get_connection(self) -> sqlite3.Connection:
        """获取（或初始化）数据库连接，并确保表结构已创建"""
        if self._conn is None:
            db_path = get_db_path()
            self._conn = sqlite3.connect(db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row  # 允许按列名访问
            self._conn.execute("PRAGMA journal_mode=WAL")  # 提升并发写入安全性
            self._create_tables()
        return self._conn

    def _create_tables(self) -> None:
        """创建所有必要的表（若已存在则忽略）"""
        conn = self._conn
        assert conn is not None

        conn.executescript(
            """
            -- 待办任务表
            CREATE TABLE IF NOT EXISTS tasks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT    NOT NULL,
                priority    TEXT    NOT NULL DEFAULT 'medium',  -- 'high' | 'medium' | 'low'
                due_time    TEXT,           -- ISO8601 格式字符串，可为 NULL
                done        INTEGER NOT NULL DEFAULT 0,         -- 0=未完成, 1=已完成
                created_at  TEXT    NOT NULL,                   -- ISO8601 创建时间
                done_at     TEXT                               -- ISO8601 完成时间，可为 NULL
            );

            -- 应用配置表（key-value 结构）
            CREATE TABLE IF NOT EXISTS settings (
                key         TEXT PRIMARY KEY,
                value       TEXT NOT NULL
            );

            -- 休息提醒历史（用于复盘统计）
            CREATE TABLE IF NOT EXISTS reminder_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                triggered_at TEXT NOT NULL,    -- ISO8601 触发时间
                text        TEXT NOT NULL       -- 提醒文案
            );

            -- 任务附件/笔记（与 tasks 一对多）
            CREATE TABLE IF NOT EXISTS task_notes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id     INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                note_type   TEXT    NOT NULL DEFAULT 'text',  -- 'text' | 'image' | 'video'
                content     TEXT,            -- 文字内容（text 类型）或文件路径（image/video）
                file_name   TEXT,            -- 原始文件名（image/video）
                file_size   INTEGER,         -- 字节数（image/video）
                created_at  TEXT    NOT NULL
            );
            """
        )
        conn.commit()

    def close(self) -> None:
        """关闭数据库连接（程序退出时调用）"""
        if self._conn is not None:
            self._conn.close()
            self._conn = None


# 全局单例快捷访问
_db = Database()


def get_conn() -> sqlite3.Connection:
    """全局快捷函数：获取数据库连接"""
    return _db.get_connection()


def close_db() -> None:
    """全局快捷函数：关闭数据库"""
    _db.close()
