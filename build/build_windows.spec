# -*- mode: python ; coding: utf-8 -*-
# ============================================================
# Ψ∿ QuantumPulse - Windows EXE Build Specification
# Build Date: 2025-11-21
# Python Version: 3.11+
# Security: Anti-tampering, Anti-reverse engineering
# ============================================================

import sys
import os

python_dll = os.path.join(sys.exec_prefix, 'python311.dll')
extra_binaries = []
if os.path.exists(python_dll):
    extra_binaries.append((python_dll, '.'))
for dll_name in ['vcruntime140.dll', 'vcruntime140_1.dll', 'msvcp140.dll']:
    dll_path = os.path.join(sys.exec_prefix, dll_name)
    if os.path.exists(dll_path):
        extra_binaries.append((dll_path, '.'))

a = Analysis(
    ['src/selfbot_webull.py'],
    pathex=[],
    binaries=extra_binaries,
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
        'anthropic',
        'google.genai',
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
        'logging',
        'logging.handlers',
        'logging.config',
        'src.logging_config',
        'logging_config',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludedimports=[],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='QuantumPulse',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
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
    strip=False,
    upx=True,
    upx_exclude=[],
    name='QuantumPulse_Windows_Build_2025-11-21',
)
