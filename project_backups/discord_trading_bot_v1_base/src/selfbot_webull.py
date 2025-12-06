# selfbot_webull.py
# ------------------------------------------------------------
# Discord self-bot that reads trade signals and places orders
# on Webull (stocks + options). Use at your own risk.
# ------------------------------------------------------------
print("[STARTUP] Script starting - version with environment variable support")

import re
import json
import asyncio
import configparser
import os
from datetime import datetime
from typing import Optional, Tuple, Dict, Any
import discord

# Load environment variables from .env file (if present)
try:
    from dotenv import load_dotenv
    load_dotenv()  # Load .env file from project root
    print("[STARTUP] .env file loaded (if present)")
except ImportError:
    print("[STARTUP] python-dotenv not installed, using system environment variables only")

print("[STARTUP] Imports loaded successfully")

# ----------------------------- OPTIONAL HTTP DEBUG LOGGER -----------------------------
# Disabled to reduce console clutter - only show position updates and signals
# Uncomment the code below to enable HTTP debugging if troubleshooting API issues
# try:
#     import requests
#     _orig_request = requests.Session.request
#     def _debug_request(self, method, url, **kwargs):
#         resp = _orig_request(self, method, url, **kwargs)
#         try:
#             preview = resp.text[:400]
#         except Exception:
#             preview = "<non-text body>"
#         print(f"\n[HTTP {resp.status_code}] {method.upper()} {url}\n{preview}\n---\n")
#         return resp
#     requests.Session.request = _debug_request
#     print("[HTTP] Debug logging ENABLED")
# except Exception as _e:
#     print("[HTTP] Debug logger not enabled:", _e)

# ------------------------------------- CONFIG ----------------------------------------
from pathlib import Path

print("[CONFIG] Starting config load...")

cfg = configparser.ConfigParser()

config_paths = [
    Path(__file__).parent / 'config.ini',
    Path(__file__).parent.parent / 'config.ini',
    Path.cwd() / 'config.ini',
    Path.cwd() / 'src' / 'config.ini',
]

config_found = False
for config_path in config_paths:
    print(f"[CONFIG] Checking: {config_path}")
    if config_path.exists():
        cfg.read(str(config_path))
        print(f"[CONFIG] Loaded from: {config_path}")
        config_found = True
        break

if not config_found:
    raise SystemExit("config.ini not found. Checked locations:\n" +
                     "\n".join(f"  - {p}" for p in config_paths))

# Discord - Load from setup wizard, environment variables, or config
print("[CONFIG] Loading Discord settings...")

# Try to load from interactive setup wizard first (for EXE distribution)
wizard_credentials = {}
try:
    from setup_wizard import SetupWizard
    wizard = SetupWizard()
    if wizard.config_file.exists():
        wizard_credentials = wizard._load_credentials()
        print("[CONFIG] ✓ Loaded credentials from setup wizard")
except Exception as e:
    # Setup wizard not available or failed - fall back to env vars
    pass

try:
    # Priority: 1) Setup wizard, 2) Environment variables, 3) config.ini
    USER_TOKEN = wizard_credentials.get('DISCORD_USER_TOKEN') or os.getenv('DISCORD_USER_TOKEN', '').strip()
    if not USER_TOKEN:
        USER_TOKEN = cfg['discord'].get('discord_user_token', '').strip()
    
    if not USER_TOKEN:
        # Run setup wizard if no credentials found
        try:
            from setup_wizard import SetupWizard
            print("\n[SETUP] No credentials found. Running first-time setup wizard...")
            print()
            wizard = SetupWizard()
            wizard_credentials = wizard.run()
            USER_TOKEN = wizard_credentials['DISCORD_USER_TOKEN']
        except Exception as e:
            raise SystemExit(f"ERROR: Could not obtain Discord token. Please set DISCORD_USER_TOKEN environment variable or run setup wizard. Error: {e}")
    
    # Clean and validate token
    USER_TOKEN = USER_TOKEN.strip()
    print(f"[CONFIG] ✓ Discord token loaded (length: {len(USER_TOKEN)} chars)")
    print(f"[CONFIG]   Token starts with: {USER_TOKEN[:20]}...")
    print(f"[CONFIG]   Token ends with: ...{USER_TOKEN[-15:]}")
    
    CHANNEL_IDS = [int(x.strip()) for x in cfg['discord']['channel_ids'].split(',') if x.strip()]
    
    ALLOWED_AUTHOR_IDS = []
    author_ids_str = cfg['discord'].get('allowed_author_ids', '').strip()
    if author_ids_str:
        ALLOWED_AUTHOR_IDS = [int(x.strip()) for x in author_ids_str.split(',') if x.strip()]
    
    ALLOWED_GUILD_IDS = []
    guild_ids_str = cfg['discord'].get('allowed_guild_ids', '').strip()
    if guild_ids_str:
        ALLOWED_GUILD_IDS = [int(x.strip()) for x in guild_ids_str.split(',') if x.strip()]
    
    DISCOVERY_MODE = cfg['discord'].getboolean('discovery_mode', fallback=False)
    ALLOW_SELF_MESSAGES = cfg['discord'].getboolean('allow_self_messages', fallback=False)
    
    print(f"[CONFIG] Discord channels: {CHANNEL_IDS}")
    print(f"[CONFIG] Allowed authors: {ALLOWED_AUTHOR_IDS if ALLOWED_AUTHOR_IDS else 'ALL'}")
    print(f"[CONFIG] Allowed guilds: {ALLOWED_GUILD_IDS if ALLOWED_GUILD_IDS else 'ALL'}")
    print(f"[CONFIG] Discovery mode: {DISCOVERY_MODE}")
    print(f"[CONFIG] Allow self messages: {ALLOW_SELF_MESSAGES}")
except KeyError as e:
    raise SystemExit(f"Missing [discord] key in config.ini: {e}")

# Signals - LOWERCASE C/P FIX
print("[CONFIG] Loading signal patterns...")

