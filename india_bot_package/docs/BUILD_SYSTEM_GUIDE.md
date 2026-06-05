# Multi-Platform Build System Guide

## Complete Setup for Windows, macOS, and Linux Builds via GitHub Actions

This guide shows how BotifyTrades creates distributable executables for all platforms and how to set up the same for your India project.

---

## Replit Agent Prompt

Use this prompt to set up the build system in your India trading bot project:

```
I need to set up a GitHub Actions build system that creates standalone executables for Windows, macOS (Intel and Apple Silicon), and Linux. The system should:

1. **Build Triggers**
   - Manual workflow_dispatch with version input
   - Repository dispatch for automated releases

2. **Code Protection**
   - PyArmor for Python source code obfuscation
   - PyArmor license restoration from GitHub secrets
   - Build USER and ADMIN variants

3. **Build Targets (4 parallel jobs)**
   - Windows (windows-latest) → .exe
   - Linux (ubuntu-latest) → binary
   - macOS Intel (macos-15-intel) → tar.gz with code signing
   - macOS Apple Silicon (macos-14) → tar.gz with code signing

4. **Build Process**
   - Set BUILD_TYPE variable in source code
   - Update version in version.py
   - Obfuscate source with PyArmor
   - Bundle with PyInstaller
   - Upload artifacts with 90-day retention

5. **macOS Specifics**
   - Ad-hoc code signing (codesign --force --deep --sign -)
   - Remove quarantine attribute (xattr -cr)
   - Create tar.gz to preserve permissions

6. **Publish to Public Repo**
   - Download all artifacts
   - Create GitHub release with download links
   - Include installation instructions

Required GitHub Secrets:
- PYARMOR_LICENSE (base64-encoded license file)
- PUBLIC_REPO_TOKEN (for publishing releases)
- GITHUB_TOKEN (automatic)

Required Files:
- .github/workflows/build-user.yml
- .github/workflows/build-admin.yml
- build/build_exe.spec (PyInstaller spec)
- requirements.txt
- upgrade/version.py
```

---

## Project Structure

```
your-project/
├── .github/
│   └── workflows/
│       ├── build-user.yml      # Public user builds
│       └── build-admin.yml     # Private admin builds
├── build/
│   └── build_exe.spec          # PyInstaller configuration
├── src/
│   └── main.py                 # Your main entry point
├── gui_app/
│   └── ...                     # Flask web GUI
├── upgrade/
│   └── version.py              # Version info
└── requirements.txt
```

---

## Complete GitHub Workflow File

### `.github/workflows/build-user.yml`

