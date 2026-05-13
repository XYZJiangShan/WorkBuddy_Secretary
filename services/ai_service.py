"""
ai_service.py - AI 服务核心层

封装所有 AI 调用，基于 OpenAI 兼容接口（支持 DeepSeek / 通义 / GPT）。
提供核心方法：
  1. parse_task()              - 自然语言 → 结构化任务
  2. generate_reminder_texts() - 批量生成休息提醒文案
  3. generate_daily_review()   - 今日任务复盘报告（v2：含笔记+图片描述）
  4. generate_weekly_report()  - 周报整理报告（v2：含笔记+图片描述）
  5. describe_image()          - Vision 识别图片内容

设计原则：
- 统一的超时与重试处理，AI 不可用时优雅降级
- 所有方法均为同步阻塞，由 AIWorker（QThread）在子线程调用
- 不依赖 UI 层，可独立测试
- 每次调用自动记录 token 用量，支持周限额检查
"""

from __future__ import annotations

import base64
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from openai import OpenAI, APIError, APITimeoutError

from data.settings_repository import SettingsRepository
from data.token_repository import TokenRepository

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
#  本地降级文案（AI 不可用时使用）
# --------------------------------------------------------------------------- #
FALLBACK_REMINDER_TEXTS: list[str] = [
    "⏰ 休息一下吧！闭上眼睛 20 秒，让眼睛放松放松~",
    "🧘 起来活动活动！伸个懒腰、转转脖子，远眺窗外绿色~",
    "💪 已经专注很久了！站起来走走，喝杯水，回来状态更好！",
    "🌿 给自己一点喘息空间，深呼吸三次，感受当下的宁静~",
    "✨ 短暂休息是下一段高效工作的燃料，好好补充一下！",
    "👀 眼睛需要休息了，看看远处，让视线放松 1 分钟~",
    "🎵 休息片刻，起身倒杯热水，听段音乐，再回来冲~",
    "🌟 工作很棒！现在给自己 5 分钟，做几个简单拉伸~",
]

# 图片识别每日上限（防止意外消耗过多 token）
MAX_VISION_IMAGES_PER_REPORT = 10
# 支持的图片后缀
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
# MIME 映射
_MIME_MAP = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
}


# --------------------------------------------------------------------------- #
#  AIService
# --------------------------------------------------------------------------- #

