# -*- mode: python ; coding: utf-8 -*-
# ============================================================
# Ψ∿ QuantumPulse - Windows EXE Build (HARDENED)
# Build Date: 2025-11-21
# Python Version: 3.11+
# Protection: PyArmor Obfuscation + Anti-Reverse Engineering
# USE THIS FOR PRODUCTION/DISTRIBUTION
# ============================================================
# NOTE: Requires: pip install pyarmor
# Build command: pyarmor obfuscate --restrict src/selfbot_webull.py
#                 Then run: pyinstaller build_windows_hardened.spec
# ============================================================

a = Analysis(
    ['src/selfbot_webull.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('gui_app/templates', 'gui_app/templates'),
        ('gui_app/static', 'gui_app/static'),
        ('config.ini', '.'),
        ('replit.md', '.'),
    ],
    hiddenimports=[
        'discord',
        'webull',
        'alpaca',
        'flask',
        'cryptography',
        'ta',
        'yfinance',
        'pandas',
        'numpy',
        'openai',
        'aiohttp',
        'requests',
        'pywin32',
        'win32crypt',
        'win32api',
        'win32com',
        'wmi',
        'hashlib',
        'hmac',
        'uuid',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludedimports=[],
    noarchive=True,
    optimize=2,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='QuantumPulse_Hardened',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='gui_app/static/img/logo.ico' if False else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=True,
    upx=True,
    upx_exclude=[],
    name='QuantumPulse_Windows_Hardened_2025-11-21',
)