```yaml
name: Build User (Public Release)

on:
  workflow_dispatch:
    inputs:
      version:
        description: 'Version number (e.g., 1.0.0)'
        required: true
        type: string
  repository_dispatch:
    types: [user_release_ready]

env:
  VERSION: ${{ github.event.inputs.version || github.event.client_payload.version }}
  APP_NAME: IndiaTrader  # Change this to your app name

jobs:
  set-build-type:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
        with:
          token: ${{ secrets.GITHUB_TOKEN }}
      
      - name: Set BUILD_TYPE to USER
        run: |
          sed -i "s/^BUILD_TYPE = .*/BUILD_TYPE = 'USER'  # Set by CI/" src/main.py
          echo "BUILD_TYPE set to USER"
      
      - name: Update version
        run: |
          BUILD_DATE=$(date +%Y-%m-%d)
          sed -i "s/APP_VERSION = \"[^\"]*\"/APP_VERSION = \"${{ env.VERSION }}\"/" upgrade/version.py
          sed -i "s/BUILD_DATE = \"[^\"]*\"/BUILD_DATE = \"$BUILD_DATE\"/" upgrade/version.py
      
      - name: Upload modified source
        uses: actions/upload-artifact@v4
        with:
          name: source-user
          path: .
          retention-days: 1

  build-windows:
    needs: set-build-type
    runs-on: windows-latest
    
    steps:
      - name: Download modified source
        uses: actions/download-artifact@v4
        with:
          name: source-user
          path: .
      
      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install pyarmor pyinstaller
          pip install -r requirements.txt
      
      - name: Restore PyArmor License
        shell: powershell
        run: |
          $bytes = [Convert]::FromBase64String("${{ secrets.PYARMOR_LICENSE }}")
          [IO.File]::WriteAllBytes("pyarmor-regfile.zip", $bytes)
          pyarmor reg pyarmor-regfile.zip
          Remove-Item pyarmor-regfile.zip
          pyarmor -v
      
      - name: Obfuscate source code
        shell: powershell
        run: |
          chcp 65001
          $env:PYTHONIOENCODING = "utf-8"
          pyarmor gen --output obfuscated src/
          
          Write-Host "=== PyArmor output structure ==="
          Get-ChildItem -Path obfuscated -Recurse | Select-Object FullName
      
      - name: Build with PyInstaller
        shell: powershell
        run: |
          Copy-Item -Path src -Destination src_backup -Recurse
          Copy-Item -Path obfuscated/src/* -Destination src/ -Recurse -Force
          
          # Copy PyArmor runtime module
          Get-ChildItem -Path obfuscated -Directory -Filter "pyarmor_runtime_*" | ForEach-Object {
            Write-Host "Copying PyArmor runtime: $($_.Name)"
            Copy-Item -Path $_.FullName -Destination "src/$($_.Name)" -Recurse -Force
          }
          
          pyinstaller build/build_exe.spec --clean --noconfirm
          Remove-Item -Path src -Recurse -Force
          Move-Item -Path src_backup -Destination src
          Rename-Item -Path dist/TradingBot.exe -NewName ${{ env.APP_NAME }}-Windows.exe
      
      - name: Upload Windows build
        uses: actions/upload-artifact@v4
        with:
          name: ${{ env.APP_NAME }}-Windows-v${{ env.VERSION }}
          path: dist/${{ env.APP_NAME }}-Windows.exe
          retention-days: 90

  build-linux:
    needs: set-build-type
    runs-on: ubuntu-latest
    
    steps:
      - name: Download modified source
        uses: actions/download-artifact@v4
        with:
          name: source-user
          path: .
      
      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install pyarmor pyinstaller
          pip install -r requirements.txt
      
      - name: Restore PyArmor License
        run: |
          echo "${{ secrets.PYARMOR_LICENSE }}" | base64 -d > pyarmor-regfile.zip
          pyarmor reg pyarmor-regfile.zip
          rm pyarmor-regfile.zip
          pyarmor -v
      
      - name: Obfuscate and Build
        run: |
          pyarmor gen --output obfuscated src/
          
          cp -r src src_backup
          cp -r obfuscated/src/* src/
          
          # Copy PyArmor runtime
          for runtime_dir in obfuscated/pyarmor_runtime_*; do
            if [ -d "$runtime_dir" ]; then
              runtime_name=$(basename "$runtime_dir")
              cp -r "$runtime_dir" "src/$runtime_name"
            fi
          done
          
          pyinstaller build/build_exe.spec --clean --noconfirm
          rm -rf src && mv src_backup src
          mv dist/TradingBot dist/${{ env.APP_NAME }}-Linux
      
      - name: Upload Linux build
        uses: actions/upload-artifact@v4
        with:
          name: ${{ env.APP_NAME }}-Linux-v${{ env.VERSION }}
          path: dist/${{ env.APP_NAME }}-Linux
          retention-days: 90

  build-macos-intel:
    needs: set-build-type
    runs-on: macos-15-intel
    
    steps:
      - name: Download modified source
        uses: actions/download-artifact@v4
        with:
          name: source-user
          path: .
      
      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install pyarmor pyinstaller
          pip install -r requirements.txt
      
      - name: Restore PyArmor License
        run: |
          echo "${{ secrets.PYARMOR_LICENSE }}" | base64 -d > pyarmor-regfile.zip
          pyarmor reg pyarmor-regfile.zip
          rm pyarmor-regfile.zip
          pyarmor -v
      
      - name: Obfuscate and Build
        run: |
          pyarmor gen --output obfuscated src/
          
          cp -r src src_backup
          cp -r obfuscated/src/* src/
          
          for runtime_dir in obfuscated/pyarmor_runtime_*; do
            if [ -d "$runtime_dir" ]; then
              runtime_name=$(basename "$runtime_dir")
              cp -r "$runtime_dir" "src/$runtime_name"
            fi
          done
          
          pyinstaller build/build_exe.spec --clean --noconfirm
          rm -rf src && mv src_backup src
          mv dist/TradingBot dist/${{ env.APP_NAME }}-macOS-Intel
      
      - name: Sign and package
        run: |
          chmod +x dist/${{ env.APP_NAME }}-macOS-Intel
          codesign --force --deep --sign - dist/${{ env.APP_NAME }}-macOS-Intel
          xattr -cr dist/${{ env.APP_NAME }}-macOS-Intel
          cd dist && tar -czvf ${{ env.APP_NAME }}-macOS-Intel.tar.gz ${{ env.APP_NAME }}-macOS-Intel
      
      - name: Upload macOS Intel build
        uses: actions/upload-artifact@v4
        with:
          name: ${{ env.APP_NAME }}-macOS-Intel-v${{ env.VERSION }}
          path: dist/${{ env.APP_NAME }}-macOS-Intel.tar.gz
          retention-days: 90

  build-macos-silicon:
    needs: set-build-type
    runs-on: macos-14
    
    steps:
      - name: Download modified source
        uses: actions/download-artifact@v4
        with:
          name: source-user
          path: .
      
      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install pyarmor pyinstaller
          pip install -r requirements.txt
      
      - name: Restore PyArmor License
        run: |
          echo "${{ secrets.PYARMOR_LICENSE }}" | base64 -d > pyarmor-regfile.zip
          pyarmor reg pyarmor-regfile.zip
          rm pyarmor-regfile.zip
          pyarmor -v
      
      - name: Obfuscate and Build
        run: |
          pyarmor gen --output obfuscated src/
          
          cp -r src src_backup
          cp -r obfuscated/src/* src/
          
          for runtime_dir in obfuscated/pyarmor_runtime_*; do
            if [ -d "$runtime_dir" ]; then
              runtime_name=$(basename "$runtime_dir")
              cp -r "$runtime_dir" "src/$runtime_name"
            fi
          done
          
          pyinstaller build/build_exe.spec --clean --noconfirm
          rm -rf src && mv src_backup src
          mv dist/TradingBot dist/${{ env.APP_NAME }}-macOS-Silicon
      
      - name: Sign and package
        run: |
          chmod +x dist/${{ env.APP_NAME }}-macOS-Silicon
          codesign --force --deep --sign - dist/${{ env.APP_NAME }}-macOS-Silicon
          xattr -cr dist/${{ env.APP_NAME }}-macOS-Silicon
          cd dist && tar -czvf ${{ env.APP_NAME }}-macOS-Silicon.tar.gz ${{ env.APP_NAME }}-macOS-Silicon
      
      - name: Upload macOS Silicon build
        uses: actions/upload-artifact@v4
        with:
          name: ${{ env.APP_NAME }}-macOS-Silicon-v${{ env.VERSION }}
          path: dist/${{ env.APP_NAME }}-macOS-Silicon.tar.gz
          retention-days: 90

  publish-release:
    needs: [build-windows, build-linux, build-macos-intel, build-macos-silicon]
    runs-on: ubuntu-latest
    
    steps:
      - name: Download all artifacts
        uses: actions/download-artifact@v4
        with:
          path: releases
          pattern: ${{ env.APP_NAME }}-*
      
      - name: Create GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          repository: YourOrg/YourPublicRepo  # Change this
          token: ${{ secrets.PUBLIC_REPO_TOKEN }}
          tag_name: v${{ env.VERSION }}
          name: ${{ env.APP_NAME }} v${{ env.VERSION }}
          body: |
            ## ${{ env.APP_NAME }} v${{ env.VERSION }}
            
            ### Downloads
            - **Windows**: ${{ env.APP_NAME }}-Windows.exe
            - **Linux**: ${{ env.APP_NAME }}-Linux
            - **macOS (Intel)**: ${{ env.APP_NAME }}-macOS-Intel.tar.gz
            - **macOS (Apple Silicon)**: ${{ env.APP_NAME }}-macOS-Silicon.tar.gz
            
            ### Installation
            
            **Windows/Linux:** Download and run the executable.
            
            **macOS:**
            1. Download the .tar.gz for your Mac type
            2. Extract: `tar -xzf ${{ env.APP_NAME }}-macOS-*.tar.gz`
            3. Run the executable
            4. If blocked: System Settings > Privacy & Security > "Open Anyway"
          files: releases/**/*
          draft: false
          prerelease: false

  cleanup:
    needs: [publish-release]
    runs-on: ubuntu-latest
    if: always()
    steps:
      - name: Delete source artifact
        uses: geekyeggo/delete-artifact@v5
        with:
          name: source-user
```

