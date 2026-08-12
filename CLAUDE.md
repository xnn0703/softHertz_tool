# SoftHertz Tool 开发约束

本文件给出仓库级开发边界。项目功能、安装、测试、打包和 TODO 以根目录 `README.md` 为准；详细架构与规范位于 `docs/architecture` 和 `docs/development`。

## 项目身份

- 产品显示名：`SoftHertz Tool`。
- Windows 产物：`SoftHertz_Tool.exe`。
- 正式 Python 包：`src/soft_hertz_tool`。
- 工作区：`AFDTR`、`AFD01_QS`。
- `AFDT1024` 是 1024 发射阵列，`AFDR1024` 是 1024 接收阵列。
- `AFDTR` 只表示工作区；`devices/afdtr1024` 与 `AFDTR1024*` 只表示 TX/RX 共用实现。
- 正式业务实现不得放在 `packaging`、`tests` 或仓库根脚本中。

## 常用命令

在仓库根目录执行：

```bash
python -m pip install -e ".[dev]"
QT_QPA_PLATFORM=offscreen python -m pytest -q
python -m compileall -q src tests packaging
python -m soft_hertz_tool
```

模拟器：

```bash
soft-hertz-afdtr-sim <TX端口> <RX端口> --ids 1,2,3 --baudrate 460800
soft-hertz-qs-sim <QS端口> --baudrate 921600
```

Windows 打包：

```bat
python packaging\build_windows.py
```

输出为 `dist/SoftHertz_Tool.exe`。

## 依赖边界

```text
app -> workspaces -> devices -> shared
                         panel -> driver -> protocol/stream
```

- `app` 负责应用入口、静态 workspace registry、工作区切换和统一退出。
- `workspaces` 只组合设备 Panel，并实现 `activate()`、`deactivate()`、`shutdown()`。
- `devices/<device>` 维护协议、流式拆帧、Driver、Panel；按需增加 models、widgets、simulator。
- `shared` 提供串口线程、端口扫描、报文记录、异步日志、资源定位和共享控件，不得反向导入具体设备。
- Panel 通过 Driver 语义接口操作设备，不手工构帧或拆帧。
- Driver 管理串口会话和协议事件，不创建业务控件。
- protocol/stream 保持纯逻辑，不依赖 Qt 控件或 pyserial。
- 模拟器复用正式协议模块，不复制协议常量、字段偏移或校验算法。
- 新工作区通过静态 registry 注册，不在 `MainWindow` 增加设备特判。

依赖边界由 `tests/integration/test_dependency_boundaries.py` 检查。

## 并发与生命周期

- pyserial 对象只能由所属 `SerialThread` 打开、读写和关闭。
- UI 通过有界发送队列提交字节；串口写入必须设置有限超时。
- Qt 控件只能在主线程更新；高频数据必须限频或批量刷新。
- 隐藏工作区必须停止页面定时器并释放串口。
- 线程未确认退出时不得销毁 Driver、切换工作区或关闭窗口。
- 快速重连必须用连接代际过滤旧会话的延迟信号。
- `deactivate()` 和 `shutdown()` 必须可重复调用，并明确返回停止结果。
- 原始 `TX`、`RX`、`DROP` 事件统一转换为 `FrameRecord`。

## 功能开发流程

1. 非简单功能开始前，在 `docs/development/<feature>/` 建立 `plan.md` 和 `acceptance.md`。
2. 明确目标、非目标、受控协议版本、风险、验收命令和硬件/平台门槛。
3. 实现过程中维护 `development.md`，只记录仍然有效的设计决策、验证结果和未闭环项。
4. 协议变更同步修改 protocol、stream、driver、simulator、tests 和协议说明。
5. 完成后逐项对照 plan 与 acceptance review，并运行与风险匹配的测试。
6. 更新 README 的功能、限制和 TODO；删除已失效的临时说明。

模拟器或主机测试不能替代 Windows 产物和真实设备验收。

## 编码与提交

- Python 目标版本为 3.9+，4 空格缩进，新增公共接口使用类型注解。
- PySide6 槽函数使用 `@Slot`，用户可见文本和注释优先使用中文。
- 修复缺陷先增加可复现测试，再修改实现。
- 协议字段必须注明端序、缩放、偏移、校验范围和物理单位。
- 不提交 `.venv`、缓存、日志、`build/`、`dist/`、生成的 spec、压缩包或可执行文件。
- 不在源码、设置、日志或提交中保存口令、令牌和客户敏感数据。
- Git 提交使用 `type(scope): 中文描述`；未经明确要求不要主动提交。

## 当前能力边界

当前只实现串口通信，不支持 DEBUG 通用设备页面、TCP、UDP、广播通信和通用多通道曲线。需要这些能力时，应按现有设备与共享组件边界重新设计并建立独立验收标准。
