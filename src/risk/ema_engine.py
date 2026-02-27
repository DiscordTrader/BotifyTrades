"""
EMA-5 Candlestick Risk Engine
==============================
Builds 1-min/5-min OHLC candles from WebSocket streaming ticks,
computes EMA, and evaluates exit/escalation signals for positions.

Components:
- CandleAggregator: Per-symbol candle builder from tick data (thread-safe)
- EMAEngine: Rolling EMA computation with SMA seeding
- EMAExitEvaluator: Pure function for exit/escalate/hold decisions
- CandlePreWarmService: Singleton service managing candle/EMA state for all symbols
"""

import threading
import time
import math
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any, Callable, Tuple
from enum import Enum
from collections import deque


PRE_WARM_SYMBOLS = ['SPY', 'QQQ', 'SPX', 'NDX']
MAX_TRACKED_SYMBOLS = 50
STALE_TICK_THRESHOLD_SECONDS = 120


@dataclass
class Candle:
    open: float
    high: float
    low: float
    close: float
    timestamp: float
    tick_count: int = 0
    finalized: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            'timestamp': self.timestamp,
            'tick_count': self.tick_count,
            'finalized': self.finalized
        }


@dataclass
class EMAState:
    value: Optional[float] = None
    cross_state: str = 'seeding'
    candles_count: int = 0
    last_candle: Optional[Candle] = None
    last_candle_time: Optional[float] = None
    seeded: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            'ema_value': self.value,
            'cross_state': self.cross_state,
            'candles_count': self.candles_count,
            'last_candle': self.last_candle.to_dict() if self.last_candle else None,
            'last_candle_time': self.last_candle_time,
            'seeded': self.seeded
        }


class EMADecision(Enum):
    HOLD = 'hold'
    EXIT = 'exit'
    ESCALATE = 'escalate'
    NO_TREND_EXIT = 'no_trend_exit'
    NO_TREND_TICK = 'no_trend_tick'
    NOT_READY = 'not_ready'


@dataclass
class EMAEvalResult:
    decision: EMADecision
    reason: str = ''
    new_stop_price: Optional[float] = None
    ema_value: Optional[float] = None
    candle: Optional[Candle] = None


