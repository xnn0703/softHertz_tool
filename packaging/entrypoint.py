"""PyInstaller 使用的稳定脚本入口。

命令行参数原样交给正式模块入口，因此打包产物同样支持 ``--smoke``。
"""

from soft_hertz_tool.__main__ import main


if __name__ == "__main__":
    raise SystemExit(main())
