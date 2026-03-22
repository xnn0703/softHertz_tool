from PyInstaller.__main__ import run

if __name__ == "__main__":
    run(
        [
            "main_qt6.py",
            "--name=SoftHertz_AFDTR_Tool",
            "--windowed",
            "--onefile",
            "--icon=NONE",
            "--add-data=afdt1024_protocol.py;.",
            "--add-data=protocol.py;.",
            "--hidden-import=serial",
            "--hidden-import=serial.tools.list_ports",
            "--hidden-import=PySide6",
            "--hidden-import=PySide6.QtCore",
            "--hidden-import=PySide6.QtGui",
            "--hidden-import=PySide6.QtWidgets",
        ]
    )
