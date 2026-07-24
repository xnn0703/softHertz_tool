# 新增设备与工作区指南

## 1. 先确定扩展类型

新增功能前先判断属于哪一种：

| 场景 | 推荐做法 |
| --- | --- |
| 现有工作区增加一个独立串口设备 | 新增 `devices/<device>`，在现有 Workspace 组合 Panel |
| 现有设备增加命令或状态 | 修改该设备纵向切片，不新增 Workspace |
| 新产品模式需要独立页面组合与生命周期 | 新增 `devices/<device>` 和 `workspaces/<workspace>.py`，再注册 Workspace |
| 两个设备共用协议主体但存在稳定变体 | 共用 protocol/driver 基类或参数化实现，用明确 Enum 区分 |
| 新增 TCP/UDP 等传输方式 | 先设计 `shared/transport` 扩展和生命周期，不直接写入 Panel |

不要因为 UI 标题不同就复制整套设备代码，也不要为了“通用”把不稳定的设备差异提前抽象到共享层。

## 2. 建立计划与验收

在 `docs/development/<feature>/` 建立：

```text
plan.md
acceptance.md
development.md
```

至少明确：

- 公开设备名称和稳定 key；
- 加入现有 Workspace 还是新增 Workspace；
- 协议名称、版本和受控原件路径；
- 串口参数、命令、响应和超时；
- 数据速率与 UI 刷新目标；
- 模拟器范围；
- 错误、掉线和不支持功能的表现；
- 主机、模拟器、目标平台和真实硬件验收项；
- 明确不做的内容。

协议原件缺失或字段存在冲突时，先停止协议实现并完成确认。

## 3. 创建设备纵向切片

建议结构：

```text
src/soft_hertz_tool/devices/<device>/
├── __init__.py
├── protocol.py
├── stream.py
├── driver.py
├── panel.py
├── models.py       # 按需
├── widgets.py      # 按需
└── simulator.py    # 按需
```

对应测试：

```text
tests/devices/test_<device>.py
```

复杂设备可拆成多个测试文件，但生产模块和测试应保持可定位关系。

## 4. 实现 protocol.py

先完成不依赖 Qt 和串口的协议层：

1. 定义帧头、命令/地址、长度和校验；
2. 为物理字段定义单位、端序、符号、缩放、偏移和量化；
3. 为每个操作提供语义化构帧函数；
4. 对参数范围做显式校验；
5. 解析完整帧并返回语义字段；
6. 对设备变体使用 Enum 或明确参数，而不是散布布尔判断。

建议接口形态：

```python
def build_status_query(device_id: int) -> bytes:
    ...


def parse_response(frame: bytes) -> tuple[dict | None, str]:
    ...
```

禁止：

- 在 Panel 中拼接协议字节；
- 在 protocol 中读取控件或串口；
- 从抓包片段猜测未确认字段；
- 复制 simulator 专用协议常量。

## 5. 实现 stream.py

流式拆帧器应提供：

```python
class DeviceStreamParser:
    def feed(self, data: bytes) -> list[StreamEvent]:
        ...

    def reset(self) -> None:
        ...
```

`feed()` 接受任意大小字节块，并返回：

- 完整帧事件；
- 带原始字节和原因的丢弃事件。

测试分包、粘包、垃圾前缀、坏长度、坏校验、半个帧头和坏帧后的恢复。

## 6. 实现 driver.py

串口设备优先继承或组合 `shared.transport.SerialThread`。Driver 负责：

- 创建流式拆帧器；
- 处理接收字节；
- 调用 protocol 解析完整帧；
- 发布语义状态信号；
- 提供 `query_*`、`set_*` 等业务方法；
- 把 TX/RX/DROP 转换为 `FrameRecord`；
- 通过有界队列提交发送帧；
- 安全停止线程。

示意：

```python
class DeviceDriver(SerialThread):
    status_received = Signal(dict)
    frame_signal = Signal(object)

    @Slot(bytes)
    def handle_bytes(self, data: bytes) -> None:
        ...

    def query_status(self) -> bool:
        frame = protocol.build_status_query(...)
        return self.send_bytes(frame)
```

需要明确：

- 串口打开成功/失败信号；
- 发送队列满的处理；
- 命令超时；
- 断线后的状态；
- 快速重连的连接代际；
- `stop()` 的超时和返回值。

## 7. 实现 panel.py

Panel 负责用户交互：

