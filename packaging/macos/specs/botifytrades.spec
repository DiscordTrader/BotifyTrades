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
        'logging',
        'logging.handlers',
        'logging.config',
        'src.logging_config',
        'logging_config',
        # Note: license/, services/, gui_app/, src/ modules are included via datas section
        # Only include imports for modules that exist as actual Python packages
        'certifi',
        # Indian market broker APIs
        'upstox_client',
        'upstox_client.configuration',
        'upstox_client.api_client',
        'upstox_client.api',
        'dhanhq',
        'dhanhq.dhanhq',
        'kiteconnect',
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
    argv_emulation=True,
    target_arch=None,  # Build for native architecture - use CI matrix for Intel + Apple Silicon builds
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