---

## PyInstaller Spec File

### `build/build_exe.spec`

```python
# PyInstaller spec file for India Trading Bot
import shutil
import os
import glob
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

# Collect submodules for dependencies
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
    telegram_imports = collect_submodules('telethon')
except:
    telegram_imports = []

# Get project root
import sys
SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
PROJECT_ROOT = os.path.dirname(SPEC_DIR)

# Find PyArmor runtime module
pyarmor_runtime_data = []
pyarmor_hidden = []

for pattern in ['src/pyarmor_runtime_*', 'pyarmor_runtime_*']:
    for runtime_dir in glob.glob(os.path.join(PROJECT_ROOT, pattern)):
        if os.path.isdir(runtime_dir):
            runtime_name = os.path.basename(runtime_dir)
            pyarmor_runtime_data.append((runtime_dir, runtime_name))
            pyarmor_hidden.append(runtime_name)
            print(f"[BUILD] Found PyArmor runtime: {runtime_name}")

a = Analysis(
    [os.path.join(PROJECT_ROOT, 'src', 'main.py')],  # Your main entry point
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=[
        (os.path.join(PROJECT_ROOT, 'src'), 'src'),
        (os.path.join(PROJECT_ROOT, 'gui_app'), 'gui_app'),
    ] + pyarmor_runtime_data,
    hiddenimports=upstox_imports + dhanhq_imports + kiteconnect_imports + telegram_imports + pyarmor_hidden + [
        # Core
        'asyncio', 'json', 'logging', 'threading',
        
        # HTTP/Async
        'aiohttp', 'requests', 'httpx',
        
        # Flask GUI
        'flask', 'jinja2', 'werkzeug',
        'gui_app', 'gui_app.app', 'gui_app.routes', 'gui_app.database',
        
        # Encryption
        'cryptography', 'cryptography.fernet',
        
        # Data
        'pandas', 'numpy',
        
        # Indian Brokers
        'upstox_client', 'dhanhq', 'kiteconnect',
        
        # Telegram
        'telethon',
    ],
    hookspath=[],
    excludes=[],
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
    name='TradingBot',  # Output name
    debug=False,
    strip=False,
    upx=True,
    console=False,  # Set True if you want console window
)

print("\n[BUILD] Build complete!")
print("[BUILD] Output: dist/TradingBot")
```

