"""
Activation-Based License Generator
Generates licenses that auto-bind to customer's machine on first run
NO MACHINE ID NEEDED FROM CUSTOMER!
"""

import hmac
import hashlib
import json
import base64
import secrets
from datetime import datetime, timedelta
import argparse
from pathlib import Path

SECRET_KEY = b"01690f93dc8536b80ddc194e47970d07fd85d3bb8758d5e0744e429edb8c876dd2d8e227a16f4d3b09beac10c9c2984a"

def generate_activation_license(customer_id: str, days: int) -> tuple:
    """
    Generate activation-based license key
    
    Args:
        customer_id: Customer identifier
        days: License duration in days
        
    Returns:
        Tuple of (license_key, activation_code, expires_dt)
    """
    expires_dt = datetime.now() + timedelta(days=days)
    
    activation_code = secrets.token_hex(8)
    
    payload = {
        "activation_code": activation_code,
        "customer_id": customer_id,
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
    
    return license_key, activation_code, expires_dt

def save_license_record(customer_id: str, activation_code: str, license_key: str, expires_dt: datetime, days: int):
    """Save license record to tracking file"""
    licenses_dir = Path("licenses")
    licenses_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = licenses_dir / f"{customer_id}_{timestamp}.txt"
    
    with open(filename, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("ACTIVATION LICENSE KEY\n")
        f.write("=" * 80 + "\n")
        f.write(f"Customer ID: {customer_id}\n")
        f.write(f"Activation Code: {activation_code}\n")
        f.write(f"Duration: {days} days\n")
        f.write(f"Issued: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Expires: {expires_dt.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("\n")
        f.write("License Key:\n")
        f.write("-" * 80 + "\n")
        f.write(license_key + "\n")
        f.write("-" * 80 + "\n")
        f.write("\n")
        f.write("HOW IT WORKS:\n")
        f.write("1. Customer receives this license key\n")
        f.write("2. Customer runs the bot and enters the license key\n")
        f.write("3. Bot AUTOMATICALLY binds to their machine on first run\n")
        f.write("4. License works ONLY on that machine from then on\n")
        f.write("\n")
        f.write("BENEFITS:\n")
        f.write("✓ Customer doesn't need to share Machine ID\n")
        f.write("✓ Simple activation process (just paste license key)\n")
        f.write("✓ License auto-binds to their hardware\n")
        f.write("✓ Cannot be transferred to another machine\n")
        f.write("\n")
        f.write("SUPPORT:\n")
        f.write("- If customer changes hardware, generate new license\n")
        f.write("- Track by Activation Code: {}\n".format(activation_code))
        f.write("=" * 80 + "\n")
    
    db_file = licenses_dir / "license_database.txt"
    with open(db_file, 'a', encoding='utf-8') as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | ")
        f.write(f"{customer_id:20s} | {days:3d} days | ")
        f.write(f"Code: {activation_code:16s} | ")
        f.write(f"Expires: {expires_dt.strftime('%Y-%m-%d')}\n")
    
    return filename

def main():
    parser = argparse.ArgumentParser(
        description="Generate activation-based license keys (auto-bind on first run)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python generate_license_activation.py --customer john_doe --days 30
  python generate_license_activation.py --customer trial_user --days 7
  python generate_license_activation.py --customer premium --days 365
  
NO MACHINE ID NEEDED!
License auto-binds to customer's machine on first run.
        """
    )
    
    parser.add_argument('--customer', required=True, help='Customer ID/name')
    parser.add_argument('--days', type=int, required=True, help='License duration in days')
    parser.add_argument('--batch', type=int, help='Generate N licenses with sequential customer IDs')
    
    args = parser.parse_args()
    
    if args.batch:
        print(f"\n🚀 Generating {args.batch} activation licenses...")
        print()
        
        for i in range(1, args.batch + 1):
            customer_id = f"{args.customer}_{i}"
            license_key, activation_code, expires_dt = generate_activation_license(customer_id, args.days)
            filename = save_license_record(customer_id, activation_code, license_key, expires_dt, args.days)
            print(f"✓ {i:2d}/{args.batch}: {customer_id:25s} | Code: {activation_code} | {filename.name}")
        
        print()
        print(f"✅ Generated {args.batch} licenses successfully!")
        print(f"📋 All saved to: licenses/")
    else:
        license_key, activation_code, expires_dt = generate_activation_license(args.customer, args.days)
        
        print("\n" + "=" * 80)
        print("ACTIVATION LICENSE GENERATED")
        print("=" * 80)
        print(f"Customer ID: {args.customer}")
        print(f"Activation Code: {activation_code}")
        print(f"Duration: {args.days} days")
        print(f"Expires: {expires_dt.strftime('%Y-%m-%d %H:%M:%S')}")
        print()
        print("License Key:")
        print("-" * 80)
        print(license_key)
        print("-" * 80)
        
        filename = save_license_record(args.customer, activation_code, license_key, expires_dt, args.days)
        
        print()
        print(f"💾 License saved to: {filename}")
        print(f"📋 Database updated: licenses/license_database.txt")
        print()
        print("=" * 80)
        print("HOW ACTIVATION WORKS:")
        print("=" * 80)
        print("1. Send license key to customer")
        print("2. Customer runs bot and pastes license key")
        print("3. Bot AUTO-BINDS to their machine on first run")
        print("4. License works ONLY on that machine")
        print()
        print("✓ No Machine ID needed from customer!")
        print("✓ Simple one-step activation")
        print("✓ Hardware-locked for security")
        print("=" * 80)

if __name__ == "__main__":
    main()
