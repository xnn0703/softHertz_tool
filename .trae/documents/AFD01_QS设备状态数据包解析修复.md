# AFD01_QS设备状态数据包解析修复方案

## 问题分析
根据用户提供的协议格式图片，发现以下问题：

**校验和解析格式错误**：
- 当前代码使用 `struct.unpack('<H', crc_bytes)[0]`（低字节在前，小端序）
- 但根据图片格式，校验和是**高字节在前（大端序）**
- 应该使用 `struct.unpack('>H', crc_bytes)[0]`

这个错误会导致校验和验证失败，进而导致数据包解析失败，设备状态显示为"N/A"。

## 修复方案

修改 `afd01_qs_protocol.py` 文件中的 `parse_response` 方法，将校验和解析从**小端序**改为**大端序**：

```python
# 当前代码（错误）：
received_checksum = struct.unpack('<H', crc_bytes)[0]

# 修改为（正确）：
received_checksum = struct.unpack('>H', crc_bytes)[0]
```

## 修复后预期效果
1. 设备能够正确验证校验和
2. 设备能够正确解析天线状态上报帧
3. 设备信息能够被正确更新
4. UI显示的设备状态不再是"N/A"，而是实际的设备状态数据

## 测试验证
可以通过运行现有的测试文件 `test_afd01_ui_update.py` 来验证修复效果：
```bash
python test_afd01_ui_update.py
```

如果修复成功，测试将通过，显示所有设备状态字段都已正确更新。