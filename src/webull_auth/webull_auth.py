"""
Webull Authentication Module
Handles Webull login with MFA support, session persistence via database storage.
Uses adapter pattern for database access - credentials stored encrypted in SQLite.
"""
from typing import Optional, Dict, Any, Callable
from webull import webull, paper_webull
import requests


def _patched_get_account_id(self, id=0):
    """
    Patched version of webull.get_account_id() that handles missing 'rzone' field.
    Webull API changed in late 2025 to sometimes omit 'rzone' from responses.
    """
    headers = self.build_req_headers()
    response = requests.get(self._urls.account_id(), headers=headers, timeout=self.timeout)
    
    if response.status_code != 200:
        print(f"[WEBULL AUTH] get_account_id HTTP {response.status_code}: {response.text[:200]}")
        return None
    
    try:
        result = response.json()
    except Exception:
        print(f"[WEBULL AUTH] get_account_id non-JSON response: {response.text[:200]}")
        return None
    
    if result.get('success') and len(result.get('data', [])) > 0:
        account_data = result['data'][int(id)]
        self.zone_var = str(account_data.get('rzone', getattr(self, 'zone_var', 'dc_core_r001')))
        self._account_id = str(account_data.get('secAccountId', ''))
        self._region_code = account_data.get('regionId', account_data.get('region_id', ''))
        return self._account_id
    else:
        print(f"[WEBULL AUTH] get_account_id failed - API response: {str(result)[:300]}")
        return None

webull.get_account_id = _patched_get_account_id
paper_webull.get_account_id = _patched_get_account_id


