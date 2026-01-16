# 修复AFD01_QS设备UI显示N/A的问题

## 问题分析

通过分析代码，我发现`afd01_qs_protocol.py`中的`extract_data`方法在处理`CMD_DATA_REPORT`命令时，返回的是格式化字符串，而不是原始数值类型。这会导致UI的`update_ui`方法无法正确处理这些值，从而显示"N/A"。

## 修复方案

1. **修改`afd01_qs_protocol.py`中的`extract_data`方法**：
   - 将`CMD_DATA_REPORT`命令返回的`snr`字段从格式化字符串改为原始数值类型
   - 保持其他字符串类型字段不变（如`power_status`、`broadcast_lock_status`等）

2. **创建完整的测试脚本**：
   - 模拟设备发送55A0数据包
   - 验证UI能否正确显示所有设备状态字段
   - 确保所有字段都能从"N/A"更新为实际值

## 修复步骤

1. 编辑`afd01_qs_protocol.py`文件
2. 修改`CMD_DATA_REPORT`命令的处理逻辑，将`snr`字段返回原始数值
3. 创建测试脚本，验证修复效果
4. 运行测试脚本，确保所有设备状态字段都能正确更新

## 预期结果

- 所有设备状态字段都能从"N/A"更新为实际值
- UI能正确显示GPS坐标、频率、姿态角等信息
- 修复后的数据上报命令也能正确更新UI

## 修复代码示例

```python
# 修改前
result.update({
    "snr": f"{snr:.2f}",
    # 其他字段...
})

# 修改后
result.update({
    "snr": snr,
    # 其他字段...
})
```