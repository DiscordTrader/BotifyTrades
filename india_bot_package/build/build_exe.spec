# PyInstaller spec for India Trading Bot
# console=False for GUI-only operation (no black console window)

import os
import sys
import glob
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
PROJECT_ROOT = os.path.dirname(SPEC_DIR)

# Collect broker submodules
try:
    upstox_imports = collect_submodules('upstox_client')
except:
    upstox_imports = []

try:
    dhanhq_imports = collect_submodules('dhanhq')
except:
    dhanhq_imports = []

try:
    kiteconnect_imports = collect_submodules('kiteconnect')
except:
    kiteconnect_imports = []

try:
    telethon_imports = collect_submodules('telethon')
except:
    telethon_imports = []

# Find PyArmor runtime (created during obfuscation)
pyarmor_runtime_data = []
pyarmor_hidden = []
for pattern in ['src/pyarmor_runtime_*', 'pyarmor_runtime_*']:
    for runtime_dir in glob.glob(os.path.join(PROJECT_ROOT, pattern)):
        if os.path.isdir(runtime_dir):
            runtime_name = os.path.basename(runtime_dir)
            pyarmor_runtime_data.append((runtime_dir, runtime_name))
            pyarmor_hidden.append(runtime_name)
            print(f"[BUILD] Found PyArmor runtime: {runtime_name}")

if not pyarmor_runtime_data:
    print("[BUILD] WARNING: No PyArmor runtime found")

a = Analysis(
    [os.path.join(PROJECT_ROOT, 'src', 'main.py')],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=[
        (os.path.join(PROJECT_ROOT, 'src'), 'src'),
        (os.path.join(PROJECT_ROOT, 'gui_app'), 'gui_app'),
        (os.path.join(PROJECT_ROOT, 'upgrade'), 'upgrade'),
    ] + pyarmor_runtime_data,
    hiddenimports=upstox_imports + dhanhq_imports + kiteconnect_imports + telethon_imports + pyarmor_hidden + [
        # Qt/GUI
        'PySide6',
        'PySide6.QtWidgets',
        'PySide6.QtCore',
        'PySide6.QtGui',
        
        # Flask/Web
        'flask',
        'flask.json',
        'jinja2',
        'werkzeug',
        
        # HTTP/Async
        'requests',
        'aiohttp',
        'aiohttp.web',
        'httpx',
        
        # Encryption
        'cryptography',
        'cryptography.fernet',
        'cryptography.hazmat',
        'cryptography.hazmat.primitives',
        'cryptography.hazmat.backends',
        
        # Telegram
        'telethon',
        
        # Indian Brokers
        'upstox_client',
        'dhanhq',
        'kiteconnect',
        
        # Core Python
        'json',
        'asyncio',
        'threading',
        'logging',
        'logging.handlers',
        'datetime',
        'base64',
        'hashlib',
        'uuid',
        'platform',
        'subprocess',
        'queue',
        'typing',
        'pathlib',
        
        # Application modules
        'src',
        'src.gui',
        'src.gui.splash_screen',
        'src.gui.system_tray',
        'src.gui.license_controller',
        'src.services',
        'src.services.lifecycle_manager',
        'src.license',
        'src.license.client',
        'src.license.crypto',
        'src.license.cache',
        'src.license.heartbeat',
        'src.license.network_monitor',
        'gui_app',
        'gui_app.app',
        'upgrade',
        'upgrade.version',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='IndiaTradingBot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # NO CONSOLE WINDOW - GUI only
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

print("\n[BUILD] Build complete!")
print("[BUILD] IndiaTradingBot built with console=False (no console window)")
print("[BUILD] Output: dist/IndiaTradingBot")
