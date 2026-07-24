# SoftHertz Tool 工程收敛实施记录

状态：工程、仓库与本地目录迁移完成；Windows 原生和真实硬件验收待完成

## 1. 实施基线

- 基线分支：`master`
- 基线提交：`ef82881`
- 迁移前正式包与兼容回归合计：`183 passed`（包含两套入口中的重复断言）
- 正式实现来源：`src/soft_hertz_tool` 的设备纵向切片架构

迁移不改写 Git 历史。旧 PyQt5 实现、旧兼容入口和历史生成物仍可从基线提交及其祖先提交恢复。

## 2. 已完成内容

### 2.1 工程根收敛

- 将 `src/soft_hertz_tool`、`tests`、`pyproject.toml` 和 `packaging` 移到仓库根。
- 将受控协议原件移到 `docs/protocols/controlled-originals`。
- 将可检索协议说明移到 `docs/protocols/readable-notes`。
- 删除当前工作树中的旧 PyQt5 工程、兼容入口和设备专用套壳目录。
- 删除失效的计划、打包记录、日志、缓存、EXE、ZIP、`.spec` 和 PyInstaller 中间产物。
- 扩展 `.gitignore`，阻止生成物重新进入版本控制。
- 增加仓库结构和 Git 生成物跟踪检查。

### 2.2 产品身份

- UI 产品名统一为 `SoftHertz Tool`。
- Windows 产物名统一为 `SoftHertz_Tool.exe`。
- Python distribution/CLI 保持 `soft-hertz-tool`。
- Python import 根保持 `soft_hertz_tool`。
- Qt 设置命名空间改为 `SoftHertz/SoftHertz_Tool`。
- 当前设置缺失时，从旧 `SoftHertz/AFDTR_Tool` 复制 `device_model`；旧设置不删除、不修改。
- 新日志写入 `Documents/SoftHertz/SoftHertz_Tool/logs`；旧日志目录不移动、不删除。
- Qt 进程、主窗口、设置和日志共用集中身份常量。

### 2.3 架构与兼容收尾

- 保持 `app -> workspaces -> devices -> shared` 依赖方向。
- 增加自动化依赖边界检查。
- protocol、stream 和 models 禁止依赖 Qt 或 pyserial。
- 删除资源定位对旧 `code/` 目录的兼容回退；资源缺失时显式报错。
- 移除设备包对模拟器模块的提前导入，模块方式启动模拟器不再产生 `runpy RuntimeWarning`。
- 旧 PyQt5 独有的 DEBUG、TCP、UDP、广播和通用曲线能力已正式退役，未复制到新架构。

### 2.4 启动、打包与 CI

- `run.sh`、`run.bat` 从仓库根安装 editable package。
- 启动脚本支持 `app`、`afdtr-sim`、`qs-sim` 三种模式。
- 增加 `--smoke`，创建真实主窗口后自动关闭。
- PyInstaller 从 `packaging/entrypoint.py` 进入。
- 构建前只清理仓库内 `build/pyinstaller` 和 `dist`。
- Windows 产物固定为 `dist/SoftHertz_Tool.exe`。
- Windows workflow 先在 Python 3.9 与 3.11.9 上运行正式测试，再进入发布构建。
- Python 3.9 最低版本矩阵固定 pytest 8.4.2；Python 3.11 发布环境固定 pytest 9.0.3。
- 两套环境均固定 PySide6 6.9.3、PyInstaller 6.20.0 和配套 hooks。
- workflow 执行正式测试、EXE 启动冒烟、SHA256 生成、Artifact 上传和 tag Release。

### 2.5 当前项目文档

- README 已收敛为当前项目功能、架构、运行、测试、打包、规范、TODO 和接手顺序。
- 当前架构、开发规范、新增设备流程和验收边界分别维护在：
  - `docs/architecture/overview.md`
  - `docs/development/standards.md`
  - `docs/development/adding-device.md`
  - `docs/development/acceptance-boundaries.md`
- 过程性旧文档已删除；有效约束已合并到当前文档。

### 2.6 Git 与仓库迁移

- 目录迁移与产品重命名提交为 `542268f`，过时代理规划文档清理提交为 `f80390c`。
- 迁移提交以普通快进方式进入 Gitee 默认开发主线 `master`，未改写历史、强推或删除远端历史分支。
- Gitee 仓库已改名为 `softHertz_tool`，开发 remote 为 `https://gitee.com/soft-hertz/softHertz_tool.git`。
- GitHub 发布仓库已改名为 `softHertz_tool`，remote 为 `https://github.com/xnn0703/softHertz_tool.git`。
- 本次开发提交只推送 Gitee；GitHub 现有发布代码线未同步、未创建 Release。
- 本地仓库目录已改名为 `softHertz_tool`，并在新路径重新创建 editable 虚拟环境。

## 3. 测试吸收

- 旧串口改进测试的 50 个用例名称均已进入正式测试树。
- 旧 QS 测试的 11 类语义由设备、共享组件和集成测试覆盖。
- 唯一正式 pytest 入口为根目录 `tests`。
- 当前不再维护依赖旧 `code/` 路径的第二套测试入口。

## 4. 本地验证

验证环境：

- macOS arm64
- Python 3.13.13
- PySide6 6.9.3
- pyserial 3.5
- pytest 9.0.3
- PyInstaller 6.20.0
- pyinstaller-hooks-contrib 2026.6

| 检查 | 结果 |
|---|---|
| `QT_QPA_PLATFORM=offscreen python -m pytest -q` | `125 passed` |
| `python -m compileall -q src tests packaging` | 通过 |
| `bash -n run.sh` | 通过 |
| `run.sh app --smoke` | 通过 |
| AFDT1024/AFDR1024 模拟器 `--help` | 通过，无提前导入告警 |
| AFD01_QS 模拟器 `--help` | 通过 |
| `python -m pip check` | 通过 |
| GitHub Actions YAML 解析 | 通过 |
| `git diff --check` | 通过 |
| macOS PyInstaller clean build | 通过 |
| macOS 打包产物 `--smoke` | 通过 |

macOS 本地产物仅用于验证入口、资源收集和生命周期，不是 Windows Release 资产。

## 5. 待完成门槛

- 更新后的 GitHub Actions 尚未在 Windows runner 实际执行。
- Python 3.9 最低版本目前只完成依赖解析和语法兼容检查，尚未完成原生 Windows 运行。
- `SoftHertz_Tool.exe` 尚未在干净 Windows 10 1809+ 或 Windows 11 客户环境验证。
- KaUDC004A、AFDT1024、AFDR1024、AFD01_QS 真实设备验收仍保持未完成。
- AFD01_QS V1.6 受控协议原件仍待补入。
- 历史日志没有自动迁移或删除；需要保留运维可见性。

## 6. 结论

工程已经从并列旧实现与设备专用套壳收敛为单一多设备项目根。源码、测试、打包和文档现在围绕同一个 `soft_hertz_tool` 包组织；新增设备应继续采用设备纵向切片和共享基础设施，不恢复旧工程的横向复制结构。
