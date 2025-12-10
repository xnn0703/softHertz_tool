import os
import subprocess
import sys
import shutil
import argparse
import logging
from datetime import datetime

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'build.log'), encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# 获取当前脚本所在目录
script_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = script_dir

# 定义版本信息
APP_VERSION = "V2.0"
APP_RELEASE_DATE = "2025-10-01"


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='softHertz调试工具打包脚本')
    parser.add_argument('--debug', action='store_true', help='启用调试模式')
    parser.add_argument('--console', action='store_true', default=False, help='显示控制台窗口')
    parser.add_argument('--onedir', action='store_true', default=False, help='生成目录模式的可执行文件')
    parser.add_argument('--name', type=str, default='softHertzDebugTool', help='应用程序名称（建议使用英文）')
    parser.add_argument('--icon', type=str, default=os.path.join(project_dir, 'code', 'soft_hertz_logo_deepspace_blue_512.ico'), help='图标文件路径')
    parser.add_argument('--distpath', type=str, default=os.path.join(project_dir, 'dist'), help='输出目录')
    parser.add_argument('--workpath', type=str, default=os.path.join(project_dir, 'build'), help='工作目录')
    parser.add_argument('--no-install', action='store_true', default=False, help='不自动安装依赖')
    return parser.parse_args()


