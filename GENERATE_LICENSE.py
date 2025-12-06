#!/usr/bin/env python3
"""
Quick License Key Generator for QuantumPulse Trading Bot
Generates LEGACY format licenses (no machine binding required)
"""

import sys
import os
import json
import hmac
import hashlib
import base64
from datetime import datetime, timedelta

# MUST match the SECRET_KEY in src/license_manager_secure.py
SECRET_KEY = b"01690f93dc8536b80ddc194e47970d07fd85d3bb8758d5e0744e429edb8c876dd2d8e227a16f4d3b09beac10c9c2984a"

def generate_legacy_license(days: int, customer_id: str = "test_user") -> str:
    """
    Generate a legacy license (non-machine-bound)
    This format works on any machine without activation
    """
    expiration = datetime.now() + timedelta(days=days)
    
    license_data = {
        'customer_id': customer_id,
        'issued': datetime.now().isoformat(),
        'expires': expiration.isoformat(),
        'days': days
    }
    
    json_data = json.dumps(license_data, sort_keys=True)
    
    signature = hmac.new(
        SECRET_KEY,
        json_data.encode('utf-8'),
        hashlib.sha256
    ).digest()
    
    combined = json_data.encode('utf-8') + b'::' + signature
    license_key = base64.b64encode(combined).decode('utf-8')
    
    return license_key

def validate_license(license_key: str):
    """Validate the generated license"""
    try:
        combined = base64.b64decode(license_key.encode('utf-8'))
        
        if b'::' not in combined:
            return False, "Invalid format"
        
        json_data, signature = combined.rsplit(b'::', 1)
        
        expected_signature = hmac.new(
            SECRET_KEY,
            json_data,
            hashlib.sha256
        ).digest()
        
        if not hmac.compare_digest(signature, expected_signature):
            return False, "Invalid signature"
        
        payload = json.loads(json_data.decode('utf-8'))
        expires_dt = datetime.fromisoformat(payload['expires'])
        
        if datetime.now() >= expires_dt:
            return False, "Expired"
        
        days_remaining = (expires_dt - datetime.now()).days
        return True, f"Valid - {days_remaining} days remaining"
        
    except Exception as e:
        return False, f"Error: {e}"

def main():
    print("=" * 80)
    print("  QuantumPulse Trading Bot - License Key Generator")
    print("=" * 80)
    print()
    
    print("How many days should the license be valid?")
    print("  1. 30 days (1 month)")
    print("  2. 90 days (3 months)")
    print("  3. 365 days (1 year)")
    print("  4. 3650 days (10 years)")
    print("  5. Custom days")
    print()
    
    choice = input("Enter choice (1-5): ").strip()
    
    if choice == '1':
        days = 30
    elif choice == '2':
        days = 90
    elif choice == '3':
        days = 365
    elif choice == '4':
        days = 3650
    elif choice == '5':
        days = int(input("Enter number of days: ").strip())
    else:
        days = 365
        print(f"Invalid choice, defaulting to 365 days")
    
    customer_id = input("\nEnter customer ID (press Enter for 'test_user'): ").strip()
    if not customer_id:
        customer_id = "test_user"
    
    print(f"\nGenerating license for {days} days...")
    license_key = generate_legacy_license(days=days, customer_id=customer_id)
    
    is_valid, message = validate_license(license_key)
    
    print()
    print("=" * 80)
    print("  LICENSE KEY GENERATED SUCCESSFULLY!")
    print("=" * 80)
    print()
    print(f"Customer ID:  {customer_id}")
    print(f"Valid for:    {days} days")
    print(f"Status:       {message}")
    print(f"Type:         LEGACY (works on any machine)")
    print()
    print("=" * 80)
    print("YOUR LICENSE KEY:")
    print("=" * 80)
    print()
    print(license_key)
    print()
    print("=" * 80)
    print()
    print("HOW TO USE THIS LICENSE:")
    print("-" * 80)
    print()
    print("Option 1: Set as environment variable (Recommended)")
    print("  PowerShell:")
    print(f'    $env:LICENSE_KEY = "{license_key}"')
    print("    cd src")
    print("    python selfbot_webull.py")
    print()
    print("Option 2: Paste when the bot prompts for license")
    print("  1. Run: cd src && python selfbot_webull.py")
    print("  2. Choose option 2 (Subscription License)")
    print("  3. Paste the license key above")
    print()
    print("Option 3: Save to file for auto-loading")
    print("  Create/edit: wizard_credentials.json")
    print(f'  Add: "LICENSE_KEY": "{license_key}"')
    print()
    print("=" * 80)
    print()
    
    # Save to file option
    save = input("Do you want to save this to wizard_credentials.json? (yes/no): ").strip().lower()
    if save in ('yes', 'y'):
        creds_file = Path.home() / '.discord_trading_bot' / 'credentials.dat'
        json_file = 'wizard_credentials.json'
        
        # Try to load existing
        try:
            with open(json_file, 'r') as f:
                creds = json.load(f)
        except:
            creds = {}
        
        creds['LICENSE_KEY'] = license_key
        
        with open(json_file, 'w') as f:
            json.dump(creds, f, indent=2)
        
        print(f"\n✅ License saved to {json_file}")
        print("The bot will automatically use this license on next run!")
    
    print("\nPress Enter to exit...")
    input()

if __name__ == "__main__":
    from pathlib import Path
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nCancelled by user")
        sys.exit(0)
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        input("\nPress Enter to exit...")
        sys.exit(1)
