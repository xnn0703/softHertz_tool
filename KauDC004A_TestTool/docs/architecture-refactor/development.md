# 上位机可扩展架构重构开发记录

## 基线

- 分支：`feat/afdtr-v2.1-multi-subarray`
- 实施日期：2026-07-22
- 重构前自动化基线：`75 passed`
- 发布产物名：`SoftHertz_AFDTR_Tool`
- 既有 AFD01_QS、报文监视和协议行为均纳入迁移范围，不改变受控协议语义。

## 命名决策

- 真实硬件型号分别为 **AFDT1024**（1024 发射阵列）和 **AFDR1024**（1024 接收阵列），界面、日志和文档分别使用对应型号。
- `AFDTR` 继续作为工作区和产品包名，不表示硬件型号；workspace key 仍为 `AFDTR`、`AFD01_QS`。
- `devices/afdtr1024` 目录、`AFDTR1024*` 类名及 TX/RX variant 仅用于 AFDT1024/AFDR1024 的内部共用实现，不表示硬件型号。
- 报文监视器按设备区分 `KaUDC004A`、`AFDT1024`、`AFDR1024`、`AFD01_QS`。

## 实施结果

| 阶段 | 状态 | 结果 |
| --- | --- | --- |
| 计划与验收文档 | 已完成 | 已建立并更新 plan、acceptance、development |
| 正式 Python 包 | 已完成 | `pyproject.toml`、`src/soft_hertz_tool`、模块入口和 console scripts |
| 共享基础设施 | 已完成 | 有界串口队列、有限写超时、停止确认、端口扫描、报文监视、异步日志、资源与连接控件 |
| 设备纵向迁移 | 已完成 | KaUDC004A、AFDT1024/AFDR1024 共用实现、AFD01_QS 独立 protocol/stream/driver/panel；模拟器复用正式协议 |
| Workspace/Registry | 已完成 | 静态 registry、统一 activate/deactivate/shutdown、隐藏页面定时器暂停 |
| 会话生命周期加固 | 已完成 | 连接状态机、旧会话代际过滤、阻塞 I/O 取消、两阶段关闭、停止失败时禁止切换/关闭 |
| 入口/打包迁移 | 已完成 | run 脚本、兼容入口、稳定 PyInstaller 入口和 Windows workflow |
| 软件验收 | 已完成 | pytest、compileall、边界检查、持续流、源码/兼容入口、macOS 打包产物冒烟 |
| 硬件与 Windows 实机验收 | 待完成 | 需要真实设备、Windows runner 产物和干净 Windows 机器证据 |

## 关键边界

1. `shared` 不导入具体设备；协议和流式解析不依赖 Qt 控件或串口。
2. Panel 只调用 Driver 语义接口；构帧、解析和串口会话留在设备纵向模块内。
3. pyserial 对象由后台线程打开、读写和关闭；UI 只向有界队列提交不可变字节。
4. 串口停止先设置退出标志并取消阻塞读写，只有 `QThread.wait()` 确认退出后才释放 Driver。
5. 快速断开/重连使用连接代际过滤旧 Driver 已排队的状态、速率、日志和延迟查询。
6. workspace 切换停止隐藏页面串口与定时器；最终退出才关闭全局异步日志。
7. 最终关闭先对全部 workspace 执行可恢复的 deactivate，全部成功后才标记永久 shutdown，避免部分页面失活。
8. 正式代码只位于 `src/soft_hertz_tool`；`code/` 中的旧模块只作为兼容入口。

## 软件验证记录

| 验证项 | 结果 |
| --- | --- |
| 正式包测试 | `108 passed`，连续 3 轮通过 |
| 旧入口兼容回归 | `75 passed` |
| Python 编译检查 | `python -m compileall -q` 通过 |
| 依赖边界检查 | shared→device、protocol/stream→Qt/serial 违规数为 0 |
| 离屏 UI | 主窗口创建、AFDTR/QS 多次切换、隐藏定时器暂停/恢复、幂等关闭通过 |
| 阻塞写停止 | 模拟阻塞 `write()`，`cancel_write()`、线程退出和 stop-before-start 回归通过 |
| QS 30 秒持续流 | 30.000 秒、3000 帧、99.999 Hz；间隔 9.561～10.487 ms |
| 一键脚本 | `run.sh` 自动补注册 `soft-hertz-tool`、AFDTR/QS 模拟器命令并成功启动源码 UI |
| 模拟器命令 | 两个 console script 的 `--help` 通过 |
| 本地 PyInstaller | macOS arm64 构建完成，产物离屏运行 20 秒仍存活 |
| 生成物隔离 | spec/work 输出到忽略的 `KauDC004A_TestTool/build/pyinstaller`，未继续改写历史 tracked build |
| 差异格式检查 | `git diff --check` 通过 |

## 未闭环边界

- Windows workflow 配置已更新，但当前工作区没有实际 Actions 运行结果和 Windows EXE 启动证据。
- KaUDC004A、AFDT1024、AFDR1024、AFD01_QS 均未在本轮结构重构后完成真实设备闭环。
- macOS PyInstaller 6.20 提示 onefile 与 `.app` 组合将在 PyInstaller 7 中不再支持；Windows onefile 目标不受该警告直接影响，macOS 后续应改为 onedir 或仅生成裸可执行文件。
- 仓库历史上已跟踪的 `code/build/**` 和旧 spec 尚未移除；新构建不再修改它们，清理工作保留在 README TODO。

## 开发约束

- 不在结构重构中改变受控协议字段、端序、校验和物理量算法。
- 没有真实硬件或 Windows 证据时，不将对应验收标记为完成。
- 后续新增设备从 plan 和 acceptance 开始，并同步维护测试、模拟器和 README。
- 不主动提交 Git；生成物、日志、虚拟环境和缓存不得进入提交范围。
