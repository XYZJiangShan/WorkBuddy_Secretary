"""test_dialogs_tray.py - 验证弹窗和托盘模块导入与实例化"""
import sys
sys.path.insert(0, ".")

from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)

# ---- 导入验证 ----
from ui.review_dialog import ReviewDialog
print("ReviewDialog import OK")

from ui.settings_dialog import SettingsDialog
print("SettingsDialog import OK")

from ui.tray_icon import TrayIcon, _make_default_icon, _load_icon
print("TrayIcon import OK")

# ---- 实例化验证 ----
from data.settings_repository import SettingsRepository
from data.task_repository import TaskRepository
from services.ai_service import AIService

settings = SettingsRepository()
settings.initialize()
task_repo = TaskRepository()
ai_svc = AIService(settings)

# SettingsDialog
sd = SettingsDialog(settings)
print(f"SettingsDialog() OK, size={sd.width()}x{sd.height()}")

# ReviewDialog
rd = ReviewDialog(ai_svc, task_repo, settings)
print(f"ReviewDialog() OK, size={rd.width()}")

# TrayIcon (需要检查系统是否支持托盘)
if not QApplication.primaryScreen():
    print("TrayIcon: 跳过（无屏幕）")
else:
    icon = _make_default_icon(32)
    print(f"default icon OK, null={icon.isNull()}")
    # 实例化 TrayIcon（不 show，避免依赖真实托盘）
    tray = TrayIcon()
    print(f"TrayIcon() OK, visible={tray.isVisible()}")

# ---- 测试托盘菜单信号 ----
signal_log = []
tray.show_window.connect(lambda: signal_log.append("show"))
tray.open_settings.connect(lambda: signal_log.append("settings"))
tray.quit_app.connect(lambda: signal_log.append("quit"))

tray.show_window.emit()
tray.open_settings.emit()
assert "show" in signal_log and "settings" in signal_log
print("TrayIcon signals OK")

# ---- set_window_visible ----
tray.set_window_visible(False)
assert tray._toggle_action.text() == "显示窗口"
tray.set_window_visible(True)
assert tray._toggle_action.text() == "隐藏窗口"
print("TrayIcon.set_window_visible() OK")

print("\nAll dialogs & tray tests PASSED!")
app.quit()
