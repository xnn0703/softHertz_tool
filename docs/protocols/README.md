# 协议资料索引

协议实现和联调结论必须以受控原件、当前验收标准和实际设备证据为准，不能仅依据历史代码反推。

## 目录

### `controlled-originals/`

保存未经改写的受控协议原件：

- KaUDC004A 控制命令；
- AFDT1024 发射阵列 V2.1、V2.2；
- AFDR1024 接收阵列 V2.1、V2.2。

原件文件名、版本号和正文不得为配合代码命名而修改。

### `readable-notes/`

保存便于源码检索和评审的 Markdown 转写：

- `AFDT1024_TX_Protocol.md`
- `AFDR1024_RX_Protocol.md`

转写文档必须标明来源版本。转写内容与受控原件冲突时，以受控原件为准。

## 当前缺口

AFD01_QS 当前实现以 QS V1.7 为目标，但仓库尚未保存可入库的受控协议原件。当前代码包含
`0x01`～`0x0A` 控制、`0x0B/0xA1` 阵列档位和 `0xA0` 实时状态处理；这些实现与主机/模拟器
测试均不能替代受控原件。新增或修改 AFD01_QS 字段、端序、缩放和校验范围前，应先补齐原件并
逐项核对。

`0x0B/A1` 的 TX/RX 字段采用客户档位 `1～5`，依次表示 `8×8`、`10×10`、`12×12`、
`14×14`、`16×16` 有效子阵。查询请求仍固定发送 `op=0, tx_level=0, rx_level=0`；
设置请求中 `0xFF` 仍表示对应通道保持不变。旧值 `6～8` 不属于 V1.8 档位编码，上位机不会
自动按旧语义解释。`0xA1` 的载荷长度固定为 2 字节，只包含当前
`tx_level, rx_level`；不包含结果、电源或应用状态字段，旧 5 字节 A1 不兼容。

## 代码位置

| 设备 | 协议实现 |
|---|---|
| KaUDC004A | `src/soft_hertz_tool/devices/kaudc004a/protocol.py` |
| AFDT1024 / AFDR1024 | `src/soft_hertz_tool/devices/afdtr1024/protocol.py` |
| AFD01_QS | `src/soft_hertz_tool/devices/afd01_qs/protocol.py` |
