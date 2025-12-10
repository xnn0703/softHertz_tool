# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['D:\\1-project_upper\\1.softHertz_upper\\softHertz_upper\\code\\app.py'],
    pathex=[],
    binaries=[],
    datas=[('D:\\1-project_upper\\1.softHertz_upper\\softHertz_upper\\code\\soft_hertz_logo_deepspace_blue_512.png', '.'), ('C:\\Users\\徐亚彬\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyQt5\\Qt5\\plugins', 'PyQt5/Qt5/plugins')],
    hiddenimports=['serial', 'PyQt5.QtCore', 'PyQt5.QtGui', 'PyQt5.QtWidgets', 'PyQt5.QtNetwork', 'PyQt5.QtWebEngineWidgets', 'pyqtgraph'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'numpy', 'pandas', 'tkinter', 'wx', 'unittest', 'doctest', 'email', 'smtplib', 'imaplib', 'sqlite3', 'psycopg2', 'mysql', 'pywin32_bootstrap'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='softHertz调试工具',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='D:\\1-project_upper\\1.softHertz_upper\\softHertz_upper\\version_info.txt',
    icon=['D:\\1-project_upper\\1.softHertz_upper\\softHertz_upper\\code\\soft_hertz_logo_deepspace_blue_512.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='softHertz调试工具',
)
