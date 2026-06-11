@echo off
REM 一键运行 SoftHertz_AFDTR_Tool 上位机（Windows）
REM 自动创建虚拟环境、安装依赖并启动 GUI
REM
REM 用法:
REM   run.bat            启动上位机
REM   run.bat --update   强制重新安装依赖后启动
REM   run.bat --sim      启动设备模拟器（无硬件联调用）
setlocal enabledelayedexpansion

set "ROOT_DIR=%~dp0"
set "CODE_DIR=%ROOT_DIR%KauDC004A_TestTool\code"
set "REQ_FILE=%ROOT_DIR%KauDC004A_TestTool\requirements.txt"
set "VENV_DIR=%ROOT_DIR%.venv"

REM 解析参数
set "FORCE_UPDATE=0"
set "RUN_SIM=0"
for %%a in (%*) do (
  if "%%a"=="--update" set "FORCE_UPDATE=1"
  if "%%a"=="-u"       set "FORCE_UPDATE=1"
  if "%%a"=="--sim"    set "RUN_SIM=1"
)

REM 确认目录 / 分支
if not exist "%CODE_DIR%\main_qt6.py" (
  echo [X] 找不到 %CODE_DIR%\main_qt6.py
  echo     本脚本针对 dev_kaudc004a 分支，请确认已切换: git checkout dev_kaudc004a
  exit /b 1
)

REM 检查 Python
where python >nul 2>nul
if errorlevel 1 (
  echo [X] 未找到 Python，请先安装 Python 3.9+ 并加入 PATH
  exit /b 1
)

REM 创建虚拟环境（首次）
if not exist "%VENV_DIR%" (
  echo ^> 创建虚拟环境: %VENV_DIR%
  python -m venv "%VENV_DIR%"
  set "FORCE_UPDATE=1"
)

REM 激活
call "%VENV_DIR%\Scripts\activate.bat"

REM 安装依赖（首次或 --update）
if "%FORCE_UPDATE%"=="1" goto :install
if not exist "%VENV_DIR%\.deps_installed" goto :install
goto :launch

:install
echo ^> 安装依赖（%REQ_FILE%）...
python -m pip install --upgrade pip >nul
python -m pip install -r "%REQ_FILE%"
type nul > "%VENV_DIR%\.deps_installed"

:launch
cd /d "%CODE_DIR%"
if "%RUN_SIM%"=="1" (
  echo ^> 启动设备模拟器（Ctrl+C 退出）...
  python device_simulator.py
) else (
  echo ^> 启动上位机 SoftHertz_AFDTR_Tool...
  python main_qt6.py
)
