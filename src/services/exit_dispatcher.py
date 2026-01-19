"""
Exit Dispatcher Service
========================
Unified exit routing for both trader signals and risk-triggered exits.

Features:
- Routes exits to webhook OR destination channel based on mapping config
- Exit Arbiter integration to prevent double-sells
- Idempotent with option_key + exit_reason deduplication
- P&L tracking for each exit
- Multi-broker support with per-broker routing
"""

import asyncio
import aiohttp
from datetime import datetime
from typing import Optional, Dict, Any, List, Callable, Awaitable
from dataclasses import dataclass

from src.services.position_ledger import (
    get_position_ledger,
    PositionLedger,
    LedgerPosition,
    PartialExit,
    ExitReason
)


@dataclass
class ExitRequest:
    """Request to exit a position."""
    option_key: str
    exit_qty: int
    exit_price: float
    exit_reason: str
    message_id: str = ""
    broker_id: str = ""
    account_id: str = ""
    channel_id: str = ""
    is_risk_triggered: bool = False
    destination_type: str = "webhook"
    destination_url: str = ""
    destination_channel_id: str = ""


@dataclass
class ExitResult:
    """Result of an exit attempt."""
    success: bool
    message: str
    exit_qty: int = 0
    exit_pnl_dollar: float = 0.0
    exit_pnl_pct: float = 0.0
    partial_exit: Optional[PartialExit] = None


