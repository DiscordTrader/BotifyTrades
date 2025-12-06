#!/usr/bin/env python3
"""
Quick setup validation script
Run this before starting the bot to check if everything is configured correctly
"""

import os
import sys

# Load .env file first
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("✓ Loaded .env file")
except ImportError:
    print("⚠️  python-dotenv not installed. Run: pip install python-dotenv")
except Exception as e:
    print(f"⚠️  Could not load .env file: {e}")

print("=" * 60)
print("Discord Trading Bot - Setup Validation")
print("=" * 60)
print()

errors = []
warnings = []

# Check Python version
print("✓ Checking Python version...")
if sys.version_info < (3, 11):
    warnings.append(f"Python {sys.version_info.major}.{sys.version_info.minor} detected. Python 3.11+ recommended.")
else:
    print(f"  ✓ Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")

# Check required packages
print("\n✓ Checking required packages...")
required_packages = ['discord', 'webull', 'requests']
for package in required_packages:
    try:
        __import__(package)
        print(f"  ✓ {package} installed")
    except ImportError:
        errors.append(f"Package '{package}' not installed. Run: pip install -r requirements.txt")

# Check environment variables
print("\n✓ Checking environment variables...")

token = os.getenv('DISCORD_USER_TOKEN')
if not token:
    errors.append("DISCORD_USER_TOKEN not set!")
else:
    # Check for common mistakes
    if token.startswith('"') or token.startswith("'"):
        errors.append("DISCORD_USER_TOKEN has quotes around it! Remove quotes.")
    elif len(token) < 50:
        warnings.append(f"DISCORD_USER_TOKEN seems too short ({len(token)} chars). Discord tokens are usually 70+ characters.")
    else:
        print(f"  ✓ DISCORD_USER_TOKEN set ({len(token)} characters)")
        print(f"    Preview: {token[:20]}...")

webull_access = os.getenv('WEBULL_ACCESS_TOKEN')
webull_refresh = os.getenv('WEBULL_REFRESH_TOKEN')
webull_did = os.getenv('WEBULL_DID')
webull_pin = os.getenv('WEBULL_TRADE_PIN')

if webull_access and webull_refresh and webull_did:
    print(f"  ✓ WEBULL_ACCESS_TOKEN set")
    print(f"  ✓ WEBULL_REFRESH_TOKEN set")
    print(f"  ✓ WEBULL_DID set")
else:
    warnings.append("Webull tokens not fully set. Bot may require username/password login.")

if not webull_pin:
    errors.append("WEBULL_TRADE_PIN not set! This is required for trading.")
else:
    if len(webull_pin) != 6 or not webull_pin.isdigit():
        warnings.append(f"WEBULL_TRADE_PIN should be 6 digits. Got: {len(webull_pin)} characters")
    else:
        print(f"  ✓ WEBULL_TRADE_PIN set (6 digits)")

# Check config.ini
print("\n✓ Checking config.ini...")
try:
    with open('config.ini', 'r') as f:
        config_content = f.read()
        if 'channel_ids =' in config_content:
            print("  ✓ config.ini exists")
        else:
            warnings.append("config.ini might not have channel_ids set")
except FileNotFoundError:
    errors.append("config.ini not found! Copy from config.ini.example")

# Summary
print("\n" + "=" * 60)
print("VALIDATION SUMMARY")
print("=" * 60)

if errors:
    print("\n❌ ERRORS (must fix before running):")
    for i, error in enumerate(errors, 1):
        print(f"  {i}. {error}")

if warnings:
    print("\n⚠️  WARNINGS (should check):")
    for i, warning in enumerate(warnings, 1):
        print(f"  {i}. {warning}")

if not errors and not warnings:
    print("\n✅ ALL CHECKS PASSED!")
    print("You're ready to run the bot!")
    print("\nRun: python src/selfbot_webull.py")
elif not errors:
    print("\n✅ No critical errors found")
    print("You can try running the bot, but check the warnings above.")
    print("\nRun: python src/selfbot_webull.py")
else:
    print("\n❌ Please fix the errors above before running the bot.")
    print("\nNeed help? Check TROUBLESHOOTING.md")

print("=" * 60)
