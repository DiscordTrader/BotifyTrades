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

CONSENT_VERSION = "2.0"

AGREEMENT_TEXT = """
USER AGREEMENT & LIABILITY WAIVER
(For Discord Automation Bot, Brokerage API Integration & Auto-Trading Tool)

Version: 2.0 - Strong Legal Edition
Effective Date: December 2024

================================================================================
1. ACKNOWLEDGMENT OF RISK
================================================================================
By using this Software, you acknowledge and agree that:

• Trading involves substantial financial risk, including the loss of your entire investment.
• Automated trading systems may malfunction, misinterpret data, execute incorrect trades, execute duplicate trades, or fail to execute trades.
• You alone decide whether to use this Software for trading purposes.
• You assume full responsibility for all actions taken by this Software.
• The Developer assumes no responsibility for your trading results, losses, or decisions.

================================================================================
2. NO FINANCIAL ADVICE — NO FIDUCIARY DUTY
================================================================================
You acknowledge and agree that:

• This Software is not a financial advisor.
• It does not provide investment recommendations, advice, or suitability analysis.
• The Developer is not your broker, agent, fiduciary, or representative.
• All trading decisions are entirely your own and at your own risk.
• No profitability is guaranteed or implied.

================================================================================
3. "AS-IS" AND "AS-AVAILABLE" — NO WARRANTY
================================================================================
The Software is provided strictly on an AS-IS and AS-AVAILABLE basis.

The Developer makes no warranties, express or implied, including but not limited to:
• Performance or profitability
• Accuracy or reliability
• Correct API behavior
• Timely or correct order execution
• Functioning of risk management features
• Uptime, availability, or continued support

You accept the Software with all faults, defects, and errors, known or unknown.

================================================================================
4. TOTAL WAIVER OF LIABILITY
================================================================================
To the maximum extent permitted by law, the Developer shall NOT be liable for:

• Direct, indirect, incidental, or consequential damages
• Financial losses, lost profits, account liquidation, margin calls
• Missed, incorrect, duplicate, late, or unintended trades
• Market losses or volatility impacts
• Emotional, psychological, or stress-related damages
• Technical failures, bugs, crashes, or software malfunctions
• Broker/API outages, errors, or data inaccuracies

You expressly waive any legal right to seek damages or compensation.

================================================================================
5. YOU ASSUME ALL RISKS
================================================================================
You assume all risks associated with automated trading, including:

• Market volatility, slippage, spreads
• Incorrect parsing of Discord messages or signals
• Message delays, API rate limits, and Discord blocks
• Broker/API downtime, API changes, revoked access
• Trading losses, including total loss of account value
• Bot misinterpretation, failed trades, or unexpected behavior

================================================================================
6. DISCORD SELF-BOT & POLICY COMPLIANCE
================================================================================
This Software may operate in a manner considered a self-bot, which may violate Discord's Terms of Service.

• You are 100% responsible for ensuring compliance with Discord policies.
• The Developer is not responsible for account warnings, suspensions, bans, or loss of access.

================================================================================
7. BROKERAGE & API COMPLIANCE
================================================================================
• The Developer is not affiliated with any brokerage or financial institution.
• The Software does not guarantee API availability, accuracy, or performance.
• You are solely responsible for complying with all brokerage rules, restrictions, and regulations.
• The Developer is not responsible for loss of API access, rejected orders, or brokerage enforcement actions.

================================================================================
8. LICENSE SERVER, HEARTBEAT VALIDATION, AND MACHINE ID BINDING
================================================================================
By using this Software, you acknowledge and agree to the following:

8.1 License Validation
----------------------
This Software requires communication with a remote License Server to:
• Verify subscription or license status
• Validate authenticity of your license key
• Confirm that the license is not shared or misused
• Enforce usage limits and subscription terms

8.2 Heartbeat Check
-------------------
The Software regularly sends a heartbeat request to the License Server to:
• Validate an active license
• Confirm subscription status
• Detect unauthorized use or tampering
• Prevent use of expired or invalid licenses

If the Software cannot reach the License Server, your license may be:
• Temporarily suspended
• Restricted
• Disabled until revalidation occurs

8.3 Machine ID Binding
----------------------
To prevent unauthorized license sharing:
• Your license may be bound to a unique hardware identifier (Machine ID).
• This Machine ID contains no personal data and is used only for anti-piracy and authentication.
• Changing hardware or attempting to spoof the Machine ID may invalidate the license.

8.4 Remote Disablement
----------------------
The Developer reserves the right to revoke, suspend, disable, block, or terminate any license that is:
• Expired
• Refunded or charged back
• Shared among unauthorized users
• Used on multiple machines without permission
• Tampered with or bypassed

8.5 Anti-Tampering
------------------
You agree not to:
• Reverse engineer the Software
• Modify or patch any executable or script
• Bypass the heartbeat or license checks
• Spoof Machine ID
• Interfere with server communication

Violation results in immediate termination of license and no refund.

================================================================================
9. CREDENTIALS STORED LOCALLY
================================================================================
• All credentials (Discord token, broker keys, passwords) are stored only on the user's machine.
• The Developer does not store, access, or control any brokerage or Discord accounts.
• You are fully responsible for securing your system, files, and environment.

================================================================================
10. INDEMNIFICATION
================================================================================
You agree to indemnify, defend, and hold harmless the Developer from any claims, losses, damages, liabilities, or expenses arising from:

• Use or misuse of the Software
• Trading losses
• API or brokerage behavior
• Discord account actions
• Violation of this Agreement

================================================================================
11. NO SUING / NO CLAIMS / NO DISPUTES
================================================================================
You waive all rights to:
• Sue the Developer
• Make financial or legal claims
• Demand refunds or compensation
• File disputes or chargebacks for any reason

All sales are final.

================================================================================
12. TERMINATION OF ACCESS
================================================================================
The Developer may, at any time and without notice, modify, suspend, disable, or terminate any part of the Software or licensing system, including:

• Heartbeat servers
• License validation
• API integrations
• Features and functionality

================================================================================
13. IF YOU DO NOT AGREE — DO NOT USE
================================================================================
If you disagree with any part of this Agreement:
• You must stop using the Software immediately
• Delete all files and uninstall the application

================================================================================
14. FINAL ACKNOWLEDGMENT
================================================================================
By installing, accessing, or using the Software, you affirm that you:

• Read and fully understand this Agreement
• Accept all risks of automated trading
• Acknowledge the Developer is not liable for anything
• Understand the Software may be disabled at any time
• Accept license-server, Machine ID, and heartbeat requirements
• Voluntarily choose to proceed at your own risk
• Are solely responsible for all consequences
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
        version = db.get_setting('user_consent_version', '')
        accepted_at = db.get_setting('user_consent_timestamp', '')
        
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
        db.save_setting('user_consent_version', '')
        db.save_setting('user_consent_timestamp', '')
        
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
