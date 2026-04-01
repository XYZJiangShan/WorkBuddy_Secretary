"""
main.py - 桌面小秘书程序入口 v2

重要：所有 UI 层 import 必须在 QApplication 创建之后执行，
否则 QObject 子类（如 ThemeManager）会因无 Qt 上下文而崩溃。
"""

import logging
import sys
import os

os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

# ---- 数据层（无 Qt 依赖）----
from data.database import close_db
from data.task_repository import TaskRepository
from data.settings_repository import SettingsRepository

# ---- 服务层（无 Qt 依赖）----
from services.ai_service import AIService
from services.reminder_service import ReminderService
from services.pomodoro_service import PomodoroService
from services.hotkey_service import HotkeyService
from services.sync_service import SyncService

# ---- 日志 ----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("DeskSecretary")
    app.setApplicationDisplayName("桌面小秘书")
    app.setQuitOnLastWindowClosed(False)

    # ---- 主线程预热（必须在任何子线程启动前完成，防止 COM 冲突 0x8001010d）----
    # openai/httpx/ssl 首次初始化必须在主线程，否则子线程 COM 冲突崩溃
    try:
        import ssl
        ssl.create_default_context()        # 预热 SSL
        import httpx
        httpx.Client().close()              # 预热 httpx 连接池
        import openai                       # 预热 openai（触发所有子模块 import）
        import openai.types                 # 确保 types 子包全部加载
        logger.debug("主线程预热完成（SSL/httpx/openai）")
    except Exception as e:
        logger.warning("预热失败（不影响运行）: %s", e)

    # ---- UI 层（必须在 QApplication 之后 import！）----
    from ui.floating_window import FloatingWindow
    from ui.tray_icon import TrayIcon
    from ui.settings_dialog import SettingsDialog
    from ui.review_dialog import ReviewDialog
    from ui.theme import theme_manager

    # 全局 tooltip 样式
    app.setStyleSheet("""
        QToolTip {
            background: rgba(45, 43, 61, 0.97);
            color: #E8E5FF;
            border: 1px solid rgba(139,133,255,0.4);
            border-radius: 6px;
            padding: 5px 8px;
            font-family: "Microsoft YaHei";
            font-size: 11px;
        }
    """)

    # ---- 数据层 ----
    settings = SettingsRepository()
    settings.initialize()
    task_repo = TaskRepository()

    # ---- 主题初始化 ----
    saved_theme = settings.get("theme", "light")
    theme_manager.set_theme(saved_theme)

    # ---- 服务层 ----
    ai_service = AIService(settings)
    # 主线程预构建 AI 客户端（openai/httpx 首次初始化必须在主线程，否则子线程 COM 冲突崩溃）
    if ai_service.is_configured():
        try:
            ai_service._get_client()
            logger.debug("AI 客户端主线程预热完成")
        except Exception as e:
            logger.warning("AI 客户端预热失败（不影响运行）: %s", e)
    reminder_service = ReminderService(ai_service, settings)
    pomodoro_service = PomodoroService()
    hotkey_service = HotkeyService(
        hotkey=settings.get("hotkey_toggle_window", "alt+space")
    )
    sync_service = SyncService(settings)

    # 启动时从 GitHub 拉取（后台，不阻塞 UI）
    def _startup_pull():
        if sync_service.is_enabled():
            logger.info("启动同步：从 GitHub 拉取数据…")
            result = sync_service.pull_on_startup()
            if result.pulled:
                logger.info("启动同步：已从 GitHub 拉取最新数据")
            elif not result.success:
                logger.warning("启动同步失败: %s", result.message)
    QTimer.singleShot(2000, _startup_pull)  # 延迟 2 秒，等 Qt 事件循环稳定

    pomodoro_service.update_durations(
        focus_min=settings.get_int("pomodoro_focus_minutes", 25),
        short_min=settings.get_int("pomodoro_short_break_minutes", 5),
        long_min=settings.get_int("pomodoro_long_break_minutes", 15),
    )

    # ---- UI 层 ----
    main_window = FloatingWindow(
        settings, task_repo, ai_service, reminder_service, pomodoro_service
    )
    tray = TrayIcon()

    # ---- 窗口显示/隐藏逻辑 ----
    def show_window():
        main_window.show()
        main_window.raise_()
        tray.set_window_visible(True)

    def hide_window():
        main_window.hide()
        tray.set_window_visible(False)

    def toggle_window():
        if main_window.isVisible():
            hide_window()
        else:
            show_window()

    def quit_app():
        hotkey_service.stop()
        reminder_service.stop()
        sync_service.stop()
        # 退出时推送（同步，最多等 10 秒）
        if sync_service.is_enabled():
            logger.info("退出同步：推送数据到 GitHub…")
            try:
                sync_service.push_now()
            except Exception as e:
                logger.warning("退出同步失败: %s", e)
        close_db()
        app.quit()

    # ---- 连接信号 ----
    tray.show_window.connect(show_window)
    tray.hide_window.connect(hide_window)
    tray.quit_app.connect(quit_app)
    tray.trigger_reminder.connect(
        lambda: reminder_service.reminder_triggered.emit("🔔 手动提醒：休息一下，活动活动！")
    )
    hotkey_service.toggle_window.connect(toggle_window)
    hotkey_service.hotkey_error.connect(
        lambda msg: logger.warning("热键错误: %s", msg)
    )

    main_window.open_settings.connect(
        lambda: _open_settings(settings, ai_service, reminder_service,
                               pomodoro_service, hotkey_service, sync_service, main_window)
    )
    main_window.open_review.connect(
        lambda: _open_review(ai_service, task_repo, settings, main_window)
    )
    tray.open_settings.connect(
        lambda: _open_settings(settings, ai_service, reminder_service,
                               pomodoro_service, hotkey_service, sync_service, main_window)
    )

    # ---- 启动 ----
    tray.show()
    tray.set_window_visible(True)
    main_window.show()
    main_window.raise_()
    reminder_service.start()
    sync_service.start()   # 启动定时同步

    if settings.get_bool("hotkey_enabled", True):
        hotkey_service.start()

    if not ai_service.is_configured():
        QTimer.singleShot(500, lambda: _open_settings(
            settings, ai_service, reminder_service,
            pomodoro_service, hotkey_service, sync_service, main_window,
            first_run=True
        ))

    logger.info("桌面小秘书 v2 已启动（主题=%s）", saved_theme)
    return app.exec()


