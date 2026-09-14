# AFD01 Debug 网口射频测试（schema 1）

本接口只在 AFD01/AFD01C App Debug 编入；AFD01C 为首版实板验收对象。室内、不连接 Modem；不提供多客户端协调。
SoftHertz Tool 独立 AFD01 工作区连接设备 IPv4、UDP 4004。UDP 本地源端口由系统分配，设备使用现有 Debug 通路回送。

## 模式与生命周期

先查询能力，再点击切换手动模式；Tracking 已应用的 MANUAL 状态和 transceiver 手动仲裁都确认后，固件接受控制。
请求提交和实际执行前均检查模式。网络断开/关闭页面保持模式和设置，切换回页面只重连查询，不重放设置。
恢复自动由 `track md 0` 明确执行。阵列重新上线保留原发射请求重放行为，需操作员重新下发测试设置。
外部参考频率测试不调用 FRAM 保存，其他测试控制同样只在 RAM 生效。原 Shell 持久化行为保持。

## 帧与操作

沿用 Debug envelope：`AA 55 0D CMD LEN:u16le DATA CRC:u16le EE`。
CRC16/CCITT-FALSE 初值 FFFF、poly 1021，覆盖帧头到 DATA 末。每个 UDP 数据报一帧。
顶层命令：30 请求、31 控制响应、32 查询响应（十六进制）；与 CONTROL 子命令属于不同编号空间。

请求 DATA 固定 19 字节：schema:u8=1，request_id:u32le（非零），operation:u8，target:u8（0 TX/1 RX），a/b/c:f32le。
所有浮点数必须有限；保留参数为零。表中操作号为十进制。

| operation | 操作 | a / b / c |
|---|---|---|
| 0 | 查询能力与状态 | 0 / 0 / 0，target=0 |
| 1 | 切换手动 | 0 / 0 / 0，target=0；已确认手动时幂等 |
| 2 | 变频 LO/RF | LO MHz / RF MHz / 0；整数 |
| 3 | 变频衰减 | dB / 0 / 0；0..31.5，0.5 步进 |
| 4 | IF 开关 | 0 或 1 / 0 / 0 |
| 5 | 外部参考 | MHz / 0 / 0；10..250，10 步进，target=0 |
| 6 | 阵列频率 | RF MHz / 0 / 0；整数 |
| 7 | 阵列波束 | 离轴角 -90..90° / 方位角 -360..360° / 0；使用阵列当前频率 |
| 8 | 极化 | 0 左旋、1 右旋 / 0 / 0 |
| 9 | 阵列工作模式 | 0、1、2 / 0 / 0（沿用 ant tm/rm） |
| 10 | 阵列衰减 | 公共 0..8 dB / 支路 0..7.5 dB / 0；0.5 步进 |
| 11 | 阵面大小 | 8、10、12、14、16 / 0 / 0 |
| 12 | 阵列开关 | 0 或 1 / 0 / 0 |
| 13 | TX PA | 0 或 1 / 0 / 0，target=0 |

TX RF 范围 27500..31000 MHz，RX 17700..21200 MHz；LO 1..40000 MHz。
超出型号实际 LO/硬件支持时由既有驱动报告执行失败；不改变已有型号频点算法。
AFD01 不声明 IF、阵列模式和 TX PA 测试能力；AFD01C 声明全部操作。能力 bit 位置等于 operation。

响应 DATA 固定 7 字节：schema:u8=1、request_id:u32le、operation:u8、result:u8。
result：0=已入槽，1=发送成功，2=参数错误，3=槽忙，4=不支持，5=需要手动模式，6=执行失败，7=服务未就绪。
查询不返回普通控制响应，直接返回状态。已入槽后通过状态里的 owner 最近结果确认执行。
一个客户端一次一条控制在途，5 s 超时不重发；普通查询 1 Hz；上位机扫描有控制在途时100ms查询，保持单个查询在途，1s查询超时后才更换编号。3 s 无响应禁用控制。
手动模式切换通过模式状态确认完成；固件不会为查询/模式切换新增结果缓存。

## 状态 DATA：144 字节

所有多字节字段小端，浮点字段 f32；未初始化/温度/PA 的有效位须先于数值解释。

| 偏移 | 长度 | 内容 |
|---|---|---|
| 0 | 1 | schema=1 |
| 1 | 4 | 查询 request_id |
| 5 | 16 | NUL 填充 ASCII 实际型号 AFD01/AFD01C |
| 21 | 1 | Tracking 状态枚举；4=MANUAL，255=未知 |
| 22 | 4 | 能力位图 |
| 26 | 28 | 变频：TX LO/RF、RX LO/RF 各 u32，TX/RX 衰减各 f32，flags:u16，temperature:i16 °C |
| 54 | 19 | 最近变频结果：id:u32、operation:u8、target:u8、a/b/c:f32、result:u8 |
| 73 | 19 | 最近阵列结果，同上；id=0 表示无结果 |
| 92 | 26 | TX 阵列：frequency:u32、theta/phi/common/branch:f32、flags:u16、polar:u8、size:u8、temperature:i16 |
| 118 | 26 | RX 阵列，同上 |

变频 flags bit0..11：initialized、ready、CLK lock、TX lock、RX lock、temperature available、TX IF requested、RX IF requested、TX IF sent valid、RX IF sent valid、TX IF sent value、RX IF sent value。
阵列 flags bit0..5：initialized、online、array enabled、PA value、board temperature available、PA value available。
快照由各硬件 owner 在原业务循环更新；最近结果只记录网口请求，Shell 命令不会覆盖该结果编号。发送成功与快照均不替代物理 RF 验收。

## 实现边界

`afd01_rf_test` 只分发/编码；`afd01_rf_test_codec` 仅校验纯数据。
`transceiver_rf_submit` / `antenna_rf_submit` 在模块内映射既有私有命令类型，复用原单槽和执行函数。
没有新增固件任务、队列、自动重试或测试接管开关。仅增加 Debug 请求标识、最近执行结果和 owner 快照，用于查询可观测性。
