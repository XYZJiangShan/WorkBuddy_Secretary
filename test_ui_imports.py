"""test_ui_imports.py - 验证 UI 层三个模块可正常导入"""
import sys
sys.path.insert(0, ".")

from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)

from ui.reminder_banner import ReminderBanner
print("ReminderBanner import OK")

from ui.task_list_widget import TaskListWidget, TaskItemWidget, ParseResultCard
print("TaskListWidget import OK")

from ui.floating_window import FloatingWindow, CountdownProgressBar, _ProgressBarInner
print("FloatingWindow import OK")

# 快速实例化测试（不 show）
banner = ReminderBanner()
print("ReminderBanner() instance OK")

task_list = TaskListWidget()
print("TaskListWidget() instance OK")

progress = CountdownProgressBar()
progress.update_progress(1500, 2700)
print("CountdownProgressBar.update_progress() OK")

from data.settings_repository import SettingsRepository
from data.task_repository import TaskRepository
from services.ai_service import AIService
from services.reminder_service import ReminderService

settings = SettingsRepository()
settings.initialize()
task_repo = TaskRepository()
ai_svc = AIService(settings)
reminder_svc = ReminderService(ai_svc, settings)

win = FloatingWindow(settings, task_repo, ai_svc, reminder_svc)
print("FloatingWindow() instance OK")
print(f"  window size: {win.width()}x{win.height()}")
print(f"  collapsed: {win._collapsed}")

print("\nAll UI import & instance tests PASSED!")
app.quit()
