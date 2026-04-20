"""
report_repository.py - 日报/周报存储层

封装 reports 表的 CRUD 操作：
- save_report(): 保存/覆盖指定日期的报告
- get_report(): 按类型+日期查询单条
- get_reports_by_type(): 按类型查询历史列表
- get_all_reports(): 全量历史
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional

from data.database import get_conn


@dataclass
class Report:
    report_type: str          # 'daily' | 'weekly'
    report_date: str          # 日报: 'YYYY-MM-DD', 周报: 'YYYY-MM-DD~YYYY-MM-DD'
    content: str              # Markdown 正文
    auto_generated: bool = False
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(sep=" ", timespec="seconds"))
    id: Optional[int] = None


class ReportRepository:
    """日报/周报存储 CRUD"""

    def save_report(self, report: Report) -> Report:
        """
        保存报告（INSERT OR REPLACE）。
        同类型+同日期只保留最新一份。
        """
        conn = get_conn()
        conn.execute(
            """
            INSERT OR REPLACE INTO reports
                (report_type, report_date, content, auto_generated, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                report.report_type,
                report.report_date,
                report.content,
                int(report.auto_generated),
                report.created_at,
            ),
        )
        conn.commit()
        # 读回 id
        row = conn.execute(
            "SELECT id FROM reports WHERE report_type=? AND report_date=?",
            (report.report_type, report.report_date),
        ).fetchone()
        if row:
            report.id = row[0]
        return report

    def get_report(self, report_type: str, report_date: str) -> Optional[Report]:
        """按类型+日期查询单条"""
        conn = get_conn()
        row = conn.execute(
            "SELECT * FROM reports WHERE report_type=? AND report_date=?",
            (report_type, report_date),
        ).fetchone()
        return self._row_to_report(row) if row else None

    def get_reports_by_type(self, report_type: str, limit: int = 60) -> list[Report]:
        """按类型查询历史列表（最新在前）"""
        conn = get_conn()
        rows = conn.execute(
            "SELECT * FROM reports WHERE report_type=? ORDER BY report_date DESC LIMIT ?",
            (report_type, limit),
        ).fetchall()
        return [self._row_to_report(r) for r in rows]

    def get_all_reports(self, limit: int = 100) -> list[Report]:
        """全量查询（最新在前）"""
        conn = get_conn()
        rows = conn.execute(
            "SELECT * FROM reports ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_report(r) for r in rows]

    def delete_report(self, report_id: int) -> bool:
        conn = get_conn()
        cursor = conn.execute("DELETE FROM reports WHERE id=?", (report_id,))
        conn.commit()
        return cursor.rowcount > 0

    @staticmethod
    def _row_to_report(row) -> Report:
        return Report(
            id=row["id"],
            report_type=row["report_type"],
            report_date=row["report_date"],
            content=row["content"],
            auto_generated=bool(row["auto_generated"]),
            created_at=row["created_at"],
        )
