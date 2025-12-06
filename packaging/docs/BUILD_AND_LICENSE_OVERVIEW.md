# BotifyTrades - Build & License System Overview

## Directory Structure

```
project_root/
├── license/                    # Consolidated license system
│   ├── client/                 # Runtime license validation (for app)
│   │   ├── __init__.py
│   │   ├── manager.py          # Legacy license manager
│   │   ├── manager_secure.py   # Machine-bound validation
│   │   ├── manager_activation.py # Activation-based validation
│   │   └── client.py           # Server-side validation client
│   ├── config/                 # Centralized configuration
│   │   ├── __init__.py
│   │   └── constants.py        # SECRET_KEY, RSA keys, settings
│   └── tools/                  # Admin license generators
│       ├── __init__.py
│       ├── generate.py         # Legacy license generator
│       ├── generate_secure.py  # Machine-bound generator
│       └── generate_activation.py # Activation-based generator
│
├── packaging/                  # Build system
│   ├── windows/
│   │   ├── scripts/            # Build scripts (.bat)
│   │   │   ├── build_standard.bat
│   │   │   └── build_with_pyarmor.bat
│   │   ├── specs/              # PyInstaller specifications
│   │   │   └── botifytrades.spec
│   │   └── dist/               # Build output (gitignored)
│   ├── linux/
│   │   ├── scripts/            # Build scripts (.sh)
│   │   │   ├── build_standard.sh
│   │   │   └── build_with_pyarmor.sh
│   │   ├── specs/              # PyInstaller specifications
│   │   │   └── botifytrades.spec
│   │   └── dist/               # Build output (gitignored)
│   └── docs/                   # Build documentation
│       └── BUILD_AND_LICENSE_OVERVIEW.md
│
├── src/                        # Application source code
└── gui_app/                    # Web GUI application
```

## License System

### License Types

1. **Legacy License** (`license/client/manager.py`)
   - Simple HMAC-signed license
   - NOT machine-bound
   - Format: `base64(json_data::signature_bytes)`
   - Use for backwards compatibility only

2. **Machine-Bound License** (`license/client/manager_secure.py`)
   - Tied to specific hardware fingerprint
   - Customer must provide Machine ID first
   - Format: `base64(json_payload):hmac_signature`
   - Higher security, harder to share

3. **Activation License** (`license/client/manager_activation.py`)
   - Auto-binds to machine on first run
   - Customer doesn't need to provide Machine ID
   - Best user experience
   - **RECOMMENDED for new deployments**

4. **Server-Validated License** (`license/client/client.py`)
   - Validates via external license server
   - RSA signature verification (cannot be forged)
   - Offline grace period with cached tokens
   - Highest security level

### Generating Licenses

```bash
# Legacy format (simple)
python -m license.tools.generate --days 30 --customer "john_doe"

# Machine-bound (requires Machine ID from customer)
python -m license.tools.generate_secure --customer "john_doe" --machine "abc123def4567890" --days 30

# Activation-based (RECOMMENDED - no Machine ID needed)
python -m license.tools.generate_activation --customer "john_doe" --days 30
```

### Using in Application

```python
# Import from consolidated module
from license.client import (
    LicenseManager,           # Legacy
    validate_license,         # Secure (auto-detects format)
    check_or_activate_license # Activation-based
)

# Validate any license format
is_valid, data = validate_license(license_key)

# Check existing activation or activate new
is_valid, data = check_or_activate_license(license_key)
```

## Build System

### Windows Build

```batch
# Standard build (UPX compression)
packaging\windows\scripts\build_standard.bat

# Protected build (PyArmor + UPX)
packaging\windows\scripts\build_with_pyarmor.bat

# Output: packaging\windows\dist\BotifyTrades.exe
```

### Linux Build

```bash
# Standard build
chmod +x packaging/linux/scripts/build_standard.sh
./packaging/linux/scripts/build_standard.sh

# Protected build (PyArmor + UPX)
chmod +x packaging/linux/scripts/build_with_pyarmor.sh
./packaging/linux/scripts/build_with_pyarmor.sh

# Output: packaging/linux/dist/BotifyTrades
```

### PyInstaller Specification

The `.spec` files in `packaging/*/specs/` include:

- All application data (gui_app, src, services)
- Consolidated license module
- Hidden imports for all dependencies
- Proper path references for isolated builds

**Note**: PyInstaller v6.0 (2023) removed the `--key` bytecode encryption feature.
The encryption key had to be embedded in the executable, making it trivially
extractable. Use PyArmor, Cython, or Nuitka for additional code protection.

### Build Process

1. Check Python and PyInstaller installation
2. Clean previous builds
3. Build with PyInstaller using spec file
4. Compress with UPX (Windows, optional)
5. Create distribution package
6. Clean up temporary files

### Alternative Protection Methods

Since PyInstaller bytecode encryption was removed, consider:

1. **PyArmor** - Runtime obfuscation (recommended for license validation)
2. **Cython** - Compile Python to C extensions
3. **Nuitka** - Compile to native binaries (strongest protection)

## GUI License Management

The application includes a web-based License Management page at `/license`:

### Features
- **Status Display**: Shows license status (active/expired/inactive) with days remaining
- **Machine Information**: Displays hardware fingerprint for support
- **Activation**: Enter and activate license keys directly in browser
- **Validation**: Test keys without binding them
- **Deactivation**: Remove license binding for machine transfer

### API Endpoints
- `GET /api/license/status` - Get current license status
- `GET /api/license/machine-info` - Get machine fingerprint  
- `POST /api/license/activate` - Activate a license key
- `POST /api/license/validate` - Validate without activating
- `POST /api/license/deactivate` - Remove license

### Header Badge
A license status indicator appears in the navigation bar showing:
- Days remaining (green if valid)
- Warning color if expiring within 30 days
- Red if expired or no license

## Security Notes

### Important Files to Protect

1. `license/config/constants.py` - Contains SECRET_KEY
   - **MUST be obfuscated with PyArmor before distribution**
   - Never commit production keys to git

2. `license/client/manager_*.py` - License validation logic
   - Should be obfuscated to prevent bypass

### Obfuscation (Production)

Before production builds:

```bash
# Obfuscate license module
pyarmor obfuscate license/config/constants.py
pyarmor obfuscate license/client/manager_secure.py
pyarmor obfuscate license/client/manager_activation.py
```

### Key Rotation

To rotate the SECRET_KEY:

1. Update `license/config/constants.py`
2. Regenerate all customer licenses
3. Rebuild the application
4. Distribute new EXE and licenses

## Troubleshooting

### Common Build Issues

1. **Missing module imports**
   - Add to `hiddenimports` in spec file
   - Run: `pip install <missing_module>`

2. **Data files not included**
   - Add to `datas` list in spec file
   - Use correct path format for OS

3. **License validation fails after build**
   - Check that `license/` folder is in `datas`
   - Verify `hiddenimports` includes license modules

### License Issues

1. **Machine ID mismatch**
   - Customer changed hardware
   - Generate new license with new Machine ID

2. **Expired license**
   - Generate new license with extended duration

3. **Signature verification failed**
   - License was tampered or corrupted
   - Generate new license

## Migration from Old Structure

If migrating from the old scattered files:

1. Old files still work (imports fall back to old paths)
2. Update imports in main app to use `license.client`
3. Remove old files after confirming new structure works:
   - `src/license_manager.py`
   - `src/license_manager_activation.py`
   - `src/license_manager_secure.py`
   - `src/license_client.py`
   - `generate_license.py`
   - `generate_license_activation.py`
   - `generate_license_secure.py`
