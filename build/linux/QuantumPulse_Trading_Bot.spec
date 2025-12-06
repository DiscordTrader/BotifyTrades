# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['/home/runner/workspace/src/selfbot_webull.py'],
    pathex=['/home/runner/workspace'],
    binaries=[],
    datas=[('/home/runner/workspace/gui_app', 'gui_app'), ('/home/runner/workspace/src', 'src'), ('/home/runner/workspace/config.ini.example', '.'), ('/home/runner/workspace/broker_sync_service.py', '.')],
    hiddenimports=['discord', 'webull', 'flask', 'openai', 'alpaca_py', 'ta', 'yfinance', 'broker_sync_service'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pytest', 'unittest'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='QuantumPulse_Trading_Bot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
