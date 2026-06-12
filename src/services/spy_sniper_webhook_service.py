"""
Spy-Sniper Webhook Service
===========================
Service for processing spy-sniper signals and forwarding to webhook channels.

Features:
- Detects Open/Trim/Close alerts from spy-sniper channel
- Forwards entries as BTO with configurable default quantity or $ amount
- Forwards exits as STC with calculated proportional quantity
- Integrates with PositionLedger for centralized trade tracking
- Uses ExitDispatcher for unified exit routing
- Triggers STC on risk management hits (PT/SL/trailing stop)
"""

import asyncio
import aiohttp
from datetime import datetime
from typing import Optional, Dict, Any, Callable, Awaitable
from dataclasses import dataclass, field

from src.signals.spy_sniper_parser import (
    is_spy_sniper_signal,
    parse_spy_sniper_signal,
    process_spy_sniper_message,
    SpySniperSignal,
    SpySniperSignalType,
    SpySniperPositionTracker,
    get_position_tracker,
    format_as_bto,
    format_as_stc,
)

from src.services.position_ledger import (
    get_position_ledger,
    LedgerPosition,
    PositionLedger
)
from src.services.exit_dispatcher import (
    get_exit_dispatcher,
    ExitDispatcher,
    ExitRequest
)
from src.services.price_monitor_service import get_price_monitor, PriceMonitorService


@dataclass
class SpySniperConfig:
    """Configuration for spy-sniper webhook service."""
    channel_id: str = ""
    webhook_url: str = ""
    default_quantity: int = 1
    default_dollar_amount: Optional[float] = None
    enable_execution: bool = False
    enable_forwarding: bool = True
    enable_risk_management: bool = True
    stop_loss_pct: float = 25.0
    pt1_pct: float = 25.0
    pt2_pct: float = 50.0
    pt3_pct: float = 75.0
    pt4_pct: float = 100.0
    trailing_stop_pct: float = 0.0
    trailing_activation_pct: float = 15.0
    routing_mapping_id: Optional[int] = None  # Signal routing discriminator for risk engine
    exit_schedule: Dict[int, int] = field(default_factory=lambda: {
        15: 20,
        50: 20,
        100: 20,
        150: 20,
        200: 20,
    })


