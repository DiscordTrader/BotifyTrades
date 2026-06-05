# QuantumPulse Trading Bot - Build System

Complete build system for creating protected executables for Windows and Linux platforms.

---

## 📁 Directory Structure

```
build/
├── windows/
│   ├── build_standard.bat       # Standard Windows build (15-30 min protection)
│   ├── build_hardened.bat       # Hardened Windows build (40+ hours protection)
│   ├── dist_standard/           # Output for standard builds
│   └── dist_hardened/           # Output for hardened builds
├── linux/
│   ├── build_standard.sh        # Standard Linux build (15-30 min protection)
│   ├── build_hardened.sh        # Hardened Linux build (40+ hours protection)
│   ├── dist_standard/           # Output for standard builds
│   └── dist_hardened/           # Output for hardened builds
├── docs/                        # Build documentation
└── README.md                    # This file
```

---

## 🎯 Protection Levels

### Standard Build
**Protection Time:** 15-30 minutes to reverse engineer

**Technologies:**
- ✅ PyInstaller single-file packaging
- ✅ AES-256 bytecode encryption
- ✅ UPX compression (reduces file size + obfuscation)
- ✅ Debug symbol stripping (Linux)

**Use Case:** Quick distribution, casual protection

---

### Hardened Build  
**Protection Time:** 40+ hours to reverse engineer

**Technologies:**
- ✅ **PyArmor BCC Mode** - Converts Python functions to C code
- ✅ **PyArmor RFT Mode** - Irreversible function/variable renaming
- ✅ String encryption
- ✅ Import/call assertions
- ✅ AES-256 bytecode encryption
- ✅ UPX ultra compression
- ✅ Debug symbol stripping (Linux)

**Use Case:** Commercial distribution, IP protection

---

## 🪟 Windows Build Instructions

### Prerequisites
```bash
# Install Python 3.8+
python --version

# Install build dependencies
pip install pyinstaller pycryptodome pyarmor

# (Optional) Install UPX for compression
# Download from: https://upx.github.io/
```

### Standard Build
```bash
# Navigate to project root
cd /path/to/QuantumPulse

# Run standard build
build\windows\build_standard.bat

# Output: build\windows\dist_standard\QuantumPulse_Trading_Bot.exe
```

### Hardened Build
```bash
# Run hardened build (with PyArmor protection)
build\windows\build_hardened.bat

# Output: build\windows\dist_hardened\QuantumPulse_Trading_Bot_Pro.exe
```

---

## 🐧 Linux Build Instructions

### Prerequisites
```bash
# Install Python 3.8+
python3 --version

# Install build dependencies
pip3 install pyinstaller pycryptodome pyarmor

# Install UPX (optional but recommended)
sudo apt install upx-ucl   # Ubuntu/Debian
sudo yum install upx       # CentOS/RHEL
```

### Standard Build
```bash
# Navigate to project root
cd /path/to/QuantumPulse

# Run standard build
chmod +x build/linux/build_standard.sh
./build/linux/build_standard.sh

# Output: build/linux/dist_standard/QuantumPulse_Trading_Bot
```

### Hardened Build
```bash
# Run hardened build (with PyArmor protection)
chmod +x build/linux/build_hardened.sh
./build/linux/build_hardened.sh

# Output: build/linux/dist_hardened/QuantumPulse_Trading_Bot_Pro
```

---

## 📦 Distribution Packages

Each build creates a complete distribution package:

```
dist_*/
├── QuantumPulse_Trading_Bot(.exe)     # Main executable
├── config.ini.example                  # Configuration template
├── GET_DISCORD_TOKEN.html             # Discord token helper
├── GET_WEBULL_TOKENS.html             # Webull token helper
└── RUN.bat / run.sh                   # Launch script
```

---

## 🔧 Build Options Explained

### PyInstaller Flags
- `--onefile` - Single executable (no external files)
- `--windowed` - No console window on startup (Windows GUI apps)
- `--key` - AES-256 encryption key for bytecode
- `--add-data` - Include non-Python files
- `--hidden-import` - Force include modules not detected automatically
- `--exclude-module` - Remove unnecessary modules to reduce size

