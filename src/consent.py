"""
User Agreement / Risk Disclosure Consent Management

This module handles the first-run consent flow where users must accept
the terms and risk disclosure before using the trading bot.

Storage: Uses the database settings table with key 'user_consent_accepted'
Location: The consent is stored per-installation (database-based)

To modify the agreement text:
  - Edit the AGREEMENT_TEXT constant below
  - Update CONSENT_VERSION to force re-acceptance on major changes
"""

import os
import sys
from datetime import datetime

CONSENT_VERSION = "1.0"

AGREEMENT_TEXT = """
USER AGREEMENT & LIABILITY WAIVER
(For Discord Automation Bot, Webull API Integration & Auto-Trading Tool)

Effective Date: December 2024

1. ACKNOWLEDGMENT OF RISK
By installing, accessing, or using this software/application/bot ("Software"), you expressly acknowledge and agree that:
(a) Trading involves significant financial risk, including the possible loss of your entire investment.
(b) Automated trading may malfunction, execute trades incorrectly, or fail to execute trades.
(c) You alone are choosing to use this Software for trading purposes.
(d) You accept full responsibility for all actions taken by this Software.
The developer, creator, owner, or distributor ("Developer") assumes NO responsibility for your trading activity.

2. NO FINANCIAL ADVICE - NO FIDUCIARY DUTY
You understand and agree that:
- The Software is not a financial advisor.
- The Software does not provide investment recommendations.
- The Software cannot and does not guarantee any trading results.
- The Developer is not acting as your broker, advisor, agent, or fiduciary.
Any trading decision you make is 100% your decision and your responsibility.

3. "AS-IS" AND "AS-AVAILABLE" - NO WARRANTY
The Software is provided strictly "AS-IS," "AS-AVAILABLE," and WITHOUT ANY WARRANTY OF ANY KIND.
This includes (but is not limited to):
- No warranty of performance
- No warranty of accuracy
- No warranty of profitability
- No warranty of uptime
- No warranty of correct API behavior
- No guarantee of correct or timely order execution
- No guarantee of functioning risk management
You accept the Software with all faults, known and unknown.

4. TOTAL WAIVER OF LIABILITY
To the maximum extent permitted by law, you agree that the Developer:
- Is NOT liable for any direct damages
- Is NOT liable for any indirect damages
- Is NOT liable for incidental or consequential damages
- Is NOT liable for financial losses of any kind
- Is NOT liable for lost profits
- Is NOT liable for missed, late, duplicated, or incorrect trades
- Is NOT liable for account liquidation or margin calls
- Is NOT liable for trading losses
- Is NOT liable for emotional or psychological damages
- Is NOT liable for any "loss of opportunity"
- Is NOT liable for technical failures, bugs, or crashes
- Is NOT liable for incorrect market data or API errors
You hereby release the Developer from ALL claims, known or unknown, arising from your use of this Software.

5. YOU ASSUME ALL FINANCIAL, PERSONAL & TECHNICAL RISKS
This includes risks such as:
- Market volatility
- Slippage
- Incorrect parsing of signals
- Discord message delays
- Self-bot behavior being blocked
- API rate limits
- Broker downtime
- Webull API changes
- Loss of API access
- Loss of funds
- Loss of entire account
- Bot misinterpretation of trading signals
- Execution at unexpected prices
- Delayed or missing notifications
You accept ALL risks unconditionally.

6. DISCORD SELF-BOT & POLICY COMPLIANCE
This Software may use:
- Automated message reading
- Self-bot functionality
- Automated Discord interactions
You understand:
- Self-bots may violate Discord Terms of Service.
- You alone are responsible for compliance with Discord ToS.
- The Developer is not responsible for:
  - Discord account bans
  - Suspensions
  - Server bans
  - Enforcement actions
You use this Software on Discord at your own risk.

7. BROKERAGE & API COMPLIANCE (WEBULL, ALPACA, ETC.)
The Software may interact with brokerage APIs such as Webull, Alpaca, or others.
You acknowledge that:
- The Developer is not affiliated with any broker.
- The Developer does not guarantee API availability or accuracy.
- You alone are responsible for compliance with all brokerage rules, regulations, and policies.
The Developer is not liable for:
- API outages
- API errors
- Order failures
- Mis-executed trades
- Brokerage account termination

8. CREDENTIALS STORED LOCALLY - NOT ACCESSED BY DEVELOPER
All credentials (e.g., Discord token, API keys, Webull login) are stored locally on your machine.
The Developer:
- Does not store any credentials
- Does not have access to your accounts
- Does not collect personal data
- Does not control your trades
You are fully responsible for securing your system.

9. INDEMNIFICATION
You agree to indemnify, defend, and hold harmless the Developer from any claims, losses, damages, liabilities, legal costs, or expenses arising out of:
- Your use of this Software
- Your trading activities
- Your violation of Discord or brokerage policies
- Your use of self-bot functionalities
- Any financial losses you incur
- Any misuse or unauthorized modification of this Software

10. NO SUING / NO CLAIMS / NO DISPUTES
By using this Software, you agree that:
- You waive your right to sue the Developer for any reason whatsoever.
- You waive your right to make any financial or legal claims.
- You waive your right to demand compensation of any kind.
This agreement is binding and enforceable to the fullest extent permitted by law.

11. TERMINATION OF ACCESS
The Developer may modify, suspend, disable, or terminate the Software at any time, without notice, and without liability.

12. IF YOU DO NOT AGREE - DO NOT USE THIS SOFTWARE
If you do not accept all terms above:
- You must exit the application immediately
- You must delete all files associated with this Software
- You must stop using all functionality immediately
Continuing to use the Software constitutes full legal acceptance.

13. FINAL ACKNOWLEDGMENT
By installing, running, or using this Software, you affirm that:
- You read and understood this entire agreement
- You fully accept all risks associated with automated trading
- You acknowledge the Developer is not liable for anything
- You waive all legal rights to sue the Developer
- You voluntarily choose to proceed at your own risk
- You are solely responsible for all consequences
"""


