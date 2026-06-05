# BotifyTrades - macOS Installation Guide

## Prerequisites

Before building BotifyTrades on macOS, ensure you have:

1. **Python 3.8+** - Install via Homebrew:
   ```bash
   brew install python3
   ```

2. **PyInstaller** - Will be installed automatically by the build script

3. **Required Python packages** - Will be installed automatically

## Building the Application

### Option 1: Standard Build (Recommended)

1. Open Terminal and navigate to the project root:
   ```bash
   cd /path/to/BotifyTrades
   ```

2. Run the build script:
   ```bash
   ./packaging/macos/scripts/build_standard.sh
   ```

3. The built application will be in:
   ```
   packaging/macos/dist/BotifyTrades/
   ```

### Option 2: Manual Build

If you prefer to build manually:

```bash
cd /path/to/BotifyTrades

# Install dependencies
pip3 install pyinstaller discord.py-self webull flask cryptography requests openai aiohttp yfinance pandas numpy ta alpaca-py

# Build
python3 -m PyInstaller --clean --noconfirm \
    --distpath "packaging/macos/dist" \
    --workpath "packaging/macos/build_temp" \
    packaging/macos/specs/botifytrades.spec
```

## Running the Application

### Method 1: Double-click (Easiest)
1. Navigate to `packaging/macos/dist/BotifyTrades/`
2. Double-click `run.command`

### Method 2: Terminal
```bash
cd packaging/macos/dist/BotifyTrades
./BotifyTrades
```

## macOS Security / Gatekeeper

macOS may block the application because it's not signed. To allow it:

### First Time Launch
1. Try to open `BotifyTrades` or `run.command`
2. macOS will show a security warning
3. Go to **System Preferences** > **Security & Privacy** > **General**
4. Click **"Open Anyway"** next to the BotifyTrades message
5. Click **"Open"** in the confirmation dialog

### Alternative: Remove Quarantine Attribute
```bash
xattr -d com.apple.quarantine packaging/macos/dist/BotifyTrades/BotifyTrades
xattr -d com.apple.quarantine packaging/macos/dist/BotifyTrades/run.command
```

## First Time Setup

1. **Open Browser**: Navigate to `http://localhost:5000`
2. **Create Admin Account**: Complete the setup wizard
3. **Accept Agreement**: Read and accept the User Agreement
4. **Enter License**: Input your license key in the License page
5. **Configure Brokers**: Set up Discord, Alpaca, Webull, or IBKR

## Files Included

| File | Description |
|------|-------------|
| `BotifyTrades` | Main executable |
| `run.command` | Double-click launcher |
| `config.ini.example` | Example configuration |
| `GET_DISCORD_TOKEN.html` | Guide for getting Discord token |
| `GET_WEBULL_TOKENS.html` | Guide for getting Webull tokens |
| `README.txt` | Quick start guide |

## Troubleshooting

### "App is damaged and can't be opened"
Run this command to remove the quarantine flag:
```bash
xattr -cr packaging/macos/dist/BotifyTrades/
```

### "Permission denied"
Make the executable runnable:
```bash
chmod +x packaging/macos/dist/BotifyTrades/BotifyTrades
chmod +x packaging/macos/dist/BotifyTrades/run.command
```

### App crashes immediately
Check Terminal output for errors:
```bash
cd packaging/macos/dist/BotifyTrades
./BotifyTrades 2>&1 | tee debug.log
```

### Missing libraries
Reinstall dependencies and rebuild:
```bash
pip3 install --upgrade pyinstaller discord.py-self webull flask
./packaging/macos/scripts/build_standard.sh
```

## Intel vs Apple Silicon (M1/M2/M3) Compatibility

**As of v3.2.5+**, separate builds are provided for each architecture:
- **Intel Macs** (x86_64): Download `macOS-Intel` version
- **Apple Silicon Macs** (M1/M2/M3): Download `macOS-AppleSilicon` version

### "Bad CPU type in executable" Error

If you see this error, it means the binary was built for a different CPU architecture.

**Solutions:**
1. **Download the correct version for your Mac:**
   - Check your Mac: Apple menu → About This Mac → Chip/Processor
   - **Intel processor**: Download `macOS-Intel` version
   - **Apple M1/M2/M3**: Download `macOS-AppleSilicon` version

2. **Check the binary type:**
   ```bash
   file ./BotifyTrades
   ```
   - `arm64` = Apple Silicon only
   - `x86_64` = Intel only

3. **For Intel Mac users with ARM64-only binary:**
   - Download the correct `macOS-Intel` version
   - Or build locally on your Intel Mac

### Building Locally

The build script creates a binary for your current Mac's architecture:
- **On Intel Mac**: Creates x86_64 binary
- **On Apple Silicon Mac**: Creates arm64 binary

For cross-platform distribution, you need to build on BOTH architectures (done automatically via GitHub Actions CI).

## Support

For issues:
1. Check the console output for error messages
2. Enable Debug Mode in Settings to get detailed logs
3. Find your Machine ID in the License page
4. Contact support with your Machine ID and error logs
