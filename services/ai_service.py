"""
ai_service.py - AI 服务核心层

封装所有 AI 调用，基于 OpenAI 兼容接口（支持 DeepSeek / 通义 / GPT）。
提供三个核心方法：
  1. parse_task()        - 自然语言 → 结构化任务
  2. generate_reminder_texts() - 批量生成休息提醒文案
  3. generate_daily_review()   - 今日任务复盘报告

设计原则：
- 统一的超时与重试处理，AI 不可用时优雅降级
- 所有方法均为同步阻塞，由 AIWorker（QThread）在子线程调用
- 不依赖 UI 层，可独立测试
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from openai import OpenAI, APIError, APITimeoutError

from data.settings_repository import SettingsRepository

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


# --------------------------------------------------------------------------- #
#  AIService
# --------------------------------------------------------------------------- #

class AIService:
    """AI 服务封装，所有方法为同步阻塞调用（在 QThread 中执行）"""

    def __init__(self, settings: Optional[SettingsRepository] = None) -> None:
        self._settings = settings or SettingsRepository()
        self._client: Optional[OpenAI] = None

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
    #  接口 1：自然语言解析任务
    # ------------------------------------------------------------------ #

    def parse_task(self, user_input: str) -> dict:
        """
        将用户自然语言输入解析为结构化任务。

        Args:
            user_input: 用户输入，如 "明天下午 3 点开项目会议，比较重要"

        Returns:
            {
                "title": str,
                "priority": "high" | "medium" | "low",
                "due_time": str | None,   # "YYYY-MM-DD HH:MM" 或 None
                "raw": str                # 原始输入
            }

        Raises:
            ValueError: API Key 未配置
            RuntimeError: AI 调用失败
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
            client = self._get_client()
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=200,
            )
            content = response.choices[0].message.content.strip()

            # 尝试提取 JSON（模型有时会在前后加额外文字）
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
        """
        批量生成互不重复的休息提醒文案。

        Args:
            count: 需要生成的文案数量（默认 5 条）

        Returns:
            文案字符串列表，AI 不可用时返回本地降级文案
        """
        if not self.is_configured():
            logger.info("generate_reminder_texts: API Key 未配置，使用本地文案")
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
            content = response.choices[0].message.content.strip()
            lines = [line.strip() for line in content.splitlines() if line.strip()]
            # 过滤掉过短或过长的行
            lines = [l for l in lines if 5 <= len(l) <= 80]
            if not lines:
                return _sample_fallback(count)
            # 保证数量
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
    #  接口 3：今日复盘报告
    # ------------------------------------------------------------------ #

    def generate_daily_review(
        self,
        done_tasks: list[dict],
        undone_tasks: list[dict],
    ) -> str:
        """
        根据今日任务完成情况生成复盘报告。

        Args:
            done_tasks:   已完成任务列表，每项包含 title / priority / done_at
            undone_tasks: 未完成任务列表，每项包含 title / priority / due_time

        Returns:
            Markdown 格式的复盘报告字符串；
            API Key 未配置或调用失败时返回简要本地报告
        """
        today = datetime.now().strftime("%Y年%m月%d日")
        done_count = len(done_tasks)
        undone_count = len(undone_tasks)

        if not self.is_configured():
            return _local_review(today, done_tasks, undone_tasks)

        done_list = "\n".join(
            f"- [{t.get('priority', 'medium')}] {t['title']}"
            for t in done_tasks
        ) or "（今日暂无已完成任务）"

        undone_list = "\n".join(
            f"- [{t.get('priority', 'medium')}] {t['title']}"
            + (f"（截止：{t['due_time']}）" if t.get("due_time") else "")
            for t in undone_tasks
        ) or "（今日所有任务均已完成 🎉）"

        prompt = f"""你是一位温暖又专业的工作复盘助手。请根据以下今日任务数据，生成一份简洁有价值的复盘报告。

今日日期：{today}
已完成（{done_count} 项）：
{done_list}

未完成（{undone_count} 项）：
{undone_list}

报告要求：
1. 先简短肯定今日成果（1~2句）
2. 分析未完成任务的可能原因（若有，1~3条建议）
3. 给出明日优先事项提示（2~3条）
4. 结尾用一句温暖的话鼓励

格式：使用 Markdown（## 标题，- 列表），控制在 200 字以内，语气真诚不浮夸。"""

        model = self._settings.get("ai_model", "deepseek-chat")
        try:
            client = self._get_client()
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=600,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error("generate_daily_review 失败: %s", e)
            return _local_review(today, done_tasks, undone_tasks) + f"\n\n> ⚠️ AI 服务暂时不可用（{e}），以上为本地统计报告。"


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


def _local_review(today: str, done_tasks: list[dict], undone_tasks: list[dict]) -> str:
    """本地生成简要复盘报告（无 AI 时使用）"""
    done_count = len(done_tasks)
    undone_count = len(undone_tasks)
    lines = [
        f"## 📅 {today} 今日复盘",
        "",
        f"**✅ 已完成：{done_count} 项　❌ 未完成：{undone_count} 项**",
        "",
    ]
    if done_tasks:
        lines.append("### 完成的任务")
        for t in done_tasks:
            lines.append(f"- {t['title']}")
        lines.append("")
    if undone_tasks:
        lines.append("### 未完成的任务")
        for t in undone_tasks:
            suffix = f"（截止：{t['due_time']}）" if t.get("due_time") else ""
            lines.append(f"- {t['title']}{suffix}")
        lines.append("")
    lines.append("---")
    lines.append("_提示：配置 AI API Key 可获得更丰富的复盘分析 ✨_")
    return "\n".join(lines)
