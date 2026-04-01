"""test_main_syntax.py - 验证 main.py 语法 + 全量模块导入"""
import sys, io
sys.path.insert(0, ".")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import ast

with open("main.py", encoding="utf-8") as f:
    src = f.read()
ast.parse(src)
print("main.py syntax OK")

# 验证所有模块可导入
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)

import main as m
print("main.py import OK")
print("_open_settings:", m._open_settings)
print("_open_review:  ", m._open_review)

print("\n全量模块导入 PASSED!")
app.quit()
