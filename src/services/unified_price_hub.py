import threading
import time
import importlib
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass
class UnifiedQuote:
    symbol: str
    canonical: str = ""
    bid: float = 0.0
    ask: float = 0.0
    last: float = 0.0
    volume: int = 0
    high: float = 0.0
    low: float = 0.0
    open_price: float = 0.0
    close_price: float = 0.0
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    source_hub: str = ""
    timestamp: float = 0.0
    last_changed_ts: float = 0.0
    last_changed_price: float = 0.0
    freshness: str = "unknown"

    @property
    def mid(self) -> float:
        if self.bid > 0 and self.ask > 0:
            return round((self.bid + self.ask) / 2, 4)
        return self.last

    @property
    def age_seconds(self) -> float:
        if self.timestamp <= 0:
            return 999.0
        return time.time() - self.timestamp

    @property
    def price_age_seconds(self) -> float:
        if self.last_changed_ts <= 0:
            return 999.0
        return time.time() - self.last_changed_ts


_INDEX_TO_CANONICAL = {
    'SPXW': 'SPX', 'NDXP': 'NDX', 'VIXW': 'VIX', 'RUTW': 'RUT', 'DJXW': 'DJX',
}

_HUB_SYMBOL_MAP = {
    'webull':  {'SPX': 'SPX', 'SPXW': 'SPX', 'NDX': 'NDX', 'NDXP': 'NDX',
                'VIX': 'VIX', 'VIXW': 'VIX', 'RUT': 'RUT', 'RUTW': 'RUT',
                'DJX': 'DJX', 'DJXW': 'DJX'},
    'schwab':  {'SPX': 'SPXW', 'SPXW': 'SPXW', 'NDX': 'NDXP', 'NDXP': 'NDXP',
                'VIX': 'VIXW', 'VIXW': 'VIXW', 'RUT': 'RUTW', 'RUTW': 'RUTW',
                'DJX': 'DJXW', 'DJXW': 'DJXW'},
    'ibkr':    {'SPX': 'SPX', 'SPXW': 'SPX', 'NDX': 'NDX', 'NDXP': 'NDX',
                'VIX': 'VIX', 'VIXW': 'VIX', 'RUT': 'RUT', 'RUTW': 'RUT',
                'DJX': 'DJX', 'DJXW': 'DJX'},
}

FRESHNESS_FRESH = 3.0
FRESHNESS_PROBE = 5.0
FRESHNESS_STALE = 10.0
FRESHNESS_UNVERIFIED = 30.0

_HUB_REGISTRY = [
    ('webull', 'src.services.webull_data_hub', 'get_webull_data_hub'),
    ('schwab', 'src.services.schwab_data_hub', 'get_schwab_data_hub'),
    ('ibkr', 'src.services.ibkr_data_hub', 'get_ibkr_data_hub'),
    ('trading212', 'src.services.trading212_data_hub', 'get_trading212_data_hub'),
]


