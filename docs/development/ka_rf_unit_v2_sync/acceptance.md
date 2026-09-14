# KA_RF_UNIT V2 同步验收标准

状态：用户已确认实施；2026-09-13 软件验收完成。A01..A12 在下述软件证据范围内 PASS，
不引用旧 OTA 草稿的通过数量，不代表真实设备或 Windows 验收。

## 软件验收

| 编号 | 可观察结果 |
|---|---|
| A01 | 独立协议向量验证 V2 帧、空 0x20、46 字节 A0，三段 u16 版本与负温度；长度、CRC、版本错误被拒绝，分片粘包与错误后恢复可用 |
| A02 | 0x10/0x16 固定/自由频率、0x11 临时及 0x48 持久衰减、内部 C5/C7 原功能回归，快照版本仍为 1 |
| A03 | 模拟器仅响应状态查询，无 0x30 主动发送；UI 查询周期只改变本地调度，不发旧 0x20 频率载荷 |
| A04 | 普通请求与 OTA 查询均单请求在途；超时可恢复，OTA 占用期间查询/扫描/设置不能混入原始传输 |
| A05 | BEGIN/ABORT/STATUS 空载荷；无 COMMIT 发送路径；A4 无候选/有候选/失败、last_result、非法阶段及长度全部覆盖 |
| A06 | 文件名 basename、target/版本/类型、大小上下界校验；CRC16-FALSE=29B1、CRC16-XMODEM=31C3，向量为 123456789 |
| A07 | 假时钟与接收端测试桩覆盖等 C、block0、数据块、序号回绕、双 EOT、末空包；CRC、重传序号和有效长度正确 |
| A08 | block0 响应等 10 秒；数据响应等 2 秒，每包最多重试 10 次；无进展 10 秒、原始总时长 120 秒；重复与错误输入不无限延长传输 |
| A09 | BEGIN 响应丢失不发文件，等首包窗口后查询；末 ACK 丢失不重传原始尾包，静默至少 200 ms 后恢复；CAN/传输失败等待设备退出原始模式 |
| A10 | 恢复查询单次超时 2 秒，约 1 秒间隔；覆盖 BUSY、PENDING、旧版本、断连、last_result 失败和目标 STABLE；同版本/期限届满不误报安装成功 |
| A11 | UI 经 Driver 语义接口操作；队列满、发送错误可见；重连过滤旧事件；取消、隐藏、关闭幂等且线程退出得到确认 |
| A12 | PSA 帧和 OTA 原始 TX/RX/DROP 在既有监视与日志可查，业务 UI 不跨线程更新 |

标准复验入口：

```sh
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/devices/test_ka_rf_unit*.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q src tests packaging
QT_QPA_PLATFORM=offscreen ./run.sh app --smoke
```

## 独立环境验收

- PASS：全项目 `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`：436 passed，16.07 秒。
- PASS：KA 专项 + PTY 集成：208 passed；执行参数为 `tests/devices/test_ka_rf_unit*.py tests/integration/test_ka_rf_unit_v2_serial.py`。
- PASS：compileall 与 git diff --check，退出 0。
- PASS：offscreen `./run.sh app --smoke` 及 macOS 原生 `./run.sh app --smoke`，退出 0；只证明主窗口开闭，不证明真实串口。
- PASS：真实 SerialThread + PTY，普通变频衰减设置/状态查询回读；OTA block0/data/双 EOT/末空包，
  故意丢最后 ACK、先 PENDING 后 STABLE，确认无 COMMIT，关闭时线程退出。
  macOS PTY 使用 38400：460800 的自定义波特率 ioctl 返回 errno 25；PTY 无物理线速，不能证明 460800 RS485 时序。
- PASS：客户控制与 OTA 两页 offscreen 1440×1050 截图人工检查，字段、警告、按钮及状态表无裁切。
- BLOCKED：Windows 原生 EXE 启动与操作，需 Windows 环境；macOS 和 pytest 不替代。
- BLOCKED：真机 RS485/Flash/Boot、上传复位及健康、丢包断电恢复、输出保持与 RF，需设备联调。
- 本阶段未执行真实刷机、Git 提交、推送、打标签或发布。
