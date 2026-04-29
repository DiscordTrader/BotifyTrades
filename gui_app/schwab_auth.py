"""
Charles Schwab OAuth Authentication Blueprint
Handles OAuth2 flow for Schwab API integration with automatic token refresh
"""

import os
import json
import asyncio
import threading
import time
import secrets
from datetime import datetime
from flask import Blueprint, redirect, request, url_for, flash, jsonify, session
from . import database as db

schwab_auth = Blueprint("schwab_auth", __name__)

_oauth_state_store = {}
_oauth_state_lock = threading.Lock()

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
        self._token_dead = False
        self.load_tokens()
    
    def load_tokens(self):
        """Load tokens from file"""
        try:
            if os.path.exists(SCHWAB_TOKEN_FILE):
                with open(SCHWAB_TOKEN_FILE, 'r', encoding='utf-8') as f:
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
            with open(SCHWAB_TOKEN_FILE, 'w', encoding='utf-8') as f:
                json.dump(self._token_data, f, indent=2)
            print(f"[SCHWAB TOKEN] Saved tokens, expires in {expires_in}s")
            self._refresh_failures = 0
            self._token_dead = False
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
        if self._token_dead:
            refresh_valid = False
        
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
                'refresh_token': self._token_data['refresh_token'],
                'client_id': creds['client_id']
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
                    
                    if response.status_code == 400 and ('invalid_grant' in response.text or 'refresh_token_authentication_error' in response.text or 'unsupported_token_type' in response.text):
                        self._token_dead = True
                        print("[SCHWAB TOKEN] ❌ Refresh token expired or revoked. Re-authentication required via Settings → Brokers.")
                    
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
                        if not success and self._token_dead:
                            print("[SCHWAB TOKEN] Refresh token is dead. Stopping auto-refresh. Re-authenticate via Settings → Brokers.")
                            break
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
                'redirect_uri': creds.get('redirect_uri', get_default_redirect_uri()),
                'dry_run': creds.get('dry_run', False)  # Default to LIVE mode
            }
    except Exception as e:
        print(f"[SCHWAB AUTH] Error getting credentials: {e}")
    return None


def get_default_redirect_uri():
    """Get the default redirect URI based on environment"""
    if os.environ.get("REPLIT_DEV_DOMAIN"):
        return f'https://{os.environ["REPLIT_DEV_DOMAIN"]}/api/schwab/callback'
    # For local deployments, use the automatic callback server on port 8182
    return 'https://127.0.0.1:8182/callback'


def get_local_callback_uri():
    """Get the local HTTPS callback URI for automatic OAuth."""
    return 'https://127.0.0.1:8182/callback'


def is_schwab_configured():
    """Check if Schwab is properly configured"""
    creds = get_schwab_credentials()
    return creds and creds.get('client_id') and creds.get('client_secret')


