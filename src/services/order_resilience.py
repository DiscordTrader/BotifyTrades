"""
Order Resilience Layer
======================
Universal, broker-agnostic order placement resilience for all 11 brokers.

3-Layer Architecture:
1. BrokerErrorClassifier - Standardizes broker-specific errors into 5 categories
2. OrderCircuitBreaker - Per broker+symbol circuit breaker (separate from channel circuit breaker)
3. OrderResilienceLayer - Orchestrates retry budgets, cancel-before-retry, and circuit breaking

Integration Point: execute_on_single_broker() in selfbot_webull.py
"""

import time
import threading
from typing import Dict, Optional, Any, Callable, Awaitable
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict, deque


class ErrorCategory(Enum):
    TRANSIENT_BUSY = 'transient_busy'
    RATE_LIMIT = 'rate_limit'
    PENDING_CONFLICT = 'pending_conflict'
    TOKEN_EXPIRED = 'token_expired'
    FATAL = 'fatal'
    SUCCESS = 'success'


class CircuitState(Enum):
    CLOSED = 'closed'
    OPEN = 'open'
    HALF_OPEN = 'half_open'


@dataclass
class BrokerThresholds:
    failures_to_open: int = 3
    window_seconds: float = 30.0
    open_duration_seconds: float = 45.0
    emergency_open_duration_seconds: float = 20.0
    half_open_max_probes: int = 1


BROKER_THRESHOLDS: Dict[str, BrokerThresholds] = {
    'webull': BrokerThresholds(failures_to_open=3, window_seconds=30, open_duration_seconds=45, emergency_open_duration_seconds=20),
    'webull_paper': BrokerThresholds(failures_to_open=3, window_seconds=30, open_duration_seconds=45, emergency_open_duration_seconds=20),
    'alpaca': BrokerThresholds(failures_to_open=4, window_seconds=30, open_duration_seconds=30, emergency_open_duration_seconds=15),
    'alpaca_paper': BrokerThresholds(failures_to_open=4, window_seconds=30, open_duration_seconds=30, emergency_open_duration_seconds=15),
    'schwab': BrokerThresholds(failures_to_open=3, window_seconds=60, open_duration_seconds=60, emergency_open_duration_seconds=30),
    'robinhood': BrokerThresholds(failures_to_open=2, window_seconds=60, open_duration_seconds=90, emergency_open_duration_seconds=45),
    'ibkr': BrokerThresholds(failures_to_open=5, window_seconds=10, open_duration_seconds=20, emergency_open_duration_seconds=10),
    'tastytrade': BrokerThresholds(failures_to_open=4, window_seconds=30, open_duration_seconds=30, emergency_open_duration_seconds=15),
    'questrade': BrokerThresholds(failures_to_open=3, window_seconds=30, open_duration_seconds=45, emergency_open_duration_seconds=20),
    'zerodha': BrokerThresholds(failures_to_open=3, window_seconds=30, open_duration_seconds=45, emergency_open_duration_seconds=20),
    'upstox': BrokerThresholds(failures_to_open=3, window_seconds=30, open_duration_seconds=45, emergency_open_duration_seconds=20),
    'dhanq': BrokerThresholds(failures_to_open=3, window_seconds=30, open_duration_seconds=45, emergency_open_duration_seconds=20),
}


