"""
Post-Trade Analysis Tracker
Schedules AI analysis at 30min, 1hr, and 1day intervals after trade execution
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
import os

@dataclass
class ExecutedTrade:
    """Represents an executed trade"""
    symbol: str
    action: str
    qty: int
    entry_price: float
    executed_at: datetime
    asset_type: str  # 'option' or 'stock'
    
    # Options-specific
    option_type: Optional[str] = None
    strike: Optional[float] = None
    expiry: Optional[str] = None
    expiry_year: Optional[int] = None  # For LEAPS and cross-year trades
    
    # Analysis tracking
    analyzed_30min: bool = False
    analyzed_1hr: bool = False
    analyzed_1day: bool = False
    
    def to_dict(self):
        """Convert to dictionary with datetime serialization"""
        data = asdict(self)
        data['executed_at'] = self.executed_at.isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: dict):
        """Create from dictionary with datetime deserialization"""
        data['executed_at'] = datetime.fromisoformat(data['executed_at'])
        return cls(**data)


class TradeTracker:
    """Tracks executed trades and schedules follow-up analysis"""
    
    def __init__(self, trade_analyzer=None, broker=None):
        """
        Initialize trade tracker
        
        Args:
            trade_analyzer: AI analyzer instance for follow-up analysis
            broker: Webull broker instance for price checking
        """
        self.trades: List[ExecutedTrade] = []
        self.trade_analyzer = trade_analyzer
        self.broker = broker
        self.storage_file = "executed_trades.json"
        self._lock = asyncio.Lock()  # Prevent race conditions on file writes
        self._load_trades()
    
    async def add_trade(self, sig: dict):
        """
        Add a newly executed trade for tracking
        
        Args:
            sig: Signal dictionary with trade details
        """
        trade = ExecutedTrade(
            symbol=sig['symbol'],
            action=sig['action'],
            qty=sig['qty'],
            entry_price=sig['price'],
            executed_at=datetime.now(),
            asset_type=sig.get('asset', 'stock'),
            option_type=sig.get('opt_type'),
            strike=sig.get('strike'),
            expiry=sig.get('expiry'),
            expiry_year=sig.get('expiry_year')  # Capture year for LEAPS
        )
        
        async with self._lock:
            self.trades.append(trade)
            await self._save_trades()
        
        trade_desc = self._format_trade(trade)
        print(f"[TRACKER] ✓ Trade added for follow-up analysis: {trade_desc}")
    
    def _format_trade(self, trade: ExecutedTrade) -> str:
        """Format trade for display"""
        if trade.asset_type == 'option':
            return f"{trade.action} {trade.qty} {trade.symbol} ${trade.strike}{trade.option_type} {trade.expiry} @${trade.entry_price}"
        else:
            return f"{trade.action} {trade.qty} {trade.symbol} @${trade.entry_price}"
    
    async def check_and_analyze(self):
        """Check all trades and run analysis for those due"""
        now = datetime.now()
        
        async with self._lock:
            trades_copy = list(self.trades)
        
        for trade in trades_copy:
            time_elapsed = now - trade.executed_at
            
            # Check 30-minute analysis
            if not trade.analyzed_30min and time_elapsed >= timedelta(minutes=30):
                await self._analyze_trade(trade, "30min")
                async with self._lock:
                    trade.analyzed_30min = True
                    await self._save_trades()
            
            # Check 1-hour analysis
            elif not trade.analyzed_1hr and time_elapsed >= timedelta(hours=1):
                await self._analyze_trade(trade, "1hr")
                async with self._lock:
                    trade.analyzed_1hr = True
                    await self._save_trades()
            
            # Check 1-day analysis
            elif not trade.analyzed_1day and time_elapsed >= timedelta(days=1):
                await self._analyze_trade(trade, "1day")
                async with self._lock:
                    trade.analyzed_1day = True
                    await self._save_trades()
        
        # Clean up trades older than 2 days that have all analysis done
        cutoff = now - timedelta(days=2)
        async with self._lock:
            self.trades = [
                t for t in self.trades
                if t.executed_at > cutoff or not (t.analyzed_30min and t.analyzed_1hr and t.analyzed_1day)
            ]
            await self._save_trades()
    
    async def _analyze_trade(self, trade: ExecutedTrade, interval: str):
        """
        Run AI analysis for a trade at specified interval
        
        Args:
            trade: The trade to analyze
            interval: Time interval (30min, 1hr, 1day)
        """
        if not self.trade_analyzer:
            return
        
        try:
            # Get current price
            current_price = await self._get_current_price(trade)
            
            # Calculate P&L
            if trade.action.upper() == 'BTO':
                pnl = current_price - trade.entry_price if current_price else 0
                direction_correct = pnl > 0
            else:  # STC
                pnl = trade.entry_price - current_price if current_price else 0
                direction_correct = pnl > 0
            
            trade_desc = self._format_trade(trade)
            
            print(f"\n{'='*70}")
            print(f"[AI FOLLOW-UP] {interval.upper()} Analysis")
            print(f"{'='*70}")
            print(f"Trade: {trade_desc}")
            print(f"Executed: {trade.executed_at.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"Entry Price: ${trade.entry_price:.2f}")
            
            if current_price:
                pnl_percent = (pnl / trade.entry_price) * 100
                print(f"Current Price: ${current_price:.2f}")
                print(f"P&L: ${pnl:.2f} ({pnl_percent:+.2f}%)")
                print(f"Direction: {'✓ CORRECT' if direction_correct else '✗ WRONG'}")
            else:
                print(f"Current Price: Unable to fetch")
            
            # Build analysis prompt
            prompt = self._build_followup_prompt(trade, interval, current_price, pnl, direction_correct)
            
            # Call AI analyzer
            await asyncio.to_thread(
                self._get_ai_analysis,
                prompt
            )
            
            print(f"{'='*70}\n")
            
        except Exception as e:
            print(f"[AI FOLLOW-UP] Error analyzing trade at {interval}: {e}")
    
    async def _get_current_price(self, trade: ExecutedTrade) -> Optional[float]:
        """Get current price for the traded asset"""
        if not self.broker or not self.broker._client:
            return None
        
        try:
            wb = self.broker._client
            
            if trade.asset_type == 'option':
                # Get current option price
                def fetch_option_price():
                    try:
                        from src.core.expiry import normalize_expiry_iso
                        expire_date_iso = normalize_expiry_iso(trade.expiry)
                        
                        # Normalize option_type: handle C/P or CALL/PUT
                        opt_type_upper = trade.option_type.upper()
                        if opt_type_upper in ('C', 'CALL'):
                            direction = 'call'
                        elif opt_type_upper in ('P', 'PUT'):
                            direction = 'put'
                        else:
                            print(f"[TRACKER] Unknown option type: {trade.option_type}")
                            return None
                        
                        try:
                            from src.services.webull_data_hub import get_webull_data_hub
                            import time as _time
                            hub = get_webull_data_hub()
                            cached_oid = hub.get_option_ticker_id(trade.symbol, float(trade.strike), expire_date_iso, trade.option_type.upper()[:1])
                            if cached_oid:
                                hub_quote = hub.get_quote(str(cached_oid))
                                if hub_quote and hub_quote.timestamp and (_time.time() - hub_quote.timestamp) < 10:
                                    if hub_quote.last > 0:
                                        print(f"[TRACKER] ✓ Hub-cached option price: {trade.symbol} ${trade.strike}{trade.option_type} = ${hub_quote.last}")
                                        return hub_quote.last
                        except Exception:
                            pass

                        data = wb.get_options_by_strike_and_expire_date(
                            stock=trade.symbol,
                            expireDate=expire_date_iso,  # Format: YYYY-MM-DD
                            strike=str(trade.strike),
                            direction=direction  # 'call' or 'put'
                        )
                        
                        # Extract current price from the option data
                        if data and len(data) > 0:
                            opt = data[0]
                            # Try to get the most recent price
                            price = opt.get('close') or opt.get('askList', [{}])[0].get('price') or opt.get('bidList', [{}])[0].get('price')
                            if price:
                                print(f"[TRACKER] ✓ Fetched option price: {trade.symbol} ${trade.strike}{trade.option_type} {trade.expiry} = ${price}")
                                return float(price)
                    except Exception as e:
                        print(f"[TRACKER] Option price fetch error: {e}")
                    return None
                
                return await asyncio.to_thread(fetch_option_price)
            else:
                def fetch_stock_price():
                    try:
                        from src.services.webull_data_hub import get_webull_data_hub
                        import time as _time
                        hub = get_webull_data_hub()
                        hub_quote = hub.get_quote(trade.symbol)
                        if hub_quote and hub_quote.timestamp and (_time.time() - hub_quote.timestamp) < 10:
                            if hub_quote.last > 0:
                                return hub_quote.last
                    except Exception:
                        pass
                    quote = wb.get_quote(trade.symbol)
                    if quote:
                        return float(quote.get('close', 0) or quote.get('last', 0) or 0)
                    return None
                
                return await asyncio.to_thread(fetch_stock_price)
        except Exception as e:
            print(f"[TRACKER] Warning: Could not fetch current price: {e}")
        
        return None
    
    def _build_followup_prompt(self, trade: ExecutedTrade, interval: str, 
                                current_price: Optional[float], pnl: float, 
                                direction_correct: bool) -> str:
        """Build AI prompt for follow-up analysis"""
        
        trade_desc = self._format_trade(trade)
        time_elapsed = datetime.now() - trade.executed_at
        
        prompt = f"""Analyze this executed trade after {interval}:

TRADE DETAILS:
- Signal: {trade_desc}
- Action: {trade.action}
- Entry: ${trade.entry_price:.2f}
- Quantity: {trade.qty} {'contracts' if trade.asset_type == 'option' else 'shares'}
- Executed: {trade.executed_at.strftime('%Y-%m-%d %H:%M:%S')}
- Time Elapsed: {time_elapsed}

CURRENT STATUS ({interval.upper()}):"""
        
        if current_price:
            pnl_percent = (pnl / trade.entry_price) * 100
            prompt += f"""
- Current Price: ${current_price:.2f}
- P&L: ${pnl:.2f} ({pnl_percent:+.2f}%)
- Direction: {'CORRECT - Trade moving as expected' if direction_correct else 'WRONG - Trade moving against position'}
"""
        else:
            prompt += f"""
- Current Price: Not available
- Direction: Cannot determine
"""
        
        prompt += f"""
Please provide a {interval} post-trade analysis:

1. Was the trade direction CORRECT? (Did it move the right way?)
2. What happened in the market during this {interval}?
3. Should the trader hold or consider closing?
4. Key levels to watch going forward

Keep it concise and actionable."""
        
        return prompt
    
    def _get_ai_analysis(self, prompt: str):
        """Get AI analysis (runs in thread)"""
        try:
            system_msg = "You are an expert trading analyst providing post-trade analysis. Focus on whether the trade direction was correct and what the trader should do next."
            ta = self.trade_analyzer

            if getattr(ta, '_provider', '') == 'gemini':
                response = ta.client.models.generate_content(
                    model=ta.model,
                    contents=f"{system_msg}\n\n{prompt}"
                )
                analysis = response.text
            elif getattr(ta, '_is_anthropic', False):
                response = ta.client.messages.create(
                    model=ta.model,
                    max_tokens=600,
                    temperature=0.7,
                    system=system_msg,
                    messages=[{"role": "user", "content": prompt}]
                )
                analysis = response.content[0].text
            else:
                response = ta.client.chat.completions.create(
                    model=ta.model,
                    messages=[
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.7,
                    max_tokens=600
                )
                analysis = response.choices[0].message.content
            print(f"\n{analysis}\n")
            
        except Exception as e:
            print(f"[AI] Analysis failed: {e}")
    
    async def _save_trades(self):
        """Save trades to disk"""
        def save():
            try:
                data = [t.to_dict() for t in self.trades]
                with open(self.storage_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2)
            except Exception as e:
                print(f"[TRACKER] Warning: Could not save trades: {e}")
        
        await asyncio.to_thread(save)
    
    def _load_trades(self):
        """Load trades from disk"""
        try:
            if os.path.exists(self.storage_file):
                with open(self.storage_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.trades = [ExecutedTrade.from_dict(t) for t in data]
                print(f"[TRACKER] Loaded {len(self.trades)} trades from storage")
        except Exception as e:
            print(f"[TRACKER] Warning: Could not load trades: {e}")
            self.trades = []
