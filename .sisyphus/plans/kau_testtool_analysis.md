# KauDC004A_TestTool (SoftHertz_AFDTR_Tool) - 深度分析计划

## 一、工程概述

### 1.1 项目基本信息
| 项目 | 内容 |
|------|------|
| **项目名称** | KauDC004A_TestTool / SoftHertz_AFDTR_Tool |
| **语言** | Python 3.x |
| **GUI框架** | Tkinter |
| **串口库** | pyserial |
| **打包工具** | PyInstaller |
| **代码行数** | main.py(1338) + afdt1024_protocol.py(399) + protocol.py(29) ≈ 1766行 |

### 1.2 项目结构
```
1-project_upper/
├── KauDC004A_TestTool/
│   └── code/
│       ├── main.py              # 主程序入口 (Tkinter GUI)
│       ├── protocol.py          # KaUDC004A遗留协议 (0xAA55帧)
│       ├── afdt1024_protocol.py # AFDT/AFDR 1024阵列协议 (0x50帧)
│       ├── test_serial_improved.py
│       ├── build.spec           # PyInstaller配置
│       └── SoftHertz_AFDTR_Tool.exe  # 打包后的可执行文件
└── DOC/
    ├── AFDT1024_TX_Protocol.md  # TX设备协议规范
    ├── AFDR1024_RX_Protocol.md  # RX设备协议规范
    ├── 上位调试软件需求.txt      # 需求文档
    └── 修改记录.txt             # 版本历史
```

### 1.3 支持的设备
| 设备 | 协议 | 波特率 | 主要功能 |
|------|------|--------|----------|
| KaUDC004A | Legacy (0xAA55) | 115200 | 本振设置、衰减设置、状态查询 |
| Ka1024_TX | AFDT1024 (PSA) | 460800 | 波束设置、极化设置、PA使能、状态查询 |
| Ka1024_RX | AFDR1024 (PSA) | 460800 | 波束设置、极化设置、状态查询 |

### 1.4 AFDT1024协议帧格式 (关键)

**帧结构**: `[HEADER(3)][ID(1)][LEN(1)][DATA(LEN)][CHECKSUM(1)]`

| 字段 | 长度 | 说明 |
|------|------|------|
| HEADER | 3 Byte | 固定 `0x50 0x53 0x41` (ASCII "PSA") |
| ID | 1 Byte | 子阵ID |
| LEN | 1 Byte | DATA长度 |
| DATA | N Byte | 数据区 |
| CHECKSUM | 1 Byte | 前面所有字节求和取低8位 |

**关键发现**:
- **状态查询回复帧中没有ADDR字段**！回复帧的DATA直接就是状态数据
- 设备**不会主动上报**，只在收到指令后回复
- 配置指令成功时，设备返回**原帧回显**

### 1.5 软件架构
```
┌─────────────────────────────────────────────────────────────┐
│                      SerialTool (root)                       │
│  ┌─────────────────┬──────────────────┬─────────────────┐   │
│  │ DeviceController │ AFDT1024Controller│ AFDR1024Controller│  │
│  │   (KaUDC004A)    │   (Ka1024_TX)    │   (Ka1024_RX)     │  │
│  └────────┬────────┴────────┬─────────┴────────┬──────────┘  │
│           │                 │                   │              │
│           └─────────────────┴───────────────────┘              │
│                             │                                  │
│              ┌──────────────┴───────────────┐                │
│              │     read_thread (daemon)      │                │
│              │  串口接收 + 帧解析 + UI更新    │                │
│              └───────────────────────────────┘                │
└─────────────────────────────────────────────────────────────┘
```

---

## 二、已识别的缺陷

### 🔴 缺陷1: 状态查询帧解析逻辑错误 (严重)

**问题描述**: 
> "状态查询帧只解析发送状态查询后的那一帧回复帧，解析出设备状态，我看现在每一个数据帧都会当成状态查询帧的回复帧来解析，导致状态出错"

**根本原因分析**:

根据协议和实际日志分析：

1. **状态查询回复帧结构** (TX: LEN=6, RX: LEN=5)
   - TX回复: `[Rev][State][SysVcc][SysTemp][ATT_TC][MCU_VER]` (6字节)
   - RX回复: `[Rev][SysVcc][SysTemp][ATT_TC][MCU_VER]` (5字节)
   - **回复帧中没有ADDR字段**，无法通过ADDR判断是否是状态回复