### PyArmor Protection Modes
- `--enable-bcc` - **BCC Mode** - Converts Python functions to C code
- `--enable-rft` - **RFT Mode** - Rename functions, classes, variables
- `--mix-str` - Encrypt all string literals
- `--assert-call` - Add runtime verification for function calls
- `--assert-import` - Add runtime verification for imports

### UPX Compression
- `--best` - Maximum compression ratio
- `--ultra-brute` - Extreme compression (slow but best results)

---

## 🛡️ Security Comparison

| Feature | Standard | Hardened |
|---------|----------|----------|
| **Decompilation Protection** | Low | High |
| **String Obfuscation** | ❌ | ✅ |
| **Function Renaming** | ❌ | ✅ |
| **C-Level Compilation** | ❌ | ✅ |
| **Import Protection** | ❌ | ✅ |
| **File Size** | Smaller | Larger |
| **Build Time** | ~2 minutes | ~5 minutes |
| **Runtime Overhead** | None | Minimal |

---

## ⚠️ Common Issues & Solutions

### Windows

**Issue:** `'python' is not recognized`
```bash
# Add Python to PATH or use full path
C:\Python39\python.exe build\windows\build_standard.bat
```

**Issue:** `UPX not found`
```bash
# Download UPX from https://upx.github.io/
# Extract and add to PATH, or skip compression (still builds successfully)
```

**Issue:** `PyArmor license error`
```bash
# PyArmor free tier has limitations
# Either purchase license or use standard build
```

### Linux

**Issue:** `Permission denied`
```bash
chmod +x build/linux/build_standard.sh
```

**Issue:** `strip: command not found`
```bash
sudo apt install binutils
```

**Issue:** `UPX not found`
```bash
sudo apt install upx-ucl   # Ubuntu/Debian
sudo yum install upx       # CentOS/RHEL
```

---

## 🚀 Quick Start

**Windows (Hardened):**
```bash
cd C:\path\to\QuantumPulse
build\windows\build_hardened.bat
```

**Linux (Hardened):**
```bash
cd /path/to/QuantumPulse
./build/linux/build_hardened.sh
```

---

## 📊 Build Time Estimates

| Platform | Standard | Hardened |
|----------|----------|----------|
| **Windows** | ~2 minutes | ~5 minutes |
| **Linux** | ~2 minutes | ~5 minutes |

*Times vary based on system performance and PyArmor license tier*

---

## 🔬 Testing Builds

After building, test the executable:

```bash
# Windows
build\windows\dist_hardened\QuantumPulse_Trading_Bot_Pro.exe --help

# Linux
build/linux/dist_hardened/QuantumPulse_Trading_Bot_Pro --help
```

---

## 📝 Notes

1. **PyArmor Free Tier:** Limited to 10 registration uses. For commercial distribution, purchase a license.
2. **UPX Compression:** Optional but recommended. Reduces file size by 30-50%.
3. **Encryption Keys:** Generated randomly on each build. Keep builds separate.
4. **Cross-Compilation:** Not supported. Build Windows executables on Windows, Linux binaries on Linux.
5. **Code Signing:** Not included. Add code signing certificates separately for production.

---

## 📚 Further Reading

- [PyInstaller Documentation](https://pyinstaller.org/)
- [PyArmor Documentation](https://pyarmor.readthedocs.io/)
- [UPX Documentation](https://upx.github.io/)
- [Python Code Protection Best Practices](https://realpython.com/python-code-protection/)

---

## 💡 Recommendations

**For Development/Testing:**
- Use Standard Build (faster iteration)

**For Distribution:**
- Use Hardened Build (better protection)
- Consider code signing certificates
- Add hardware binding for commercial licenses

**For Maximum Security:**
1. Use Hardened Build
2. Add code signing
3. Implement server-side license validation
4. Keep sensitive logic server-side when possible

---

## 📧 Support

For build issues, check:
1. This README
2. Build logs in `build/windows/` or `build/linux/`
3. Project documentation in `build/docs/`
