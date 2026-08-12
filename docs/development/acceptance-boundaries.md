# 测试结构与验收边界

## 1. 原则

SoftHertz Tool 的验证证据分层记录。低层证据不能替代高层证据：

```text
静态检查
  -> 主机单元/集成测试
    -> 模拟器闭环
      -> 目标操作系统源码/产物
        -> 真实设备功能
          -> 现场长稳与发布验收
```

“测试通过”必须说明测试对象、平台、版本、命令和结果。不能只写“已验证”。

## 2. 证据层级

| 层级 | 能证明 | 不能证明 |
| --- | --- | --- |
| 源码静态检查 | 模块可编译、依赖方向和仓库结构符合规则 | Qt 可启动、串口和协议行为正确 |
| 主机 pytest | 协议向量、流解析、Driver、Panel 和生命周期满足测试断言 | 客户 Windows、USB 驱动和真实硬件可用 |
| 模拟器闭环 | 主机侧构帧、解析、设置/回读和高频数据链路一致 | 设备固件、电气接口和真实时序一致 |
| macOS/Linux 运行 | 对应主机的 Qt、资源和虚拟串口链路可用 | Windows EXE 可加载 |
| Windows 原生产物 | EXE、Qt DLL、运行库、资源、日志和串口在该系统可用 | 真实设备所有命令正确 |
| 真实设备功能 | 指定设备、固件和串口配置完成命令闭环 | 长时间稳定、所有客户环境都可用 |
| 长稳/现场 | 指定时长和工况下性能、恢复和日志可接受 | 其他固件、系统或工况自动通过 |

## 3. 当前正式测试结构

唯一正式测试入口是根目录 `tests`：

```text
tests/
├── devices/
│   ├── test_kaudc004a.py
│   ├── test_afdtr1024.py
│   ├── test_afdtr1024_regression.py
│   └── test_afd01_qs.py
├── shared/
│   ├── test_transport.py
│   ├── test_observability.py
│   └── test_resources.py
└── integration/
    ├── test_application_identity.py
    ├── test_workspace_registry.py
    ├── test_dependency_boundaries.py
    ├── test_documentation_contract.py
    ├── test_entrypoint_smoke.py
    ├── test_entrypoints_and_packaging.py
    └── test_repository_layout.py
```

覆盖关系：

- 设备测试覆盖协议构帧/解析、流恢复、Driver、Panel、模拟器和设备业务回归；
- QS 测试覆盖构帧、A0/A1 解码、上报频率、流恢复、阵列配置、模拟器 100 Hz、日志监视、
  阵列网格、单请求约束和 UI 超时；
- 集成测试补充产品配置、模块与 PyInstaller 入口冒烟、打包参数/清理范围、生产代码 docstring、
  Workspace 切换/退出、依赖方向和仓库结构；
- 不维护第二套重复的兼容测试入口。

正式验证命令：

```bash
python -m pip install -e ".[dev]"
QT_QPA_PLATFORM=offscreen python -m pytest -q
python -m compileall -q src tests packaging
git diff --check
```

每次发布应记录实际 collected、passed、failed、skipped 数量，不在长期文档中用旧数量替代本次结果。
当前 `0.0.0` 是开发包版本；在版本单一来源落地前，tag、Release 和包元数据必须分别记录，
不能据 tag 名推断包版本。

## 4. 设备软件验收

### KaUDC004A

- [ ] CRC、固定长度、命令和响应解析自动化测试通过；
- [ ] 版本、温度、本振和衰减的正常/异常向量通过；
- [ ] 流式解析可以从垃圾字节、坏帧和粘包恢复；
- [ ] Driver 产生 TX/RX/DROP 和语义状态；
- [ ] Panel 断开和关闭可重复调用；
- [ ] 真实设备完成复位、查询与设置闭环；
- [ ] 温度换算规则由受控协议和设备回读确认。

### AFDT1024

- [ ] V2.2 构帧、地址、校验、量化和波束字段测试通过；
- [ ] 广播、具体 ID、`ID+0x80` 和多子阵测试通过；
- [ ] 查询 1/2 按 ID 合并；
- [ ] 模拟器完成波束、阵列、PA、极化和查询闭环；
- [ ] 真实 1024 发射阵列完成相同闭环；
- [ ] 实际波特率、固件版本和子阵拓扑已记录。

### AFDR1024

