# 上位机可扩展架构重构验收标准

## 1. 结构验收

- [x] 存在可安装/可导入的 `soft_hertz_tool` 包和 `python -m soft_hertz_tool` 入口。
- [x] 共享层不导入具体设备模块。
- [x] KaUDC004A、AFDT1024/AFDR1024 共用实现、AFD01_QS 均有独立设备目录。
- [x] 界面、日志和文档分别使用 AFDT1024（1024 发射阵列）、AFDR1024（1024 接收阵列）；`AFDTR` 仅作为工作区/产品包名，`devices/afdtr1024` 与 `AFDTR1024*` 仅作为内部共用实现命名。
- [x] 协议、流式拆帧、Driver、Panel 和 Workspace 职责分离。
- [x] 主窗口仅通过静态 registry 创建 workspace，不硬编码逐个设备实例。
- [x] 报文监视器型号筛选由设备事件动态生成，不硬编码设备型号列表。
- [x] 旧脚本入口保留薄兼容层并在 README 中给出迁移方式。

## 2. 行为验收

- [x] AFDTR 工作区仍包含 KaUDC004A、AFDT1024、AFDR1024 三个独立串口面板。
- [x] AFDT1024/AFDR1024 多 ID、广播、`ID+0x80`、查询 1/2 合并和量化频率波束计算无变化。
- [x] AFD01_QS 0x01～0x0B、0xA0、0xA1、100 Hz 接收、10 Hz UI、阵列超时和可视化无变化。
- [x] 型号切换会断开隐藏 workspace 的串口并暂停页面定时器，停止失败时取消切换。
- [x] 窗口关闭会统一停止全部 workspace 和全局日志线程，停止失败时取消关闭。
- [x] 全局报文监视的 TX/RX/DROP、筛选、复制、另存和轮转行为无变化。
- [x] 模拟器复用正式协议能力，配置后回读闭环保持通过。

## 3. 自动化验收

- [x] 原 75 项测试保持通过。
- [x] 新包结构 108 项测试和兼容入口测试通过。
- [x] `python -m compileall` 覆盖全部新生产模块和兼容入口。
- [x] `QT_QPA_PLATFORM=offscreen` 下可创建主窗口、多次切换两个 workspace 并正常关闭。
- [x] QS 模拟器 30 秒持续流保持约 100 Hz、无突发补帧，报文与异步日志回归通过。
- [x] `git diff --check` 通过。

## 4. 运行与打包验收

- [x] macOS/Linux `run.sh` 和 Windows `run.bat` 指向新包入口并注册模拟器命令。
- [x] `code/main_qt6.py` 兼容入口仍可启动。
- [x] 本地 PyInstaller 能收集全部设备、registry 和资源并启动主窗口。
- [x] Windows workflow 使用新包入口并执行正式/兼容回归，发布产物名仍为 `SoftHertz_AFDTR_Tool.exe`。

## 5. 硬件验收边界

- [ ] KaUDC004A 真实设备完成复位、版本、温度、本振和衰减闭环。
- [ ] AFDT1024 和 AFDR1024 真实设备完成 V2.2 多 ID 配置及查询闭环。
- [ ] AFD01_QS 真实设备在 921600 下完成持续 A0、0x01～0x0B 和 A1 阵列回读。
- [ ] Windows 实际 EXE 在干净机器完成启动、串口和日志验证。

> 前四节软件验收通过不自动勾选第五节；硬件和 Windows 现场证据缺失时必须明确保持未完成。