2. **设备行为**: 设备不会主动上报，只在收到指令后回复

3. **正确策略**: 发送状态查询帧后，**只解析下一帧**作为状态回复

**当前错误代码** (`AFDT1024Controller.read_thread()`, 第869-876行):
```python
if msg == "OK" and parsed:
    if parsed.get('payload'):
        status_info, status_msg = parse_status_response(parsed['payload'])
        # ← 错误: 所有帧都被当成状态回复!
        if status_msg == "OK" and status_info:
            self.update_status_display(status_info)
```

**正确做法**:
```python
# 需要追踪: 刚发送了状态查询，下一帧才是状态回复
if self._expecting_status_reply:
    if msg == "OK" and parsed:
        if parsed.get('payload'):
            status_info, status_msg = parse_status_response(parsed['payload'])
            if status_msg == "OK" and status_info:
                self.update_status_display(status_info)
    self._expecting_status_reply = False
```

**涉及代码位置**:
| 文件 | 类 | 行号 | 问题 |
|------|-----|------|------|
| main.py | AFDT1024Controller | 869-876 | 任意帧解析为状态 |
| main.py | AFDR1024Controller | 1238-1245 | 任意帧解析为状态 |

---

### 🔴 缺陷2: 配置指令成功检测缺失 (功能不完整)

**问题描述**:
> "除了设备状态查询帧的回复外每发送一包配置指令，如果配置成功的话，AFDT1024设备会返回一模一样的回复帧，可以利用这个来判断指令是否配置成功"

**根因分析**:

根据TX串口日志验证:
```
[Line 161] >>> 发送: AA550C00140000000064F29A    # 发射衰减设置
[Line 162] <<< 收到: AA550C00140000000064F29A [OK]  # 设备回显原帧=成功
```

设备在配置成功后**返回完全相同的帧**作为确认。当前代码只解析了帧但**没有判断是否配置成功**。

**当前代码问题**:
```python
# main.py, AFDT1024Controller.set_beam() 等配置函数
def set_beam(self):
    frame = build_tx_beam_frame(device_id, freq, beam_h, beam_v)
    self.send_frame(frame)
    # ← 没有检测回显来确认配置成功!
```

**应该增加**:
```python
def set_beam(self):
    frame = build_tx_beam_frame(device_id, freq, beam_h, beam_v)
    self.send_frame(frame)
    self._expecting_echo = True  # 标记等待回显
    self._sent_frame = frame     # 保存发送的帧用于比对
```

**涉及代码位置**:
| 文件 | 类 | 行号 | 问题 |
|------|-----|------|------|
| main.py | AFDT1024Controller | 721-726 | set_beam无成功检测 |
| main.py | AFDT1024Controller | 737-739 | set_array_enable无成功检测 |
| main.py | AFDT1024Controller | 750-752 | set_polarization无成功检测 |
| main.py | AFDT1024Controller | 762-764 | set_pa_enable无成功检测 |
| main.py | AFDR1024Controller | 类似 | 同样问题 |

---

### 🔴 缺陷3: RX设备状态查询校验和问题 (设备bug补偿)

**问题描述**:
> "AFDT1024_RX设备对设备状态查询帧的回复帧进行解析时，校验和计算不要包含mcu_ver字段，因为设备端在开发的时候犯了错误，对这一帧回复进行校验和计算时没有加mcu_ver"

**根因分析**:

根据用户提供的实际日志:
```
>>> 发送: 50534101019C82     # RX状态查询
<<< 收到帧：50534101054a738e040239
<<<解析结果:校验和错误
```

设备端校验和计算时**遗漏了mcu_ver字段**，导致上位机校验失败。

**当前校验逻辑** (`afdt1024_protocol.py`, `calculate_checksum`):
```python
def calculate_checksum(data):
    checksum = sum(data)  # 包含所有字节
    return checksum & 0xFF
```

**问题**: 当设备返回的校验和是针对 `[DATA_不含MCU_VER]` 计算的，而我们用 `[DATA_含MCU_VER]` 计算校验和，结果不一致。

**帧解析流程**:
1. `parse_response()` 计算校验和时包含所有DATA字节
2. 但设备端计算校验和时**不包含**MCU_VER
3. 校验和必然不匹配

