# PyInstaller spec file for Discord Trading Bot - LINUX VERSION
# Cross-platform build with Linux-specific dependencies

import shutil
import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

# Collect all submodules automatically
discord_imports = collect_submodules('discord')
webull_imports = collect_submodules('webull')
openai_imports = collect_submodules('openai')
anthropic_imports = collect_submodules('anthropic')
try:
    genai_imports = collect_submodules('google.genai')
except Exception:
    genai_imports = []
ta_imports = collect_submodules('ta')
crypto_imports = collect_submodules('cryptography')

# Analysis - what files to include
a = Analysis(
    ['src/selfbot_webull.py'],  # Main script
    pathex=[],
    binaries=[],
    datas=[
        # Include all source modules
        ('src/setup_wizard.py', 'src'),
        ('src/license_manager_activation.py', 'src'),
        ('src/license_manager_secure.py', 'src'),
        ('src/machine_fingerprint.py', 'src'),
        ('src/ai_analyzer.py', 'src'),
        ('src/swing_analyzer.py', 'src'),
        ('src/fundamental_analyzer.py', 'src'),
        ('src/news_service.py', 'src'),
        ('src/alpha_vantage_scanner.py', 'src'),
        ('src/broker_interface.py', 'src'),
        ('src/broker_manager.py', 'src'),
        ('src/trade_tracker.py', 'src'),
        
        # Include GUI app (Flask web control panel)
        ('gui_app/__init__.py', 'gui_app'),
        ('gui_app/app.py', 'gui_app'),
        ('gui_app/routes.py', 'gui_app'),
        ('gui_app/database.py', 'gui_app'),
        ('gui_app/config_service.py', 'gui_app'),
        ('gui_app/discord_notifier.py', 'gui_app'),
        ('gui_app/lot_matcher.py', 'gui_app'),
        ('gui_app/templates', 'gui_app/templates'),
        ('gui_app/static', 'gui_app/static'),
        
        # Include broker modules
        ('src/brokers', 'src/brokers'),
        ('src/data_providers', 'src/data_providers'),
    ],
    hiddenimports=discord_imports + webull_imports + openai_imports + anthropic_imports + genai_imports + ta_imports + crypto_imports + [
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
        
        # Linux-specific credential storage
        'keyring',
        'keyring.backends',
        'keyring.backends.SecretService',
        'secretstorage',
        
        # Broker integrations
        'alpaca',
        'alpaca.trading',
        'alpaca.data',
        'ib_insync',
        
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
        
        # Linux system info (cross-platform alternative to wmi)
        'psutil',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude Windows-only modules
        'win32crypt',
        'pywintypes',
        'win32api',
        'win32con',
        'wmi',
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
    console=True,  # Show console for logs
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# Post-build: Copy config.ini template to dist folder
print("\n[BUILD] Copying config.ini to dist folder...")
try:
    if not os.path.exists('dist'):
        os.makedirs('dist')
    shutil.copyfile('config.ini', 'dist/config.ini')
    print("[BUILD] ✓ config.ini copied to dist/")
except Exception as e:
    print(f"[BUILD] ⚠️  Warning: Could not copy config.ini: {e}")

print("\n[BUILD] Build complete!")
print("[BUILD] Distributable files are in: dist/")
print("[BUILD] Package contents:")
print("  - DiscordTradingBot (Linux executable)")
print("  - config.ini")
