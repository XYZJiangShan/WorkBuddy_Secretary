"""
test_reminder_service.py - ReminderService 功能验证

测试策略：
- 启动 QApplication 事件循环
- 将提醒间隔设置为 2 秒（极短），验证触发流程
- 用 QTimer.singleShot 在 5 秒后退出，检查信号是否触发
"""
import sys
import io
sys.path.insert(0, ".")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

from data.settings_repository import SettingsRepository
from services.ai_service import AIService
from services.reminder_service import ReminderService

app = QApplication(sys.argv)

settings = SettingsRepository()
settings.initialize()
# 设置极短间隔（2秒）用于快速测试
settings.set("reminder_interval_minutes", "0")  # 0分钟 = 即刻，实际用秒数重置

ai_svc = AIService(settings)
svc = ReminderService(ai_svc, settings)

# --- 收集信号事件 ---
events = {"ticks": [], "triggered": [], "refreshing": 0}

def on_tick(sec):
    events["ticks"].append(sec)
    print(f"  [tick] 剩余 {sec} 秒")

def on_triggered(text):
    events["triggered"].append(text)
    print(f"  [TRIGGERED] 文案: {text[:40]}...")

def on_refreshing():
    events["refreshing"] += 1
    print(f"  [cache_refreshing] 缓存补充触发 #{events['refreshing']}")

svc.countdown_tick.connect(on_tick)
svc.reminder_triggered.connect(on_triggered)
svc.cache_refreshing.connect(on_refreshing)

# 直接用 _reset_countdown 设 3 秒，不走完整 start
svc._reset_countdown(3)
print("已启动倒计时（3秒）...")

# 6 秒后检查并退出
def check_and_quit():
    print("\n--- 验证结果 ---")
    assert len(events["ticks"]) >= 2, f"tick 次数不足: {len(events['ticks'])}"
    print(f"tick 次数: {len(events['ticks'])} (>= 2) OK")

    assert len(events["triggered"]) >= 1, "提醒未触发！"
    print(f"triggered 次数: {len(events['triggered'])} (>= 1) OK")

    # 验证 seconds_left 在触发后重置
    assert svc.seconds_left > 0, "触发后应重置倒计时"
    print(f"触发后 seconds_left = {svc.seconds_left} (> 0) OK")

    # 验证历史记录写入
    history = svc.get_today_history()
    assert len(history) >= 1, f"提醒历史未写入: {history}"
    print(f"reminder_history 记录数: {len(history)} (>= 1) OK")

    # 验证 snooze
    svc.snooze(10)
    assert svc.seconds_left == 10, f"snooze 失败: {svc.seconds_left}"
    print("snooze(10) OK")

    # 验证 pause / resume
    svc.pause()
    assert not svc.is_running, "pause 后应为 False"
    svc.resume()
    assert svc.is_running, "resume 后应为 True"
    print("pause/resume OK")

    svc.stop()
    print("\nAll ReminderService tests PASSED!")
    app.quit()

QTimer.singleShot(6000, check_and_quit)
sys.exit(app.exec())
