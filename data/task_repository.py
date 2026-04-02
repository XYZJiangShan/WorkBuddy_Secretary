"""
task_repository.py - 任务数据访问层

封装所有 tasks 表的 CRUD 操作，对业务层暴露清晰的 Task 数据模型。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional

from data.database import get_conn


# --------------------------------------------------------------------------- #
#  数据模型
# --------------------------------------------------------------------------- #

PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass
class Task:
    title: str
    priority: str = "medium"        # 'high' | 'medium' | 'low'
    due_time: Optional[str] = None  # ISO8601 字符串，如 "2026-03-31 15:00"
    done: bool = False
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(sep=" ", timespec="seconds"))
    done_at: Optional[str] = None
    id: Optional[int] = None

    @property
    def priority_label(self) -> str:
        mapping = {"high": "高", "medium": "中", "low": "低"}
        return mapping.get(self.priority, "中")

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Task":
        return cls(
            id=row["id"],
            title=row["title"],
            priority=row["priority"],
            due_time=row["due_time"],
            done=bool(row["done"]),
            created_at=row["created_at"],
            done_at=row["done_at"],
        )


# --------------------------------------------------------------------------- #
#  Repository
# --------------------------------------------------------------------------- #

class TaskRepository:
    """任务 CRUD 封装，直接操作 SQLite tasks 表"""

    # ------------------------------------------------------------------ #
    #  写操作
    # ------------------------------------------------------------------ #

    def add(self, task: Task) -> Task:
        """插入一条新任务，返回填充了 id 的 Task 对象"""
        conn = get_conn()
        cursor = conn.execute(
            """
            INSERT INTO tasks (title, priority, due_time, done, created_at, done_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                task.title,
                task.priority,
                task.due_time,
                int(task.done),
                task.created_at,
                task.done_at,
            ),
        )
        conn.commit()
        task.id = cursor.lastrowid
        return task

    def mark_done(self, task_id: int) -> bool:
        """将指定任务标记为已完成，返回是否成功（False 表示任务不存在）"""
        conn = get_conn()
        done_at = datetime.now().isoformat(sep=" ", timespec="seconds")
        cursor = conn.execute(
            "UPDATE tasks SET done=1, done_at=? WHERE id=? AND done=0",
            (done_at, task_id),
        )
        conn.commit()
        return cursor.rowcount > 0

    def mark_undone(self, task_id: int) -> bool:
        """将指定任务重新标记为未完成"""
        conn = get_conn()
        cursor = conn.execute(
            "UPDATE tasks SET done=0, done_at=NULL WHERE id=? AND done=1",
            (task_id,),
        )
        conn.commit()
        return cursor.rowcount > 0

    def update(self, task: Task) -> bool:
        """更新任务的标题、优先级、截止时间（id 必须存在）"""
        if task.id is None:
            return False
        conn = get_conn()
        cursor = conn.execute(
            """
            UPDATE tasks
               SET title=?, priority=?, due_time=?
             WHERE id=?
            """,
            (task.title, task.priority, task.due_time, task.id),
        )
        conn.commit()
        return cursor.rowcount > 0

    def delete(self, task_id: int) -> bool:
        """物理删除指定任务"""
        conn = get_conn()
        cursor = conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        conn.commit()
        return cursor.rowcount > 0

    # ------------------------------------------------------------------ #
    #  读操作
    # ------------------------------------------------------------------ #

    def get_by_id(self, task_id: int) -> Optional[Task]:
        """按 id 查询单条任务"""
        conn = get_conn()
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return Task.from_row(row) if row else None

    def get_all(self, include_done: bool = True) -> list[Task]:
        """查询所有任务，可选是否包含已完成任务，按优先级 → 创建时间排序"""
        conn = get_conn()
        if include_done:
            rows = conn.execute(
                "SELECT * FROM tasks ORDER BY done ASC, created_at DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE done=0 ORDER BY created_at DESC"
            ).fetchall()
        return [Task.from_row(r) for r in rows]

    def get_today(self, include_done: bool = True) -> list[Task]:
        """
        主列表查询：
        - 未完成任务：全部显示（跨日保留，直到完成为止）
        - 已完成任务：只显示今日完成的（done_at LIKE 今日%）
        排序：未完成优先，按优先级高→中→低，同优先级按创建时间倒序
        """
        today_str = date.today().isoformat()
        priority_case = "CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END"
        conn = get_conn()
        if include_done:
            rows = conn.execute(
                f"""
                SELECT * FROM tasks
                WHERE done=0
                   OR (done=1 AND done_at LIKE ?)
                ORDER BY done ASC, {priority_case} ASC, created_at DESC
                """,
                (f"{today_str}%",),
            ).fetchall()
        else:
            rows = conn.execute(
                f"""
                SELECT * FROM tasks
                WHERE done=0
                ORDER BY {priority_case} ASC, created_at DESC
                """,
            ).fetchall()
        return [Task.from_row(r) for r in rows]

    def get_today_done(self) -> list[Task]:
        """查询今日已完成任务"""
        today_str = date.today().isoformat()
        conn = get_conn()
        rows = conn.execute(
            "SELECT * FROM tasks WHERE created_at LIKE ? AND done=1 ORDER BY done_at DESC",
            (f"{today_str}%",),
        ).fetchall()
        return [Task.from_row(r) for r in rows]

    def count_today(self) -> dict:
        """统计今日任务完成情况，返回 {'total': int, 'done': int, 'undone': int}"""
        today_str = date.today().isoformat()
        conn = get_conn()
        total = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE created_at LIKE ?",
            (f"{today_str}%",),
        ).fetchone()[0]
        done = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE created_at LIKE ? AND done=1",
            (f"{today_str}%",),
        ).fetchone()[0]
        return {"total": total, "done": done, "undone": total - done}

    def get_by_date_range(self, start: str, end: str) -> list[Task]:
        """按创建时间范围查询任务（start/end 为 'YYYY-MM-DD' 格式）"""
        conn = get_conn()
        rows = conn.execute(
            "SELECT * FROM tasks WHERE DATE(created_at) BETWEEN ? AND ? ORDER BY created_at DESC",
            (start, end),
        ).fetchall()
        return [Task.from_row(r) for r in rows]

    def get_history_by_date(self) -> dict[str, list[Task]]:
        """
        获取所有历史任务，按日期分组返回。
        返回格式：{'YYYY-MM-DD': [Task, ...], ...}，日期倒序排列（最新在前）
        """
        conn = get_conn()
        rows = conn.execute(
            "SELECT * FROM tasks ORDER BY created_at DESC"
        ).fetchall()
        result: dict[str, list[Task]] = {}
        for row in rows:
            task = Task.from_row(row)
            day = task.created_at[:10]  # "YYYY-MM-DD"
            result.setdefault(day, []).append(task)
        return result

    def get_week_summary(self, end_date: date | None = None) -> dict:
        """
        获取最近一周的任务统计，用于周报生成。

        Args:
            end_date: 周报截止日期（默认今天）

        Returns:
            {
                "start": "YYYY-MM-DD",
                "end": "YYYY-MM-DD",
                "total": int,
                "done": int,
                "undone": int,
                "by_day": {
                    "YYYY-MM-DD": {"done": [Task, ...], "undone": [Task, ...]},
                    ...
                },
                "by_priority": {"high": int, "medium": int, "low": int},
            }
        """
        from datetime import timedelta
        end_d = end_date or date.today()
        start_d = end_d - timedelta(days=6)  # 最近 7 天
        start_str = start_d.isoformat()
        end_str = end_d.isoformat()

        conn = get_conn()
        rows = conn.execute(
            """
            SELECT * FROM tasks
            WHERE DATE(created_at) BETWEEN ? AND ?
               OR (done=0 AND DATE(created_at) < ?)
            ORDER BY created_at DESC
            """,
            (start_str, end_str, start_str),
        ).fetchall()

        tasks = [Task.from_row(r) for r in rows]
        by_day: dict[str, dict[str, list]] = {}
        by_priority = {"high": 0, "medium": 0, "low": 0}
        done_count = 0

        for t in tasks:
            day = t.created_at[:10]
            if day not in by_day:
                by_day[day] = {"done": [], "undone": []}
            if t.done:
                by_day[day]["done"].append(t)
                done_count += 1
            else:
                by_day[day]["undone"].append(t)
            by_priority[t.priority] = by_priority.get(t.priority, 0) + 1

        return {
            "start": start_str,
            "end": end_str,
            "total": len(tasks),
            "done": done_count,
            "undone": len(tasks) - done_count,
            "by_day": dict(sorted(by_day.items())),
            "by_priority": by_priority,
        }
