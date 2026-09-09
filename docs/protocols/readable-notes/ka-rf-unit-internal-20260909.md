# KA_RF_UNIT 内部测试协议 20260909

配套独立文档：《【内部】Ka波段射频单元控制接口协议-20260909.docx》。不修改客户协议原件。
沿用 PSA / version 1 / 大端 / CRC-16 CCITT-FALSE / RS422 460800 8N1。

| 请求 → 响应 | payload | 语义 |
|---|---|---|
| 0x40 → C0 | enable:u8，0/1 | 独立 PA |
| 0x41 → C1 | enable:u8，0/1 | 独立 TX IF |
| 0x42 → C2 | enable:u8，0/1 | 独立 RX IF |
| 0x43 → C3 | target、TX 行/列、RX 行/列，各 u8 | 芯片行列位 bit0..7；不是独立物理天线单元 |
| 0x44 → C4 | target:u8，TX theta/phi、RX theta/phi，各 u16 BE | 0.01°，theta 0..9000，phi 0..35999 |
| 0x45 → C5 | 空 | 内部控制快照 |
| 0x46 → C6 | target、TX 干路/支路、RX 干路/支路，均 u8 | TA/RA 阵列衰减，单位 0.5 dB |
| 0x47 → C7 | 空 | BF 类型及衰减发送记录 |

target=1 TX、2 RX、3 双阵面；只处理选中阵面。0x44 在主控使用最近接受 RF 转换，
不由 Panel 转 raw。TX/RX f0=30000/20270 MHz；相位按 lroundf、模 4096 编码。
客户 0x12 覆盖 TX mask 和 PA，0x13 覆盖 RX mask，均保持 IF；内部请求不持久化。

设置响应仅 1B result。C5 成功载荷 13B：result、snapshot_version=1、requested_flags、
sent_valid_flags、sent_value_flags、TX 请求行/列、RX 请求行/列、TX 发送行/列、RX 发送行/列。
flags bit0 PA、bit1 TX IF、bit2 RX IF、bit3 TX 阵列、bit4 RX 阵列，其他 0。
阵列行/列均非 0 才表示有效开启。错误 C5 仍为 1B result，不接受 1B OK 冒充快照。

上位机内部分页区分输入请求、设备应答和最近发送记录。查询不覆盖操作输入；断连清空。
阵列发送失败保留上次完整记录，IF 部分写入失败清除有效位；有效或值相同均不能证明物理应用。
响应 OK 只表示请求接受；实板 PA、IF、逐位方向和波束时延仍需仪表验收。

实现和验收记录：`docs/development/ka-rf-unit-internal-20260909/`。

TA/RA 不同于 0x11 变频衰减。BF0 干路仅 0/8 dB，BF1 干路和两型支路均 0..7.5 dB、步进 0.5。
主控从有效阵列 INFO 确定 BF；未知返回 04，范围错误返回 03，全部选中侧验证通过才提交。
设置不持久化、不改变 PA/IF/行列。发送前 owner 再校验 INFO，失败不自动重发。

C7 成功载荷 10B：result、version=1、bf_valid_mask、tx_bf、rx_bf、attenuation_sent_valid_mask、
tx_common、tx_branch、rx_common、rx_branch。mask bit0 TX、bit1 RX；BF 0/1 对应 BF0/BF1，无效 FF；
衰减单位 0.5 dB。查询展示最近完整发送记录，不表示请求完成或 RF 已应用；错误响应单字节 result。
旧 C5 仍为 13B。模拟器使用明确的模拟 BF 配置 TX=BF0/RX=BF1，不作为真实硬件型号依据。
