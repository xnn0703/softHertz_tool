# hook_qt5_plugins.py
# 设置Qt插件路径，解决中文用户名问题

import os
import sys

# 添加当前目录到插件路径
sys.path.append(os.path.dirname(sys.executable))

# 设置Qt插件路径环境变量
os.environ['QT_PLUGIN_PATH'] = os.path.dirname(sys.executable)

# 打印调试信息
print(f"QT_PLUGIN_PATH: {os.environ.get('QT_PLUGIN_PATH')}")
print(f"当前目录: {os.getcwd()}")
print(f"可执行文件目录: {os.path.dirname(sys.executable)}")