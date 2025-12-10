#!/usr/bin/env python3
"""
License Key Generator for Discord Trading Bot
Admin tool to generate customer license keys
"""

import sys
import argparse
from src.license_manager import LicenseManager

def main():
    parser = argparse.ArgumentParser(
        description='Generate license keys for Discord Trading Bot customers',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate 7-day trial license
  python generate_license.py --days 7 --customer "john_trial"
  
  # Generate 30-day license
  python generate_license.py --days 30 --customer "john_doe"
  
  # Generate 1-year license
  python generate_license.py --days 365 --customer "premium_customer"
  
  # Quick generation (interactive)
  python generate_license.py
        """
    )
    
    parser.add_argument('--days', type=int, help='Number of days license is valid')
    parser.add_argument('--customer', type=str, help='Customer identifier')
    parser.add_argument('--batch', type=int, help='Generate multiple licenses at once')
    
    args = parser.parse_args()
    
    print("=" * 70)
    print("Discord Trading Bot - License Key Generator")
    print("=" * 70)
    print()
    
    # Interactive mode if no args provided
    if args.days is None:
        print("Quick License Generation")
        print()
        print("Select license duration:")
        print("  1) 7 days (Trial)")
        print("  2) 15 days")
        print("  3) 30 days (Monthly)")
        print("  4) 90 days (Quarterly)")
        print("  5) 365 days (Yearly)")
        print("  6) Custom")
        print()
        
        choice = input("Enter choice (1-6): ").strip()
        
        days_map = {'1': 7, '2': 15, '3': 30, '4': 90, '5': 365}
        
        if choice in days_map:
            days = days_map[choice]
        elif choice == '6':
            days = int(input("Enter number of days: ").strip())
        else:
            print("Invalid choice")
            sys.exit(1)
        
        customer = input("Enter customer ID (optional, press Enter to skip): ").strip()
        if not customer:
            customer = "customer"
    else:
        days = args.days
        customer = args.customer or "customer"
    
    # Generate license(s)
    num_licenses = args.batch or 1
    
    print()
    print("=" * 70)
    print(f"Generating {num_licenses} license key(s) - {days} days validity")
    print("=" * 70)
    print()
    
    for i in range(num_licenses):
        customer_id = customer if num_licenses == 1 else f"{customer}_{i+1}"
        license_key = LicenseManager.generate_license(days, customer_id)
        
        print(f"License #{i+1}:")
        print(f"  Customer: {customer_id}")
        print(f"  Duration: {days} days")
        print(f"  Key: {license_key}")
        print()
        
        # Validate to show expiration
        is_valid, message, data = LicenseManager.validate_license(license_key)
        if is_valid:
            info = LicenseManager.get_license_info(license_key)
            print(f"  Status: ✅ {message}")
            print(f"  Expires: {info['expires_formatted']}")
            print()
    
    print("=" * 70)
    print("License generation complete!")
    print()
    print("📋 Next steps:")
    print("  1. Copy the license key above")
    print("  2. Send it to your customer")
    print("  3. Customer enters it when running the bot for the first time")
    print("=" * 70)

if __name__ == '__main__':
    main()
