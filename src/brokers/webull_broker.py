"""
Webull Broker Implementation
"""

import sys
import os
import asyncio
from typing import Optional, Dict, Any
from webull import webull, paper_webull
from datetime import datetime

# Add parent directory to path for absolute imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from broker_interface import BrokerInterface, OrderResult, BrokerFactory


class WebullBroker(BrokerInterface):
    """Webull broker implementation using webull package"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.name = "WEBULL"
        self.wb = None
        self.paper_trade = config.get('paper_trade', False)
        self._tokens_valid = False
        self._token_refresh_task = None
        self._option_id_cache = {}
        self._option_id_cache_ttl = 300
        self._reverse_option_id_cache = {}
        self._streaming_client = None
        self._data_hub = None
    
    async def connect(self) -> bool:
        """Connect to Webull"""
        try:
            try:
                self._event_loop = asyncio.get_running_loop()
            except RuntimeError:
                self._event_loop = None

            if self.paper_trade:
                self.wb = paper_webull()
                print(f"[{self.name}] Using paper trading mode")
            else:
                self.wb = webull()
                print(f"[{self.name}] Using LIVE trading mode")
            
            # Try token-based authentication first
            access_token = self.config.get('access_token')
            refresh_token = self.config.get('refresh_token')
            did = self.config.get('did')
            
            if access_token and refresh_token:
                print(f"[{self.name}] Using saved tokens for authentication")
                self.wb._access_token = access_token
                self.wb.access_token = access_token
                self.wb._refresh_token = refresh_token
                self.wb.refresh_token = refresh_token
                if did:
                    self.wb._did = did
                    self.wb.did = did
                try:
                    if hasattr(self.wb, '_headers'):
                        self.wb._headers['Authorization'] = f'Bearer {access_token}'
                    if hasattr(self.wb, '_session') and hasattr(self.wb._session, 'headers'):
                        self.wb._session.headers['Authorization'] = f'Bearer {access_token}'
                except Exception:
                    pass
                
                desired_account_type = self.config.get('account_type', 'margin').lower()
                acct_id = await asyncio.to_thread(self._resolve_account_by_type, desired_account_type)
                if acct_id:
                    print(f"[{self.name}] ✓ Account ID resolved: {acct_id} ({desired_account_type.upper()} account, {'paper' if self.paper_trade else 'live'})")
                else:
                    print(f"[{self.name}] ⚠️ Could not resolve account ID — positions may be unreliable")
                
                account = await asyncio.to_thread(self.wb.get_account)
                if account:
                    self.connected = True
                    self._tokens_valid = True
                    print(f"[{self.name}] ✓ Connected successfully (token auth)")
                    self._start_proactive_token_refresh()
                    self._start_streaming()
                    return True
            
            username = self.config.get('username')
            password = self.config.get('password')
            
            if username and password:
                print(f"[{self.name}] Attempting username/password login")
                def login():
                    return self.wb.login(username, password)
                
                result = await asyncio.to_thread(login)
                if result:
                    desired_account_type = self.config.get('account_type', 'margin').lower()
                    await asyncio.to_thread(self._resolve_account_by_type, desired_account_type)
                    self.connected = True
                    self._tokens_valid = True
                    print(f"[{self.name}] ✓ Connected successfully (password auth, {desired_account_type.upper()} account)")
                    self._start_proactive_token_refresh()
                    self._start_streaming()
                    return True
            
            print(f"[{self.name}] ❌ Failed to connect - no valid credentials")
            return False
            
        except Exception as e:
            print(f"[{self.name}] ❌ Connection error: {e}")
            return False
    
    def _resolve_account_by_type(self, desired_type='margin'):
        """Resolve account ID by type (margin/cash/ira). Falls back to saved ID or index 0."""
        import requests as _req
        import time

        saved_sec_id = ''
        saved_rzone = ''
        try:
            from gui_app.broker_credentials_service import get_webull_credentials
            saved_creds = get_webull_credentials()
            saved_sec_id = saved_creds.get('sec_account_id', '')
            saved_rzone = saved_creds.get('rzone', '')
        except Exception:
            pass

        try:
            headers = self.wb.build_req_headers()
            url = self.wb._urls.account_id()

            api_result = None
            for attempt in range(3):
                try:
                    response = _req.get(url, headers=headers, timeout=self.wb.timeout)
                    result = response.json()
                    if result.get('success') and result.get('data'):
                        api_result = result
                        break
                    else:
                        print(f"[{self.name}] ⚠️ Account list API returned non-success (attempt {attempt+1}/3)")
                except Exception as api_err:
                    print(f"[{self.name}] ⚠️ Account list API error (attempt {attempt+1}/3): {api_err}")
                if attempt < 2:
                    time.sleep(1)

            if not api_result:
                if saved_sec_id:
                    print(f"[{self.name}] ✓ Using saved account ID from database: {saved_sec_id}")
                    self.wb._account_id = saved_sec_id
                    if saved_rzone:
                        self.wb.zone_var = saved_rzone
                    return self.wb._account_id
                print(f"[{self.name}] ⚠️ Could not fetch account list and no saved ID — falling back to default")
                return self.wb.get_account_id()

            accounts = api_result['data']
            valid_accounts = [a for a in accounts if a.get('secAccountId')]

            print(f"[{self.name}] Found {len(accounts)} account(s) ({len(valid_accounts)} with secAccountId), resolving types...")

            for i, acct in enumerate(valid_accounts):
                sec_id = str(acct.get('secAccountId', ''))
                rzone = str(acct.get('rzone', ''))
                detected_type = self._detect_account_type(sec_id, headers)
                print(f"[{self.name}]   [{i}] secAccountId={sec_id} detected_type={detected_type}")

                if detected_type.upper() == desired_type.upper():
                    self.wb.zone_var = rzone
                    self.wb._account_id = sec_id
                    print(f"[{self.name}] ✓ Selected {desired_type.upper()} account at index [{i}] (secAccountId={sec_id})")
                    self._persist_resolved_account_id(sec_id, rzone)
                    return self.wb._account_id

            if not valid_accounts:
                if saved_sec_id:
                    print(f"[{self.name}] ⚠️ No valid accounts in API — using saved ID: {saved_sec_id}")
                    self.wb._account_id = saved_sec_id
                    if saved_rzone:
                        self.wb.zone_var = saved_rzone
                    return self.wb._account_id
                print(f"[{self.name}] ⚠️ No valid accounts found — falling back to default")
                return self.wb.get_account_id()

            print(f"[{self.name}] ⚠️ No {desired_type.upper()} account found in {len(valid_accounts)} account(s) — using first account")
            self.wb.zone_var = str(valid_accounts[0].get('rzone', ''))
            self.wb._account_id = str(valid_accounts[0].get('secAccountId', ''))
            self._persist_resolved_account_id(self.wb._account_id, self.wb.zone_var)
            return self.wb._account_id
        except Exception as e:
            if saved_sec_id:
                print(f"[{self.name}] ⚠️ Account resolution failed ({e}) — using saved ID: {saved_sec_id}")
                self.wb._account_id = saved_sec_id
                if saved_rzone:
                    self.wb.zone_var = saved_rzone
                return self.wb._account_id
            print(f"[{self.name}] ⚠️ Account type resolution failed ({e}) — falling back to default")
            try:
                return self.wb.get_account_id()
            except Exception:
                return None

    def _persist_resolved_account_id(self, sec_account_id, rzone=''):
        """Save the resolved account ID to the database for future fallback."""
        try:
            from gui_app.broker_credentials_service import get_webull_credentials
            from gui_app.config_service import save_config
            existing = get_webull_credentials()
            existing['sec_account_id'] = sec_account_id
            if rzone:
                existing['rzone'] = rzone
            save_config('webull_credentials', existing)
            print(f"[{self.name}] ✓ Saved account ID {sec_account_id} to database for fallback")
        except Exception as e:
            print(f"[{self.name}] ⚠️ Could not persist account ID: {e}")

    def _detect_account_type(self, sec_account_id, headers):
        """Query account details to detect type (Margin/Cash/IRA)."""
        import requests as _req
        try:
            url = self.wb._urls.account(sec_account_id)
            resp = _req.get(url, headers=headers, timeout=self.wb.timeout)
            if resp.status_code != 200:
                print(f"[{self.name}] ⚠️ Account detail API returned {resp.status_code} for {sec_account_id}")
                return 'Unknown'
            data = resp.json()
            account = data.get('data', data) if isinstance(data, dict) else data
            if not isinstance(account, dict):
                return 'Unknown'
            account_data = {}
            for item in account.get('accountMembers', []):
                if isinstance(item, dict) and 'key' in item and 'value' in item:
                    account_data[item['key']] = item['value']
            for k, v in account.items():
                if k != 'accountMembers' and k not in account_data:
                    account_data[k] = v
            for field in ['brokerAccountTypeStr', 'accountType', 'brokerAccountType']:
                if field in account_data:
                    raw = str(account_data[field]).upper()
                    if 'MARGIN' in raw:
                        return 'Margin'
                    elif 'CASH' in raw:
                        return 'Cash'
                    elif 'IRA' in raw or 'ROTH' in raw or 'TRADITIONAL' in raw:
                        return 'IRA'
                    return account_data[field]
            return 'Unknown'
        except Exception as e:
            print(f"[{self.name}] ⚠️ Could not detect type for account {sec_account_id}: {e}")
            return 'Unknown'

    def _start_streaming(self):
        try:
            from src.services.webull_streaming_client import WebullStreamingClient
            from src.services.webull_data_hub import get_webull_data_hub
            self._data_hub = get_webull_data_hub()
            self._streaming_client = WebullStreamingClient(self)
            self._streaming_client.set_wb_instance(self.wb)
            self._streaming_client.start()
            print(f"[{self.name}] ✓ Streaming client started")
            try:
                from src.services.price_monitor_service import get_price_monitor
                pm = get_price_monitor()
                if pm and hasattr(pm, 'set_streaming_client'):
                    pm.set_streaming_client(self._streaming_client)
                    print(f"[{self.name}] ✓ Streaming client wired to PriceMonitor")
            except Exception:
                pass
        except Exception as e:
            print(f"[{self.name}] ⚠️ Could not start streaming: {e}")
            self._streaming_client = None

    async def disconnect(self):
        """Disconnect from Webull"""
        if self._streaming_client:
            try:
                self._streaming_client.stop()
            except Exception:
                pass
            self._streaming_client = None
        if self._token_refresh_task and not self._token_refresh_task.done():
            self._token_refresh_task.cancel()
            try:
                await self._token_refresh_task
            except asyncio.CancelledError:
                pass
        self._token_refresh_task = None
        self.connected = False
        self._tokens_valid = False
        self._option_id_cache.clear()
        self._reverse_option_id_cache.clear()
        print(f"[{self.name}] Disconnected")
    
    def is_authenticated(self) -> bool:
        """Check if Webull is actually authenticated (tokens valid)
        
        This is different from 'connected' which may stay True after token expiration.
        Uses cached validation to avoid repeated API calls.
        """
        return getattr(self, '_tokens_valid', True) and self.connected
    
    def _get_extended_hours_enabled(self) -> bool:
        try:
            from gui_app.database import get_broker_extended_hours
            enabled = get_broker_extended_hours('webull')
            if enabled:
                print(f"[{self.name}] Extended hours ENABLED")
            return enabled
        except ImportError:
            return False
        except Exception as e:
            print(f"[{self.name}] Error checking extended hours setting: {e}")
            return False

    def _resolve_option_enforce(self, expiry: str) -> str:
        from datetime import datetime, date
        try:
            today = date.today()
            exp_date = None
            if expiry and '/' in expiry:
                parts = expiry.split('/')
                if len(parts) == 2:
                    m, d = int(parts[0]), int(parts[1])
                    exp_date = date(today.year, m, d)
                    if exp_date < today:
                        exp_date = date(today.year + 1, m, d)
                elif len(parts) == 3:
                    m, d, y = int(parts[0]), int(parts[1]), int(parts[2])
                    if y < 100:
                        y += 2000
                    exp_date = date(y, m, d)
            elif expiry and '-' in expiry:
                exp_date = date.fromisoformat(expiry[:10])

            if exp_date and exp_date <= today:
                print(f"[{self.name}] 0DTE/same-day option detected (exp={exp_date}) — using enforce=DAY (Webull cancels GTC on 0DTE)")
                return 'DAY'
        except Exception as e:
            print(f"[{self.name}] ⚠️ Could not parse expiry '{expiry}' for enforce check: {e}")

        return 'DAY'
    
    async def _refresh_trade_token(self) -> bool:
        """Refresh the Webull trade token when it expires.
        
        Returns:
            True if refresh successful, False otherwise
        """
        try:
            def _blocking_refresh():
                if not self.wb:
                    return False
                    
                # Try refresh_login method
                if hasattr(self.wb, 'refresh_login'):
                    try:
                        result = self.wb.refresh_login()
                        if result and isinstance(result, dict):
                            new_access = result.get('accessToken')
                            new_refresh = result.get('refreshToken')
                            if new_access:
                                self.wb.access_token = new_access
                                if new_refresh:
                                    self.wb.refresh_token = new_refresh
                                print(f"[{self.name}] ✓ Trade token refreshed via refresh_login")
                                return True
                    except Exception as e:
                        print(f"[{self.name}] refresh_login failed: {e}")
                
                # Fallback: try get_trade_token if available
                if hasattr(self.wb, 'get_trade_token'):
                    try:
                        # Get stored password or trading PIN
                        trading_pin = self.config.get('trading_pin') or self.config.get('trade_pin')
                        if trading_pin:
                            result = self.wb.get_trade_token(trading_pin)
                            if result:
                                print(f"[{self.name}] ✓ Trade token refreshed via trading PIN")
                                return True
                    except Exception as e:
                        print(f"[{self.name}] get_trade_token failed: {e}")
                
                return False
            
            return await asyncio.to_thread(_blocking_refresh)
            
        except Exception as e:
            print(f"[{self.name}] Token refresh error: {e}")
            return False
    
    def _start_proactive_token_refresh(self):
        """Start background task to refresh tokens every 10 minutes during market hours"""
        if self._token_refresh_task and not self._token_refresh_task.done():
            return
        
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                self._token_refresh_task = loop.create_task(self._proactive_refresh_loop())
            else:
                self._token_refresh_task = asyncio.ensure_future(self._proactive_refresh_loop())
            print(f"[{self.name}] ✓ Proactive token refresh started (every 10 min during market hours)")
        except Exception as e:
            print(f"[{self.name}] Could not start proactive refresh: {e}")
    
    async def _proactive_refresh_loop(self):
        """Background loop that refreshes tokens proactively to prevent mid-trade expiry"""
        REFRESH_INTERVAL = 600
        while self.connected and self._tokens_valid:
            try:
                await asyncio.sleep(REFRESH_INTERVAL)
                
                if not self.connected or not self._tokens_valid:
                    break
                
                if self._is_market_hours_or_premarket():
                    print(f"[{self.name}] [PROACTIVE] Refreshing trade token...")
                    success = await self._refresh_trade_token()
                    if success:
                        print(f"[{self.name}] [PROACTIVE] ✓ Token refreshed successfully")
                    else:
                        print(f"[{self.name}] [PROACTIVE] ⚠️ Token refresh failed - will retry next cycle")
                        
            except asyncio.CancelledError:
                print(f"[{self.name}] [PROACTIVE] Token refresh task cancelled")
                break
            except Exception as e:
                print(f"[{self.name}] [PROACTIVE] Error in refresh loop: {e}")
                await asyncio.sleep(60)
    
    def _is_market_hours_or_premarket(self) -> bool:
        """Check if current time is within extended trading window (4 AM - 8 PM ET)"""
        try:
            from datetime import timezone, timedelta
            et = timezone(timedelta(hours=-5))
            now = datetime.now(et)
            if now.weekday() >= 5:
                return False
            hour = now.hour
            return 4 <= hour < 20
        except Exception:
            return True
    
    def cache_option_id(self, symbol: str, strike: float, expiry: str, option_type: str, option_id: str):
        """Cache an option_id for faster exit order lookups"""
        import time
        cache_key = f"{symbol}_{float(strike):.2f}_{expiry}_{option_type.upper()}"
        self._option_id_cache[cache_key] = {
            'option_id': option_id,
            'cached_at': time.time()
        }
        self._reverse_option_id_cache[str(option_id)] = {
            'symbol': symbol,
            'strike': float(strike),
            'expiry': expiry,
            'option_type': option_type.upper(),
            'cached_at': time.time()
        }
    
    def get_cached_option_id(self, symbol: str, strike: float, expiry: str, option_type: str) -> Optional[str]:
        """Retrieve a cached option_id if still valid"""
        import time
        cache_key = f"{symbol}_{float(strike):.2f}_{expiry}_{option_type.upper()}"
        entry = self._option_id_cache.get(cache_key)
        if entry and (time.time() - entry['cached_at']) < self._option_id_cache_ttl:
            return entry['option_id']
        if entry:
            del self._option_id_cache[cache_key]
        return None

    def get_option_details_by_id(self, option_id) -> Optional[dict]:
        """Reverse lookup: given an optionId, return cached {symbol, strike, expiry, option_type}"""
        import time
        entry = self._reverse_option_id_cache.get(str(option_id))
        if entry and (time.time() - entry['cached_at']) < self._option_id_cache_ttl:
            return entry
        return None
    
    async def _retry_on_busy(self, func, label: str, max_retries: int = 2, delay: float = 2.0):
        """Retry a Webull API call if it returns a 'system busy' error."""
        for attempt in range(1, max_retries + 1):
            result = await asyncio.to_thread(func)
            if isinstance(result, dict):
                msg = str(result.get('msg', '')).lower()
                code = str(result.get('code', ''))
                if ('busy' in msg or 'system' in msg) and attempt < max_retries:
                    print(f"[{self.name}] ⚠️ {label} system busy (attempt {attempt}/{max_retries}) — retrying in {delay}s...")
                    await asyncio.sleep(delay)
                    continue
            return result
        return result

    async def get_account_info(self) -> Dict[str, Any]:
        """Get account information. Uses hub cache when fresh."""
        try:
            if self._data_hub:
                cached = self._data_hub.get_account_info(max_age_seconds=90)
                if cached is not None:
                    _bp = cached.get('buying_power', 0) or 0
                    _sc = cached.get('settled_cash', 0) or 0
                    if _sc == 0 and _bp > 0:
                        cached['settled_cash'] = _bp
                    return cached

            account_response = await self._retry_on_busy(self.wb.get_account, 'get_account')
            
            # DEBUG: Print raw response structure first
            print(f"[{self.name}] Raw account response type: {type(account_response)}")
            if isinstance(account_response, dict):
                print(f"[{self.name}] Raw response keys: {list(account_response.keys())[:10]}")
            
            # Unwrap API response if it has 'data' key
            if isinstance(account_response, dict) and 'data' in account_response:
                account = account_response['data']
            else:
                account = account_response
            
            # Parse accountMembers list into a dict (Webull returns {'key': 'name', 'value': 'val'} items)
            account_data = {}
            account_members = account.get('accountMembers', []) if isinstance(account, dict) else []
            print(f"[{self.name}] accountMembers count: {len(account_members)}")
            if account_members and isinstance(account_members, list):
                for item in account_members:
                    if isinstance(item, dict) and 'key' in item and 'value' in item:
                        account_data[item['key']] = item['value']
            
            # Merge direct fields with parsed accountMembers (accountMembers takes priority)
            if isinstance(account, dict):
                for k, v in account.items():
                    if k != 'accountMembers' and k not in account_data:
                        account_data[k] = v
            
            # DEBUG: Print all fields (including zeros)
            print(f"[{self.name}] Parsed account_data ({len(account_data)} fields): {list(account_data.keys())[:15]}")
            
            # Try multiple field name variations for buying power
            buying_power = 0.0
            for field in ['cashBalance', 'buyingPower', 'dayBuyingPower', 'settledFunds', 'cashAvailableForTrade', 'overnightBuyingPower']:
                if field in account_data:
                    try:
                        buying_power = float(account_data[field])
                        if buying_power > 0:
                            print(f"[{self.name}] [DEBUG] Using '{field}' for buying_power: ${buying_power:.2f}")
                            break
                    except (ValueError, TypeError):
                        pass
            
            # Get options-specific buying power (critical for options trading)
            options_buying_power = 0.0
            if 'optionBuyingPower' in account_data:
                try:
                    options_buying_power = float(account_data['optionBuyingPower'])
                    print(f"[{self.name}] [DEBUG] Found optionBuyingPower: ${options_buying_power:.2f}")
                except (ValueError, TypeError):
                    pass
            # Fallback to regular buying power if no options BP
            if options_buying_power == 0:
                options_buying_power = buying_power
            
            # Try multiple field name variations for cash
            cash = 0.0
            for field in ['settledCash', 'cashBalance', 'settledFunds']:
                if field in account_data:
                    try:
                        cash = float(account_data[field])
                        if cash > 0:
                            break
                    except (ValueError, TypeError):
                        pass
            
            settled_cash = 0.0
            unsettled_cash = 0.0
            _settled_found = False
            for field in ['settledCash', 'settledFunds']:
                if field in account_data:
                    try:
                        settled_cash = float(account_data[field])
                        _settled_found = True
                        print(f"[{self.name}] [DEBUG] Settled cash from '{field}': ${settled_cash:.2f}")
                        break
                    except (ValueError, TypeError):
                        pass
            
            for field in ['unsettledCash', 'unsettledFunds']:
                if field in account_data:
                    try:
                        unsettled_cash = float(account_data[field])
                        print(f"[{self.name}] [DEBUG] Unsettled cash from '{field}': ${unsettled_cash:.2f}")
                        break
                    except (ValueError, TypeError):
                        pass

            if not _settled_found and buying_power > 0:
                settled_cash = buying_power
                print(f"[{self.name}] [DEBUG] Webull API did not return settledCash/settledFunds — using buying_power ${buying_power:.2f} as settled cash")
            
            # Try multiple field name variations for portfolio value (market value)
            portfolio_value = 0.0
            for field in ['netLiquidation', 'totalMarketValue', 'accountValue', 'totalAccountValue']:
                if field in account_data:
                    try:
                        portfolio_value = float(account_data[field])
                        if portfolio_value > 0:
                            break
                    except (ValueError, TypeError):
                        pass
            
            # Extract account type (Margin/Cash/IRA)
            account_type = 'Unknown'
            for field in ['brokerAccountTypeStr', 'accountType', 'brokerAccountType']:
                if field in account_data:
                    raw_type = str(account_data[field]).upper()
                    if 'MARGIN' in raw_type:
                        account_type = 'Margin'
                    elif 'CASH' in raw_type:
                        account_type = 'Cash'
                    elif 'IRA' in raw_type or 'ROTH' in raw_type or 'TRADITIONAL' in raw_type:
                        account_type = 'IRA'
                    else:
                        account_type = account_data[field]
                    print(f"[{self.name}] [DEBUG] Account type from '{field}': {account_type}")
                    break
            
            # Get account ID for display
            account_id = account_data.get('secAccountId', account_data.get('accountId', 'N/A'))
            
            result = {
                'buying_power': buying_power,
                'options_buying_power': options_buying_power,
                'cash': cash,
                'settled_cash': settled_cash,
                'unsettled_cash': unsettled_cash,
                'portfolio_value': portfolio_value,
                'account_type': account_type,
                'account_id': str(account_id)
            }
            print(f"[{self.name}] [DEBUG] Final account info: Type={account_type}, BP=${buying_power:.2f}, OptBP=${options_buying_power:.2f}, SettledCash=${settled_cash:.2f}, UnsettledCash=${unsettled_cash:.2f}, PortValue=${portfolio_value:.2f}")
            if self._data_hub:
                self._data_hub.update_account_info(result)
            return result
        except Exception as e:
            print(f"[{self.name}] Error getting account info: {e}")
            import traceback
            traceback.print_exc()
            if self._data_hub:
                cached = self._data_hub.get_account_info(max_age_seconds=300)
                if cached is not None:
                    print(f"[{self.name}] Returning hub-cached account info after error")
                    return cached
            return None
    
    async def get_positions(self) -> Dict[str, Any]:
        """Get current positions"""
        try:
            positions = await asyncio.to_thread(self.wb.get_positions)
            result = {}
            for pos in positions:
                symbol = pos.get('ticker', {}).get('symbol', '')
                quantity = int(pos.get('position', 0))
                if symbol:
                    result[symbol] = quantity
            return result
        except Exception as e:
            print(f"[{self.name}] Error getting positions: {e}")
            return {}
    
    async def get_positions_detailed(self) -> list:
        """Get detailed positions with full information.
        
        IMPORTANT: Always fetch directly from REST API (not hub cache) to prevent
        live/paper position cross-contamination. The WebullDataHub is a singleton
        shared by both live and paper brokers — using its cache means the live
        broker can receive paper positions (and vice versa).
        """
        try:
            positions_raw = None
            _from_rest = False
            acct_id = getattr(self.wb, '_account_id', 'UNKNOWN')
            print(f"[{self.name}] get_positions_detailed: account_id={acct_id}, paper={self.paper_trade}", flush=True)
            positions_raw = await self._retry_on_busy(self.wb.get_positions, 'get_positions')
            _from_rest = True
            if positions_raw:
                syms = [p.get('ticker', {}).get('symbol', '?') for p in positions_raw[:5]]
                print(f"[{self.name}] REST positions ({len(positions_raw)}): {syms}", flush=True)
            else:
                print(f"[{self.name}] REST positions: EMPTY/None", flush=True)
            positions = []
            
            for pos in positions_raw:
                # Skip closed positions
                position_qty = float(pos.get('position', 0))
                if position_qty <= 0:
                    continue
                
                symbol = pos.get('ticker', {}).get('symbol', '') or pos.get('symbol', '')
                asset_type = pos.get('assetType', 'unknown')
                
                # Check if this is an option
                is_option = (
                    'optionId' in pos or 
                    'strikePrice' in pos or 
                    asset_type.lower() in ('option', 'opt')
                )
                
                if is_option:
                    strike = float(pos.get('strikePrice', 0) or pos.get('optionExercisePrice', 0) or pos.get('strike', 0) or 0)
                    direction = (pos.get('direction', '') or pos.get('optionType', '') or pos.get('callPut', '') or pos.get('right', '') or '').upper()
                    expiry = pos.get('expireDate', '') or pos.get('optionExpireDate', '') or pos.get('expirationDate', '') or ''
                    
                    opt_id_val = pos.get('optionId', 0)
                    ticker_id = pos.get('ticker', {}).get('tickerId', 0)

                    if (not strike or strike == 0.0) and opt_id_val:
                        reverse = self.get_option_details_by_id(opt_id_val)
                        if not reverse and ticker_id:
                            reverse = self.get_option_details_by_id(ticker_id)
                        if reverse:
                            strike = reverse['strike']
                            expiry = reverse['expiry']
                            direction = reverse['option_type']
                            print(f"[{self.name}] ✓ Reverse cache enriched position: {symbol} {strike} {direction} {expiry}")

                    expiry_mmdd = ''
                    if expiry and '-' in expiry:
                        from datetime import datetime
                        try:
                            exp_date = datetime.strptime(expiry, '%Y-%m-%d')
                            expiry_mmdd = exp_date.strftime('%m/%d')
                        except:
                            expiry_mmdd = expiry
                    
                    d_upper = direction.upper() if direction else ''
                    if d_upper in ('CALL', 'C'):
                        opt_direction = 'C'
                    elif d_upper in ('PUT', 'P'):
                        opt_direction = 'P'
                    else:
                        opt_direction = d_upper[:1] if d_upper else ''
                    
                    if opt_id_val and expiry and opt_direction:
                        self.cache_option_id(symbol, strike, expiry, opt_direction, str(opt_id_val))
                    
                    from src.risk.risk_types import normalize_index_symbol as _norm_idx
                    positions.append({
                        'asset': 'option',
                        'symbol': _norm_idx(symbol),
                        'quantity': position_qty,
                        'avg_cost': float(pos.get('costPrice', 0)),
                        'current_price': float(pos.get('latestPrice', 0) or pos.get('lastPrice', 0)),
                        'unrealized_pl': float(pos.get('unrealizedProfitLoss', 0)),
                        'option_id': opt_id_val,
                        'strike': strike,
                        'expiry': expiry_mmdd,
                        'expiry_full': expiry,
                        'direction': opt_direction,
                        'ticker_id': pos.get('ticker', {}).get('tickerId', 0)
                    })
                else:
                    # Stock position
                    quantity = position_qty
                    market_value = float(pos.get('marketValue', 0))
                    current_price = market_value / quantity if quantity > 0 else 0
                    
                    positions.append({
                        'asset': 'stock',
                        'symbol': symbol,
                        'quantity': quantity,
                        'avg_cost': float(pos.get('costPrice', 0)),
                        'current_price': current_price,
                        'unrealized_pl': float(pos.get('unrealizedProfitLoss', 0)),
                        'ticker_id': pos.get('ticker', {}).get('tickerId', 0)
                    })
            
            if self._data_hub and _from_rest:
                self._data_hub.update_positions(positions_raw, source="rest")
            if self._streaming_client:
                self._streaming_client.subscribe_positions(positions)

            return positions
        except Exception as e:
            print(f"[{self.name}] Error getting detailed positions: {e}")
            import traceback
            traceback.print_exc()
            return []

    async def subscribe_position_symbols(self, positions: list):
        if self._streaming_client and positions:
            self._streaming_client.subscribe_positions(positions)

    async def get_pending_orders(self) -> list:
        """Get all pending/open orders from Webull. Uses hub cache when fresh."""
        try:
            if self._data_hub:
                cached = self._data_hub.get_pending_orders(max_age_seconds=45)
                if cached is not None:
                    return cached

            orders_raw = await self._retry_on_busy(self.wb.get_current_orders, 'get_pending_orders')
            orders = []
            
            if not orders_raw:
                if self._data_hub:
                    self._data_hub.update_pending_orders([])
                return []
            
            for order in orders_raw:
                # Extract order details
                ticker = order.get('ticker', {})
                symbol = ticker.get('symbol', '') if ticker else ''
                
                orders.append({
                    'order_id': str(order.get('orderId', '')),
                    'symbol': symbol,
                    'quantity': int(order.get('totalQuantity', 0)),
                    'limit_price': float(order.get('lmtPrice', 0)) if order.get('lmtPrice') else None,
                    'action': order.get('action', ''),  # BUY/SELL
                    'status': order.get('status', ''),
                    'order_type': order.get('orderType', ''),
                    'filled_quantity': int(order.get('filledQuantity', 0))
                })
            
            if self._data_hub:
                self._data_hub.update_pending_orders(orders)
            return orders
        except Exception as e:
            print(f"[{self.name}] Error getting pending orders: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    async def get_order_status(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Get order status by checking pending orders first, then filled history.
        
        Args:
            order_id: The Webull order ID to look up
            
        Returns:
            Dict with 'status' (FILLED/PENDING/CANCELLED/etc) and 'filled_qty',
            or None if order not found in any source
        """
        try:
            pending = await self.get_pending_orders()
            for order in (pending or []):
                if str(order.get('order_id', '')) == str(order_id):
                    raw_status = str(order.get('status', '')).upper()
                    if raw_status == 'FILLED':
                        return {'status': 'FILLED', 'filled_qty': int(order.get('filled_quantity', 0) or order.get('quantity', 0))}
                    elif raw_status in ('CANCELLED', 'CANCELED'):
                        return {'status': 'CANCELLED', 'filled_qty': 0}
                    elif raw_status == 'REJECTED':
                        return {'status': 'REJECTED', 'filled_qty': 0}
                    else:
                        filled = int(order.get('filled_quantity', 0))
                        if filled > 0:
                            return {'status': 'PARTIALLY_FILLED', 'filled_qty': filled}
                        return {'status': 'PENDING', 'filled_qty': 0}

            filled_orders = await self.get_order_history(count=20)
            for order in (filled_orders or []):
                if str(order.get('order_id', '')) == str(order_id):
                    return {'status': 'FILLED', 'filled_qty': int(order.get('quantity', 0))}

            return None
        except Exception as e:
            print(f"[{self.name}] Error getting order status for {order_id}: {e}")
            return None

    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel a pending order by order ID
        
        Args:
            order_id: The order ID to cancel
            
        Returns:
            Dict with 'success' and optional 'error' keys
        """
        try:
            result = await asyncio.to_thread(self.wb.cancel_order, order_id)
            if result:
                print(f"[{self.name}] ✓ Order {order_id} cancelled successfully")
                if self._data_hub:
                    self._data_hub.invalidate_orders()
                return {'success': True, 'order_id': order_id}
            else:
                print(f"[{self.name}] ❌ Failed to cancel order {order_id}")
                return {'success': False, 'error': 'Cancel returned False'}
        except Exception as e:
            print(f"[{self.name}] Error cancelling order {order_id}: {e}")
            return {'success': False, 'error': str(e)}
    
    async def get_option_quote(self, symbol: str, strike: float, expiry: str, call_put: str) -> Optional[Dict[str, Any]]:
        """Get current bid/ask quote for an option
        
        Args:
            symbol: Underlying symbol (e.g., 'AAPL')
            strike: Strike price
            expiry: Expiration date (YYYY-MM-DD format)
            call_put: 'C' or 'P'
            
        Returns:
            Dict with bid, ask, mid, last prices or None if not found
        """
        try:
            chain = await self.get_option_chain(symbol, expiry)
            if not chain:
                return None
            
            options_list = chain.get('calls' if call_put.upper() == 'C' else 'puts', [])
            
            for opt in options_list:
                if abs(opt.get('strike', 0) - strike) < 0.01:
                    bid = opt.get('bid', 0)
                    ask = opt.get('ask', 0)
                    mid = (bid + ask) / 2 if bid and ask else opt.get('last', 0)
                    return {
                        'bid': bid,
                        'ask': ask,
                        'mid': round(mid, 2),
                        'last': opt.get('last', 0),
                        'spread': round(ask - bid, 2) if bid and ask else 0
                    }
            
            return None
        except Exception as e:
            print(f"[{self.name}] Error getting option quote for {symbol} {strike}{call_put}: {e}")
            return None
    
    async def get_order_history(self, count: int = 50, max_cache_age: int = 120) -> list:
        """Get filled/completed order history from Webull
        
        Args:
            count: Number of recent orders to fetch (default 50)
            max_cache_age: Max cache age in seconds (default 120)
            
        Returns:
            List of filled order dicts with keys: order_id, symbol, quantity, 
            filled_price, action, filled_time, asset_type, strike, expiry, direction
        """
        try:
            import time as _t
            import threading as _threading
            if not hasattr(self, '_order_history_cache'):
                self._order_history_cache = None
                self._order_history_cache_time = 0
                self._order_history_cache_count = 0
                self._order_history_lock = _threading.Lock()
            with self._order_history_lock:
                if (self._order_history_cache is not None
                        and (_t.time() - self._order_history_cache_time) < max_cache_age
                        and self._order_history_cache_count >= count):
                    return list(self._order_history_cache[:count])

            orders_raw = await asyncio.to_thread(self.wb.get_history_orders, count=count)
            orders = []
            
            if not orders_raw:
                return []
            
            for order in orders_raw:
                status = order.get('status', '')
                if status != 'Filled':
                    continue
                    
                ticker = order.get('ticker', {})
                symbol = ticker.get('symbol', '') if ticker else ''
                
                option_data = order.get('optionExercisePrice')
                asset_type_raw = str(order.get('assetType', '')).lower()
                has_option_strike = option_data is not None and float(option_data or 0) > 0
                is_option = has_option_strike or asset_type_raw == 'option'
                
                order_dict = {
                    'order_id': str(order.get('orderId', '')),
                    'symbol': symbol,
                    'quantity': int(order.get('filledQuantity', 0) or order.get('totalQuantity', 0)),
                    'filled_price': float(order.get('avgFilledPrice', 0) or order.get('filledPrice', 0) or 0),
                    'action': order.get('action', ''),
                    'filled_time': order.get('filledTime', '') or order.get('updateTime', ''),
                    'asset_type': 'option' if is_option else 'stock',
                    'order_type': order.get('orderType', 'LMT'),
                }
                
                if is_option:
                    order_dict['strike'] = float(order.get('optionExercisePrice', 0) or 0)
                    order_dict['expiry'] = order.get('optionExpireDate', '')
                    direction = order.get('optionType', '')
                    order_dict['direction'] = 'C' if direction.upper() == 'CALL' else ('P' if direction.upper() == 'PUT' else '')
                
                orders.append(order_dict)
            
            with self._order_history_lock:
                self._order_history_cache = orders
                self._order_history_cache_time = _t.time()
                self._order_history_cache_count = count
            return orders
        except Exception as e:
            print(f"[{self.name}] Error getting order history: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    @staticmethod
    def _round_to_cboe_increment(price: float, is_sell: bool = False) -> float:
        import math
        if price <= 0:
            return 0.05
        if price < 3.00:
            increment = 0.05
        else:
            increment = 0.10
        ticks = round(price / increment, 8)
        if is_sell:
            rounded = math.floor(ticks) * increment
        else:
            rounded = math.ceil(ticks) * increment
        rounded = round(rounded, 2)
        if rounded <= 0:
            rounded = increment
        return rounded

    @staticmethod
    def _get_min_lot_size(price: float) -> int:
        """Webull minimum order sizes for low-priced stocks."""
        if price is None or price <= 0:
            return 1
        if price < 0.01:
            return 10000
        elif price < 0.1:
            return 1000
        elif price < 1.0:
            return 100
        return 1

    async def place_stock_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        price: Optional[float] = None,
        _skip_internal_retry: bool = False
    ) -> OrderResult:
        """Place a stock order"""
        try:
            side = 'BUY' if action == 'BTO' else 'SELL'
            extended_hours_enabled = self._get_extended_hours_enabled()
            
            if action == 'BTO':
                _lot_check_price = price
                if _lot_check_price is None or _lot_check_price <= 0:
                    try:
                        quote = self.wb.get_quote(stock=symbol)
                        if quote:
                            _lot_check_price = self._extract_current_price(quote)
                    except Exception:
                        pass
                if _lot_check_price and _lot_check_price > 0:
                    min_qty = self._get_min_lot_size(_lot_check_price)
                    if quantity < min_qty:
                        print(f"[{self.name}] ⚠️ Webull requires minimum {min_qty} shares for ${_lot_check_price:.4f} stocks, adjusting {quantity} → {min_qty}")
                        quantity = min_qty
            
            _effective_price = price
            _use_limit = price is not None

            if price is None:
                _convert_to_limit = False
                try:
                    from src.services.market_hours import is_regular_market_hours
                    if not is_regular_market_hours():
                        _convert_to_limit = True
                except Exception:
                    pass

                if _convert_to_limit:
                    try:
                        quote = self.wb.get_quote(stock=symbol)
                        if quote:
                            _qp = self._extract_current_price(quote)
                            if _qp > 0:
                                _rd = 4 if _qp < 1.0 else 2
                                if side == 'SELL':
                                    _effective_price = round(_qp * 0.97, _rd)
                                else:
                                    _effective_price = round(_qp * 1.03, _rd)
                                _use_limit = True
                                print(f"[{self.name}] ⚠️ Extended hours — converting MKT to LMT @ ${_effective_price:.4f}")
                    except Exception as _eq:
                        print(f"[{self.name}] ⚠️ Extended hours quote fetch failed: {_eq}")

            def execute_order():
                if not _use_limit:
                    return self.wb.place_order(
                        stock=symbol,
                        price=0.0,
                        action=side,
                        orderType='MKT',
                        enforce='GTC',
                        quant=quantity
                    )
                else:
                    return self.wb.place_order(
                        stock=symbol,
                        price=_effective_price,
                        action=side,
                        orderType='LMT',
                        enforce='GTC',
                        quant=quantity,
                        outsideRegularTradingHour=True
                    )
            
            TRANSIENT_CODES = {'trade.system.exception', 'trade.busy', 'system.busy'}
            MAX_TRANSIENT_RETRIES = 1 if _skip_internal_retry else 3
            TRANSIENT_RETRY_DELAY = 3
            
            response = None
            for attempt in range(1, MAX_TRANSIENT_RETRIES + 1):
                print(f"[{self.name}] [Attempt {attempt}] Placing order: {side} {quantity} @ ${price}")
                response = await asyncio.to_thread(execute_order)
                
                if response and response.get('code') == 'trade.token.expire':
                    print(f"[{self.name}] Trade token expired - attempting auto-refresh...")
                    refresh_success = await self._refresh_trade_token()
                    if refresh_success:
                        print(f"[{self.name}] Token refreshed, retrying order...")
                        response = await asyncio.to_thread(execute_order)
                    else:
                        self._tokens_valid = False
                        return OrderResult(
                            success=False,
                            message="Trade token expired and refresh failed. Please re-login to Webull in Settings.",
                            symbol=symbol,
                            action=action
                        )
                
                error_code = response.get('code', '') if response else ''
                is_transient = error_code in TRANSIENT_CODES or (response and 'system' in str(response.get('msg', '')).lower() and 'busy' in str(response.get('msg', '')).lower())
                
                if response and not response.get('msg'):
                    break
                elif is_transient and attempt < MAX_TRANSIENT_RETRIES:
                    print(f"[{self.name}] [Attempt {attempt}] ⚠️ Transient error: {response.get('msg', 'Unknown')} - retrying in {TRANSIENT_RETRY_DELAY}s...")
                    await asyncio.sleep(TRANSIENT_RETRY_DELAY)
                    if attempt == 2:
                        print(f"[{self.name}] Refreshing trade token before final retry...")
                        await self._refresh_trade_token()
                    continue
                else:
                    break
            
            if response and not response.get('msg'):
                try:
                    from gui_app.discord_notifier import send_bto_notification, send_stc_notification
                    
                    executed_price = price if price else 0.0
                    
                    if action == "BTO":
                        send_bto_notification(
                            symbol=symbol,
                            quantity=quantity,
                            price=executed_price
                        )
                    elif action == "STC":
                        send_stc_notification(
                            symbol=symbol,
                            quantity=quantity,
                            price=executed_price,
                            entry_price=0.0
                        )
                except Exception as e:
                    print(f"[{self.name}] Failed to send Discord notification: {e}")
                
                if self._data_hub:
                    self._data_hub.invalidate_all()
                self._order_history_cache = None
                if action == "BTO" and self._streaming_client:
                    try:
                        tid = (self._streaming_client._symbol_to_ticker_id.get(symbol.upper())
                               or (self._data_hub and self._data_hub.get_ticker_id(symbol)))
                        if tid:
                            self._streaming_client.subscribe_symbol(symbol, str(tid), is_option=False)
                            print(f"[{self.name}] ✓ Immediate stream subscribe: {symbol}")
                    except Exception:
                        pass
                return OrderResult(
                    success=True,
                    order_id=str(response.get('orderId', '')),
                    message=f"Stock order placed: {action} {quantity} {symbol}",
                    price=price,
                    quantity=quantity,
                    symbol=symbol,
                    action=action
                )
            else:
                error_msg = response.get('msg', 'Unknown error') if response else 'No response'
                error_code = response.get('code', '') if response else ''
                if error_code:
                    error_msg = f"{error_msg} (code: {error_code})"
                
                full_error = f"{error_msg} {error_code}".upper()
                if 'GENERATE_NEW_SHORT_POSITION' in full_error or ('SHORT' in full_error and 'POSITION' in full_error):
                    print(f"[{self.name}] 🛑 SHORT POSITION error for {symbol} - adding to permanent blocklist")
                    try:
                        from pathlib import Path
                        import json as _json
                        _pf_file = Path.cwd() / '.permanent_failures.json'
                        existing = []
                        if _pf_file.exists():
                            with open(_pf_file, 'r') as _f:
                                existing = _json.load(_f)
                        for key_variant in [f"{self.name}_{symbol}_stock", f"{self.name.upper()}_{symbol}_stock"]:
                            if key_variant not in existing:
                                existing.append(key_variant)
                        with open(_pf_file, 'w', encoding='utf-8') as _f:
                            _json.dump(existing, _f, indent=2)
                        print(f"[{self.name}] 🛑 {symbol} added to permanent failure blocklist")
                    except Exception as bf_err:
                        print(f"[{self.name}] ⚠️ Failed to update blocklist: {bf_err}")
                
                return OrderResult(
                    success=False,
                    message=f"Order failed: {error_msg}",
                    symbol=symbol,
                    action=action
                )
                
        except Exception as e:
            return OrderResult(
                success=False,
                message=f"Webull error: {str(e)}",
                symbol=symbol,
                action=action
            )
    
    async def place_bracket_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        stop_loss_price: Optional[float] = None,
        profit_target_price: Optional[float] = None,
        entry_price: Optional[float] = None
    ) -> OrderResult:
        """Place a bracket order (entry + stop loss + profit target)
        
        ⚠️ WEBULL LIMITATION: This places 3 SEPARATE orders (not linked as OCO)
        - Entry order (market or limit)
        - Stop loss order (independent STP)
        - Profit target order (independent LMT)
        
        Unlike Alpaca's true bracket orders, these orders are NOT automatically linked.
        If one exit fills, the other will NOT auto-cancel. Manual monitoring required.
        
        For true OCO bracket orders, use Alpaca broker.
        
        Args:
            symbol: Stock ticker
            action: BTO (buy) or STC (sell)
            quantity: Number of shares
            stop_loss_price: Stop loss price (separate order)
            profit_target_price: Profit target price (separate order)
            entry_price: Entry limit price (None for market order)
        """
        try:
            print(f"[{self.name}] ⚠️  BEST-EFFORT bracket order for {symbol} (not true OCO)...")
            if stop_loss_price:
                print(f"[{self.name}]   Stop Loss: ${stop_loss_price} (separate order)")
            if profit_target_price:
                print(f"[{self.name}]   Profit Target: ${profit_target_price} (separate order)")
            
            side = 'BUY' if action == 'BTO' else 'SELL'
            
            # Step 1: Place entry order (GTC + extended hours to match place_stock_order behavior)
            def execute_entry_order():
                if entry_price is None:
                    return self.wb.place_order(
                        stock=symbol,
                        price=0.0,
                        action=side,
                        orderType='MKT',
                        enforce='GTC',
                        quant=quantity,
                        outsideRegularTradingHour=True
                    )
                else:
                    return self.wb.place_order(
                        stock=symbol,
                        price=entry_price,
                        action=side,
                        orderType='LMT',
                        enforce='GTC',
                        quant=quantity,
                        outsideRegularTradingHour=True
                    )
            
            entry_response = await asyncio.to_thread(execute_entry_order)
            
            if not entry_response or entry_response.get('msg'):
                error_msg = entry_response.get('msg', 'Unknown error') if entry_response else 'No response'
                return OrderResult(
                    success=False,
                    message=f"Entry order failed: {error_msg}",
                    symbol=symbol,
                    action=action
                )
            
            entry_order_id = str(entry_response.get('orderId', ''))
            print(f"[{self.name}] ✓ Entry order placed (ID: {entry_order_id})")
            
            # Step 2: Place exit orders (stop loss and profit target) as OCO
            exit_order_ids = []
            exit_side = 'SELL' if action == 'BTO' else 'BUY'  # Opposite of entry
            
            # Place stop loss order
            if stop_loss_price:
                try:
                    def execute_stop_loss():
                        return self.wb.place_order(
                            stock=symbol,
                            stpPrice=stop_loss_price,
                            action=exit_side,
                            orderType='STP',
                            enforce='GTC',
                            quant=quantity
                        )
                    
                    stop_response = await asyncio.to_thread(execute_stop_loss)
                    
                    if stop_response and not stop_response.get('msg'):
                        stop_order_id = str(stop_response.get('orderId', ''))
                        exit_order_ids.append(stop_order_id)
                        print(f"[{self.name}] ✓ Stop loss order placed (ID: {stop_order_id})")
                    else:
                        print(f"[{self.name}] ⚠️ Stop loss order failed: {stop_response.get('msg', 'Unknown')}")
                except Exception as e:
                    print(f"[{self.name}] ⚠️ Stop loss error: {e}")
            
            # Place profit target order
            if profit_target_price:
                try:
                    def execute_profit_target():
                        return self.wb.place_order(
                            stock=symbol,
                            price=profit_target_price,
                            action=exit_side,
                            orderType='LMT',  # Limit order
                            enforce='GTC',
                            quant=quantity
                        )
                    
                    target_response = await asyncio.to_thread(execute_profit_target)
                    
                    if target_response and not target_response.get('msg'):
                        target_order_id = str(target_response.get('orderId', ''))
                        exit_order_ids.append(target_order_id)
                        print(f"[{self.name}] ✓ Profit target order placed (ID: {target_order_id})")
                    else:
                        print(f"[{self.name}] ⚠️ Profit target order failed: {target_response.get('msg', 'Unknown')}")
                except Exception as e:
                    print(f"[{self.name}] ⚠️ Profit target error: {e}")
            
            # Build success message
            message_parts = [f"Bracket order placed: {action} {quantity} {symbol}"]
            if stop_loss_price:
                message_parts.append(f"Stop Loss @ ${stop_loss_price}")
            if profit_target_price:
                message_parts.append(f"Target @ ${profit_target_price}")
            
            # Send Discord notification for entry order
            try:
                from gui_app.discord_notifier import send_bto_notification
                
                if action == "BTO":
                    send_bto_notification(
                        symbol=symbol,
                        quantity=quantity,
                        price=entry_price if entry_price else 0.0
                    )
            except Exception as e:
                print(f"[{self.name}] Failed to send Discord notification: {e}")
            
            return OrderResult(
                success=True,
                order_id=entry_order_id,
                message=" | ".join(message_parts) + f" (Exit orders: {len(exit_order_ids)})",
                price=entry_price if entry_price else 0.0,
                quantity=quantity,
                symbol=symbol,
                action=action
            )
                
        except Exception as e:
            error_msg = str(e)
            print(f"[{self.name}] Bracket order exception: {error_msg}")
            
            return OrderResult(
                success=False,
                message=f"Webull error: {error_msg}",
                symbol=symbol,
                action=action
            )
    
    async def place_option_order(
        self,
        symbol: str,
        strike: float,
        expiry: str,
        option_type: str,
        action: str,
        quantity: int,
        price: Optional[float] = None,
        option_id: Optional[str] = None,
        _skip_internal_retry: bool = False,
        **kwargs
    ) -> OrderResult:
        """Place an options order"""
        try:
            side = 'BUY' if action == 'BTO' else 'SELL'
            opt_type = 'call' if option_type.lower() in ['c', 'call'] else 'put'
            is_risk_order = kwargs.get('_risk_management_order', False)
            _fallback_price = kwargs.get('_signal_price_fallback')
            
            if not option_id:
                return OrderResult(
                    success=False,
                    message="Error: option_id is required for option orders",
                    symbol=symbol,
                    action=action
                )
            
            enforce = self._resolve_option_enforce(expiry)
            
            is_stc = action.upper() in ('STC', 'SELL_TO_CLOSE')
            use_aggressive_limit = False
            sell_buffers = [0.01, 0.02, 0.03, 0.05]
            
            def _get_option_quote():
                try:
                    qd = self.wb.get_option_quote(stock=symbol, optionId=option_id)
                    if qd:
                        bid_list = qd.get('bidList', [])
                        ask_list = qd.get('askList', [])
                        bid = float(bid_list[0].get('price', 0)) if bid_list else float(qd.get('bidPrice', 0) or 0)
                        ask = float(ask_list[0].get('price', 0)) if ask_list else float(qd.get('askPrice', 0) or 0)
                        last = float(qd.get('close', 0) or qd.get('lastPrice', 0) or 0)
                        return {'bid': bid if bid > 0 else 0, 'ask': ask if ask > 0 else 0, 'last': last if last > 0 else 0}
                except Exception as e:
                    print(f"[{self.name}] Option quote failed ({e})")
                return None
            
            def _get_bid_price():
                q = _get_option_quote()
                if q:
                    return q['bid'] or q['last'] or None
                return None
            
            def _get_ask_price():
                q = _get_option_quote()
                if q:
                    return q['ask'] or q['last'] or None
                return None
            
            if is_stc and is_risk_order:
                current_bid = await asyncio.to_thread(_get_bid_price)
                if current_bid and current_bid > 0:
                    _rd = 4 if current_bid < 1.0 else 2
                    price = max(0.0001, round(current_bid * (1 - sell_buffers[0]), _rd))
                    print(f"[{self.name}] ⚡ Risk STC: bid=${current_bid:.4f} → aggressive limit ${price:.4f} (-{sell_buffers[0]*100:.0f}% buffer) for fast fill")
                    use_aggressive_limit = True
                elif _fallback_price and _fallback_price > 0:
                    _rd = 4 if _fallback_price < 1.0 else 2
                    price = max(0.0001, round(_fallback_price * 0.80, _rd))
                    print(f"[{self.name}] ⚡ Risk STC: no bid, fallback ${_fallback_price:.4f} → aggressive limit ${price:.4f} (20% below)")
                    use_aggressive_limit = True
                elif price and price > 0:
                    _rd = 4 if price < 1.0 else 2
                    price = max(0.0001, round(price * 0.85, _rd))
                    print(f"[{self.name}] ⚡ Risk STC: no bid/fallback, using signal price -15% → ${price:.4f}")
                else:
                    price = 0.01
                    print(f"[{self.name}] ⚡ Risk STC: no price available, using $0.01 floor")
            elif is_stc and price is not None and price > 0:
                current_bid = await asyncio.to_thread(_get_bid_price)
                if current_bid and current_bid > 0:
                    _rd = 4 if current_bid < 1.0 else 2
                    aggressive_price = max(0.0001, round(current_bid * 0.90, _rd))
                    if price > current_bid * 1.5:
                        print(f"[{self.name}] ⚡ STC price ${price} >> current bid ${current_bid:.4f} — using aggressive limit ${aggressive_price:.4f} for fast fill")
                        price = aggressive_price
                    else:
                        print(f"[{self.name}] STC price ${price} near bid ${current_bid:.4f} — keeping limit")
            elif price is None:
                if is_stc:
                    current_bid = await asyncio.to_thread(_get_bid_price)
                    if current_bid and current_bid > 0:
                        _rd = 4 if current_bid < 1.0 else 2
                        price = max(0.0001, round(current_bid * (1 - sell_buffers[0]), _rd))
                        print(f"[{self.name}] ⚡ Market STC: bid=${current_bid:.4f} → aggressive limit ${price:.4f}")
                        use_aggressive_limit = True
                    elif _fallback_price and _fallback_price > 0:
                        _rd = 4 if _fallback_price < 1.0 else 2
                        price = max(0.0001, round(_fallback_price * 0.80, _rd))
                        print(f"[{self.name}] ⚡ Market STC: no bid, fallback → ${price:.4f}")
                    else:
                        price = 0.01
                        print(f"[{self.name}] ⚡ Market STC: no price data, using $0.01 floor")
                else:
                    current_ask = await asyncio.to_thread(_get_ask_price)
                    if current_ask and current_ask > 0:
                        _rd = 4 if current_ask < 1.0 else 2
                        price = round(current_ask * (1 + sell_buffers[0]), _rd)
                        print(f"[{self.name}] ⚡ Market BTO: ask=${current_ask:.4f} → aggressive limit ${price:.4f} (+{sell_buffers[0]*100:.0f}% buffer)")
                    elif _fallback_price and _fallback_price > 0:
                        _rd = 4 if _fallback_price < 1.0 else 2
                        price = round(_fallback_price * 1.03, _rd)
                        print(f"[{self.name}] ⚡ Market BTO: no quote, fallback → ${price:.4f}")
                    else:
                        print(f"[{self.name}] ❌ Market BTO: no ask quote and no fallback price — cannot place order")
                        return OrderResult(
                            success=False,
                            message="Cannot place market BTO: no quote available and no fallback price",
                            symbol=symbol,
                            action=action
                        )
            
            if price and price > 0:
                original_price = price
                price = self._round_to_cboe_increment(price, is_sell=is_stc)
                if price != original_price:
                    direction = "down for sell" if is_stc else "up for buy"
                    print(f"[{self.name}] CBOE increment: ${original_price:.4f} -> ${price:.2f} "
                          f"({'$0.05' if price < 3.00 else '$0.10'} increment, rounded {direction})")

            def execute_order():
                return self.wb.place_order_option(
                    optionId=option_id,
                    lmtPrice=price if price else 0.01,
                    stpPrice=None,
                    action=side,
                    orderType='LMT',
                    enforce=enforce,
                    quant=quantity
                )
            
            TRANSIENT_CODES = {'trade.system.exception', 'trade.busy', 'system.busy'}
            MAX_TRANSIENT_RETRIES = 1 if _skip_internal_retry else 3
            TRANSIENT_RETRY_DELAY = 3
            
            response = None
            for attempt in range(1, MAX_TRANSIENT_RETRIES + 1):
                print(f"[{self.name}] [Attempt {attempt}] Placing order: {side} {quantity} {symbol} ${strike}{option_type} @ ${price} (enforce={enforce})")
                response = await asyncio.to_thread(execute_order)
                
                if response and response.get('code') == 'trade.token.expire':
                    print(f"[{self.name}] Trade token expired - attempting auto-refresh...")
                    refresh_success = await self._refresh_trade_token()
                    if refresh_success:
                        print(f"[{self.name}] Token refreshed, retrying option order...")
                        response = await asyncio.to_thread(execute_order)
                    else:
                        self._tokens_valid = False
                        return OrderResult(
                            success=False,
                            message="Trade token expired and refresh failed. Please re-login to Webull in Settings.",
                            symbol=symbol,
                            action=action
                        )
                
                error_code = response.get('code', '') if response else ''
                is_transient = error_code in TRANSIENT_CODES or (response and 'system' in str(response.get('msg', '')).lower() and 'busy' in str(response.get('msg', '')).lower())
                
                if response and not response.get('msg'):
                    break
                elif is_transient and attempt < MAX_TRANSIENT_RETRIES:
                    print(f"[{self.name}] [Attempt {attempt}] ⚠️ Transient error: {response.get('msg', 'Unknown')} - retrying in {TRANSIENT_RETRY_DELAY}s...")
                    await asyncio.sleep(TRANSIENT_RETRY_DELAY)
                    if attempt == 2:
                        print(f"[{self.name}] Refreshing trade token before final retry...")
                        await self._refresh_trade_token()
                    continue
                else:
                    if is_transient:
                        print(f"[{self.name}] [Attempt {attempt}] ❌ Transient error persisted after {MAX_TRANSIENT_RETRIES} attempts: {response.get('msg', 'Unknown')}")
                    break
            
            if use_aggressive_limit and is_stc and response and response.get('msg'):
                print(f"[{self.name}] ⚡ Aggressive STC failed ({response.get('msg', 'Unknown')}), retrying with wider buffers...")
                for buf_idx, buf in enumerate(sell_buffers[1:], start=2):
                    fresh_bid = await asyncio.to_thread(_get_bid_price)
                    if fresh_bid and fresh_bid > 0:
                        price = max(0.01, round(fresh_bid * (1 - buf), 2))
                    else:
                        price = max(0.01, round(price * (1 - 0.02), 2))
                    price = self._round_to_cboe_increment(price, is_sell=True)
                    print(f"[{self.name}] ⚡ STC retry #{buf_idx}: refreshed bid=${fresh_bid or 'N/A'} → limit ${price:.2f} (-{buf*100:.0f}% buffer)")
                    def retry_order(p=price):
                        return self.wb.place_order_option(
                            optionId=option_id, lmtPrice=p, stpPrice=None,
                            action=side, orderType='LMT', enforce=enforce, quant=quantity
                        )
                    await asyncio.sleep(1)
                    response = await asyncio.to_thread(retry_order)
                    if response and not response.get('msg'):
                        print(f"[{self.name}] ⚡ STC retry #{buf_idx} accepted at ${price:.2f}")
                        break
            
            if response and not response.get('msg'):
                try:
                    from gui_app.discord_notifier import send_bto_notification, send_stc_notification
                    
                    executed_price = price if price else 0.0
                    
                    if action == "BTO":
                        send_bto_notification(
                            symbol=symbol,
                            quantity=quantity,
                            price=executed_price,
                            strike=strike,
                            expiry=expiry,
                            call_put=option_type
                        )
                    elif action == "STC":
                        send_stc_notification(
                            symbol=symbol,
                            quantity=quantity,
                            price=executed_price,
                            entry_price=0.0,
                            strike=strike,
                            expiry=expiry,
                            call_put=option_type
                        )
                except Exception as e:
                    print(f"[{self.name}] Failed to send Discord notification: {e}")
                
                if self._data_hub:
                    self._data_hub.invalidate_all()
                self._order_history_cache = None
                if action == "BTO" and self._streaming_client:
                    try:
                        oid = str(option_id) if option_id else None
                        if oid:
                            self._streaming_client.subscribe_symbol(symbol, oid, is_option=True)
                            print(f"[{self.name}] ✓ Immediate stream subscribe: {symbol} (option)")
                    except Exception:
                        pass
                return OrderResult(
                    success=True,
                    order_id=str(response.get('orderId', '')),
                    message=f"Option order placed: {action} {quantity} {symbol} ${strike}{option_type} {expiry}",
                    price=price,
                    quantity=quantity,
                    symbol=symbol,
                    action=action
                )
            else:
                error_msg = response.get('msg', 'Unknown error') if response else 'No response'
                error_code = response.get('code', '') if response else ''
                if error_code:
                    error_msg = f"{error_msg} (code: {error_code})"
                return OrderResult(
                    success=False,
                    message=f"Order failed: {error_msg}",
                    symbol=symbol,
                    action=action
                )
                
        except Exception as e:
            return OrderResult(
                success=False,
                message=f"Webull error: {str(e)}",
                symbol=symbol,
                action=action
            )
    
    def _extract_current_price(self, quote: dict) -> float:
        if not quote:
            return 0.0
        bid = float(quote.get('bidPrice', 0) or 0)
        ask = float(quote.get('askPrice', 0) or 0)
        if bid > 0 and ask > 0:
            return (bid + ask) / 2
        pp = float(quote.get('pPrice', 0) or 0)
        if pp > 0:
            return pp
        last = float(quote.get('last', 0) or 0)
        if last > 0:
            return last
        close_val = float(quote.get('close', 0) or 0)
        return close_val

    async def get_quote(self, symbol: str) -> Optional[float]:
        """Get current price for a symbol"""
        try:
            quote = await asyncio.to_thread(self.wb.get_quote, symbol)
            if quote:
                price = self._extract_current_price(quote)
                if price > 0:
                    return price
            return None
        except Exception as e:
            print(f"[{self.name}] Error getting quote for {symbol}: {e}")
            return None
    
    async def get_options_expiration_dates(self, symbol: str) -> list:
        """Get all available option expiration dates for a symbol"""
        try:
            result = await asyncio.to_thread(self.wb.get_options_expiration_dates, stock=symbol)
            
            # Handle both list (new API) and dict (old API) formats
            exp_list = []
            if isinstance(result, list):
                exp_list = result
            elif isinstance(result, dict) and 'expireDateList' in result:
                exp_list = result['expireDateList']
            
            if exp_list:
                return [
                    {
                        'date': exp.get('date', ''),
                        'count': exp.get('count', 0),
                        'label': exp.get('label', exp.get('date', ''))
                    }
                    for exp in exp_list if isinstance(exp, dict) and exp.get('date')
                ]
            return []
        except Exception as e:
            print(f"[{self.name}] Error getting expiration dates for {symbol}: {e}")
            return []
    
    async def get_option_chain(self, symbol: str, expiration_date: str) -> Dict[str, Any]:
        """Get option chain for a symbol and expiration date"""
        try:
            chain = await asyncio.to_thread(
                self.wb.get_option_chain,
                stock=symbol,
                expiration_date=expiration_date
            )
            
            if not chain:
                return {'calls': [], 'puts': [], 'stock_price': None}
            
            # Get current stock price
            stock_price = None
            if 'stock' in chain and 'close' in chain['stock']:
                stock_price = float(chain['stock']['close'])
            
            # Parse call options
            calls = []
            if 'call' in chain:
                for call in chain['call']:
                    calls.append({
                        'strike': float(call.get('strikePrice', 0)),
                        'bid': float(call.get('bidPrice', 0)),
                        'ask': float(call.get('askPrice', 0)),
                        'last': float(call.get('lastPrice', 0)),
                        'volume': int(call.get('volume', 0)),
                        'open_interest': int(call.get('openInterest', 0)),
                        'delta': float(call.get('delta', 0)),
                        'gamma': float(call.get('gamma', 0)),
                        'theta': float(call.get('theta', 0)),
                        'vega': float(call.get('vega', 0)),
                        'iv': float(call.get('impliedVolatility', 0)),
                        'option_id': call.get('optionId', ''),
                        'symbol': call.get('symbol', '')
                    })
            
            # Parse put options
            puts = []
            if 'put' in chain:
                for put in chain['put']:
                    puts.append({
                        'strike': float(put.get('strikePrice', 0)),
                        'bid': float(put.get('bidPrice', 0)),
                        'ask': float(put.get('askPrice', 0)),
                        'last': float(put.get('lastPrice', 0)),
                        'volume': int(put.get('volume', 0)),
                        'open_interest': int(put.get('openInterest', 0)),
                        'delta': float(put.get('delta', 0)),
                        'gamma': float(put.get('gamma', 0)),
                        'theta': float(put.get('theta', 0)),
                        'vega': float(put.get('vega', 0)),
                        'iv': float(put.get('impliedVolatility', 0)),
                        'option_id': put.get('optionId', ''),
                        'symbol': put.get('symbol', '')
                    })
            
            return {
                'calls': calls,
                'puts': puts,
                'stock_price': stock_price,
                'expiration': expiration_date,
                'symbol': symbol
            }
            
        except Exception as e:
            print(f"[{self.name}] Error getting option chain for {symbol} {expiration_date}: {e}")
            return {'calls': [], 'puts': [], 'stock_price': None}
    
    async def place_option_order_simple(self, symbol: str, strike: float, expiry: str, 
                                       option_type: str, quantity: int, side: str, 
                                       price: float, option_id: str) -> OrderResult:
        """
        Simplified option order placement - just specify price
        
        Args:
            symbol: Stock symbol
            strike: Strike price
            expiry: Expiration date (YYYY-MM-DD format)
            option_type: 'CALL' or 'PUT'
            quantity: Number of contracts
            side: 'BUY' or 'SELL'
            price: Limit price per contract
            option_id: Webull option contract ID (REQUIRED)
        """
        return await self.place_option_order(
            symbol=symbol,
            strike=strike,
            expiry=expiry,
            option_type=option_type,
            quantity=quantity,
            action='BTO' if side == 'BUY' else 'STC',
            price=price,
            option_id=option_id
        )


# Register this broker with the factory
BrokerFactory.register_broker('WEBULL', WebullBroker)
