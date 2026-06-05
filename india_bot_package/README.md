# India Trading Bot - Complete Package

This package contains everything needed to build a professional trading bot for Indian markets (NSE/BSE/MCX).

## Features

- **No console window** - Runs as a GUI application
- **Splash screen** - License activation with trial option
- **System tray** - Background operation with status indicator
- **Stop/Restart buttons** - Via tray menu and web panel
- **Same license server** - Connects to license-forge--uk15286.replit.app

## Quick Start

1. Copy all files to your project
2. Set up GitHub secrets (PYARMOR_LICENSE, PUBLIC_REPO_TOKEN)
3. Run GitHub Actions workflow to build executables

## Documentation

- `docs/INDIA_BOT_COMPLETE_PACKAGE.md` - Complete implementation guide
- `docs/BUILD_SYSTEM_GUIDE.md` - GitHub Actions + PyArmor + PyInstaller
- `docs/LICENSE_SYSTEM_GUIDE.md` - License validation system

## Directory Structure

```
├── src/
│   ├── license/       # License validation (7 files)
│   ├── gui/           # GUI components (splash, tray)
│   ├── services/      # Lifecycle manager
│   └── main.py        # Entry point
├── gui_app/           # Flask web panel
├── build/             # PyInstaller spec
├── upgrade/           # Version info
└── .github/workflows/ # Build automation
```

## Requirements

- Python 3.11+
- PySide6 (Qt for Python)
- Flask
- PyArmor (for code protection)
- PyInstaller (for bundling)

## Build Command

```bash
# Local build (development)
pyinstaller build/build_exe.spec --clean --noconfirm

# Production build via GitHub Actions
# Push to main branch or trigger workflow manually
```