FLEXIBLE_OPT_PATTERN = r'^(BTO|STC)\s+(\d+)\s+([A-Za-z]+)\s+([\d.]+)\s*([CPcp])\s+(\d{2}/\d{2})\s*@\s*([\d.]+)'
DEFAULT_STK_PATTERN = r'^(BTO|STC)\s+(\d+)\s+([A-Za-z]+)\s*@\s*([\d.]+)'

OPT_REGEX = re.compile(cfg.get('signals', 'pattern', fallback=FLEXIBLE_OPT_PATTERN), re.IGNORECASE)
STK_REGEX = re.compile(cfg.get('signals', 'stock_pattern', fallback=DEFAULT_STK_PATTERN), re.IGNORECASE)

print(f"[CONFIG] ✓ Option pattern: {OPT_REGEX.pattern}")
print(f"[CONFIG] ✓ Stock pattern: {STK_REGEX.pattern}")
print(f"[CONFIG] ✓ IGNORECASE flag: {bool(OPT_REGEX.flags & re.IGNORECASE)}")

# Auto-quantity calculation when quantity not specified
MAX_POSITION_SIZE = cfg.getfloat('signals', 'max_position_size', fallback=200.0)
if MAX_POSITION_SIZE <= 0:
    raise SystemExit("ERROR: max_position_size must be positive in config.ini")
print(f"[CONFIG] ✓ Max position size (auto-qty): ${MAX_POSITION_SIZE}")

# Risk Management - Profit targets, stop loss, trailing stops
print("[CONFIG] Loading risk management settings...")
ENABLE_RISK_MGMT = cfg.getboolean('risk_management', 'enable_risk_management', fallback=False)
MONITORING_INTERVAL = cfg.getint('risk_management', 'monitoring_interval', fallback=30)
PROFIT_TARGET_PCT = cfg.getfloat('risk_management', 'profit_target_percent', fallback=0.0)
STOP_LOSS_PCT = cfg.getfloat('risk_management', 'stop_loss_percent', fallback=0.0)
TRAILING_STOP_PCT = cfg.getfloat('risk_management', 'trailing_stop_percent', fallback=0.0)
TRAILING_ACTIVATION_PCT = cfg.getfloat('risk_management', 'trailing_stop_activation_percent', fallback=0.0)

if ENABLE_RISK_MGMT:
    print(f"[CONFIG] ✓ Risk management ENABLED")
    print(f"[CONFIG]   - Monitoring interval: {MONITORING_INTERVAL}s")
    print(f"[CONFIG]   - Profit target: {PROFIT_TARGET_PCT}%")
    print(f"[CONFIG]   - Stop loss: {STOP_LOSS_PCT}%")
    print(f"[CONFIG]   - Trailing stop: {TRAILING_STOP_PCT}% (activates after {TRAILING_ACTIVATION_PCT}% gain)")
else:
    print(f"[CONFIG] Risk management DISABLED")

# Webull - Load from setup wizard, environment variables, or config
print("[CONFIG] Loading Webull settings...")
try:
    # Priority: 1) Setup wizard, 2) Environment variables, 3) config.ini
    WB_USER = wizard_credentials.get('WEBULL_USERNAME') or os.getenv('WEBULL_USERNAME', '').strip()
    if not WB_USER:
        WB_USER = cfg['webull'].get('username', '').strip()
    
    WB_PASS = wizard_credentials.get('WEBULL_PASSWORD') or os.getenv('WEBULL_PASSWORD', '').strip()
    if not WB_PASS:
        WB_PASS = cfg['webull'].get('password', '').strip()
    
    WB_PIN = wizard_credentials.get('WEBULL_TRADE_PIN') or os.getenv('WEBULL_TRADE_PIN', '').strip()
    if not WB_PIN:
        WB_PIN = cfg['webull'].get('trade_pin', '').strip()
    
    WB_ACCESS_TOKEN = wizard_credentials.get('WEBULL_ACCESS_TOKEN') or os.getenv('WEBULL_ACCESS_TOKEN', '').strip()
    if not WB_ACCESS_TOKEN:
        WB_ACCESS_TOKEN = cfg['webull'].get('access_token', '').strip()
    
    WB_REFRESH_TOKEN = wizard_credentials.get('WEBULL_REFRESH_TOKEN') or os.getenv('WEBULL_REFRESH_TOKEN', '').strip()
    if not WB_REFRESH_TOKEN:
        WB_REFRESH_TOKEN = cfg['webull'].get('refresh_token', '').strip()
    
    WB_DID = wizard_credentials.get('WEBULL_DID') or os.getenv('WEBULL_DID', '').strip()
    if not WB_DID:
        WB_DID = cfg['webull'].get('did', '').strip()
    
    if WB_ACCESS_TOKEN and WB_REFRESH_TOKEN:
        print("[CONFIG] ✓ Using saved access/refresh tokens (skipping login)")
    elif not WB_USER or not WB_PASS:
        raise SystemExit("ERROR: Either provide access_token+refresh_token OR username+password in environment or config.ini")
    
    if not WB_PIN:
        raise SystemExit("ERROR: WEBULL_TRADE_PIN must be set in environment or config.ini")
    
    WB_DEVICE = cfg['webull'].get('device_name', 'MyTradingBot').strip()
    WB_ENFORCE = cfg['webull'].get('enforce', 'GTC').strip().upper()
    PAPER_TRADE = cfg['webull'].getboolean('paper_trade', fallback=True)
    
    print(f"[CONFIG] Webull user: {WB_USER if WB_USER else '(using saved tokens)'}")
    print(f"[CONFIG] Webull DID: {WB_DID if WB_DID else '(not set)'}")
    print(f"[CONFIG] Webull enforce: {WB_ENFORCE}")
    print(f"[CONFIG] Paper trading: {PAPER_TRADE}")
    
    if PAPER_TRADE:
        print("[CONFIG] ⚠️  PAPER TRADING MODE ENABLED - No real trades will be executed")
    else:
        print("[CONFIG] ⚠️  LIVE TRADING MODE - Real trades will be executed!")
        
except KeyError as e:
    raise SystemExit(f"Missing [webull] key in config.ini: {e}")

