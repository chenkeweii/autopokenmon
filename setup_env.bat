@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo  AutoPokemon 环境初始化脚本
echo ============================================================
echo.

:: ── 1. 找 Python ──────────────────────────────────────────────
set "PYEXE=%~dp0python\python.exe"

if not exist "%PYEXE%" (
    echo [错误] 找不到嵌入式 Python：%PYEXE%
    echo.
    echo 请先从 https://www.python.org/downloads/windows/ 下载
    echo Python 3.13.x embeddable package（64-bit），
    echo 解压全部内容到本目录的 python\ 文件夹，再重新运行本脚本。
    echo.
    pause
    exit /b 1
)

echo [OK] 找到 Python: %PYEXE%

:: ── 2. 解锁 site-packages（取消 python3xx._pth 中 import site 的注释）──
for %%F in ("%~dp0python\python3*._pth") do (
    set "PTHFILE=%%F"
)

if not defined PTHFILE (
    echo [警告] 未找到 python3xx._pth 文件，跳过 site-packages 解锁
) else (
    echo [INFO] 检测 _pth 文件: !PTHFILE!

    :: 检查是否已经启用
    findstr /C:"import site" "!PTHFILE!" > nul 2>&1
    if errorlevel 1 (
        echo [警告] _pth 文件中未找到 import site 行，可能需要手动检查
    ) else (
        :: 检查是否被注释掉了（以 # 开头）
        findstr /RC:"^#.*import site" "!PTHFILE!" > nul 2>&1
        if not errorlevel 1 (
            echo [INFO] 正在解锁 site-packages ...
            :: 用 PowerShell 替换注释行
            powershell -Command "(Get-Content '!PTHFILE!') -replace '^#\s*import site', 'import site' | Set-Content '!PTHFILE!'"
            echo [OK] site-packages 已解锁
        ) else (
            echo [OK] site-packages 已是解锁状态，无需修改
        )
    )
)

:: ── 3. 安装 pip ────────────────────────────────────────────────
"%PYEXE%" -c "import pip" > nul 2>&1
if not errorlevel 1 (
    echo [OK] pip 已安装，跳过
) else (
    echo [INFO] 正在安装 pip ...
    :: 下载 get-pip.py
    powershell -Command "Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile 'get-pip.py' -UseBasicParsing"
    if not exist "get-pip.py" (
        echo [错误] 下载 get-pip.py 失败，请检查网络连接
        pause
        exit /b 1
    )
    "%PYEXE%" get-pip.py
    del get-pip.py
    echo [OK] pip 安装完成
)

:: ── 4. 安装 Python 依赖 ────────────────────────────────────────
echo.
echo [INFO] 安装 requirements.txt 中的依赖包 ...
"%PYEXE%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [错误] 依赖安装失败，请查看上方错误信息
    pause
    exit /b 1
)
echo [OK] 依赖安装完成

:: ── 5. 安装 Playwright 浏览器 ─────────────────────────────────
echo.
echo [INFO] 安装 Playwright Chromium 浏览器内核 ...
echo [INFO] （首次下载约 200MB，请耐心等待）
set "PLAYWRIGHT_BROWSERS_PATH=%~dp0browsers"
"%PYEXE%" -m playwright install chromium
if errorlevel 1 (
    echo [错误] Playwright 浏览器安装失败
    pause
    exit /b 1
)
echo [OK] Playwright 安装完成

:: ── 完成 ──────────────────────────────────────────────────────
echo.
echo ============================================================
echo  初始化完成！现在可以运行 AutoPokemon.exe 了。
echo ============================================================
echo.
pause