class AIService:
    """AI 服务封装，所有方法为同步阻塞调用（在 QThread 中执行）"""

    def __init__(self, settings: Optional[SettingsRepository] = None) -> None:
        self._settings = settings or SettingsRepository()
        self._client: Optional[OpenAI] = None
        self._token_repo = TokenRepository()

    # ------------------------------------------------------------------ #
    #  客户端（懒初始化，配置变更后调用 reset() 重建）
    # ------------------------------------------------------------------ #

    def _get_client(self) -> OpenAI:
        """获取（或重建）OpenAI 客户端"""
        if self._client is None:
            self._client = self._build_client()
        return self._client

    def _build_client(self) -> OpenAI:
        api_key = self._settings.get("ai_api_key", "").strip()
        base_url = self._settings.get("ai_base_url", "https://api.deepseek.com/v1").strip()
        timeout = self._settings.get_float("ai_timeout", 15.0)

        if not api_key:
            raise ValueError("AI API Key 未配置，请在设置中填写")

        return OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
        )

    def reset(self) -> None:
        """配置更新后调用，下次请求会重建客户端"""
        self._client = None

    def is_configured(self) -> bool:
        """检查 API Key 是否已配置"""
        return bool(self._settings.get("ai_api_key", "").strip())

    # ------------------------------------------------------------------ #
    #  Token 用量管理
    # ------------------------------------------------------------------ #

    def _record_usage(self, call_type: str, response) -> None:
        """从 API 响应中提取 token 用量并记录"""
        try:
            usage = getattr(response, "usage", None)
            if usage:
                self._token_repo.record(
                    call_type=call_type,
                    prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                    completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
                    total_tokens=getattr(usage, "total_tokens", 0) or 0,
                )
        except Exception as e:
            logger.warning("记录 token 用量失败: %s", e)

    def check_weekly_limit(self) -> bool:
        """返回 True 表示还有余额可用，False 表示已超周限额"""
        limit = self._settings.get_int("weekly_token_limit", 0)
        if limit <= 0:
            return True  # 0 或负数 = 不限制
        used = self._token_repo.get_week_total()
        return used < limit

    def get_week_usage_info(self) -> dict:
        """获取本周 token 使用概况"""
        limit = self._settings.get_int("weekly_token_limit", 0)
        used = self._token_repo.get_week_total()
        by_type = self._token_repo.get_week_by_type()
        return {
            "used": used,
            "limit": limit,
            "remaining": max(0, limit - used) if limit > 0 else -1,
            "by_type": by_type,
        }

    # ------------------------------------------------------------------ #
    #  接口 1：自然语言解析任务
    # ------------------------------------------------------------------ #

    def parse_task(self, user_input: str) -> dict:
        """
        将用户自然语言输入解析为结构化任务。
        """
        today = datetime.now().strftime("%Y-%m-%d %H:%M")
        prompt = f"""你是一个任务解析助手。请将用户输入的自然语言任务描述解析为结构化 JSON。

当前时间：{today}

规则：
- title: 简洁的任务名称（不超过30字）
- priority: 优先级，只能是 "high"（高/重要/紧急）、"medium"（中/普通）、"low"（低/随意）
- due_time: 截止时间，格式为 "YYYY-MM-DD HH:MM"，无法确定时为 null
- 如果用户说"明天"，基于今天日期推算；说"下周"推算到下周一

只返回 JSON，不要解释，格式如下：
{{"title": "...", "priority": "medium", "due_time": "2026-03-31 15:00"}}

用户输入：{user_input}"""

        model = self._settings.get("ai_model", "deepseek-chat")
        try:
            if not self.check_weekly_limit():
                raise RuntimeError("本周 Token 用量已达上限，请在设置中调整")

            client = self._get_client()
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=200,
            )
            self._record_usage("parse", response)

            content = response.choices[0].message.content.strip()
            content = _extract_json(content)
            data = json.loads(content)

            return {
                "title": str(data.get("title", user_input[:30])),
                "priority": _normalize_priority(data.get("priority", "medium")),
                "due_time": data.get("due_time") or None,
                "raw": user_input,
            }
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("parse_task JSON 解析失败: %s，降级处理", e)
            return {
                "title": user_input[:30],
                "priority": "medium",
                "due_time": None,
                "raw": user_input,
            }
        except Exception as e:
            logger.error("parse_task AI 调用失败: %s", e)
            raise RuntimeError(f"AI 解析失败：{e}") from e

    # ------------------------------------------------------------------ #
    #  接口 2：批量生成休息提醒文案
    # ------------------------------------------------------------------ #

    def generate_reminder_texts(self, count: int = 5) -> list[str]:
        """批量生成互不重复的休息提醒文案。"""
        if not self.is_configured():
            logger.info("generate_reminder_texts: API Key 未配置，使用本地文案")
            return _sample_fallback(count)

        if not self.check_weekly_limit():
            logger.info("generate_reminder_texts: 周 Token 限额已满，使用本地文案")
            return _sample_fallback(count)

        prompt = f"""你是一个关爱员工健康的小助手。请生成 {count} 条"休息提醒"文案，帮助长时间工作的人放松身心。

要求：
- 每条文案简短有趣（15~35 字），语气轻松温暖，不说教
- 内容多样，可涉及：眼部放松、起身活动、深呼吸、喝水、远眺等
- 可适当加 1~2 个 emoji 增加活泼感
- 每条一行，不编号，不加引号

请直接输出 {count} 条文案，每条一行："""

        model = self._settings.get("ai_model", "deepseek-chat")
        try:
            client = self._get_client()
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.9,
                max_tokens=400,
            )
            self._record_usage("reminder", response)

            content = response.choices[0].message.content.strip()
            lines = [line.strip() for line in content.splitlines() if line.strip()]
            lines = [l for l in lines if 5 <= len(l) <= 80]
            if not lines:
                return _sample_fallback(count)
            while len(lines) < count:
                lines.extend(_sample_fallback(count - len(lines)))
            return lines[:count]
        except (APITimeoutError, APIError) as e:
            logger.warning("generate_reminder_texts 失败: %s，使用本地文案", e)
            return _sample_fallback(count)
        except Exception as e:
            logger.warning("generate_reminder_texts 异常: %s，使用本地文案", e)
            return _sample_fallback(count)

    # ------------------------------------------------------------------ #
    #  接口 3：Vision 图片识别
    # ------------------------------------------------------------------ #

    def describe_image(self, image_path: str) -> str:
        """
        用 Vision 模型识别图片内容，返回一句简要中文描述。

        Args:
            image_path: 图片文件绝对路径

        Returns:
            图片内容描述字符串；失败时返回空字符串
        """
        path = Path(image_path)
        if not path.exists():
            logger.warning("describe_image: 文件不存在 %s", image_path)
            return ""

        suffix = path.suffix.lower()
        if suffix not in _IMAGE_EXTENSIONS:
            logger.warning("describe_image: 不支持的图片格式 %s", suffix)
            return ""

        # 限制文件大小（超过 5MB 跳过）
        try:
            size = path.stat().st_size
            if size > 5 * 1024 * 1024:
                logger.info("describe_image: 文件过大 %.1fMB，跳过", size / 1024 / 1024)
                return f"(图片文件 {path.name}，{size / 1024 / 1024:.1f}MB，过大跳过识别)"
        except Exception:
            return ""

        try:
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
        except Exception as e:
            logger.warning("describe_image: 读取文件失败 %s", e)
            return ""

        mime = _MIME_MAP.get(suffix, "image/png")
        model = self._settings.get("ai_model", "deepseek-chat")

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "用一句中文简要描述这张图片的内容。"
                            "如果是截图，请提取关键信息（如报错内容、界面状态、数据等）。"
                            "如果是游戏截图，描述画面场景和关键元素。"
                            "不超过 80 字。"
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    },
                ],
            }
        ]

        try:
            if not self.check_weekly_limit():
                return f"(图片 {path.name}，Token 限额已满跳过识别)"

            client = self._get_client()
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.2,
                max_tokens=150,
            )
            self._record_usage("vision", response)

            desc = response.choices[0].message.content.strip()
            logger.debug("describe_image: %s → %s", path.name, desc[:40])
            return desc
        except Exception as e:
            logger.warning("describe_image 失败: %s", e)
            return f"(图片 {path.name}，识别失败)"

    def describe_images_batch(self, image_paths: list[str]) -> list[str]:
        """
        批量识别图片，返回描述列表（与输入等长）。
        超过 MAX_VISION_IMAGES_PER_REPORT 张的只返回文件名。
        """
        results = []
        for i, path in enumerate(image_paths):
            if i < MAX_VISION_IMAGES_PER_REPORT:
                desc = self.describe_image(path)
                results.append(desc)
            else:
                name = Path(path).name
                results.append(f"(图片 {name}，超出识别上限)")
        return results

    # ------------------------------------------------------------------ #
    #  接口 4：今日复盘报告（v2）
    # ------------------------------------------------------------------ #

    def generate_daily_review(
        self,
        done_tasks: list[dict],
        undone_tasks: list[dict],
    ) -> str:
        """
        根据今日任务完成情况生成复盘报告。

        v2 改进：
        - 每条任务可带 notes（文字笔记）、image_descriptions（图片描述）、
          links（URL列表）、files（文档名列表）
        - 新格式：完成 / 未完成 / 小结，简洁实用
        """
        today = datetime.now().strftime("%Y年%m月%d日")
        done_count = len(done_tasks)
        undone_count = len(undone_tasks)

        if not self.is_configured():
            return _local_review(today, done_tasks, undone_tasks)

        if not self.check_weekly_limit():
            return _local_review(today, done_tasks, undone_tasks) + \
                "\n\n> ⚠️ 本周 Token 用量已达上限，以上为本地统计报告。"

        done_list = _format_tasks_for_prompt(done_tasks, "done") or "（今日暂无已完成任务）"
        undone_list = _format_tasks_for_prompt(undone_tasks, "undone") or "（今日所有任务均已完成 🎉）"

        prompt = f"""你是一位简洁务实的工作复盘助手。请根据以下今日任务数据，生成一份日报。

今日日期：{today}
已完成（{done_count} 项）：
{done_list}

未完成（{undone_count} 项）：
{undone_list}

日报格式要求（严格遵循）：
1. 标题行：## 日报 · {today}
2. **完成 ✅（N 项）**：逐条列出已完成任务，每条用 - 开头。如果任务有笔记或图片描述，用 → 缩进补充关键信息（一句话即可）
3. **未完成 ❌（N 项）**：逐条列出未完成任务，有截止时间的标注
4. **小结**：1~2 句话概括今天做了什么 + 明天重点，不要鼓励不要废话

语气：简洁客观，直接说事。不要分类汇总，不要鼓励语。
格式：Markdown。字数根据任务量弹性，不硬设上限。"""

        model = self._settings.get("ai_model", "deepseek-chat")
        try:
            client = self._get_client()
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=900,
            )
            self._record_usage("daily", response)
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error("generate_daily_review 失败: %s", e)
            return _local_review(today, done_tasks, undone_tasks) + \
                f"\n\n> ⚠️ AI 服务暂时不可用（{e}），以上为本地统计报告。"

    # ------------------------------------------------------------------ #
    #  接口 5：周报整理（v2）
    # ------------------------------------------------------------------ #

    def generate_weekly_report(self, week_summary: dict) -> str:
        """
        根据一周任务数据生成周报。

        v2 改进：新格式（概览/完成清单/待跟进/下周重点），含笔记和图片描述。
        """
        start = week_summary["start"]
        end = week_summary["end"]
        total = week_summary["total"]
        done = week_summary["done"]
        undone = week_summary["undone"]
        by_day = week_summary["by_day"]
        by_priority = week_summary["by_priority"]

        if not self.is_configured():
            return _local_weekly_report(week_summary)

        if not self.check_weekly_limit():
            return _local_weekly_report(week_summary) + \
                "\n\n> ⚠️ 本周 Token 用量已达上限，以上为本地统计报告。"

        # 构造每日明细文本（v2：含笔记信息）
        daily_detail_lines = []
        for day, tasks_map in by_day.items():
            done_titles = [t.title for t in tasks_map["done"]]
            undone_titles = [t.title for t in tasks_map["undone"]]
            daily_detail_lines.append(f"📅 {day}:")
            if done_titles:
                daily_detail_lines.append(f"  ✅ 已完成: {', '.join(done_titles)}")
            if undone_titles:
                daily_detail_lines.append(f"  ❌ 未完成: {', '.join(undone_titles)}")
            if not done_titles and not undone_titles:
                daily_detail_lines.append("  （无任务记录）")

        # 附加 enriched 信息
        enriched_info = week_summary.get("enriched_info", "")

        daily_detail = "\n".join(daily_detail_lines) or "（本周无任务记录）"

        rate = (done / max(total, 1) * 100)
        prompt = f"""你是一位简洁务实的工作效率顾问。请根据以下一周任务数据，生成一份周报。

周报期间：{start} ~ {end}
任务统计：总计 {total} 项，已完成 {done} 项，未完成 {undone} 项
完成率：{rate:.0f}%
优先级分布：高 {by_priority.get('high', 0)} 项 / 中 {by_priority.get('medium', 0)} 项 / 低 {by_priority.get('low', 0)} 项

每日明细：
{daily_detail}

{f"任务详细信息：{chr(10)}{enriched_info}" if enriched_info else ""}

周报格式要求（严格遵循）：
1. 标题行：## 周报 · {start} ~ {end}
2. **概览**：2 句话——本周完成率 + 重点推进方向
3. **完成清单**：合并同类项紧凑列出（不要逐条一行一行列），如果有任务笔记/图片描述就融入补充
4. **未完成 & 待跟进**：列出未完成任务 + 建议下周优先处理的
5. **下周重点**：2~3 条实际待办

语气：简洁客观专业，不要鼓励语，不要节奏分析。
格式：Markdown。字数根据任务量弹性。"""

        model = self._settings.get("ai_model", "deepseek-chat")
        try:
            client = self._get_client()
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=1000,
            )
            self._record_usage("weekly", response)
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error("generate_weekly_report 失败: %s", e)
            return _local_weekly_report(week_summary) + \
                f"\n\n> ⚠️ AI 服务暂时不可用（{e}），以上为本地统计报告。"


