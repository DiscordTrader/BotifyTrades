# PyInstaller spec file for Discord Trading Bot
# This file defines how to bundle the bot into a standalone .exe

import shutil
import os
import glob
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

# Collect all discord and webull submodules automatically
discord_imports = collect_submodules('discord')
webull_imports = collect_submodules('webull')
openai_imports = collect_submodules('openai')
ta_imports = collect_submodules('ta')
crypto_imports = collect_submodules('cryptography')

# Collect broker library submodules (handles all submodules automatically)
try:
    tastytrade_imports = collect_submodules('tastytrade')
except Exception:
    tastytrade_imports = []
    print("[BUILD] Warning: tastytrade not installed, skipping submodule collection")

try:
    upstox_imports = collect_submodules('upstox_client')
except Exception:
    upstox_imports = []
    print("[BUILD] Warning: upstox_client not installed, skipping submodule collection")

try:
    dhanhq_imports = collect_submodules('dhanhq')
except Exception:
    dhanhq_imports = []
    print("[BUILD] Warning: dhanhq not installed, skipping submodule collection")

try:
    kiteconnect_imports = collect_submodules('kiteconnect')
except Exception:
    kiteconnect_imports = []
    print("[BUILD] Warning: kiteconnect not installed, skipping submodule collection")

# Get the project root directory (parent of build/)
import sys
SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
PROJECT_ROOT = os.path.dirname(SPEC_DIR)

# Find PyArmor runtime module (created during obfuscation)
pyarmor_runtime_data = []
pyarmor_hidden = []

# Search for pyarmor_runtime in src directory (where obfuscated code is copied)
for pattern in ['src/pyarmor_runtime_*', 'pyarmor_runtime_*']:
    for runtime_dir in glob.glob(os.path.join(PROJECT_ROOT, pattern)):
        if os.path.isdir(runtime_dir):
            runtime_name = os.path.basename(runtime_dir)
            pyarmor_runtime_data.append((runtime_dir, runtime_name))
            pyarmor_hidden.append(runtime_name)
            print(f"[BUILD] Found PyArmor runtime: {runtime_name}")

if not pyarmor_runtime_data:
    print("[BUILD] WARNING: No PyArmor runtime found - build may fail if code is obfuscated")

# Analysis - what files to include
a = Analysis(
    [os.path.join(PROJECT_ROOT, 'src', 'selfbot_webull.py')],  # Main script
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=[
        # Include entire src directory (simpler and more reliable)
        (os.path.join(PROJECT_ROOT, 'src'), 'src'),
        
        # Include GUI app (Flask web control panel)
        (os.path.join(PROJECT_ROOT, 'gui_app'), 'gui_app'),
    ] + pyarmor_runtime_data,
    hiddenimports=discord_imports + webull_imports + openai_imports + ta_imports + crypto_imports + tastytrade_imports + upstox_imports + dhanhq_imports + kiteconnect_imports + pyarmor_hidden + [
        # Market Data
        'yfinance',
        'pandas',
        'numpy',
        
        # HTTP/Async
        'aiohttp',
        'aiohttp.web',
        'aiohttp.client',
        'requests',
        'urllib3',
        
        # Flask GUI
        'flask',
        'flask.json',
        'jinja2',
        'werkzeug',
        'gui_app',
        'gui_app.app',
        'gui_app.routes',
        'gui_app.database',
        'gui_app.config_service',
        'gui_app.discord_notifier',
        'gui_app.lot_matcher',
        
        # JSON/Data (built-ins, but included for safety)
        'json',
        'asyncio',
        'datetime',
        'base64',
        'hmac',
        'hashlib',
        
        # Logging (critical for PyInstaller)
        'logging',
        'logging.handlers',
        'logging.config',
        'src.logging_config',
        'logging_config',
        
        # Encryption (for credential storage)
        'cryptography',
        'cryptography.fernet',
        'cryptography.hazmat',
        'cryptography.hazmat.primitives',
        'cryptography.hazmat.backends',
        
        # Windows encryption (for setup wizard)
        'win32crypt',
        'pywintypes',
        'win32api',
        'win32con',
        
        # Broker integrations
        'alpaca',
        'alpaca.trading',
        'alpaca.data',
        'ib_insync',
        
        # Indian Market Brokers (submodules collected automatically above)
        # Fallback entries in case collect_submodules fails
        'upstox_client',
        'dhanhq',
        'kiteconnect',
        'tastytrade',
        
        # Other dependencies
        'dotenv',
        'configparser',
        'queue',
        're',
        'typing',
        'pathlib',
        'getpass',
        'uuid',
        'platform',
        'subprocess',
        'wmi',
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
    name='DiscordTradingBot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Hide console for GUI mode (hardened build)
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# Post-build: Copy config.ini template to dist folder
print("\n[BUILD] Copying config.ini to dist folder...")
try:
    dist_dir = os.path.join(PROJECT_ROOT, 'dist')
    if not os.path.exists(dist_dir):
        os.makedirs(dist_dir)
    src_config = os.path.join(PROJECT_ROOT, 'config.ini')
    dst_config = os.path.join(dist_dir, 'config.ini')
    if os.path.exists(src_config):
        shutil.copyfile(src_config, dst_config)
        print("[BUILD] OK - config.ini copied to dist/")
    else:
        print("[BUILD] WARN - config.ini not found, skipping")
except Exception as e:
    print("[BUILD] WARN - Could not copy config.ini: " + str(e))

print("\n[BUILD] Build complete!")
print("[BUILD] Distributable files are in: dist/")
