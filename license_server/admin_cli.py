"""
License Server Admin CLI
Command-line tool for managing licenses via API
"""

import requests
import os
import sys
from datetime import datetime
import argparse

SERVER_URL = os.getenv("LICENSE_SERVER_URL", "http://localhost:8000")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")

def create_license(customer_id: str, days: int, max_activations: int = 1, notes: str = None):
    """Create a new license"""
    response = requests.post(
        f"{SERVER_URL}/api/v1/admin/licenses",
        json={
            "customer_id": customer_id,
            "days": days,
            "max_activations": max_activations,
            "notes": notes
        },
        headers={"X-API-Key": ADMIN_API_KEY}
    )
    
    if response.status_code == 200:
        data = response.json()
        print("=" * 80)
        print(f"✅ License Created Successfully")
        print("=" * 80)
        print(f"Customer ID: {data['customer_id']}")
        print(f"Duration: {days} days")
        print(f"Expires: {data['expires_at']}")
        print(f"\nLicense Key:")
        print("-" * 80)
        print(data['license_key'])
        print("-" * 80)
        print(f"\n💾 Save this key and send it to {customer_id}")
        print("=" * 80)
        return data['license_key']
    else:
        print(f"❌ Error: {response.json()}")
        return None

def revoke_license(license_key: str):
    """Revoke a license"""
    response = requests.post(
        f"{SERVER_URL}/api/v1/admin/licenses/{license_key}/revoke",
        headers={"X-API-Key": ADMIN_API_KEY}
    )
    
    if response.status_code == 200:
        print(f"✅ License revoked: {license_key}")
    else:
        print(f"❌ Error: {response.json()}")

def list_licenses():
    """List all licenses"""
    response = requests.get(
        f"{SERVER_URL}/api/v1/admin/licenses",
        headers={"X-API-Key": ADMIN_API_KEY}
    )
    
    if response.status_code == 200:
        data = response.json()
        print("=" * 140)
        print(f"License Database - Total: {data['total']}")
        print("=" * 140)
        print(f"{'License Key':<25} {'Customer':<15} {'Status':<10} {'Expires':<12} {'Machine ID':<18} {'Devices':<10} {'Last Seen':<20}")
        print("-" * 140)
        
        for lic in data['licenses']:
            expires = datetime.fromisoformat(lic['expires_at']).strftime("%Y-%m-%d")
            last_seen = datetime.fromisoformat(lic['last_validated']).strftime("%Y-%m-%d %H:%M") if lic['last_validated'] else "Never"
            machine = lic['machine_id'][:16] if lic['machine_id'] and lic['machine_id'] != "Not activated" else "Not activated"
            license_short = lic.get('license_key', 'N/A')[:24] if lic.get('license_key') else 'N/A'
            devices = f"{lic['activation_count']}/{lic.get('max_activations', 1)}"
            
            print(f"{license_short:<25} {lic['customer_id']:<15} {lic['status']:<10} {expires:<12} {machine:<18} {devices:<10} {last_seen:<20}")
        
        print("=" * 140)
    else:
        print(f"❌ Error: {response.json()}")

def get_license_details(license_key: str):
    """Get detailed info for a specific license"""
    response = requests.get(
        f"{SERVER_URL}/api/v1/admin/licenses/{license_key}",
        headers={"X-API-Key": ADMIN_API_KEY}
    )
    
    if response.status_code == 200:
        data = response.json()
        print("=" * 60)
        print(f"License Details: {license_key}")
        print("=" * 60)
        print(f"  Customer ID:     {data.get('customer_id', 'N/A')}")
        print(f"  Status:          {data.get('status', 'N/A')}")
        print(f"  Machine ID:      {data.get('machine_id') or 'Not activated'}")
        print(f"  Devices:         {data.get('activation_count', 0)}/{data.get('max_activations', 1)}")
        print(f"  Days Remaining:  {data.get('days_remaining', 'N/A')}")
        print(f"  Expires:         {data.get('expires_at', 'N/A')}")
        print(f"  Last Validated:  {data.get('last_validated') or 'Never'}")
        print("=" * 60)
    else:
        print(f"❌ Error: {response.json()}")

def clear_activation(license_key: str):
    """Clear machine activation to allow re-activation on new machine"""
    response = requests.post(
        f"{SERVER_URL}/api/v1/admin/licenses/{license_key}/clear-activation",
        headers={"X-API-Key": ADMIN_API_KEY}
    )
    
    if response.status_code == 200:
        data = response.json()
        print("=" * 60)
        print(f"✅ Activation Cleared Successfully")
        print("=" * 60)
        print(f"  License Key:    {license_key}")
        print(f"  Old Machine ID: {data.get('old_machine_id', 'None')}")
        print(f"  Status:         Ready for new activation")
        print("=" * 60)
    else:
        print(f"❌ Error: {response.json()}")

def set_device_limit(license_key: str, limit: int):
    """Set device limit for a license"""
    response = requests.post(
        f"{SERVER_URL}/api/v1/admin/licenses/{license_key}/set-device-limit?limit={limit}",
        headers={"X-API-Key": ADMIN_API_KEY}
    )
    
    if response.status_code == 200:
        data = response.json()
        print("=" * 60)
        print(f"✅ Device Limit Updated")
        print("=" * 60)
        print(f"  License Key: {license_key}")
        print(f"  Old Limit:   {data.get('old_limit', 'N/A')}")
        print(f"  New Limit:   {data.get('new_limit', limit)}")
        print("=" * 60)
    else:
        print(f"❌ Error: {response.json()}")

def main():
    parser = argparse.ArgumentParser(description="License Server Admin CLI")
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    create_parser = subparsers.add_parser('create', help='Create new license')
    create_parser.add_argument('--customer', required=True, help='Customer ID')
    create_parser.add_argument('--days', type=int, required=True, help='Duration in days')
    create_parser.add_argument('--max-activations', type=int, default=1, help='Max activations allowed')
    create_parser.add_argument('--notes', help='Optional notes')
    
    revoke_parser = subparsers.add_parser('revoke', help='Revoke license')
    revoke_parser.add_argument('--key', required=True, help='License key to revoke')
    
    subparsers.add_parser('list', help='List all licenses')
    
    details_parser = subparsers.add_parser('details', help='Get license details')
    details_parser.add_argument('--key', required=True, help='License key')
    
    clear_parser = subparsers.add_parser('clear-activation', help='Clear machine activation')
    clear_parser.add_argument('--key', required=True, help='License key')
    
    limit_parser = subparsers.add_parser('set-limit', help='Set device limit')
    limit_parser.add_argument('--key', required=True, help='License key')
    limit_parser.add_argument('--limit', type=int, required=True, help='New device limit')
    
    args = parser.parse_args()
    
    if not ADMIN_API_KEY:
        print("❌ Error: ADMIN_API_KEY environment variable not set")
        print("Set it with: export ADMIN_API_KEY='your_key_here'")
        sys.exit(1)
    
    if args.command == 'create':
        create_license(args.customer, args.days, args.max_activations, args.notes)
    elif args.command == 'revoke':
        revoke_license(args.key)
    elif args.command == 'list':
        list_licenses()
    elif args.command == 'details':
        get_license_details(args.key)
    elif args.command == 'clear-activation':
        clear_activation(args.key)
    elif args.command == 'set-limit':
        set_device_limit(args.key, args.limit)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
