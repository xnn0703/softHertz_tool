# KauDC004A_TestTool QtSerialPort 迁移计划

## 1. 背景与目标

### 1.1 当前问题

**PyQt5 + pyserial 架构问题**：
- pyserial 使用轮询方式读取串口 (`read()` + `time.sleep()`)
- 轮询间隔 10ms 导致响应延迟
- CPU 持续占用，即使无数据
- 手动线程管理复杂，容易出现竞态条件
- 信号发射过于频繁导致 UI 事件队列泛滥

**UI 冻结现象**：
- 快速点击按钮 → 多帧接收 → 每帧触发 `log_signal.emit()` → Qt 事件队列泛滥 → UI 冻结

### 1.2 目标

使用 **PySide6 + QtSerialPort** 替换现有方案，实现：
- 事件驱动串口读取（`readyRead` 信号，无轮询）
- Qt 原生线程安全
- ms 级响应延迟
- 完全不阻塞 UI

---

## 2. 新架构设计

### 2.1 架构对比

| 特性 | pyserial (当前) | QtSerialPort (目标) |
|------|-----------------|---------------------|
| 读取方式 | 轮询 (`while` + `sleep`) | 事件驱动 (`readyRead`) |
| CPU 占用 | 中等 (持续轮询) | 极低 (仅事件触发) |
| 响应延迟 | ≥10ms (轮询间隔) | <1ms (事件触发) |
| 线程安全 | 手动 (queue.Lock) | Qt 原生 (signals) |
| 多串口 | 复杂 | 简单 (每串口独立 Worker) |

### 2.2 类结构

```
MainWindow (QMainWindow)
├── KaUDCPanel (QFrame)
│   ├── SerialSettings (端口/波特率)
│   ├── StatusTable (状态显示)
│   ├── CommandUI (命令发送)
│   ├── LogText (日志)
│   └── KaUDCWorker (QThread)
│       └── QSerialPort (readyRead → parse → emit)
│
├── TXPanel (QFrame)
│   ├── SerialSettings
│   ├── BeamUI (频率/角度)
│   ├── ArrayUI (使能)
│   ├── PAUI (使能)
│   ├── PolarizationUI (LHCP/RHCP)
│   ├── StatusDisplay
│   ├── LogText
│   └── TXWorker (QThread)
│       └── QSerialPort
│
└── RXPanel (QFrame)
    ├── SerialSettings
    ├── BeamUI
    ├── ArrayUI
    ├── PolarizationUI
    ├── StatusDisplay
    ├── LogText
    └── RXWorker (QThread)
        └── QSerialPort
```

### 2.3 线程模型

```
┌─────────────────────────────────────────────────────────────────┐
│                         主线程 (UI)                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐           │
│  │ KaUDC面板   │  │  TX 面板    │  │  RX 面板    │           │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘           │
│         │                 │                 │                   │
│    Signal/Slot      Signal/Slot      Signal/Slot              │
└─────────┼─────────────────┼─────────────────┼───────────────────┘
          │                 │                 │
┌─────────▼─────────────────▼─────────────────▼───────────────────┐
│                    QThread Worker × 3                            │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐     │
│  │ KaUDCWorker    │  │  TXWorker      │  │  RXWorker      │     │
│  │                │  │                │  │                │     │
│  │ QSerialPort    │  │ QSerialPort    │  │ QSerialPort    │     │
│  │                │  │                │  │                │     │
│  │ readyRead ──►  │  │ readyRead ──►  │  │ readyRead ──►  │     │
│  │ readAll()      │  │ readAll()      │  │ readAll()      │     │
│  │                │  │                │  │                │     │
│  │ parse_frame()  │  │ parse_frame()  │  │ parse_frame()  │     │
│  │                │  │                │  │                │     │
│  │ emit signal    │  │ emit signal    │  │ emit signal    │     │
│  └────────────────┘  └────────────────┘  └────────────────┘     │
└─────────────────────────────────────────────────────────────────┘
```

### 2.4 Signal 定义

```python
# PySide6 信号 (与 PyQt5 略有不同)
from PySide6.QtCore import Signal, QObject

class Worker(QObject):
    # 日志消息信号
    log_signal = Signal(str)
    
    # 状态数据信号
    status_signal = Signal(dict)
    
    # 配置成功信号
    config_success_signal = Signal(str)
    
    # KaUDC 响应信号
    response_signal = Signal(str, str)  # cmd_name, value
```

