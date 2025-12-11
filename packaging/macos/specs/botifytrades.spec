# -*- mode: python ; coding: utf-8 -*-
# ============================================================
# BotifyTrades - macOS Build Specification
# Uses consolidated license/ module for clean architecture
# Produces standalone macOS executable
# Note: NO GIT REQUIRED - version is read from upgrade/version.py
# ============================================================

import os
import sys
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
DIST_DIR = os.path.join(PROJECT_ROOT, 'packaging', 'macos', 'dist')
WORK_DIR = os.path.join(PROJECT_ROOT, 'packaging', 'macos', 'build_temp')

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
        'src.consent',
        'src.license_client',
        'src.setup_wizard',
        'setup_wizard',
        'certifi',
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
    console=True,
    disable_windowed_traceback=True,
    argv_emulation=True,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