# --------------------------------------------------------------------------- #
#  私有工具函数
# --------------------------------------------------------------------------- #

def _extract_json(text: str) -> str:
    """从 AI 回复中提取第一个 {...} JSON 块"""
    start = text.find("{")
    end = text.rfind("}") + 1
    if start != -1 and end > start:
        return text[start:end]
    return text


def _normalize_priority(raw: str) -> str:
    """将 AI 返回的优先级标准化为 high / medium / low"""
    raw = str(raw).lower().strip()
    if raw in ("high", "高", "紧急", "重要"):
        return "high"
    if raw in ("low", "低", "不重要", "随意"):
        return "low"
    return "medium"


def _sample_fallback(count: int) -> list[str]:
    """从本地备用文案中采样（循环补足数量）"""
    import random
    pool = FALLBACK_REMINDER_TEXTS.copy()
    random.shuffle(pool)
    result: list[str] = []
    while len(result) < count:
        result.extend(pool)
    return result[:count]


def _format_tasks_for_prompt(tasks: list[dict], status: str) -> str:
    """
    将任务列表格式化为 AI prompt 文本（v2：含笔记、图片描述、链接等）。

    每条任务的 dict 可包含：
    - title, priority, done_at / due_time
    - notes: str（文字笔记内容）
    - image_descriptions: list[str]（图片识别描述）
    - links: list[str]（URL 列表）
    - files: list[str]（文档文件名列表）
    """
    lines = []
    for t in tasks:
        # 基本信息行
        prio = t.get("priority", "medium")
        line = f"- [{prio}] {t['title']}"
        if status == "undone" and t.get("due_time"):
            line += f"（截止：{t['due_time']}）"
        lines.append(line)

        # 文字笔记
        notes = t.get("notes", "").strip()
        if notes:
            # 截断过长的笔记
            if len(notes) > 200:
                notes = notes[:200] + "…"
            lines.append(f"  📝 笔记: {notes}")

        # 图片描述
        img_descs = t.get("image_descriptions", [])
        for desc in img_descs:
            if desc:
                lines.append(f"  🖼 图片: {desc}")

        # 链接
        link_list = t.get("links", [])
        for lnk in link_list:
            if lnk:
                lines.append(f"  🔗 链接: {lnk}")

        # 文档附件
        file_list = t.get("files", [])
        if file_list:
            lines.append(f"  📎 文档: {', '.join(file_list)}")

    return "\n".join(lines)