class ExitDispatcher:
    """
    Unified exit dispatcher for all position exits.
    
    Handles:
    - Trader signal exits (STC from source channel)
    - Risk-triggered exits (PT, SL, trailing stop)
    - Manual exits
    
    Routes to:
    - Webhook URL
    - Destination Discord channel
    - Broker execution (via callback)
    """
    
    def __init__(self):
        self.ledger = get_position_ledger()
        self._session: Optional[aiohttp.ClientSession] = None
        self._processed_exits: set = set()
        
        self._on_broker_exit: Optional[Callable[[ExitRequest, LedgerPosition], Awaitable[bool]]] = None
        self._on_channel_post: Optional[Callable[[str, str], Awaitable[bool]]] = None
    
    def set_broker_exit_callback(self, callback: Callable[[ExitRequest, LedgerPosition], Awaitable[bool]]):
        """Set callback for broker execution of exits."""
        self._on_broker_exit = callback
    
    def set_channel_post_callback(self, callback: Callable[[str, str], Awaitable[bool]]):
        """Set callback for posting to Discord channels."""
        self._on_channel_post = callback
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
    
    async def close(self):
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()
    
    def _get_dedupe_key(self, request: ExitRequest) -> str:
        """Generate deduplication key for exit with broker/account isolation."""
        msg_or_ts = request.message_id if request.message_id else datetime.now().strftime('%Y%m%d%H%M%S')
        return f"{request.option_key}_{request.broker_id}_{request.account_id}_{request.exit_reason}_{msg_or_ts}"
    
    def is_duplicate_exit(self, request: ExitRequest) -> bool:
        """Check if this exit was already processed."""
        key = self._get_dedupe_key(request)
        return key in self._processed_exits
    
    def mark_exit_processed(self, request: ExitRequest):
        """Mark exit as processed."""
        key = self._get_dedupe_key(request)
        self._processed_exits.add(key)
    
    async def dispatch_exit(self, request: ExitRequest) -> ExitResult:
        """
        Dispatch an exit request through the unified pipeline.
        
        Steps:
        1. Acquire exit lock (via arbiter)
        2. Validate position exists and has quantity
        3. Record exit in ledger
        4. Route to destination (webhook/channel)
        5. Trigger broker execution if enabled
        """
        if self.is_duplicate_exit(request):
            return ExitResult(
                success=False,
                message=f"Duplicate exit skipped: {request.option_key}"
            )
        
        position = self.ledger.get_position_by_key(
            request.option_key,
            request.broker_id,
            request.account_id
        )
        
        if not position:
            return ExitResult(
                success=False,
                message=f"No position found: {request.option_key}"
            )
        
        if position.remaining_qty <= 0:
            return ExitResult(
                success=False,
                message=f"Position already closed: {request.option_key}"
            )
        
        try:
            locked = await self.ledger.exit_arbiter.acquire_exit_lock(
                request.option_key, request.broker_id, request.account_id
            )
            if not locked:
                return ExitResult(
                    success=False,
                    message=f"Exit already in progress: {request.option_key}"
                )
        except asyncio.TimeoutError:
            return ExitResult(
                success=False,
                message=f"Could not acquire exit lock: {request.option_key}"
            )
        
        try:
            actual_qty = min(request.exit_qty, position.remaining_qty)
            
            partial_exit = self.ledger.record_partial_exit(
                position_id=position.id or 0,
                exit_qty=actual_qty,
                exit_price=request.exit_price,
                exit_reason=request.exit_reason,
                message_id=request.message_id
            )
            
            if not partial_exit:
                return ExitResult(
                    success=False,
                    message=f"Failed to record exit: {request.option_key}"
                )
            
            stc_message = self._format_stc_message(request, position, partial_exit)
            
            if request.destination_type == "webhook" and request.destination_url:
                await self._post_to_webhook(request.destination_url, stc_message)
            elif request.destination_type == "channel" and request.destination_channel_id:
                if self._on_channel_post:
                    await self._on_channel_post(request.destination_channel_id, stc_message)
            
            if self._on_broker_exit:
                try:
                    await self._on_broker_exit(request, position)
                except Exception as e:
                    print(f"[EXIT-DISPATCH] Broker execution error: {e}")
            
            self.mark_exit_processed(request)
            
            print(f"[EXIT-DISPATCH] ✓ {request.exit_reason} exit: {actual_qty} {request.option_key} "
                  f"@ ${request.exit_price:.2f} | P&L: ${partial_exit.exit_pnl_dollar:.2f} "
                  f"({partial_exit.exit_pnl_pct:.1f}%)")
            
            return ExitResult(
                success=True,
                message=f"Exit successful: {request.option_key}",
                exit_qty=actual_qty,
                exit_pnl_dollar=partial_exit.exit_pnl_dollar,
                exit_pnl_pct=partial_exit.exit_pnl_pct,
                partial_exit=partial_exit
            )
            
        finally:
            lock = self.ledger.exit_arbiter.get_lock(
                request.option_key, request.broker_id, request.account_id
            )
            if lock.locked():
                lock.release()
    
    def _format_stc_message(
        self, 
        request: ExitRequest, 
        position: LedgerPosition,
        exit: PartialExit
    ) -> str:
        """Format STC message for webhook/channel posting."""
        reason_tag = f"({request.exit_reason})" if request.is_risk_triggered else ""
        pnl_emoji = "🟢" if exit.exit_pnl_pct >= 0 else "🔴"
        
        msg = f"STC {exit.exit_qty} {position.symbol} {position.expiry} " \
              f"{position.strike}{position.option_type} @ {request.exit_price:.2f} " \
              f"{pnl_emoji} {exit.exit_pnl_pct:.1f}% {reason_tag}"
        
        return msg.strip()
    
    async def _post_to_webhook(self, webhook_url: str, message: str) -> bool:
        """Post message to webhook URL."""
        if not webhook_url:
            return False
        
        try:
            session = await self._get_session()
            async with session.post(
                webhook_url,
                json={"content": message}
            ) as resp:
                if resp.status in (200, 204):
                    print(f"[EXIT-DISPATCH] ✓ Posted to webhook: {message[:50]}")
                    return True
                else:
                    print(f"[EXIT-DISPATCH] Webhook failed: HTTP {resp.status}")
                    return False
        except Exception as e:
            print(f"[EXIT-DISPATCH] Webhook error: {e}")
            return False
    
    async def dispatch_risk_exit(
        self,
        option_key: str,
        exit_reason: str,
        exit_price: float,
        exit_pct: int = 100,
        broker_id: str = "",
        account_id: str = "",
        destination_url: str = "",
        destination_channel_id: str = ""
    ) -> ExitResult:
        """
        Dispatch a risk-triggered exit (PT/SL/trailing stop).
        
        Called by the risk monitor when exit conditions are met.
        """
        position = self.ledger.get_position_by_key(option_key, broker_id, account_id)
        
        if not position:
            return ExitResult(success=False, message=f"Position not found: {option_key}")
        
        exit_qty = max(1, int(position.entry_qty * exit_pct / 100))
        exit_qty = min(exit_qty, position.remaining_qty)
        
        request = ExitRequest(
            option_key=option_key,
            exit_qty=exit_qty,
            exit_price=exit_price,
            exit_reason=exit_reason,
            broker_id=broker_id,
            account_id=account_id,
            channel_id=position.channel_id,
            is_risk_triggered=True,
            destination_type="webhook" if destination_url else "channel",
            destination_url=destination_url,
            destination_channel_id=destination_channel_id
        )
        
        return await self.dispatch_exit(request)
    
    async def dispatch_signal_exit(
        self,
        option_key: str,
        exit_qty: int,
        exit_price: float,
        message_id: str,
        broker_id: str = "",
        account_id: str = "",
        destination_url: str = "",
        destination_channel_id: str = ""
    ) -> ExitResult:
        """
        Dispatch a trader-signal exit (STC from source channel).
        """
        request = ExitRequest(
            option_key=option_key,
            exit_qty=exit_qty,
            exit_price=exit_price,
            exit_reason=ExitReason.SIGNAL.value,
            message_id=message_id,
            broker_id=broker_id,
            account_id=account_id,
            is_risk_triggered=False,
            destination_type="webhook" if destination_url else "channel",
            destination_url=destination_url,
            destination_channel_id=destination_channel_id
        )
        
        return await self.dispatch_exit(request)


_dispatcher_instance: Optional[ExitDispatcher] = None


def get_exit_dispatcher() -> ExitDispatcher:
    """Get the global exit dispatcher instance."""
    global _dispatcher_instance
    if _dispatcher_instance is None:
        _dispatcher_instance = ExitDispatcher()
    return _dispatcher_instance
