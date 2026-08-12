# SoftHertz Tool 工程收敛验收标准

状态：工程迁移与本地验收完成；Windows 原生与真实硬件验收保持开放

## 1. 范围确认

- [x] 已确认远端仓库名为 `softHertz_tool`，本地编号目录为 `2-softHertz_tool` 且直接作为仓库根。
- [x] 已确认 UI 产品名为 `SoftHertz Tool`。
- [x] 已确认 Windows 产物名为 `SoftHertz_Tool.exe`。
- [x] 已确认旧 PyQt5 独有的 DEBUG、TCP、UDP 和多通道曲线功能正式退役。
- [x] 已确认历史 Git 提交和历史 Release 保留，不执行历史重写。

## 2. 工作树结构

- [x] 仓库根目录直接包含 `pyproject.toml`、`src`、`tests`、`packaging`、`docs`。
- [x] 正式实现唯一位于 `src/soft_hertz_tool`。
- [x] `app`、`workspaces`、`devices`、`shared` 和 `resources` 边界完整。
- [x] 不再存在 `softHertz_upper/`。
- [x] 不再存在 `KauDC004A_TestTool/`。
- [x] 不再存在 `code/` 兼容入口。
- [x] 不再存在根目录 `DOC/`，协议资料已迁入 `docs/protocols`。

## 3. 生成物清理

以下命令结果应为空：

```bash
git ls-files | rg '(^|/)(build|dist|__pycache__|\.pytest_cache)(/|$)'
git ls-files | rg '\.(exe|zip|pyc|log|spec)$'
```

- [x] Git 不再跟踪 EXE、ZIP、日志、`.pyc` 和 `.spec`。
- [x] Git 不再跟踪 PyInstaller `build/`、`dist/` 和测试缓存。
- [x] 本地重新运行和打包后，上述生成物仍保持未跟踪或被忽略。

## 4. 命名一致性

- [x] UI 主窗口显示 `SoftHertz Tool`。
- [x] 发射阵列显示 `AFDT1024`。
- [x] 接收阵列显示 `AFDR1024`。
- [x] `AFDTR` 只作为产品工作区名称，不冒充具体硬件型号。
- [x] Python import 根保持 `soft_hertz_tool`。
- [x] Python distribution 和 CLI 保持 `soft-hertz-tool`。
- [x] 当前源码、测试、脚本、CI 和面向当前项目的文档不再引用 `KauDC004A_TestTool`。
- [x] 当前产品身份不再使用 `SoftHertz_AFDTR_Tool` 或 `AFDTR_Tool`。

允许保留旧名称的位置仅限：

- Git 历史；
- v2.2.0～v2.2.2 历史 Release 和历史资产；
- 一次性配置迁移代码及其测试；
- 描述迁移来源的受控迁移文档。

## 5. 安装与入口

- [x] 在新建 Python 3.13 虚拟环境执行 `python -m pip install -e ".[dev]"` 成功。
- [ ] Python 3.9 最低版本在原生 Windows CI 中安装和运行成功。
- [x] `python -m soft_hertz_tool` 能创建主窗口。
- [x] `soft-hertz-tool` 入口可用。
- [x] AFDT1024/AFDR1024 模拟器入口可用。
- [x] AFD01_QS 模拟器入口可用。
- [x] `run.sh` 不依赖旧目录。
- [x] `run.bat` 不依赖旧目录。

## 6. 功能与回归

- [x] 正式测试覆盖迁移前正式测试，并吸收旧兼容套件的有效断言语义。
- [x] 旧 `code/test_serial_improved.py` 的有效断言已被正式测试覆盖。
- [x] 旧 `code/test_qs_features.py` 的有效断言已被正式测试覆盖。
- [x] KaUDC004A 协议构帧、解析和串口驱动回归通过。
- [x] AFDT1024/AFDR1024 V2.2 构帧、解析、查询和模拟器回归通过。
- [x] AFD01_QS V1.6 数据流、阵列选择、速率统计和模拟器回归通过。
- [x] 工作区切换能正确停用旧工作区并过滤旧连接代际信号。
- [x] 关闭窗口时所有串口线程和日志线程均可确认退出。

建议最低验证命令：

```bash
QT_QPA_PLATFORM=offscreen python -m pytest -q
python -m compileall -q src tests packaging
git diff --check
```

## 7. 设置、日志和资源

- [x] 首次启动能读取旧 `QSettings("SoftHertz", "AFDTR_Tool")` 中的有效设备选择。
- [x] 新设置写入 `QSettings("SoftHertz", "SoftHertz_Tool")`。
- [x] 新日志写入 `Documents/SoftHertz/SoftHertz_Tool/logs`。
- [x] 旧 `Documents/SoftHertz/AFDTR_Tool/logs` 不被删除或覆盖。
- [x] 日志保持 50 MiB 轮转策略。
- [x] 源码运行、editable install 和 macOS PyInstaller 产物均可加载 PNG/ICO 资源。

## 8. Windows 构建

- [x] GitHub Actions 配置从仓库根目录安装和测试。
- [x] PyInstaller 使用 `packaging/entrypoint.py`。
- [x] 产物名为 `SoftHertz_Tool.exe`。
- [x] Artifact 名为 `SoftHertz_Tool-windows`。
- [x] 构建依赖版本已固定，Python 3.9 依赖解析与源码语法兼容检查通过。
- [ ] Windows 产物实测包含 Qt Core/Gui/Widgets、运行库和 PNG/ICO 资源。
- [ ] 在干净 Windows 10 1809+ 或 Windows 11 环境完成原生启动冒烟。
- [x] workflow 配置生成 SHA256，并随 tag Release 上传。

Windows CI 打包成功不等于客户环境和真实设备验收完成。

## 9. 文档

- [x] README 只描述当前项目功能、架构、运行、测试、打包、规范和 TODO。
- [x] README 不把协作过程或提交过程写成开发流水账。
- [x] 新增设备流程明确采用 `protocol/stream/driver/panel/simulator` 纵向切片。
- [x] 依赖方向明确为 `app -> workspaces -> devices -> shared`。
- [x] 受控协议原件与 Markdown 转写文档分开保存。
- [x] 未完成的 Windows、硬件和协议原件验收边界继续明确标注。

## 10. Git 与远端

- [x] 目录迁移使用普通提交记录，可从父提交恢复旧工作树。
- [x] 旧 PyQt5 代码线仍可从 Git 历史访问。
- [x] 未执行历史重写、强推或远端分支删除。
- [x] `master` 是 Gitee 默认且唯一的开发主线；非主线历史分支仅用于保留研发轨迹。
- [x] Gitee 仓库改名为 `softHertz_tool` 后，`origin` URL 已更新并验证。
- [x] GitHub 仓库改名为 `softHertz_tool` 后，`github` URL 已更新并验证。
- [x] GitHub 仍只用于发布，未同步本次开发提交或创建 Release。
- [x] 本地编号目录最终改名为 `2-softHertz_tool`，中间 `softHertz_tool` 已去除，虚拟环境已重建。

## 11. 验收边界

以下状态必须分开记录，不得互相替代：

- [x] 源码静态检查通过。
- [x] 主机单元/集成测试通过。
- [x] 模拟器测试通过。
- [x] macOS 本地运行/打包通过。
- [ ] Windows 原生 EXE 启动通过。
- [ ] KaUDC004A 真实设备闭环通过。
- [ ] AFDT1024 真实设备闭环通过。
- [ ] AFDR1024 真实设备闭环通过。
- [ ] AFD01_QS 真实设备闭环通过。