- 使用 `SerialConnectionWidget` 管理端口、波特率和连接按钮；
- 将输入转换成 Driver 的语义方法参数；
- 在主线程显示状态、错误和超时；
- 将 Driver 的 `frame_signal` 向 Workspace 转发；
- 提供幂等的 `activate()`、`deactivate()`、`shutdown()`；
- 高频数据使用缓存和 QTimer 限频刷新。

Panel 不应：

- 直接创建 pyserial；
- 直接读写串口；
- 手工构造校验和；
- 保存流式接收缓冲；
- 在槽函数中 `sleep`；
- 在断开后继续接受旧 Driver 信号。

## 8. 增加模拟器

有明确设置/查询协议的设备应尽量提供模拟器：

1. 复用正式 protocol/stream；
2. 将设备状态内核与串口适配分离；
3. 支持配置端口、波特率和必要地址；
4. 设置后能够查询回读；
5. 模拟广播、目标回复、非法请求和超时；
6. 周期上报不突发补帧；
7. 可以在 pytest 中不打开真实串口测试状态内核。

没有模拟器时，应在 README 和验收边界中明确真实硬件是唯一闭环入口。

## 9. 加入 Workspace

### 加入现有 Workspace

在对应 Workspace 中：

1. 创建 Panel；
2. 加入布局；
3. 将 `panel.frame_signal` 连接到 `workspace.frame_signal`；
4. 在 `activate()`、`deactivate()`、`shutdown()` 中管理 Panel；
5. 测试任一 Panel 停止失败时 Workspace 返回失败。

### 新增 Workspace

新建 `src/soft_hertz_tool/workspaces/<workspace>.py`，然后：

1. 从 `workspaces/__init__.py` 导出；
2. 向静态 registry 增加唯一、稳定的 key、标题和工厂；
3. 验证首次创建、切换、切回和关闭；
4. 验证 QSettings 保存并恢复选择；
5. 验证 PyInstaller 能收集该模块和资源。

禁止在 `MainWindow` 使用 `if device_name == ...` 创建或关闭具体设备。

## 10. 接入监视与日志

所有设备事件使用共享 `FrameRecord`，至少填写：

- 公开设备型号；
- 端口或端点；
- `TX`、`RX` 或 `DROP`；
- 命令/地址的可读名称；
- 原始字节；
- 解析结果或丢弃原因。

新设备接入后，报文监视器应通过事件动态发现型号，不修改固定筛选列表。

## 11. 自动化测试清单

### 设备测试

- [ ] 每个构帧函数有受控正常向量；
- [ ] 参数上下限和非法输入；
- [ ] 响应字段、端序、缩放、符号和单位；
- [ ] 坏长度、坏校验、分包、粘包和垃圾字节；
- [ ] Driver 发布语义状态与 FrameRecord；
- [ ] 发送队列满、未连接发送和停止；
- [ ] Panel 输入、显示、超时和幂等关闭；
- [ ] 模拟器设置/回读闭环。

### 集成测试

- [ ] registry key 唯一；
- [ ] 工作区切换释放串口并暂停定时器；
- [ ] 快速重连过滤旧信号；
- [ ] 窗口关闭确认全部线程退出；
- [ ] 依赖方向没有反向导入；
- [ ] 源码与打包入口可以加载资源。

### 验证命令

```bash
QT_QPA_PLATFORM=offscreen python -m pytest -q
python -m compileall -q src tests packaging
git diff --check
```

## 12. 文档与发布同步

新增设备完成时同步更新：

- README 当前功能、目录、模拟器、限制和 TODO；
- `docs/protocols` 中的受控原件或可读说明；
- 架构文档中的工作区/设备关系；
- 验收边界中的硬件项目；
- `pyproject.toml` 的新依赖、命令或 package data；
- Windows 打包资源和 CI 验证。

只有主机测试通过时，不得把 Windows EXE、真实设备或长期稳定性标记为完成。

## 13. 新传输方式

当前只支持串口。若需要 TCP 或 UDP：

1. 先编写独立 plan 和 acceptance；
2. 在 `shared/transport` 定义传输契约；
3. 明确连接、监听、收发、超时、停止和线程归属；
4. 明确客户端/服务端、单播/广播等模式；
5. 让 Driver 依赖传输契约，而不是让 Panel 操作 socket；
6. 增加共享层并发、停止和异常恢复测试；
7. 验证不影响现有串口 Driver。

通用曲线功能应作为共享可视化组件单独设计，数据源与刷新频率必须解耦，不能直接让每个串口帧触发一次重绘。
