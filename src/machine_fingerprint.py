"""
Machine Fingerprinting
Generates stable hardware-based machine ID for license binding
Works across Windows, Mac, Linux
Uses persistent caching to ensure consistency across runs
"""

import hashlib
import platform
import uuid
import subprocess
import os
from pathlib import Path

# Persistent machine ID file - once generated, always reuse
MACHINE_ID_FILE = Path.home() / '.discord_trading_bot' / '.machine_id'

def get_machine_id() -> str:
    """
    Generate stable machine fingerprint based on hardware
    Returns consistent ID even after OS reinstall
    Uses persistent caching to ensure PyInstaller builds use same ID
    """
    # FIRST: Check if we have a persisted machine ID file
    try:
        if MACHINE_ID_FILE.exists():
            saved_id = MACHINE_ID_FILE.read_text(encoding='utf-8').strip()
            if saved_id and len(saved_id) >= 8:  # Allow various lengths
                return saved_id
    except Exception:
        pass
    
    # SECOND: Check if there's a machine_id in license_cache.json (migration from old versions)
    try:
        cache_file = MACHINE_ID_FILE.parent / 'license_cache.json'
        if cache_file.exists():
            import json
            with open(cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
                cached_machine_id = cache_data.get('machine_id', '').strip()
                if cached_machine_id and len(cached_machine_id) >= 8:
                    # Migrate: save this as the persistent machine ID
                    try:
                        MACHINE_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
                        MACHINE_ID_FILE.write_text(cached_machine_id, encoding='utf-8')
                    except Exception:
                        pass
                    return cached_machine_id
    except Exception:
        pass
    
    # Generate new machine ID from hardware
    identifiers = []
    
    system = platform.system()
    
    if system == "Windows":
        identifiers.extend(_get_windows_identifiers())
    elif system == "Darwin":  # Mac
        identifiers.extend(_get_mac_identifiers())
    elif system == "Linux":
        identifiers.extend(_get_linux_identifiers())
    
    identifiers.append(f"node:{uuid.getnode()}")
    identifiers.append(f"platform:{platform.machine()}")
    
    combined = "|".join(sorted(identifiers))
    
    machine_hash = hashlib.sha256(combined.encode('utf-8')).hexdigest()
    machine_id = machine_hash[:16]
    
    # PERSIST the machine ID for future runs
    try:
        MACHINE_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
        MACHINE_ID_FILE.write_text(machine_id, encoding='utf-8')
    except Exception:
        pass  # Best effort
    
    return machine_id

def _get_windows_identifiers() -> list:
    """Get Windows-specific hardware identifiers"""
    identifiers = []
    
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography")
        guid, _ = winreg.QueryValueEx(key, "MachineGuid")
        identifiers.append(f"win_guid:{guid}")
        winreg.CloseKey(key)
    except Exception:
        pass
    
    try:
        output = subprocess.check_output(
            'wmic csproduct get uuid',
            shell=True,
            text=True,
            stderr=subprocess.DEVNULL
        )
        uuid_match = [line for line in output.split('\n') if line.strip() and 'UUID' not in line]
        if uuid_match:
            identifiers.append(f"hw_uuid:{uuid_match[0].strip()}")
    except Exception:
        pass
    
    try:
        output = subprocess.check_output(
            'wmic baseboard get serialnumber',
            shell=True,
            text=True,
            stderr=subprocess.DEVNULL
        )
        serial_match = [line for line in output.split('\n') if line.strip() and 'SerialNumber' not in line]
        if serial_match:
            identifiers.append(f"mb_serial:{serial_match[0].strip()}")
    except Exception:
        pass
    
    return identifiers

def _get_mac_identifiers() -> list:
    """Get macOS-specific hardware identifiers"""
    identifiers = []
    
    try:
        output = subprocess.check_output(
            ['system_profiler', 'SPHardwareDataType'],
            text=True,
            stderr=subprocess.DEVNULL
        )
        for line in output.split('\n'):
            if 'Hardware UUID' in line:
                uuid = line.split(':')[1].strip()
                identifiers.append(f"hw_uuid:{uuid}")
            elif 'Serial Number' in line:
                serial = line.split(':')[1].strip()
                identifiers.append(f"serial:{serial}")
    except Exception:
        pass
    
    return identifiers

def _get_linux_identifiers() -> list:
    """Get Linux-specific hardware identifiers"""
    identifiers = []
    
    try:
        if os.path.exists('/etc/machine-id'):
            with open('/etc/machine-id', 'r', encoding='utf-8') as f:
                machine_id = f.read().strip()
                identifiers.append(f"machine_id:{machine_id}")
    except Exception:
        pass

    try:
        if os.path.exists('/var/lib/dbus/machine-id'):
            with open('/var/lib/dbus/machine-id', 'r', encoding='utf-8') as f:
                dbus_id = f.read().strip()
                identifiers.append(f"dbus_id:{dbus_id}")
    except Exception:
        pass
    
    try:
        output = subprocess.check_output(
            ['dmidecode', '-s', 'system-uuid'],
            text=True,
            stderr=subprocess.DEVNULL
        )
        uuid = output.strip()
        identifiers.append(f"hw_uuid:{uuid}")
    except Exception:
        pass
    
    return identifiers

def get_machine_info() -> dict:
    """Get detailed machine information for display"""
    return {
        "machine_id": get_machine_id(),
        "platform": platform.system(),
        "platform_version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "node": platform.node()
    }

if __name__ == "__main__":
    info = get_machine_info()
    print("=" * 60)
    print("Machine Fingerprint Information")
    print("=" * 60)
    for key, value in info.items():
        print(f"{key:20s}: {value}")
    print("=" * 60)
    print(f"\nMachine ID: {get_machine_id()}")