### 2.5 QtSerialPort 关键 API

```python
from PySide6.QtSerialPort import QSerialPort, QSerialPortInfo
from PySide6.QtCore import QIODevice

# 创建串口
serial = QSerialPort()
serial.setPortName("COM1")
serial.setBaudRate(QSerialPort.Baud115200)
serial.setDataBits(QSerialPort.Data8)
serial.setParity(QSerialPort.NoParity)
serial.setStopBits(QSerialPort.OneStop)

# 打开串口
if serial.open(QIODevice.ReadWrite):
    print("串口已打开")

# 事件驱动读取 (核心区别!)
serial.readyRead.connect(self.handle_ready_read)
def handle_ready_read(self):
    data = serial.readAll()  # 读取所有可用数据
    # 处理数据...

# 写入串口
serial.write(b"\x50\x53\x41\x01\x02...")

# 关闭串口
serial.close()
```

---

## 3. 依赖

```bash
# 方式1: PySide6 (推荐 - Qt 官方维护)
pip install PySide6

# 方式2: PyQt5 + QtSerialPort
pip install PyQt5
# QtSerialPort 在 PyQt5-stubs 中
pip install PyQt5-stubs
```

**注意**: QtSerialPort 在 PySide6/PyQt5 中已内置，无需额外安装。

---

## 4. 文件结构

```
KauDC004A_TestTool/
├── code/
│   ├── main_qt6.py          # 新主程序 (PySide6 + QtSerialPort)
│   ├── main_qt.py           # 旧主程序 (保留)
│   ├── protocol.py          # KaUDC004A 协议 (不变)
│   ├── afdt1024_protocol.py # AFDT1024/AFDR1024 协议 (不变)
│   └── device_simulator.py  # 设备模拟器 (不变)
├── plan.md                  # 本计划
└── DEV_LOG.md              # 开发日志
```

---

## 5. 实现步骤

### Step 1: 创建 PySide6 基础框架
- 迁移 import 语句 (PyQt5 → PySide6)
- 调整信号/槽语法差异
- 创建 `main_qt6.py`

### Step 2: 实现 QtSerialPort Worker
- 创建 `SerialWorker` 使用 `QSerialPort`
- 实现 `readyRead` 信号连接
- 实现帧解析逻辑

### Step 3: 实现 KaUDCWorker
- 使用 `QSerialPort` 替代 `serial.Serial`
- 实现 KaUDC 协议解析

### Step 4: 调整 UI 组件
- 适配 PySide6 语法差异
- 测试三面板布局

### Step 5: 测试验证
- 使用模拟器测试
- 验证 UI 响应性
- 对比性能提升

---

## 6. 关键差异参考

### PyQt5 → PySide6 迁移

| PyQt5 | PySide6 |
|-------|---------|
| `pyqtSignal(str)` | `Signal(str)` |
| `pyqtSlot()` | `@Slot()` |
| `QThread` | `QThread` |
| `QApplication(sys.argv)` | `QApplication(sys.argv)` |
| `app.exec_()` | `app.exec()` |

### pyserial → QtSerialPort

| pyserial | QtSerialPort |
|----------|--------------|
| `serial.Serial(port, baudrate, timeout=0.01)` | `QSerialPort()` + `setBaudRate()` + `open()` |
| `ser.read(1024)` | `ser.readAll()` (在 `readyRead` 回调中) |
| `ser.write(frame)` | `ser.write(frame)` |
| `ser.in_waiting` | `ser.bytesAvailable()` |
| `ser.close()` | `ser.close()` |

---

## 7. 验收标准

1. **无轮询**: 使用 `readyRead` 信号，无 `while` 循环轮询
2. **UI 响应**: 快速连续点击 10 次按钮，UI 保持流畅
3. **低延迟**: 串口数据到达后 <5ms 触发处理
4. **正确性**: 所有现有功能保持不变
5. **兼容性**: 支持 Windows 串口

---

## 8. 保留内容

- `afdt1024_protocol.py` - 协议解析保持不变
- `protocol.py` - KaUDC004A 协议保持不变
- `device_simulator.py` - 模拟器保持不变
- `main_qt.py` - 旧版本保留备份
