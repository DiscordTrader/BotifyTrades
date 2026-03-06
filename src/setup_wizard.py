#!/usr/bin/env python3
"""
Interactive Setup Wizard for Discord Trading Bot
Collects and securely stores credentials on first run
Uses Windows DPAPI for secure credential storage (Windows-only)
"""

import os
import json
import getpass
import platform
from pathlib import Path

# License System Configuration
# 'offline' = Machine-bound licenses (requires pre-shared Machine ID) - USE WITH generate_license_secure.py
# 'server' = Auto-activation (license binds on first run) - USE WITH generate_license_activation.py
LICENSE_MODE = 'server'  # Changed to 'server' - uses the new license client system

# Try to import license validation functions - make optional so wizard can still load
validate_license = None
get_current_machine_id = None
check_license = None
activate_license = None
get_machine_id = None

try:
    # Try new license client system first (preferred)
    from src.license.client import LicenseClient
    from src.license.crypto import get_machine_id as _get_machine_id
    
    def validate_license(key):
        client = LicenseClient()
        is_valid, result = client.validate_license(key)
        return is_valid
    
    def get_current_machine_id():
        return _get_machine_id()
    
    get_machine_id = get_current_machine_id
    check_license = validate_license
    activate_license = validate_license
    
except ImportError:
    try:
        from license.client import LicenseClient
        from license.crypto import get_machine_id as _get_machine_id
        
        def validate_license(key):
            client = LicenseClient()
            is_valid, result = client.validate_license(key)
            return is_valid
        
        def get_current_machine_id():
            return _get_machine_id()
        
        get_machine_id = get_current_machine_id
        check_license = validate_license
        activate_license = validate_license
        
    except ImportError:
        # Fallback: try legacy modules
        try:
            if LICENSE_MODE == 'offline':
                try:
                    from src.license_manager_secure import validate_license, get_current_machine_id
                except ImportError:
                    from license_manager_secure import validate_license, get_current_machine_id
            else:
                try:
                    from src.license_manager_activation import check_license, activate_license, get_machine_id
                except ImportError:
                    from license_manager_activation import check_license, activate_license, get_machine_id
        except ImportError:
            # All imports failed - license functions will be None
            # The wizard can still load but license validation will fail gracefully
            pass