def install_dependency(package_name, version=None):
    """安装单个依赖"""
    try:
        if version:
            install_cmd = f"{package_name}=={version}"
        else:
            install_cmd = package_name
        
        logger.info(f"正在安装 {install_cmd}...")
        subprocess.run(
            [sys.executable, '-m', 'pip', 'install', install_cmd],
            check=True,
            capture_output=True,
            text=True
        )
        logger.info(f"成功安装 {package_name}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"安装 {package_name} 失败: {e}")
        logger.error(f"错误输出: {e.stderr}")
        return False


def check_dependencies(auto_install=True):
    """检查必要的依赖是否已安装，如未安装则自动安装"""
    # 依赖映射表：包名 -> 导入名
    dependency_map = {
        'PyInstaller>=6.0.0': 'PyInstaller',
        'PyQt5>=5.15.0': 'PyQt5',
        'pyqtgraph>=0.13.0': 'pyqtgraph',
        'pyserial>=3.5': 'serial',  # pyserial的导入名是serial
    }
    
    required_dependencies = list(dependency_map.keys())
    missing_deps = []
    
    for dep in required_dependencies:
        try:
            import_name = dependency_map[dep]
            __import__(import_name)
            logger.info(f"✓ {dep} 已安装")
        except ImportError:
            logger.warning(f"✗ {dep} 未安装")
            missing_deps.append(dep)
    
    if not missing_deps:
        return True
    
    if not auto_install:
        logger.error("缺少必要的依赖，请先安装:")
        for dep in missing_deps:
            logger.error(f"  - {dep}")
        return False
    
    logger.info("开始自动安装缺失的依赖...")
    for dep in missing_deps:
        if not install_dependency(dep):
            logger.error("依赖安装失败")
            return False
    
    logger.info("所有依赖安装完成")
    return True


def clean_old_builds(build_dir, dist_dir, spec_file):
    """清理旧的构建文件"""
    logger.info("开始清理旧的构建文件...")
    
    if os.path.exists(build_dir):
        logger.info(f"删除构建目录: {build_dir}")
        shutil.rmtree(build_dir, ignore_errors=True)
    
    if os.path.exists(dist_dir):
        logger.info(f"删除输出目录: {dist_dir}")
        shutil.rmtree(dist_dir, ignore_errors=True)
    
    if os.path.exists(spec_file):
        logger.info(f"删除spec文件: {spec_file}")
        os.remove(spec_file)
    
    logger.info("清理完成")


def build_exe(args):
    """执行打包命令"""
    # 定义文件路径
    main_script = os.path.join(project_dir, 'code', 'app.py')
    icon_file = args.icon
    spec_file = os.path.join(project_dir, f'{args.name}.spec')
    
    # 检查主脚本是否存在
    if not os.path.exists(main_script):
        logger.error(f"主脚本文件不存在: {main_script}")
        return False
    
    # 检查图标文件是否存在
    if args.icon and not os.path.exists(args.icon):
        logger.warning(f"图标文件不存在: {args.icon}")
    
    # 构建PyInstaller命令 - 使用最简单的配置
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--noconfirm',
        '--onedir',  # 使用目录模式
        '--windowed',  # 窗口模式
        '--name', args.name,
    ]
    
    # 添加图标
    if args.icon and os.path.exists(args.icon):
        cmd.extend(['--icon', icon_file])
    
    # 添加数据文件
    cmd.extend([
        '--add-data', f'{os.path.join(project_dir, "code", "soft_hertz_logo_deepspace_blue_512.png")};.',
    ])
    
    # 添加输出目录
    cmd.extend(['--distpath', args.distpath])
    cmd.extend(['--workpath', args.workpath])
    
    # 添加必要的隐藏导入
    hidden_imports = [
        'serial',
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.QtWidgets',
        'pyqtgraph',
    ]
    
    for imp in hidden_imports:
        cmd.extend(['--hidden-import', imp])
    
    # 添加主脚本
    cmd.append(main_script)
    
    logger.info(f"执行打包命令: {' '.join(cmd)}")
    logger.info(f"开始打包 {args.name} {APP_VERSION}...")
    
    start_time = datetime.now()
    
    try:
        result = subprocess.run(
            cmd, 
            check=True, 
            cwd=project_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='latin-1'  # 使用latin-1编码处理非UTF-8字符
        )
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        logger.info(f"打包成功! 耗时: {duration:.2f}秒")
        logger.info(f"输出目录: {args.distpath}")
        logger.info(f"可执行文件: {os.path.join(args.distpath, f'{args.name}.exe')}")
        
        # 显示打包结果（限制输出长度）
        if result.stdout:
            # 只记录前1000个字符，避免日志过大
            truncated_output = result.stdout[:1000] + "..." if len(result.stdout) > 1000 else result.stdout
            logger.debug(f"打包输出: {truncated_output}")
        
        return True
        
    except subprocess.CalledProcessError as e:
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        logger.error(f"打包失败! 耗时: {duration:.2f}秒")
        logger.error(f"错误代码: {e.returncode}")
        
        # 显示错误输出（限制长度并使用latin-1解码）
        if e.stdout:
            truncated_stdout = e.stdout[:1000] + "..." if len(e.stdout) > 1000 else e.stdout
            logger.error(f"打包输出: {truncated_stdout}")
        
        if e.stderr:
            truncated_stderr = e.stderr[:1000] + "..." if len(e.stderr) > 1000 else e.stderr
            logger.error(f"错误信息: {truncated_stderr}")
        
        return False
    except UnicodeDecodeError as e:
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        logger.error(f"打包过程中发生解码错误! 耗时: {duration:.2f}秒")
        logger.error(f"解码错误: {e}")
        logger.error("这通常是由于PyInstaller输出包含非UTF-8字符导致的")
        
        # 尝试使用不同的编码重新运行，不捕获输出
        logger.info("尝试不捕获输出的方式重新运行...")
        try:
            subprocess.run(
                cmd, 
                check=True, 
                cwd=project_dir
            )
            logger.info(f"打包成功! 耗时: {duration:.2f}秒")
            logger.info(f"输出目录: {args.distpath}")
            logger.info(f"可执行文件: {os.path.join(args.distpath, f'{args.name}.exe')}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"重新运行也失败了: {e}")
            return False


def create_version_file():
    """创建版本信息文件"""
    version_file_content = f'''
VSVersionInfo(\n  ffi=FixedFileInfo(\n    filevers=({APP_VERSION[1:].replace('.', ',')}, 0),\n    prodvers=({APP_VERSION[1:].replace('.', ',')}, 0),\n    mask=0x3f,\n    flags=0x0,\n    OS=0x40004,\n    fileType=0x1,\n    subtype=0x0,\n    date=(0, 0)\n    ),\n  kids=[\n    StringFileInfo(\n      [\n      StringTable(\n        '040904B0',\n        [StringStruct('CompanyName', '软赫电子'),\n        StringStruct('FileDescription', 'softHertz调试工具'),\n        StringStruct('FileVersion', '{APP_VERSION}'),\n        StringStruct('InternalName', 'softHertz调试工具'),\n        StringStruct('LegalCopyright', 'Copyright (C) 2025 软赫电子'),\n        StringStruct('OriginalFilename', 'softHertz调试工具.exe'),\n        StringStruct('ProductName', 'softHertz调试工具'),\n        StringStruct('ProductVersion', '{APP_VERSION}')])\n      ]),\n    VarFileInfo([VarStruct('Translation', [0x409, 1200])])\n  ]\n)\n'''
    
    version_file_path = os.path.join(project_dir, 'version_info.txt')
    with open(version_file_path, 'w', encoding='utf-8') as f:
        f.write(version_file_content)
    
    return version_file_path


def main():
    """主函数"""
    logger.info(f"=== softHertz调试工具打包脚本 {APP_VERSION} ===")
    logger.info(f"发布日期: {APP_RELEASE_DATE}")
    
    # 解析命令行参数
    args = parse_args()
    
    # 检查依赖
    if not check_dependencies(auto_install=not args.no_install):
        sys.exit(1)
    
    # 清理旧的构建文件
    clean_old_builds(args.workpath, args.distpath, os.path.join(project_dir, f'{args.name}.spec'))
    
    # 执行打包
    success = build_exe(args)
    
    # 清理临时文件
    version_file = os.path.join(project_dir, 'version_info.txt')
    if os.path.exists(version_file):
        os.remove(version_file)
    
    if success:
        logger.info("✅ 打包完成!")
        logger.info(f"可执行文件位置: {os.path.join(args.distpath, f'{args.name}.exe')}")
        sys.exit(0)
    else:
        logger.error("❌ 打包失败!")
        sys.exit(1)


if __name__ == '__main__':
    main()