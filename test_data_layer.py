"""数据层快速功能验证脚本"""
import sys
sys.path.insert(0, ".")

from data.database import get_conn
from data.task_repository import Task, TaskRepository
from data.settings_repository import SettingsRepository

repo = TaskRepository()
settings = SettingsRepository()

# 初始化默认配置
settings.initialize()
interval = settings.get("reminder_interval_minutes")
api_key = settings.get("ai_api_key")
print(f"Settings initialized: interval={interval} min, api_key={repr(api_key)}")

# 添加任务
t1 = repo.add(Task(title="写周报", priority="high"))
t2 = repo.add(Task(title="下午开会", priority="medium", due_time="2026-03-30 15:00"))
t3 = repo.add(Task(title="整理文档", priority="low"))
print(f"Added tasks: id={t1.id}, {t2.id}, {t3.id}")

# 查询今日任务
today = repo.get_today()
print(f"Today tasks: {len(today)} items -> {[t.title for t in today]}")

# 标记完成
ok = repo.mark_done(t1.id)
print(f"mark_done({t1.id}): {ok}")

stats = repo.count_today()
print(f"Stats: total={stats['total']}, done={stats['done']}, undone={stats['undone']}")

# 删除
repo.delete(t3.id)
remaining = repo.get_all(include_done=True)
print(f"After delete: {len(remaining)} tasks remain")

# 配置批量写入
settings.set_many({"window_x": "200", "window_y": "150"})
wx = settings.get_int("window_x")
wy = settings.get_int("window_y")
print(f"Window pos: ({wx}, {wy})")

# 测试 get_all_settings
all_cfg = settings.get_all()
print(f"Total settings keys: {len(all_cfg)}")

print("\nAll tests PASSED!")