**补偿方案**:
```python
def parse_response_with_workaround(frame, has_checksum_bug=False):
    """解析AFDT1024响应帧
    has_checksum_bug: RX设备状态查询回复的校验和不包含mcu_ver
    """
    # 正常解析...
    if has_checksum_bug and len(data) > 5:
        # 对于RX状态查询回复，需要用不含mcu_ver的数据计算校验和
        expected_checksum = calculate_checksum(data[:-1])  # 排除mcu_ver
    else:
        expected_checksum = calculate_checksum(data)
    
    if checksum_recv != expected_checksum:
        return None, "校验和错误"
```

**涉及代码位置**:
| 文件 | 类/函数 | 行号 | 问题 |
|------|---------|------|------|
| afdt1024_protocol.py | calculate_checksum | 50-53 | 简单求和校验 |
| afdt1024_protocol.py | parse_response | 74-110 | 无特殊处理 |
| main.py | AFDR1024Controller.read_thread | 1233 | 校验失败被跳过 |

---

### 🔴 缺陷4: 日志写入阻塞串口接收线程 (严重)

**问题描述**:
> "目前的log及串口数据处理方式似乎会造成阻塞"

**根本原因**:
`log()` 方法在串口接收线程中直接执行同步文件I/O：

```python
# main.py, 第660-663行 (所有Controller类相同)
def log(self, msg):
    ts = datetime.datetime.now().strftime("[%Y-%m-%d %H:%M:%S] ")
    self.logfile.write(ts + msg + "\n")  # ← 阻塞I/O
    self.logfile.flush()                   # ← 强制刷盘，更严重阻塞
```

**阻塞点统计**:
| 类 | 每帧log调用次数 |
|----|----------------|
| DeviceController | 5+ 次 |
| AFDT1024Controller | 4+ 次 |
| AFDR1024Controller | 4+ 次 |

**涉及代码位置**:
| 文件 | 类 | 行号 | 问题 |
|------|-----|------|------|
| main.py | DeviceController | 153-156 | log()同步I/O |
| main.py | AFDT1024Controller | 660-663 | log()同步I/O |
| main.py | AFDR1024Controller | 1042-1045 | log()同步I/O |

---

### 🔴 缺陷5: Tkinter UI跨线程访问 (严重)

**问题描述**:
`read_thread()` 后台线程直接调用 `self.text.insert()` 等UI方法

**问题分析**:
1. Tkinter不是线程安全的
2. 后台线程直接调用 `scrolledtext.insert()`, `text.see()`, `treeview.item()` 等
3. 可能导致界面撕裂、死锁、崩溃

**涉及代码位置**:
- `DeviceController.read_thread()`: 第318, 319, 362, 368, 377, 381, 395, 400, 409, 416, 423, 430行
- `AFDT1024Controller.read_thread()`: 第815-876行
- `AFDR1024Controller.read_thread()`: 第1184-1249行

---

## 三、协议实际数据分析

### 3.1 AFDT1024 TX状态查询实测

**发送**:
```
50 53 41 01 01 5C 42
   |  |  |  |  |  |
   |  |  |  |  |  +-- CHECKSUM: lower8(50+53+41+01+01+5C) = 0x42
   |  |  |  |  +-- ADDR: 0x5C (状态查询)
   |  |  |  +-- LEN: 1 (DATA长度)
   |  |  +-- ID: 0x01
   +-- HEADER: PSA
```

**接收**:
```
50 53 41 01 06 01 01 77 77 01 02 DE
   |  |  |  |  |  |  |  |  |  |  |
   |  |  |  |  |  |  |  |  |  |  +-- CHECKSUM
   |  |  |  |  |  |  |  |  |  +-- MCU_VER: 0x02
   |  |  |  |  |  |  |  |  +-- ATT_TC: 0x01
   |  |  |  |  |  |  |  +-- SysTemp: 0x77 - 80 = 39°C
   |  |  |  |  |  |  +-- SysVcc: 0x77 * 0.1 = 11.9V
   |  |  |  |  |  +-- State: 0x01
   |  |  |  |  +-- Rev: 0x01
   |  |  |  +-- LEN: 6 (DATA长度)
   |  |  +-- ID: 0x01
   +-- HEADER: PSA
```

