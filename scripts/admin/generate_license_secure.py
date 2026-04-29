"""
Secure License Generator - Machine-Bound Licenses
Generates licenses tied to specific hardware fingerprints
"""

import hmac
import hashlib
import json
import base64
from datetime import datetime, timedelta
import argparse
import os
from pathlib import Path

SECRET_KEY = b"01690f93dc8536b80ddc194e47970d07fd85d3bb8758d5e0744e429edb8c876dd2d8e227a16f4d3b09beac10c9c2984a"

def generate_license(customer_id: str, machine_id: str, days: int) -> str:
    """
    Generate machine-bound license key
    
    Args:
        customer_id: Customer identifier
        machine_id: Hardware fingerprint (from customer's machine)
        days: License duration in days
        
    Returns:
        License key string
    """
    expires_dt = datetime.now() + timedelta(days=days)
    
    payload = {
        "customer_id": customer_id,
        "machine_id": machine_id,
        "expires": int(expires_dt.timestamp()),
        "issued": int(datetime.now().timestamp())
    }
    
    payload_json = json.dumps(payload)
    payload_b64 = base64.b64encode(payload_json.encode()).decode()
    
    signature = hmac.new(
        SECRET_KEY,
        payload_b64.encode(),
        hashlib.sha256
    ).hexdigest()
    
    license_key = f"{payload_b64}:{signature}"
    
    return license_key, expires_dt

def save_license_record(customer_id: str, machine_id: str, license_key: str, expires_dt: datetime, days: int):
    """Save license record to tracking file"""
    licenses_dir = Path("licenses")
    licenses_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = licenses_dir / f"{customer_id}_{timestamp}.txt"
    
    with open(filename, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("MACHINE-BOUND LICENSE KEY\n")
        f.write("=" * 80 + "\n")
        f.write(f"Customer ID: {customer_id}\n")
        f.write(f"Duration: {days} days\n")
        f.write(f"Issued: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Expires: {expires_dt.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Machine ID: {machine_id}\n")
        f.write("\n")
        f.write("License Key:\n")
        f.write("-" * 80 + "\n")
        f.write(license_key + "\n")
        f.write("-" * 80 + "\n")
        f.write("\n")
        f.write("IMPORTANT:\n")
        f.write("- This license is bound to the customer's specific hardware\n")
        f.write("- It will NOT work on any other machine\n")
        f.write("- If customer changes hardware, generate new license\n")
        f.write("- License cannot be transferred or shared\n")
        f.write("=" * 80 + "\n")
    
    db_file = licenses_dir / "license_database.txt"
    with open(db_file, 'a', encoding='utf-8') as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | ")
        f.write(f"{customer_id:20s} | {days:3d} days | ")
        f.write(f"Machine: {machine_id[:16]:16s} | ")
        f.write(f"Expires: {expires_dt.strftime('%Y-%m-%d')}\n")
    
    return filename

def main():
    parser = argparse.ArgumentParser(
        description="Generate machine-bound license keys",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python generate_license_secure.py --customer john_doe --machine abc123def456 --days 30
  python generate_license_secure.py --customer trial_user --machine xyz789abc012 --days 7
  
Customer must provide their Machine ID first!
They can get it by running: python -c "from src.machine_fingerprint import get_machine_id; print(get_machine_id())"
        """
    )
    
    parser.add_argument('--customer', required=True, help='Customer ID/name')
    parser.add_argument('--machine', required=True, help='Customer machine fingerprint (16 chars)')
    parser.add_argument('--days', type=int, required=True, help='License duration in days')
    parser.add_argument('--batch', type=int, help='Generate N licenses with sequential customer IDs')
    
    args = parser.parse_args()
    
    if len(args.machine) != 16:
        print(f"❌ Error: Machine ID must be exactly 16 characters")
        print(f"   Received: {args.machine} ({len(args.machine)} chars)")
        return
    
    if args.batch:
        print(f"\nGenerating {args.batch} licenses...")
        for i in range(1, args.batch + 1):
            customer_id = f"{args.customer}_{i}"
            license_key, expires_dt = generate_license(customer_id, args.machine, args.days)
            filename = save_license_record(customer_id, args.machine, license_key, expires_dt, args.days)
            print(f"✓ {i}/{args.batch}: {customer_id} -> {filename}")
        print(f"\n✅ Generated {args.batch} licenses successfully!")
    else:
        license_key, expires_dt = generate_license(args.customer, args.machine, args.days)
        
        print("\n" + "=" * 80)
        print("LICENSE KEY GENERATED SUCCESSFULLY")
        print("=" * 80)
        print(f"Customer ID: {args.customer}")
        print(f"Duration: {args.days} days")
        print(f"Expires: {expires_dt.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Machine ID: {args.machine}")
        print("\nLicense Key:")
        print("-" * 80)
        print(license_key)
        print("-" * 80)
        
        filename = save_license_record(args.customer, args.machine, license_key, expires_dt, args.days)
        
        print(f"\n💾 License saved to: {filename}")
        print(f"📋 Database updated: licenses/license_database.txt")
        print("\n⚠️  IMPORTANT:")
        print("   - This license ONLY works on the customer's specific hardware")
        print("   - Cannot be transferred to another machine")
        print("   - Send this license key to customer via secure channel")
        print("=" * 80)

if __name__ == "__main__":
    main()