def get_consent_status():
    """
    Check if user has accepted the agreement.
    
    Returns:
        dict: {
            'accepted': bool,
            'version': str or None,
            'accepted_at': str or None
        }
    """
    try:
        from gui_app import database as db
        
        accepted = db.get_setting('user_consent_accepted', 'false')
        version = db.get_setting('user_consent_version', None)
        accepted_at = db.get_setting('user_consent_timestamp', None)
        
        is_accepted = accepted.lower() == 'true' and version == CONSENT_VERSION
        
        return {
            'accepted': is_accepted,
            'version': version,
            'accepted_at': accepted_at,
            'current_version': CONSENT_VERSION
        }
    except Exception as e:
        print(f"[CONSENT] Error checking consent status: {e}")
        return {
            'accepted': False,
            'version': None,
            'accepted_at': None,
            'current_version': CONSENT_VERSION
        }


def accept_consent():
    """
    Record that the user has accepted the agreement.
    
    Returns:
        bool: True if successfully saved, False otherwise
    """
    try:
        from gui_app import database as db
        
        timestamp = datetime.now().isoformat()
        
        db.save_setting('user_consent_accepted', 'true')
        db.save_setting('user_consent_version', CONSENT_VERSION)
        db.save_setting('user_consent_timestamp', timestamp)
        
        print(f"[CONSENT] User accepted agreement v{CONSENT_VERSION} at {timestamp}")
        return True
    except Exception as e:
        print(f"[CONSENT] Error saving consent: {e}")
        return False


def revoke_consent():
    """
    Revoke user consent (for testing or if user wants to see agreement again).
    
    Returns:
        bool: True if successfully revoked, False otherwise
    """
    try:
        from gui_app import database as db
        
        db.save_setting('user_consent_accepted', 'false')
        db.save_setting('user_consent_version', None)
        db.save_setting('user_consent_timestamp', None)
        
        print("[CONSENT] User consent revoked")
        return True
    except Exception as e:
        print(f"[CONSENT] Error revoking consent: {e}")
        return False


def require_consent(redirect_func):
    """
    Decorator for Flask routes that require user consent.
    Use this to wrap routes that should only be accessible after consent.
    
    Usage:
        @app.route('/dashboard')
        @require_consent(lambda: redirect('/consent'))
        def dashboard():
            return render_template('dashboard.html')
    """
    from functools import wraps
    
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            status = get_consent_status()
            if not status['accepted']:
                return redirect_func()
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def get_agreement_text():
    """Get the current agreement text."""
    return AGREEMENT_TEXT


def ensure_user_consent():
    """
    CLI-based consent flow for Windows EXE or non-GUI environments.
    
    This function BLOCKS execution until the user accepts the agreement.
    Must be called BEFORE any Discord login, broker connection, or trading loops.
    
    Returns:
        bool: True if user accepted, exits program if declined
    """
    status = get_consent_status()
    
    if status['accepted']:
        return True
    
    print("\n" + "=" * 70)
    print(AGREEMENT_TEXT)
    print("=" * 70)
    print("\nTo continue using BotifyTrades, you must accept this agreement.")
    print("Type 'I AGREE' (exactly) to accept, or 'DECLINE' to exit.\n")
    
    while True:
        try:
            response = input("Your response: ").strip().upper()
            
            if response == "I AGREE":
                if accept_consent():
                    print("\n[CONSENT] Agreement accepted. Starting BotifyTrades...\n")
                    return True
                else:
                    print("\n[CONSENT] Error saving consent. Please try again.")
                    continue
            
            elif response == "DECLINE":
                print("\n" + "=" * 70)
                print("You did not agree to the User Agreement & Liability Waiver.")
                print("The application will now exit.")
                print("If you change your mind, you can restart the application.")
                print("=" * 70 + "\n")
                sys.exit(0)
            
            else:
                print("Please type exactly 'I AGREE' to accept or 'DECLINE' to exit.")
        
        except KeyboardInterrupt:
            print("\n\nInterrupted. Exiting...")
            sys.exit(0)
        except EOFError:
            print("\n\nNo input received. Exiting...")
            sys.exit(0)