if WB_ENFORCE not in ('GTC', 'DAY'):
    WB_ENFORCE = 'GTC'

def _latin1(s: str) -> str:
    return (s or "").encode('latin-1', 'ignore').decode('latin-1')

print("[CONFIG] ✓ All settings loaded successfully\n")

# ------------------------------ HELPERS ---------------------------------------
def fix_symbol(symbol: str, direction: str) -> str:
    if direction == 'in':
        return symbol.replace("SPXW", "SPX").replace("NDXP", "NDX")
    elif direction == 'out':
        return symbol.replace("SPX", "SPXW").replace("NDX", "NDXP")
    return symbol

# --------------------------------- WEBULL BROKER -------------------------------------
class WebullBroker:
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop
        self._client = None
        self._logged_in = False

    def _patch_headers(self, wb):
        if hasattr(wb, "_session") and hasattr(wb, "_headers"):
            safe_device = _latin1(WB_DEVICE or "AndroidDevice")
            safe_ua = _latin1('Mozilla/5.0 (Linux; Android 13; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Mobile Safari/537.36')
            wb._headers.update({
                'did': _latin1(WB_DID) if WB_DID else '',
                'device-type': 'Android',
                'device-name': safe_device,
                'os': 'Android',
                'os-version': '13',
                'app': 'global',
                'app-version': '9.53.3',
                'accept-language': 'en-US',
                'user-agent': safe_ua,
            })
            wb._session.headers.update(wb._headers)

    def _set_did(self, wb):
        if WB_DID:
            if hasattr(wb, "_set_did"):
                wb._set_did(WB_DID)
            else:
                wb._did = WB_DID

    def _apply_tokens(self, wb, access_token, refresh_token, did_from_web=None):
        for attr, val in (("_access_token", access_token),
                          ("access_token", access_token),
                          ("_refresh_token", refresh_token),
                          ("refresh_token", refresh_token),
                          ("_did", did_from_web or WB_DID)):
            try:
                setattr(wb, attr, val)
            except Exception:
                pass
        if hasattr(wb, "_headers"):
            wb._headers['Authorization'] = f'Bearer {access_token}'
        if hasattr(wb, "_session"):
            wb._session.headers['Authorization'] = f'Bearer {access_token}'
        if did_from_web:
            try:
                if hasattr(wb, "_set_did"):
                    wb._set_did(did_from_web)
                else:
                    wb._did = did_from_web
            except Exception:
                pass

    async def login(self):
        def _blocking_login():
            from webull import webull
            wb = webull()
            try:
                self._set_did(wb)
            except Exception as e:
                print(f"[Webull] DID set warning: {e}")
            try:
                self._patch_headers(wb)
            except Exception as e:
                print(f"[Webull] header patch warning: {e}")

            if WB_ACCESS_TOKEN and WB_REFRESH_TOKEN:
                print("[Webull] Using saved access/refresh tokens")
                self._apply_tokens(wb, WB_ACCESS_TOKEN, WB_REFRESH_TOKEN, did_from_web=WB_DID or None)
                print("[Webull] ✓ Tokens applied successfully")
            else:
                try:
                    print(f"[Webull] Attempting login with username: {WB_USER}")
                    data = wb.login(WB_USER, WB_PASS, _latin1(WB_DEVICE))
                    if not (data and data.get('accessToken')):
                        raise RuntimeError(f"login returned no accessToken: {data}")
                    print("[Webull] ✓ Login successful")
                except Exception as e_login:
                    print(f"[Webull] primary login failed: {e_login}")
                    print("[Webull] Using manual token bootstrap from your logged-in browser session.")
                    print("\n>>> In Chrome/Edge: open https://app.webull.com, log in, press F12 → Console and paste:")
                    print("""console.log(JSON.stringify({
  accessToken: sessionStorage.accessToken || localStorage.accessToken || localStorage.ACCESS_TOKEN || '',
  refreshToken: sessionStorage.refreshToken || localStorage.refreshToken || localStorage.REFRESH_TOKEN || '',
  did: sessionStorage.did || localStorage.did || sessionStorage.deviceId || localStorage.deviceId || ''
}));""")
                    print("\n>>> After getting the JSON, save these values to config.ini or Replit Secrets:")
                    print("    access_token = <accessToken value>")
                    print("    refresh_token = <refreshToken value>")
                    print("    did = <did value>")
                    blob = input("\nPaste the printed JSON here: ").strip()
                    try:
                        tokens = json.loads(blob)
                    except Exception:
                        raise RuntimeError("Invalid JSON pasted. Please paste exactly what the console printed.")
                    acc = (tokens.get("accessToken") or "").strip()
                    ref = (tokens.get("refreshToken") or "").strip()
                    did_web = (tokens.get("did") or "").strip()
                    if not acc:
                        raise RuntimeError("Missing accessToken in pasted JSON.")
                    if not ref:
                        print("[Webull] No refreshToken provided — continuing with accessToken only.")
                    self._apply_tokens(wb, acc, ref, did_from_web=did_web or None)

            try:
                wb.get_account_id()
            except Exception as e_acc:
                print(f"[Webull] get_account_id warning: {e_acc}")
            try:
                wb.get_trade_token(WB_PIN)
            except Exception as e_pin:
                raise RuntimeError(f"get_trade_token failed (check your 6-digit trading PIN): {e_pin}")
            return wb

        self._client = await self.loop.run_in_executor(None, _blocking_login)
        self._logged_in = True

    async def _ensure_login(self):
        if not self._logged_in:
            await self.login()

    def _wb_get_option_id_strict(self, wb, base_symbol: str, strike: float, opt_type: str, expiry_mmdd: str, expiry_year: str = None) -> Tuple[int, int]:
        def iso_from_mmdd(mmdd: str, year: str = None) -> str:
            m, d = mmdd.split('/')
            if year is None:
                yyyy = datetime.now().strftime('%Y')
            else:
                yyyy = year
            return f"{yyyy}-{int(m):02d}-{int(d):02d}"

        def iter_rows(obj):
            if isinstance(obj, dict):
                yield obj
                for v in obj.values():
                    yield from iter_rows(v)
            elif isinstance(obj, list):
                for it in obj:
                    yield from iter_rows(it)

        def extract_candidate(row, direction: str):
            if not isinstance(row, dict):
                return None

            strike_raw = row.get('strikePrice') or row.get('strike')
            try:
                strike_val = float(strike_raw) if strike_raw is not None else None
            except Exception:
                strike_val = None

            exp = row.get('expireDate') or row.get('expiry') or row.get('date')

            side = (row.get('callPut') or row.get('optionType') or row.get('direction') or '').lower()
            nested = row.get(direction)
            nested_oid = None
            nested_exp = None
            if isinstance(nested, dict):
                nested_oid = nested.get('tickerId') or nested.get('id') or nested.get('optionId')
                nested_exp = nested.get('expireDate') or nested.get('expiry') or nested.get('date')

            oid = row.get('tickerId') or row.get('optionId') or row.get('id')

            if not side and isinstance(nested, dict):
                side = direction
            side = {'c': 'call', 'p': 'put'}.get(side[:1], side)

            if nested_oid:
                oid = nested_oid
            if nested_exp:
                exp = nested_exp

            if (strike_val is None) or (oid is None):
                return None

            return {
                'strike': strike_val,
                'side': side,
                'expiry': exp,
                'option_id': oid
            }

        symbol = fix_symbol(base_symbol, "in")
        direction = 'call' if opt_type.upper() == 'C' else 'put'
        iso_exp = iso_from_mmdd(expiry_mmdd, year=expiry_year)
        target_strike = float(strike)

        tId = wb.get_ticker(symbol)
        if not tId:
            raise RuntimeError(f"Symbol not found: {symbol}")

        data = wb.get_options(stock=symbol, direction=direction, expireDate=iso_exp)
        candidates = []
        for row in iter_rows(data):
            cand = extract_candidate(row, direction)
            if not cand:
                continue
            if cand['side'] != direction:
                continue
            if cand['expiry'] and str(cand['expiry']).startswith(iso_exp):
                candidates.append(cand)

        if not candidates:
            data = wb.get_options(stock=symbol, direction=direction)
            for row in iter_rows(data):
                cand = extract_candidate(row, direction)
                if not cand:
                    continue
                if cand['side'] != direction:
                    continue
                if cand['expiry'] and str(cand['expiry']).startswith(iso_exp):
                    candidates.append(cand)

        for cand in candidates:
            if abs(cand['strike'] - target_strike) < 1e-6:
                return int(cand['option_id']), int(tId)

        best = None
        best_diff = 1e9
        for cand in candidates:
            diff = abs(cand['strike'] - target_strike)
            if diff < best_diff:
                best, best_diff = cand, diff
        if best and best_diff <= 0.01:
            return int(best['option_id']), int(tId)

        raise RuntimeError(f"OptionId not found for {symbol} {strike}{opt_type} {iso_exp}")

    async def place_option_order(self, action: str, qty: int, symbol: str,
                                 strike: float, opt_type: str, expiry_mmdd: str,
                                 limit_price: float, expiry_year: str = None) -> Dict[str, Any]:
        await self._ensure_login()
        
        if PAPER_TRADE:
            print(f"[PAPER TRADE] Would place {action} {qty} {symbol} {strike}{opt_type} {expiry_mmdd} @{limit_price}")
            return {
                'success': True,
                'msg': 'Paper trade - no actual order placed',
                'paper_trade': True,
                'signal': {
                    'action': action,
                    'qty': qty,
                    'symbol': symbol,
                    'strike': strike,
                    'opt_type': opt_type,
                    'expiry': expiry_mmdd,
                    'price': limit_price
                }
            }

        def _blocking_place():
            import inspect
            wb = self._client
            option_id, tId = self._wb_get_option_id_strict(wb, symbol, strike, opt_type, expiry_mmdd, expiry_year)
            side = 'BUY' if action.upper() in ('BTO', 'BTC') else 'SELL'

            if not hasattr(wb, "place_order_option"):
                raise RuntimeError("Your installed `webull` package has no place_order_option(). Please upgrade that package.")

            payload_v1 = {
                'optionId': int(option_id),
                'lmtPrice': float(limit_price),
                'action': side,
                'orderType': 'LMT',
                'enforce': WB_ENFORCE,
                'quant': int(qty),
            }
            print(f"[DEBUG] place_order_option basic payload: {payload_v1}")

            resp = None
            try:
                resp = wb.place_order_option(**payload_v1)
            except TypeError:
                payload_v1_snake = {
                    'option_id': int(option_id),
                    'lmtPrice': float(limit_price),
                    'action': side,
                    'orderType': 'LMT',
                    'enforce': WB_ENFORCE,
                    'quant': int(qty),
                }
                print(f"[DEBUG] Retrying with snake_case: {payload_v1_snake}")
                try:
                    resp = wb.place_order_option(**payload_v1_snake)
                except:
                    resp = {'success': False, 'msg': 'stock is required'}
                    print(f"[DEBUG] Forcing fallback due to TypeError")

            need_fallback = False
            if isinstance(resp, dict):
                print(f"[DEBUG] place_order_option response: {resp}")
                msg = (str(resp) or "").lower()
                if resp.get('success') is False or 'error' in msg or 'exception' in msg:
                    need_fallback = True
                    print(f"[DEBUG] Triggering fallback due to error response")

            if not need_fallback:
                print(f"[DEBUG] place_order_option succeeded, returning response")
                return resp

            if not hasattr(wb, "place_option_order"):
                raise RuntimeError("Server requires 'stock' but this client has no place_option_order(). Update your webull package.")

            payload_v2 = {
                'option_id': int(option_id),
                'lmtPrice': float(limit_price),
                'orderType': 'LMT',
                'enforce': WB_ENFORCE,
                'quant': int(qty),
                'action': side,
                'outsideRegularTradingHour': True,
                'stock': fix_symbol(symbol, "in"),
                'tId': int(tId),
                'comboType': 'NORMAL',
                'serialId': None,
            }
            print(f"[DEBUG] fallback place_option_order payload: {payload_v2}")
            resp2 = wb.place_option_order(**payload_v2)
            return resp2

        return await self.loop.run_in_executor(None, _blocking_place)

    async def place_stock_order(self, action: str, qty: int, symbol: str, limit_price: float) -> Dict[str, Any]:
        await self._ensure_login()
        
        if PAPER_TRADE:
            print(f"[PAPER TRADE] Would place {action} {qty} {symbol} @{limit_price}")
            return {
                'success': True,
                'msg': 'Paper trade - no actual order placed',
                'paper_trade': True,
                'signal': {
                    'action': action,
                    'qty': qty,
                    'symbol': symbol,
                    'price': limit_price
                }
            }

        def _blocking_place():
            import inspect
            wb = self._client
            base_sym = fix_symbol(symbol, "in")
            tId = wb.get_ticker(base_sym)
            if not tId:
                raise RuntimeError(f"Symbol not found: {base_sym}")

            side = 'BUY' if action.upper() in ('BTO', 'BTC') else 'SELL'

            base_payload = {
                'stock': base_sym,
                'tId': int(tId),
                'price': float(limit_price),
                'lmtPrice': float(limit_price),
                'action': side,
                'orderType': 'LMT',
                'enforce': WB_ENFORCE,
                'quant': int(qty),
                'outsideRegularTradingHour': True,
                'stpPrice': None,
                'trial_value': None,
                'trial_type': None,
            }

            func = None
            if hasattr(wb, 'place_order'):
                func = wb.place_order
            elif hasattr(wb, 'place_stock_order'):
                func = wb.place_stock_order
            else:
                raise RuntimeError("This webull client lacks place_order/place_stock_order.")

            try:
                sig = inspect.signature(func)
                allowed = set(sig.parameters.keys())
            except Exception:
                allowed = {'stock','tId','price','action','orderType','enforce','quant',
                           'outsideRegularTradingHour','stpPrice','trial_value','trial_type','lmtPrice'}
            payload = {k: v for k, v in base_payload.items() if k in allowed}

            if 'price' not in allowed and 'lmtPrice' in allowed:
                payload.pop('price', None)
            if 'lmtPrice' not in allowed and 'price' in payload:
                payload.pop('lmtPrice', None)

            print(f"[DEBUG] place_stock payload: {payload}")
            resp = func(**payload)
            return resp

        return await self.loop.run_in_executor(None, _blocking_place)

    async def get_positions(self) -> list:
        """Get current open positions from Webull (stocks and options)"""
        def _blocking_get():
            wb = self._client
            if not wb:
                return []
            
            positions = []
            
            # Get all positions (stocks and options together)
            try:
                all_positions = wb.get_positions()
                if all_positions:
                    for pos in all_positions:
                        # Convert position to float for comparison (API may return string)
                        try:
                            position_qty = float(pos.get('position', 0))
                        except (ValueError, TypeError):
                            position_qty = 0
                        
                        if position_qty <= 0:  # Skip closed positions
                            continue
                        
                        # Determine asset type
                        symbol = pos.get('ticker', {}).get('symbol', '') or pos.get('symbol', '')
                        asset_type = pos.get('assetType', 'unknown')
                        
                        # Check if this is an option by looking for option-specific fields
                        is_option = (
                            'optionId' in pos or 
                            'strikePrice' in pos or 
                            'expireDate' in pos or
                            asset_type in ('option', 'OPTION', 'OPT')
                        )
                        
                        if is_option:
                            # Option position - use tickerId to fetch details if missing
                            ticker_id = pos.get('tickerId', 0)
                            symbol = pos.get('ticker', {}).get('symbol', '') or pos.get('symbol', '')
                            
                            # Try to get option details from API using tickerId
                            option_details = None
                            if ticker_id:
                                try:
                                    # Use tickerId as optionId to get full option details
                                    option_details = wb.get_option_quote(stock=symbol, optionId=str(ticker_id))
                                except Exception as e:
                                    print(f"[RISK] Warning: Could not fetch option details for {symbol}: {e}")
                            
                            # Extract option metadata from API response or fallback to empty
                            strike = 0.0
                            expiry = ''
                            direction = ''
                            option_id = ticker_id
                            
                            if option_details and isinstance(option_details, dict) and 'data' in option_details:
                                # Search for the matching option in the data array by tickerId
                                matched_option = None
                                for opt in option_details.get('data', []):
                                    if opt.get('tickerId') == ticker_id:
                                        matched_option = opt
                                        break
                                
                                if matched_option:
                                    # Extract metadata from matched option
                                    strike = float(matched_option.get('strikePrice', 0))
                                    
                                    # Convert expiry date: "2025-12-19" -> "12/19" or "12/19/25"
                                    raw_expiry = matched_option.get('expireDate', '')
                                    if raw_expiry:
                                        from datetime import datetime
                                        try:
                                            exp_date = datetime.strptime(raw_expiry, '%Y-%m-%d')
                                            current_year = datetime.now().year
                                            if exp_date.year == current_year:
                                                expiry = exp_date.strftime('%m/%d')  # Same year: "12/19"
                                            else:
                                                expiry = exp_date.strftime('%m/%d/%y')  # Future year: "12/19/25"
                                        except:
                                            expiry = raw_expiry
                                    
                                    # Convert direction: "call" -> "C", "put" -> "P"
                                    raw_direction = matched_option.get('direction', '').lower()
                                    if raw_direction == 'call':
                                        direction = 'C'
                                    elif raw_direction == 'put':
                                        direction = 'P'
                                    
                                    option_id = ticker_id
                                else:
                                    print(f"[RISK] Warning: Could not match option metadata for {symbol} (tickerId={ticker_id})")
                            
                            positions.append({
                                'asset': 'option',
                                'symbol': symbol,
                                'quantity': float(pos.get('position', 0)),
                                'avg_cost': float(pos.get('costPrice', 0)),
                                'current_price': float(pos.get('latestPrice', 0) or pos.get('lastPrice', 0)),
                                'unrealized_pl': float(pos.get('unrealizedProfitLoss', 0)),
                                'option_id': option_id,
                                'strike': strike,
                                'expiry': expiry,
                                'direction': direction,
                                'ticker_id': ticker_id  # Keep for future lookups
                            })
                        else:
                            # Stock position
                            quantity = float(pos.get('position', 1))
                            market_value = float(pos.get('marketValue', 0))
                            current_price = market_value / quantity if quantity > 0 else 0
                            
                            positions.append({
                                'asset': 'stock',
                                'symbol': pos.get('ticker', {}).get('symbol', ''),
                                'quantity': quantity,
                                'avg_cost': float(pos.get('costPrice', 0)),
                                'current_price': current_price,
                                'unrealized_pl': float(pos.get('unrealizedProfitLoss', 0)),
                                'ticker_id': pos.get('ticker', {}).get('tickerId', 0)
                            })
            except Exception as e:
                print(f"[RISK] Warning: Could not fetch positions: {e}")
                import traceback
                traceback.print_exc()
            
            return positions
        
        return await self.loop.run_in_executor(None, _blocking_get)

    async def get_latest_quote(self, symbol: str, asset_type: str = 'stock', option_id: int = None):
        """Get latest price quote for a symbol"""
        def _blocking_quote():
            wb = self._client
            if not wb:
                return None
            
            try:
                if asset_type == 'option' and option_id:
                    # For options, we need the option ID
                    quote = wb.get_option_quote(option_id=option_id)
                    if quote:
                        return float(quote.get('latestPrice', 0))
                else:
                    # For stocks
                    quote = wb.get_quote(stock=symbol)
                    if quote:
                        return float(quote.get('close', 0) or quote.get('lastPrice', 0))
            except Exception as e:
                print(f"[RISK] Warning: Could not fetch quote for {symbol}: {e}")
            
            return None
        
        return await self.loop.run_in_executor(None, _blocking_quote)

    async def monitor_positions(self, order_queue: asyncio.Queue):
        """Background task to monitor positions and manage risk"""
        if not ENABLE_RISK_MGMT:
            print("[RISK] Position monitoring disabled (enable_risk_management = false)")
            return
        
        print(f"[RISK] ✓ Position monitoring started (interval: {MONITORING_INTERVAL}s)")
        print(f"[RISK]   Profit target: {PROFIT_TARGET_PCT}%, Stop loss: {STOP_LOSS_PCT}%, Trailing stop: {TRAILING_STOP_PCT}%")
        
        # Position cache: key = unique position ID, value = tracking state
        position_cache = {}
        
        # Load cache from file (if exists)
        cache_file = Path.cwd() / '.position_cache.json'
        try:
            if cache_file.exists():
                with open(cache_file, 'r') as f:
                    position_cache = json.load(f)
                print(f"[RISK] Loaded {len(position_cache)} cached positions")
        except Exception as e:
            print(f"[RISK] Warning: Could not load position cache: {e}")
        
        while True:
            try:
                await asyncio.sleep(MONITORING_INTERVAL)
                
                # Get current open positions from Webull
                positions = await self.get_positions()
                
                if not positions:
                    continue
                
                print(f"\n[RISK] Monitoring {len(positions)} open positions...")
                
                for pos in positions:
                    # Create unique key for this position
                    if pos['asset'] == 'option':
                        pos_key = f"{pos['symbol']}_{pos.get('strike', '')}_{pos.get('expiry', '')}_{pos.get('direction', '')}"
                    else:
                        pos_key = f"{pos['symbol']}_stock"
                    
                    # Initialize cache entry if new position
                    if pos_key not in position_cache:
                        position_cache[pos_key] = {
                            'entry_price': pos['avg_cost'],
                            'highest_price': pos['current_price'],
                            'trailing_activated': False,
                            'closing': False
                        }
                        print(f"[RISK] New position tracked: {pos_key} @ ${pos['avg_cost']:.2f}")
                    
                    cache = position_cache[pos_key]
                    
                    # Skip if already closing
                    if cache.get('closing', False):
                        continue
                    
                    # Update highest price
                    if pos['current_price'] > cache['highest_price']:
                        cache['highest_price'] = pos['current_price']
                    
                    # Calculate profit/loss percentage
                    entry = cache['entry_price']
                    current = pos['current_price']
                    pct_change = ((current - entry) / entry) * 100
                    
                    print(f"[RISK] {pos_key}: ${current:.2f} ({pct_change:+.2f}%) | Entry: ${entry:.2f} | Qty: {pos['quantity']}")
                    
                    # Check exit conditions
                    should_exit = False
                    exit_reason = ""
                    
                    # 1. Profit target hit
                    if PROFIT_TARGET_PCT > 0 and pct_change >= PROFIT_TARGET_PCT:
                        should_exit = True
                        exit_reason = f"PROFIT TARGET ({pct_change:.2f}% >= {PROFIT_TARGET_PCT}%)"
                    
                    # 2. Stop loss hit (if not using trailing stop)
                    elif TRAILING_STOP_PCT == 0 and STOP_LOSS_PCT > 0 and pct_change <= -STOP_LOSS_PCT:
                        should_exit = True
                        exit_reason = f"STOP LOSS ({pct_change:.2f}% <= -{STOP_LOSS_PCT}%)"
                    
                    # 3. Trailing stop logic
                    elif TRAILING_STOP_PCT > 0:
                        # Activate trailing stop if profit threshold reached
                        if not cache['trailing_activated'] and pct_change >= TRAILING_ACTIVATION_PCT:
                            cache['trailing_activated'] = True
                            print(f"[RISK] {pos_key}: Trailing stop ACTIVATED at {pct_change:.2f}% gain")
                        
                        # If trailing stop active, check if price dropped below trailing threshold
                        if cache['trailing_activated']:
                            trailing_stop_price = cache['highest_price'] * (1 - TRAILING_STOP_PCT / 100)
                            if current <= trailing_stop_price:
                                should_exit = True
                                exit_reason = f"TRAILING STOP (${current:.2f} <= ${trailing_stop_price:.2f}, dropped {TRAILING_STOP_PCT}% from high ${cache['highest_price']:.2f})"
                        
                        # Also check fixed stop loss before trailing activates
                        elif STOP_LOSS_PCT > 0 and pct_change <= -STOP_LOSS_PCT:
                            should_exit = True
                            exit_reason = f"STOP LOSS ({pct_change:.2f}% <= -{STOP_LOSS_PCT}%)"
                    
                    # Execute exit if conditions met
                    if should_exit:
                        print(f"[RISK] ✓ EXIT TRIGGERED: {pos_key} - {exit_reason}")
                        
                        # Mark as closing to prevent duplicate orders
                        cache['closing'] = True
                        
                        try:
                            # Create STC signal
                            stc_signal = {
                                'asset': pos['asset'],
                                'action': 'STC',
                                'qty': int(pos['quantity']),
                                'symbol': pos['symbol'],
                                'price': current  # Market price for limit order
                            }
                            
                            # Add option-specific fields
                            if pos['asset'] == 'option':
                                # Convert ISO date format (YYYY-MM-DD) to MM/DD format
                                # Preserve year for LEAPS (long-term options) or store it separately
                                expiry_iso = pos.get('expiry', '')
                                expiry_year = None
                                if expiry_iso and '-' in expiry_iso:
                                    # Parse YYYY-MM-DD and convert to MM/DD
                                    parts = expiry_iso.split('-')
                                    if len(parts) == 3:
                                        expiry_year = parts[0]  # Preserve year
                                        expiry_mmdd = f"{parts[1]}/{parts[2]}"  # MM/DD
                                    else:
                                        expiry_mmdd = expiry_iso  # Fallback to original
                                else:
                                    expiry_mmdd = expiry_iso  # Already in correct format or empty
                                
                                # Convert direction: "CALL" → "C", "PUT" → "P"
                                direction = pos.get('direction', '').upper()
                                if direction == 'CALL':
                                    opt_type = 'C'
                                elif direction == 'PUT':
                                    opt_type = 'P'
                                else:
                                    # Assume single letter format already (C or P)
                                    opt_type = direction[0] if direction else 'C'
                                
                                stc_signal['strike'] = pos.get('strike', 0)
                                stc_signal['opt_type'] = opt_type
                                stc_signal['expiry'] = expiry_mmdd
                                stc_signal['expiry_year'] = expiry_year  # Preserve year for LEAPS
                                stc_signal['option_id'] = pos.get('option_id', 0)
                            
                            # Add to order queue for processing (None = automated order, not from Discord)
                            await order_queue.put((None, stc_signal))
                            print(f"[RISK] STC order queued for {pos_key}: {stc_signal}")
                        
                        except Exception as e:
                            # If order enqueueing fails, clear closing flag so we can retry
                            cache['closing'] = False
                            print(f"[RISK] ✗ Failed to queue STC order for {pos_key}: {e}")
                
                # Save cache to file
                try:
                    with open(cache_file, 'w') as f:
                        json.dump(position_cache, f, indent=2)
                except Exception as e:
                    print(f"[RISK] Warning: Could not save position cache: {e}")
                
                # Clean up closed positions from cache
                current_pos_keys = set()
                for pos in positions:
                    if pos['asset'] == 'option':
                        pos_key = f"{pos['symbol']}_{pos.get('strike', '')}_{pos.get('expiry', '')}_{pos.get('direction', '')}"
                    else:
                        pos_key = f"{pos['symbol']}_stock"
                    current_pos_keys.add(pos_key)
                
                # Remove positions that are no longer open
                closed_keys = set(position_cache.keys()) - current_pos_keys
                for key in closed_keys:
                    del position_cache[key]
                    print(f"[RISK] Position closed: {key}")
                
            except Exception as e:
                print(f"[RISK] Error in position monitoring: {e}")
                import traceback
                traceback.print_exc()

