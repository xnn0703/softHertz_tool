# 文档与代码注释同步验收标准

状态：已完成

## 1. 文档一致性

- [x] README 中的工作区、设备名称、功能、命令、目录和 TODO 可追溯到当前实现；
- [x] 架构文档与当前依赖方向、线程模型、生命周期和 registry 一致；
- [x] 开发规范与实际支持的 Python、PySide6、测试和打包方式一致；
- [x] 新增设备指南引用的接口和目录在当前工程中存在；
- [x] 测试结构文档列出当前正式测试文件，不遗漏资源、入口和产品身份测试；
- [x] Windows、真实设备、协议原件和日志保留策略等开放项没有被误标为完成；
- [x] README 不包含协作对话或操作流水账。

## 2. 注释覆盖

- [x] `src/soft_hertz_tool` 的 Python 模块、类、函数和方法均有 docstring；
- [x] `packaging` 的 Python 模块、函数均有 docstring；
- [x] 公共或复杂函数说明功能、输入、输出和关键异常/状态约束；
- [x] Qt 槽、线程、生命周期和协议函数的副作用或线程归属清楚；
- [x] 关键流程具有解释设计原因的行内注释；
- [x] 注释未使用错误的公开设备名称；
- [x] 注释未把模拟器或主机验证描述为真实硬件验收。

## 3. 行为保持

- [x] 协议、UI、串口、线程、日志和打包逻辑没有行为性修改；
- [x] 生产代码仍支持 Python 3.9 语法；
- [x] 正式测试全部通过；
- [x] 应用 `--smoke` 入口通过；
- [x] AFDT1024/AFDR1024 与 AFD01_QS 模拟器入口可加载；

## 4. 验证命令

```bash
QT_QPA_PLATFORM=offscreen python -m pytest -q
python -m compileall -q src tests packaging
python -m soft_hertz_tool --smoke
python -m soft_hertz_tool.devices.afdtr1024.simulator --help
python -m soft_hertz_tool.devices.afd01_qs.simulator --help
git diff --check
```
