import copy
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
    last_tick_ts: float = 0.0
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
    ('tastytrade', 'src.services.tastytrade_data_hub', 'get_tastytrade_data_hub'),
    ('trading212', 'src.services.trading212_data_hub', 'get_trading212_data_hub'),
    # webull_official shares WebullDataHub singleton with 'webull' — only one subscription
    # needed. Duplicate entry removed to prevent double-firing of quote_updated → risk engine.
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

    @classmethod
    def instance(cls) -> Optional['UnifiedPriceHub']:
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

        self._subscribed_hubs: Dict[str, Callable] = {}
        self._subscribe_lock = threading.Lock()

        self._auto_sub_ts: Dict[str, float] = {}  # canonical → last subscribe_symbol() call time

        self._stats = {
            'hits': 0, 'misses': 0, 'cross_hub_fills': 0,
            'stale_detections': 0, 'total_updates': 0,
            'streaming_ticks': 0,
        }
        self._stats_lock = threading.Lock()

        for alias, canonical in _INDEX_TO_CANONICAL.items():
            self._register_alias(alias, canonical)

        print("[UPH] Unified Price Hub initialized (active)", flush=True)

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
        seen_ids: set = set()
        for key, mod_path, func_name in _HUB_REGISTRY:
            try:
                mod = importlib.import_module(mod_path)
                hub = getattr(mod, func_name)()
                if hub and id(hub) not in seen_ids:
                    hubs[key] = hub
                    seen_ids.add(id(hub))
            except Exception:
                pass

        with self._hub_cache_lock:
            self._hub_cache = hubs
            self._hub_cache_ts = now
        return dict(hubs)

    def _subscribe_to_hubs(self):
        hubs = self._get_hubs()
        newly_subscribed = []
        with self._subscribe_lock:
            for hub_key, hub in hubs.items():
                if hub_key in self._subscribed_hubs:
                    continue
                if not hasattr(hub, 'on'):
                    continue
                callback = self._make_hub_callback(hub_key, hub)
                try:
                    hub.on('quote_updated', callback)
                    self._subscribed_hubs[hub_key] = callback
                    newly_subscribed.append(hub_key)
                except Exception as e:
                    print(f"[UPH] ⚠️ Failed to subscribe to {hub_key}: {e}", flush=True)
        if newly_subscribed:
            print(f"[UPH] ✓ Subscribed to real-time events: {newly_subscribed}", flush=True)

    def _make_hub_callback(self, hub_key: str, hub) -> Callable:
        def _on_quote_updated(event_data):
            try:
                if not isinstance(event_data, dict):
                    return
                symbol = event_data.get('symbol')
                if not symbol:
                    return

                quote_obj = event_data.get('quote')
                if quote_obj is not None:
                    data = {}
                    for attr in ('bid', 'ask', 'last', 'volume', 'high', 'low',
                                 'delta', 'gamma', 'theta', 'vega',
                                 'open_price', 'close_price'):
                        val = getattr(quote_obj, attr, None)
                        if val is not None:
                            data[attr] = val
                    price = getattr(quote_obj, 'last', None) or getattr(quote_obj, 'price', None)
                    if price and price > 0:
                        data['last'] = price
                    ts = getattr(quote_obj, 'timestamp', None)
                    if ts:
                        data['timestamp'] = ts
                    if data.get('last', 0) > 0 or data.get('bid', 0) > 0:
                        self._update_cache(symbol, data, hub_key)
                        with self._stats_lock:
                            self._stats['streaming_ticks'] += 1
                else:
                    try:
                        if hasattr(hub, 'get_quote'):
                            q = hub.get_quote(symbol)
                            if q:
                                data = {}
                                for attr in ('bid', 'ask', 'last', 'volume', 'high', 'low'):
                                    val = getattr(q, attr, None)
                                    if val is not None:
                                        data[attr] = val
                                ts = getattr(q, 'timestamp', None)
                                if ts:
                                    data['timestamp'] = ts
                                if data.get('last', 0) > 0 or data.get('bid', 0) > 0:
                                    self._update_cache(symbol, data, hub_key)
                                    with self._stats_lock:
                                        self._stats['streaming_ticks'] += 1
                    except Exception:
                        pass
            except Exception:
                pass
        return _on_quote_updated

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
            old_bid = existing.bid
            old_ask = existing.ask
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
            if 'open_price' in data and data['open_price']:
                existing.open_price = float(data['open_price'])
            elif 'open' in data and data['open']:
                existing.open_price = float(data['open'])
            if 'close_price' in data and data['close_price']:
                existing.close_price = float(data['close_price'])
            elif 'close' in data and data['close']:
                existing.close_price = float(data['close'])
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

            any_change = (abs(existing.last - old_last) > 0.0001
                          or abs(existing.bid - old_bid) > 0.0001
                          or abs(existing.ask - old_ask) > 0.0001)
            if any_change:
                existing.last_tick_ts = now

            existing.freshness = self._classify_freshness(existing)

            emit_data = {
                'symbol': canonical,
                'price': existing.last,
                'bid': existing.bid,
                'ask': existing.ask,
                'source': source_hub,
                'freshness': existing.freshness,
            }

        with self._stats_lock:
            self._stats['total_updates'] += 1

        self._emit('quote_updated', emit_data)

        return existing

    def get_quote(self, symbol: str) -> Optional[UnifiedQuote]:
        canonical = self._to_canonical(symbol)
        result = None
        with self._cache_lock:
            quote = self._cache.get(canonical)
            if quote and (quote.last > 0 or quote.bid > 0 or quote.ask > 0):
                quote.freshness = self._classify_freshness(quote)
                result = copy.copy(quote)
        if result:
            with self._stats_lock:
                self._stats['hits'] += 1
            return result

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
            'open_price': quote.open_price,
            'close_price': quote.close_price,
            'source': quote.source_hub,
            'timestamp': quote.timestamp,
            'freshness': quote.freshness,
            'age_seconds': quote.age_seconds,
            'price_age_seconds': quote.price_age_seconds,
        }

    def get_all_quotes(self) -> Dict[str, UnifiedQuote]:
        with self._cache_lock:
            return {k: copy.copy(v) for k, v in self._cache.items()}

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
                        cached = self._update_cache(canonical, data, hub_key)
                        return copy.copy(cached) if cached else None
                elif hasattr(hub, 'get_quote_price'):
                    price = hub.get_quote_price(lookup_sym)
                    if price and price > 0:
                        cached = self._update_cache(canonical, {'last': price}, hub_key)
                        return copy.copy(cached) if cached else None
            except Exception:
                pass

        # All hubs missed — subscribe the symbol so future ticks flow in automatically.
        # Rate-limited to once per 30s per symbol to avoid log spam.
        # Only for plain equity symbols (no '_' option key, no spaces).
        if '_' not in symbol and ' ' not in symbol:
            now = time.time()
            last_sub = self._auto_sub_ts.get(canonical, 0)
            if now - last_sub >= 30.0:
                self._auto_sub_ts[canonical] = now
                self.subscribe_symbol(symbol)
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
                                     'delta', 'gamma', 'theta', 'vega',
                                     'open_price', 'close_price', 'timestamp'):
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

    _BROKER_NAME_TO_HUB = {
        'SCHWAB': 'schwab', 'SCHWAB_LIVE': 'schwab', 'SCHWAB_PAPER': 'schwab',
        'WEBULL': 'webull', 'WEBULL_LIVE': 'webull', 'WEBULL_PAPER': 'webull',
        'WEBULL_OFFICIAL': 'webull_official', 'WEBULL_OFFICIAL_LIVE': 'webull_official', 'WEBULL_OFFICIAL_PAPER': 'webull_official',
        'IBKR': 'ibkr', 'IBKR_LIVE': 'ibkr', 'IBKR_PAPER': 'ibkr',
        'TASTYTRADE': 'tastytrade', 'TASTYTRADE_LIVE': 'tastytrade', 'TASTYTRADE_PAPER': 'tastytrade',
        'TRADING212': 'trading212', 'TRADING212_LIVE': 'trading212', 'TRADING212_PAPER': 'trading212',
    }

    def _resolve_hub_key(self, broker_name: Optional[str]) -> Optional[str]:
        if not broker_name:
            return None
        return self._BROKER_NAME_TO_HUB.get(str(broker_name).upper().strip())

    def shadow_compare(
        self,
        symbol: str,
        consumer_price: float,
        consumer_source: str,
        asset_type: str = 'stock',
        broker_hint: Optional[str] = None,
        raw_symbol: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if not self._shadow_mode:
            return None
        if consumer_price <= 0:
            return None

        is_option = (str(asset_type or 'stock').lower() == 'option')

        if is_option:
            hub_key = self._resolve_hub_key(broker_hint)
            if not hub_key or not raw_symbol:
                with self._stats_lock:
                    self._stats.setdefault('shadow_skipped_option_unresolvable', 0)
                    self._stats['shadow_skipped_option_unresolvable'] += 1
                return None
            hubs = self._get_hubs()
            hub = hubs.get(hub_key)
            if not hub or not hasattr(hub, 'get_quote_detailed'):
                with self._stats_lock:
                    self._stats.setdefault('shadow_skipped_option_no_hub', 0)
                    self._stats['shadow_skipped_option_no_hub'] += 1
                return None
            try:
                try:
                    data = hub.get_quote_detailed(raw_symbol, max_age=FRESHNESS_STALE)
                except TypeError:
                    data = hub.get_quote_detailed(raw_symbol)
            except Exception:
                return None
            if not data:
                with self._stats_lock:
                    self._stats.setdefault('shadow_skipped_option_uncached', 0)
                    self._stats['shadow_skipped_option_uncached'] += 1
                return None
            quote_ts = float(data.get('timestamp') or 0)
            age = (time.time() - quote_ts) if quote_ts > 0 else 999.0
            if age <= FRESHNESS_FRESH:
                ref_freshness = 'fresh'
            elif age <= FRESHNESS_PROBE:
                ref_freshness = 'aging'
            elif age <= FRESHNESS_STALE:
                ref_freshness = 'stale'
            else:
                with self._stats_lock:
                    self._stats.setdefault('shadow_skipped_option_stale', 0)
                    self._stats['shadow_skipped_option_stale'] += 1
                return None
            if ref_freshness in ('stale',):
                with self._stats_lock:
                    self._stats.setdefault('shadow_skipped_option_stale', 0)
                    self._stats['shadow_skipped_option_stale'] += 1
                return None
            ref_last = float(data.get('last') or 0)
            ref_bid = float(data.get('bid') or 0)
            ref_ask = float(data.get('ask') or 0)
            if ref_last <= 0 and ref_bid > 0 and ref_ask > 0:
                ref_last = round((ref_bid + ref_ask) / 2, 4)
            if ref_last <= 0:
                return None
            ref_source = f"{hub_key}_option"
            display_symbol = raw_symbol
        else:
            quote = self.get_quote(symbol)
            if not quote or quote.last <= 0:
                return None
            if quote.freshness in ('unverified', 'degraded', 'stale'):
                return None
            ref_last = quote.last
            ref_source = quote.source_hub
            ref_freshness = quote.freshness
            display_symbol = symbol

        diff = abs(ref_last - consumer_price)
        pct = (diff / consumer_price) * 100 if consumer_price > 0 else 0

        with self._stats_lock:
            self._stats.setdefault('shadow_checks', 0)
            self._stats['shadow_checks'] += 1
            if pct <= 1.0:
                self._stats.setdefault('shadow_matches', 0)
                self._stats['shadow_matches'] += 1

        if pct > 5.0:
            result = {
                'symbol': display_symbol,
                'asset_type': 'option' if is_option else 'stock',
                'uph_price': ref_last,
                'uph_source': ref_source,
                'uph_freshness': ref_freshness,
                'consumer_price': consumer_price,
                'consumer_source': consumer_source,
                'diff_pct': round(pct, 2),
                'timestamp': time.time(),
            }
            with self._shadow_lock:
                self._shadow_discrepancies.append(result)
                if len(self._shadow_discrepancies) > 500:
                    self._shadow_discrepancies = self._shadow_discrepancies[-250:]
            print(f"[UPH] ⚠️ Shadow discrepancy: {display_symbol} | {consumer_source}=${consumer_price:.4f} vs UPH=${ref_last:.4f} ({ref_source}/{ref_freshness}) | diff={pct:.2f}%", flush=True)
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
            self._poll_interval = max(interval, 1.0)
            self._poll_running = True
            self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True, name="UPH-Poller")
            self._poll_thread.start()
        self._subscribe_to_hubs()
        print(f"[UPH] Background polling started (fallback interval={self._poll_interval}s, event-driven=primary)", flush=True)

    def stop_polling(self):
        with self._poll_state_lock:
            self._poll_running = False
            t = self._poll_thread
            self._poll_thread = None
        if t:
            t.join(timeout=5)
        print("[UPH] Background polling stopped", flush=True)

    def _poll_loop(self):
        print(f"[UPH] Poll loop thread started (event-driven primary, poll fallback)", flush=True)
        while self._poll_running:
            try:
                self._subscribe_to_hubs()

                updated = self.poll_all_hubs()

                stale = self.get_stale_symbols()
                if stale:
                    with self._stats_lock:
                        self._stats['stale_detections'] += len(stale)

                now = time.time()
                if now - self._shadow_last_log > self._shadow_log_interval:
                    self._shadow_last_log = now
                    hubs = self._get_hubs()
                    hub_info = {k: hasattr(v, 'is_streaming') and v.is_streaming() for k, v in hubs.items()}
                    with self._subscribe_lock:
                        sub_keys = list(self._subscribed_hubs.keys())
                    with self._stats_lock:
                        streaming_ticks = self._stats.get('streaming_ticks', 0)
                    print(f"[UPH] Hubs: {hub_info} | Subscribed: {sub_keys} | StreamTicks: {streaming_ticks} | PollUpdated: {updated}", flush=True)
                    report = self.get_shadow_report()
                    shadow_checks = report['stats'].get('shadow_checks', 0)
                    shadow_matches = report['stats'].get('shadow_matches', 0)
                    shadow_disc = len(report['recent_discrepancies'])
                    print(f"[UPH] Cache: {report['cache_size']} symbols, "
                          f"{report['stale_symbols']} stale | "
                          f"Hits: {report['stats']['hits']}, "
                          f"Misses: {report['stats']['misses']}, "
                          f"CrossHub: {report['stats']['cross_hub_fills']}, "
                          f"Updates: {report['stats']['total_updates']} | "
                          f"Shadow: {shadow_checks} checks, {shadow_matches} match, {shadow_disc} discrepancies", flush=True)
                    if report['recent_discrepancies']:
                        disc_strs = [str(d['symbol']) + ":" + str(d['diff_pct']) + "%" for d in report['recent_discrepancies'][-5:]]
                        print(f"[UPH] Shadow discrepancies (last {len(report['recent_discrepancies'])}): {disc_strs}", flush=True)

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

    def is_streaming(self) -> bool:
        """Alias for is_active() — allows UPH to be used as a drop-in hub in StreamingPriceMonitor."""
        return self.is_active()

    def subscribe_symbol(self, symbol: str):
        """Push a symbol subscription to all connected broker hubs so UPH receives live ticks.

        Called by conditional order monitors, position monitor, or any consumer that
        needs live prices for a symbol not yet in any broker's stream (e.g. pre-trade
        conditional orders where no position exists yet).
        """
        sym = symbol.upper().strip()
        hubs = self._get_hubs()
        subscribed_to = []

        for hub_key, hub in hubs.items():
            try:
                # Schwab: thread-safe pending queue, drained every 10s by streaming loop
                if hasattr(hub, 'request_subscribe_equities'):
                    if hasattr(hub, 'is_streaming') and hub.is_streaming():
                        hub.request_subscribe_equities({sym})
                        subscribed_to.append(hub_key)
                # IBKR: queues in pending_subscriptions even when not streaming (picked up on reconnect)
                elif hasattr(hub, 'subscribe_symbol') and hasattr(hub, '_ib'):
                    hub.subscribe_symbol(sym)
                    subscribed_to.append(hub_key)
                # Tastytrade: DXLink subscription queue
                elif hasattr(hub, 'subscribe_symbol') and hasattr(hub, '_streamer'):
                    hub.subscribe_symbol(sym)
                    subscribed_to.append(hub_key)
            except Exception:
                pass

        if subscribed_to:
            print(f"[UPH] subscribe_symbol({sym}) → pushed to: {subscribed_to}", flush=True)
        else:
            print(f"[UPH] subscribe_symbol({sym}) → no streaming hubs available", flush=True)


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
