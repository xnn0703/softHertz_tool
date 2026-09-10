# 固定/自由频点配置

2026-09-10 用户已确认并完成软件实现。联合计划与验收位于固件仓库
`code/target/ka_rf_unit/doc/frequency_commands_20260910/`。
上位机范围为 protocol/driver/panel/simulator、回归测试、协议说明及 README。
流解析器无需特殊分支，沿用已有通用拆帧，并增加 0x96 每个切分位置回归。
协议当前合同见 `docs/protocols/readable-notes/ka-rf-unit-frequency-20260910.md`。