**状态格式**: `[Rev][State][SysVcc][SysTemp][ATT_TC][MCU_VER]`

### 3.2 AFDR1024 RX状态查询实测

**发送**:
```
50 53 41 01 01 9C 81
   |  |  |  |  |  +-- CHECKSUM
   |  |  |  |  +-- ADDR: 0x9C (RX状态查询)
   |  |  |  +-- LEN: 1
   |  |  +-- ID: 0x01
   +-- HEADER: PSA
```

**接收**:
```
50 53 41 01 06 01 02 77 77 01 02 DF
   |  |  |  |  |  |  |  |  |  |  |
   |  |  |  |  |  |  |  |  |  |  +-- CHECKSUM (设备计算时不含MCU_VER!)
   |  |  |  |  |  |  |  |  |  +-- MCU_VER: 0x02 (不参与校验和计算!)
   |  |  |  |  |  |  |  |  +-- ATT_TC: 0x01
   |  |  |  |  |  |  |  +-- SysTemp: 0x77 - 80 = 39°C
   |  |  |  |  |  |  +-- SysVcc: 0x02 * 0.1 = 0.2V ← 异常?
   |  |  |  |  |  +-- Rev: 0x01
   |  |  |  |  +-- LEN: 6
   |  |  +-- ID: 0x01
   +-- HEADER: PSA
```

**注意**: RX设备返回LEN=6但校验和只计算了前5字节! 这是设备bug。

**状态格式**: `[Rev][SysVcc][SysTemp][ATT_TC][MCU_VER]` (5字节DATA)

### 3.3 配置指令回显验证

**实测日志** (KaUDC004A):
```
[Line 161] >>> 发送: AA550C00140000000064F29A    # 发射衰减设置=10dB
[Line 162] <<< 收到: AA550C00140000000064F29A [OK]  # 完全相同的帧=成功
```

**结论**: 配置成功后，设备返回**完全相同的帧**作为确认。

---

## 四、修复方案设计

### 4.1 状态查询帧识别 - 发送后下一帧策略

```python
class AFDT1024Controller:
    def __init__(self, ...):
        # ... 现有初始化
        self._pending_reply_type = None  # 追踪待处理的回复类型
        self._sent_frame = None         # 保存发送的帧用于回显比对
    
    def query_status(self):
        """发送状态查询"""
        device_id = int(self.id_entry.get())
        frame = build_status_query_frame(device_id)
        self.send_frame(frame)
        self._pending_reply_type = 'status_query'
        self._sent_frame = frame
    
    def set_beam(self):
        """发送波束设置"""
        # ... 构建frame ...
        self.send_frame(frame)
        self._pending_reply_type = 'echo_check'
        self._sent_frame = frame
    
    def read_thread(self):
        """接收线程 - 基于_pending_reply_type决定如何处理"""
        while self.running:
            # ... 接收帧 ...
            
            if self._pending_reply_type == 'status_query':
                # 只有状态查询后才解析状态
                if msg == "OK" and parsed:
                    status_info, status_msg = parse_status_response(parsed['payload'])
                    if status_msg == "OK" and status_info:
                        self.update_status_display(status_info)
                self._pending_reply_type = None
                
            elif self._pending_reply_type == 'echo_check':
                # 检查是否回显一致
                if frame == self._sent_frame:
                    self._safe_insert(self.text, "✓ 配置成功")
                else:
                    self._safe_insert(self.text, "✗ 配置失败或无响应")
                self._pending_reply_type = None
```

### 4.2 RX设备校验和补偿

```python
def parse_response_workaround(frame, expect_rx_status=False):
    """解析AFDT1024响应帧
    expect_rx_status: 是否为RX状态查询回复（设备校验和有bug）
    """
    # ... 帧头、长度解析 ...
    
    if expect_rx_status:
        # RX状态查询: 校验和计算不含mcu_ver
        # DATA = [Rev][SysVcc][SysTemp][ATT_TC][MCU_VER]
        # 设备校验和只计算前4字节
        if len(data) >= 5:
            expected_cs = calculate_checksum(data[:-1])  # 排除mcu_ver
        else:
            expected_cs = calculate_checksum(data)
    else:
        expected_cs = calculate_checksum(data)
    
    if checksum != expected_cs:
        return None, "校验和错误"
    
    # ... 继续解析 ...
```

