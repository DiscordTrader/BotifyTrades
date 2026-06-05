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
│   │   ├── scripts/
│   │   │   └── build.bat       # PyArmor protected build
│   │   ├── specs/
│   │   │   └── botifytrades.spec
│   │   └── dist/               # Build output (gitignored)
│   ├── linux/
│   │   ├── scripts/
│   │   │   └── build.sh        # PyArmor protected build
│   │   ├── specs/
│   │   │   └── botifytrades.spec
│   │   └── dist/               # Build output (gitignored)
│   ├── macos/
│   │   ├── scripts/
│   │   │   └── build.sh        # PyArmor protected build
│   │   ├── specs/
│   │   │   └── botifytrades.spec
│   │   └── dist/               # Build output (gitignored)
│   └── docs/                   # Build documentation
│       └── BUILD_AND_LICENSE_OVERVIEW.md
│
├── src/                        # Application source code
└── gui_app/                    # Web GUI application
```

## Build System

**IMPORTANT**: All builds use PyArmor obfuscation for license protection. No standard builds available.

**NO GIT REQUIRED** - Version is read from `upgrade/version.py`

### Windows Build

```batch
cd packaging\windows\scripts
build.bat

# Output: packaging\windows\dist\BotifyTrades.exe
```

### Linux Build

```bash
cd packaging/linux/scripts
chmod +x build.sh
./build.sh

# Output: packaging/linux/dist/BotifyTrades
```

### macOS Build

```bash
cd packaging/macos/scripts
chmod +x build.sh
./build.sh

# Output: packaging/macos/dist/BotifyTrades
```

### Build Process

1. Check Python, PyArmor, and PyInstaller installation
2. Backup original license files
3. Obfuscate license code with PyArmor
4. Replace originals with obfuscated versions
5. Build with PyInstaller using spec file
6. Compress with UPX (optional, where available)
7. Create distribution package
8. Restore original files (automatic on exit)
9. Clean up temporary files

### Protection Levels

All builds include:
- **PyArmor** - Runtime obfuscation of license validation code
- **PyInstaller** - Single executable packaging
- **UPX** - Compression (where available)

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
- `POST /api/license/deactivate` - Remove license binding

## Security Best Practices

### For Production Builds

1. Always use PyArmor builds (the only option now)
2. Generate unique SECRET_KEY in `license/config/constants.py`
3. Never commit production keys to git
4. Test license validation before distribution

### For License Keys

1. Use activation-based licenses for best UX
2. Set reasonable expiration periods
3. Track machine bindings for support
4. Implement offline grace period for reliability