def _local_review(today: str, done_tasks: list[dict], undone_tasks: list[dict]) -> str:
    """本地生成简洁版复盘报告（无 AI 时使用）"""
    done_count = len(done_tasks)
    undone_count = len(undone_tasks)
    lines = [
        f"## 日报 · {today}",
        "",
    ]
    if done_tasks:
        lines.append(f"### 完成 ✅（{done_count} 项）")
        for t in done_tasks:
            lines.append(f"- {t['title']}")
            notes = t.get("notes", "").strip()
            if notes:
                lines.append(f"  → {notes[:60]}")
        lines.append("")

    if undone_tasks:
        lines.append(f"### 未完成 ❌（{undone_count} 项）")
        for t in undone_tasks:
            suffix = f"（截止：{t['due_time']}）" if t.get("due_time") else ""
            lines.append(f"- {t['title']}{suffix}")
        lines.append("")
    elif done_tasks:
        lines.append("### 未完成 ❌（0 项）")
        lines.append("今日所有任务均已完成 🎉")
        lines.append("")

    lines.append("### 小结")
    if done_count > 0:
        lines.append(f"今日完成 {done_count} 项任务。")
    else:
        lines.append("今日暂无已完成任务。")

    lines.append("")
    lines.append("---")
    lines.append("_提示：配置 AI API Key 可获得更丰富的分析 ✨_")
    return "\n".join(lines)


