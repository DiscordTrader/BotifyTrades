# -*- mode: python ; coding: utf-8 -*-
# ============================================================
# BotifyTrades - Windows EXE Build Specification
# Uses consolidated license/ module for clean architecture
# Note: --key encryption removed in PyInstaller v6.0 (2023)
# Note: NO GIT REQUIRED - version is read from upgrade/version.py
# ============================================================

import os
import sys
import glob
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(SPEC), '..', '..', '..')))
try:
    from upgrade.version import APP_VERSION, BUILD_DATE
except ImportError:
    APP_VERSION = "2.1.35"
    BUILD_DATE = datetime.now().strftime('%Y-%m-%d')

print(f"[BUILD] Version: {APP_VERSION} | Build Date: {BUILD_DATE}")
build_date = BUILD_DATE

SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
PROJECT_ROOT = os.path.abspath(os.path.join(SPEC_DIR, '..', '..', '..'))
DIST_DIR = os.path.join(PROJECT_ROOT, 'packaging', 'windows', 'dist')
WORK_DIR = os.path.join(PROJECT_ROOT, 'packaging', 'windows', 'build_temp')

# Find PyArmor runtime module (dynamically named)
pyarmor_hidden = []
for pattern in ['license/pyarmor_runtime_*', 'src/pyarmor_runtime_*', 'pyarmor_runtime_*']:
    for runtime_dir in glob.glob(os.path.join(PROJECT_ROOT, pattern)):
        if os.path.isdir(runtime_dir):
            runtime_name = os.path.basename(runtime_dir)
            pyarmor_hidden.append(runtime_name)
            print(f"[BUILD] Found PyArmor runtime: {runtime_name}")

if not pyarmor_hidden:
    print("[BUILD] WARNING: No PyArmor runtime found - build may fail if code is obfuscated")

# Include SSL certificates for HTTPS requests
import certifi
CERT_PATH = certifi.where()

a = Analysis(
    [os.path.join(PROJECT_ROOT, 'src', 'selfbot_webull.py')],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=[
        (os.path.join(PROJECT_ROOT, 'gui_app'), 'gui_app'),
        (os.path.join(PROJECT_ROOT, 'src'), 'src'),
        (os.path.join(PROJECT_ROOT, 'ui'), 'ui'),  # Setup Wizard UI
        (os.path.join(PROJECT_ROOT, 'license'), 'license'),
        (os.path.join(PROJECT_ROOT, 'services'), 'services'),
        (os.path.join(PROJECT_ROOT, 'config.ini.example'), '.'),
        (CERT_PATH, 'certifi'),  # SSL certificates for HTTPS requests
    ],
    hiddenimports=[
        'discord',
        'webull',
        'alpaca',
        'alpaca.trading',
        'alpaca.trading.client',
        'alpaca.trading.requests',
        'alpaca.trading.enums',
        'alpaca.data',
        'alpaca.data.live',
        'alpaca.data.historical',
        'alpaca.common',
        'alpaca.common.enums',
        'flask',
        'cryptography',
        'cryptography.fernet',
        'ta',
        'yfinance',
        'pandas',
        'numpy',
        'openai',
        'aiohttp',
        'requests',
        'hashlib',
        'hmac',
        'uuid',
        'sqlite3',
        'logging',
        'logging.handlers',
        'logging.config',
        'src.logging_config',
        'logging_config',
        'license',
        'license.client',
        'license.client.manager',
        'license.client.manager_secure',
        'license.client.manager_activation',
        'license.client.client',
        'license.config',
        'license.config.constants',
        'services',
        'services.simulation',
        'gui_app',
        'gui_app.routes',
        'gui_app.database',
        'gui_app.broker_credentials_service',
        'gui_app.config_service',
        'src.machine_fingerprint',
        'machine_fingerprint',
        'src.license_manager',
        'src.license_manager_secure',
        'src.license_manager_activation',
        'src.license_client',
        'src.setup_wizard',
        'setup_wizard',
        'certifi',  # SSL certificates
        # Indian market broker APIs
        'upstox_client',
        'upstox_client.configuration',
        'upstox_client.api_client',
        'upstox_client.api',
        'dhanhq',
        'dhanhq.dhanhq',
        'kiteconnect',
    ] + pyarmor_hidden + [  # PyArmor runtime (dynamically detected)
        # PySide6 for Setup Wizard GUI
        'PySide6',
        'PySide6.QtWidgets',
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtNetwork',
        'ui',
        'ui.wizard',
        'ui.wizard.wizard',
        'ui.wizard.launcher',
        'ui.wizard.config_db',
        'ui.wizard.pages',
        'ui.wizard.pages.base_page',
        'ui.wizard.pages.welcome',
        'ui.wizard.pages.app_mode',
        'ui.wizard.pages.discord',
        'ui.wizard.pages.broker_selection',
        'ui.wizard.pages.broker_credentials',
        'ui.wizard.pages.channels',
        'ui.wizard.pages.risk_management',
        'ui.wizard.pages.notifications',
        'ui.wizard.pages.privacy',
        'ui.wizard.pages.review',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludedimports=['pytest', 'unittest', 'test_*'],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='BotifyTrades',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
