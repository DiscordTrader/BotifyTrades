"""
Broker Manager - Handles multiple brokers and routing
"""

import re
from typing import Optional, Dict, Any, List
from src.broker_interface import BrokerInterface, OrderResult, BrokerFactory


class BrokerManager:
    """Manages multiple brokers and handles order routing"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.brokers: Dict[str, BrokerInterface] = {}
        self.default_broker: Optional[str] = None
        # Read selection method from [brokers] section
        brokers_config = config.get('brokers', {})
        self.selection_method = brokers_config.get('broker_selection_method', 'prefix').lower()  # prefix, channel, or default
        
    async def initialize(self):
        """Initialize all enabled brokers (both live and paper trading accounts)"""
        brokers_config = self.config.get('brokers', {})
        
        # Initialize Webull (Live)
        if brokers_config.get('enable_webull', True):
            try:
                webull_config = self.config.get('webull', {}).copy()
                webull_config['paper_trade'] = False
                webull_broker = BrokerFactory.create_broker('WEBULL', webull_config)
                if webull_broker and await webull_broker.connect():
                    self.brokers['WEBULL'] = webull_broker
                    print(f"[BROKER MANAGER] ✓ Webull LIVE initialized")
                else:
                    print(f"[BROKER MANAGER] ❌ Webull LIVE failed to connect")
            except Exception as e:
                print(f"[BROKER MANAGER] ❌ Webull LIVE error: {e}")
            
            # Initialize Webull Paper Trading
            try:
                webull_paper_config = self.config.get('webull', {}).copy()
                webull_paper_config['paper_trade'] = True
                webull_paper_broker = BrokerFactory.create_broker('WEBULL', webull_paper_config)
                if webull_paper_broker and await webull_paper_broker.connect():
                    self.brokers['WEBULL_PAPER'] = webull_paper_broker
                    print(f"[BROKER MANAGER] ✓ Webull PAPER initialized")
                else:
                    print(f"[BROKER MANAGER] ❌ Webull PAPER failed to connect")
            except Exception as e:
                print(f"[BROKER MANAGER] ❌ Webull PAPER error: {e}")
        
        # Initialize Alpaca (Live)
        if brokers_config.get('enable_alpaca', False):
            try:
                alpaca_config = self.config.get('alpaca', {}).copy()
                alpaca_config['paper_trade'] = False
                alpaca_broker = BrokerFactory.create_broker('ALPACA', alpaca_config)
                if alpaca_broker and await alpaca_broker.connect():
                    self.brokers['ALPACA'] = alpaca_broker
                    print(f"[BROKER MANAGER] ✓ Alpaca LIVE initialized")
                else:
                    print(f"[BROKER MANAGER] ❌ Alpaca LIVE failed to connect")
            except Exception as e:
                print(f"[BROKER MANAGER] ❌ Alpaca LIVE error: {e}")
            
            # Initialize Alpaca Paper Trading
            try:
                alpaca_paper_config = self.config.get('alpaca', {}).copy()
                alpaca_paper_config['paper_trade'] = True
                alpaca_paper_broker = BrokerFactory.create_broker('ALPACA', alpaca_paper_config)
                if alpaca_paper_broker and await alpaca_paper_broker.connect():
                    self.brokers['ALPACA_PAPER'] = alpaca_paper_broker
                    print(f"[BROKER MANAGER] ✓ Alpaca PAPER initialized")
                else:
                    print(f"[BROKER MANAGER] ❌ Alpaca PAPER failed to connect")
            except Exception as e:
                print(f"[BROKER MANAGER] ❌ Alpaca PAPER error: {e}")
        
        # Initialize IBKR (LIVE + PAPER)
        if brokers_config.get('enable_ibkr', False):
            # LIVE
            try:
                ibkr_live_config = self.config.get('ibkr', {}).copy()
                ibkr_live_config['paper_trade'] = False
                ibkr_live_broker = BrokerFactory.create_broker('IBKR', ibkr_live_config)
                if ibkr_live_broker and await ibkr_live_broker.connect():
                    self.brokers['IBKR'] = ibkr_live_broker
                    print(f"[BROKER MANAGER] ✓ IBKR LIVE initialized")
                else:
                    print(f"[BROKER MANAGER] ❌ IBKR LIVE failed to connect")
            except Exception as e:
                print(f"[BROKER MANAGER] ❌ IBKR LIVE error: {e}")

            # PAPER (use different client_id to avoid conflicts)
            try:
                ibkr_paper_config = self.config.get('ibkr', {}).copy()
                ibkr_paper_config['paper_trade'] = True
                ibkr_paper_config['client_id'] = ibkr_paper_config.get('client_id', 1) + 1  # Use different client ID
                ibkr_paper_broker = BrokerFactory.create_broker('IBKR', ibkr_paper_config)
                if ibkr_paper_broker and await ibkr_paper_broker.connect():
                    self.brokers['IBKR_PAPER'] = ibkr_paper_broker
                    print(f"[BROKER MANAGER] ✓ IBKR PAPER initialized")
                else:
                    print(f"[BROKER MANAGER] ❌ IBKR PAPER failed to connect")
            except Exception as e:
                print(f"[BROKER MANAGER] ❌ IBKR PAPER error: {e}")
        
        # Initialize Schwab (LIVE only - no paper trading with Schwab)
        if brokers_config.get('enable_schwab', False):
            try:
                schwab_config = self.config.get('schwab', {}).copy()
                try:
                    from gui_app.schwab_auth import get_schwab_credentials
                    db_creds = get_schwab_credentials()
                    if db_creds:
                        schwab_config['client_id'] = db_creds.get('client_id', schwab_config.get('client_id', ''))
                        schwab_config['client_secret'] = db_creds.get('client_secret', schwab_config.get('client_secret', ''))
                        schwab_config['redirect_uri'] = db_creds.get('redirect_uri', schwab_config.get('redirect_uri', 'https://127.0.0.1'))
                        schwab_config['dry_run'] = db_creds.get('dry_run', False)
                        print(f"[BROKER MANAGER] Schwab dry_run={'ON' if schwab_config['dry_run'] else 'OFF (LIVE)'} (from saved credentials)")
                    else:
                        schwab_config['dry_run'] = brokers_config.get('schwab_dry_run', True)
                except ImportError:
                    schwab_config['dry_run'] = brokers_config.get('schwab_dry_run', True)
                schwab_broker = BrokerFactory.create_broker('SCHWAB', schwab_config)
                if schwab_broker and await schwab_broker.connect():
                    self.brokers['SCHWAB'] = schwab_broker
                    mode = "DRY RUN" if schwab_config.get('dry_run', True) else "LIVE"
                    print(f"[BROKER MANAGER] ✓ Schwab initialized ({mode})")
                else:
                    print(f"[BROKER MANAGER] ⚠️  Schwab not authenticated - use Settings to connect")
            except Exception as e:
                print(f"[BROKER MANAGER] ❌ Schwab error: {e}")
        
        if brokers_config.get('enable_trading212', False):
            try:
                t212_config = self.config.get('trading212', {}).copy()
                try:
                    from gui_app.broker_credentials_service import get_trading212_credentials
                    db_creds = get_trading212_credentials()
                    if db_creds and db_creds.get('api_key'):
                        t212_config['api_key'] = db_creds.get('api_key', '')
                        t212_config['api_secret'] = db_creds.get('api_secret', '')
                        t212_config['environment'] = db_creds.get('environment', 'demo')
                except ImportError:
                    pass
                if t212_config.get('api_key'):
                    t212_broker = BrokerFactory.create_broker('TRADING212', t212_config)
                    if t212_broker and await t212_broker.connect():
                        self.brokers['TRADING212'] = t212_broker
                        env = t212_config.get('environment', 'demo').upper()
                        print(f"[BROKER MANAGER] Trading 212 initialized ({env})")
                    else:
                        print(f"[BROKER MANAGER] Trading 212 not authenticated")
                else:
                    print(f"[BROKER MANAGER] Trading 212 skipped (no API key)")
            except Exception as e:
                print(f"[BROKER MANAGER] Trading 212 error: {e}")

        # STRICT ROUTING: No default broker - all trades must specify broker via channel config
        # default_broker is kept for backwards compatibility but NOT used for routing
        self.default_broker = None  # Disabled - strict channel routing enforced
        
        if not self.brokers:
            print(f"[BROKER MANAGER] ❌ No brokers available!")
            return False
        
        print(f"[BROKER MANAGER] Initialized with {len(self.brokers)} broker(s): {list(self.brokers.keys())}")
        print(f"[BROKER MANAGER] STRICT ROUTING: No default broker - channel config required")
        return len(self.brokers) > 0
    
    def extract_broker_from_signal(self, message: str) -> tuple[Optional[str], str]:
        """
        Extract broker prefix from signal if present
        Returns: (broker_name, cleaned_message)
        
        Examples:
        - "[ALPACA] BTO 10 SPY @450" -> ('ALPACA', 'BTO 10 SPY @450')
        - "[IBKR] STC TSLA 200c 12/15" -> ('IBKR', 'STC TSLA 200c 12/15')
        - "[DISABLED] BTO AAPL @150" -> (None, 'BTO AAPL @150')  # Broker disabled, strips prefix
        - "BTO AAPL @150" -> (None, 'BTO AAPL @150')
        """
        # Match [BROKER] at start of message
        match = re.match(r'^\[(\w+)\]\s*(.+)$', message.strip(), re.IGNORECASE)
        if match:
            broker_name = match.group(1).upper()
            cleaned_message = match.group(2)
            if broker_name in self.brokers:
                return broker_name, cleaned_message
            else:
                # Broker unknown/disabled - strip prefix and fall back to default
                print(f"[BROKER MANAGER] Warning: Unknown broker '{broker_name}' in signal, using default (prefix stripped)")
                return None, cleaned_message  # Return cleaned message, not original
        return None, message
    
    def get_broker_for_signal(self, message: str, channel_id: Optional[str] = None, paper_trade: bool = False) -> BrokerInterface:
        """
        Get the appropriate broker for a signal based on selection method
        
        Selection methods:
        - prefix: Use [BROKER] prefix in signal, fall back to default
        - channel: Route based on channel ID mapping (future feature)
        - default: Always use default broker
        
        Args:
            message: Signal message content
            channel_id: Discord channel ID
            paper_trade: If True, route to paper trading broker
        """
        broker_name = None
        
        if self.selection_method == 'prefix':
            broker_name, _ = self.extract_broker_from_signal(message)
        
        elif self.selection_method == 'channel' and channel_id:
            # Future: Map channel IDs to specific brokers
            # For now, fall through to default
            pass
        
        # Determine base broker name - STRICT: No default broker fallback
        if not broker_name:
            # No broker specified - this should be handled by caller via channel config
            print(f"[BROKER MANAGER] ❌ No broker specified and no channel override")
            return None
        
        # Route to paper trading account if requested
        if paper_trade:
            paper_broker_name = f"{broker_name}_PAPER"
            if paper_broker_name in self.brokers:
                print(f"[BROKER MANAGER] Routing to {paper_broker_name} (paper trading)")
                return self.brokers[paper_broker_name]
            else:
                print(f"[BROKER MANAGER] ❌ {paper_broker_name} not available - no fallback")
                return None  # STRICT: No fallback to default broker
        
        # Return requested broker - STRICT: No fallback to default
        broker = self.brokers.get(broker_name)
        if not broker:
            print(f"[BROKER MANAGER] ❌ Broker '{broker_name}' not available - no fallback")
            return None
        return broker
    
    async def place_stock_order(
        self,
        broker_name: Optional[str],
        symbol: str,
        action: str,
        quantity: int,
        price: Optional[float] = None
    ) -> OrderResult:
        """Place a stock order on specified broker - STRICT: broker_name required"""
        if not broker_name:
            return OrderResult(
                success=False,
                message="No broker specified - channel broker configuration required",
                symbol=symbol,
                action=action
            )
        broker = self.brokers.get(broker_name)
        if not broker:
            return OrderResult(
                success=False,
                message=f"Broker not available: {broker_name}",
                symbol=symbol,
                action=action
            )
        
        return await broker.place_stock_order(symbol, action, quantity, price)
    
    async def place_option_order(
        self,
        broker_name: Optional[str],
        symbol: str,
        strike: float,
        expiry: str,
        option_type: str,
        action: str,
        quantity: int,
        price: Optional[float] = None,
        expiry_year: Optional[str] = None
    ) -> OrderResult:
        """Place an option order on specified broker - STRICT: broker_name required"""
        if not broker_name:
            return OrderResult(
                success=False,
                message="No broker specified - channel broker configuration required",
                symbol=symbol,
                action=action
            )
        broker = self.brokers.get(broker_name)
        if not broker:
            return OrderResult(
                success=False,
                message=f"Broker not available: {broker_name}",
                symbol=symbol,
                action=action
            )
        
        return await broker.place_option_order(
            symbol, strike, expiry, option_type, action, quantity, price
        )
    
    async def get_account_info(self, broker_name: Optional[str] = None) -> Dict[str, Any]:
        """Get account info from specified broker - STRICT: broker_name required for trading contexts"""
        if not broker_name:
            print("[BROKER MANAGER] ⚠️ get_account_info called without broker_name")
            return {}
        broker = self.brokers.get(broker_name)
        if not broker:
            print(f"[BROKER MANAGER] ❌ Broker '{broker_name}' not available for account info")
            return {}
        return await broker.get_account_info()
    
    async def get_positions(self, broker_name: Optional[str] = None) -> Dict[str, Any]:
        """Get positions from specified broker - STRICT: broker_name required for trading contexts"""
        if not broker_name:
            print("[BROKER MANAGER] ⚠️ get_positions called without broker_name")
            return {}
        broker = self.brokers.get(broker_name)
        if not broker:
            print(f"[BROKER MANAGER] ❌ Broker '{broker_name}' not available for positions")
            return {}
        return await broker.get_positions()
    
    async def get_quote(self, symbol: str, broker_name: Optional[str] = None) -> Optional[float]:
        """Get quote from specified broker - STRICT: broker_name required"""
        if not broker_name:
            print(f"[BROKER MANAGER] ⚠️ get_quote for {symbol} called without broker_name")
            return None
        broker = self.brokers.get(broker_name)
        if not broker:
            print(f"[BROKER MANAGER] ❌ Broker '{broker_name}' not available for quote")
            return None
        return await broker.get_quote(symbol)
    
    async def shutdown(self):
        """Disconnect all brokers"""
        for name, broker in self.brokers.items():
            try:
                await broker.disconnect()
                print(f"[BROKER MANAGER] Disconnected {name}")
            except Exception as e:
                print(f"[BROKER MANAGER] Error disconnecting {name}: {e}")
    
    def get_broker_list(self) -> List[str]:
        """Get list of available brokers"""
        return list(self.brokers.keys())
    
    def is_broker_available(self, broker_name: str) -> bool:
        """Check if broker is available"""
        return broker_name in self.brokers