def _local_weekly_report(week_summary: dict) -> str:
    """本地生成简洁版周报（无 AI 时使用）"""
    start = week_summary["start"]
    end = week_summary["end"]
    total = week_summary["total"]
    done = week_summary["done"]
    undone = week_summary["undone"]
    by_day = week_summary["by_day"]
    by_priority = week_summary["by_priority"]
    rate = (done / max(total, 1) * 100)

    lines = [
        f"## 周报 · {start} ~ {end}",
        "",
        f"### 概览",
        f"本周完成 {done}/{total} 项任务，完成率 {rate:.0f}%。",
        f"优先级分布：高 {by_priority.get('high', 0)} / 中 {by_priority.get('medium', 0)} / 低 {by_priority.get('low', 0)}",
        "",
    ]

    all_done = []
    all_undone = []
    if by_day:
        for day, tasks_map in by_day.items():
            all_done.extend(tasks_map["done"])
            all_undone.extend(tasks_map["undone"])

    if all_done:
        lines.append("### 完成清单")
        for t in all_done:
            lines.append(f"- ✅ {t.title}")
        lines.append("")

    if all_undone:
        lines.append("### 未完成 & 待跟进")
        for t in all_undone:
            lines.append(f"- ❌ {t.title}")
        lines.append("")

    lines.append("---")
    lines.append("_提示：配置 AI API Key 可获得更深入的分析周报 ✨_")
    return "\n".join(lines)
