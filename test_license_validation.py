"""
Quick test to validate a license key against the license server.
Run this to verify client-server alignment.
"""

import os
import sys

# Add src to path
sys.path.insert(0, 'src')

from license.client import LicenseClient
from license.crypto import get_machine_id, get_machine_info

def test_license(license_key: str, server_url: str = None):
    """Test license validation against server."""
    
    print("=" * 60)
    print("LICENSE VALIDATION TEST")
    print("=" * 60)
    
    # Get machine info
    machine_id = get_machine_id()
    machine_info = get_machine_info()
    
    print(f"\nMachine ID: {machine_id}")
    print(f"Machine Info: {machine_info}")
    print(f"License Key: {license_key}")
    
    # Create client
    if server_url:
        print(f"\nUsing custom server: {server_url}")
        client = LicenseClient(license_server_url=server_url)
    else:
        print(f"\nUsing default servers: {client.server_urls}")
        client = LicenseClient()
    
    print(f"Active server: {client.server_url}")
    
    # Test 1: Server status
    print("\n" + "-" * 40)
    print("TEST 1: Server Status Check")
    print("-" * 40)
    status = client.check_server_status()
    print(f"Response: {status}")
    
    if status.get('status') == 'offline':
        print("\n[ERROR] Server is offline or unreachable!")
        print(f"Error: {status.get('error')}")
        return False
    
    # Test 2: Activate license
    print("\n" + "-" * 40)
    print("TEST 2: Activate License")
    print("-" * 40)
    activate_result = client.activate_license(license_key)
    print(f"Response: {activate_result}")
    
    if not activate_result.get('success') and not activate_result.get('is_valid'):
        if 'already activated' in str(activate_result.get('message', '')).lower():
            print("[OK] License already activated on this machine")
        elif 'another machine' in str(activate_result.get('error', '')).lower():
            print("[WARN] License is bound to a different machine")
        else:
            print(f"[ERROR] Activation failed: {activate_result.get('error')}")
    else:
        print("[OK] Activation successful!")
    
    # Test 3: Validate license
    print("\n" + "-" * 40)
    print("TEST 3: Validate License")
    print("-" * 40)
    is_valid, validate_result = client.validate_license(license_key)
    print(f"Is Valid: {is_valid}")
    print(f"Response: {validate_result}")
    
    if is_valid:
        print("\n[SUCCESS] License is VALID!")
        print(f"  - Customer: {validate_result.get('customer_id', 'N/A')}")
        print(f"  - Expires: {validate_result.get('expires_at', 'N/A')}")
        print(f"  - Days Remaining: {validate_result.get('days_remaining', 'N/A')}")
        print(f"  - License Type: {validate_result.get('license_type', 'N/A')}")
        print(f"  - Has Signed Token: {bool(validate_result.get('signed_token'))}")
    else:
        print(f"\n[FAILED] License validation failed: {validate_result.get('error')}")
    
    # Check expected response fields
    print("\n" + "-" * 40)
    print("RESPONSE FIELD CHECK")
    print("-" * 40)
    expected_fields = ['is_valid', 'expires_at', 'days_remaining', 'signed_token']
    optional_fields = ['customer_id', 'license_type', 'success']
    
    for field in expected_fields:
        has_field = field in validate_result
        print(f"  {field}: {'OK' if has_field else 'MISSING'}")
    
    for field in optional_fields:
        has_field = field in validate_result
        print(f"  {field}: {'OK' if has_field else 'not present (optional)'}")
    
    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)
    
    return is_valid


if __name__ == "__main__":
    # License key to test
    LICENSE_KEY = "BTF-J0B7-SKNY-P2XV"
    
    # Your license server URL (update this!)
    # Example: "https://your-repl-name.your-username.repl.co"
    SERVER_URL = os.getenv("LICENSE_SERVER_URL", None)
    
    if len(sys.argv) > 1:
        SERVER_URL = sys.argv[1]
    
    if len(sys.argv) > 2:
        LICENSE_KEY = sys.argv[2]
    
    print(f"\nTesting license: {LICENSE_KEY}")
    if SERVER_URL:
        print(f"Against server: {SERVER_URL}")
    else:
        print("Using default server URLs from license_types.py")
    print()
    
    test_license(LICENSE_KEY, SERVER_URL)
