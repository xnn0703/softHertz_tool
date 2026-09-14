# 验收标准
状态：软件验收 PASS，Windows 原生与实板验收待执行。
- AFD01/AFD01C App Debug/Release 构建；Release 无新增控制符号。
- codec 参数/帧/CRC/请求编号与错误响应测试。
- 独立 Tab、模式与能力门禁、按钮语义、超时不重发、重连/关闭/原 Tab 回归。
- 函数合同、格式、diff 检查。
- 实板网口/Tracking 手动保持、GPIO/RF 独立操作/上线/重启待实测，Windows 原生运行单独记录。
- 不提交、不下载、不发布。

## 2026-09-14 软件验收结果

| 验收项 | 结果 | 证据与边界 |
|---|---|---|
| 独立 AFD01 工作区 | PASS | 静态 registry 第四项，主窗口无设备特判，KA_RF_UNIT 实现独立 |
| AFD01C App Debug/Release | PASS | build.sh 两项成功 |
| AFD01 App Debug/Release | PASS | build.sh 两项成功 |
| Release 控制入口排除 | PASS | 两型号 Release ELF 均无 afd01_rf_handle/transceiver_rf_submit/antenna_rf_submit；Debug 均存在 |
| C 纯 codec | PASS | code/tests/afd01_rf_test_codec/run_tests.sh：参数边界、保留字段、schema、长度、输出失败保持、黄金 payload |
| Python 完整回归 | PASS | QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q：456 passed in 16.92s，包含原 KA_RF_UNIT 回归 |
| 最终状态文案回归 | PASS | tests/devices/test_afd01.py + 文档合同检查；真实 UDP 回环、按钮语义、旧代际、错编号、超时无重发、模式/能力/过期门禁 |
| 入口冒烟/编译 | PASS | 独立 python -m soft_hertz_tool --smoke；compileall src tests packaging |
| 页面布局 | PASS | macOS Qt offscreen 1280×1050 截图检查；控制完整、可滚动；不等于 Windows 原生检查 |
| 函数合同 | PASS | strict debug/antenna/transceiver：20 files / 269 functions / 0 diagnostics；全仓 baseline：592 files / 7203 functions / 0 diagnostics |
| 格式与差异 | PASS | 改动 C 文件 clang-format --dry-run --Werror、两仓 git diff --check |
| 文档站 | PASS | 73 页生成、内部链接校验通过 |
| Windows 原生与实板 | 待执行 | 未连接设备、未下载，未确认 GPIO/PLL/RF 效果或实际 Tracking 手动保持 |

构建日志中 newlib syscall stub 等警告不表示构建失败；未扩大本次修改范围。

## 实板执行清单

1. 使用 AFD01C Debug，在 AFD01 页面填写 IP/4004；确认实际型号、能力和状态有效。
2. 自动模式下写操作禁用；点击切换手动，确认状态后逐项设置变频 TX/RX LO/RF、衰减、IF、参考频率。
3. 独立设置阵列 TX/RX 频率、角度、模式、极化、衰减、大小、开关及 TX PA；核对另一通路保持。
4. 持续观察多个 Tracking/业务周期，确认手动设置不被 Tracking 覆盖；GPIO、电源、物理频率与输出由仪表分别确认。
5. 覆盖非法参数、槽忙/执行失败、阵列掉线重新上线、网络断开重连、切换 Tab、重启默认行为。
6. Release/旧固件连接不开放写操作；恢复自动明确使用 track md 0。
7. 在 Windows 原生运行确认 Tab、UDP 收发、退出与原串口设备功能。

## Debug 离轴 ±90° 验证

PASS：上位机相关测试 43 项；固件 RF codec 边界测试；AFD01/AFD01C App Debug/Release 四项构建；修改模块函数合同与差异检查。手动 TX/RX 及扫描起终点范围均为 −90°～90°。大角度设备执行与物理 RF 未实板验收，未下载固件。

## 连接默认行为与界面精简

用户确认默认地址 192.168.1.12；每次连接获得首次有效能力/状态后，非手动时自动请求一次手动模式。已有手动模式直接使用，自动请求失败不重试，仍可使用手动按钮；设备确认手动后才开放测试写操作。此规则替代原连接后仅查询的模式规则，射频设置和扫描仍不重放。

删除状态表最近请求行、页内报文及其页签；AFD01 隐藏公共报文监视器，其他工作区保留。Workspace 用单个静态可见性属性告知主窗口，不引入设备特判；原报文日志通路保留。界面为上方连接、左侧变频/扫描、右侧阵列/操作反馈、下方八行状态表。