- [ ] V2.2 RX 地址、校验、量化和波束字段测试通过；
- [ ] 广播、具体 ID、`ID+0x80` 和多子阵测试通过；
- [ ] 查询 1/2 按 ID 合并；
- [ ] 模拟器完成波束、阵列、极化和查询闭环；
- [ ] 真实 1024 接收阵列完成相同闭环；
- [ ] 实际波特率、固件版本和子阵拓扑已记录。

### AFD01_QS

- [ ] `0x01`～`0x0B` 构帧和参数边界测试通过；
- [ ] `0xA0/0xA1` 解码、分包、粘包、坏校验和恢复通过；
- [ ] 100 Hz 上报统计、10 Hz UI、1 秒断流提示通过；
- [ ] 档位 1～5、8×8～16×16 子阵网格、64/100/144/196/256 启用数量和状态颜色通过；
- [ ] 单请求、3 秒超时和不支持固件降级通过；
- [ ] 模拟器持续流不突发补帧；
- [ ] 真实设备在 921600 下完成命令、持续 A0 和阵列回读；
- [ ] 真实设备完成长稳测试并记录丢帧、CPU、内存和日志轮转。

## 5. 生命周期验收

- [ ] 首次启动进入默认 Workspace；
- [ ] 最近选择可以恢复；
- [ ] 当前产品设置写入统一命名空间；
- [ ] 配置兼容迁移不删除原设置；
- [ ] 切换 Workspace 前停用旧页面；
- [ ] 隐藏页面串口释放、定时器暂停；
- [ ] Driver 停止失败时取消切换；
- [ ] 快速重连不接收旧连接代际的延迟信号；
- [ ] 窗口关闭确认所有串口线程退出；
- [ ] 日志线程完成队列写入并关闭；
- [ ] 重复 `deactivate()`/`shutdown()` 不产生异常。

## 6. 可观测性验收

- [ ] 每个设备产生公开型号正确的 TX/RX/DROP；
- [ ] 筛选型号由事件动态发现；
- [ ] 方向和文本筛选正确；
- [ ] 暂停、恢复、复制、清空和另存正确；
- [ ] UI 最多保留 10000 行；
- [ ] 100 ms 批量刷新不阻塞高频接收；
- [ ] 日志写入 `Documents/SoftHertz/SoftHertz_Tool/logs`；
- [ ] 单文件达到 50 MiB 后轮转；
- [ ] 轮转不自动删除已有日志；
- [ ] 日志不包含凭据或无关敏感信息。

## 7. Windows 产物验收

构建检查：

- [ ] Windows runner 从仓库根安装 `.[dev]`；
- [ ] 正式 pytest 全部通过；
- [ ] `packaging/build_windows.py` 成功；
- [ ] 输出 `dist/SoftHertz_Tool.exe`；
- [ ] Artifact 名为 `SoftHertz_Tool-windows`；
- [ ] EXE 包含 Qt Core/Gui/Widgets、运行库和 PNG/ICO；
- [ ] Release 资产可独立下载；
- [ ] 记录 EXE SHA256。

原生启动检查：

- [ ] 在干净 Windows 10 1809+ 或 Windows 11 启动；
- [ ] 不依赖开发机 Python、虚拟环境或源码目录；
- [ ] 窗口标题和图标正确；
- [ ] 两个 Workspace 均可创建和切换；
- [ ] 默认日志目录可创建；
- [ ] 可枚举并打开实际或虚拟 COM 口；
- [ ] 关闭后无残留进程；
- [ ] 杀毒/EDR 环境的单文件解包行为已验证或记录限制。

只看到 CI job 成功、Artifact 上传或本地非 Windows 打包，均不能勾选原生启动检查。

## 8. 发布记录最小内容

每个候选版本至少保存：

```text
版本/tag：
提交：
Python / PySide6 / PyInstaller：
pytest 命令与结果：
构建 workflow：
Artifact / Release URL：
EXE SHA256：
Windows 版本：
启动结果：
设备型号与固件：
串口参数：
测试时长：
日志/截图位置：
未完成项：
```

证据中不得包含客户凭据、私有令牌或未经授权的敏感数据。

## 9. 当前开放门槛

以下项目在取得对应证据前保持未完成：

- 干净 Windows 环境的当前 EXE 原生启动；
- KaUDC004A 真实设备完整闭环与温度规则确认；
- AFDT1024 真实设备 V2.2 多子阵闭环；
- AFDR1024 真实设备 V2.2 多子阵闭环；
- AFD01_QS 真实设备命令、阵列与 100 Hz 长稳；
- QS V1.7 受控协议原件逐字段复核；
- 日志总容量和保留策略。

主机或模拟器结果可以作为前置证据，但不能关闭这些门槛。
