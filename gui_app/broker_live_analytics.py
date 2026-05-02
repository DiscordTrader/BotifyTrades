"""
Broker Live Analytics Service
Fetches real-time positions, trades, and calculates PNL directly from brokerage accounts.
Supports Webull Live, Webull Paper, Alpaca Live, Alpaca Paper, and IBKR.
"""

import asyncio
import sys
import os
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from webull import webull, paper_webull
except ImportError:
    webull = None
    paper_webull = None

try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import GetOrdersRequest
    from alpaca.trading.enums import QueryOrderStatus, OrderSide, OrderStatus
except ImportError:
    TradingClient = None
    GetOrdersRequest = None
    QueryOrderStatus = None


class BrokerLiveAnalytics:
    """Service for fetching real-time analytics from broker accounts"""
    
    BROKER_CONFIGS = {
        'webull_live': {'name': 'Webull Live', 'type': 'webull', 'paper': False},
        'alpaca_live': {'name': 'Alpaca Live', 'type': 'alpaca', 'paper': False},
        'alpaca_paper': {'name': 'Alpaca Paper', 'type': 'alpaca', 'paper': True},
        'tastytrade_live': {'name': 'Tastytrade Live', 'type': 'tastytrade', 'paper': False},
        'tastytrade_paper': {'name': 'Tastytrade Paper', 'type': 'tastytrade', 'paper': True},
        'ibkr_live': {'name': 'IBKR Live', 'type': 'ibkr', 'paper': False},
        'ibkr_paper': {'name': 'IBKR Paper', 'type': 'ibkr', 'paper': True},
        'schwab_live': {'name': 'Schwab Live', 'type': 'schwab', 'paper': False},
        'schwab_paper': {'name': 'Schwab Paper', 'type': 'schwab', 'paper': True},
        'robinhood': {'name': 'Robinhood', 'type': 'robinhood', 'paper': False},
    }
    
    def __init__(self):
        self._clients = {}
        self._cached_data = {}
        self._cache_timestamps = {}
        self._cache_duration = 30  # Cache for 30 seconds
        
    def _get_credentials(self, broker_id: str) -> Dict[str, Any]:
        """Get stored credentials for a broker with environment-specific handling"""
        from .broker_credentials_service import (
            get_webull_credentials, 
            get_alpaca_credentials
        )
        from .database import Database
        
        config = self.BROKER_CONFIGS.get(broker_id, {})
        broker_type = config.get('type', '')
        is_paper = config.get('paper', True)
        
        if broker_type == 'webull':
            creds = get_webull_credentials()
            creds['paper_mode'] = is_paper
            return creds
        elif broker_type == 'alpaca':
            base_creds = get_alpaca_credentials()
            if is_paper:
                db = Database()
                paper_key = db.get_setting('alpaca_paper_api_key', base_creds.get('api_key', ''))
                paper_secret = db.get_setting('alpaca_paper_secret_key', base_creds.get('secret_key', ''))
                return {
                    'api_key': paper_key or base_creds.get('api_key', ''),
                    'secret_key': paper_secret or base_creds.get('secret_key', ''),
                    'paper_mode': True
                }
            else:
                db = Database()
                live_key = db.get_setting('alpaca_live_api_key', '')
                live_secret = db.get_setting('alpaca_live_secret_key', '')
                return {
                    'api_key': live_key or base_creds.get('api_key', ''),
                    'secret_key': live_secret or base_creds.get('secret_key', ''),
                    'paper_mode': False
                }
        elif broker_type == 'tastytrade':
            from .broker_credentials_service import get_tastytrade_credentials
            creds = get_tastytrade_credentials()
            creds['paper_mode'] = is_paper
            return creds
        elif broker_type == 'ibkr':
            from .broker_credentials_service import get_ibkr_credentials
            creds = get_ibkr_credentials()
            creds['paper_mode'] = is_paper
            return creds
        elif broker_type == 'schwab':
            try:
                from .broker_credentials_service import get_schwab_credentials
                creds = get_schwab_credentials()
                creds['paper_mode'] = is_paper
                return creds
            except (ImportError, Exception):
                db = Database()
                return {
                    'client_id': db.get_setting('schwab_client_id', ''),
                    'client_secret': db.get_setting('schwab_client_secret', ''),
                    'redirect_uri': db.get_setting('schwab_redirect_uri', 'https://127.0.0.1'),
                    'paper_mode': is_paper,
                    'dry_run': is_paper
                }
        elif broker_type == 'robinhood':
            try:
                from .broker_credentials_service import get_robinhood_credentials
                return get_robinhood_credentials()
            except (ImportError, Exception):
                return {}
        return {}
    
    def _is_cache_valid(self, broker_id: str) -> bool:
        """Check if cached data is still valid"""
        if broker_id not in self._cache_timestamps:
            return False
        elapsed = (datetime.now() - self._cache_timestamps[broker_id]).total_seconds()
        return elapsed < self._cache_duration
    
    async def connect_webull(self, broker_id: str, credentials: Dict) -> Optional[Any]:
        """Connect to Webull account"""
        if webull is None:
            return None
        
        if not credentials:
            print(f"[ANALYTICS] No credentials for {broker_id}")
            return None
            
        try:
            config = self.BROKER_CONFIGS.get(broker_id, {})
            is_paper = config.get('paper', True)
            
            if is_paper:
                wb = paper_webull()
            else:
                wb = webull()
            
            access_token = credentials.get('access_token')
            refresh_token = credentials.get('refresh_token')
            device_id = credentials.get('device_id')
            
            if not access_token and not refresh_token and not credentials.get('email'):
                print(f"[ANALYTICS] Webull credentials not configured for {broker_id}")
                return None
            
            if access_token and refresh_token:
                wb.access_token = access_token
                wb.refresh_token = refresh_token
                if device_id:
                    wb.did = device_id
                
                try:
                    from src.services.webull_data_hub import get_webull_data_hub
                    hub = get_webull_data_hub()
                    cached = hub.get_account_info(max_age_seconds=300)
                    if cached and isinstance(cached, dict) and not cached.get('code'):
                        self._clients[broker_id] = wb
                        return wb
                except Exception:
                    pass
                account = await asyncio.to_thread(wb.get_account)
                if account:
                    self._clients[broker_id] = wb
                    return wb
            
            email = credentials.get('email')
            password = credentials.get('password')
            
            if email and password:
                result = await asyncio.to_thread(wb.login, email, password)
                if result:
                    self._clients[broker_id] = wb
                    return wb
                    
            return None
            
        except Exception as e:
            print(f"[ANALYTICS] Error connecting to {broker_id}: {e}")
            return None
    
    async def connect_alpaca(self, broker_id: str, credentials: Dict) -> Optional[Any]:
        """Connect to Alpaca account"""
        if TradingClient is None:
            return None
            
        try:
            config = self.BROKER_CONFIGS.get(broker_id, {})
            is_paper = config.get('paper', True)
            
            api_key = credentials.get('api_key')
            secret_key = credentials.get('secret_key')
            
            if not api_key or not secret_key:
                return None
            
            client = TradingClient(
                api_key=api_key,
                secret_key=secret_key,
                paper=is_paper
            )
            
            account = await asyncio.to_thread(client.get_account)
            if account:
                self._clients[broker_id] = client
                return client
                
            return None
            
        except Exception as e:
            print(f"[ANALYTICS] Error connecting to {broker_id}: {e}")
            return None
    
    async def connect_ibkr(self, broker_id: str, credentials: Dict) -> Optional[Any]:
        """Connect to Interactive Brokers account"""
        try:
            from src.brokers.ibkr_broker import IBKRBroker
        except ImportError:
            print(f"[ANALYTICS] IBKR broker module not available")
            return None
            
        try:
            config = self.BROKER_CONFIGS.get(broker_id, {})
            is_paper = config.get('paper', True)
            
            host = credentials.get('host', '127.0.0.1')
            port = credentials.get('port', 7497 if is_paper else 7496)
            client_id = credentials.get('client_id', 1)
            
            if not host or not port:
                print(f"[ANALYTICS] IBKR credentials not configured for {broker_id}")
                return None
            
            broker = IBKRBroker(
                host=host,
                port=int(port),
                client_id=int(client_id),
                paper_trade=is_paper
            )
            
            connected = await broker.connect()
            if connected:
                self._clients[broker_id] = broker
                return broker
                
            return None
            
        except Exception as e:
            print(f"[ANALYTICS] Error connecting to {broker_id}: {e}")
            return None
    
    async def connect_tastytrade(self, broker_id: str, credentials: Dict) -> Optional[Any]:
        """Connect to Tastytrade account"""
        try:
            from src.brokers.tastytrade_broker import TastytradeBroker
        except ImportError:
            print(f"[ANALYTICS] Tastytrade broker module not available")
            return None
            
        try:
            config = self.BROKER_CONFIGS.get(broker_id, {})
            is_paper = config.get('paper', True)
            
            username = credentials.get('username', '')
            password = credentials.get('password', '')
            client_id = credentials.get('client_id', '')
            client_secret = credentials.get('client_secret', '')
            refresh_token = credentials.get('refresh_token', '')
            
            if not ((username and password) or (client_id and client_secret and refresh_token)):
                print(f"[ANALYTICS] Tastytrade credentials not configured for {broker_id}")
                return None
            
            broker_config = {
                'username': username,
                'password': password,
                'client_id': client_id,
                'client_secret': client_secret,
                'refresh_token': refresh_token,
                'paper_trade': is_paper
            }
            
            broker = TastytradeBroker(broker_config)
            await broker.connect()
            self._clients[broker_id] = broker
            return broker
            
        except Exception as e:
            print(f"[ANALYTICS] Error connecting to {broker_id}: {e}")
            return None
    
    async def connect_schwab(self, broker_id: str, credentials: Dict) -> Optional[Any]:
        """Connect to Schwab account"""
        try:
            from src.brokers.schwab_broker import SchwabBroker
        except ImportError:
            print(f"[ANALYTICS] Schwab broker module not available")
            return None
        
        try:
            config = self.BROKER_CONFIGS.get(broker_id, {})
            is_paper = config.get('paper', True)
            
            broker_config = {
                'client_id': credentials.get('client_id', ''),
                'client_secret': credentials.get('client_secret', ''),
                'redirect_uri': credentials.get('redirect_uri', 'https://127.0.0.1'),
                'dry_run': is_paper
            }
            
            if not broker_config['client_id'] or not broker_config['client_secret']:
                print(f"[ANALYTICS] Schwab credentials not configured for {broker_id}")
                return None
            
            broker = SchwabBroker(broker_config)
            connected = await broker.connect()
            if connected:
                self._clients[broker_id] = broker
                return broker
            
            return None
        except Exception as e:
            print(f"[ANALYTICS] Error connecting to {broker_id}: {e}")
            return None
    
    async def connect_robinhood(self, broker_id: str, credentials: Dict) -> Optional[Any]:
        """Connect to Robinhood account - uses existing bot instance"""
        try:
            from gui_app.routes import _bot_instance
            if _bot_instance and hasattr(_bot_instance, 'robinhood_broker') and _bot_instance.robinhood_broker:
                self._clients[broker_id] = _bot_instance.robinhood_broker
                return _bot_instance.robinhood_broker
        except Exception as e:
            print(f"[ANALYTICS] Error connecting to {broker_id}: {e}")
        return None
    
    async def get_client(self, broker_id: str) -> Optional[Any]:
        """Get or create client for broker"""
        if broker_id in self._clients:
            return self._clients[broker_id]
            
        credentials = self._get_credentials(broker_id)
        config = self.BROKER_CONFIGS.get(broker_id, {})
        broker_type = config.get('type', '')
        
        if broker_type == 'webull':
            return await self.connect_webull(broker_id, credentials)
        elif broker_type == 'alpaca':
            return await self.connect_alpaca(broker_id, credentials)
        elif broker_type == 'ibkr':
            return await self.connect_ibkr(broker_id, credentials)
        elif broker_type == 'tastytrade':
            return await self.connect_tastytrade(broker_id, credentials)
        elif broker_type == 'schwab':
            return await self.connect_schwab(broker_id, credentials)
        elif broker_type == 'robinhood':
            return await self.connect_robinhood(broker_id, credentials)
        
        return None
    
    async def get_account_info(self, broker_id: str) -> Dict[str, Any]:
        """Get account information from broker"""
        config = self.BROKER_CONFIGS.get(broker_id, {})
        broker_type = config.get('type', '')
        client = await self.get_client(broker_id)
        
        if not client:
            return {
                'connected': False,
                'error': 'Unable to connect to broker',
                'buying_power': 0,
                'cash': 0,
                'portfolio_value': 0,
                'day_pnl': 0,
                'day_pnl_percent': 0
            }
        
        try:
            if broker_type == 'webull':
                account = await asyncio.to_thread(client.get_account)
                if account:
                    buying_power = 0
                    for field in ['usableCash', 'dayBuyingPower', 'buyingPower']:
                        if field in account:
                            try:
                                buying_power = float(account[field])
                                if buying_power > 0:
                                    break
                            except:
                                pass
                    
                    portfolio_value = 0
                    for field in ['netLiquidation', 'totalAccountValue', 'accountValue']:
                        if field in account:
                            try:
                                portfolio_value = float(account[field])
                                if portfolio_value > 0:
                                    break
                            except:
                                pass
                    
                    day_pnl = float(account.get('dayProfitLoss', 0) or 0)
                    
                    return {
                        'connected': True,
                        'buying_power': buying_power,
                        'cash': float(account.get('cashBalance', 0) or 0),
                        'portfolio_value': portfolio_value,
                        'day_pnl': day_pnl,
                        'day_pnl_percent': (day_pnl / portfolio_value * 100) if portfolio_value > 0 else 0
                    }
                    
            elif broker_type == 'alpaca':
                account = await asyncio.to_thread(client.get_account)
                if account:
                    portfolio_value = float(account.portfolio_value)
                    last_equity = float(account.last_equity) if hasattr(account, 'last_equity') else portfolio_value
                    day_pnl = portfolio_value - last_equity
                    
                    return {
                        'connected': True,
                        'buying_power': float(account.buying_power),
                        'cash': float(account.cash),
                        'portfolio_value': portfolio_value,
                        'day_pnl': day_pnl,
                        'day_pnl_percent': (day_pnl / last_equity * 100) if last_equity > 0 else 0
                    }
                    
            elif broker_type == 'ibkr':
                account = await client.get_account_info()
                if account:
                    portfolio_value = float(account.get('net_liquidation', 0) or 0)
                    buying_power = float(account.get('buying_power', 0) or 0)
                    cash = float(account.get('cash_balance', 0) or 0)
                    day_pnl = float(account.get('day_profit_loss', 0) or 0)
                    
                    return {
                        'connected': True,
                        'buying_power': buying_power,
                        'cash': cash,
                        'portfolio_value': portfolio_value,
                        'day_pnl': day_pnl,
                        'day_pnl_percent': (day_pnl / portfolio_value * 100) if portfolio_value > 0 else 0
                    }
                    
            elif broker_type == 'tastytrade':
                account = await client.get_account_info()
                if account:
                    portfolio_value = float(account.get('portfolio_value', 0) or 0)
                    buying_power = float(account.get('buying_power', 0) or account.get('options_buying_power', 0) or 0)
                    cash = float(account.get('cash', 0) or 0)
                    day_pnl = float(account.get('day_profit_loss', 0) or 0)
                    
                    return {
                        'connected': True,
                        'buying_power': buying_power,
                        'cash': cash,
                        'portfolio_value': portfolio_value,
                        'day_pnl': day_pnl,
                        'day_pnl_percent': (day_pnl / portfolio_value * 100) if portfolio_value > 0 else 0
                    }
            
            elif broker_type == 'schwab':
                account = await client.get_account_info()
                if account:
                    portfolio_value = float(account.get('portfolio_value', 0) or 0)
                    buying_power = float(account.get('buying_power', 0) or 0)
                    cash = float(account.get('cash', 0) or account.get('settled_cash', 0) or 0)
                    day_pnl = float(account.get('day_pnl', 0) or 0)
                    
                    return {
                        'connected': True,
                        'buying_power': buying_power,
                        'cash': cash,
                        'portfolio_value': portfolio_value,
                        'day_pnl': day_pnl,
                        'day_pnl_percent': (day_pnl / portfolio_value * 100) if portfolio_value > 0 else 0
                    }
                    
        except Exception as e:
            print(f"[ANALYTICS] Error getting account info for {broker_id}: {e}")
            return {
                'connected': False,
                'error': str(e),
                'buying_power': 0,
                'cash': 0,
                'portfolio_value': 0,
                'day_pnl': 0,
                'day_pnl_percent': 0
            }
            
        return {
            'connected': False,
            'error': 'Unknown error',
            'buying_power': 0,
            'cash': 0,
            'portfolio_value': 0,
            'day_pnl': 0,
            'day_pnl_percent': 0
        }
    
    async def get_open_positions(self, broker_id: str) -> List[Dict[str, Any]]:
        """Get all open positions from broker"""
        config = self.BROKER_CONFIGS.get(broker_id, {})
        broker_type = config.get('type', '')
        client = await self.get_client(broker_id)
        
        if not client:
            return []
        
        positions = []
        
        try:
            if broker_type == 'webull':
                raw_positions = await asyncio.to_thread(client.get_positions)
                
                for pos in raw_positions:
                    qty = float(pos.get('position', 0))
                    if qty <= 0:
                        continue
                        
                    symbol = pos.get('ticker', {}).get('symbol', '') or pos.get('symbol', '')
                    avg_cost = float(pos.get('costPrice', 0) or 0)
                    current_price = float(pos.get('latestPrice', 0) or pos.get('lastPrice', 0) or 0)
                    market_value = float(pos.get('marketValue', 0) or 0)
                    unrealized_pnl = float(pos.get('unrealizedProfitLoss', 0) or 0)
                    
                    if market_value > 0 and qty > 0 and current_price == 0:
                        current_price = market_value / qty
                    
                    pnl_percent = 0
                    if avg_cost > 0:
                        pnl_percent = ((current_price - avg_cost) / avg_cost) * 100
                    
                    is_option = (
                        'optionId' in pos or 
                        'strikePrice' in pos or 
                        pos.get('assetType', '').lower() in ('option', 'opt')
                    )
                    
                    position_data = {
                        'symbol': symbol,
                        'quantity': qty,
                        'avg_cost': avg_cost,
                        'current_price': current_price,
                        'market_value': market_value if market_value > 0 else (qty * current_price),
                        'unrealized_pnl': unrealized_pnl,
                        'pnl_percent': pnl_percent,
                        'asset_type': 'option' if is_option else 'stock'
                    }
                    
                    if is_option:
                        position_data['strike'] = float(pos.get('strikePrice', 0) or 0)
                        position_data['expiry'] = pos.get('expireDate', '')
                        position_data['option_type'] = 'CALL' if pos.get('direction', '').upper() == 'CALL' else 'PUT'
                    
                    positions.append(position_data)
                    
            elif broker_type == 'alpaca':
                raw_positions = await asyncio.to_thread(client.get_all_positions)
                
                for pos in raw_positions:
                    qty = float(pos.qty)
                    avg_cost = float(pos.avg_entry_price)
                    current_price = float(pos.current_price)
                    market_value = float(pos.market_value)
                    unrealized_pnl = float(pos.unrealized_pl)
                    pnl_percent = float(pos.unrealized_plpc) * 100
                    
                    is_option = hasattr(pos, 'asset_class') and pos.asset_class == 'us_option'
                    
                    position_data = {
                        'symbol': pos.symbol,
                        'quantity': qty,
                        'avg_cost': avg_cost,
                        'current_price': current_price,
                        'market_value': market_value,
                        'unrealized_pnl': unrealized_pnl,
                        'pnl_percent': pnl_percent,
                        'asset_type': 'option' if is_option else 'stock',
                        'side': pos.side
                    }
                    
                    positions.append(position_data)
            
            elif broker_type == 'schwab':
                raw_positions = await client.get_positions_detailed()
                for pos in raw_positions:
                    qty = float(pos.get('quantity', 0))
                    if qty == 0:
                        continue
                    
                    avg_cost = float(pos.get('avg_cost', 0))
                    current_price = float(pos.get('current_price', 0))
                    unrealized_pnl = float(pos.get('unrealized_pl', 0))
                    pnl_percent = ((current_price - avg_cost) / avg_cost * 100) if avg_cost > 0 else 0
                    
                    is_option = pos.get('asset') == 'option'
                    
                    position_data = {
                        'symbol': pos.get('symbol', ''),
                        'quantity': qty,
                        'avg_cost': avg_cost,
                        'current_price': current_price,
                        'market_value': qty * current_price * (100 if is_option else 1),
                        'unrealized_pnl': unrealized_pnl,
                        'pnl_percent': pnl_percent,
                        'asset_type': 'option' if is_option else 'stock'
                    }
                    
                    if is_option:
                        position_data['strike'] = pos.get('strike', 0)
                        position_data['expiry'] = pos.get('expiry', '')
                        position_data['option_type'] = 'CALL' if pos.get('direction', '') == 'C' else 'PUT'
                    
                    positions.append(position_data)
            
            elif broker_type == 'ibkr':
                raw_positions = await client.get_positions_detailed()
                for pos in raw_positions:
                    qty = float(pos.get('quantity', 0))
                    if qty == 0:
                        continue

                    avg_cost = float(pos.get('avg_cost', 0))
                    current_price = float(pos.get('current_price', 0))
                    unrealized_pnl = float(pos.get('unrealized_pl', 0))
                    pnl_percent = ((current_price - avg_cost) / avg_cost * 100) if avg_cost > 0 else 0

                    is_option = pos.get('asset') == 'option'

                    position_data = {
                        'symbol': pos.get('symbol', ''),
                        'quantity': qty,
                        'avg_cost': avg_cost,
                        'current_price': current_price,
                        'market_value': qty * current_price * (100 if is_option else 1),
                        'unrealized_pnl': unrealized_pnl,
                        'pnl_percent': pnl_percent,
                        'asset_type': 'option' if is_option else 'stock'
                    }

                    if is_option:
                        position_data['strike'] = pos.get('strike', 0)
                        position_data['expiry'] = pos.get('expiry', '')
                        position_data['option_type'] = 'CALL' if pos.get('direction', '') == 'C' else 'PUT'

                    positions.append(position_data)

            elif broker_type == 'robinhood':
                if hasattr(client, 'get_all_positions'):
                    raw_positions = client.get_all_positions()
                    for pos in raw_positions:
                        qty = float(pos.get('quantity', 0))
                        if qty == 0:
                            continue

                        avg_cost = float(pos.get('avg_price') or pos.get('average_buy_price') or 0)
                        current_price = float(pos.get('current_price', 0))
                        unrealized_pnl = float(pos.get('unrealized_pnl', 0))
                        pnl_percent = ((current_price - avg_cost) / avg_cost * 100) if avg_cost > 0 else 0

                        positions.append({
                            'symbol': pos.get('symbol', ''),
                            'quantity': qty,
                            'avg_cost': avg_cost,
                            'current_price': current_price,
                            'market_value': qty * current_price,
                            'unrealized_pnl': unrealized_pnl,
                            'pnl_percent': pnl_percent,
                            'asset_type': pos.get('asset_type') or 'stock'
                        })
                    
        except Exception as e:
            print(f"[ANALYTICS] Error getting positions for {broker_id}: {e}")
            import traceback
            traceback.print_exc()
            
        return positions
    
    async def get_closed_trades(self, broker_id: str, days: int = 30) -> List[Dict[str, Any]]:
        """Get closed/filled orders from broker for PNL calculation"""
        config = self.BROKER_CONFIGS.get(broker_id, {})
        broker_type = config.get('type', '')
        client = await self.get_client(broker_id)
        
        if not client:
            return []
        
        trades = []
        start_date = datetime.now() - timedelta(days=days)
        
        try:
            if broker_type == 'webull':
                # Get ALL orders (not just 'Filled') to capture partial fills, pending, etc.
                all_statuses = ['Filled', 'Working', 'Cancelled', 'Partially Filled', 'Pending']
                history = []
                for status in all_statuses:
                    try:
                        orders = await asyncio.to_thread(client.get_history_orders, status=status)
                        if orders:
                            history.extend(orders)
                    except:
                        pass
                
                if history:
                    for order in history:
                        filled_time = order.get('filledTime', order.get('createTime', ''))
                        
                        if filled_time:
                            try:
                                if 'T' in filled_time:
                                    order_date = datetime.fromisoformat(filled_time.replace('Z', '+00:00'))
                                else:
                                    order_date = datetime.strptime(filled_time[:10], '%Y-%m-%d')
                                    
                                if order_date.replace(tzinfo=None) < start_date:
                                    continue
                            except:
                                pass
                        
                        symbol = order.get('ticker', {}).get('symbol', '')
                        action = order.get('action', '')
                        qty = float(order.get('filledQuantity', order.get('totalQuantity', 0)) or 0)
                        price = float(order.get('avgFilledPrice', order.get('lmtPrice', 0)) or 0)
                        
                        trades.append({
                            'order_id': str(order.get('orderId', '')),
                            'symbol': symbol,
                            'action': action,
                            'quantity': qty,
                            'price': price,
                            'total_value': qty * price,
                            'filled_time': filled_time,
                            'order_type': order.get('orderType', 'MARKET'),
                            'status': 'FILLED'
                        })
                        
            elif broker_type == 'alpaca':
                request = GetOrdersRequest(
                    status=QueryOrderStatus.CLOSED,
                    after=start_date.isoformat()
                )
                orders = await asyncio.to_thread(client.get_orders, filter=request)
                
                for order in orders:
                    if order.status != OrderStatus.FILLED:
                        continue
                        
                    trades.append({
                        'order_id': str(order.id),
                        'symbol': order.symbol,
                        'action': 'BUY' if order.side == OrderSide.BUY else 'SELL',
                        'quantity': float(order.filled_qty),
                        'price': float(order.filled_avg_price) if order.filled_avg_price else 0,
                        'total_value': float(order.filled_qty) * float(order.filled_avg_price or 0),
                        'filled_time': order.filled_at.isoformat() if order.filled_at else '',
                        'order_type': str(order.type),
                        'status': 'FILLED'
                    })
                    
        except Exception as e:
            print(f"[ANALYTICS] Error getting closed trades for {broker_id}: {e}")
            import traceback
            traceback.print_exc()
            
        return trades
    
    def calculate_pnl_from_trades(self, trades: List[Dict]) -> Dict[str, Any]:
        """Calculate PNL from trade history using FIFO matching"""
        symbol_lots = defaultdict(list)  # Open lots per symbol
        closed_trades = []
        
        sorted_trades = sorted(trades, key=lambda x: x.get('filled_time', ''))
        
        for trade in sorted_trades:
            symbol = trade['symbol']
            action = trade['action'].upper()
            qty = trade['quantity']
            price = trade['price']
            
            if action in ('BUY', 'BTO'):
                symbol_lots[symbol].append({
                    'quantity': qty,
                    'price': price,
                    'time': trade.get('filled_time', '')
                })
            elif action in ('SELL', 'STC'):
                remaining_qty = qty
                realized_pnl = 0
                
                while remaining_qty > 0 and symbol_lots[symbol]:
                    lot = symbol_lots[symbol][0]
                    
                    if lot['quantity'] <= remaining_qty:
                        realized_pnl += (price - lot['price']) * lot['quantity']
                        remaining_qty -= lot['quantity']
                        symbol_lots[symbol].pop(0)
                    else:
                        realized_pnl += (price - lot['price']) * remaining_qty
                        lot['quantity'] -= remaining_qty
                        remaining_qty = 0
                
                closed_trades.append({
                    'symbol': symbol,
                    'quantity': qty,
                    'sell_price': price,
                    'realized_pnl': realized_pnl,
                    'time': trade.get('filled_time', '')
                })
        
        total_pnl = sum(t['realized_pnl'] for t in closed_trades)
        winners = [t for t in closed_trades if t['realized_pnl'] > 0]
        losers = [t for t in closed_trades if t['realized_pnl'] < 0]
        
        win_rate = (len(winners) / len(closed_trades) * 100) if closed_trades else 0
        avg_win = (sum(t['realized_pnl'] for t in winners) / len(winners)) if winners else 0
        avg_loss = (sum(t['realized_pnl'] for t in losers) / len(losers)) if losers else 0
        profit_factor = abs(sum(t['realized_pnl'] for t in winners) / sum(t['realized_pnl'] for t in losers)) if losers and sum(t['realized_pnl'] for t in losers) != 0 else 0
        
        return {
            'total_pnl': total_pnl,
            'total_trades': len(closed_trades),
            'winners': len(winners),
            'losers': len(losers),
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'closed_trades': closed_trades
        }
    
    def aggregate_daily_pnl(self, closed_trades: List[Dict]) -> List[Dict]:
        """Aggregate PNL by day"""
        daily_pnl = defaultdict(float)
        
        for trade in closed_trades:
            time_str = trade.get('time', '')
            if time_str:
                try:
                    if 'T' in time_str:
                        date = time_str.split('T')[0]
                    else:
                        date = time_str[:10]
                    daily_pnl[date] += trade.get('realized_pnl', 0)
                except:
                    pass
        
        result = [{'date': date, 'pnl': pnl} for date, pnl in sorted(daily_pnl.items())]
        return result
    
    def aggregate_period_pnl(self, daily_data: List[Dict], period: str = 'weekly') -> List[Dict]:
        """Aggregate daily PNL into weekly/monthly/yearly"""
        period_pnl = defaultdict(float)
        
        for item in daily_data:
            date_str = item['date']
            pnl = item['pnl']
            
            try:
                date = datetime.strptime(date_str, '%Y-%m-%d')
                
                if period == 'weekly':
                    key = date.strftime('%Y-W%W')
                elif period == 'monthly':
                    key = date.strftime('%Y-%m')
                elif period == 'yearly':
                    key = date.strftime('%Y')
                else:
                    key = date_str
                    
                period_pnl[key] += pnl
            except:
                pass
        
        return [{'period': k, 'pnl': v} for k, v in sorted(period_pnl.items())]
    
    async def get_full_analytics(self, broker_id: str, days: int = 30) -> Dict[str, Any]:
        """Get comprehensive analytics for a broker account"""
        if self._is_cache_valid(broker_id) and broker_id in self._cached_data:
            cached = self._cached_data[broker_id]
            if cached.get('days') == days:
                return cached
        
        account_info = await self.get_account_info(broker_id)
        
        if not account_info.get('connected'):
            return {
                'connected': False,
                'error': account_info.get('error', 'Not connected'),
                'broker_id': broker_id,
                'broker_name': self.BROKER_CONFIGS.get(broker_id, {}).get('name', broker_id)
            }
        
        positions = await self.get_open_positions(broker_id)
        trades = await self.get_closed_trades(broker_id, days)
        pnl_stats = self.calculate_pnl_from_trades(trades)
        daily_pnl = self.aggregate_daily_pnl(pnl_stats['closed_trades'])
        weekly_pnl = self.aggregate_period_pnl(daily_pnl, 'weekly')
        monthly_pnl = self.aggregate_period_pnl(daily_pnl, 'monthly')
        
        # Enrich positions and trades with source_display for UI badges
        from .database import get_trade_source_display, find_open_bto_trade, get_channel_by_discord_id
        broker_config = self.BROKER_CONFIGS.get(broker_id, {})
        broker_name = broker_config.get('name', 'Broker')
        
        # Map broker_id to broker name for database lookup
        broker_name_map = {
            'webull_live': 'Webull',
            'alpaca_live': 'Alpaca',
            'alpaca_paper': 'Alpaca',
            'ibkr_live': 'IBKR',
            'ibkr_paper': 'IBKR'
        }
        db_broker_name = broker_name_map.get(broker_id, broker_name)
        
        # For broker-fetched data, create a "from broker" source display (fallback)
        broker_source = {
            'name': broker_name,
            'type': 'sync',
            'color': 'gray',
            'icon': '🔄',
            'full_name': f'Position from {broker_name}'
        }
        
        for pos in positions:
            # Try to find matching trade in database for source info (channel name)
            try:
                symbol = pos.get('symbol', '')
                asset_type = pos.get('asset_type', 'stock')
                strike = pos.get('strike')
                expiry = pos.get('expiry')
                call_put = pos.get('option_type', '')[0].upper() if pos.get('option_type') else None
                
                # Find matching open BTO trade in database
                matching_trade = find_open_bto_trade(
                    symbol=symbol,
                    asset_type=asset_type,
                    broker=db_broker_name,
                    strike=strike,
                    expiry=expiry,
                    call_put=call_put
                )
                
                if matching_trade:
                    if matching_trade.get('channel_id'):
                        # Get channel info for display (use Discord channel ID lookup)
                        channel_info = get_channel_by_discord_id(matching_trade['channel_id'])
                        if channel_info:
                            channel_name = channel_info.get('name', 'Unknown')
                            if channel_info.get('execute_enabled'):
                                pos['source_display'] = {
                                    'name': f'#{channel_name}',
                                    'type': 'execute',
                                    'color': 'blue',
                                    'icon': '🎯',
                                    'full_name': f'Executed from #{channel_name}'
                                }
                            elif channel_info.get('track_enabled'):
                                pos['source_display'] = {
                                    'name': f'#{channel_name}',
                                    'type': 'track',
                                    'color': 'purple',
                                    'icon': '👁️',
                                    'full_name': f'Tracked from #{channel_name}'
                                }
                            else:
                                pos['source_display'] = {
                                    'name': f'#{channel_name}',
                                    'type': 'channel',
                                    'color': 'green',
                                    'icon': '#',
                                    'full_name': f'From #{channel_name}'
                                }
                        else:
                            # Channel not found, use trade source display
                            pos['source_display'] = get_trade_source_display(matching_trade)
                    else:
                        # Trade exists but no channel - use proper source display (GUI, risk exit, etc.)
                        pos['source_display'] = get_trade_source_display(matching_trade)
                else:
                    pos['source_display'] = broker_source
            except Exception as e:
                print(f"[ANALYTICS] Error matching position to channel: {e}")
                pos['source_display'] = broker_source
            
        for trade in pnl_stats['closed_trades']:
            trade['source_display'] = trade.get('source_display') or broker_source
        
        total_unrealized = sum(p.get('unrealized_pnl', 0) for p in positions)
        
        top_symbols = defaultdict(float)
        for trade in pnl_stats['closed_trades']:
            top_symbols[trade['symbol']] += trade['realized_pnl']
        top_symbols_sorted = sorted(top_symbols.items(), key=lambda x: x[1], reverse=True)[:10]
        
        result = {
            'connected': True,
            'broker_id': broker_id,
            'broker_name': self.BROKER_CONFIGS.get(broker_id, {}).get('name', broker_id),
            'days': days,
            'timestamp': datetime.now().isoformat(),
            'account': account_info,
            'positions': {
                'open': positions,
                'count': len(positions),
                'total_value': sum(p.get('market_value', 0) for p in positions),
                'total_unrealized_pnl': total_unrealized
            },
            'performance': {
                'total_pnl': pnl_stats['total_pnl'],
                'realized_pnl': pnl_stats['total_pnl'],
                'unrealized_pnl': total_unrealized,
                'total_trades': pnl_stats['total_trades'],
                'winners': pnl_stats['winners'],
                'losers': pnl_stats['losers'],
                'win_rate': pnl_stats['win_rate'],
                'avg_win': pnl_stats['avg_win'],
                'avg_loss': pnl_stats['avg_loss'],
                'profit_factor': pnl_stats['profit_factor']
            },
            'charts': {
                'daily_pnl': daily_pnl,
                'weekly_pnl': weekly_pnl,
                'monthly_pnl': monthly_pnl,
                'equity_curve': self._build_equity_curve(daily_pnl, account_info.get('portfolio_value', 0))
            },
            'top_symbols': [{'symbol': s, 'pnl': p} for s, p in top_symbols_sorted],
            'recent_trades': pnl_stats['closed_trades'][-20:][::-1]
        }
        
        self._cached_data[broker_id] = result
        self._cache_timestamps[broker_id] = datetime.now()
        
        return result
    
    def _build_equity_curve(self, daily_pnl: List[Dict], current_value: float) -> List[Dict]:
        """Build equity curve from daily PNL"""
        if not daily_pnl:
            return []
        
        total_pnl = sum(d['pnl'] for d in daily_pnl)
        starting_value = current_value - total_pnl
        
        curve = []
        cumulative = starting_value
        
        for item in daily_pnl:
            cumulative += item['pnl']
            curve.append({
                'date': item['date'],
                'value': cumulative
            })
        
        return curve
    
    def get_available_brokers(self) -> List[Dict[str, str]]:
        """Get list of available broker configs"""
        return [
            {'id': k, 'name': v['name'], 'type': v['type'], 'paper': v['paper']}
            for k, v in self.BROKER_CONFIGS.items()
        ]


_analytics_service = None

def get_analytics_service() -> BrokerLiveAnalytics:
    """Get singleton analytics service instance"""
    global _analytics_service
    if _analytics_service is None:
        _analytics_service = BrokerLiveAnalytics()
    return _analytics_service
