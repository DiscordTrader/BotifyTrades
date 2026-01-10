"""
Charles Schwab OAuth Authentication Blueprint
Handles OAuth2 flow for Schwab API integration with automatic token refresh
"""

import os
import json
import asyncio
import threading
import time
from datetime import datetime
from flask import Blueprint, redirect, request, url_for, flash, jsonify
from . import database as db

schwab_auth = Blueprint("schwab_auth", __name__)

SCHWAB_TOKEN_FILE = "schwab_token.json"
TOKEN_REFRESH_MARGIN_SECONDS = 300  # Refresh 5 minutes before expiry


class SchwabTokenManager:
    """
    Manages Schwab OAuth2 tokens with automatic refresh.
    
    Token lifecycle:
    - Access tokens expire in 30 minutes
    - Refresh tokens expire in 7 days
    - Automatically refreshes access token before expiry
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._refresh_thread = None
        self._stop_event = threading.Event()
        self._token_data = None
        self._last_refresh_attempt = 0
        self._refresh_failures = 0
        self.load_tokens()
    
    def load_tokens(self):
        """Load tokens from file"""
        try:
            if os.path.exists(SCHWAB_TOKEN_FILE):
                with open(SCHWAB_TOKEN_FILE, 'r') as f:
                    self._token_data = json.load(f)
                print(f"[SCHWAB TOKEN] Loaded tokens, expiry: {self._get_expiry_time_str()}")
                return True
        except Exception as e:
            print(f"[SCHWAB TOKEN] Error loading tokens: {e}")
        self._token_data = None
        return False
    
    def save_tokens(self, access_token: str, refresh_token: str, expires_in: int):
        """Save tokens to file"""
        try:
            self._token_data = {
                'access_token': access_token,
                'refresh_token': refresh_token,
                'token_expiry': datetime.now().timestamp() + expires_in,
                'refresh_token_created': datetime.now().timestamp(),
                'last_refreshed': datetime.now().isoformat()
            }
            with open(SCHWAB_TOKEN_FILE, 'w') as f:
                json.dump(self._token_data, f, indent=2)
            print(f"[SCHWAB TOKEN] Saved tokens, expires in {expires_in}s")
            self._refresh_failures = 0
            return True
        except Exception as e:
            print(f"[SCHWAB TOKEN] Error saving tokens: {e}")
            return False
    
    def get_access_token(self) -> str | None:
        """Get valid access token, refreshing if needed"""
        if not self._token_data:
            self.load_tokens()
        
        if not self._token_data:
            return None
        
        # Check if token needs refresh
        if self._needs_refresh():
            print("[SCHWAB TOKEN] Token expiring soon, refreshing...")
            if not self.refresh_tokens():
                print("[SCHWAB TOKEN] Refresh failed, token may be expired")
        
        return self._token_data.get('access_token')
    
    def get_refresh_token(self) -> str | None:
        """Get refresh token"""
        if not self._token_data:
            self.load_tokens()
        return self._token_data.get('refresh_token') if self._token_data else None
    
    def _needs_refresh(self) -> bool:
        """Check if token needs refresh (within margin of expiry)"""
        if not self._token_data:
            return False
        
        expiry = self._token_data.get('token_expiry', 0)
        return datetime.now().timestamp() > (expiry - TOKEN_REFRESH_MARGIN_SECONDS)
    
    def _get_expiry_time_str(self) -> str:
        """Get human-readable expiry time"""
        if not self._token_data:
            return "No tokens"
        expiry = self._token_data.get('token_expiry', 0)
        if expiry:
            return datetime.fromtimestamp(expiry).strftime('%Y-%m-%d %H:%M:%S')
        return "Unknown"
    
    def get_token_status(self) -> dict:
        """Get current token status for UI display"""
        if not self._token_data:
            self.load_tokens()
        
        if not self._token_data:
            return {
                'has_tokens': False,
                'access_token_valid': False,
                'needs_reauth': True,
                'message': 'Not authenticated'
            }
        
        now = datetime.now().timestamp()
        expiry = self._token_data.get('token_expiry', 0)
        refresh_created = self._token_data.get('refresh_token_created', 0)
        
        access_valid = now < expiry
        refresh_valid = (now - refresh_created) < (7 * 24 * 60 * 60) if refresh_created else True
        
        seconds_until_expiry = max(0, expiry - now)
        minutes_until_expiry = int(seconds_until_expiry / 60)
        
        if not refresh_valid:
            message = 'Refresh token expired (7 days). Please re-authenticate.'
        elif not access_valid:
            message = 'Access token expired. Auto-refresh will attempt on next API call.'
        elif minutes_until_expiry < 10:
            message = f'Access token expires in {minutes_until_expiry} min. Auto-refresh scheduled.'
        else:
            message = f'Connected. Token valid for {minutes_until_expiry} min.'
        
        return {
            'has_tokens': True,
            'access_token_valid': access_valid,
            'refresh_token_valid': refresh_valid,
            'needs_reauth': not refresh_valid,
            'expires_in_minutes': minutes_until_expiry,
            'last_refreshed': self._token_data.get('last_refreshed', 'Unknown'),
            'message': message
        }
    
    def refresh_tokens(self) -> bool:
        """Refresh access token using refresh token"""
        # Rate limit refresh attempts
        now = time.time()
        if now - self._last_refresh_attempt < 30:
            print("[SCHWAB TOKEN] Rate limiting refresh attempts")
            return False
        self._last_refresh_attempt = now
        
        if not self._token_data or not self._token_data.get('refresh_token'):
            print("[SCHWAB TOKEN] No refresh token available")
            return False
        
        try:
            import httpx
            import base64
            
            creds = get_schwab_credentials()
            if not creds:
                print("[SCHWAB TOKEN] No credentials configured")
                return False
            
            credentials = base64.b64encode(
                f"{creds['client_id']}:{creds['client_secret']}".encode()
            ).decode()
            
            headers = {
                'Authorization': f'Basic {credentials}',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            data = {
                'grant_type': 'refresh_token',
                'refresh_token': self._token_data['refresh_token']
            }
            
            print("[SCHWAB TOKEN] Sending refresh token request...")
            
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    'https://api.schwabapi.com/v1/oauth/token',
                    headers=headers,
                    data=data
                )
                
                if response.status_code == 200:
                    token_data = response.json()
                    
                    self.save_tokens(
                        access_token=token_data.get('access_token'),
                        refresh_token=token_data.get('refresh_token'),
                        expires_in=token_data.get('expires_in', 1800)
                    )
                    
                    print("[SCHWAB TOKEN] Token refresh successful!")
                    self._refresh_failures = 0
                    return True
                else:
                    self._refresh_failures += 1
                    print(f"[SCHWAB TOKEN] Refresh failed: {response.status_code}")
                    print(f"[SCHWAB TOKEN] Response: {response.text}")
                    
                    if response.status_code == 400 and 'invalid_grant' in response.text:
                        print("[SCHWAB TOKEN] Refresh token expired or revoked. Re-authentication required.")
                    
                    return False
                    
        except Exception as e:
            self._refresh_failures += 1
            print(f"[SCHWAB TOKEN] Error refreshing tokens: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def start_auto_refresh(self):
        """Start background thread for automatic token refresh"""
        if self._refresh_thread and self._refresh_thread.is_alive():
            print("[SCHWAB TOKEN] Auto-refresh already running")
            return
        
        self._stop_event.clear()
        self._refresh_thread = threading.Thread(
            target=self._auto_refresh_loop,
            daemon=True,
            name="SchwabTokenRefresh"
        )
        self._refresh_thread.start()
        print("[SCHWAB TOKEN] Auto-refresh thread started")
    
    def stop_auto_refresh(self):
        """Stop the auto-refresh thread"""
        self._stop_event.set()
        if self._refresh_thread:
            self._refresh_thread.join(timeout=5)
        print("[SCHWAB TOKEN] Auto-refresh thread stopped")
    
    def _auto_refresh_loop(self):
        """Background loop that refreshes tokens before expiry"""
        print("[SCHWAB TOKEN] Auto-refresh loop started")
        
        while not self._stop_event.is_set():
            try:
                if not self._token_data:
                    self.load_tokens()
                
                if self._token_data:
                    expiry = self._token_data.get('token_expiry', 0)
                    now = datetime.now().timestamp()
                    
                    # Calculate time until we should refresh (5 min before expiry)
                    refresh_at = expiry - TOKEN_REFRESH_MARGIN_SECONDS
                    sleep_time = max(60, refresh_at - now)  # At least 60 seconds
                    
                    if now >= refresh_at:
                        # Time to refresh
                        print("[SCHWAB TOKEN] Auto-refresh triggered")
                        success = self.refresh_tokens()
                        if not success and self._refresh_failures >= 3:
                            print("[SCHWAB TOKEN] Multiple refresh failures, stopping auto-refresh")
                            break
                        sleep_time = 60  # Check again in 1 minute
                    else:
                        print(f"[SCHWAB TOKEN] Next refresh in {int(sleep_time/60)} minutes")
                else:
                    sleep_time = 300  # No tokens, check every 5 minutes
                
                # Sleep in small increments to allow stop event to work
                for _ in range(int(sleep_time)):
                    if self._stop_event.is_set():
                        break
                    time.sleep(1)
                    
            except Exception as e:
                print(f"[SCHWAB TOKEN] Error in auto-refresh loop: {e}")
                time.sleep(60)
        
        print("[SCHWAB TOKEN] Auto-refresh loop ended")


# Global token manager instance
_token_manager = None

def get_token_manager() -> SchwabTokenManager:
    """Get or create the singleton token manager"""
    global _token_manager
    if _token_manager is None:
        _token_manager = SchwabTokenManager()
    return _token_manager


def get_schwab_credentials():
    """Get Schwab credentials from database"""
    try:
        result = db.get_broker_credentials('SCHWAB')
        if result:
            creds = result.get('credentials', {})
            return {
                'client_id': creds.get('client_id', ''),
                'client_secret': creds.get('client_secret', ''),
                'redirect_uri': creds.get('redirect_uri', get_default_redirect_uri())
            }
    except Exception as e:
        print(f"[SCHWAB AUTH] Error getting credentials: {e}")
    return None


def get_default_redirect_uri():
    """Get the default redirect URI based on environment"""
    if os.environ.get("REPLIT_DEV_DOMAIN"):
        return f'https://{os.environ["REPLIT_DEV_DOMAIN"]}/schwab/callback'
    return 'https://127.0.0.1'


def is_schwab_configured():
    """Check if Schwab is properly configured"""
    creds = get_schwab_credentials()
    return creds and creds.get('client_id') and creds.get('client_secret')


def is_schwab_authenticated():
    """Check if we have valid Schwab tokens"""
    try:
        if os.path.exists(SCHWAB_TOKEN_FILE):
            with open(SCHWAB_TOKEN_FILE, 'r') as f:
                data = json.load(f)
                return bool(data.get('access_token') and data.get('refresh_token'))
    except Exception:
        pass
    return False


@schwab_auth.route("/schwab/login")
def schwab_login():
    """Initiate Schwab OAuth login flow"""
    if not is_schwab_configured():
        flash("Schwab is not configured. Please add Client ID and Secret in Settings.", "error")
        return redirect(url_for('settings_page'))
    
    try:
        import urllib.parse
        
        creds = get_schwab_credentials()
        if not creds:
            flash("Schwab credentials not found", "error")
            return redirect(url_for('settings_page'))
        
        params = {
            'response_type': 'code',
            'client_id': creds['client_id'],
            'redirect_uri': creds['redirect_uri'],
            'scope': 'readonly'
        }
        
        auth_url = f"https://api.schwabapi.com/v1/oauth/authorize?{urllib.parse.urlencode(params)}"
        
        print(f"[SCHWAB AUTH] Redirecting to Schwab for authorization...")
        print(f"[SCHWAB AUTH] Callback URL: {creds['redirect_uri']}")
        
        return redirect(auth_url)
        
    except Exception as e:
        print(f"[SCHWAB AUTH] Error initiating login: {e}")
        flash(f"Failed to connect to Schwab: {str(e)}", "error")
        return redirect(url_for('settings_page'))


@schwab_auth.route("/schwab/callback")
def schwab_callback():
    """Handle Schwab OAuth callback"""
    try:
        code = request.args.get('code')
        error = request.args.get('error')
        
        if error:
            flash(f"Schwab authorization failed: {error}", "error")
            return redirect(url_for('settings_page'))
        
        if not code:
            flash("No authorization code received from Schwab", "error")
            return redirect(url_for('settings_page'))
        
        creds = get_schwab_credentials()
        if not creds:
            flash("Schwab credentials not found", "error")
            return redirect(url_for('settings_page'))
        
        success = exchange_code_for_tokens(code, creds)
        
        if success:
            flash("Successfully connected to Schwab!", "success")
            db.update_broker_connection_status('SCHWAB', True)
        else:
            flash("Failed to exchange authorization code for tokens", "error")
        
        return redirect(url_for('settings_page'))
        
    except Exception as e:
        print(f"[SCHWAB AUTH] Callback error: {e}")
        import traceback
        traceback.print_exc()
        flash(f"Authentication failed: {str(e)}", "error")
        return redirect(url_for('settings_page'))


def exchange_code_for_tokens(code: str, creds: dict) -> bool:
    """Exchange authorization code for access/refresh tokens using token manager"""
    try:
        import httpx
        import base64
        
        credentials = base64.b64encode(
            f"{creds['client_id']}:{creds['client_secret']}".encode()
        ).decode()
        
        headers = {
            'Authorization': f'Basic {credentials}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        data = {
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': creds['redirect_uri']
        }
        
        with httpx.Client() as client:
            response = client.post(
                'https://api.schwabapi.com/v1/oauth/token',
                headers=headers,
                data=data
            )
            
            if response.status_code == 200:
                token_data = response.json()
                
                # Use token manager to save and manage tokens
                token_manager = get_token_manager()
                token_manager.save_tokens(
                    access_token=token_data.get('access_token'),
                    refresh_token=token_data.get('refresh_token'),
                    expires_in=token_data.get('expires_in', 1800)
                )
                
                # Start auto-refresh thread
                token_manager.start_auto_refresh()
                
                print(f"[SCHWAB AUTH] Tokens saved successfully, auto-refresh started")
                return True
            else:
                print(f"[SCHWAB AUTH] Token exchange failed: {response.status_code}")
                print(f"[SCHWAB AUTH] Response: {response.text}")
                return False
                
    except Exception as e:
        print(f"[SCHWAB AUTH] Error exchanging code: {e}")
        import traceback
        traceback.print_exc()
        return False


@schwab_auth.route("/schwab/status")
def schwab_status():
    """Get Schwab connection status with detailed token info"""
    token_manager = get_token_manager()
    token_status = token_manager.get_token_status()
    
    return jsonify({
        'configured': is_schwab_configured(),
        'authenticated': is_schwab_authenticated(),
        'redirect_uri': get_default_redirect_uri(),
        'token_status': token_status
    })


@schwab_auth.route("/schwab/refresh", methods=['POST'])
def schwab_refresh():
    """Manually trigger token refresh"""
    try:
        token_manager = get_token_manager()
        
        # Check if rate limited
        now = time.time()
        if now - token_manager._last_refresh_attempt < 30:
            return jsonify({
                'success': False, 
                'error': 'Rate limited. Please wait 30 seconds between refresh attempts.',
                'rate_limited': True
            })
        
        success = token_manager.refresh_tokens()
        
        if success:
            return jsonify({'success': True, 'message': 'Token refreshed successfully'})
        else:
            return jsonify({'success': False, 'error': 'Failed to refresh token. May need to re-authenticate.'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@schwab_auth.route("/schwab/disconnect", methods=['POST'])
def schwab_disconnect():
    """Disconnect from Schwab (remove tokens)"""
    try:
        # Stop auto-refresh thread
        token_manager = get_token_manager()
        token_manager.stop_auto_refresh()
        
        if os.path.exists(SCHWAB_TOKEN_FILE):
            os.remove(SCHWAB_TOKEN_FILE)
        
        # Clear token manager's cached data
        token_manager._token_data = None
        
        db.update_broker_connection_status('SCHWAB', False)
        return jsonify({'success': True, 'message': 'Disconnected from Schwab'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@schwab_auth.route("/schwab/manual-code", methods=['POST'])
def schwab_manual_code():
    """
    Manual code entry for local deployments where callback URL doesn't work.
    User copies the full redirect URL or just the code from their browser.
    """
    try:
        data = request.get_json() or {}
        code_or_url = data.get('code', '').strip()
        
        if not code_or_url:
            return jsonify({'success': False, 'error': 'No code provided'})
        
        # Extract code from full URL if provided
        import urllib.parse
        if 'code=' in code_or_url:
            # Parse the URL to extract the code parameter
            if code_or_url.startswith('http'):
                parsed = urllib.parse.urlparse(code_or_url)
                params = urllib.parse.parse_qs(parsed.query)
                code = params.get('code', [''])[0]
            else:
                # Just the query string portion
                params = urllib.parse.parse_qs(code_or_url)
                code = params.get('code', [''])[0]
        else:
            code = code_or_url
        
        if not code:
            return jsonify({'success': False, 'error': 'Could not extract authorization code'})
        
        # URL decode the code (handles %40 -> @, etc.)
        code = urllib.parse.unquote(code)
        
        print(f"[SCHWAB AUTH] Manual code entry - extracted code: {code[:20]}...")
        
        creds = get_schwab_credentials()
        if not creds:
            return jsonify({'success': False, 'error': 'Schwab credentials not configured'})
        
        success = exchange_code_for_tokens(code, creds)
        
        if success:
            db.update_broker_connection_status('SCHWAB', True)
            return jsonify({'success': True, 'message': 'Successfully connected to Schwab!'})
        else:
            return jsonify({'success': False, 'error': 'Failed to exchange code for tokens. Code may have expired.'})
            
    except Exception as e:
        print(f"[SCHWAB AUTH] Manual code error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})


def init_schwab_token_manager():
    """
    Initialize Schwab token manager on app startup.
    Call this from the main Flask app initialization.
    Loads tokens and starts auto-refresh if tokens exist.
    """
    try:
        token_manager = get_token_manager()
        
        # Force load tokens from file on startup
        token_manager.load_tokens()
        
        if token_manager._token_data and token_manager._token_data.get('refresh_token'):
            print("[SCHWAB AUTH] Existing tokens found, starting auto-refresh...")
            token_manager.start_auto_refresh()
            return True
        else:
            print("[SCHWAB AUTH] No existing tokens, auto-refresh not started")
            return False
    except Exception as e:
        print(f"[SCHWAB AUTH] Error initializing token manager: {e}")
        return False
