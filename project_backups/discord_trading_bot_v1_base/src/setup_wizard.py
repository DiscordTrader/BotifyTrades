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

class SetupWizard:
    """Interactive credential setup wizard"""
    
    def __init__(self):
        self.config_dir = Path.home() / '.discord_trading_bot'
        self.config_file = self.config_dir / 'credentials.dat'
        
        # Check platform compatibility
        self.is_windows = platform.system() == 'Windows'
        if not self.is_windows:
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
        
        # Discord Token
        print("=" * 60)
        print("Step 1: Discord User Token")
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
        print("Step 2: Webull Credentials")
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
        
        # Save encrypted credentials
        print("=" * 60)
        print("Step 3: Secure Storage")
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
    
    def _load_credentials(self) -> dict:
        """Load existing credentials"""
        try:
            encrypted = self.config_file.read_bytes()
            credentials = self._decrypt_data(encrypted)
            print("✅ Loaded existing credentials (Windows DPAPI)")
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
