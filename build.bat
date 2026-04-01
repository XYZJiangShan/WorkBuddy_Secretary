@echo off
chcp 65001 > nul
echo ===================================
echo   桌面小秘书 - 打包为 exe
echo ===================================

REM 安装依赖
echo [1/3] 检查并安装依赖...
py -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo 依赖安装失败，请检查网络或 Python 环境
    pause
    exit /b 1
)

REM 创建 assets 目录（若不存在）
if not exist assets mkdir assets

REM 清理上次打包缓存（可选）
if exist build rmdir /s /q build
if exist dist\DeskSecretary.exe del /f dist\DeskSecretary.exe

REM 执行 PyInstaller 打包
echo [2/3] 开始打包（约需 1-3 分钟）...
py -m PyInstaller ^
    --onefile ^
    --windowed ^
    --name DeskSecretary ^
    --add-data "assets;assets" ^
    --add-data "data;data" ^
    --add-data "services;services" ^
    --add-data "ui;ui" ^
    --hidden-import PyQt6.QtCore ^
    --hidden-import PyQt6.QtWidgets ^
    --hidden-import PyQt6.QtGui ^
    --hidden-import PyQt6.QtMultimedia ^
    --hidden-import openai ^
    --hidden-import keyboard ^
    --hidden-import sqlite3 ^
    --hidden-import httpx ^
    --hidden-import httpcore ^
    --collect-all PyQt6 ^
    --collect-all openai ^
    main.py

if errorlevel 1 (
    echo.
    echo 打包失败！请查看上方错误信息
    pause
    exit /b 1
)

echo.
echo [3/3] 打包完成！
echo ================================
echo 输出文件：dist\DeskSecretary.exe
echo ================================
echo.
echo 提示：
echo   - 首次运行请配置 AI API Key（程序自动弹出设置窗口）
echo   - 数据存储在 %%APPDATA%%\DeskSecretary\
echo   - 图片/视频附件存储在 %%APPDATA%%\DeskSecretary\attachments\
echo.
pause
