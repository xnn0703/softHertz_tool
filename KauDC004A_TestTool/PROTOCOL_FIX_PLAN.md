# KauDC004A_TestTool 协议解析修复计划

## 1. 问题描述

### 当前问题
所有响应帧都被错误地当作"状态查询响应"处理，包括配置命令的 Echo 回复。

### 表现
- TX 波束设置发送后，日志显示 "电压: 0.0V, 温度: -80°C"（错误的状态数据）
- 正确的应该是显示 "✓ TX波束配置成功"

### 根本原因
帧解析逻辑没有正确区分"配置命令 Echo 回复"和"状态查询回复"。

---

## 2. 协议帧格式分析

### 2.1 已知命令地址

```python
ADDR_TX_BEAM = 0x50       # TX波束设置
ADDR_TX_ENABLE = 0x51     # TX阵列使能
ADDR_TX_POLARIZATION = 0x53 # TX极化设置
ADDR_PA_ENABLE = 0x56      # PA使能
ADDR_RX_BEAM = 0x90        # RX波束设置
ADDR_RX_ENABLE = 0x91      # RX阵列使能
ADDR_RX_POLARIZATION = 0x93 # RX极化设置
```

### 2.2 帧格式

| 帧类型 | 格式 | 示例 |
|--------|------|------|
| 配置命令 Echo 回复 | `[header][id][length=5][data(5字节)][addr(1字节)][checksum]` | `505341010500000000503A` |
| 状态查询回复 | `[header][id][length=5][status_data(5字节)][checksum]` | `5053410105017777770151` |

### 2.3 关键区分方法

**问题**: 两种帧的 `length` 都是 5，结构看起来一样！

**区分方法**: 检查 `data` 的最后一个字节是否为已知命令地址

- `data[-1] == 0x50` → TX波束设置 Echo 回复
- `data[-1] == 0x51` → TX阵列使能 Echo 回复
- `data[-1] == 0x53` → TX极化设置 Echo 回复
- `data[-1] == 0x56` → PA使能 Echo 回复
- `data[-1] == 0x90` → RX波束设置 Echo 回复
- `data[-1] == 0x91` → RX阵列使能 Echo 回复
- `data[-1] == 0x93` → RX极化设置 Echo 回复
- `data[-1]` 不在上述列表 → 状态查询回复

---

## 3. 当前解析逻辑分析

### 3.1 当前代码 (afdt1024_protocol.py)

```python
if length > 0:
    if len(data) == length:
        # 状态查询回复 - 没有addr字段
        addr = None
        payload = data
    elif len(data) == length + 1:
        # 配置命令回复 - 有addr字段
        addr = data[-1]
        payload = data[:-1]
```

### 3.2 问题所在

对于帧 `505341010500000000503A`:
- `length = 5`
- `data = 00 00 00 00 50` (5字节)
- `len(data) == length` → True

当前代码判断这帧为"状态查询回复"，但实际上它是配置命令 Echo！

### 3.3 正确逻辑应该是

1. 先检查 `data[-1]` 是否为已知命令地址
2. 如果是 → 配置命令 Echo 回复，`addr = data[-1]`，`payload = data[:-1]`
3. 如果否 → 状态查询回复，`addr = None`，`payload = data`

---

## 4. 修复方案

### 4.1 修改 parse_response 函数

```python
def parse_response(frame, has_rx_status_bug=False):
    """解析AFDT1024协议响应帧"""
    try:
        if frame[:3] != FRAME_HEADER:
            return None, "无效的帧头"

        device_id = frame[3]
        length = frame[4]
        data = frame[5:-1]
        checksum = frame[-1]

        if len(data) != length:
            return None, "长度不匹配"

        # 校验和计算
        if has_rx_status_bug and len(data) >= 5:
            expected_checksum = calculate_checksum(frame[:-2])
        else:
            expected_checksum = calculate_checksum(frame[:-1])

        if checksum != expected_checksum:
            return None, "校验和错误"

        # 关键修改：先判断是否为配置命令 Echo
        # 配置命令: data[-1] 是 addr
        # 状态查询: data 是纯状态数据，data[-1] 不是有效 addr

        known_addrs = [
            ADDR_TX_BEAM, ADDR_TX_ENABLE, ADDR_TX_POLARIZATION, ADDR_PA_ENABLE,
            ADDR_RX_BEAM, ADDR_RX_ENABLE, ADDR_RX_POLARIZATION
        ]

        if data[-1] in known_addrs:
            # 配置命令 Echo 回复
            addr = data[-1]
            payload = data[:-1]
        else:
            # 状态查询回复
            addr = None
            payload = data

        return {"device_id": device_id, "addr": addr, "payload": payload}, "OK"

    except Exception as e:
        return None, f"解析错误: {str(e)}"
```

