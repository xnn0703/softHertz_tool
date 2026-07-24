# SoftHertz Tool 工程收敛与重命名计划

状态：已完成（Windows 原生与真实硬件验收保持开放）
完成日期：2026-07-24
目标分支：`master`
目标产品：多设备集合上位机

## 1. 目标

将当前仓库收敛为唯一的 PySide6 多设备上位机工程，消除旧 PyQt5 实现、新工程套壳目录、设备专用产品名和构建生成物对后续开发的干扰。

本次迁移完成后：

- 仓库和本地工程目录统一为 `softHertz_tool`。
- 仓库根目录就是 Python 工程根，不再额外嵌套同名工程目录。
- 正式实现只保留 `src/soft_hertz_tool`。
- `app`、`workspaces`、`devices`、`shared` 的现有模块边界保持不变。
- Git 历史继续保留旧 PyQt5 代码线和既有研发提交，不改写历史。
- 当前工作树不再保留旧 PyQt5 目录、兼容入口和历史构建生成物。

## 2. 统一命名

| 使用场景 | 目标名称 |
|---|---|
| Gitee 仓库 | `softHertz_tool` |
| GitHub 发布仓库 | `softHertz_tool` |
| 本地仓库目录 | `softHertz_tool` |
| UI 产品名 | `SoftHertz Tool` |
| Windows 可执行文件 | `SoftHertz_Tool.exe` |
| CI Artifact | `SoftHertz_Tool-windows` |
| Python distribution | `soft-hertz-tool` |
| Python import 包 | `soft_hertz_tool` |
| CLI 命令 | `soft-hertz-tool` |
| Qt 配置应用名 | `SoftHertz_Tool` |
| 日志目录 | `Documents/SoftHertz/SoftHertz_Tool/logs` |

设备和工作区名称保持：

- 工作区：`AFDTR`
- 发射阵列：`AFDT1024`
- 接收阵列：`AFDR1024`
- 变频组件：`KaUDC004A`
- 数字波束设备：`AFD01_QS`

内部共用模块 `devices/afdtr1024` 可以保留，该名称只表示 AFDT1024/AFDR1024 的共用实现。

## 3. 目标目录

```text
softHertz_tool/
├── .github/
│   └── workflows/
├── docs/
│   ├── architecture/
│   ├── development/
│   ├── protocols/
│   │   ├── controlled-originals/
│   │   └── readable-notes/
│   └── project-restructure/
├── packaging/
│   ├── entrypoint.py
│   └── build_windows.py
├── src/
│   └── soft_hertz_tool/
│       ├── app/
│       ├── devices/
│       │   ├── afd01_qs/
│       │   ├── afdtr1024/
│       │   └── kaudc004a/
│       ├── resources/
│       ├── shared/
│       │   ├── observability/
│       │   ├── transport/
│       │   └── ui/
│       └── workspaces/
├── tests/
│   ├── devices/
│   ├── integration/
│   └── shared/
├── .gitignore
├── pyproject.toml
├── README.md
├── run.bat
└── run.sh
```

最终工作树中不再存在：

```text
softHertz_upper/
KauDC004A_TestTool/
KauDC004A_TestTool/code/
DOC/
```

## 4. 范围

### 4.1 保留并迁移

- `KauDC004A_TestTool/src/soft_hertz_tool` 移至根目录 `src/soft_hertz_tool`。
- 正式测试移至根目录 `tests`。
- `pyproject.toml` 和依赖声明移至仓库根目录。
- PyInstaller 入口和构建脚本移至 `packaging`。
- 受控协议原件和有效协议说明统一移至 `docs/protocols`。
- 当前有效的架构、开发规范和验收说明整理到 `docs`。
- 启动脚本、CI、README 和开发说明全部改为根目录入口。

### 4.2 删除当前工作树中的旧内容

- 删除旧 PyQt5 目录 `softHertz_upper/`。
- 删除 `KauDC004A_TestTool/code/` 兼容入口。
- 删除已被正式测试覆盖的旧测试副本。
- 从 Git 索引移除 EXE、ZIP、日志、`.pyc`、`.spec`、`build/`、`dist/` 和缓存目录。
- 删除已经失效的历史计划、打包记录和设备专用工程说明。