class SetupWizard:
    """Interactive credential setup wizard"""
    
    _platform_warning_shown = False
    
    def __init__(self):
        self.config_dir = Path.home() / '.discord_trading_bot'
        self.config_file = self.config_dir / 'credentials.dat'
        
        # Check platform compatibility
        self.is_windows = platform.system() == 'Windows'
        if not self.is_windows and not SetupWizard._platform_warning_shown:
            SetupWizard._platform_warning_shown = True
            print("⚠️  Warning: This setup wizard is optimized for Windows.")
            print("   On Mac/Linux, credentials are stored with basic protection.")
            print()
        
    def _encrypt_data(self, data: dict) -> bytes:
        """Encrypt credential data using Windows DPAPI or fallback"""
        json_data = json.dumps(data).encode('utf-8')
        
        if self.is_windows:
            try:
                import win32crypt
                # Windows DPAPI - encrypts with user's Windows account
                # Only the current Windows user can decrypt this data
                encrypted = win32crypt.CryptProtectData(
                    json_data,
                    'Discord Trading Bot Credentials',  # Description
                    None,  # Optional entropy
                    None,  # Reserved
                    None,  # Prompt struct
                    0  # Flags
                )
                return encrypted
            except ImportError:
                print("⚠️  Warning: pywin32 not installed. Using basic encoding.")
                print("   For production, install: pip install pywin32")
                return json_data  # Fallback: no encryption
        else:
            # Mac/Linux fallback - just base64 encoding (not secure!)
            import base64
            return base64.b64encode(json_data)
    
    def _decrypt_data(self, encrypted: bytes) -> dict:
        """Decrypt credential data using Windows DPAPI or fallback"""
        if self.is_windows:
            try:
                import win32crypt
                # Windows DPAPI decryption
                _, json_data = win32crypt.CryptUnprotectData(
                    encrypted,
                    None,  # Optional entropy
                    None,  # Reserved
                    None,  # Prompt struct
                    0  # Flags
                )
                return json.loads(json_data)
            except ImportError:
                # Fallback: assume unencrypted
                return json.loads(encrypted)
        else:
            # Mac/Linux fallback
            import base64
            json_data = base64.b64decode(encrypted)
            return json.loads(json_data)
    
    def run(self) -> dict:
        """Run the setup wizard"""
        print("=" * 60)
        print("Discord Trading Bot - First-Time Setup")
        print("=" * 60)
        print()
        
        # Check if already configured
        if self.config_file.exists():
            print("Existing configuration found.")
            choice = input("Do you want to reconfigure? (yes/no): ").strip().lower()
            if choice not in ('yes', 'y'):
                # Load existing config
                return self._load_credentials()
        
        print("\n📝 This wizard will collect your credentials and store them securely.")
        print("⚠️  WARNING: These credentials give full access to your accounts!")
        print()
        
        credentials = {}
        
        # License Key Validation
        print("=" * 60)
        print("Step 1: License Activation")
        print("=" * 60)
        print()
        print("Choose your license option:")
        print()
        print("  1) 🆓 7-Day FREE Trial (No purchase required)")
        print("  2) 💳 Subscription License (Enter license key)")
        print()
        
        license_choice = input("Select option (1 or 2): ").strip()
        print()
        
        if license_choice == '1':
            # AUTO-GENERATE 7-DAY TRIAL LICENSE
            print("🎉 ACTIVATING FREE 7-DAY TRIAL...")
            print()
            
            # Import license generator
            try:
                from src.license_manager import LicenseManager
            except ImportError:
                from license_manager import LicenseManager
            
            # Generate unique customer ID
            import uuid
            trial_customer_id = uuid.uuid4().hex[:16]
            
            # Generate 7-day trial license
            trial_license_key = LicenseManager.generate_license(
                days=7,
                customer_id=f"trial_{trial_customer_id}"
            )
            
            # Validate it
            is_valid, message, license_data = LicenseManager.validate_license(trial_license_key)
            
            if is_valid:
                print("✅ FREE TRIAL ACTIVATED SUCCESSFULLY!")
                print(f"   ✓ Trial Period: 7 days")
                print(f"   ✓ Expires: {license_data.get('expires', 'N/A')}")
                print(f"   ✓ Customer ID: {trial_customer_id}")
                print()
                print("   📌 Your trial license key has been auto-generated.")
                print("   📌 After 7 days, you can purchase a subscription license.")
                print()
                
                credentials['LICENSE_KEY'] = trial_license_key
            else:
                print(f"❌ Trial generation failed: {message}")
                raise SystemExit("Setup cancelled - could not generate trial license")
        
        elif license_choice == '2':
            # SUBSCRIPTION LICENSE - PROMPT FOR KEY
            # Try to use LicenseClient for server-based validation (BTF-format licenses)
            try:
                try:
                    from src.license_client import LicenseClient
                except ImportError:
                    from license_client import LicenseClient
                
                client = LicenseClient()
                machine_id = client.machine_id
                
                print()
                print("╔" + "=" * 58 + "╗")
                print("║" + " " * 58 + "║")
                print("║" + "  🔑 LICENSE ACTIVATION".center(58) + "║")
                print("║" + " " * 58 + "║")
                print("║" + f"  Machine ID: {machine_id}".center(58) + "║")
                print("║" + " " * 58 + "║")
                print("╚" + "=" * 58 + "╝")
                print()
                
                license_valid = False
                while not license_valid:
                    license_key = input("Enter your subscription license key: ").strip()
                    
                    if not license_key:
                        print("❌ License key cannot be empty")
                        retry = input("Try again? (yes/no): ").strip().lower()
                        if retry not in ('yes', 'y'):
                            raise SystemExit("Setup cancelled - license key required")
                        continue
                    
                    # BTF-format licenses use server validation
                    if license_key.startswith('BTF-'):
                        print("[LICENSE] Activating with license server...")
                        
                        result = client.activate_license(license_key)
                        
                        if result.get('success') or result.get('is_valid'):
                            print()
                            print("✅ LICENSE ACTIVATED SUCCESSFULLY!")
                            print(f"   ✓ License Type: {result.get('license_type', 'subscription')}")
                            print(f"   ✓ Expires: {result.get('expires', 'N/A')}")
                            print(f"   ✓ Days Remaining: {result.get('days_remaining', 'N/A')}")
                            print()
                            credentials['LICENSE_KEY'] = license_key
                            license_valid = True
                        else:
                            error_msg = result.get('error') or result.get('message') or 'Unknown error'
                            print()
                            print(f"❌ Activation Failed: {error_msg}")
                            if result.get('offline'):
                                print("   ⚠️ Could not connect to license server")
                                print("   Check your internet connection or firewall settings")
                            print()
                            print(f"   Full response: {result}")
                            print()
                            retry = input("Try again? (yes/no): ").strip().lower()
                            if retry not in ('yes', 'y'):
                                raise SystemExit("Setup cancelled - valid license required")
                    else:
                        # Legacy format - use old validation
                        is_valid, license_data = validate_license(license_key)
                        
                        if is_valid:
                            print()
                            print("✅ LICENSE ACTIVATED SUCCESSFULLY!")
                            print(f"   ✓ Customer: {license_data['customer_id']}")
                            print(f"   ✓ Expires: {license_data['expires']}")
                            print(f"   ✓ Days Remaining: {license_data['days_remaining']}")
                            print()
                            credentials['LICENSE_KEY'] = license_key
                            license_valid = True
                        else:
                            print(f"❌ Validation Failed: {license_data.get('error', 'Unknown error')}")
                            retry = input("Try again? (yes/no): ").strip().lower()
                            if retry not in ('yes', 'y'):
                                raise SystemExit("Setup cancelled - valid license required")
                
            except ImportError:
                # Fallback to legacy validation if LicenseClient not available
                print("[WARNING] LicenseClient not available, using legacy validation")
                if LICENSE_MODE == 'offline':
                    machine_id = get_current_machine_id()
                else:
                    machine_id = "N/A"
                
                print()
                print("╔" + "=" * 58 + "╗")
                print("║" + " " * 58 + "║")
                print("║" + "  🔑 YOUR MACHINE ID (Copy this!)".center(58) + "║")
                print("║" + " " * 58 + "║")
                print("║" + f"  {machine_id}".center(58) + "║")
                print("║" + " " * 58 + "║")
                print("╚" + "=" * 58 + "╝")
                print()
                print("📋 INSTRUCTIONS:")
                print("   1. Copy your Machine ID above")
                print("   2. Send it to the bot provider via email/support")
                print("   3. You will receive a license key bound to THIS computer")
                print("   4. Paste the license key below")
                print()
                print("⚠️  IMPORTANT: The license will ONLY work on THIS computer")
                print("   If you change hardware, you'll need a new license")
                print()
                
                license_valid = False
                while not license_valid:
                    license_key = input("Enter your subscription license key: ").strip()
                    
                    if not license_key:
                        print("❌ License key cannot be empty")
                        print(f"   (Your Machine ID: {machine_id})")
                        retry = input("Try again? (yes/no): ").strip().lower()
                        if retry not in ('yes', 'y'):
                            raise SystemExit("Setup cancelled - license key required")
                        continue
                    
                    is_valid, license_data = validate_license(license_key)
                    
                    if is_valid:
                        print()
                        print("✅ LICENSE ACTIVATED SUCCESSFULLY!")
                        print(f"   ✓ Customer: {license_data['customer_id']}")
                        print(f"   ✓ Bound to machine: {license_data.get('machine_id', 'N/A')}")
                        print(f"   ✓ Expires: {license_data['expires']}")
                        print(f"   ✓ Days Remaining: {license_data['days_remaining']}")
                        print()
                        print("   This license is hardware-locked to THIS computer.")
                        credentials['LICENSE_KEY'] = license_key
                        license_valid = True
                    else:
                        print(f"❌ Validation Failed: {license_data.get('error', 'Unknown error')}")
                        print(f"   (Your Machine ID: {machine_id})")
                        retry = input("Try again? (yes/no): ").strip().lower()
                        if retry not in ('yes', 'y'):
                            raise SystemExit("Setup cancelled - valid license required")
        
        else:
            print("❌ Invalid choice. Please run setup again and choose 1 or 2.")
            raise SystemExit("Setup cancelled - invalid license option")
        
        print()
        
        # Discord Token
        print("=" * 60)
        print("Step 2: Discord User Token")
        print("=" * 60)
        print("To get your Discord user token:")
        print("1. Open Discord in your web browser (not the app)")
        print("2. Press F12 to open Developer Tools")
        print("3. Go to the Console tab")
        print("4. Paste this command and press Enter:")
        print("   (webpackChunkdiscord_app.push([[''],{},e=>{m=[];")
        print("   for(let c in e.c)m.push(e.c[c])}]),m).find(m=>")
        print("   m?.exports?.default?.getToken!==void 0).exports.default.getToken()")
        print("5. Copy the token (without quotes)")
        print()
        
        while True:
            token = getpass.getpass("Enter your Discord token (hidden): ").strip()
            if len(token) > 50:  # Basic validation
                credentials['DISCORD_USER_TOKEN'] = token
                break
            print("❌ Invalid token (too short). Please try again.")
        
        print("✅ Discord token saved")
        print()
        
        # Webull Tokens
        print("=" * 60)
        print("Step 3: Webull Credentials")
        print("=" * 60)
        print("You can use either saved tokens OR username/password.")
        print()
        
        choice = input("Do you have saved Webull tokens? (yes/no): ").strip().lower()
        
        if choice in ('yes', 'y'):
            # Token-based auth
            print("\nEnter your Webull tokens:")
            print("(Run this Python code once to get them:")
            print("  from webull import webull")
            print("  wb = webull()")
            print("  wb.login('email', 'password')")
            print("  print(wb.access_token, wb.refresh_token, wb.did)")
            print(")")
            print()
            
            credentials['WEBULL_ACCESS_TOKEN'] = getpass.getpass("Access Token (hidden): ").strip()
            credentials['WEBULL_REFRESH_TOKEN'] = getpass.getpass("Refresh Token (hidden): ").strip()
            credentials['WEBULL_DID'] = input("Device ID: ").strip()
        else:
            # Username/password auth
            print("\nEnter your Webull login credentials:")
            credentials['WEBULL_USERNAME'] = input("Email: ").strip()
            credentials['WEBULL_PASSWORD'] = getpass.getpass("Password (hidden): ").strip()
        
        # Trading PIN
        while True:
            pin = getpass.getpass("6-Digit Trading PIN (hidden): ").strip()
            if len(pin) == 6 and pin.isdigit():
                credentials['WEBULL_TRADE_PIN'] = pin
                break
            print("❌ Invalid PIN (must be 6 digits). Please try again.")
        
        print("✅ Webull credentials saved")
        print()
        
        # API Keys (Optional)
        print("=" * 60)
        print("Step 4: Optional API Keys (for advanced features)")
        print("=" * 60)
        print("These API keys enable optional features:")
        print("  • OpenAI API - AI-powered trade analysis and !analyze commands")
        print("  • Alpha Vantage API - Option flow scanning (FREE)")
        print("  • Finnhub API - Real-time market news (FREE)")
        print()
        print("You can skip these now and add them later via environment variables.")
        print()
        
        configure_apis = input("Configure API keys now? (yes/no): ").strip().lower()
        
        if configure_apis in ('yes', 'y'):
            print()
            
            # OpenAI API Key
            print("--- OpenAI API Key (for AI analysis) ---")
            print("Get your API key from: https://platform.openai.com/api-keys")
            print("(Leave blank to skip)")
            openai_key = getpass.getpass("OpenAI API Key (hidden, optional): ").strip()
            if openai_key:
                credentials['OPENAI_API_KEY'] = openai_key
                print("✅ OpenAI API key saved")
            else:
                print("⏭️  Skipped - AI features will be disabled")
            print()
            
            # Alpha Vantage API Key
            print("--- Alpha Vantage API Key (for option flow scanner) ---")
            print("Get FREE API key from: https://www.alphavantage.co/support/#api-key")
            print("(Leave blank to skip)")
            alphavantage_key = input("Alpha Vantage API Key (optional): ").strip()
            if alphavantage_key:
                credentials['ALPHA_VANTAGE_API_KEY'] = alphavantage_key
                print("✅ Alpha Vantage API key saved")
            else:
                print("⏭️  Skipped - Option flow scanner will be disabled")
            print()
            
            # Finnhub API Key
            print("--- Finnhub API Key (for real-time news) ---")
            print("Get FREE API key from: https://finnhub.io/register")
            print("(Leave blank to skip)")
            finnhub_key = input("Finnhub API Key (optional): ").strip()
            if finnhub_key:
                credentials['FINNHUB_API_KEY'] = finnhub_key
                print("✅ Finnhub API key saved")
            else:
                print("⏭️  Skipped - News features will be disabled")
            print()
        else:
            print("⏭️  Skipped API configuration")
            print("   You can add API keys later using environment variables:")
            print("   - OPENAI_API_KEY")
            print("   - ALPHA_VANTAGE_API_KEY")
            print("   - FINNHUB_API_KEY")
            print()
        
        # Save encrypted credentials
        print("=" * 60)
        print("Step 5: Secure Storage")
        print("=" * 60)
        
        if self.is_windows:
            print("Your credentials will be encrypted using Windows DPAPI.")
            print("Only your Windows account can decrypt them.")
        else:
            print("⚠️  Your credentials will be stored with basic protection.")
            print("   For production use, run on Windows with pywin32 installed.")
        print()
        
        # Create config directory
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        # Encrypt and save
        encrypted = self._encrypt_data(credentials)
        self.config_file.write_bytes(encrypted)
        
        # Set restrictive permissions (Unix-like systems)
        try:
            os.chmod(self.config_file, 0o600)  # Read/write for owner only
        except Exception:
            pass  # Windows doesn't support chmod the same way
        
        print(f"✅ Credentials stored at: {self.config_file}")
        print()
        print("=" * 60)
        print("Setup Complete!")
        print("=" * 60)
        print()
        print("⚠️  SECURITY REMINDERS:")
        print("  • Credentials are encrypted with your Windows account (DPAPI)")
        print("  • Never share your token or credentials with anyone")
        print("  • This bot violates Discord's Terms of Service")
        print("  • The bot executes real trades with real money")
        print("  • Always test with paper trading first")
        print()
        
        return credentials
    
    def _save_credentials(self, credentials: dict) -> bool:
        """Save credentials to encrypted file"""
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            encrypted = self._encrypt_data(credentials)
            self.config_file.write_bytes(encrypted)
            try:
                os.chmod(self.config_file, 0o600)
            except Exception:
                pass
            SetupWizard._credential_cache = None
            SetupWizard._credential_cache_time = 0
            print(f"✅ Credentials saved to: {self.config_file}")
            return True
        except Exception as e:
            print(f"❌ Failed to save credentials: {e}")
            return False
    
    _credential_cache = None
    _credential_cache_time = 0
    _CREDENTIAL_CACHE_TTL = 120
    
    def _load_credentials(self) -> dict:
        """Load existing credentials (cached for 120s to avoid repeated DPAPI calls)"""
        import time as _time
        now = _time.monotonic()
        if (SetupWizard._credential_cache is not None
                and (now - SetupWizard._credential_cache_time) < SetupWizard._CREDENTIAL_CACHE_TTL):
            return SetupWizard._credential_cache.copy()
        
        try:
            encrypted = self.config_file.read_bytes()
            credentials = self._decrypt_data(encrypted)
            print("✅ Loaded existing credentials (Windows DPAPI)")
            SetupWizard._credential_cache = credentials
            SetupWizard._credential_cache_time = now
            return credentials
        except Exception as e:
            print(f"❌ Failed to load credentials: {e}")
            print("Please run setup wizard again.")
            raise
    
    def load_or_setup(self) -> dict:
        """Load existing credentials or run setup wizard"""
        if self.config_file.exists():
            try:
                return self._load_credentials()
            except Exception:
                pass  # Fall through to setup wizard
        
        return self.run()


def main():
    """Run the setup wizard standalone"""
    wizard = SetupWizard()
    credentials = wizard.run()
    print("\nYou can now run the trading bot!")

if __name__ == '__main__':
    main()