def _open_settings(settings, ai_service, reminder_service,
                   pomodoro_service, hotkey_service, sync_service, parent,
                   first_run: bool = False):
    from ui.settings_dialog import SettingsDialog
    dialog = SettingsDialog(settings, parent=parent)

    def on_saved():
        ai_service.reset()
        # 设置保存后在主线程重新预热客户端（避免子线程首次初始化 COM 冲突）
        if ai_service.is_configured():
            try:
                ai_service._get_client()
            except Exception:
                pass
        reminder_service.reload_settings()
        parent.apply_settings()
        pomodoro_service.update_durations(
            focus_min=settings.get_int("pomodoro_focus_minutes", 25),
            short_min=settings.get_int("pomodoro_short_break_minutes", 5),
            long_min=settings.get_int("pomodoro_long_break_minutes", 15),
        )
        if settings.get_bool("hotkey_enabled", True):
            hotkey_service.update_hotkey(
                settings.get("hotkey_toggle_window", "alt+space")
            )
        else:
            hotkey_service.stop()
        sync_service.reload_settings()   # 同步配置变更后重新加载
        logger.info("设置已保存并全部生效")

    dialog.settings_saved.connect(on_saved)
    if first_run:
        dialog.setWindowTitle("欢迎使用小秘书 - 请先配置 AI")
    dialog.raise_()
    dialog.activateWindow()
    dialog.exec()


def _open_review(ai_service, task_repo, settings, parent):
    from ui.review_dialog import ReviewDialog
    dialog = ReviewDialog(ai_service, task_repo, settings, parent=parent)
    dialog.exec()


if __name__ == "__main__":
    sys.exit(main())