### 4.2 修改 main_qt6.py 中的 _process_frame

```python
def _process_frame(self, frame):
    try:
        parsed, msg = parse_afdt_response(frame, has_rx_status_bug=False)

        # RX 设备：先尝试正常解析，失败则尝试 bug 解析
        if not parsed and self.device_type == "RX":
            parsed, msg = parse_afdt_response(frame, has_rx_status_bug=True)

        if parsed:
            addr = parsed.get("addr")
            frame_hex = frame.hex().upper()

            if addr is not None and addr in ADDR_CMD_NAMES:
                # 配置命令 Echo 回复
                cmd_name = ADDR_CMD_NAMES.get(addr, f"0x{addr:02X}")
                self.log_signal.emit(f"<<< 收到: {frame_hex}")
                self.log_signal.emit(f"✓ {cmd_name}配置成功")
            elif addr is None:
                # 状态查询响应
                if self.device_type == "TX":
                    status_info, status_msg = parse_status_response(parsed["payload"])
                else:
                    status_info, status_msg = parse_rx_status_response(parsed["payload"])

                if status_msg == "OK" and status_info:
                    self.log_signal.emit(f"<<< 收到: {frame_hex}")
                    self.log_signal.emit(
                        f"电压: {status_info.get('sys_vcc', 0):.1f}V, 温度: {status_info.get('sys_temp', 0)}°C"
                    )
                    self.status_signal.emit(status_info)
            else:
                # addr 不为 None 但不在已知命令列表中
                self.log_signal.emit(f"<<< 收到: {frame_hex}")
        else:
            frame_hex = frame.hex().upper()
            self.log_signal.emit(f"<<< 收到: {frame_hex}")
            self.log_signal.emit(f"✗ 解析失败: {msg}")

    except Exception as e:
        self.log_signal.emit(f"<<< 处理异常: {str(e)}")
```

---

## 5. 测试用例

### 5.1 TX 波束设置 Echo
- 发送: `505341010500000000503A`
- 期望: 显示 "✓ TX波束配置成功"

### 5.2 TX 状态查询回复
- 收到: `5053410105017777770151`
- 期望: 显示 "电压: 11.9V, 温度: 39°C" 并更新 UI

### 5.3 RX 波束设置 Echo
- 发送: `50534101053300000090AD`
- 期望: 显示 "✓ RX波束配置成功"

### 5.4 RX 状态查询回复 (带校验和 bug)
- 收到: `50534101054A738E040239`
- 期望: 显示 "电压: 11.5V, 温度: 14°C" 并更新 UI

---

## 6. 实施步骤

1. 修改 `afdt1024_protocol.py` 中的 `parse_response` 函数
   - 使用 `data[-1] in known_addrs` 判断是否为配置命令 Echo
   
2. 修改 `main_qt6.py` 中的 `_process_frame` 方法
   - 调整判断逻辑，先判断 `addr is not None` 和 `addr in ADDR_CMD_NAMES`
   - 移除不再需要的调试日志

3. 测试验证

---

## 7. 风险评估

| 风险 | 影响 | 缓解 |
|------|------|------|
| 修改协议解析可能影响其他模块 | 中 | 只修改 `parse_response` 返回结构，不改变接口 |
| RX 校验和 bug 补偿逻辑 | 低 | 已有 `has_rx_status_bug` 参数 |