class BrokerErrorClassifier:
    """
    Classifies broker-specific error responses into standardized ErrorCategory.
    Each broker has unique error codes/messages - this normalizes them.
    """

    WEBULL_TRANSIENT = {'trade.system.exception', 'trade.busy', 'system.busy'}
    WEBULL_TOKEN = {'trade.token.expire'}
    WEBULL_CONFLICT = {'ORDER_NOT_SUPPORT_REVERSE'}

    @classmethod
    def classify(cls, broker_name: str, result: Any) -> ErrorCategory:
        broker_key = cls._normalize_broker(broker_name)

        if cls._is_success(result):
            return ErrorCategory.SUCCESS

        error_msg = cls._extract_error_message(result)
        error_code = cls._extract_error_code(result)
        error_lower = error_msg.lower()

        if broker_key in ('webull', 'webull_paper'):
            return cls._classify_webull(error_code, error_lower)
        elif broker_key in ('alpaca', 'alpaca_paper'):
            return cls._classify_alpaca(error_code, error_lower, result)
        elif broker_key == 'schwab':
            return cls._classify_schwab(error_code, error_lower, result)
        elif broker_key == 'robinhood':
            return cls._classify_robinhood(error_code, error_lower)
        elif broker_key == 'ibkr':
            return cls._classify_ibkr(error_code, error_lower)
        elif broker_key == 'tastytrade':
            return cls._classify_tastytrade(error_code, error_lower)
        elif broker_key == 'questrade':
            return cls._classify_questrade(error_code, error_lower)
        elif broker_key in ('zerodha', 'upstox', 'dhanq'):
            return cls._classify_india(error_code, error_lower)
        else:
            return cls._classify_generic(error_code, error_lower)

    @classmethod
    def _normalize_broker(cls, broker_name: str) -> str:
        name = broker_name.lower().replace(' ', '_').replace('-', '_')
        for key in BROKER_THRESHOLDS:
            if key in name:
                return key
        return name

    @classmethod
    def _is_success(cls, result: Any) -> bool:
        if result is None:
            return False
        if hasattr(result, 'success'):
            return result.success
        if isinstance(result, dict):
            if result.get('success'):
                return True
            if result.get('orderId') and not result.get('msg'):
                return True
        return False

    @classmethod
    def _extract_error_message(cls, result: Any) -> str:
        if hasattr(result, 'message'):
            return str(result.message or '')
        if isinstance(result, dict):
            return str(result.get('msg', '') or result.get('message', '') or result.get('error', '') or '')
        return str(result) if result else ''

    @classmethod
    def _extract_error_code(cls, result: Any) -> str:
        if isinstance(result, dict):
            return str(result.get('code', '') or '')
        return ''

    @classmethod
    def _classify_webull(cls, code: str, msg: str) -> ErrorCategory:
        if code in cls.WEBULL_TOKEN:
            return ErrorCategory.TOKEN_EXPIRED
        if code in cls.WEBULL_TRANSIENT or ('system' in msg and 'busy' in msg):
            return ErrorCategory.TRANSIENT_BUSY
        if code in cls.WEBULL_CONFLICT or 'order_not_support_reverse' in msg:
            return ErrorCategory.PENDING_CONFLICT
        if 'rate' in msg and 'limit' in msg:
            return ErrorCategory.RATE_LIMIT
        return ErrorCategory.FATAL

    @classmethod
    def _classify_alpaca(cls, code: str, msg: str, result: Any) -> ErrorCategory:
        full_code = ''
        if isinstance(result, dict):
            full_code = str(result.get('code', ''))
        if hasattr(result, 'message'):
            full_code = str(getattr(result, 'code', ''))
        if '40310000' in full_code or 'held_for_orders' in msg:
            return ErrorCategory.PENDING_CONFLICT
        if '429' in code or 'too many requests' in msg or 'rate limit' in msg:
            return ErrorCategory.RATE_LIMIT
        if '401' in code or 'unauthorized' in msg or 'forbidden' in msg:
            return ErrorCategory.TOKEN_EXPIRED
        if 'timeout' in msg or 'connection' in msg or '500' in code or '503' in code or 'internal server' in msg:
            return ErrorCategory.TRANSIENT_BUSY
        return ErrorCategory.FATAL

    @classmethod
    def _classify_schwab(cls, code: str, msg: str, result: Any) -> ErrorCategory:
        if 'invalid_grant' in msg or '401' in code or 'unauthorized' in msg:
            return ErrorCategory.TOKEN_EXPIRED
        if '429' in code or 'retry-after' in msg or 'rate limit' in msg or 'too many' in msg:
            return ErrorCategory.RATE_LIMIT
        if 'timeout' in msg or 'connection' in msg or '500' in code or '503' in code or 'internal server' in msg:
            return ErrorCategory.TRANSIENT_BUSY
        return ErrorCategory.FATAL

    @classmethod
    def _classify_robinhood(cls, code: str, msg: str) -> ErrorCategory:
        if 'session' in msg and 'expired' in msg:
            return ErrorCategory.TOKEN_EXPIRED
        if 'throttle' in msg or 'rate limit' in msg or 'too many' in msg or '429' in code:
            return ErrorCategory.RATE_LIMIT
        if 'timeout' in msg or 'connection' in msg or '500' in code or '503' in code:
            return ErrorCategory.TRANSIENT_BUSY
        return ErrorCategory.FATAL

    @classmethod
    def _classify_ibkr(cls, code: str, msg: str) -> ErrorCategory:
        if 'not authenticated' in msg or 'auth' in msg and 'fail' in msg:
            return ErrorCategory.TOKEN_EXPIRED
        if 'pacing' in msg or 'rate' in msg or 'too many' in msg:
            return ErrorCategory.RATE_LIMIT
        if 'connection' in msg and ('lost' in msg or 'reset' in msg or 'refused' in msg):
            return ErrorCategory.TRANSIENT_BUSY
        if 'timeout' in msg or '500' in code or '503' in code:
            return ErrorCategory.TRANSIENT_BUSY
        return ErrorCategory.FATAL

    @classmethod
    def _classify_tastytrade(cls, code: str, msg: str) -> ErrorCategory:
        if 'session' in msg and ('expired' in msg or 'invalid' in msg):
            return ErrorCategory.TOKEN_EXPIRED
        if '429' in code or 'rate limit' in msg or 'too many' in msg:
            return ErrorCategory.RATE_LIMIT
        if 'timeout' in msg or 'connection' in msg or '500' in code or '503' in code:
            return ErrorCategory.TRANSIENT_BUSY
        return ErrorCategory.FATAL

    @classmethod
    def _classify_questrade(cls, code: str, msg: str) -> ErrorCategory:
        if 'token' in msg and ('expired' in msg or 'invalid' in msg):
            return ErrorCategory.TOKEN_EXPIRED
        if '429' in code or 'rate limit' in msg:
            return ErrorCategory.RATE_LIMIT
        if 'timeout' in msg or 'connection' in msg or '500' in code or '503' in code:
            return ErrorCategory.TRANSIENT_BUSY
        return ErrorCategory.FATAL

    @classmethod
    def _classify_india(cls, code: str, msg: str) -> ErrorCategory:
        if 'token' in msg and ('expired' in msg or 'invalid' in msg):
            return ErrorCategory.TOKEN_EXPIRED
        if 'auth' in msg and ('fail' in msg or 'invalid' in msg):
            return ErrorCategory.TOKEN_EXPIRED
        if '429' in code or 'rate limit' in msg or 'too many' in msg or 'throttle' in msg:
            return ErrorCategory.RATE_LIMIT
        if 'timeout' in msg or 'connection' in msg or '500' in code or '503' in code:
            return ErrorCategory.TRANSIENT_BUSY
        return ErrorCategory.FATAL

    @classmethod
    def _classify_generic(cls, code: str, msg: str) -> ErrorCategory:
        if 'token' in msg and 'expired' in msg:
            return ErrorCategory.TOKEN_EXPIRED
        if '429' in code or 'rate limit' in msg:
            return ErrorCategory.RATE_LIMIT
        if 'timeout' in msg or 'busy' in msg or '500' in code or '503' in code:
            return ErrorCategory.TRANSIENT_BUSY
        return ErrorCategory.FATAL