### 4.3 异步日志系统

```python
class AsyncLogger:
    """异步日志写入器 - 生产者/消费者模式"""
    
    def __init__(self, filename):
        self._queue = queue.Queue(maxsize=2000)
        self._filename = filename
        self._running = True
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()
    
    def log(self, msg):
        """非阻塞日志写入"""
        ts = datetime.now().strftime("[%Y-%m-%d %H:%M:%S] ")
        try:
            self._queue.put_nowait(ts + msg)
        except queue.Full:
            pass  # 队列满时丢弃
    
    def _worker(self):
        with open(self._filename, "a", encoding="utf-8") as f:
            while self._running:
                try:
                    msg = self._queue.get(timeout=0.5)
                    f.write(msg + "\n")
                except queue.Empty:
                    continue
```

### 4.4 线程安全UI更新

```python
class ThreadSafeUIMixin:
    """线程安全的UI更新Mixin"""
    
    def _safe_insert(self, widget, text):
        """在主线程中插入文本"""
        def callback():
            widget.insert(tk.END, text + "\n")
            widget.see(tk.END)
        self.master.after(0, callback)
    
    def _safe_update_status(self, table, items):
        """在主线程中更新状态表格"""
        def callback():
            for iid, values in items:
                table.item(iid, values=values)
        self.master.after(0, callback)
```

---

## 五、改进优先级

| 优先级 | 缺陷 | 建议方案 | 工作量 |
|--------|------|----------|--------|
| **P0** | 状态查询帧解析错误 | 引入_pending_reply_type追踪机制 | 中 |
| **P0** | 配置成功检测缺失 | 引入回显比对机制 | 中 |
| **P0** | RX校验和bug | 补偿计算排除mcu_ver | 小 |
| **P0** | 日志阻塞 | 异步日志写入器 | 中 |
| **P0** | UI跨线程 | after()安全更新 | 中 |

---

## 六、实现计划

### Phase 1: 核心帧处理逻辑 (关键)

**目标**: 修复状态查询和配置确认的帧处理

1. **引入_pending_reply_type机制**
   - [ ] DeviceController: 引入pending_reply追踪
   - [ ] AFDT1024Controller: 引入pending_reply追踪
   - [ ] AFDR1024Controller: 引入pending_reply追踪

2. **实现回显检测**
   - [ ] AFDT1024Controller: set_beam/set_enable等检测回显
   - [ ] AFDR1024Controller: set_beam/set_enable等检测回显
   - [ ] UI显示"配置成功/失败"提示

3. **RX校验和补偿**
   - [ ] 修改parse_response支持has_checksum_bug参数
   - [ ] AFDT1024Controller调用时传入正确参数

### Phase 2: 异步和线程安全

**目标**: 消除阻塞和线程安全隐患

1. **异步日志系统**
   - [ ] 实现AsyncLogger类
   - [ ] 重构所有Controller使用AsyncLogger

2. **线程安全UI更新**
   - [ ] 实现ThreadSafeUIMixin
   - [ ] 重构所有UI更新使用_safe_insert/_safe_update_status

### Phase 3: 测试验证

**目标**: 确保修复正确

1. **手动测试**
   - [ ] TX状态查询: 发送后下一帧被正确解析
   - [ ] TX配置: 成功后显示确认提示
   - [ ] RX状态查询: 校验和不再报错
   - [ ] RX配置: 成功后显示确认提示

2. **边界测试**
   - [ ] 连续快速发送多个指令
   - [ ] 设备无响应超时处理

---

## 七、待确认问题

1. **回显超时**: 配置指令发送后，如果设备没有回显，应该等待多久超时？建议2秒？

2. **状态查询超时**: 当前 query_status() 只发送帧，不等待响应。如何与 read_thread 配合？

3. **KaUDC004A协议**: 遗留协议(KaUDC004A)是否也有类似的状态查询和回显问题？它的帧格式是 `AA55` 开头。

4. **错误处理**: 当检测到回显不一致时，除了显示提示，还应该重试吗？

---

*更新时间: 2026-03-22*
*分析工具: Sisyphus Code Analysis Agent*
*备注: 根据用户反馈更新 - 状态查询无ADDR字段，使用"发送后下一帧"策略; 配置成功返回原帧回显; RX校验和不含mcu_ver*