以上内容仍可从 Git 历史或既有 Release 恢复；本计划不执行历史重写。

### 4.3 明确退役的旧功能

旧 PyQt5 代码中存在、当前 PySide6 正式包尚未实现的功能：

- DEBUG 设备页面和多通道曲线显示；
- TCP 客户端/服务端；
- UDP 和广播通信。

按“删除全部旧实现”的目标，本计划将这些能力标记为正式退役，不把旧代码直接复制进新架构。未来如重新立项，应按 `devices` 和 `shared/transport` 的现有边界重新实现。

### 4.4 不在本次范围

- 不改写或压缩 Git 历史。
- 不修改 v2.2.0～v2.2.2 的历史 Release 和资产名称。
- 不宣称已完成真实设备验收。
- 不在缺少原生 Windows 运行证据时宣称新 EXE 已通过客户环境验收。

## 5. 实施步骤

### 阶段 A：工作树隔离

1. 复核并隔离当前已有的未提交改动。
2. 创建迁移分支，避免在验证完成前直接改变 `master`。
3. 记录迁移前测试基线和 Git 提交位置。

### 阶段 B：目录收敛

1. 使用 Git 可追踪的移动操作将正式包、测试、打包和有效文档迁到仓库根目录。
2. 将 `code/build_spec.py` 改造为 `packaging/build_windows.py`。
3. 确认旧兼容测试中的有效断言已被正式测试覆盖。
4. 删除 `KauDC004A_TestTool/code/` 和空的套壳目录。
5. 删除旧 PyQt5 目录和已确认退役的旧功能实现。

### 阶段 C：产品身份统一

1. 更新窗口标题、可执行文件名、Artifact 名和打包脚本。
2. 将 Qt 配置应用名改为 `SoftHertz_Tool`。
3. 首次启动时读取旧 `AFDTR_Tool` 配置并迁移有效设置。
4. 新日志写入 `SoftHertz_Tool/logs`；旧日志目录保持原样，不自动删除。
5. 全量扫描并清除当前源码、脚本和文档中的旧项目路径与旧产品名。

### 阶段 D：构建和文档

1. CI 从仓库根目录安装 `.[dev]`、执行正式测试并打包。
2. README 只描述当前工程，不把分支合并和协作过程写成项目内容。
3. 文档固定新增设备的纵向切片结构和依赖方向。
4. 清理被 Git 跟踪的生成物，并验证 `.gitignore` 可阻止再次提交。

### 阶段 E：验证、提交和远端迁移

1. 执行验收清单中的静态检查、测试、离屏 UI 和打包检查。
2. 验证通过后提交目录迁移与产品重命名。
3. 合并到 `master` 并先推送 Gitee。
4. 将 Gitee 仓库改名为 `softHertz_tool`，随后更新并验证 `origin`。
5. GitHub 继续只承担发布；代码验证通过后再将仓库改名为 `softHertz_tool` 并更新 `github` remote。
6. 最后将本地仓库目录改名为 `softHertz_tool`，重建虚拟环境并重新打开工程。

## 6. 风险和控制

| 风险 | 控制措施 |
|---|---|
| 旧功能被无声删除 | 在验收标准中明确 DEBUG/TCP/UDP/曲线功能为已批准退役 |
| 旧配置丢失 | 增加一次性 QSettings 兼容读取和迁移测试 |
| 历史日志看似消失 | 不移动、不删除旧日志，只切换新日志写入路径 |
| 旧测试随兼容目录消失 | 删除前建立断言覆盖映射并运行正式回归 |
| CI 仍依赖旧目录 | 从根目录安装、测试和打包，扫描旧路径引用 |
| 生成物再次入库 | 从 Git 索引移除并用 `.gitignore` 和 CI 检查阻止 |
| Windows EXE 仍无法启动 | 固定依赖并增加 Windows 原生产物启动冒烟 |
| 协议文档权威性混乱 | 受控原件与可读转写分目录保存 |

## 7. 回滚和可恢复性

- 迁移前后的每一步均通过普通 Git 提交记录。
- 旧 PyQt5 实现、兼容入口和历史生成物可从迁移前提交检出。
- 不执行强推、历史重写或远端分支删除。
- 远端仓库改名前先保存并验证旧、新 remote URL。