@dataclass
class SymbolCircuitState:
    state: CircuitState = CircuitState.CLOSED
    failure_timestamps: deque = field(default_factory=deque)
    opened_at: float = 0.0
    half_open_probes: int = 0
    last_error_category: Optional[ErrorCategory] = None
    total_opens: int = 0
    total_failures: int = 0


class OrderCircuitBreaker:
    """
    Per-broker+symbol circuit breaker for order placement.
    Separate from the channel-level CircuitBreaker in circuit_breaker.py.

    Keys: broker_name + symbol (+ strike/expiry/type for options)
    """

    def __init__(self):
        self._states: Dict[str, SymbolCircuitState] = {}
        self._lock = threading.Lock()

    def _make_key(self, broker_name: str, symbol: str, strike: float = None,
                  expiry: str = None, opt_type: str = None) -> str:
        broker = broker_name.lower().replace(' ', '_')
        parts = [broker, symbol.upper()]
        if strike and strike > 0:
            parts.append(f"{float(strike):.1f}")
        if expiry:
            parts.append(expiry)
        if opt_type:
            parts.append(opt_type.upper()[:1])
        return '|'.join(parts)

    def _get_thresholds(self, broker_name: str) -> BrokerThresholds:
        key = BrokerErrorClassifier._normalize_broker(broker_name)
        return BROKER_THRESHOLDS.get(key, BrokerThresholds())

    def check_allowed(self, broker_name: str, symbol: str, is_emergency: bool = False,
                      strike: float = None, expiry: str = None, opt_type: str = None) -> tuple:
        key = self._make_key(broker_name, symbol, strike, expiry, opt_type)
        thresholds = self._get_thresholds(broker_name)

        with self._lock:
            state = self._states.get(key)
            if not state:
                return (True, 'circuit_closed')

            now = time.time()

            if state.state == CircuitState.CLOSED:
                return (True, 'circuit_closed')

            if state.state == CircuitState.OPEN:
                duration = thresholds.emergency_open_duration_seconds if is_emergency else thresholds.open_duration_seconds
                elapsed = now - state.opened_at

                if elapsed >= duration:
                    state.state = CircuitState.HALF_OPEN
                    state.half_open_probes = 0
                    return (True, 'circuit_half_open_probe')

                remaining = duration - elapsed
                return (False, f'circuit_open ({remaining:.0f}s remaining)')

            if state.state == CircuitState.HALF_OPEN:
                if state.half_open_probes < thresholds.half_open_max_probes:
                    state.half_open_probes += 1
                    return (True, 'circuit_half_open_probe')
                return (False, 'circuit_half_open_max_probes')

        return (True, 'circuit_closed')

    def record_success(self, broker_name: str, symbol: str,
                       strike: float = None, expiry: str = None, opt_type: str = None):
        key = self._make_key(broker_name, symbol, strike, expiry, opt_type)
        with self._lock:
            state = self._states.get(key)
            if state:
                state.state = CircuitState.CLOSED
                state.failure_timestamps.clear()
                state.half_open_probes = 0

    def record_failure(self, broker_name: str, symbol: str, error_category: ErrorCategory,
                       strike: float = None, expiry: str = None, opt_type: str = None):
        if error_category in (ErrorCategory.SUCCESS, ErrorCategory.FATAL):
            return

        key = self._make_key(broker_name, symbol, strike, expiry, opt_type)
        thresholds = self._get_thresholds(broker_name)
        now = time.time()

        with self._lock:
            if key not in self._states:
                self._states[key] = SymbolCircuitState()
            state = self._states[key]

            if state.state == CircuitState.HALF_OPEN:
                state.state = CircuitState.OPEN
                state.opened_at = now
                state.total_opens += 1
                state.total_failures += 1
                state.last_error_category = error_category
                print(f"[ORDER-CB] {broker_name}|{symbol} HALF_OPEN → OPEN (probe failed: {error_category.value})")
                return

            state.failure_timestamps.append(now)
            state.total_failures += 1
            state.last_error_category = error_category

            cutoff = now - thresholds.window_seconds
            while state.failure_timestamps and state.failure_timestamps[0] < cutoff:
                state.failure_timestamps.popleft()

            if len(state.failure_timestamps) >= thresholds.failures_to_open:
                state.state = CircuitState.OPEN
                state.opened_at = now
                state.total_opens += 1
                print(f"[ORDER-CB] {broker_name}|{symbol} CLOSED → OPEN "
                      f"({len(state.failure_timestamps)} failures in {thresholds.window_seconds}s, "
                      f"error: {error_category.value})")

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            open_circuits = {}
            for key, state in self._states.items():
                if state.state != CircuitState.CLOSED:
                    open_circuits[key] = {
                        'state': state.state.value,
                        'total_opens': state.total_opens,
                        'total_failures': state.total_failures,
                        'last_error': state.last_error_category.value if state.last_error_category else None,
                        'opened_at': state.opened_at
                    }
            return {
                'total_tracked': len(self._states),
                'open_circuits': open_circuits,
                'open_count': len(open_circuits)
            }

    def reset(self, broker_name: str = None, symbol: str = None):
        with self._lock:
            if broker_name and symbol:
                key = self._make_key(broker_name, symbol)
                if key in self._states:
                    del self._states[key]
            elif broker_name:
                prefix = broker_name.lower().replace(' ', '_') + '|'
                keys_to_delete = [k for k in self._states if k.startswith(prefix)]
                for k in keys_to_delete:
                    del self._states[k]
            else:
                self._states.clear()


