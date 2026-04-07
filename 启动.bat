@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo 正在检查 Python 环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.8 或以上版本
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo 正在检查依赖包...
python -c "import flask, requests, shapefile" >nul 2>&1
if errorlevel 1 (
    echo 正在安装依赖包，请稍候...
    pip install flask requests pyshp -q
    if errorlevel 1 (
        echo [错误] 依赖安装失败，请检查网络连接后重试
        pause
        exit /b 1
    )
    echo 依赖安装完成
)

echo 启动 SV_collect...
echo 浏览器将自动打开，如未打开请手动访问 http://127.0.0.1:5731
echo 关闭此窗口即可停止程序
echo.
python app.py
pause
