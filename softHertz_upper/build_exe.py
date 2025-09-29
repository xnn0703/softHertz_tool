import os
import subprocess
import sys
import shutil

# 获取当前脚本所在目录
script_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = script_dir

# 定义构建目录
build_dir = os.path.join(project_dir, 'build')
dist_dir = os.path.join(project_dir, 'dist')
spec_file = os.path.join(project_dir, 'app.spec')

# 清理旧的构建文件
if os.path.exists(build_dir):
    shutil.rmtree(build_dir)
if os.path.exists(dist_dir):
    shutil.rmtree(dist_dir)
if os.path.exists(spec_file):
    os.remove(spec_file)

# 构建命令
cmd = [
    sys.executable, '-m', 'PyInstaller',
    '--onefile',  # 生成单个可执行文件
    '--windowed',  # 无控制台窗口
    '--name', 'softHertz调试工具',  # 应用程序名称
    '--icon', os.path.join(project_dir, 'code', 'soft_hertz_logo_deepspace_blue_512.ico'),  # 图标文件
    '--add-data', f'{os.path.join(project_dir, "code", "soft_hertz_logo_deepspace_blue_512.png")};.',  # 添加图标资源
    os.path.join(project_dir, 'code', 'app.py')  # 主脚本文件
]

print(f"执行打包命令: {' '.join(cmd)}")

# 执行打包命令
try:
    subprocess.run(cmd, check=True, cwd=project_dir)
    print("\n✅ 打包成功!")
    print(f"\n可执行文件位置: {os.path.join(dist_dir, 'softHertz调试工具.exe')}")
except subprocess.CalledProcessError as e:
    print(f"❌ 打包失败: {e}")
    sys.exit(1)