class SpySniperWebhookService:
    """
    Service for processing spy-sniper signals and forwarding to webhook.
    
    Workflow:
    1. Message received in spy-sniper channel
    2. Detect if it's an Open/Trim/Close alert (embed)
    3. Parse signal details (symbol, expiry, strike, type, price)
    4. For entries: Forward as BTO with configured quantity
    5. For exits: Calculate proportional exit and forward as STC
    6. If execution enabled: Also queue order to broker
    """
    
    def __init__(self, config: Optional[SpySniperConfig] = None):
        self.config = config or SpySniperConfig()
        self.position_tracker = get_position_tracker()
        self.ledger = get_position_ledger()
        self.exit_dispatcher = get_exit_dispatcher()
        self.price_monitor = get_price_monitor()
        self._session: Optional[aiohttp.ClientSession] = None
        self._running = False
        
        self._on_bto_callback: Optional[Callable[[Dict], Awaitable[None]]] = None
        self._on_stc_callback: Optional[Callable[[Dict], Awaitable[None]]] = None
        self._on_risk_exit_callback: Optional[Callable[[Dict], Awaitable[None]]] = None
    
    def set_bto_callback(self, callback: Callable[[Dict], Awaitable[None]]):
        """Set callback for BTO signals (for broker execution)."""
        self._on_bto_callback = callback
    
    def set_stc_callback(self, callback: Callable[[Dict], Awaitable[None]]):
        """Set callback for STC signals (for broker execution)."""
        self._on_stc_callback = callback
    
    def set_risk_exit_callback(self, callback: Callable[[Dict], Awaitable[None]]):
        """Set callback for risk-triggered exits."""
        self._on_risk_exit_callback = callback
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
    
    async def close(self):
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()
    
    def configure(self, config: SpySniperConfig):
        """Update configuration."""
        self.config = config
        if config.exit_schedule:
            self.position_tracker.exit_schedule = config.exit_schedule
    
    def load_config_from_db(self, channel_id: str):
        """Load configuration from database for a channel."""
        try:
            from gui_app import database as db  # type: ignore
            
            channel_settings = db.get_channel_settings(channel_id)  # type: ignore
            if not channel_settings:
                print(f"[SPY-SNIPER] No settings found for channel {channel_id}")
                return
            
            mapping = db.get_channel_mapping_by_source(channel_id)  # type: ignore
            webhook_url = ""
            if mapping:
                webhook_url = mapping.get('webhook_url', '')
            
            self.config = SpySniperConfig(
                channel_id=channel_id,
                webhook_url=webhook_url,
                default_quantity=channel_settings.get('channel_qty', 1) or 1,
                default_dollar_amount=channel_settings.get('channel_size_pct'),
                enable_execution=channel_settings.get('execute_enabled', False),
                enable_forwarding=True,
                enable_risk_management=channel_settings.get('risk_management_enabled', False),
                stop_loss_pct=channel_settings.get('stop_loss_pct', 25.0) or 25.0,
                pt1_pct=channel_settings.get('pt1_pct', 25.0) or 25.0,
                pt2_pct=channel_settings.get('pt2_pct', 50.0) or 50.0,
                pt3_pct=channel_settings.get('pt3_pct', 75.0) or 75.0,
                pt4_pct=channel_settings.get('pt4_pct', 100.0) or 100.0,
                trailing_stop_pct=channel_settings.get('trailing_stop_pct', 0.0) or 0.0,
                trailing_activation_pct=channel_settings.get('trailing_activation_pct', 15.0) or 15.0,
            )
            
            print(f"[SPY-SNIPER] Loaded config: qty={self.config.default_quantity}, "
                  f"webhook={bool(self.config.webhook_url)}, exec={self.config.enable_execution}")
            
        except Exception as e:
            print(f"[SPY-SNIPER] Error loading config: {e}")
    
    def load_config_from_routing_mapping(self, channel_id: str) -> bool:
        """Load configuration from signal_routing_mappings table."""
        try:
            from gui_app import database as db
            
            mapping = db.get_signal_routing_by_source(channel_id)
            if not mapping:
                print(f"[SPY-SNIPER] No routing mapping for channel {channel_id}")
                return False
            
            if not mapping.get('enabled', 0):
                print(f"[SPY-SNIPER] Routing mapping disabled for channel {channel_id}")
                return False
            
            webhook_url = ""
            if mapping.get('destination_type') == 'webhook':
                webhook_url = mapping.get('destination_url', '')
            
            self.config = SpySniperConfig(
                channel_id=channel_id,
                webhook_url=webhook_url,
                default_quantity=mapping.get('default_quantity', 1) or 1,
                default_dollar_amount=mapping.get('default_dollar_amount'),
                enable_execution=bool(mapping.get('enable_execution', 0)),
                enable_forwarding=bool(mapping.get('enable_forwarding', 1)),
                enable_risk_management=bool(mapping.get('enable_risk_management', 1)),
                stop_loss_pct=mapping.get('stop_loss_pct', 25.0) or 25.0,
                pt1_pct=mapping.get('pt1_pct', 25.0) or 25.0,
                pt2_pct=mapping.get('pt2_pct', 50.0) or 50.0,
                pt3_pct=mapping.get('pt3_pct', 75.0) or 75.0,
                pt4_pct=mapping.get('pt4_pct', 100.0) or 100.0,
                trailing_stop_pct=mapping.get('trailing_stop_pct', 0.0) or 0.0,
                trailing_activation_pct=mapping.get('trailing_activation_pct', 15.0) or 15.0,
                routing_mapping_id=mapping.get('id'),  # Store mapping ID for risk engine discrimination
            )
            
            print(f"[SPY-SNIPER] ✓ Loaded from routing mapping: {mapping.get('name', 'unnamed')} (id={mapping.get('id')})")
            print(f"[SPY-SNIPER]   qty={self.config.default_quantity}, "
                  f"fwd={self.config.enable_forwarding}, exec={self.config.enable_execution}")
            return True
            
        except Exception as e:
            print(f"[SPY-SNIPER] Error loading from routing mapping: {e}")
            return False
    
    async def process_message(
        self,
        embed_title: str,
        embed_description: str,
        message_id: str,
        channel_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Process a Discord message with embedded alert.
        
        Args:
            embed_title: The embed title (e.g., "Open Alert")
            embed_description: The embed description with option details
            message_id: Discord message ID for deduplication
            channel_id: Optional channel ID to load config
            
        Returns:
            Dict with processing result or None if not a signal
        """
        if not is_spy_sniper_signal(embed_title):
            return None
        
        if channel_id and channel_id != self.config.channel_id:
            if not self.load_config_from_routing_mapping(channel_id):
                self.load_config_from_db(channel_id)
        
        result = process_spy_sniper_message(
            embed_title=embed_title,
            embed_description=embed_description,
            message_id=message_id,
            default_quantity=self.config.default_quantity,
            default_dollar_amount=self.config.default_dollar_amount
        )
        
        if not result:
            return None
        
        action = result.get('action', '')
        option_key = result.get('option_key', '')
        signal = result.get('signal', {})
        
        print(f"[SPY-SNIPER] Processed: {action} {option_key}")
        
        if action == 'BTO':
            self._create_ledger_position(result, channel_id or self.config.channel_id)
        elif action == 'STC':
            await self._process_exit_via_dispatcher(result)
        
        if self.config.enable_forwarding and self.config.webhook_url:
            await self._forward_to_webhook(result)
        
        if self.config.enable_execution:
            await self._trigger_execution(result)
        
        return result
    
    def _create_ledger_position(self, result: Dict[str, Any], channel_id: str):
        """Create a position in the centralized ledger for BTO entries."""
        try:
            signal = result.get('signal', {})
            option_key = result.get('option_key', '')
            quantity = result.get('quantity', 1)
            
            if not option_key or not signal.get('symbol'):
                print(f"[SPY-SNIPER] ⏭️ Skipping ledger creation - missing option_key or symbol")
                return
            
            entry_price = signal.get('entry_price', 0.0) or 0.0
            if entry_price <= 0:
                print(f"[SPY-SNIPER] ⏭️ Skipping ledger creation - invalid entry price: {entry_price}")
                return
            
            position = LedgerPosition(
                option_key=option_key,
                symbol=signal.get('symbol', ''),
                expiry=signal.get('expiry_normalized', ''),
                strike=signal.get('strike', 0.0),
                option_type=signal.get('option_type', ''),
                channel_id=channel_id,
                broker_id="",
                account_id="",
                entry_qty=quantity,
                remaining_qty=quantity,
                entry_price=signal.get('entry_price', 0.0) or 0.0,
                current_price=signal.get('entry_price', 0.0) or 0.0,
                price_updated_at=datetime.now().isoformat(),
                status="open",
                entry_time=datetime.now().isoformat(),
                entry_message_id=result.get('signal', {}).get('message_id', ''),
                source_type="spy_sniper",
                routing_mapping_id=self.config.routing_mapping_id  # Pass through for risk engine
            )
            
            position_id = self.ledger.create_position(position)
            result['ledger_position_id'] = position_id
            print(f"[SPY-SNIPER] ✓ Ledger position created: {option_key} (ID: {position_id})")
            
            if position_id and position_id > 0:
                position.id = position_id
                self.price_monitor.register_position(position)
            
        except Exception as e:
            print(f"[SPY-SNIPER] Error creating ledger position: {e}")
    
    async def _process_exit_via_dispatcher(self, result: Dict[str, Any]):
        """Process exit signal through the unified exit dispatcher."""
        try:
            option_key = result.get('option_key', '')
            quantity = result.get('quantity', 1)
            signal = result.get('signal', {})
            exit_price = signal.get('current_price', 0.0) or 0.0
            message_id = signal.get('message_id', '')
            
            exit_result = await self.exit_dispatcher.dispatch_signal_exit(
                option_key=option_key,
                exit_qty=quantity,
                exit_price=exit_price,
                message_id=message_id,
                destination_url=self.config.webhook_url
            )
            
            if exit_result.success:
                result['ledger_exit'] = {
                    'exit_qty': exit_result.exit_qty,
                    'exit_pnl_dollar': exit_result.exit_pnl_dollar,
                    'exit_pnl_pct': exit_result.exit_pnl_pct
                }
            else:
                print(f"[SPY-SNIPER] Exit dispatcher: {exit_result.message}")
                
        except Exception as e:
            print(f"[SPY-SNIPER] Error processing exit via dispatcher: {e}")
    
    async def _forward_to_webhook(self, result: Dict[str, Any]):
        """Forward the formatted signal to webhook. Only forwards valid BTO/STC signals."""
        if not self.config.webhook_url:
            return
        
        formatted_msg = result.get('formatted_message', '')
        if not formatted_msg:
            print("[SPY-SNIPER] ⏭️ No formatted message to forward")
            return
        
        action = result.get('action', '')
        if action not in ('BTO', 'STC'):
            print(f"[SPY-SNIPER] ⏭️ Invalid action '{action}' - only BTO/STC forwarded")
            return
        
        if not (formatted_msg.startswith('BTO ') or formatted_msg.startswith('STC ')):
            print(f"[SPY-SNIPER] ⏭️ Message doesn't start with BTO/STC - not forwarding")
            return
        
        try:
            session = await self._get_session()
            
            marker = f"\n||SPY-SNIPER:{result.get('option_key', '')}||"
            webhook_content = formatted_msg + marker
            
            async with session.post(
                self.config.webhook_url,
                json={"content": webhook_content}
            ) as resp:
                if resp.status == 200 or resp.status == 204:
                    print(f"[SPY-SNIPER] ✓ Forwarded to webhook: {formatted_msg[:50]}")
                else:
                    print(f"[SPY-SNIPER] Webhook failed: HTTP {resp.status}")
                    
        except Exception as e:
            print(f"[SPY-SNIPER] Webhook error: {e}")
    
    async def _trigger_execution(self, result: Dict[str, Any]):
        """Trigger broker execution for the signal."""
        action = result.get('action', '')
        
        if action == 'BTO' and self._on_bto_callback:
            try:
                await self._on_bto_callback(result)
            except Exception as e:
                print(f"[SPY-SNIPER] BTO callback error: {e}")
        
        elif action == 'STC' and self._on_stc_callback:
            try:
                await self._on_stc_callback(result)
            except Exception as e:
                print(f"[SPY-SNIPER] STC callback error: {e}")
    
    async def trigger_risk_exit(
        self,
        option_key: str,
        exit_reason: str,
        exit_price: float,
        exit_pct: int = 100,
        broker_id: str = "",
        account_id: str = ""
    ):
        """
        Trigger an exit based on risk management (PT/SL/trailing stop).
        
        Routes through ExitDispatcher for proper deduplication and ledger tracking.
        
        Args:
            option_key: The option position key
            exit_reason: Reason for exit (e.g., "PT1", "STOP_LOSS", "TRAILING")
            exit_price: Current price at exit
            exit_pct: Percentage of position to exit
            broker_id: Optional broker ID for multi-broker support
            account_id: Optional account ID
        """
        ledger_position = self.ledger.get_position_by_key(option_key, broker_id, account_id)
        
        if ledger_position:
            exit_qty = max(1, int(ledger_position.remaining_qty * exit_pct / 100))
            exit_qty = min(exit_qty, ledger_position.remaining_qty)
            
            exit_result = await self.exit_dispatcher.dispatch_risk_exit(
                option_key=option_key,
                exit_pct=int(exit_qty * 100 / ledger_position.remaining_qty) if ledger_position.remaining_qty > 0 else 100,
                exit_price=exit_price,
                exit_reason=exit_reason,
                broker_id=broker_id,
                account_id=account_id,
                destination_url=self.config.webhook_url if self.config.enable_forwarding else ""
            )
            
            if exit_result.success:
                print(f"[SPY-SNIPER] ✓ Risk exit dispatched: {option_key} ({exit_reason}) "
                      f"P&L: ${exit_result.exit_pnl_dollar:.2f} ({exit_result.exit_pnl_pct:.1f}%)")
                
                if ledger_position.id and exit_result.exit_qty >= ledger_position.remaining_qty:
                    self.price_monitor.unregister_position(ledger_position.id)
            else:
                print(f"[SPY-SNIPER] Risk exit failed: {exit_result.message}")
            
            return
        
        position = self.position_tracker.get_position(option_key)
        if not position:
            print(f"[SPY-SNIPER] No position found for risk exit: {option_key}")
            return
        
        exit_qty = max(1, int(position["quantity"] * exit_pct / 100))
        exit_qty = min(exit_qty, position["remaining_qty"])
        
        parts = option_key.split('_')
        symbol = parts[0] if len(parts) > 0 else "SPY"
        expiry = parts[1] if len(parts) > 1 else ""
        strike = parts[2] if len(parts) > 2 else ""
        opt_type = parts[3] if len(parts) > 3 else ""

        stc_msg = f"STC {exit_qty} {symbol} {expiry} {strike}{opt_type} @ {exit_price} ({exit_reason})"
        
        result = {
            "action": "STC",
            "option_key": option_key,
            "formatted_message": stc_msg,
            "quantity": exit_qty,
            "exit_percentage": exit_pct,
            "exit_reason": exit_reason,
            "exit_price": exit_price,
            "is_risk_exit": True
        }
        
        if self.config.enable_forwarding and self.config.webhook_url:
            await self._forward_to_webhook(result)
        
        if self._on_risk_exit_callback:
            try:
                await self._on_risk_exit_callback(result)
            except Exception as e:
                print(f"[SPY-SNIPER] Risk exit callback error: {e}")
        
        position["remaining_qty"] -= exit_qty
        position["remaining_pct"] -= exit_pct
        
        if position["remaining_qty"] <= 0:
            del self.position_tracker.positions[option_key]
            print(f"[SPY-SNIPER] Position closed: {option_key}")
        else:
            print(f"[SPY-SNIPER] Position reduced: {option_key} ({position['remaining_qty']} remaining)")
    
    def get_open_positions(self) -> Dict[str, Dict]:
        """Get all open positions being tracked."""
        return self.position_tracker.get_all_positions()
    
    def get_position(self, option_key: str) -> Optional[Dict]:
        """Get a specific position."""
        return self.position_tracker.get_position(option_key)
    
    def startup_reconcile(self):
        """Reconcile state on startup - sync ledger positions to price monitor."""
        try:
            synced = self.price_monitor.sync_from_ledger()
            print(f"[SPY-SNIPER] ✓ Startup reconciliation: {synced} positions synced to price monitor")
            return synced
        except Exception as e:
            print(f"[SPY-SNIPER] Startup reconciliation error: {e}")
            return 0


_service_instance: Optional[SpySniperWebhookService] = None


def get_spy_sniper_service() -> SpySniperWebhookService:
    """Get the global spy-sniper webhook service instance."""
    global _service_instance
    if _service_instance is None:
        _service_instance = SpySniperWebhookService()
    return _service_instance


def configure_spy_sniper_service(config: SpySniperConfig):
    """Configure the global spy-sniper service."""
    service = get_spy_sniper_service()
    service.configure(config)
    return service


async def process_spy_sniper_embed(
    embed_title: str,
    embed_description: str,
    message_id: str,
    channel_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Convenience function to process a spy-sniper embed.
    
    Args:
        embed_title: The embed title
        embed_description: The embed description
        message_id: Discord message ID
        channel_id: Optional channel ID
        
    Returns:
        Processing result or None
    """
    service = get_spy_sniper_service()
    return await service.process_message(
        embed_title=embed_title,
        embed_description=embed_description,
        message_id=message_id,
        channel_id=channel_id
    )