class WebullAuth:
    """
    Webull authentication with database-backed session persistence.
    
    Args:
        paper_trading: Use paper trading mode
        credentials_adapter: Optional adapter for credential storage (database)
    """
    
    def __init__(self, paper_trading: bool = False, credentials_adapter: Optional[Callable] = None):
        self.paper_trading = paper_trading
        self.wb = paper_webull() if paper_trading else webull()
        self.logged_in = False
        self.account_id = None
        self._credentials_adapter = credentials_adapter
        
    def set_credentials_adapter(self, adapter: Callable):
        """Set the credentials adapter for database storage"""
        self._credentials_adapter = adapter
        
    def login(
        self, 
        email: str, 
        password: str, 
        trading_pin: str, 
        device_id: Optional[str] = None,
        mfa_code: Optional[str] = None, 
        security_qid: Optional[str] = None, 
        security_answer: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Login to Webull with optional MFA support.
        
        Args:
            email: Webull account email
            password: Webull account password
            trading_pin: 6-digit trading PIN
            device_id: Optional device ID for MFA bypass
            mfa_code: MFA code if required
            security_qid: Security question ID if required
            security_answer: Security question answer if required
            
        Returns:
            Dict with success status, account_id or error details
        """
        try:
            if device_id:
                self.wb._set_did(device_id)
            
            # Try saved session first
            session_result = self._try_saved_session(trading_pin)
            if session_result.get("success"):
                return {"success": True, "account_id": self.account_id, "method": "saved_session"}
            
            if mfa_code and security_qid and security_answer:
                result = self.wb.login(
                    email, 
                    password, 
                    'DiscordTradingBot',
                    mfa_code,
                    security_qid,
                    security_answer
                )
            elif mfa_code:
                result = self.wb.login(email, password, 'DiscordTradingBot', mfa_code)
            else:
                result = self.wb.login(email, password)
            
            if result:
                result_str = str(result)
                if 'accessToken' in result_str or 'access_token' in result_str or result.get('success') == True:
                    self.wb.get_trade_token(trading_pin)
                    self.logged_in = True
                    self.account_id = self.wb.get_account_id()
                    self._save_session()
                    return {"success": True, "account_id": self.account_id}
                elif 'extInfo' in result_str or 'mfa' in result_str.lower():
                    return {
                        "success": False, 
                        "error": "MFA required",
                        "needs_mfa": True,
                        "result": result
                    }
                else:
                    error_msg = result.get('msg', 'Login failed') if isinstance(result, dict) else 'Login failed'
                    error_code = result.get('code', '') if isinstance(result, dict) else ''
                    if error_code == 'user.check.slider.pic.fail':
                        error_msg = 'CAPTCHA verification required. Try logging in via browser first, or use saved tokens.'
                    elif error_code == 'account.pwd.mismatch':
                        error_msg = f"Incorrect password. {result.get('data', {}).get('allowPwdErrorTime', 'Several')} attempts remaining."
                    return {"success": False, "error": error_msg, "code": error_code, "result": result}
            else:
                return {"success": False, "error": "Login returned empty response"}
                
        except Exception as e:
            error_msg = str(e)
            if 'mfa' in error_msg.lower() or 'verification' in error_msg.lower():
                return {"success": False, "error": "MFA required", "needs_mfa": True}
            if 'Expecting value' in error_msg or 'JSONDecodeError' in error_msg or 'line 1 column 1' in error_msg:
                return {
                    "success": False, 
                    "error": "Webull CAPTCHA/anti-bot protection detected. Email login is blocked. Please use Token-Only Mode instead.",
                    "captcha_blocked": True
                }
            return {"success": False, "error": error_msg}
    
    def _try_saved_session(self, trading_pin: str) -> Dict[str, Any]:
        """Try to restore session from database-stored tokens. Returns dict with success/error."""
        import sys
        import traceback
        try:
            print(f"[WEBULL AUTH DEBUG] === _try_saved_session START ===", flush=True)
            creds = self._load_credentials()
            if not creds:
                print(f"[WEBULL AUTH DEBUG] No credentials found in database", flush=True)
                return {"success": False, "error": "No Webull credentials found in database"}
            
            # Debug: show all credential keys
            print(f"[WEBULL AUTH DEBUG] Credential keys: {list(creds.keys())}", flush=True)
            print(f"[WEBULL AUTH DEBUG] access_token: {'yes' if creds.get('access_token') else 'no'} (len={len(creds.get('access_token', ''))})", flush=True)
            print(f"[WEBULL AUTH DEBUG] refresh_token: {'yes' if creds.get('refresh_token') else 'no'}", flush=True)
            print(f"[WEBULL AUTH DEBUG] zone_var: {creds.get('zone_var', 'NOT SET')}", flush=True)
            print(f"[WEBULL AUTH DEBUG] rzone: {creds.get('rzone', 'NOT SET')}", flush=True)
            print(f"[WEBULL AUTH DEBUG] account_id: {creds.get('account_id', 'NOT SET')}", flush=True)
            print(f"[WEBULL AUTH DEBUG] region_id: {creds.get('region_id', 'NOT SET')}", flush=True)
            print(f"[WEBULL AUTH DEBUG] device_id: {'yes' if creds.get('device_id') else 'no'}", flush=True)
                
            access_token = creds.get('access_token')
            refresh_token = creds.get('refresh_token')
            
            if not access_token:
                return {"success": False, "error": "No access token configured. Please enter your Webull access token."}
            
            # Apply tokens EXACTLY like the main bot's _apply_tokens method
            # CRITICAL: Must set BOTH private and public attributes + Authorization headers
            print(f"[WEBULL AUTH DEBUG] Applying tokens to webull client...", flush=True)
            
            # Set both private and public token attributes (matches bot's _apply_tokens)
            for attr, val in (("_access_token", access_token),
                              ("access_token", access_token),
                              ("_refresh_token", refresh_token),
                              ("refresh_token", refresh_token)):
                try:
                    setattr(self.wb, attr, val)
                except Exception:
                    pass
            
            # CRITICAL: Update Authorization headers (this was missing!)
            if hasattr(self.wb, "_headers") and isinstance(self.wb._headers, dict):
                self.wb._headers['Authorization'] = f'Bearer {access_token}'
                print(f"[WEBULL AUTH DEBUG] ✓ Set _headers Authorization")
            if hasattr(self.wb, "_session") and hasattr(self.wb._session, 'headers'):
                self.wb._session.headers['Authorization'] = f'Bearer {access_token}'
                print(f"[WEBULL AUTH DEBUG] ✓ Set _session.headers Authorization")
            
            # Set device ID
            device_id = creds.get('device_id')
            if device_id:
                try:
                    if hasattr(self.wb, "_set_did"):
                        self.wb._set_did(device_id)
                    else:
                        self.wb._did = device_id
                        self.wb.did = device_id
                except Exception:
                    pass
            
            # Apply region metadata if available (required by Webull API v2 - Nov 2025+)
            # CRITICAL: zone_var is where webull library stores 'rzone' value!
            zone_var = creds.get('zone_var', '') or creds.get('rzone', '')
            saved_account_id = creds.get('account_id', '')
            region_code = creds.get('region_id', '')
            
            # Set zone_var BEFORE any API calls - this is the critical field!
            if zone_var:
                self.wb.zone_var = zone_var
                print(f"[WEBULL AUTH] ✓ Restored zone_var: {zone_var}")
            
            # Set account_id if we have it saved (avoids needing get_account_id first)
            if saved_account_id:
                self.wb._account_id = saved_account_id
                print(f"[WEBULL AUTH] ✓ Restored account_id: {saved_account_id}")
            
            # Set region code if available
            if region_code:
                try:
                    self.wb._region_code = int(region_code) if region_code.isdigit() else region_code
                except Exception:
                    pass
            
            # Check if zone_var is missing (tokens from before Nov 2025 API change)
            if not zone_var:
                print(f"[WEBULL AUTH DEBUG] ⚠ zone_var missing - will try get_account_id() first to obtain it", flush=True)
            
            print(f"[WEBULL AUTH DEBUG] Current wb state before API calls:", flush=True)
            print(f"[WEBULL AUTH DEBUG]   wb.zone_var = {getattr(self.wb, 'zone_var', 'NOT SET')}", flush=True)
            print(f"[WEBULL AUTH DEBUG]   wb._account_id = {getattr(self.wb, '_account_id', 'NOT SET')}", flush=True)
            print(f"[WEBULL AUTH DEBUG]   wb._region_code = {getattr(self.wb, '_region_code', 'NOT SET')}", flush=True)
            
            # ALWAYS call get_account_id() first - this sets zone_var from API response
            # This matches how the main bot works (selfbot_webull.py line 1930)
            try:
                print(f"[WEBULL AUTH DEBUG] Calling get_account_id() (ALWAYS required to set zone_var)...", flush=True)
                account_id = self.wb.get_account_id()
                print(f"[WEBULL AUTH DEBUG] get_account_id() returned: {account_id}", flush=True)
                print(f"[WEBULL AUTH DEBUG] After get_account_id, wb.zone_var = {getattr(self.wb, 'zone_var', 'NOT SET')}", flush=True)
                if account_id:
                    print(f"[WEBULL AUTH] ✓ Got account_id: {account_id}, zone_var: {self.wb.zone_var}", flush=True)
                else:
                    if refresh_token:
                        print(f"[WEBULL AUTH] Access token rejected — attempting refresh_login()...", flush=True)
                        try:
                            new_token = self.wb.refresh_login()
                            if new_token and isinstance(new_token, dict) and new_token.get('accessToken'):
                                new_access = new_token['accessToken']
                                new_refresh = new_token.get('refreshToken', refresh_token)
                                for attr, val in (("_access_token", new_access), ("access_token", new_access),
                                                  ("_refresh_token", new_refresh), ("refresh_token", new_refresh)):
                                    try:
                                        setattr(self.wb, attr, val)
                                    except Exception:
                                        pass
                                if hasattr(self.wb, "_headers") and isinstance(self.wb._headers, dict):
                                    self.wb._headers['Authorization'] = f'Bearer {new_access}'
                                if hasattr(self.wb, "_session") and hasattr(self.wb._session, 'headers'):
                                    self.wb._session.headers['Authorization'] = f'Bearer {new_access}'
                                print(f"[WEBULL AUTH] ✓ refresh_login() got new access token ({len(new_access)} chars)", flush=True)
                                account_id = self.wb.get_account_id()
                                print(f"[WEBULL AUTH] After refresh, get_account_id() returned: {account_id}", flush=True)
                                if account_id:
                                    print(f"[WEBULL AUTH] ✓ Token refreshed and verified!", flush=True)
                                else:
                                    return {"success": False, "error": "Token refresh succeeded but account verification failed. Please get a fresh access token from Webull.", "token_expired": True}
                            else:
                                print(f"[WEBULL AUTH] refresh_login() returned no new token: {type(new_token)}", flush=True)
                                return {"success": False, "error": "Access token expired and refresh failed. Please get a new access token from Webull (open https://app.webull.com, login, F12 → Console, copy new token).", "token_expired": True}
                        except Exception as ref_err:
                            print(f"[WEBULL AUTH] refresh_login() failed: {ref_err}", flush=True)
                            return {"success": False, "error": "Access token expired and refresh failed. Please get a new access token from Webull (open https://app.webull.com, login, F12 → Console, copy new token).", "token_expired": True}
                    else:
                        return {"success": False, "error": "Access token expired and no refresh token available. Please get a new access token from Webull (open https://app.webull.com, login, F12 → Console, copy new token).", "token_expired": True}
                
                print(f"[WEBULL AUTH DEBUG] Calling get_account()...", flush=True)
                account = self.wb.get_account()
                print(f"[WEBULL AUTH DEBUG] get_account() returned: {'data' if account else 'empty'}")
                if account:
                    print(f"[WEBULL AUTH] ✓ Token verification successful")
                    # Tokens work! Get trade token
                    if trading_pin:
                        try:
                            self.wb.get_trade_token(trading_pin)
                            print(f"[WEBULL AUTH] ✓ Trade token acquired")
                        except Exception as e:
                            print(f"[WEBULL AUTH] ⚠ Trade token warning: {e}")
                    self.logged_in = True
                    # Re-save session to persist zone_var if it was obtained fresh
                    self._save_session()
                    self.account_id = self.wb._account_id or self.wb.get_account_id()
                    return {"success": True, "account_id": self.account_id}
                else:
                    print(f"[WEBULL AUTH] ✗ get_account returned empty")
                    return {"success": False, "error": "Token verification failed - get_account returned empty. Token may be expired."}
            except KeyError as e:
                # Handle missing keys in Webull API response (schema drift like 'rzone')
                key_name = str(e).strip("'\"")
                print(f"[WEBULL AUTH DEBUG] ✗ KEYERROR EXCEPTION: {key_name}", flush=True)
                print(f"[WEBULL AUTH DEBUG] Full traceback:", flush=True)
                traceback.print_exc()
                sys.stdout.flush()
                sys.stderr.flush()
                # Mark tokens as stale and prompt for re-authentication
                return {
                    "success": False, 
                    "error": f"Saved tokens are stale (API schema changed). Please re-enter your Webull tokens to refresh.",
                    "token_stale": True,
                    "missing_key": key_name
                }
            except Exception as e:
                error_msg = str(e)
                print(f"[WEBULL AUTH] ✗ Token verification failed: {error_msg}")
                # Check for specific error types
                if 'Expecting value' in error_msg or 'JSONDecodeError' in error_msg:
                    return {"success": False, "error": "Webull API returned invalid response. Token may be expired or blocked."}
                # Handle KeyError-like messages in exception text
                if "KeyError" in error_msg or "'rzone'" in error_msg or "'regionId'" in error_msg:
                    return {
                        "success": False, 
                        "error": "Saved tokens are stale. Please re-enter your Webull tokens to refresh.",
                        "token_stale": True
                    }
                return {"success": False, "error": f"Token verification failed: {error_msg}"}
        except Exception as e:
            return {"success": False, "error": f"Session restore error: {str(e)}"}
    
    def login_with_saved_session(self, trading_pin: str) -> Dict[str, Any]:
        """Login using saved session tokens from database"""
        result = self._try_saved_session(trading_pin)
        if result.get("success"):
            return result
        # Return the specific error from _try_saved_session
        return {"success": False, "error": result.get("error", "Unknown error"), "token_expired": True}
    
    def _load_credentials(self) -> Optional[Dict[str, Any]]:
        """Load credentials from database via adapter"""
        if self._credentials_adapter:
            try:
                return self._credentials_adapter('get')
            except Exception:
                pass
        return None
    
    def _save_session(self):
        """Save session tokens to database via adapter (including region metadata for API v2)"""
        if not self._credentials_adapter:
            return
            
        try:
            # Extract zone_var from webull client (THIS is where rzone value is stored!)
            # The webull library sets zone_var in get_account_id() from result['data'][id]['rzone']
            zone_var = getattr(self.wb, 'zone_var', '')
            region_code = getattr(self.wb, '_region_code', '')
            account_id = getattr(self.wb, '_account_id', '')
            
            token_data = {
                'access_token': getattr(self.wb, '_access_token', None) or getattr(self.wb, 'access_token', None),
                'refresh_token': getattr(self.wb, '_refresh_token', None) or getattr(self.wb, 'refresh_token', None),
                'token_expire': getattr(self.wb, '_token_expire', None),
                'uuid': getattr(self.wb, '_uuid', None),
                'device_id': getattr(self.wb, '_did', None) or getattr(self.wb, 'did', None),
                'region_id': str(region_code) if region_code else '',
                'zone_id': '',
                'rzone': zone_var,
                'zone_var': zone_var,
                'account_id': account_id
            }
            self._credentials_adapter('save', token_data)
            print(f"[WEBULL AUTH] ✓ Session saved (zone_var: {zone_var or 'none'}, region_code: {region_code or 'none'})")
        except Exception as e:
            print(f"[WEBULL AUTH] Warning: Could not save session: {e}")
    
    def request_mfa(self, email: str) -> Dict[str, Any]:
        """Request MFA code to be sent to email/phone"""
        try:
            result = self.wb.get_mfa(email)
            return {"success": True, "message": "MFA code sent to your email/phone", "result": result}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_security_question(self, email: str) -> Dict[str, Any]:
        """Get security question for MFA"""
        try:
            result = self.wb.get_security(email)
            if result and len(result) > 0:
                return {
                    "success": True, 
                    "question_id": result[0].get('questionId'),
                    "question": result[0].get('questionName'),
                    "result": result
                }
            return {"success": False, "error": "No security question returned"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_mfa_code(self, email: str) -> Dict[str, Any]:
        """Alias for request_mfa"""
        return self.request_mfa(email)
    
    def get_account_info(self) -> Dict[str, Any]:
        """Get account information"""
        if not self.logged_in:
            return {"success": False, "error": "Not logged in"}
        try:
            account = self.wb.get_account()
            return {"success": True, "account": account}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_positions(self) -> Dict[str, Any]:
        """Get current positions"""
        if not self.logged_in:
            return {"success": False, "error": "Not logged in"}
        try:
            positions = self.wb.get_positions()
            return {"success": True, "positions": positions}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_orders(self) -> Dict[str, Any]:
        """Get current orders"""
        if not self.logged_in:
            return {"success": False, "error": "Not logged in"}
        try:
            orders = self.wb.get_current_orders()
            return {"success": True, "orders": orders}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def is_authenticated(self) -> bool:
        """Check if currently authenticated"""
        return self.logged_in and self.wb.is_logged_in()
    
    def get_broker_instance(self):
        """Get the underlying webull broker instance for direct API calls"""
        return self.wb
