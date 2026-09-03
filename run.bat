@echo off
REM SoftHertz Tool 一键入口（Windows）
setlocal EnableExtensions DisableDelayedExpansion

set "ROOT_DIR=%~dp0"
set "VENV_DIR=%ROOT_DIR%.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "FORCE_UPDATE=0"
set "MODE=app"
set "MODE_SELECTED=0"
set "FORWARD_ARGS="

:parse_args
if "%~1"=="" goto :setup
if /I "%~1"=="--update" (
  set "FORCE_UPDATE=1"
  shift
  goto :parse_args
)
if /I "%~1"=="-u" (
  set "FORCE_UPDATE=1"
  shift
  goto :parse_args
)
if "%MODE_SELECTED%"=="1" goto :collect_args
if /I "%~1"=="app" (
  set "MODE=app"
  set "MODE_SELECTED=1"
  shift
  goto :parse_args
)
if /I "%~1"=="afdtr-sim" (
  set "MODE=afdtr-sim"
  set "MODE_SELECTED=1"
  shift
  goto :parse_args
)
if /I "%~1"=="qs-sim" (
  set "MODE=qs-sim"
  set "MODE_SELECTED=1"
  shift
  goto :parse_args
)
if /I "%~1"=="ka-rf-sim" (
  set "MODE=ka-rf-sim"
  set "MODE_SELECTED=1"
  shift
  goto :parse_args
)
if /I "%~1"=="--help" goto :usage
if /I "%~1"=="-h" goto :usage
goto :collect_args

:collect_args
if "%~1"=="" goto :setup
set "FORWARD_ARGS=%FORWARD_ARGS% "%~1""
shift
goto :collect_args

:setup
if not exist "%ROOT_DIR%pyproject.toml" (
  echo [X] 当前目录不是完整的 SoftHertz Tool 仓库: %ROOT_DIR%
  exit /b 1
)
if not exist "%ROOT_DIR%src\soft_hertz_tool\__main__.py" (
  echo [X] 找不到 src\soft_hertz_tool\__main__.py
  exit /b 1
)

where python >nul 2>nul
if errorlevel 1 (
  echo [X] 未找到 Python，请先安装 Python 3.9+ 并加入 PATH
  exit /b 1
)

if not exist "%VENV_PYTHON%" (
  echo ^> 创建虚拟环境: %VENV_DIR%
  python -m venv "%VENV_DIR%"
  if errorlevel 1 exit /b 1
  set "FORCE_UPDATE=1"
)

if "%FORCE_UPDATE%"=="1" goto :install
if not exist "%VENV_DIR%\.deps_installed" goto :install

REM editable install 含绝对源码路径；仓库移动或改名后必须重新注册。
"%VENV_PYTHON%" -m pip install --quiet --no-deps --editable "%ROOT_DIR%."
if errorlevel 1 exit /b 1
goto :launch

:install
echo ^> 从仓库根目录安装依赖和入口...
"%VENV_PYTHON%" -m pip install --upgrade pip
if errorlevel 1 exit /b 1
"%VENV_PYTHON%" -m pip install --editable "%ROOT_DIR%."
if errorlevel 1 exit /b 1
type nul > "%VENV_DIR%\.deps_installed"

:launch
cd /d "%ROOT_DIR%"
if /I "%MODE%"=="afdtr-sim" (
  echo ^> 启动 AFDT1024/AFDR1024 模拟器（Ctrl+C 退出）...
  "%VENV_PYTHON%" -m soft_hertz_tool.devices.afdtr1024.simulator %FORWARD_ARGS%
  exit /b
)
if /I "%MODE%"=="qs-sim" (
  echo ^> 启动 AFD01_QS 模拟器（Ctrl+C 退出）...
  "%VENV_PYTHON%" -m soft_hertz_tool.devices.afd01_qs.simulator %FORWARD_ARGS%
  exit /b
)
if /I "%MODE%"=="ka-rf-sim" (
  echo ^> 启动 KA_RF_UNIT 模拟器（Ctrl+C 退出）...
  "%VENV_PYTHON%" -m soft_hertz_tool.devices.ka_rf_unit.simulator %FORWARD_ARGS%
  exit /b
)

echo ^> 启动 SoftHertz Tool...
"%VENV_PYTHON%" -m soft_hertz_tool %FORWARD_ARGS%
exit /b %ERRORLEVEL%

:usage
echo 用法:
echo   run.bat [--update] [app] [应用参数...]
echo   run.bat [--update] afdtr-sim [TX端口] [RX端口] [模拟器参数...]
echo   run.bat [--update] qs-sim ^<QS端口^> [模拟器参数...]
echo   run.bat [--update] ka-rf-sim ^<KaRF端口^> [模拟器参数...]
echo.
echo 模式:
echo   app         启动 SoftHertz Tool（默认）
echo   afdtr-sim   启动 AFDT1024/AFDR1024 双串口模拟器
echo   qs-sim      启动 AFD01_QS 串口模拟器
echo   ka-rf-sim   启动 KA_RF_UNIT 串口模拟器
echo.
echo 选项:
echo   --update, -u  更新依赖并重新注册 editable install
echo   --help, -h    显示本帮助
exit /b 0
