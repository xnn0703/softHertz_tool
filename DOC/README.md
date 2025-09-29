# KauDC004A_TestTool

#### 介绍
KauDC004A测试工具是一款用于KauDC004A和AFD01_QS设备的串口上位机调试工具，可以实现设备参数的读取、修改、命令发送以及设备状态监控等功能。

#### 软件架构
软件采用模块化设计，主要包含以下几个部分：
- **app.py**：应用程序主入口，负责整合各模块并启动应用
- **serial_controller.py**：串口通信控制模块
- **devices/**：设备协议和设备类实现
- **ui/**：用户界面实现
- **common/**：通用工具类和函数

#### 安装教程

1. 确保已安装Python 3.7或更高版本
2. 安装项目依赖：
   ```bash
   pip install pyserial>=3.5
   ```
3. 直接运行app.py启动应用：
   ```bash
   python code/app.py
   ```

#### 使用说明

1. 选择正确的串口和波特率
2. 点击连接按钮连接设备
3. 根据需要读取或修改设备参数
4. 可以发送命令控制设备
5. 实时监控设备状态信息

#### 打包指南
如需将程序打包为可执行文件(.exe)，请按照以下步骤操作：

1. 安装PyInstaller：
   ```bash
   pip install pyinstaller
   ```
2. 确保已安装项目依赖：
   ```bash
   pip install pyserial>=3.5
   ```
3. 运行打包脚本：
   ```bash
   python build_exe.py
   ```
   或直接使用PyInstaller命令：
   ```bash
   pyinstaller --onefile --windowed --name "softHertz调试工具" --icon=code/soft_hertz_logo_deepspace_blue_512.ico code/app.py
   ```
4. 打包完成后，可执行文件将位于dist目录下

#### 参与贡献

1. Fork 本仓库
2. 新建 Feat_xxx 分支
3. 提交代码
4. 新建 Pull Request