# ------------------------------ SIGNAL PARSER -------------------------------------
def parse_option_signal(text: str) -> Optional[dict]:
    m = OPT_REGEX.match(text.strip())
    if not m:
        return None
    direction, qty_str, symbol, strike, opt_type, expiry, price_str = m.groups()
    
    price = float(price_str)
    
    # Calculate quantity if not specified
    # CRITICAL: Options cost 100x the quoted premium (1 contract = 100 shares)
    if qty_str is None:
        actual_cost_per_contract = price * 100
        if actual_cost_per_contract <= 0:
            print(f"[AUTO-QTY] ✗ Invalid option price: ${price}, skipping auto-calculation")
            return None
        qty = max(1, int(MAX_POSITION_SIZE / actual_cost_per_contract))
        print(f"[AUTO-QTY] Option: ${price} premium x 100 = ${actual_cost_per_contract}/contract, buying {qty} contracts (max ${MAX_POSITION_SIZE})")
    else:
        qty = int(qty_str)
    
    return {
        "asset": "option",
        "action": direction.upper(),
        "qty": qty,
        "symbol": symbol.upper(),
        "strike": float(strike),
        "opt_type": opt_type.upper(),
        "expiry": expiry,
        "price": price
    }

def parse_stock_signal(text: str) -> Optional[dict]:
    m = STK_REGEX.match(text.strip())
    if not m:
        return None
    direction, qty_str, symbol, price_str = m.groups()
    
    price = float(price_str)
    
    # Calculate quantity if not specified
    if qty_str is None:
        if price <= 0:
            print(f"[AUTO-QTY] ✗ Invalid stock price: ${price}, skipping auto-calculation")
            return None
        qty = max(1, int(MAX_POSITION_SIZE / price))
        print(f"[AUTO-QTY] Stock: ${price}/share, buying {qty} shares (max ${MAX_POSITION_SIZE})")
    else:
        qty = int(qty_str)
    
    return {
        "asset": "stock",
        "action": direction.upper(),
        "qty": qty,
        "symbol": symbol.upper(),
        "price": price,
    }

