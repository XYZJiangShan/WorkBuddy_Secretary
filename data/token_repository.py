"""
token_repository.py - Token 用量统计数据层

记录每次 AI 调用的 token 消耗，提供周统计和限额检查。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import Optional

from data.database import get_conn


@dataclass
class TokenRecord:
    call_type: str          # 'parse' | 'reminder' | 'daily' | 'weekly' | 'vision'
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    called_at: str = field(
        default_factory=lambda: datetime.now().isoformat(sep=" ", timespec="seconds")
    )
    id: Optional[int] = None


class TokenRepository:
    """Token 用量 CRUD + 统计"""

    def record(self, call_type: str, prompt_tokens: int,
               completion_tokens: int, total_tokens: int) -> TokenRecord:
        """记录一次 AI 调用的 token 用量"""
        rec = TokenRecord(
            call_type=call_type,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
        conn = get_conn()
        cur = conn.execute(
            """
            INSERT INTO token_usage (call_type, prompt_tokens, completion_tokens,
                                     total_tokens, called_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (rec.call_type, rec.prompt_tokens, rec.completion_tokens,
             rec.total_tokens, rec.called_at),
        )
        conn.commit()
        rec.id = cur.lastrowid
        return rec

    def get_week_total(self, end_date: date | None = None) -> int:
        """获取本周（最近 7 天）的总 token 消耗"""
        end_d = end_date or date.today()
        start_d = end_d - timedelta(days=6)
        conn = get_conn()
        row = conn.execute(
            """
            SELECT COALESCE(SUM(total_tokens), 0)
            FROM token_usage
            WHERE DATE(called_at) BETWEEN ? AND ?
            """,
            (start_d.isoformat(), end_d.isoformat()),
        ).fetchone()
        return row[0] if row else 0

    def get_week_by_type(self, end_date: date | None = None) -> dict[str, int]:
        """按调用类型统计本周 token 消耗"""
        end_d = end_date or date.today()
        start_d = end_d - timedelta(days=6)
        conn = get_conn()
        rows = conn.execute(
            """
            SELECT call_type, COALESCE(SUM(total_tokens), 0)
            FROM token_usage
            WHERE DATE(called_at) BETWEEN ? AND ?
            GROUP BY call_type
            """,
            (start_d.isoformat(), end_d.isoformat()),
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def get_today_total(self) -> int:
        """获取今日总 token 消耗"""
        today_str = date.today().isoformat()
        conn = get_conn()
        row = conn.execute(
            """
            SELECT COALESCE(SUM(total_tokens), 0)
            FROM token_usage
            WHERE DATE(called_at) = ?
            """,
            (today_str,),
        ).fetchone()
        return row[0] if row else 0