class UnifiedPriceHub:
    _instance = None
    _create_lock = threading.Lock()

    def __new__(cls):
        with cls._create_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self._cache: Dict[str, UnifiedQuote] = {}
        self._cache_lock = threading.Lock()

        self._alias_map: Dict[str, str] = {}
        self._alias_lock = threading.Lock()

        self._hub_cache: Dict[str, Any] = {}
        self._hub_cache_ts: float = 0.0
        self._hub_cache_lock = threading.Lock()
        self._HUB_CACHE_TTL = 30.0

        self._event_handlers: Dict[str, List[Callable]] = {}
        self._event_lock = threading.Lock()

        self._shadow_mode = True
        self._shadow_log_interval = 60.0
        self._shadow_last_log: float = 0.0
        self._shadow_discrepancies: List[Dict[str, Any]] = []
        self._shadow_lock = threading.Lock()

        self._poll_thread: Optional[threading.Thread] = None
        self._poll_running = False
        self._poll_interval = 2.0
        self._poll_state_lock = threading.Lock()

        self._stats = {
            'hits': 0, 'misses': 0, 'cross_hub_fills': 0,
            'stale_detections': 0, 'total_updates': 0,
        }
        self._stats_lock = threading.Lock()

        for alias, canonical in _INDEX_TO_CANONICAL.items():
            self._register_alias(alias, canonical)

        print("[UPH] Unified Price Hub initialized (shadow mode)")

    def _register_alias(self, alias: str, canonical: str):
        with self._alias_lock:
            self._alias_map[alias.upper()] = canonical.upper()

    def _to_canonical(self, symbol: str) -> str:
        s = symbol.upper().strip()
        with self._alias_lock:
            return self._alias_map.get(s, s)

    def _symbol_for_hub(self, symbol: str, hub_key: str) -> str:
        s = symbol.upper().strip()
        hub_map = _HUB_SYMBOL_MAP.get(hub_key)
        if hub_map and s in hub_map:
            return hub_map[s]
        return s

    def _get_hubs(self) -> Dict[str, Any]:
        now = time.time()
        with self._hub_cache_lock:
            if now - self._hub_cache_ts < self._HUB_CACHE_TTL and self._hub_cache:
                return dict(self._hub_cache)

        hubs = {}
        for key, mod_path, func_name in _HUB_REGISTRY:
            try:
                mod = importlib.import_module(mod_path)
                hub = getattr(mod, func_name)()
                if hub:
                    hubs[key] = hub
            except Exception:
                pass

        with self._hub_cache_lock:
            self._hub_cache = hubs
            self._hub_cache_ts = now
        return dict(hubs)

    def _classify_freshness(self, quote: UnifiedQuote) -> str:
        age = quote.price_age_seconds
        if age <= FRESHNESS_FRESH:
            return "fresh"
        elif age <= FRESHNESS_PROBE:
            return "aging"
        elif age <= FRESHNESS_STALE:
            return "stale"
        elif age <= FRESHNESS_UNVERIFIED:
            return "degraded"
        return "unverified"

    def _update_cache(self, symbol: str, data: Dict[str, Any], source_hub: str) -> Optional[UnifiedQuote]:
        canonical = self._to_canonical(symbol)
        now = time.time()

        with self._cache_lock:
            existing = self._cache.get(canonical)
            if existing is None:
                existing = UnifiedQuote(symbol=symbol, canonical=canonical)
                self._cache[canonical] = existing

            incoming_ts = data.get('timestamp', now)
            if existing.timestamp > 0 and incoming_ts < existing.timestamp - 1.0:
                return existing

            old_last = existing.last
            if 'bid' in data and data['bid']:
                existing.bid = float(data['bid'])
            if 'ask' in data and data['ask']:
                existing.ask = float(data['ask'])
            if 'last' in data and data['last']:
                existing.last = float(data['last'])
            elif 'price' in data and data['price']:
                existing.last = float(data['price'])
            if 'volume' in data:
                existing.volume = int(data['volume'] or 0)
            if 'high' in data and data['high']:
                existing.high = float(data['high'])
            if 'low' in data and data['low']:
                existing.low = float(data['low'])
            if 'delta' in data:
                existing.delta = float(data['delta'] or 0)
            if 'gamma' in data:
                existing.gamma = float(data['gamma'] or 0)
            if 'theta' in data:
                existing.theta = float(data['theta'] or 0)
            if 'vega' in data:
                existing.vega = float(data['vega'] or 0)

            existing.source_hub = source_hub
            existing.timestamp = incoming_ts if incoming_ts > 0 else now

            if existing.last > 0 and abs(existing.last - old_last) > 0.0001:
                existing.last_changed_ts = now
                existing.last_changed_price = existing.last

            existing.freshness = self._classify_freshness(existing)

        with self._stats_lock:
            self._stats['total_updates'] += 1

        self._emit('quote_updated', {
            'symbol': canonical,
            'price': existing.last,
            'bid': existing.bid,
            'ask': existing.ask,
            'source': source_hub,
            'freshness': existing.freshness,
        })

        return existing

    def get_quote(self, symbol: str) -> Optional[UnifiedQuote]:
        canonical = self._to_canonical(symbol)
        with self._cache_lock:
            quote = self._cache.get(canonical)
            if quote and (quote.last > 0 or quote.bid > 0 or quote.ask > 0):
                with self._stats_lock:
                    self._stats['hits'] += 1
                return quote

        result = self._try_fill_from_hubs(symbol)
        if result:
            with self._stats_lock:
                self._stats['cross_hub_fills'] += 1
            return result

        with self._stats_lock:
            self._stats['misses'] += 1
        return None

    def get_quote_price(self, symbol: str) -> Optional[float]:
        quote = self.get_quote(symbol)
        if quote and quote.last > 0:
            return quote.last
        return None

    def get_quote_detailed(self, symbol: str) -> Optional[Dict[str, Any]]:
        quote = self.get_quote(symbol)
        if not quote:
            return None
        return {
            'symbol': quote.symbol,
            'canonical': quote.canonical,
            'bid': quote.bid,
            'ask': quote.ask,
            'last': quote.last,
            'mid': quote.mid,
            'volume': quote.volume,
            'high': quote.high,
            'low': quote.low,
            'delta': quote.delta,
            'gamma': quote.gamma,
            'theta': quote.theta,
            'vega': quote.vega,
            'source': quote.source_hub,
            'timestamp': quote.timestamp,
            'freshness': quote.freshness,
            'age_seconds': quote.age_seconds,
            'price_age_seconds': quote.price_age_seconds,
        }

    def get_all_quotes(self) -> Dict[str, UnifiedQuote]:
        with self._cache_lock:
            return dict(self._cache)

    def get_stale_symbols(self, threshold: float = FRESHNESS_STALE) -> List[str]:
        result = []
        now = time.time()
        with self._cache_lock:
            for sym, q in self._cache.items():
                if q.last > 0 and q.last_changed_ts > 0:
                    if (now - q.last_changed_ts) > threshold:
                        result.append(sym)
        return result

    def _try_fill_from_hubs(self, symbol: str) -> Optional[UnifiedQuote]:
        hubs = self._get_hubs()
        canonical = self._to_canonical(symbol)

        for hub_key, hub in hubs.items():
            try:
                if not (hasattr(hub, 'is_streaming') and hub.is_streaming()):
                    continue
                lookup_sym = self._symbol_for_hub(symbol, hub_key)
                if hasattr(hub, 'get_quote_detailed'):
                    data = hub.get_quote_detailed(lookup_sym)
                    if data and (data.get('bid', 0) > 0 or data.get('ask', 0) > 0 or data.get('last', 0) > 0):
                        return self._update_cache(canonical, data, hub_key)
                elif hasattr(hub, 'get_quote_price'):
                    price = hub.get_quote_price(lookup_sym)
                    if price and price > 0:
                        return self._update_cache(canonical, {'last': price}, hub_key)
            except Exception:
                pass
        return None

    def poll_all_hubs(self):
        hubs = self._get_hubs()
        updated = 0
        for hub_key, hub in hubs.items():
            try:
                if not (hasattr(hub, 'is_streaming') and hub.is_streaming()):
                    continue
                if not hasattr(hub, 'get_all_quotes'):
                    continue
                all_quotes = hub.get_all_quotes()
                if not all_quotes:
                    continue
                for sym, qdata in all_quotes.items():
                    try:
                        data = {}
                        for attr in ('bid', 'ask', 'last', 'volume', 'high', 'low',
                                     'delta', 'gamma', 'theta', 'vega', 'timestamp'):
                            val = getattr(qdata, attr, None) if not isinstance(qdata, dict) else qdata.get(attr)
                            if val is not None:
                                data[attr] = val
                        if not isinstance(qdata, dict):
                            price = getattr(qdata, 'last', None) or getattr(qdata, 'price', None)
                            if price:
                                data['last'] = price
                        if data.get('last', 0) > 0 or data.get('bid', 0) > 0:
                            self._update_cache(sym, data, hub_key)
                            updated += 1
                    except Exception:
                        pass
            except Exception:
                pass
        return updated

    def shadow_compare(self, symbol: str, consumer_price: float, consumer_source: str) -> Optional[Dict[str, Any]]:
        if not self._shadow_mode:
            return None
        quote = self.get_quote(symbol)
        if not quote or quote.last <= 0 or consumer_price <= 0:
            return None

        diff = abs(quote.last - consumer_price)
        pct = (diff / consumer_price) * 100 if consumer_price > 0 else 0

        if pct > 1.0:
            result = {
                'symbol': symbol,
                'uph_price': quote.last,
                'uph_source': quote.source_hub,
                'uph_freshness': quote.freshness,
                'consumer_price': consumer_price,
                'consumer_source': consumer_source,
                'diff_pct': round(pct, 2),
                'timestamp': time.time(),
            }
            with self._shadow_lock:
                self._shadow_discrepancies.append(result)
                if len(self._shadow_discrepancies) > 500:
                    self._shadow_discrepancies = self._shadow_discrepancies[-250:]
            return result
        return None

    def get_shadow_report(self) -> Dict[str, Any]:
        with self._shadow_lock:
            recent = list(self._shadow_discrepancies[-20:])
        with self._stats_lock:
            stats = dict(self._stats)
        with self._cache_lock:
            cache_size = len(self._cache)
            stale_count = sum(1 for q in self._cache.values()
                              if q.freshness in ('stale', 'degraded', 'unverified'))
        return {
            'shadow_mode': self._shadow_mode,
            'cache_size': cache_size,
            'stale_symbols': stale_count,
            'stats': stats,
            'recent_discrepancies': recent,
        }

    def start_polling(self, interval: float = 2.0):
        with self._poll_state_lock:
            if self._poll_running:
                return
            self._poll_interval = interval
            self._poll_running = True
            self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True, name="UPH-Poller")
            self._poll_thread.start()
        print(f"[UPH] Background polling started (interval={interval}s)")

    def stop_polling(self):
        with self._poll_state_lock:
            self._poll_running = False
            t = self._poll_thread
            self._poll_thread = None
        if t:
            t.join(timeout=5)
        print("[UPH] Background polling stopped")

    def _poll_loop(self):
        while self._poll_running:
            try:
                self.poll_all_hubs()

                stale = self.get_stale_symbols()
                if stale:
                    with self._stats_lock:
                        self._stats['stale_detections'] += len(stale)

                now = time.time()
                if now - self._shadow_last_log > self._shadow_log_interval:
                    self._shadow_last_log = now
                    report = self.get_shadow_report()
                    if report['cache_size'] > 0:
                        print(f"[UPH] Cache: {report['cache_size']} symbols, "
                              f"{report['stale_symbols']} stale | "
                              f"Hits: {report['stats']['hits']}, "
                              f"Misses: {report['stats']['misses']}, "
                              f"CrossHub: {report['stats']['cross_hub_fills']}, "
                              f"Updates: {report['stats']['total_updates']}")
                        if report['recent_discrepancies']:
                            disc_strs = [str(d['symbol']) + ":" + str(d['diff_pct']) + "%" for d in report['recent_discrepancies'][-5:]]
                            print(f"[UPH] Shadow discrepancies (last {len(report['recent_discrepancies'])}): {disc_strs}")

            except Exception as e:
                print(f"[UPH] Poll error: {e}", file=sys.stderr)

            time.sleep(self._poll_interval)

    def on(self, event: str, handler: Callable):
        with self._event_lock:
            if event not in self._event_handlers:
                self._event_handlers[event] = []
            self._event_handlers[event].append(handler)

    def off(self, event: str, handler: Callable):
        with self._event_lock:
            if event in self._event_handlers:
                try:
                    self._event_handlers[event].remove(handler)
                except ValueError:
                    pass

    def _emit(self, event: str, data: Any = None):
        with self._event_lock:
            handlers = list(self._event_handlers.get(event, []))
        for h in handlers:
            try:
                h(data)
            except Exception:
                pass

    def is_active(self) -> bool:
        hubs = self._get_hubs()
        for hub in hubs.values():
            try:
                if hasattr(hub, 'is_streaming') and hub.is_streaming():
                    return True
            except Exception:
                pass
        return False


_uph_instance: Optional[UnifiedPriceHub] = None
_uph_lock = threading.Lock()


def get_unified_price_hub() -> UnifiedPriceHub:
    global _uph_instance
    if _uph_instance is None:
        with _uph_lock:
            if _uph_instance is None:
                _uph_instance = UnifiedPriceHub()
    return _uph_instance


def init_unified_price_hub(start_polling: bool = True, poll_interval: float = 2.0) -> UnifiedPriceHub:
    uph = get_unified_price_hub()
    if start_polling:
        uph.start_polling(interval=poll_interval)
    return uph
