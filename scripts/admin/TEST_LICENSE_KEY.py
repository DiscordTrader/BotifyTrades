#!/usr/bin/env python3
"""
License Key Diagnostic Tool
Tests and validates your license key format
"""

import sys
sys.path.insert(0, 'src')

from license_manager_secure import validate_license
import base64

print("=" * 70)
print("LICENSE KEY DIAGNOSTIC TOOL")
print("=" * 70)
print()

# Get the license key
license_key = input("Paste your license key here (press Enter when done):\n")
license_key = license_key.strip()

print()
print("=" * 70)
print("ANALYSIS")
print("=" * 70)
print(f"Key length: {len(license_key)} characters")
print(f"Contains '::'  ? {('::' in license_key)}")
print(f"Contains ':'   ? {(':' in license_key)}")
print()

# Show character breakdown
if '::' in license_key:
    parts = license_key.split('::')
    print(f"✓ Detected LEGACY format (double colon separator)")
    print(f"  - Payload part: {len(parts[0])} chars")
    print(f"  - Signature part: {len(parts[1])} chars")
    separator = "::"
elif ':' in license_key and '::' not in license_key:
    parts = license_key.rsplit(':', 1)
    print(f"✓ Detected MACHINE-BOUND format (single colon separator)")
    print(f"  - Payload part: {len(parts[0])} chars")
    print(f"  - Signature part: {len(parts[1])} chars")
    separator = ":"
else:
    print(f"✗ NO SEPARATOR FOUND!")
    print(f"  Your license key is missing the ':' or '::' separator")
    print(f"  This usually means:")
    print(f"    1. The key was corrupted during copy/paste")
    print(f"    2. Extra characters were added/removed")
    print(f"    3. The key format is completely different")
    print()
    print(f"First 50 chars: {license_key[:50]}")
    print(f"Last 50 chars:  {license_key[-50:]}")
    sys.exit(1)

print()

# Try to decode payload
try:
    payload_b64 = parts[0]
    payload_json = base64.b64decode(payload_b64).decode('utf-8')
    print("Payload decoded successfully:")
    print(f"  {payload_json}")
    print()
except Exception as e:
    print(f"✗ Failed to decode payload: {e}")
    print()

# Validate the license
print("=" * 70)
print("VALIDATION TEST")
print("=" * 70)

is_valid, data = validate_license(license_key)

if is_valid:
    print("✅ LICENSE IS VALID!")
    print()
    print(f"  Customer ID: {data.get('customer_id')}")
    print(f"  Expires: {data.get('expires')}")
    print(f"  Days Remaining: {data.get('days_remaining')}")
    print(f"  Machine ID: {data.get('machine_id')}")
    print(f"  License Type: {data.get('license_type')}")
else:
    print("❌ LICENSE VALIDATION FAILED")
    print()
    print(f"  Error: {data.get('error')}")

print()
print("=" * 70)
