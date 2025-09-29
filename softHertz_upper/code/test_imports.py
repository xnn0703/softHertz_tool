import sys
import os

# 将当前目录添加到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 定义颜色常量用于输出
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

# 测试函数
def test_import(module_name, import_path):
    print(f"\n测试导入 {Colors.BOLD}{module_name}{Colors.ENDC}...")
    try:
        exec(f"import {import_path}")
        print(f"{Colors.GREEN}✓ 成功导入 {module_name}{Colors.ENDC}")
        return True
    except ImportError as e:
        print(f"{Colors.RED}✗ 导入 {module_name} 失败: {e}{Colors.ENDC}")
        return False

# 主函数
def main():
    print(f"{Colors.BOLD}\n===== softHertz串口调试工具导入测试 ====={Colors.ENDC}")
    print(f"Python 版本: {sys.version}")
    print(f"当前路径: {os.path.dirname(os.path.abspath(__file__))}")
    
    # 测试导入通用组件
    common_success = True
    common_success &= test_import("SerialController", "common.serial_controller")
    common_success &= test_import("ProtocolBase", "common.protocol_base")
    common_success &= test_import("DeviceBase", "common.device_base")
    
    # 测试导入设备特定组件
    devices_success = True
    devices_success &= test_import("KauDC004AProtocol", "devices.kaudc004a_protocol")
    devices_success &= test_import("KauDC004ADevice", "devices.kaudc004a_device")
    
    # 测试导入UI组件
    ui_success = True
    ui_success &= test_import("UIBase", "ui.ui_base")
    ui_success &= test_import("KauDC004AUI", "ui.kaudc004a_ui")
    
    # 测试导入应用主程序
    app_success = test_import("Application", "app")
    
    # 汇总结果
    print(f"\n{Colors.BOLD}===== 测试结果汇总 ====={Colors.ENDC}")
    print(f"通用组件: {Colors.GREEN if common_success else Colors.RED}{'通过' if common_success else '失败'}{Colors.ENDC}")
    print(f"设备特定组件: {Colors.GREEN if devices_success else Colors.RED}{'通过' if devices_success else '失败'}{Colors.ENDC}")
    print(f"UI组件: {Colors.GREEN if ui_success else Colors.RED}{'通过' if ui_success else '失败'}{Colors.ENDC}")
    print(f"应用程序: {Colors.GREEN if app_success else Colors.RED}{'通过' if app_success else '失败'}{Colors.ENDC}")
    
    if common_success and devices_success and ui_success and app_success:
        print(f"\n{Colors.GREEN}{Colors.BOLD}✓ 所有组件导入成功！项目结构正常。{Colors.ENDC}")
        print(f"\n使用以下命令启动应用程序:")
        print(f"{Colors.BOLD}python app.py{Colors.ENDC}")
    else:
        print(f"\n{Colors.RED}{Colors.BOLD}✗ 部分组件导入失败，请检查代码和依赖项。{Colors.ENDC}")

if __name__ == "__main__":
    main()