def _get_candle_boundary(timestamp: float, timeframe_minutes: int) -> float:
    dt = datetime.fromtimestamp(timestamp)
    minute_of_day = dt.hour * 60 + dt.minute
    boundary_minute = (minute_of_day // timeframe_minutes) * timeframe_minutes
    boundary_dt = dt.replace(hour=boundary_minute // 60, minute=boundary_minute % 60, second=0, microsecond=0)
    return boundary_dt.timestamp()


def _is_market_hours(timestamp: float, extended_hours: bool = False) -> bool:
    try:
        from src.services.market_hours import is_market_open
        return is_market_open()
    except Exception:
        pass
    dt = datetime.fromtimestamp(timestamp)
    if dt.weekday() >= 5:
        return False
    hour = dt.hour
    minute = dt.minute
    time_minutes = hour * 60 + minute
    if extended_hours:
        return 240 <= time_minutes < 1200
    return 570 <= time_minutes < 960


class CandleAggregator:
    def __init__(self, timeframe_minutes: int = 5, extended_hours: bool = False):
        self._timeframe = timeframe_minutes
        self._extended_hours = extended_hours
        self._symbols: Dict[str, Dict[str, Any]] = {}
        self._locks: Dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()
        self._on_candle_callbacks: List[Callable] = []
        self._last_reset_date: Optional[str] = None

    def _get_lock(self, symbol: str) -> threading.Lock:
        with self._global_lock:
            if symbol not in self._locks:
                self._locks[symbol] = threading.Lock()
            return self._locks[symbol]

    def _get_symbol_state(self, symbol: str) -> Dict[str, Any]:
        with self._global_lock:
            if symbol not in self._symbols:
                self._symbols[symbol] = {
                    'current_candle': None,
                    'current_boundary': None,
                    'completed_candles': deque(maxlen=200),
                    'last_tick_time': None,
                    'stale': False,
                    'tick_count': 0
                }
            return self._symbols[symbol]

    def on_candle_complete(self, callback: Callable):
        self._on_candle_callbacks.append(callback)

    def process_tick(self, symbol: str, price: float, timestamp: Optional[float] = None):
        symbol = symbol.upper()
        ts = timestamp or time.time()

        if not _is_market_hours(ts, self._extended_hours):
            return

        self._check_daily_reset(ts)

        lock = self._get_lock(symbol)
        with lock:
            state = self._get_symbol_state(symbol)
            state['last_tick_time'] = ts
            state['stale'] = False
            state['tick_count'] += 1

            boundary = _get_candle_boundary(ts, self._timeframe)

            if state['current_boundary'] is not None and boundary > state['current_boundary']:
                if state['current_candle'] is not None:
                    self._finalize_candle(symbol, state)

            if state['current_candle'] is None:
                state['current_candle'] = Candle(
                    open=price, high=price, low=price, close=price,
                    timestamp=boundary, tick_count=1
                )
                state['current_boundary'] = boundary
            else:
                candle = state['current_candle']
                candle.high = max(candle.high, price)
                candle.low = min(candle.low, price)
                candle.close = price
                candle.tick_count += 1

    def process_historical_candles(self, symbol: str, candles: List[Dict[str, Any]]):
        symbol = symbol.upper()
        lock = self._get_lock(symbol)
        with lock:
            state = self._get_symbol_state(symbol)
            for c in candles:
                candle = Candle(
                    open=c['open'], high=c['high'], low=c['low'], close=c['close'],
                    timestamp=c.get('timestamp', 0), tick_count=0, finalized=True
                )
                state['completed_candles'].append(candle)
            for cb in self._on_candle_callbacks:
                try:
                    cb(symbol, list(state['completed_candles']))
                except Exception as e:
                    print(f"[EMA] Candle callback error for {symbol}: {e}")

    def _finalize_candle(self, symbol: str, state: Dict[str, Any]):
        candle = state['current_candle']
        if candle is None:
            return
        candle.finalized = True
        state['completed_candles'].append(candle)
        state['current_candle'] = None

        for cb in self._on_candle_callbacks:
            try:
                cb(symbol, [candle])
            except Exception as e:
                print(f"[EMA] Candle callback error for {symbol}: {e}")

    def get_completed_candles(self, symbol: str) -> List[Candle]:
        symbol = symbol.upper()
        lock = self._get_lock(symbol)
        with lock:
            state = self._get_symbol_state(symbol)
            return list(state['completed_candles'])

    def get_current_candle(self, symbol: str) -> Optional[Candle]:
        symbol = symbol.upper()
        lock = self._get_lock(symbol)
        with lock:
            state = self._get_symbol_state(symbol)
            return state['current_candle']

    def is_stale(self, symbol: str) -> bool:
        symbol = symbol.upper()
        lock = self._get_lock(symbol)
        with lock:
            state = self._get_symbol_state(symbol)
            if state['last_tick_time'] is None:
                return True
            return (time.time() - state['last_tick_time']) > STALE_TICK_THRESHOLD_SECONDS

    def reset(self, symbol: Optional[str] = None):
        if symbol:
            symbol = symbol.upper()
            lock = self._get_lock(symbol)
            with lock:
                if symbol in self._symbols:
                    self._symbols[symbol] = {
                        'current_candle': None,
                        'current_boundary': None,
                        'completed_candles': deque(maxlen=200),
                        'last_tick_time': None,
                        'stale': False,
                        'tick_count': 0
                    }
        else:
            with self._global_lock:
                for sym in list(self._symbols.keys()):
                    self._symbols[sym] = {
                        'current_candle': None,
                        'current_boundary': None,
                        'completed_candles': deque(maxlen=200),
                        'last_tick_time': None,
                        'stale': False,
                        'tick_count': 0
                    }

    def _check_daily_reset(self, timestamp: float):
        dt = datetime.fromtimestamp(timestamp)
        date_str = dt.strftime('%Y-%m-%d')
        reset_hour = 4 if self._extended_hours else 9
        reset_minute = 0 if self._extended_hours else 30

        if self._last_reset_date != date_str:
            if dt.hour == reset_hour and dt.minute >= reset_minute:
                self._last_reset_date = date_str
                self.reset()
                print(f"[EMA] Daily session reset at {dt.strftime('%H:%M:%S')}")

    def get_symbol_count(self) -> int:
        with self._global_lock:
            return len(self._symbols)


class EMAEngine:
    def __init__(self, period: int = 5):
        self._period = period
        self._k = 2.0 / (period + 1)
        self._symbols: Dict[str, EMAState] = {}
        self._close_history: Dict[str, List[float]] = {}
        self._locks: Dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()

    def _get_lock(self, symbol: str) -> threading.Lock:
        with self._global_lock:
            if symbol not in self._locks:
                self._locks[symbol] = threading.Lock()
            return self._locks[symbol]

    def process_candles(self, symbol: str, candles: List[Candle]):
        symbol = symbol.upper()
        lock = self._get_lock(symbol)
        with lock:
            if symbol not in self._symbols:
                self._symbols[symbol] = EMAState()
            state = self._symbols[symbol]

            if symbol not in self._close_history:
                self._close_history[symbol] = []
            history = self._close_history[symbol]

            for candle in candles:
                if not candle.finalized:
                    continue
                state.candles_count += 1
                state.last_candle = candle
                state.last_candle_time = candle.timestamp
                history.append(candle.close)

                if state.candles_count < self._period:
                    pass
                elif state.candles_count == self._period:
                    sma = sum(history[-self._period:]) / self._period
                    state.value = sma
                    state.seeded = True
                    if candle.close > state.value:
                        state.cross_state = 'above'
                    elif candle.close < state.value:
                        state.cross_state = 'below'
                    print(f"[EMA] {symbol}: EMA({self._period}) seeded at {state.value:.4f} (SMA of first {self._period} candles)")
                else:
                    if state.value is not None:
                        state.value = candle.close * self._k + state.value * (1 - self._k)
                        if candle.close > state.value:
                            state.cross_state = 'above'
                        elif candle.close < state.value:
                            state.cross_state = 'below'

    def seed_from_candles(self, symbol: str, candles: List[Candle]):
        symbol = symbol.upper()
        lock = self._get_lock(symbol)
        with lock:
            if symbol not in self._symbols:
                self._symbols[symbol] = EMAState()
            state = self._symbols[symbol]
            state.candles_count = 0
            state.value = None
            state.seeded = False
            state.cross_state = 'seeding'
            self._close_history[symbol] = [c.close for c in candles]

            for candle in candles:
                state.candles_count += 1
                state.last_candle = candle
                state.last_candle_time = candle.timestamp

                if state.candles_count < self._period:
                    continue
                elif state.candles_count == self._period:
                    closes = [c.close for c in candles[:self._period]]
                    sma = sum(closes) / len(closes)
                    state.value = sma
                    state.seeded = True
                else:
                    if state.value is not None:
                        state.value = candle.close * self._k + state.value * (1 - self._k)

            if state.seeded and state.last_candle and state.value is not None:
                if state.last_candle.close > state.value:
                    state.cross_state = 'above'
                elif state.last_candle.close < state.value:
                    state.cross_state = 'below'
                print(f"[EMA] {symbol}: Pre-seeded EMA({self._period}) = {state.value:.4f} from {len(candles)} historical candles, state={state.cross_state}")

    def get_state(self, symbol: str) -> EMAState:
        symbol = symbol.upper()
        lock = self._get_lock(symbol)
        with lock:
            if symbol not in self._symbols:
                return EMAState()
            s = self._symbols[symbol]
            return EMAState(
                value=s.value,
                cross_state=s.cross_state,
                candles_count=s.candles_count,
                last_candle=s.last_candle,
                last_candle_time=s.last_candle_time,
                seeded=s.seeded
            )

    def reset(self, symbol: Optional[str] = None):
        if symbol:
            symbol = symbol.upper()
            lock = self._get_lock(symbol)
            with lock:
                self._symbols.pop(symbol, None)
                self._close_history.pop(symbol, None)
        else:
            with self._global_lock:
                self._symbols.clear()
                self._close_history.clear()


class EMAExitEvaluator:
    @staticmethod
    def evaluate(
        position_direction: str,
        ema_state: EMAState,
        config: Dict[str, Any]
    ) -> EMAEvalResult:
        if not ema_state.seeded or ema_state.value is None:
            return EMAEvalResult(decision=EMADecision.NOT_READY, reason="EMA not seeded yet")

        if ema_state.cross_state == 'frozen':
            return EMAEvalResult(decision=EMADecision.NOT_READY, reason="EMA frozen (hub disconnected)")

        candle = ema_state.last_candle
        if candle is None:
            return EMAEvalResult(decision=EMADecision.NOT_READY, reason="No completed candle")

        ema_val = ema_state.value
        buffer_pct = config.get('ema_buffer_pct', 0.1) / 100
        exit_enabled = config.get('ema_exit_enabled', True)
        escalation_enabled = config.get('ema_escalation_enabled', True)
        no_trend_candles = config.get('ema_no_trend_candles', 3)
        no_trend_count = config.get('ema_no_trend_count', 0)

        direction = position_direction.upper()
        is_long = direction in ('C', 'CALL', 'STOCK', 'LONG')

        if is_long:
            favorable_side = candle.close > ema_val
            cross_through = candle.open >= ema_val and candle.close < ema_val

            if exit_enabled and cross_through:
                return EMAEvalResult(
                    decision=EMADecision.EXIT,
                    reason=f"EMA cross-down: candle O={candle.open:.2f} >= EMA({ema_val:.2f}), C={candle.close:.2f} < EMA",
                    ema_value=ema_val,
                    candle=candle
                )

            if favorable_side and escalation_enabled:
                new_stop = ema_val * (1 - buffer_pct)
                return EMAEvalResult(
                    decision=EMADecision.ESCALATE,
                    reason=f"EMA escalation: stop → ${new_stop:.2f} (EMA={ema_val:.2f} - {buffer_pct*100:.1f}%)",
                    new_stop_price=new_stop,
                    ema_value=ema_val,
                    candle=candle
                )

            if not favorable_side and no_trend_candles > 0:
                new_count = no_trend_count + 1
                if new_count >= no_trend_candles:
                    return EMAEvalResult(
                        decision=EMADecision.NO_TREND_EXIT,
                        reason=f"No bullish trend after {new_count} candles (close below EMA for {direction})",
                        ema_value=ema_val,
                        candle=candle
                    )
                else:
                    return EMAEvalResult(
                        decision=EMADecision.NO_TREND_TICK,
                        reason=f"Unfavorable candle {new_count}/{no_trend_candles} (close below EMA for {direction})",
                        ema_value=ema_val,
                        candle=candle
                    )
        else:
            favorable_side = candle.close < ema_val
            cross_through = candle.open <= ema_val and candle.close > ema_val

            if exit_enabled and cross_through:
                return EMAEvalResult(
                    decision=EMADecision.EXIT,
                    reason=f"EMA cross-up: candle O={candle.open:.2f} <= EMA({ema_val:.2f}), C={candle.close:.2f} > EMA",
                    ema_value=ema_val,
                    candle=candle
                )

            if favorable_side and escalation_enabled:
                new_stop = ema_val * (1 + buffer_pct)
                return EMAEvalResult(
                    decision=EMADecision.ESCALATE,
                    reason=f"EMA escalation: stop → ${new_stop:.2f} (EMA={ema_val:.2f} + {buffer_pct*100:.1f}%)",
                    new_stop_price=new_stop,
                    ema_value=ema_val,
                    candle=candle
                )

            if not favorable_side and no_trend_candles > 0:
                new_count = no_trend_count + 1
                if new_count >= no_trend_candles:
                    return EMAEvalResult(
                        decision=EMADecision.NO_TREND_EXIT,
                        reason=f"No bearish trend after {new_count} candles (close above EMA for {direction})",
                        ema_value=ema_val,
                        candle=candle
                    )
                else:
                    return EMAEvalResult(
                        decision=EMADecision.NO_TREND_TICK,
                        reason=f"Unfavorable candle {new_count}/{no_trend_candles} (close above EMA for {direction})",
                        ema_value=ema_val,
                        candle=candle
                    )

        return EMAEvalResult(decision=EMADecision.HOLD, reason="No EMA signal", ema_value=ema_val)


class CandlePreWarmService:
    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._aggregators: Dict[str, CandleAggregator] = {}
        self._ema_engines: Dict[str, EMAEngine] = {}
        self._tracked_symbols: Dict[str, Dict[str, Any]] = {}
        self._dynamic_symbols: set = set()
        self._hubs: List[Any] = []
        self._running = False
        self._lock = threading.Lock()
        self._global_enabled = True
        print("[EMA] CandlePreWarmService initialized")

    def start(self, hubs: List[Any] = None):
        if not self._global_enabled:
            print("[EMA] Pre-warm service disabled (global toggle OFF)")
            return

        self._running = True
        self._hubs = hubs or []

        for hub in self._hubs:
            try:
                hub.on('quote_updated', self._on_quote_updated)
                hub_name = type(hub).__name__
                print(f"[EMA] Connected to {hub_name} for tick data")
            except Exception as e:
                print(f"[EMA] Failed to connect to hub: {e}")

        for symbol in PRE_WARM_SYMBOLS:
            self._ensure_tracking(symbol, is_prewarm=True)
            self._fetch_historical_candles(symbol)

        print(f"[EMA] Pre-warm service started - tracking {', '.join(PRE_WARM_SYMBOLS)}")

    def stop(self):
        self._running = False
        print("[EMA] Pre-warm service stopped")

    def set_global_enabled(self, enabled: bool):
        self._global_enabled = enabled
        if not enabled:
            print("[EMA] Global EMA toggle set to OFF")
        else:
            print("[EMA] Global EMA toggle set to ON")

    def is_global_enabled(self) -> bool:
        return self._global_enabled

    def subscribe_symbol(self, symbol: str, timeframe: int = 5, period: int = 5) -> bool:
        symbol = symbol.upper()
        with self._lock:
            if symbol in self._tracked_symbols:
                return True
            if len(self._tracked_symbols) >= MAX_TRACKED_SYMBOLS:
                print(f"[EMA] Cannot subscribe {symbol}: max {MAX_TRACKED_SYMBOLS} symbols reached")
                return False

        self._ensure_tracking(symbol, is_prewarm=False, timeframe=timeframe, period=period)
        self._dynamic_symbols.add(symbol)
        self._fetch_historical_candles(symbol)
        print(f"[EMA] Dynamically subscribed {symbol} (timeframe={timeframe}m, period={period})")
        return True

    def unsubscribe_symbol(self, symbol: str):
        symbol = symbol.upper()
        if symbol in PRE_WARM_SYMBOLS:
            return

        with self._lock:
            self._tracked_symbols.pop(symbol, None)
            self._aggregators.pop(symbol, None)
            self._ema_engines.pop(symbol, None)
            self._dynamic_symbols.discard(symbol)
        print(f"[EMA] Unsubscribed dynamic symbol {symbol}")

    def get_ema_state(self, symbol: str, timeframe: int = 5, period: int = 5) -> EMAState:
        symbol = symbol.upper()
        key = f"{symbol}_{timeframe}m_{period}"

        with self._lock:
            engine = self._ema_engines.get(key)
            if engine:
                state = engine.get_state(symbol)
                agg_key = f"{symbol}_{timeframe}m"
                agg = self._aggregators.get(agg_key)
                if agg and agg.is_stale(symbol):
                    state.cross_state = 'frozen'
                return state

        return EMAState()

    def is_tracking(self, symbol: str) -> bool:
        symbol = symbol.upper()
        with self._lock:
            return symbol in self._tracked_symbols

    def get_tracked_symbols(self) -> List[str]:
        with self._lock:
            return list(self._tracked_symbols.keys())

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            status = {
                'running': self._running,
                'global_enabled': self._global_enabled,
                'total_symbols': len(self._tracked_symbols),
                'prewarm_symbols': [s for s in PRE_WARM_SYMBOLS if s in self._tracked_symbols],
                'dynamic_symbols': list(self._dynamic_symbols),
                'hubs_connected': len(self._hubs),
                'symbols': {}
            }
            for sym, info in self._tracked_symbols.items():
                key = f"{sym}_{info['timeframe']}m_{info['period']}"
                engine = self._ema_engines.get(key)
                if engine:
                    ema_state = engine.get_state(sym)
                    status['symbols'][sym] = {
                        'timeframe': info['timeframe'],
                        'period': info['period'],
                        'ema_value': ema_state.value,
                        'cross_state': ema_state.cross_state,
                        'candles_count': ema_state.candles_count,
                        'seeded': ema_state.seeded,
                        'is_prewarm': info.get('is_prewarm', False)
                    }
            return status

    def _ensure_tracking(self, symbol: str, is_prewarm: bool = False,
                         timeframe: int = 5, period: int = 5):
        symbol = symbol.upper()
        agg_key = f"{symbol}_{timeframe}m"
        ema_key = f"{symbol}_{timeframe}m_{period}"

        with self._lock:
            if symbol in self._tracked_symbols:
                return

            self._tracked_symbols[symbol] = {
                'timeframe': timeframe,
                'period': period,
                'is_prewarm': is_prewarm,
                'agg_key': agg_key,
                'ema_key': ema_key
            }

            if agg_key not in self._aggregators:
                agg = CandleAggregator(timeframe_minutes=timeframe)
                self._aggregators[agg_key] = agg

            if ema_key not in self._ema_engines:
                engine = EMAEngine(period=period)
                self._ema_engines[ema_key] = engine

            agg = self._aggregators[agg_key]
            engine = self._ema_engines[ema_key]
            agg.on_candle_complete(lambda sym, candles, e=engine: e.process_candles(sym, candles))

    def _on_quote_updated(self, event_data: Dict[str, Any]):
        if not self._running or not self._global_enabled:
            return

        symbol = event_data.get('symbol', '').upper()
        quote = event_data.get('quote')

        with self._lock:
            info = self._tracked_symbols.get(symbol)
        if not info:
            return

        price = None
        if quote:
            if hasattr(quote, 'last_price') and quote.last_price:
                price = float(quote.last_price)
            elif hasattr(quote, 'close') and quote.close:
                price = float(quote.close)
            elif isinstance(quote, dict):
                price = float(quote.get('last_price') or quote.get('close') or quote.get('price', 0))

        if price and price > 0:
            agg_key = info['agg_key']
            agg = self._aggregators.get(agg_key)
            if agg:
                agg.process_tick(symbol, price)

    def _fetch_historical_candles(self, symbol: str):
        symbol = symbol.upper()
        info = self._tracked_symbols.get(symbol)
        if not info:
            return

        timeframe = info['timeframe']
        period = info['period']
        ema_key = info['ema_key']
        engine = self._ema_engines.get(ema_key)
        if not engine:
            return

        def _do_fetch():
            candles = self._try_broker_candles(symbol, timeframe)
            if candles and len(candles) >= period:
                candle_objects = []
                for c in candles:
                    candle_objects.append(Candle(
                        open=c['open'], high=c['high'], low=c['low'], close=c['close'],
                        timestamp=c.get('timestamp', 0), tick_count=0, finalized=True
                    ))
                engine.seed_from_candles(symbol, candle_objects)
                print(f"[EMA] Pre-seeded {symbol} with {len(candle_objects)} historical candles")
            else:
                count = len(candles) if candles else 0
                print(f"[EMA] {symbol}: Only {count} historical candles available, need {period} to seed. Will build from live ticks.")

        try:
            t = threading.Thread(target=_do_fetch, daemon=True, name=f"ema-preseed-{symbol}")
            t.start()
        except Exception as e:
            print(f"[EMA] Failed to start pre-seed thread for {symbol}: {e}")

    def _try_broker_candles(self, symbol: str, timeframe: int) -> Optional[List[Dict[str, Any]]]:
        for hub in self._hubs:
            try:
                if hasattr(hub, 'get_bars') or hasattr(hub, 'get_candles'):
                    method = getattr(hub, 'get_bars', None) or getattr(hub, 'get_candles', None)
                    if method:
                        result = method(symbol, interval=f"m{timeframe}", count=100)
                        if result:
                            return result
            except Exception:
                pass

        try:
            from src.services.webull_data_hub import get_webull_data_hub
            webull_hub = get_webull_data_hub()
            if webull_hub and hasattr(webull_hub, '_broker') and webull_hub._broker:
                broker = webull_hub._broker
                if hasattr(broker, 'get_bars'):
                    bars = broker.get_bars(symbol, interval=f"m{timeframe}", count=100)
                    if bars:
                        return bars
        except Exception:
            pass

        try:
            from src.services.schwab_data_hub import get_schwab_data_hub
            schwab_hub = get_schwab_data_hub()
            if schwab_hub and hasattr(schwab_hub, '_client'):
                client = schwab_hub._client
                if hasattr(client, 'get_price_history'):
                    import httpx
                    end = datetime.now()
                    start = end - timedelta(days=2)
                    freq_map = {1: '1', 2: '2', 3: '3', 5: '5'}
                    freq = freq_map.get(timeframe, '5')
                    result = client.get_price_history(
                        symbol, periodType='day', period=2,
                        frequencyType='minute', frequency=int(freq),
                        startDate=int(start.timestamp() * 1000),
                        endDate=int(end.timestamp() * 1000)
                    )
                    if result and hasattr(result, 'json'):
                        data = result.json()
                        candles_raw = data.get('candles', [])
                        candles = []
                        for c in candles_raw:
                            candles.append({
                                'open': c['open'], 'high': c['high'],
                                'low': c['low'], 'close': c['close'],
                                'timestamp': c.get('datetime', 0) / 1000
                            })
                        if candles:
                            return candles
        except Exception:
            pass

        print(f"[EMA] No historical candles available for {symbol} from any broker")
        return None

    def daily_reset(self):
        with self._lock:
            for sym, info in self._tracked_symbols.items():
                agg_key = info['agg_key']
                ema_key = info['ema_key']
                agg = self._aggregators.get(agg_key)
                if agg:
                    agg.reset(sym)
                engine = self._ema_engines.get(ema_key)
                if engine:
                    engine.reset(sym)
        print("[EMA] Daily reset complete - all candles and EMA states cleared")

        for symbol in PRE_WARM_SYMBOLS:
            self._fetch_historical_candles(symbol)


_candle_service: Optional[CandlePreWarmService] = None


def get_candle_service() -> CandlePreWarmService:
    global _candle_service
    if _candle_service is None:
        _candle_service = CandlePreWarmService()
    return _candle_service
