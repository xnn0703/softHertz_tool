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
set "APP_DIR=%ROOT_DIR%KauDC004A_TestTool"
set "SRC_DIR=%APP_DIR%\src"
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
if not exist "%SRC_DIR%\soft_hertz_tool\__main__.py" (
  echo [X] 找不到 %SRC_DIR%\soft_hertz_tool\__main__.py
  echo     请确认仓库完整且当前代码线包含 src\soft_hertz_tool
  exit /b 1
)

set "PYTHONPATH=%SRC_DIR%;%PYTHONPATH%"

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
goto :ensure_package

:install
echo ^> 安装依赖（%REQ_FILE%）...
python -m pip install --upgrade pip >nul
python -m pip install -r "%REQ_FILE%"
type nul > "%VENV_DIR%\.deps_installed"

:ensure_package
if not exist "%VENV_DIR%\Scripts\soft-hertz-tool.exe" goto :install_package
if not exist "%VENV_DIR%\Scripts\soft-hertz-afdtr-sim.exe" goto :install_package
if not exist "%VENV_DIR%\Scripts\soft-hertz-qs-sim.exe" goto :install_package
goto :launch

:install_package
echo ^> 注册 SoftHertz 可编辑包入口...
python -m pip install --no-deps -e "%APP_DIR%"
if errorlevel 1 exit /b 1

:launch
cd /d "%CODE_DIR%"
if "%RUN_SIM%"=="1" (
  echo ^> 启动设备模拟器（Ctrl+C 退出）...
  python device_simulator.py
) else (
  echo ^> 启动上位机 SoftHertz_AFDTR_Tool...
  cd /d "%ROOT_DIR%"
  python -m soft_hertz_tool
)
