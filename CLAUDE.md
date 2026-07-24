# CLAUDE.md

本文件说明当前仓库中 PySide6 上位机的开发入口与架构边界。项目功能、环境、协议、测试、打包和 TODO 的完整说明以根目录 `README.md` 为准。

## 当前代码线

- 发布名称：`SoftHertz_AFDTR_Tool`。
- 设备工作区：`AFDTR`、`AFD01_QS`。
- 真实硬件型号分别为 **AFDT1024**（1024 发射阵列）和 **AFDR1024**（1024 接收阵列）；界面、日志和文档必须分别使用这两个型号。
- `AFDTR` 是工作区和产品包名，不是硬件型号；`devices/afdtr1024` 目录及 `AFDTR1024*` 类名仅是 AFDT1024/AFDR1024 的内部共用实现命名。
- 正式实现位于 `KauDC004A_TestTool/src/soft_hertz_tool`。
- `KauDC004A_TestTool/code` 仅保留旧启动/导入兼容层和本地打包脚本，不得继续承载新业务实现。

## 常用命令

在仓库根目录执行：

```bash
./run.sh

python -m pip install -e "KauDC004A_TestTool[dev]"
QT_QPA_PLATFORM=offscreen python -m pytest KauDC004A_TestTool/tests -q
QT_QPA_PLATFORM=offscreen python -m pytest \
  KauDC004A_TestTool/code/test_serial_improved.py \
  KauDC004A_TestTool/code/test_qs_features.py -q

cd KauDC004A_TestTool/code
python build_spec.py
```

模拟器入口：

```bash
soft-hertz-afdtr-sim <TX端口> <RX端口>
soft-hertz-qs-sim <QS端口> --baudrate 921600
```

## 架构边界

```text
app/registry -> workspaces -> devices/<device> -> shared
                                panel -> driver -> protocol/stream
```

- `app` 只负责应用、静态 workspace registry、工作区切换和统一生命周期。
- `workspaces` 只组合设备页面，并实现 `activate()` / `deactivate()` / `shutdown()`。
- 每个 `devices/<device>` 目录独立维护协议、流式拆帧、Driver、Panel；需要时增加模型、控件和模拟器。
- `shared` 提供串口线程、端口扫描、报文记录、异步日志、资源定位和共享控件，不得反向导入具体设备。
- Panel 只收集输入和展示状态，通过 Driver 语义接口操作设备，不手工拼帧或解析帧。
- Driver 独占串口会话并分派协议事件；协议模块保持纯函数，不依赖 Qt 控件或串口。
- 模拟器复用正式协议实现，不能维护第二套协议常量或校验算法。

## 并发与生命周期

- pyserial 对象只能由 `SerialThread.run()` 所在线程打开、读写和关闭；UI 通过有界发送队列提交字节，写入必须设置有限超时。
- Qt 控件只能在主线程更新；高频数据必须限频或批量刷新。
- 型号切换调用隐藏 workspace 的 `deactivate()`，断开串口并暂停页面定时器；进入前台后由 `activate()` 恢复。
- 只有 Driver 线程确认退出后才能销毁对象；快速重连时用连接代际过滤旧会话的延迟信号。
- 程序退出调用所有 workspace 的幂等 `shutdown()`；任一串口线程停止失败时取消关闭。
- 原始 TX、RX、DROP 事件统一转换为 `FrameRecord`，进入全局监视器和异步日志链路。

## 开发流程

1. 功能开发前建立 `docs/<feature>/plan.md` 和 `acceptance.md`。
2. 实现期间维护 `development.md`，记录设计决策、验证结果和未闭环的硬件/平台边界。
3. 协议变更必须先核对受控原件，并同步修改协议、模拟器、测试和文档。
4. 完成后运行正式包与兼容入口全量回归、离屏 UI 冒烟和与风险匹配的打包/硬件验证。
5. 模拟器和 Host 测试不能替代 Windows 产物或真实设备验收。

不要主动提交 Git。提交前不得包含虚拟环境、缓存、日志、`build/`、`dist/`、生成的 spec 或可执行文件。