# ------------------------------ DISCORD SELF-BOT -------------------------------------
class SelfClient(discord.Client):
    def __init__(self, **kwargs):
        # Ensure intents are set for compatibility with newer discord.py-self versions
        # Older versions (like on Replit) don't have Intents, newer versions require it
        if 'intents' not in kwargs and hasattr(discord, 'Intents'):
            intents = discord.Intents.default()
            intents.guilds = True
            intents.messages = True
            intents.message_content = True
            kwargs['intents'] = intents
        
        super().__init__(**kwargs)
        self.order_queue: asyncio.Queue = asyncio.Queue()
        self.broker: Optional[WebullBroker] = None
        self.broker_ready = asyncio.Event()
        self.processing_ready = asyncio.Event()

    async def setup(self):
        self.broker = WebullBroker(loop=self.loop)
        try:
            await self.broker.login()
            print("[Webull] ✓ Login successful")
            self.broker_ready.set()
        except Exception as e:
            print("[Webull] ✗ Login failed:", e)
            return

        self.loop.create_task(self.worker())
        self.processing_ready.set()
        print("[Init] ✓ Worker started; processing signals.")
        
        # Start position monitoring for risk management
        if ENABLE_RISK_MGMT:
            self.loop.create_task(self.broker.monitor_positions(self.order_queue))
        else:
            print("[Init] Position monitoring disabled (enable_risk_management = false)")

    async def on_ready(self):
        print(f"\n[Discord] ✓ Logged in as {self.user} (id={self.user.id})")

        print("[Discord] ✓ Monitoring channels:")
        for cid in CHANNEL_IDS:
            channel = self.get_channel(cid)
            if channel:
                if hasattr(channel, 'guild') and channel.guild:
                    print(f"  - #{channel.name} in {channel.guild.name}")
                else:
                    print(f"  - DM: {channel}")
            else:
                print(f"  - Channel ID {cid} (not found - bot may not have access)")
        print()

        await self.setup()

    async def on_message(self, message: discord.Message):
        # Silently ignore messages from channels not in monitored list
        if message.channel.id not in CHANNEL_IDS:
            return
        
        # Now log only messages from monitored channels
        print(f"\n[MSG] Channel:{message.channel.id} Author:{message.author.name} (ID:{message.author.id})")
        print(f"[MSG] Content: {message.content[:150]}")

        if message.author.id == self.user.id and not ALLOW_SELF_MESSAGES:
            print(f"[SKIP] Ignoring own message (set allow_self_messages=true in config to enable testing)")
            return
        
        if ALLOWED_AUTHOR_IDS and message.author.id not in ALLOWED_AUTHOR_IDS:
            print(f"[SKIP] Author {message.author.id} not in allowed list")
            return
        
        if ALLOWED_GUILD_IDS and hasattr(message, 'guild') and message.guild:
            if message.guild.id not in ALLOWED_GUILD_IDS:
                print(f"[SKIP] Guild {message.guild.id} not in allowed list")
                return

        if message.content.strip().lower() == "ping":
            try:
                await message.channel.send("pong")
            except Exception:
                pass
            return

        first_line = message.content.strip().split('\n')[0]

        sig = parse_option_signal(first_line)
        if not sig:
            sig = parse_stock_signal(first_line)

        if sig:
            print(f"[PARSE] ✓ Signal detected: {sig}")
        else:
            print(f"[PARSE] ✗ Could not parse: '{first_line}'")

        if sig:
            await self.order_queue.put((message.channel.id, sig))
            print(f"[QUEUE] ✓ Signal added to queue")

    async def worker(self):
        while True:
            ch_id, sig = await self.order_queue.get()
            try:
                if not self.broker or not self.broker_ready.is_set():
                    raise RuntimeError("Broker not ready")

                if sig['asset'] == 'option' and sig['action'] in ('BTO','STC'):
                    print(f"\n[Order] Placing OPTION order: {sig}")
                    resp = await self.broker.place_option_order(
                        action=sig['action'],
                        qty=sig['qty'],
                        symbol=sig['symbol'],
                        strike=sig['strike'],
                        opt_type=sig['opt_type'],
                        expiry_mmdd=sig['expiry'],
                        limit_price=sig['price'],
                        expiry_year=sig.get('expiry_year')  # Optional: for LEAPS support
                    )
                    print("[Order] ✓ Option order response:", resp)

                elif sig['asset'] == 'stock' and sig['action'] in ('BTO','STC'):
                    print(f"\n[Order] Placing STOCK order: {sig}")
                    resp = await self.broker.place_stock_order(
                        action=sig['action'],
                        qty=sig['qty'],
                        symbol=sig['symbol'],
                        limit_price=sig['price']
                    )
                    print("[Order] ✓ Stock order response:", resp)

                else:
                    print("[Skip] Unsupported signal:", sig)

            except Exception as e:
                print("[Order] ✗ ERROR:", e)
                import traceback
                traceback.print_exc()
            finally:
                self.order_queue.task_done()

# -------------------------------------- MAIN -----------------------------------------
if __name__ == "__main__":
    try:
        print("\n" + "="*60)
        print("DISCORD SELF-BOT WITH WEBULL INTEGRATION")
        print("Lowercase c/p support enabled")
        print("="*60 + "\n")

        client = SelfClient()
        client.run(USER_TOKEN)
    
    except KeyboardInterrupt:
        print("\n[EXIT] Bot stopped by user (Ctrl+C)")
    
    except Exception as e:
        print("\n" + "="*60)
        print("FATAL ERROR - Bot could not start!")
        print("="*60)
        print(f"\nError: {e}\n")
        import traceback
        traceback.print_exc()
        print("\n" + "="*60)
        print("Common fixes:")
        print("  1. Make sure config.ini exists in the same folder")
        print("  2. Check that Discord token is valid")
        print("  3. Verify Webull credentials are correct")
        print("  4. Try running setup wizard again")
        print("="*60 + "\n")
        
        # Pause so user can read the error (only when running as EXE)
        import sys
        if getattr(sys, 'frozen', False):
            # Running as EXE
            input("Press Enter to exit...")
        raise