def is_schwab_authenticated():
    """Check if we have valid Schwab tokens"""
    try:
        if os.path.exists(SCHWAB_TOKEN_FILE):
            with open(SCHWAB_TOKEN_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return bool(data.get('access_token') and data.get('refresh_token'))
    except Exception:
        pass
    return False


def _generate_oauth_state(pkce_verifier=None, redirect_uri=None):
    """Generate and store a cryptographic state token for CSRF protection."""
    state = secrets.token_urlsafe(32)
    with _oauth_state_lock:
        _oauth_state_store[state] = {
            'created': time.time(),
            'pkce_verifier': pkce_verifier,
            'redirect_uri': redirect_uri,
            'used': False
        }
        for old_state in list(_oauth_state_store.keys()):
            if time.time() - _oauth_state_store[old_state]['created'] > 600:
                del _oauth_state_store[old_state]
    return state


def _validate_oauth_state(state):
    """Validate and consume a state token. Returns stored data or None."""
    if not state:
        return None
    with _oauth_state_lock:
        data = _oauth_state_store.get(state)
        if not data:
            return None
        if data['used']:
            return None
        if time.time() - data['created'] > 600:
            del _oauth_state_store[state]
            return None
        data['used'] = True
        return data


@schwab_auth.route("/schwab/auth-url")
def schwab_auth_url():
    """Return the Schwab OAuth authorization URL for popup-based flow."""
    if not is_schwab_configured():
        return jsonify({'success': False, 'error': 'Schwab is not configured. Please add Client ID and Secret first.'})

    try:
        import urllib.parse

        creds = get_schwab_credentials()
        if not creds:
            return jsonify({'success': False, 'error': 'Schwab credentials not found'})

        is_local = not os.environ.get("REPLIT_DEV_DOMAIN")
        pkce_verifier = None
        redirect_uri = get_default_redirect_uri()

        if is_local:
            try:
                from .schwab_oauth_server import get_oauth_server, start_oauth_flow

                redirect_uri = get_local_callback_uri()

                auth_url, oauth_server = start_oauth_flow(
                    client_id=creds['client_id'],
                    redirect_uri=redirect_uri,
                    use_pkce=True
                )

                if oauth_server:
                    pkce_verifier = oauth_server.get_pkce_verifier()
                    state = _generate_oauth_state(pkce_verifier=pkce_verifier, redirect_uri=redirect_uri)

                    session['schwab_pkce_verifier'] = pkce_verifier
                    session['schwab_redirect_uri'] = redirect_uri
                    session['schwab_oauth_state_token'] = state

                    if '&state=' not in auth_url and 'state=' not in auth_url:
                        auth_url += f"&state={state}"

                    print(f"[SCHWAB AUTH] Auth URL generated with state={state[:12]}... PKCE=yes")
                    return jsonify({'success': True, 'auth_url': auth_url, 'state': state})
                else:
                    print("[SCHWAB AUTH] Callback server failed to start")
            except ImportError as e:
                print(f"[SCHWAB AUTH] OAuth server module not available: {e}")

        state = _generate_oauth_state(redirect_uri=redirect_uri)
        session['schwab_oauth_state_token'] = state

        params = {
            'response_type': 'code',
            'client_id': creds['client_id'],
            'redirect_uri': redirect_uri,
            'scope': 'readonly',
            'state': state
        }

        auth_url = f"https://api.schwabapi.com/v1/oauth/authorize?{urllib.parse.urlencode(params)}"

        print(f"[SCHWAB AUTH] ========== AUTH URL GENERATED ==========")
        print(f"[SCHWAB AUTH] Client ID: {creds['client_id'][:8]}...")
        print(f"[SCHWAB AUTH] Redirect URI: {redirect_uri}")
        print(f"[SCHWAB AUTH] State: {state[:12]}...")

        return jsonify({'success': True, 'auth_url': auth_url, 'state': state})

    except Exception as e:
        print(f"[SCHWAB AUTH] Error generating auth URL: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})


@schwab_auth.route("/schwab/login")
def schwab_login():
    """Legacy login route — redirects to Schwab auth for non-popup flows."""
    if not is_schwab_configured():
        flash("Schwab is not configured. Please add Client ID and Secret in Settings.", "error")
        return redirect(url_for('settings'))

    try:
        import urllib.parse

        creds = get_schwab_credentials()
        if not creds:
            flash("Schwab credentials not found", "error")
            return redirect(url_for('settings'))

        redirect_uri = get_default_redirect_uri()
        state = _generate_oauth_state(redirect_uri=redirect_uri)
        session['schwab_oauth_state_token'] = state

        params = {
            'response_type': 'code',
            'client_id': creds['client_id'],
            'redirect_uri': redirect_uri,
            'scope': 'readonly',
            'state': state
        }

        auth_url = f"https://api.schwabapi.com/v1/oauth/authorize?{urllib.parse.urlencode(params)}"
        return redirect(auth_url)

    except Exception as e:
        print(f"[SCHWAB AUTH] Error initiating login: {e}")
        import traceback
        traceback.print_exc()
        flash(f"Failed to connect to Schwab: {str(e)}", "error")
        return redirect(url_for('settings'))


def _get_session_oauth_state():
    """Get session-scoped OAuth flow state."""
    from flask import session
    if 'schwab_oauth_state' not in session:
        session['schwab_oauth_state'] = {
            'completed': False,
            'success': False,
            'error': None,
            'in_progress': False
        }
    return session['schwab_oauth_state']


def _set_session_oauth_state(state: dict):
    """Set session-scoped OAuth flow state."""
    from flask import session
    session['schwab_oauth_state'] = state


@schwab_auth.route("/schwab/oauth-status")
def schwab_oauth_status():
    """Poll endpoint for checking OAuth flow completion status (session-scoped)."""
    flow_state = _get_session_oauth_state()

    try:
        from .schwab_oauth_server import get_oauth_server, OAuthCallbackHandler

        server = get_oauth_server()

        session_verifier = session.get('schwab_pkce_verifier')

        if OAuthCallbackHandler.callback_received.is_set():
            captured_code = OAuthCallbackHandler.auth_code
            OAuthCallbackHandler.auth_code = None
            OAuthCallbackHandler.callback_received.clear()

            if captured_code and not flow_state['completed']:
                flow_state['in_progress'] = True
                _set_session_oauth_state(flow_state)

                creds = get_schwab_credentials()
                if creds:
                    redirect_uri = session.get('schwab_redirect_uri', get_local_callback_uri())

                    success = exchange_code_for_tokens(
                        code=captured_code,
                        creds=creds,
                        pkce_verifier=session_verifier,
                        redirect_uri_override=redirect_uri
                    )

                    flow_state['completed'] = True
                    flow_state['success'] = success
                    flow_state['in_progress'] = False

                    if success:
                        db.update_broker_connection_status('SCHWAB', True)
                        _hot_connect_schwab_broker(creds)
                    else:
                        flow_state['error'] = get_last_exchange_error() or 'Token exchange failed'

                    _set_session_oauth_state(flow_state)

                    server.stop()
                    session.pop('schwab_pkce_verifier', None)
                    session.pop('schwab_redirect_uri', None)
                else:
                    flow_state['completed'] = True
                    flow_state['success'] = False
                    flow_state['error'] = 'Credentials not found'
                    _set_session_oauth_state(flow_state)

            elif OAuthCallbackHandler.error:
                flow_state['completed'] = True
                flow_state['success'] = False
                flow_state['error'] = OAuthCallbackHandler.error
                _set_session_oauth_state(flow_state)
                server.stop()

        return jsonify(flow_state)

    except ImportError:
        return jsonify({'completed': False, 'error': 'OAuth server not available'})


@schwab_auth.route("/schwab/oauth-reset", methods=['POST'])
def schwab_oauth_reset():
    """Reset the OAuth flow state (session-scoped)."""
    from flask import session
    
    # Reset session-scoped state
    session['schwab_oauth_state'] = {
        'completed': False,
        'success': False,
        'error': None,
        'in_progress': False
    }
    session.pop('schwab_pkce_verifier', None)
    session.pop('schwab_redirect_uri', None)
    
    try:
        from .schwab_oauth_server import get_oauth_server, OAuthCallbackHandler
        OAuthCallbackHandler.callback_received.clear()
        OAuthCallbackHandler.auth_code = None
        OAuthCallbackHandler.error = None
        get_oauth_server().stop()
    except Exception:
        pass
    
    return jsonify({'success': True})


@schwab_auth.route("/schwab/callback")
@schwab_auth.route("/api/schwab/callback")
def schwab_callback():
    """Handle Schwab OAuth callback (for Replit/web-based flow)."""
    try:
        print(f"[SCHWAB CALLBACK] ========== CALLBACK RECEIVED ==========")
        print(f"[SCHWAB CALLBACK] Full URL: {request.url}")
        print(f"[SCHWAB CALLBACK] Args: {dict(request.args)}")

        code = request.args.get('code')
        state = request.args.get('state')
        error = request.args.get('error')
        error_description = request.args.get('error_description', '')

        if error:
            print(f"[SCHWAB CALLBACK] Error from Schwab: {error} - {error_description}")
            return _render_callback_result_page(False, f"Authorization failed: {error} - {error_description}")

        if not code:
            print(f"[SCHWAB CALLBACK] No authorization code in request")
            return _render_callback_result_page(False, "No authorization code received from Schwab")

        if not state:
            print(f"[SCHWAB CALLBACK] Missing state parameter - rejecting for CSRF protection")
            return _render_callback_result_page(False, "Missing state parameter. Please try connecting again.")

        state_data = _validate_oauth_state(state)
        if not state_data:
            print(f"[SCHWAB CALLBACK] Invalid or expired state parameter")
            return _render_callback_result_page(False, "Invalid or expired session. Please try connecting again.")

        print(f"[SCHWAB CALLBACK] Got authorization code (first 20 chars): {code[:20]}...")

        creds = get_schwab_credentials()
        if not creds:
            print(f"[SCHWAB CALLBACK] No credentials found in database!")
            return _render_callback_result_page(False, "Schwab credentials not found. Please save your Client ID and Secret first.")

        redirect_uri = (state_data or {}).get('redirect_uri') or get_default_redirect_uri()
        pkce_verifier = (state_data or {}).get('pkce_verifier')
        print(f"[SCHWAB CALLBACK] Using redirect_uri: {redirect_uri}")

        success = exchange_code_for_tokens(code, creds, pkce_verifier=pkce_verifier, redirect_uri_override=redirect_uri)

        if success:
            print(f"[SCHWAB CALLBACK] ✓ Token exchange successful!")
            db.update_broker_connection_status('SCHWAB', True)
            _hot_connect_schwab_broker(creds)
            return _render_callback_result_page(True, "Successfully connected to Schwab!")
        else:
            last_error = get_last_exchange_error()
            print(f"[SCHWAB CALLBACK] ✗ Token exchange failed: {last_error}")
            return _render_callback_result_page(False, f"Token exchange failed: {last_error or 'Unknown error'}")

    except Exception as e:
        print(f"[SCHWAB AUTH] Callback error: {e}")
        import traceback
        traceback.print_exc()
        return _render_callback_result_page(False, f"Authentication failed: {str(e)}")


def _render_callback_result_page(success: bool, message: str) -> str:
    """Render a minimal callback page that notifies opener via postMessage and auto-closes."""
    status = 'success' if success else 'error'
    icon = '&#10004;' if success else '&#10008;'
    color = '#00ffa3' if success else '#ff5555'
    title = 'Schwab Connected!' if success else 'Connection Failed'
    safe_message = message.replace("'", "\\'")
    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>{title}</title>
    <style>
        body {{ font-family: Arial, sans-serif; background: #1a1a2e; color: {color};
               display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }}
        .container {{ text-align: center; padding: 40px; background: #16213e; border-radius: 12px;
                     box-shadow: 0 4px 20px rgba(0,0,0,0.3); max-width: 420px; }}
        h1 {{ margin-bottom: 16px; font-size: 24px; }}
        p {{ color: #a0a0a0; margin-bottom: 20px; font-size: 14px; }}
        .close-msg {{ font-size: 12px; color: #666; }}
    </style>
    <script>
        (function() {{
            var result = {{ status: '{status}', message: '{safe_message}' }};
            var origins = [
                'http://localhost:5000', 'http://127.0.0.1:5000',
                'http://localhost:3000', 'http://127.0.0.1:3000'
            ];
            if (window.opener) {{
                for (var i = 0; i < origins.length; i++) {{
                    try {{ window.opener.postMessage({{ type: 'schwab-oauth-callback', ...result }}, origins[i]); }} catch(e) {{}}
                }}
                if (window.location.hostname) {{
                    try {{ window.opener.postMessage({{ type: 'schwab-oauth-callback', ...result }}, window.location.origin); }} catch(e) {{}}
                }}
            }}
            setTimeout(function() {{
                try {{ window.close(); }} catch(e) {{}}
            }}, 2000);
            setTimeout(function() {{
                document.getElementById('close-msg').innerHTML =
                    'If this window did not close automatically, you can close it now.';
            }}, 3000);
        }})();
    </script>
</head>
<body>
    <div class="container">
        <h1>{icon} {title}</h1>
        <p>{message}</p>
        <p id="close-msg" class="close-msg">This window will close automatically...</p>
    </div>
</body>
</html>"""
    return html


_last_exchange_error = None

from typing import Optional

def exchange_code_for_tokens(
    code: str, 
    creds: dict, 
    pkce_verifier: Optional[str] = None,
    redirect_uri_override: Optional[str] = None,
    account_id: str = ""
) -> bool:
    """
    Exchange authorization code for access/refresh tokens using token manager.
    
    Args:
        code: Authorization code from OAuth callback
        creds: Schwab credentials dict with client_id, client_secret
        pkce_verifier: PKCE code_verifier if PKCE was used in authorization
        redirect_uri_override: Override redirect_uri (for automatic callback flow)
        account_id: Optional account ID for multi-account support
        
    Returns:
        True if tokens were successfully obtained and saved
    """
    global _last_exchange_error
    _last_exchange_error = None
    
    try:
        import httpx
        import base64
        
        # Use override redirect_uri if provided (for automatic callback)
        redirect_uri = redirect_uri_override or creds.get('redirect_uri')
        
        print(f"[SCHWAB AUTH] Exchanging code (first 20 chars): {code[:20]}...")
        print(f"[SCHWAB AUTH] Redirect URI: {redirect_uri}")
        if pkce_verifier:
            print(f"[SCHWAB AUTH] Using PKCE (verifier length: {len(pkce_verifier)})")
        
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
            'redirect_uri': redirect_uri,
            'client_id': creds['client_id']
        }
        
        # Add PKCE verifier if present
        if pkce_verifier:
            data['code_verifier'] = pkce_verifier
        
        with httpx.Client(timeout=30.0) as client:
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
                
                # Also save to secure storage if available
                try:
                    from .schwab_token_storage import get_secure_storage
                    storage = get_secure_storage()
                    storage.save_refresh_token(
                        refresh_token=token_data.get('refresh_token'),
                        account_id=account_id,
                        metadata={
                            'scope': token_data.get('scope', 'readonly'),
                            'expires_in': token_data.get('expires_in', 1800)
                        }
                    )
                except ImportError:
                    pass  # Secure storage not available
                
                # Start auto-refresh thread
                token_manager.start_auto_refresh()
                
                # Reset broker backoff state so it retries immediately
                try:
                    from gui_app.routes import _bot_instance
                    if _bot_instance and hasattr(_bot_instance, 'schwab_broker') and _bot_instance.schwab_broker:
                        if hasattr(_bot_instance.schwab_broker, 'reset_token_auth'):
                            _bot_instance.schwab_broker.reset_token_auth()
                            print(f"[SCHWAB AUTH] Broker backoff state reset")
                except Exception:
                    pass
                
                print(f"[SCHWAB AUTH] Tokens saved successfully, auto-refresh started")
                return True
            else:
                error_msg = f"HTTP {response.status_code}: {response.text}"
                print(f"[SCHWAB AUTH] Token exchange failed: {error_msg}")
                _last_exchange_error = error_msg
                
                # Parse specific error codes
                if response.status_code == 400:
                    try:
                        error_data = response.json()
                        error_code = error_data.get('error', '')
                        if error_code == 'invalid_grant':
                            _last_exchange_error = "Authorization code expired or already used. Please try again."
                        elif error_code == 'invalid_request':
                            _last_exchange_error = "Invalid request. Check redirect_uri matches exactly."
                    except Exception:
                        pass
                
                return False
                
    except Exception as e:
        print(f"[SCHWAB AUTH] Error exchanging code: {e}")
        import traceback
        traceback.print_exc()
        _last_exchange_error = str(e)
        return False


def _hot_connect_schwab_broker(creds: dict):
    """Hot-connect the Schwab broker to the running bot after OAuth succeeds."""
    try:
        from gui_app.routes import _bot_instance
        if not _bot_instance:
            print("[SCHWAB HOT-CONNECT] No bot instance running - will connect on next restart")
            return
        
        if _bot_instance.schwab_broker and getattr(_bot_instance.schwab_broker, 'connected', False):
            print("[SCHWAB HOT-CONNECT] Broker already connected, refreshing tokens only")
            if hasattr(_bot_instance.schwab_broker, 'reset_token_auth'):
                _bot_instance.schwab_broker.reset_token_auth()
            return
        
        from src.brokers.schwab_broker import SchwabBroker
        import asyncio

        schwab_broker = SchwabBroker({
            'client_id': creds.get('client_id'),
            'client_secret': creds.get('client_secret'),
            'redirect_uri': creds.get('redirect_uri', 'https://127.0.0.1'),
            'dry_run': creds.get('dry_run', False)
        })

        bot_loop = getattr(_bot_instance, 'loop', None)
        connected = False

        if bot_loop and bot_loop.is_running():
            try:
                future = asyncio.run_coroutine_threadsafe(schwab_broker.connect(), bot_loop)
                connected = future.result(timeout=30)
            except Exception as e:
                print(f"[SCHWAB HOT-CONNECT] Bot-loop connect failed: {e}")
                connected = False
        else:
            loop = asyncio.new_event_loop()
            try:
                connected = loop.run_until_complete(asyncio.wait_for(schwab_broker.connect(), timeout=30.0))
            except asyncio.TimeoutError:
                print("[SCHWAB HOT-CONNECT] Connection timeout (30s)")
                connected = False
            finally:
                loop.close()

        if connected:
            if bot_loop and not hasattr(schwab_broker, '_event_loop'):
                schwab_broker._event_loop = bot_loop
            _bot_instance.schwab_broker = schwab_broker
            mode = "PAPER" if creds.get('dry_run', False) else "LIVE"
            print(f"[SCHWAB HOT-CONNECT] ✓ Broker connected ({mode}) - ready for trading")

            if hasattr(_bot_instance, 'sync_service') and _bot_instance.sync_service:
                bm = getattr(_bot_instance.sync_service, 'broker_manager', None)
                if bm and hasattr(bm, 'schwab_broker'):
                    bm.schwab_broker = schwab_broker
                    print("[SCHWAB HOT-CONNECT] ✓ BrokerManager reference updated - sync service will include Schwab")

            try:
                from gui_app.broker_credentials_service import set_broker_status
                set_broker_status('schwab', True, 'connected')
            except Exception:
                pass

            try:
                from src.services.broker_health_monitor import get_health_monitor
                health_monitor = get_health_monitor()
                health_monitor.update_broker_status('SCHWAB', True, account_info={})
                print(f"[SCHWAB HOT-CONNECT] ✓ Health monitor updated - orders will route immediately")
            except Exception as he:
                print(f"[SCHWAB HOT-CONNECT] Health monitor update skipped: {he}")

            try:
                from gui_app.discord_notifier import notify_broker_reconnected
                notify_broker_reconnected(f'Schwab {mode}')
            except Exception:
                pass
        else:
            print("[SCHWAB HOT-CONNECT] ⚠️ Connection failed - tokens saved but broker not ready")
            print("[SCHWAB HOT-CONNECT] Scheduling background retry in 10s...")
            if bot_loop and bot_loop.is_running():
                async def _deferred_schwab_connect():
                    await asyncio.sleep(10)
                    try:
                        retry_connected = await schwab_broker.connect()
                        if retry_connected:
                            if not hasattr(schwab_broker, '_event_loop'):
                                schwab_broker._event_loop = bot_loop
                            _bot_instance.schwab_broker = schwab_broker
                            schwab_broker.connected = True
                            print(f"[SCHWAB HOT-CONNECT] ✅ Deferred retry succeeded — broker is now live")
                            try:
                                from gui_app.broker_credentials_service import set_broker_status
                                set_broker_status('schwab', True, 'connected')
                            except Exception:
                                pass
                        else:
                            print("[SCHWAB HOT-CONNECT] ⚠️ Deferred retry also failed — restart bot to connect")
                    except Exception as de:
                        print(f"[SCHWAB HOT-CONNECT] ⚠️ Deferred retry error: {de}")
                asyncio.run_coroutine_threadsafe(_deferred_schwab_connect(), bot_loop)
            
    except Exception as e:
        print(f"[SCHWAB HOT-CONNECT] Error: {e}")
        import traceback
        traceback.print_exc()


def get_last_exchange_error() -> str | None:
    """Get the last token exchange error for debugging"""
    return _last_exchange_error


@schwab_auth.route("/schwab/status")
def schwab_status():
    """Get Schwab connection status with detailed token info"""
    token_manager = get_token_manager()
    token_status = token_manager.get_token_status()
    
    creds = get_schwab_credentials()
    dry_run = creds.get('dry_run', False) if creds else False
    
    return jsonify({
        'configured': is_schwab_configured(),
        'authenticated': is_schwab_authenticated(),
        'redirect_uri': get_default_redirect_uri(),
        'dry_run': dry_run,
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
        token_manager = get_token_manager()
        token_manager.stop_auto_refresh()
        
        if os.path.exists(SCHWAB_TOKEN_FILE):
            os.remove(SCHWAB_TOKEN_FILE)
        
        token_manager._token_data = None
        
        db.update_broker_connection_status('SCHWAB', False)
        
        from gui_app.routes import _bot_instance
        if _bot_instance:
            schwab_broker = getattr(_bot_instance, 'schwab_broker', None)
            if schwab_broker:
                schwab_broker.connected = False
                if hasattr(schwab_broker, 'streaming_client'):
                    try:
                        schwab_broker.streaming_client = None
                    except Exception:
                        pass
        
        from gui_app.broker_credentials_service import set_broker_status
        set_broker_status('schwab', False, 'disconnected')
        
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
            _hot_connect_schwab_broker(creds)
            return jsonify({'success': True, 'message': 'Successfully connected to Schwab!'})
        else:
            # Get detailed error from Schwab
            detailed_error = get_last_exchange_error()
            if detailed_error:
                return jsonify({'success': False, 'error': f'Schwab API error: {detailed_error}'})
            return jsonify({'success': False, 'error': 'Failed to exchange code for tokens. Code may have expired.'})
            
    except Exception as e:
        print(f"[SCHWAB AUTH] Manual code error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})


def _migrate_schwab_dry_run():
    """Fix stored dry_run=True from old default. Schwab should default to LIVE."""
    try:
        creds = db.get_broker_credentials('SCHWAB')
        if creds:
            stored = creds.get('credentials', {})
            if stored.get('dry_run') == True:
                stored['dry_run'] = False
                import json
                conn = db.get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    'UPDATE broker_credentials SET credentials_encrypted = ? WHERE broker_name = ?',
                    (json.dumps(stored), 'SCHWAB')
                )
                conn.commit()
                print("[SCHWAB AUTH] ✓ Migrated dry_run=True → False (fixed old default)")
    except Exception as e:
        print(f"[SCHWAB AUTH] Migration check skipped: {e}")


def init_schwab_token_manager():
    """
    Initialize Schwab token manager on app startup.
    Call this from the main Flask app initialization.
    Loads tokens and starts auto-refresh if tokens exist.
    """
    try:
        _migrate_schwab_dry_run()
        
        token_manager = get_token_manager()
        
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
