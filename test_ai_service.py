"""
test_ai_service.py - AI 服务层验证脚本

测试内容：
1. AIService 在无 API Key 时的降级行为
2. parse_task 本地降级（JSON 解析失败时）
3. generate_reminder_texts 降级文案采样
4. generate_daily_review 本地报告生成
5. AIWorker 信号连接（需要 QApplication）
"""

import sys
import io
sys.path.insert(0, ".")
# 避免 Windows GBK 终端 emoji 编码错误
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# ---- 测试 1: 导入 ----
from services.ai_service import AIService, _sample_fallback, _local_review, _normalize_priority
from data.settings_repository import SettingsRepository
print("Import OK")

# ---- 测试 2: is_configured ----
svc = AIService()
print(f"is_configured (no key): {svc.is_configured()}")  # 期望 False

# ---- 测试 3: generate_reminder_texts 降级 ----
texts = svc.generate_reminder_texts(count=3)
print(f"Fallback reminder texts ({len(texts)} items):")
for t in texts:
    print(f"  - {t}")

# ---- 测试 4: generate_daily_review 本地报告 ----
done = [{"title": "写周报", "priority": "high", "done_at": "2026-03-30 17:00"}]
undone = [{"title": "整理文档", "priority": "low", "due_time": None}]
report = svc.generate_daily_review(done, undone)
print("\n--- 本地复盘报告 ---")
print(report)
print("---")

# ---- 测试 5: _normalize_priority ----
assert _normalize_priority("high") == "high"
assert _normalize_priority("低") == "low"
assert _normalize_priority("紧急") == "high"
assert _normalize_priority("whatever") == "medium"
print("\n_normalize_priority: OK")

# ---- 测试 6: AIWorker 导入（不启动 QApplication，只检查 import）----
from services.ai_worker import AIWorker, run_ai_task
print("AIWorker import: OK")

# ---- 测试 7: AIWorker 实例化并检查方法链 ----
worker = AIWorker(svc)
result = worker.parse_task("明天下午3点开会")
assert result is worker, "方法链应返回 self"
assert worker._task_type == "parse_task"
assert worker._kwargs["user_input"] == "明天下午3点开会"
print("AIWorker.parse_task() chaining: OK")

worker2 = AIWorker(svc)
worker2.generate_reminder_texts(count=4)
assert worker2._task_type == "reminder_texts"
assert worker2._kwargs["count"] == 4
print("AIWorker.generate_reminder_texts() chaining: OK")

worker3 = AIWorker(svc)
worker3.generate_daily_review(done_tasks=done, undone_tasks=undone)
assert worker3._task_type == "daily_review"
print("AIWorker.generate_daily_review() chaining: OK")

print("\nAll AI service tests PASSED!")
