"""
Position Monitor
================
Main async monitoring loop coordinating all risk strategies.
"""
import asyncio
import re
from typing import Optional, List, Dict, Any, Callable, Awaitable
from pathlib import Path

from .risk_types import (
    PositionSnapshot,
    RiskSettings,
    ChannelRiskSettings,
    ExitDecision,
    PositionCacheEntry
)
from .position_cache import PositionCache
from .tiered_targets import evaluate_tiered_targets, format_tier_reason, evaluate_channel_stop_loss
from .global_risk import evaluate_global_risk, evaluate_price_based_stops
from .trailing_stop import evaluate_trailing_stop, get_effective_trailing_settings


class RiskDBAdapter:
    """
    Database adapter for risk management operations.
    Wraps gui_app.database to decouple risk module from database implementation.
    
    Usage:
        # Option 1: Pass database instance directly (preferred for SelfClient)
        adapter = RiskDBAdapter(db=self.db)
        
        # Option 2: Auto-import gui_app.database (standalone use)
        adapter = RiskDBAdapter()
    """
    
    def __init__(self, db=None):
        self._db = None
        self._available = False
        
        if db is not None:
            self._db = db
            self._available = True
        else:
            try:
                from gui_app import database as db_module
                self._db = db_module
                self._available = True
            except ImportError:
                print("[RISK] Warning: gui_app.database not available - running in headless mode")
    
    @property
    def available(self) -> bool:
        return self._available
    
    def get_connection(self):
        """Get database connection."""
        if self._db:
            return self._db.get_connection()
        return None
    
    def count_channels_with_risk(self) -> int:
        """Count channels with risk management explicitly enabled."""
        if not self._db:
            return 0
        try:
            conn = self._db.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(*) FROM channels 
                WHERE risk_management_enabled = 1
            ''')
            return cursor.fetchone()[0]
        except Exception as e:
            print(f"[RISK] Warning: Could not count channels with risk: {e}")
            return 0
    
    def get_channel_risk_settings(
        self, 
        symbol: str, 
        asset_type: str,
        strike: Optional[float] = None,
        expiry: Optional[str] = None,
        call_put: Optional[str] = None,
        broker_name: Optional[str] = None
    ) -> Optional[ChannelRiskSettings]:
        """Get per-channel risk settings for a position."""
        if not self._db:
            return None
        
        try:
            conn = self._db.get_connection()
            cursor = conn.cursor()
            
            if asset_type == 'option':
                # Normalize expiry to multiple formats for matching
                # Database may have: "12/17", "2025-12-17", "12/17/25", etc.
                expiry_variants = [expiry] if expiry else []
                if expiry:
                    # If format is YYYY-MM-DD, also try MM/DD
                    if '-' in expiry and len(expiry) == 10:
                        parts = expiry.split('-')
                        expiry_variants.append(f"{parts[1]}/{parts[2]}")  # 12/17
                        expiry_variants.append(f"{parts[1]}/{parts[2]}/{parts[0][2:]}")  # 12/17/25
                    # If format is MM/DD, also try YYYY-MM-DD
                    elif '/' in expiry and len(expiry) <= 5:
                        parts = expiry.split('/')
                        from datetime import datetime
                        year = datetime.now().year
                        expiry_variants.append(f"{year}-{parts[0].zfill(2)}-{parts[1].zfill(2)}")
                
                # Try each expiry variant
                row = None
                for exp_try in expiry_variants:
                    cursor.execute('''
                        SELECT t.channel_id, c.profit_target_1_pct, c.profit_target_2_pct, c.profit_target_3_pct,
                               c.stop_loss_pct, c.trailing_stop_pct, c.trailing_activation_pct, c.name,
                               c.risk_management_enabled, c.leave_runner_enabled, c.leave_runner_pct
                        FROM trades t
                        LEFT JOIN channels c ON t.channel_id = c.discord_channel_id
                        WHERE t.symbol = ? AND t.asset_type = 'option' AND t.strike = ? AND t.expiry = ? AND t.call_put = ?
                        AND t.status = 'OPEN' AND t.direction = 'BTO'
                        ORDER BY t.id DESC LIMIT 1
                    ''', (symbol, strike, exp_try, call_put))
                    row = cursor.fetchone()
                    if row:
                        break
                
                if not row:
                    return None
            else:
                cursor.execute('''
                    SELECT t.channel_id, c.profit_target_1_pct, c.profit_target_2_pct, c.profit_target_3_pct,
                           c.stop_loss_pct, c.trailing_stop_pct, c.trailing_activation_pct, c.name,
                           c.risk_management_enabled, c.leave_runner_enabled, c.leave_runner_pct
                    FROM trades t
                    LEFT JOIN channels c ON t.channel_id = c.discord_channel_id
                    WHERE t.symbol = ? AND t.asset_type = 'stock'
                    AND t.status = 'OPEN' AND t.direction = 'BTO'
                    ORDER BY t.id DESC LIMIT 1
                ''', (symbol,))
                row = cursor.fetchone()
                if not row:
                    return None
            
            if row[0] is not None:
                # Check if risk management is explicitly enabled for this channel
                risk_enabled = row[8] if len(row) > 8 else 0
                
                # Only apply risk management if explicitly enabled
                if not risk_enabled:
                    return None
                
                pt1 = row[1] or 0
                pt2 = row[2] or 0
                pt3 = row[3] or 0
                sl = row[4] or 0
                trail = row[5] or 0
                leave_runner_enabled = bool(row[9]) if len(row) > 9 and row[9] else False
                leave_runner_pct = row[10] if len(row) > 10 and row[10] else 25.0
                
                # Risk management is enabled - return settings
                return ChannelRiskSettings(
                    channel_id=str(row[0]),
                    channel_name=row[7] or 'Unknown',
                    profit_target_1_pct=pt1,
                    profit_target_2_pct=pt2,
                    profit_target_3_pct=pt3,
                    stop_loss_pct=sl,
                    trailing_stop_pct=trail,
                    trailing_activation_pct=row[6] or 15.0,
                    leave_runner_enabled=leave_runner_enabled,
                    leave_runner_pct=leave_runner_pct
                )
            
            return None
        except Exception as e:
            print(f"[RISK] Warning: Could not fetch channel settings: {e}")
            return None
    
    def load_position_price_targets(self) -> Dict[str, Dict[str, Optional[float]]]:
        """Load stop/target prices for all open positions.
        
        Returns dict keyed by db_key (no broker prefix) for matching with positions.
        """
        result = {}
        if not self._db:
            return result
        
        try:
            conn = self._db.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT symbol, asset_type, stop_loss_price, profit_target_price, strike, expiry, call_put
                FROM trades
                WHERE status = 'OPEN' AND direction = 'BTO'
                AND (stop_loss_price IS NOT NULL OR profit_target_price IS NOT NULL)
            ''')
            
            for row in cursor.fetchall():
                symbol = row[0]
                asset_type = row[1]
                sl_price = row[2]
                target_price = row[3]
                
                # Use db_key format (no broker prefix) for matching
                if asset_type == 'option':
                    db_key = f"{symbol}_{row[4]}_{row[5]}_{row[6]}"
                else:
                    db_key = f"{symbol}_stock"
                
                result[db_key] = {
                    'stop_loss_price': sl_price,
                    'profit_target_price': target_price
                }
            
            return result
        except Exception as e:
            print(f"[RISK] Warning: Could not load price targets: {e}")
            return result
    
    def find_open_bto_trade(
        self,
        symbol: str,
        asset_type: str,
        broker: str,
        strike: Optional[float] = None,
        expiry: Optional[str] = None,
        call_put: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Find the original BTO trade for PNL attribution."""
        if not self._db:
            return None
        
        try:
            return self._db.find_open_bto_trade(
                symbol=symbol,
                asset_type=asset_type,
                broker=broker,
                strike=strike,
                expiry=expiry,
                call_put=call_put
            )
        except Exception as e:
            print(f"[RISK] Warning: Could not find open BTO trade: {e}")
            return None
    
    def get_channel_record_id(self, discord_channel_id: str) -> Optional[int]:
        """Get channel record ID from Discord channel ID."""
        if not self._db:
            return None
        
        try:
            conn = self._db.get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT id FROM channels WHERE discord_channel_id = ?', 
                          (str(discord_channel_id),))
            row = cursor.fetchone()
            return row['id'] if row else None
        except Exception as e:
            print(f"[RISK] Warning: Could not get channel_record_id: {e}")
            return None


class RiskManager:
    """
    Main risk management coordinator.
    
    Monitors positions from multiple brokers and applies risk rules:
    1. Per-channel tiered profit targets (T1/T2/T3)
    2. Global profit target fallback
    3. Price-based stop loss / profit target overrides
    4. Trailing stop with activation threshold
    """
    
    DEFAULT_MONITORING_INTERVAL = 30  # seconds
    DEFAULT_TRAILING_ACTIVATION = 15.0  # percent
    
    def __init__(
        self,
        position_fetcher: Callable[[], Awaitable[List[Dict]]],
        order_queue: asyncio.Queue,
        settings_provider: Callable[[], Dict],
        db_adapter: Optional[RiskDBAdapter] = None,
        alpaca_broker=None,
        monitoring_interval: int = DEFAULT_MONITORING_INTERVAL,
        trailing_activation_pct: float = DEFAULT_TRAILING_ACTIVATION,
        loop: Optional[asyncio.AbstractEventLoop] = None
    ):
        """
        Initialize RiskManager.
        
        Args:
            position_fetcher: Async callable returning Webull positions
            order_queue: Queue for exit orders
            settings_provider: Callable returning RiskSettings dict
            db_adapter: Database adapter (optional, for headless mode)
            alpaca_broker: Optional AlpacaBroker instance
            monitoring_interval: Seconds between position checks
            trailing_activation_pct: Default trailing stop activation threshold
            loop: Event loop (optional)
        """
        self.position_fetcher = position_fetcher
        self.order_queue = order_queue
        self.settings_provider = settings_provider
        self.db_adapter = db_adapter or RiskDBAdapter()
        self.alpaca_broker = alpaca_broker
        self.monitoring_interval = monitoring_interval
        self.trailing_activation_pct = trailing_activation_pct
        self.loop = loop or asyncio.get_event_loop()
        
        self.cache = PositionCache()
        self._running = False
    
    async def start_monitoring(self) -> None:
        """Start the position monitoring loop."""
        risk_settings = self._get_risk_settings()
        channel_count = self.db_adapter.count_channels_with_risk()
        
        self._log_status(risk_settings, channel_count)
        
        if not risk_settings.enabled and channel_count == 0:
            print("[RISK] ❌ Position monitoring disabled (no global or channel-level risk settings)")
            return
        
        cached_count = self.cache.load()
        if cached_count > 0:
            print(f"[RISK] Loaded {cached_count} cached positions")
        
        self._load_db_price_targets()
        
        print(f"[RISK] ✓ Position monitoring started - Monitoring Webull + Alpaca")
        self._running = True
        
        while self._running:
            try:
                await self._monitoring_cycle()
            except Exception as e:
                print(f"[RISK] Error in monitoring cycle: {e}")
                import traceback
                traceback.print_exc()
            
            await asyncio.sleep(self.monitoring_interval)
    
    def stop_monitoring(self) -> None:
        """Stop the monitoring loop."""
        self._running = False
    
    async def _monitoring_cycle(self) -> None:
        """Execute one monitoring cycle."""
        risk_settings = self._get_risk_settings()
        
        if not risk_settings.enabled:
            channel_count = self.db_adapter.count_channels_with_risk()
            if channel_count == 0:
                print("[RISK] Risk management disabled - stopping monitoring")
                self._running = False
                return
            else:
                print(f"[RISK] Per-channel risk ACTIVE for {channel_count} channel(s)")
        
        positions = await self._fetch_all_positions()
        
        if positions:
            webull_count = sum(1 for p in positions if p.broker == 'Webull')
            alpaca_count = sum(1 for p in positions if 'ALPACA' in p.broker)
            print(f"\n[RISK] Monitoring {len(positions)} open positions "
                  f"(Webull: {webull_count}, Alpaca: {alpaca_count})...")
        
        broker_position_keys = set()
        
        for position in positions:
            try:
                await self._evaluate_position(position, risk_settings, broker_position_keys)
            except Exception as e:
                print(f"[RISK] ⚠️ Error processing position {position.symbol}: {e}")
        
        self.cache.save()
    
    async def _fetch_all_positions(self) -> List[PositionSnapshot]:
        """Fetch positions from all brokers."""
        positions = []
        
        webull_positions = await self.position_fetcher() or []
        for pos in webull_positions:
            pos['broker'] = 'Webull'
            positions.append(self._to_snapshot(pos))
        
        if self.alpaca_broker and getattr(self.alpaca_broker, 'connected', False):
            try:
                alpaca_positions = await self._fetch_alpaca_positions()
                positions.extend(alpaca_positions)
            except Exception as e:
                print(f"[RISK] Warning: Could not fetch Alpaca positions: {e}")
        
        return positions
    
    async def _fetch_alpaca_positions(self) -> List[PositionSnapshot]:
        """Fetch and parse Alpaca positions."""
        positions = []
        
        alpaca_raw = await asyncio.to_thread(
            self.alpaca_broker.trading_client.get_all_positions
        )
        
        for ap in alpaca_raw:
            symbol = ap.symbol
            is_option = '  ' in symbol or len(symbol) > 10
            
            if is_option:
                snapshot = self._parse_alpaca_option(ap, symbol)
                if snapshot:
                    positions.append(snapshot)
            else:
                positions.append(PositionSnapshot(
                    symbol=symbol,
                    quantity=abs(float(ap.qty)),
                    avg_cost=float(ap.avg_entry_price),
                    current_price=float(ap.current_price),
                    asset='stock',
                    broker='ALPACA_PAPER'
                ))
        
        return positions
    
    def _parse_alpaca_option(self, ap, symbol: str) -> Optional[PositionSnapshot]:
        """Parse Alpaca option symbol (OCC format)."""
        try:
            if '  ' in symbol:
                parts = symbol.split()
                underlying = parts[0]
                option_code = parts[-1]
                
                exp_yy = option_code[:2]
                exp_mm = option_code[2:4]
                exp_dd = option_code[4:6]
                expiry = f"20{exp_yy}-{exp_mm}-{exp_dd}"
                
                call_put = option_code[6]
                strike = float(option_code[7:]) / 1000
            else:
                match = re.match(r'^([A-Z]+)(\d{6})([CP])(\d+)$', symbol)
                if not match:
                    return None
                
                underlying = match.group(1)
                date_part = match.group(2)
                call_put = match.group(3)
                strike = float(match.group(4)) / 1000
                
                expiry = f"20{date_part[:2]}-{date_part[2:4]}-{date_part[4:6]}"
            
            return PositionSnapshot(
                symbol=underlying,
                quantity=abs(float(ap.qty)),
                avg_cost=float(ap.avg_entry_price),
                current_price=float(ap.current_price),
                asset='option',
                broker='ALPACA_PAPER',
                strike=strike,
                expiry=expiry,
                direction=call_put,
                raw_symbol=symbol
            )
        except Exception as e:
            print(f"[RISK] Warning: Could not parse Alpaca option symbol {symbol}: {e}")
            return None
    
    async def _evaluate_position(
        self, 
        position: PositionSnapshot, 
        risk_settings: RiskSettings,
        broker_position_keys: set
    ) -> None:
        """Evaluate a single position for risk triggers."""
        pos_key = position.position_key
        broker_position_keys.add(pos_key)
        
        cache = self.cache.get_or_create(
            position, 
            db_price_targets=getattr(self, '_db_price_targets', None)
        )
        
        if self.cache.is_closing(pos_key):
            return
        
        self.cache.update_highest_price(pos_key, position.current_price)
        
        pct_change = position.pct_change
        
        channel_settings = cache.channel_settings
        if channel_settings is None:
            call_put = self._normalize_call_put(position.direction)
            channel_settings = self.db_adapter.get_channel_risk_settings(
                position.symbol,
                position.asset,
                position.strike,
                position.expiry,
                call_put,
                position.broker
            )
            self.cache.set_channel_settings(pos_key, channel_settings)
            
            if channel_settings:
                print(f"[RISK] Using per-channel settings from '{channel_settings.channel_name}': "
                      f"Targets={channel_settings.profit_target_1_pct}%/"
                      f"{channel_settings.profit_target_2_pct}%/{channel_settings.profit_target_3_pct}%, "
                      f"StopLoss={channel_settings.stop_loss_pct}%")
        
        # Skip position if global is disabled AND no channel settings - no risk management applies
        if not channel_settings and not risk_settings.enabled:
            return  # Skip this position entirely
        
        self._log_position_status(position, cache, channel_settings, pct_change)
        
        decision = self._evaluate_exit_conditions(
            position, cache, channel_settings, risk_settings
        )
        
        if decision.should_exit:
            await self._execute_exit(position, cache, decision, channel_settings)
    
    def _evaluate_exit_conditions(
        self,
        position: PositionSnapshot,
        cache: PositionCacheEntry,
        channel_settings: Optional[ChannelRiskSettings],
        risk_settings: RiskSettings
    ) -> ExitDecision:
        """Evaluate all exit conditions in priority order."""
        
        decision = evaluate_price_based_stops(position, cache)
        if decision.should_exit:
            return decision
        
        if channel_settings:
            decision = evaluate_channel_stop_loss(position, cache, channel_settings)
            if decision.should_exit:
                return decision
        
        if channel_settings and channel_settings.has_tiered_targets:
            decision = evaluate_tiered_targets(position, cache, channel_settings)
            if decision.should_exit:
                decision.reason = format_tier_reason(decision, channel_settings.channel_name)
                return decision
        
        trailing_pct, activation_pct, stop_pct = get_effective_trailing_settings(
            channel_settings, risk_settings, self.trailing_activation_pct
        )
        channel_name = channel_settings.channel_name if channel_settings else "Global"
        
        decision, should_activate = evaluate_trailing_stop(
            position, cache, trailing_pct, activation_pct, stop_pct, channel_name
        )
        if should_activate:
            self.cache.activate_trailing_stop(position.position_key)
        if decision.should_exit:
            return decision
        
        if not channel_settings:
            decision = evaluate_global_risk(position, cache, risk_settings)
            if decision.should_exit:
                return decision
        
        return ExitDecision.no_exit()
    
    async def _execute_exit(
        self,
        position: PositionSnapshot,
        cache: PositionCacheEntry,
        decision: ExitDecision,
        channel_settings: Optional[ChannelRiskSettings]
    ) -> None:
        """Queue an exit order."""
        pos_key = position.position_key
        print(f"[RISK] ✓ EXIT TRIGGERED: {pos_key} - {decision.reason}")
        
        is_stop_exit = 'STOP LOSS' in decision.reason or 'TRAILING STOP' in decision.reason
        if not decision.is_partial:
            self.cache.mark_closing(pos_key)
        
        if decision.tier_hit:
            self.cache.mark_tier_hit(pos_key, decision.tier_hit)
            if decision.tier_hit == 1 and not decision.is_partial:
                self.cache.set_all_tiers_hit(pos_key)
        
        try:
            stc_signal = self._build_stc_signal(position, decision)
            
            call_put = self._normalize_call_put(position.direction)
            origin_trade = self.db_adapter.find_open_bto_trade(
                symbol=position.symbol,
                asset_type=position.asset,
                broker=position.broker,
                strike=position.strike,
                expiry=position.expiry,
                call_put=call_put
            )
            
            if origin_trade:
                stc_signal['channel_id'] = origin_trade.get('channel_id')
                stc_signal['message_id'] = origin_trade.get('message_id')
                stc_signal['origin_trade_id'] = origin_trade.get('id')
                
                if origin_trade.get('channel_id'):
                    channel_record_id = self.db_adapter.get_channel_record_id(
                        origin_trade['channel_id']
                    )
                    if channel_record_id:
                        stc_signal['channel_record_id'] = channel_record_id
                
                print(f"[RISK] ✓ Linked to origin channel_id={origin_trade.get('channel_id')} "
                      f"(trade #{origin_trade.get('id')})")
            else:
                print(f"[RISK] ⚠️ No origin BTO trade found in database for {pos_key}")
            
            await self.order_queue.put(stc_signal)
            print(f"[RISK] STC order queued for {pos_key} via {position.broker}: {stc_signal}")
            
        except Exception as e:
            self.cache.reset_closing(pos_key)
            print(f"[RISK] ✗ Failed to queue STC order for {pos_key}: {e}")
    
    def _build_stc_signal(self, position: PositionSnapshot, decision: ExitDecision) -> Dict:
        """Build STC signal dict for order queue."""
        stc_signal = {
            'asset': position.asset,
            'action': 'STC',
            'qty': decision.exit_qty,
            'symbol': position.symbol,
            'price': position.current_price,
            'broker': position.broker,
            'raw_symbol': position.raw_symbol,
            'exit_reason': decision.reason,
            'risk_trigger': decision.risk_trigger,
            '_risk_management_order': True
        }
        
        if position.asset == 'option':
            expiry_iso = position.expiry or ''
            expiry_year = None
            if expiry_iso and '-' in expiry_iso:
                parts = expiry_iso.split('-')
                if len(parts) == 3:
                    expiry_year = parts[0]
                    expiry_mmdd = f"{parts[1]}/{parts[2]}"
                else:
                    expiry_mmdd = expiry_iso
            else:
                expiry_mmdd = expiry_iso
            
            direction = (position.direction or '').upper()
            if direction == 'CALL':
                opt_type = 'C'
            elif direction == 'PUT':
                opt_type = 'P'
            else:
                opt_type = direction[0] if direction else 'C'
            
            stc_signal['strike'] = position.strike or 0
            stc_signal['opt_type'] = opt_type
            stc_signal['expiry'] = expiry_mmdd
            stc_signal['expiry_year'] = expiry_year
            stc_signal['option_id'] = position.option_id or 0
        
        return stc_signal
    
    def _get_risk_settings(self) -> RiskSettings:
        """Get current risk settings."""
        settings = self.settings_provider()
        return RiskSettings(
            enabled=settings.get('enabled', False),
            profit_target_percent=settings.get('profit_target_percent', 0),
            stop_loss_percent=settings.get('stop_loss_percent', 0),
            trailing_stop_percent=settings.get('trailing_stop_percent', 0)
        )
    
    def _load_db_price_targets(self) -> None:
        """Load per-position price targets from database.
        
        Note: DB returns db_key format (no broker). We store these targets
        and apply them when positions are first tracked via get_or_create().
        """
        self._db_price_targets = self.db_adapter.load_position_price_targets()
        if self._db_price_targets:
            print(f"[RISK] ✓ Loaded stop/target prices for {len(self._db_price_targets)} positions from database")
    
    def _to_snapshot(self, pos: Dict) -> PositionSnapshot:
        """Convert raw position dict to PositionSnapshot."""
        return PositionSnapshot(
            symbol=pos.get('symbol', ''),
            quantity=float(pos.get('quantity', 0)),
            avg_cost=float(pos.get('avg_cost', 0)),
            current_price=float(pos.get('current_price', 0)),
            asset=pos.get('asset', 'stock'),
            broker=pos.get('broker', 'Webull'),
            strike=pos.get('strike'),
            expiry=pos.get('expiry'),
            direction=pos.get('direction'),
            raw_symbol=pos.get('raw_symbol'),
            option_id=pos.get('option_id')
        )
    
    def _normalize_call_put(self, direction: Optional[str]) -> Optional[str]:
        """Normalize CALL/PUT to C/P."""
        if not direction:
            return None
        d = direction.upper()
        if d == 'CALL':
            return 'C'
        if d == 'PUT':
            return 'P'
        return d[0] if d else None
    
    def _log_status(self, risk_settings: RiskSettings, channel_count: int) -> None:
        """Log risk management status."""
        print(f"[RISK] ========== RISK MANAGEMENT STATUS ==========")
        print(f"[RISK] Global Risk: {'✓ ENABLED' if risk_settings.enabled else '✗ DISABLED'}")
        if risk_settings.enabled:
            print(f"[RISK]   → Profit Target: {risk_settings.profit_target_percent}%")
            print(f"[RISK]   → Stop Loss: {risk_settings.stop_loss_percent}%")
            print(f"[RISK]   → Trailing Stop: {risk_settings.trailing_stop_percent}%")
        print(f"[RISK] Per-Channel Risk: {channel_count} channel(s) configured")
        print(f"[RISK] ===============================================")
        
        if risk_settings.enabled and channel_count > 0:
            print(f"[RISK] MODE: HYBRID - Per-channel first, Global fallback")
        elif risk_settings.enabled:
            print(f"[RISK] MODE: GLOBAL ONLY - All trades use global settings")
        elif channel_count > 0:
            print(f"[RISK] MODE: PER-CHANNEL ONLY - Only channel-linked trades get risk management")
            print(f"[RISK]   ⚠️  Trades without channel_id will NOT have risk management!")
    
    def _log_position_status(
        self, 
        position: PositionSnapshot, 
        cache: PositionCacheEntry,
        channel_settings: Optional[ChannelRiskSettings],
        pct_change: float
    ) -> None:
        """Log position monitoring status."""
        pos_key = position.position_key
        current = position.current_price
        entry = cache.entry_price
        qty = position.quantity
        
        channel_name = channel_settings.channel_name if channel_settings else 'Global'
        sl_price = cache.stop_loss_price
        target_price = cache.profit_target_price
        
        if sl_price or target_price:
            print(f"[RISK] [{channel_name}] {pos_key}: ${current:.2f} ({pct_change:+.2f}%) | "
                  f"Entry: ${entry:.2f} | SL: ${sl_price or 'N/A'} | Target: ${target_price or 'N/A'} | Qty: {qty}")
        elif channel_settings:
            print(f"[RISK] [{channel_name}] {pos_key}: ${current:.2f} ({pct_change:+.2f}%) | "
                  f"Entry: ${entry:.2f} | Targets: {channel_settings.profit_target_1_pct}/"
                  f"{channel_settings.profit_target_2_pct}/{channel_settings.profit_target_3_pct}% | "
                  f"SL: {channel_settings.stop_loss_pct}% | Qty: {qty}")
        else:
            print(f"[RISK] [Global] {pos_key}: ${current:.2f} ({pct_change:+.2f}%) | "
                  f"Entry: ${entry:.2f} | Qty: {qty}")
