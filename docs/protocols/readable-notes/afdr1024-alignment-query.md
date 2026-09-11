# AFDR1024 校准结果查询 0x9E

2026-09-10，现场 RX 源码补充说明，不替代受控协议原件。
依据：`1-AFDR1024/Firmware/Src/main.c:696` 的 `UART2_ReturnAlignData`，
`Inc/main.h` 的 dev_info_Size=10 和 `module_port/app_measure.h` 的 TEMP_TRANS_OFFSET=80。
用户确认先实现 RX；AFDT1024 未确认，不发送本指令。

请求为 `PSA | ID | 01 | 9E | CS`，无数据载荷；ID=1 示例 `50 53 41 01 01 9E 84`。
回复为 `PSA | ID | 0B | 10字节数据 | 9E | CS`，共17字节。
CS 为此前全部字节求和低8位，ID 保留请求地址（含 +0x80），归行取低7位。

数据按顺序为 LINK_ID、TempOffset+80、InitATT、ZcalEn、OFST_VL、OFST_HL、OFST_VR、OFST_HR、ATT_L、ATT_R。
均为单字节，无多字节端序；TempOffset 解码减80，其余值显示原始码，未推定 dB 或角度比例。
LINK_ID 单独保存，不覆盖外层地址。严格接收10字节载荷，错误校验或长度不发布校准状态。

普通“查询全部状态”依次调度 0x9C、0x9F、0x9E，默认帧间调度间隔50ms，沿用非阻塞发送。
客户流量模拟继续使用已有0x9C/0x9F组合。模拟器默认温度偏移0、InitATT=7、ZcalEn=1、其余码0，
这些是模拟数据，不能作为设备校准结果的证明。
