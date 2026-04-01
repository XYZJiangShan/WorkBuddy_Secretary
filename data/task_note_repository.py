"""
task_note_repository.py - 任务附件/笔记数据层

每条任务可以有多条笔记，支持：
  - text  : 文字结论（直接存 content 字段）
  - image : 图片文件（复制到 AppData/DeskSecretary/attachments/，存路径）
  - video : 视频文件（同上）
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from data.database import get_conn, get_app_data_dir


def get_attachments_dir() -> Path:
    """附件存储目录：%APPDATA%/DeskSecretary/attachments/"""
    d = get_app_data_dir() / "attachments"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class TaskNote:
    task_id: int
    note_type: str          # 'text' | 'image' | 'video' | 'link' | 'file'
    content: Optional[str] = None   # 文字/URL 或 文件路径（绝对）
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    created_at: str = field(
        default_factory=lambda: datetime.now().isoformat(sep=" ", timespec="seconds")
    )
    id: Optional[int] = None

    @property
    def is_text(self) -> bool:
        return self.note_type == "text"

    @property
    def is_image(self) -> bool:
        return self.note_type == "image"

    @property
    def is_video(self) -> bool:
        return self.note_type == "video"

    @property
    def is_link(self) -> bool:
        return self.note_type == "link"

    @property
    def is_doc_file(self) -> bool:
        """本地文档文件（非图片/视频）"""
        return self.note_type == "file"

    @property
    def display_name(self) -> str:
        if self.is_text:
            txt = (self.content or "").strip()
            return txt[:40] + "…" if len(txt) > 40 else txt
        return self.file_name or self.content or "附件"


class TaskNoteRepository:
    """任务附件 CRUD"""

    # ------------------------------------------------------------------ #
    #  写操作
    # ------------------------------------------------------------------ #

    def add_text(self, task_id: int, text: str) -> TaskNote:
        """添加文字笔记"""
        note = TaskNote(task_id=task_id, note_type="text", content=text)
        return self._insert(note)

    def add_link(self, task_id: int, url: str, title: str = "") -> TaskNote:
        """添加 URL 链接（企业微信/飞书/Notion/任意网址）"""
        note = TaskNote(
            task_id=task_id,
            note_type="link",
            content=url.strip(),
            file_name=title.strip() or url.strip(),
        )
        return self._insert(note)

    def add_doc_file(self, task_id: int, src_path: str) -> TaskNote:
        """添加本地文档文件（PDF/Word/Excel/PPT/TXT等），复制到附件目录"""
        src = Path(src_path)
        if not src.exists():
            raise FileNotFoundError(f"文件不存在: {src_path}")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        dest_name = f"t{task_id}_{ts}{src.suffix.lower()}"
        dest = get_attachments_dir() / dest_name
        shutil.copy2(src, dest)
        note = TaskNote(
            task_id=task_id,
            note_type="file",
            content=str(dest),
            file_name=src.name,
            file_size=dest.stat().st_size,
        )
        return self._insert(note)

    def add_file(self, task_id: int, src_path: str, note_type: str = "image") -> TaskNote:
        """
        复制文件到附件目录，插入记录。
        note_type: 'image' | 'video'
        """
        src = Path(src_path)
        if not src.exists():
            raise FileNotFoundError(f"文件不存在: {src_path}")

        # 生成唯一文件名（task_id + 时间戳 + 后缀）
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        dest_name = f"t{task_id}_{ts}{src.suffix.lower()}"
        dest = get_attachments_dir() / dest_name
        shutil.copy2(src, dest)

        note = TaskNote(
            task_id=task_id,
            note_type=note_type,
            content=str(dest),
            file_name=src.name,
            file_size=dest.stat().st_size,
        )
        return self._insert(note)

    def update_text(self, note_id: int, text: str) -> bool:
        conn = get_conn()
        cur = conn.execute(
            "UPDATE task_notes SET content=? WHERE id=? AND note_type='text'",
            (text, note_id),
        )
        conn.commit()
        return cur.rowcount > 0

    def delete(self, note_id: int) -> bool:
        """删除笔记（文件类型同时删除物理文件）"""
        note = self.get_by_id(note_id)
        if note and not note.is_text and note.content:
            try:
                Path(note.content).unlink(missing_ok=True)
            except Exception:
                pass
        conn = get_conn()
        cur = conn.execute("DELETE FROM task_notes WHERE id=?", (note_id,))
        conn.commit()
        return cur.rowcount > 0

    def delete_all_for_task(self, task_id: int) -> None:
        """删除某任务的全部附件（含物理文件）"""
        notes = self.get_by_task(task_id)
        for n in notes:
            if not n.is_text and n.content:
                try:
                    Path(n.content).unlink(missing_ok=True)
                except Exception:
                    pass
        conn = get_conn()
        conn.execute("DELETE FROM task_notes WHERE task_id=?", (task_id,))
        conn.commit()

    # ------------------------------------------------------------------ #
    #  读操作
    # ------------------------------------------------------------------ #

    def get_by_id(self, note_id: int) -> Optional[TaskNote]:
        conn = get_conn()
        row = conn.execute("SELECT * FROM task_notes WHERE id=?", (note_id,)).fetchone()
        return self._row_to_note(row) if row else None

    def get_by_task(self, task_id: int) -> list[TaskNote]:
        conn = get_conn()
        rows = conn.execute(
            "SELECT * FROM task_notes WHERE task_id=? ORDER BY created_at ASC",
            (task_id,),
        ).fetchall()
        return [self._row_to_note(r) for r in rows]

    def get_text_note(self, task_id: int) -> Optional[TaskNote]:
        """取第一条文字笔记（每任务通常只有一条结论）"""
        conn = get_conn()
        row = conn.execute(
            "SELECT * FROM task_notes WHERE task_id=? AND note_type='text' ORDER BY created_at ASC LIMIT 1",
            (task_id,),
        ).fetchone()
        return self._row_to_note(row) if row else None

    def count_files(self, task_id: int) -> dict:
        """统计某任务的附件数"""
        conn = get_conn()
        rows = conn.execute(
            "SELECT note_type, COUNT(*) FROM task_notes WHERE task_id=? GROUP BY note_type",
            (task_id,),
        ).fetchall()
        result = {"text": 0, "image": 0, "video": 0}
        for row in rows:
            result[row[0]] = row[1]
        return result

    # ------------------------------------------------------------------ #
    #  内部
    # ------------------------------------------------------------------ #

    def _insert(self, note: TaskNote) -> TaskNote:
        conn = get_conn()
        cur = conn.execute(
            """
            INSERT INTO task_notes (task_id, note_type, content, file_name, file_size, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (note.task_id, note.note_type, note.content,
             note.file_name, note.file_size, note.created_at),
        )
        conn.commit()
        note.id = cur.lastrowid
        return note

    @staticmethod
    def _row_to_note(row) -> TaskNote:
        return TaskNote(
            id=row["id"],
            task_id=row["task_id"],
            note_type=row["note_type"],
            content=row["content"],
            file_name=row["file_name"],
            file_size=row["file_size"],
            created_at=row["created_at"],
        )
