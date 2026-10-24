@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [1/2] 首次运行，正在创建虚拟环境...
    python -m venv .venv
    if errorlevel 1 (
        echo 创建失败：请先安装 Python 3.10+ 并加入 PATH
        pause
        exit /b 1
    )
    echo [2/2] 安装依赖...
    .venv\Scripts\python.exe -m pip install -q --upgrade pip
    .venv\Scripts\python.exe -m pip install -q -r requirements.txt
)

echo.
echo 启动 StudyBuddy ... 浏览器会自动打开
start "" http://127.0.0.1:8787
.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8787
pause