---

## Version File

### `upgrade/version.py`

```python
"""Version information for the application."""

APP_VERSION = "1.0.0"
BUILD_DATE = "2026-01-17"
BUILD_TYPE = "DEV"  # Changed by CI to USER or ADMIN

def get_version():
    return APP_VERSION

def get_build_info():
    return {
        "version": APP_VERSION,
        "build_date": BUILD_DATE,
        "build_type": BUILD_TYPE
    }
```

---

## GitHub Secrets Setup

Go to your GitHub repo → Settings → Secrets and variables → Actions → New repository secret:

| Secret Name | Description | How to Get |
|-------------|-------------|------------|
| `PYARMOR_LICENSE` | Base64-encoded PyArmor license | `base64 pyarmor-regfile.zip` |
| `PUBLIC_REPO_TOKEN` | PAT with repo access | GitHub → Settings → Developer settings → PAT |

### Create PyArmor License Secret

```bash
# After purchasing PyArmor license, you'll get pyarmor-regfile.zip
# Convert to base64 for GitHub secret:

# On Linux/macOS:
base64 pyarmor-regfile.zip > pyarmor_license_base64.txt

# On Windows PowerShell:
[Convert]::ToBase64String([IO.File]::ReadAllBytes("pyarmor-regfile.zip")) > pyarmor_license_base64.txt

# Copy contents of pyarmor_license_base64.txt to GitHub secret PYARMOR_LICENSE
```

---

## How to Trigger a Build

### Manual Trigger
1. Go to GitHub repo → Actions
2. Select "Build User (Public Release)"
3. Click "Run workflow"
4. Enter version (e.g., "1.0.0")
5. Click "Run workflow"

### Automated Trigger via API

```bash
curl -X POST \
  -H "Authorization: token YOUR_GITHUB_TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  https://api.github.com/repos/YOUR_ORG/YOUR_REPO/dispatches \
  -d '{"event_type": "user_release_ready", "client_payload": {"version": "1.0.0"}}'
```

---

## Build Output

After successful build, you'll have:

| Platform | File | Size (approx) |
|----------|------|---------------|
| Windows | `IndiaTrader-Windows.exe` | 80-150 MB |
| Linux | `IndiaTrader-Linux` | 70-130 MB |
| macOS Intel | `IndiaTrader-macOS-Intel.tar.gz` | 70-130 MB |
| macOS Silicon | `IndiaTrader-macOS-Silicon.tar.gz` | 70-130 MB |

---

## Key Points

1. **PyArmor** obfuscates your Python source code (requires paid license for distribution)
2. **PyInstaller** bundles Python + dependencies into single executable
3. **Parallel builds** run Windows/Linux/macOS simultaneously (faster)
4. **macOS code signing** required for Gatekeeper to allow execution
5. **Artifacts stored 90 days** - download before expiration
6. **GitHub Actions free tier** has limited minutes - use wisely
