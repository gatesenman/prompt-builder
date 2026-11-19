# -*- mode: python ; coding: utf-8 -*-
# PromptBuilder 2.8 — Role/Category/Prompt tree + "//" quick-pick (PyInstaller 6, onedir)
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

app_modules = [
    'api', 'paths', 'settings_store', 'prompt_syntax', 'prompts_store', 'library_model',
    'winapi', 'winput', 'keyhook', 'caret', 'quickpick',
    'tray_icon', 'autostart', 'atomic_io', 'applog', 'textcheck', 'elevation',
    'revisions_store', 'history_store',
    'ai_crypto', 'ai_providers', 'ai_service',
]
try:
    comtypes_mods = ['comtypes', 'comtypes.client', 'comtypes.automation', 'comtypes.stream'] + \
        collect_submodules('comtypes.gen')
except Exception:
    comtypes_mods = ['comtypes', 'comtypes.client']

a = Analysis(
    ['src/app.py'],
    pathex=['src'],
    binaries=[],
    datas=[
        ('web', 'web'),
        ('data/examples.json', 'data'),
        ('data/builtins.json', 'data'),
        ('assets/icon.png', 'assets'),
        ('assets/icon.ico', 'assets'),
        ('VERSION.txt', '.'),
    ],
    hiddenimports=app_modules + comtypes_mods + [
        'webview', 'webview.platforms.edgechromium', 'webview.platforms.winforms',
        'pystray', 'pystray._win32', 'PIL', 'clr', 'bottle', 'proxy_tools',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # smaller bundle: GUI toolkits / pywebview backends we never use, test & dev tooling,
    # pywin32 (everything Win32 goes through ctypes)
    excludes=[
        'keyboard', 'pyperclip', 'tkinter', '_tkinter', 'turtle', 'turtledemo', 'idlelib',
        'unittest', 'doctest', 'pydoc', 'pydoc_data', 'lib2to3', 'test', 'tests',
        'setuptools', 'pip', 'ensurepip', 'venv',  # distutils omitted: PyInstaller hook conflicts on 3.12+
        'webview.platforms.qt', 'webview.platforms.gtk', 'webview.platforms.cocoa',
        'webview.platforms.android', 'webview.platforms.cef', 'webview.platforms.mshtml',
        'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'qtpy', 'gi', 'cefpython3',
        'numpy', 'IPython', 'matplotlib', 'PIL.ImageQt', 'PIL.ImageTk',
        'win32com', 'win32api', 'win32con', 'win32gui', 'pythoncom', 'pywintypes',
        'xmlrpc', 'sqlite3', 'curses', 'lzma_unused',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PromptBuilder',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.ico',
    contents_directory='_internal',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='PromptBuilder',
)