@dataclass
class OrderContext:
    broker_name: str
    symbol: str
    action: str
    asset: str = 'stock'
    strike: float = 0.0
    expiry: str = ''
    opt_type: str = ''
    is_risk_order: bool = False
    is_emergency: bool = False
    channel_id: str = ''
    position_key: str = ''


class OrderResilienceLayer:
    """
    Orchestrates order placement resilience across all brokers.

    Responsibilities:
    1. Pre-flight circuit breaker check (fast dict lookup, zero latency on success)
    2. Post-flight error classification
    3. Circuit breaker state updates
    4. Retry budget enforcement (prevents nested retry storms)
    5. Logging for observability
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.circuit_breaker = OrderCircuitBreaker()
        self.classifier = BrokerErrorClassifier()
        self._order_stats: Dict[str, int] = defaultdict(int)
        self._stats_lock = threading.Lock()
        self._initialized = True

    def pre_check(self, ctx: OrderContext) -> tuple:
        if ctx.action.upper() in ('STC', 'SELL') or ctx.is_risk_order:
            return (True, 'exit_order_bypass')

        allowed, reason = self.circuit_breaker.check_allowed(
            broker_name=ctx.broker_name,
            symbol=ctx.symbol,
            is_emergency=ctx.is_emergency,
            strike=ctx.strike if ctx.asset == 'option' else None,
            expiry=ctx.expiry if ctx.asset == 'option' else None,
            opt_type=ctx.opt_type if ctx.asset == 'option' else None
        )
        return (allowed, reason)

    def post_process(self, ctx: OrderContext, result: Any) -> ErrorCategory:
        category = self.classifier.classify(ctx.broker_name, result)

        strike = ctx.strike if ctx.asset == 'option' else None
        expiry = ctx.expiry if ctx.asset == 'option' else None
        opt_type = ctx.opt_type if ctx.asset == 'option' else None

        is_exit = ctx.action.upper() in ('STC', 'SELL') or ctx.is_risk_order

        if category == ErrorCategory.SUCCESS:
            self.circuit_breaker.record_success(
                ctx.broker_name, ctx.symbol, strike, expiry, opt_type
            )
            with self._stats_lock:
                self._order_stats[f"{ctx.broker_name}_success"] += 1
        elif category in (ErrorCategory.TRANSIENT_BUSY, ErrorCategory.RATE_LIMIT, ErrorCategory.PENDING_CONFLICT):
            if not is_exit:
                self.circuit_breaker.record_failure(
                    ctx.broker_name, ctx.symbol, category, strike, expiry, opt_type
                )
            with self._stats_lock:
                self._order_stats[f"{ctx.broker_name}_{category.value}"] += 1

            error_msg = self.classifier._extract_error_message(result)
            print(f"[ORDER-RESILIENCE] {ctx.broker_name} {ctx.action} {ctx.symbol} → {category.value}: {error_msg[:100]}")
        else:
            with self._stats_lock:
                self._order_stats[f"{ctx.broker_name}_fatal"] += 1

        return category

    def should_skip_internal_retry(self, ctx: OrderContext) -> bool:
        if ctx.is_risk_order:
            return True
        return False

    def get_retry_budget(self, ctx: OrderContext) -> int:
        if ctx.is_risk_order:
            return 1
        return 3

    def get_status(self) -> Dict[str, Any]:
        with self._stats_lock:
            stats = dict(self._order_stats)
        cb_status = self.circuit_breaker.get_status()
        return {
            'circuit_breaker': cb_status,
            'order_stats': stats
        }

    def reset_circuit(self, broker_name: str = None, symbol: str = None):
        self.circuit_breaker.reset(broker_name, symbol)


def get_resilience_layer() -> OrderResilienceLayer:
    return OrderResilienceLayer()
