"""
Webull Authentication Module
Handles Webull login with MFA support, session persistence via database storage.
Uses adapter pattern for database access - credentials stored encrypted in SQLite.
"""
from typing import Optional, Dict, Any, Callable
from webull import webull, paper_webull


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
        try:
            creds = self._load_credentials()
            if not creds:
                return {"success": False, "error": "No Webull credentials found in database"}
                
            access_token = creds.get('access_token')
            refresh_token = creds.get('refresh_token')
            
            if not access_token:
                return {"success": False, "error": "No access token configured. Please enter your Webull access token."}
            
            # Use PUBLIC attributes (same as main bot WebullBroker.connect)
            self.wb.access_token = access_token
            if refresh_token:
                self.wb.refresh_token = refresh_token
            if creds.get('device_id'):
                self.wb.did = creds.get('device_id')
            
            # Apply region metadata if available (required by Webull API v2 - Nov 2025+)
            region_id = creds.get('region_id', '')
            zone_id = creds.get('zone_id', '')
            rzone = creds.get('rzone', '')
            
            if region_id:
                try:
                    self.wb._region_id = region_id
                except Exception:
                    pass
            if zone_id:
                try:
                    self.wb._zone_id = zone_id
                except Exception:
                    pass
            if rzone:
                try:
                    # The webull library accesses session['rzone'] - we need to set it properly
                    if hasattr(self.wb, '_session') and isinstance(self.wb._session, dict):
                        self.wb._session['rzone'] = rzone
                    elif hasattr(self.wb, 'session') and isinstance(self.wb.session, dict):
                        self.wb.session['rzone'] = rzone
                except Exception:
                    pass
            
            # Check if region metadata is missing (tokens from before Nov 2025 API change)
            if not rzone and not region_id:
                print(f"[WEBULL AUTH] ⚠ Region metadata missing - tokens may be from old API version")
            
            # Verify tokens by calling get_account (same as main bot)
            try:
                print(f"[WEBULL AUTH] Verifying tokens via get_account...")
                account = self.wb.get_account()
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
                    self.account_id = self.wb.get_account_id()
                    return {"success": True, "account_id": self.account_id}
                else:
                    print(f"[WEBULL AUTH] ✗ get_account returned empty")
                    return {"success": False, "error": "Token verification failed - get_account returned empty. Token may be expired."}
            except KeyError as e:
                # Handle missing keys in Webull API response (schema drift like 'rzone')
                key_name = str(e).strip("'\"")
                print(f"[WEBULL AUTH] ✗ API schema error - missing key: {key_name}")
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
            # Extract region metadata from webull client (required for API v2)
            rzone = ''
            if hasattr(self.wb, '_session') and isinstance(self.wb._session, dict):
                rzone = self.wb._session.get('rzone', '')
            elif hasattr(self.wb, 'session') and isinstance(self.wb.session, dict):
                rzone = self.wb.session.get('rzone', '')
            
            token_data = {
                'access_token': getattr(self.wb, '_access_token', None) or getattr(self.wb, 'access_token', None),
                'refresh_token': getattr(self.wb, '_refresh_token', None) or getattr(self.wb, 'refresh_token', None),
                'token_expire': getattr(self.wb, '_token_expire', None),
                'uuid': getattr(self.wb, '_uuid', None),
                'device_id': getattr(self.wb, '_did', None) or getattr(self.wb, 'did', None),
                'region_id': getattr(self.wb, '_region_id', '') or getattr(self.wb, 'region_id', ''),
                'zone_id': getattr(self.wb, '_zone_id', '') or getattr(self.wb, 'zone_id', ''),
                'rzone': rzone
            }
            self._credentials_adapter('save', token_data)
            print(f"[WEBULL AUTH] ✓ Session saved (rzone: {'yes' if rzone else 'no'})")
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
