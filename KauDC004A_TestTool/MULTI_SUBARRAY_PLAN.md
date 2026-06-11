# 多子阵状态显示 + ID 模式支持 计划

## 背景
TX/RX 各为一条串口总线，挂多个子阵（ID 区分）。现 UI 每条总线只显示一个状态、不分 ID。需支持多子阵状态显示与三种 ID 模式操作。

## 确认的交互（来自用户）
- 拓扑：TX 一条总线、RX 一条总线，多子阵靠 ID 区分。
- ID 三模式全部 UI 可用：
  - `ID=0` 广播 → 所有子阵响应、不返回（给全部下发配置）
  - `ID=实际ID` → 所有响应、对应 ID 返回
  - `ID=实际ID+128` → 仅对应 ID 响应并返回
- ID 手动输入（逗号分隔列表）。
- 配置目标 = 下拉「全部(广播 ID=0) / 指定 ID」+「仅本子阵(+128)」复选框。
- 状态查询 = 手动点「查询全部状态」，逐个 ID 查一遍。
- 状态显示 = 表格，每个子阵 ID 一行（TX: ID/电压/温度/PA；RX: ID/电压/温度）。

## 改动点

### main_qt6.py — DevicePanel 基类（新增通用方法）
- `_create_subarray_group()`：ID列表输入框 + 目标下拉 + 仅本子阵(+128)。
- `_parse_id_list()`：解析为去重排序 [int]（1~127）。
- `_refresh_target_combo()` / `_on_id_list_changed()`：ID 列表变更时刷新目标下拉与表格。
- `_get_target_device_id()`：配置指令目标→ 全部=0 / 指定ID（勾+128 则 +128）。
- `_create_status_group(columns)` + `_rebuild_status_table()` + `_update_status_row()`：状态表格按 device_id 路由更新。
- `_on_query_status()`：遍历 ID 列表逐个发查询（间隔 50ms）。
- `_build_status_query_frame()`：抽象，TX→0x5C、RX→0x9C。
- 基类 `_on_status()` → `_update_status_row()`。

### main_qt6.py — TX/RX 面板
- 子阵设置组 → `_create_subarray_group()`；状态组 → `_create_status_group(列)`（TX 含 PA）。
- 配置指令 device_id：`_get_device_id()` → `_get_target_device_id()`。
- 删除各自的 `_on_query_status`/`_on_status`，改为基类统一 + `_build_status_query_frame()`。

### main_qt6.py — SerialWorker._process_frame
- 状态回复时把 `device_id` 放进 `status_info` 并随信号上抛，日志带 `[ID=x]`。

### device_simulator.py
- TX/RX 模拟器支持多 ID（持有 ID 集合）；按目标 ID 响应：
  - 目标=0（广播）→ 不回复；目标&0x7F ∈ 自身 ID → 回复，且电压/温度随 ID 变化，便于看到多行不同值。

### test_serial_improved.py
- 新增：模拟器多 ID 状态帧 → parse_response 得到正确 device_id；状态帧 device_id 路由正确性（协议层）。

## 验收标准（已完成）
- [x] ID 列表输入 `1,2,3` → 状态表格 3 行，目标下拉含「全部 + 1/2/3」。
- [x] 目标=全部 → 配置帧 device_id=0；目标=2 → device_id=2；勾+128 → 130。
- [x] 查询全部 → 逐个 ID 发查询；回复按 `device_id & 0x7F` 落到对应行（模拟器多 ID 验证）。
- [x] **阵列拼接**：选「列数 + 每列N」点「生成ID」→ 按协议编号规则（左列 0x01~0x0N、右列 0x11~0x1N）生成 ID，三者联动。
- [x] pytest 全绿（59 passed）；GUI 正常渲染，表格/下拉/复选框/拼接控件显示正确（offscreen 验证 + 截图）。
- [x] KaUDC 面板不受影响。

## 实现补充：阵列拼接一键生成
`DevicePanel._gen_subarray_ids(cols, n)`：`ID = (列号<<4)|行号`，列号 0=左/1=右，行号 1~N。UI「阵列拼接」选列数(1/2)+每列子阵数 N，点「生成ID」自动填入 ID 列表并刷新表格/目标下拉；手动 ID 列表框保留用于微调。
