"""
run_debug.py - 调试启动脚本
将所有崩溃/异常写入 crash.log，方便排查闪退原因
"""
import sys
import os
import traceback
import logging

# 日志同时写文件
log_path = os.path.join(os.path.dirname(__file__), "crash.log")
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(log_path, encoding="utf-8"),
        logging.StreamHandler(sys.stderr),
    ],
)

# 捕获未处理的 Python 异常
def _excepthook(exc_type, exc_value, exc_tb):
    msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    logging.critical("未捕获的异常:\n%s", msg)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"\n[CRASH] {msg}\n")

sys.excepthook = _excepthook

# 捕获 Qt 内部异常（PyQt6 会把 C++ 崩溃转成 Python 异常）
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox

def qt_message_handler(mode, context, message):
    level = {0: "DEBUG", 1: "WARNING", 2: "CRITICAL", 3: "FATAL", 4: "INFO"}.get(mode.value, "?")
    logging.warning("[Qt %s] %s (%s:%s)", level, message, context.file, context.line)

from PyQt6.QtCore import qInstallMessageHandler
qInstallMessageHandler(qt_message_handler)

# ---------- 启动主程序 ----------
print(f"调试日志写入: {log_path}")
print("启动中，请操作界面触发崩溃，崩溃信息会记录到 crash.log")

try:
    sys.path.insert(0, os.path.dirname(__file__))
    import main as app_main
    sys.exit(app_main.main())
except Exception:
    logging.critical("main() 抛出异常:\n%s", traceback.format_exc())
    raise
