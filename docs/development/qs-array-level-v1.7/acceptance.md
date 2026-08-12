# AFD01_QS 阵列档位上位机验收标准

- [x] 代码、界面、模拟器、测试和当前项目文档中的公开协议版本统一为 V1.7。
- [x] 0x0B 仅发送档位 `1～5`，`None` 编码为 `0xFF`。
- [x] A1 解码和 UI 状态不再把内部器件数量作为客户阵列尺寸。
- [x] 下拉框和状态文本显示档位及 `8×8～16×16` 有效子阵规模。
- [x] TX/RX 均为 16×16 子阵网格，五档启用数量为 64/100/144/196/256。
- [x] 模拟器默认档位5并拒绝旧值 `6～8`。
- [x] 0x0B/A1 日志摘要显示档位和客户子阵规模，原始帧保持完整。
- [x] 单请求、超时、连接代际和工作区切换行为不回退。
- [x] 完整 pytest、compileall 和 Qt offscreen 冒烟通过。
- [x] Windows CI 构建产物已完成原生 `--smoke`；客户目标机和真实设备仍明确标记为未验收。

## A1 两字段精简验收

- [x] A1 载荷长度精确为 2 字节，字段顺序为 `tx_level, rx_level`。
- [x] A1 不再解析或展示 `result`、`power_flags`、`apply_flags`。
- [x] 收到有效 A1 后，TX/RX 下拉框、网格和状态文本仅按回读档位更新为已确认。
- [x] 旧 5 字节 A1 被判为长度不匹配，不做隐式兼容。
- [x] 模拟器对有效查询/设置返回两字段 A1；非法设置不修改当前档位。
- [x] 3 秒请求超时、请求未入队和旧连接回调保护保持有效。
- [x] 本轮完整 pytest、compileall、Qt offscreen 冒烟和 `git diff --check` 通过。
- [x] 100 Hz 调度使用受控虚拟时钟验证，不依赖 Windows runner 的短时调度精度。
- [x] Python 约束文件仅在依赖安装步骤生效，不影响 setup-python 首次安装解释器。

## 主机验证证据

- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/devices/test_afd01_qs.py -q`：
  `29 passed in 0.83s`。
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`：
  `143 passed in 4.20s`。
- `.venv/bin/python -m compileall -q src tests packaging`：通过。
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m soft_hertz_tool --smoke`：退出码 0。
- 30.1 秒内存串口模拟链路：收到并记录 3010 帧 A0，平均 `99.999 Hz`，
  帧间隔 `8.969～10.889 ms`，频率指示最终为 `100.000 Hz`。
- 异步日志文件共 3010 行，与 A0 接收记录数一致，未发现主机侧日志丢帧。
- 1400×650 offscreen 页面截图已人工检查，档位文本和两块 16×16 网格无截断或重叠。
- `git diff --check`：通过。
- 已覆盖请求未入队、3 秒超时及旧连接 A1 回调：失败/超时网格转红，旧回调不覆盖新连接状态。
- 已覆盖 A1 两字段精确长度、两字段日志摘要、旧五字段帧拒绝和非法 0x0B 设置保持当前档位。
- GitHub Actions `v3.0.1`（run `31583451422`）：Windows Python 3.9/3.11.9
  正式测试、PyInstaller 构建、打包后 EXE `--smoke`、SHA256、Artifact 和 Release 发布均通过。
- Release 资产 `SoftHertz_Tool.exe` 为 48,942,774 字节，SHA256 为
  `530551490c3339a2643c1fbeb5ae21d060ab9bf071524e159754f70e5a36d0da`；校验文件内容与
  GitHub 服务器记录的 EXE 摘要一致。

## 未闭环边界

- 尚未在客户目标 Windows 机器完成启动、USB/串口驱动和长期运行验收；当前 Windows 证据来自
  GitHub Windows Server 2022 runner 的构建与 `--smoke`。
- 未连接真实 AFD01_QS 设备，未验证 V1.7 档位设置、A1 回读及长期稳定性。
