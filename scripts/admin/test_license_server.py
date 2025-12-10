#!/usr/bin/env python3
"""
Quick test script to verify license server connectivity
Run this on your Windows machine to test the license server
"""

import urllib.request
import urllib.error
import json
import hashlib
import platform
import subprocess
import ssl

LICENSE_SERVER_URL = "https://73c88a3f-ed39-46d5-9424-decd03d13c62-00-2bumin2yn8p08.riker.replit.dev"

def get_machine_id():
    """Generate machine ID"""
    try:
        result = subprocess.run(
            ['wmic', 'csproduct', 'get', 'uuid'],
            capture_output=True, text=True, timeout=10
        )
        uuid_lines = [line.strip() for line in result.stdout.split('\n') if line.strip() and line.strip() != 'UUID']
        if uuid_lines:
            machine_uuid = uuid_lines[0]
        else:
            machine_uuid = platform.node()
    except Exception:
        machine_uuid = platform.node()
    
    raw = f"{machine_uuid}_{platform.system()}_{platform.machine()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]

def test_health():
    """Test health endpoint"""
    print("\n=== Testing License Server Health ===")
    url = f"{LICENSE_SERVER_URL}/api/v1/license/health"
    print(f"URL: {url}")
    
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, method='GET')
        with urllib.request.urlopen(req, context=ctx, timeout=30) as response:
            data = json.loads(response.read().decode())
            print(f"Response: {json.dumps(data, indent=2)}")
            return True
    except Exception as e:
        print(f"Error: {e}")
        return False

def test_trial_request():
    """Test trial request"""
    print("\n=== Testing Trial Request ===")
    machine_id = get_machine_id()
    print(f"Machine ID: {machine_id}")
    
    url = f"{LICENSE_SERVER_URL}/api/v1/license/trial"
    print(f"URL: {url}")
    
    payload = json.dumps({
        'machine_id': machine_id
    }).encode('utf-8')
    
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, data=payload, method='POST')
        req.add_header('Content-Type', 'application/json')
        
        with urllib.request.urlopen(req, context=ctx, timeout=30) as response:
            data = json.loads(response.read().decode())
            print(f"Response: {json.dumps(data, indent=2)}")
            return data
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        print(f"HTTP Error {e.code}: {error_body}")
        return json.loads(error_body) if error_body else {}
    except Exception as e:
        print(f"Error: {e}")
        return {}

if __name__ == '__main__':
    print("=" * 60)
    print("  BotifyTrades License Server Test")
    print("=" * 60)
    print(f"\nServer: {LICENSE_SERVER_URL}")
    
    # Test health
    if test_health():
        print("\n✅ Server is healthy!")
    else:
        print("\n❌ Could not reach server")
    
    # Test trial
    result = test_trial_request()
    
    if result.get('success'):
        print("\n✅ Trial activated!")
        print(f"   License Key: {result.get('license_key')}")
        print(f"   Expires: {result.get('expires_at')}")
    elif 'already' in result.get('error', '').lower():
        print("\n⚠️  Trial already used on this machine")
        print("   You need a subscription license to continue")
    else:
        print(f"\n❌ Trial request failed: {result.get('error', 'Unknown error')}")
    
    print("\n" + "=" * 60)
    input("Press Enter to exit...")
