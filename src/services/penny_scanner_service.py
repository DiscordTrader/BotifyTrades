import asyncio
import importlib
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
from zoneinfo import ZoneInfo


MAX_SCANNER_SYMBOLS = 50
_ET = ZoneInfo('America/New_York')

_scanner_instance = None
_scanner_lock = threading.Lock()


def get_penny_scanner() -> 'PennyStockScanner':
    global _scanner_instance
    with _scanner_lock:
        if _scanner_instance is None:
            _scanner_instance = PennyStockScanner()
        return _scanner_instance


class PennyStockScanner:

    DIRECTIONS = {
        'gainers': ('gainer', '1d'),
        'losers': ('loser', '1d'),
        'active': ('active', 'volume'),
        'premarket_gainers': ('gainer', 'preMarket'),
        'premarket_losers': ('loser', 'preMarket'),
        'afterhours_gainers': ('gainer', 'afterMarket'),
        'afterhours_losers': ('loser', 'afterMarket'),
    }

    def __init__(self):
        self._candidates: Dict[str, Dict] = {}
        self._ticker_ids: Dict[str, str] = {}
        self._subscribed_symbols: Set[str] = set()
        self._last_scan_time: float = 0
        self._lock = threading.Lock()

    def _get_webull_instance(self):
        try:
            from gui_app.routes import _bot_instance
            if _bot_instance and hasattr(_bot_instance, 'broker') and _bot_instance.broker:
                wb = getattr(_bot_instance.broker, 'wb', None)
                if wb:
                    return wb
        except Exception:
            pass
        try:
            from webull import webull
            return webull()
        except Exception:
            return None

    def scan_webull(self, scan_type: str = 'active', min_price: float = 0.01,
                    max_price: float = 5.00, min_volume: int = 0, count: int = 50) -> List[Dict]:
        wb = self._get_webull_instance()
        if not wb:
            print("[SCANNER] No Webull instance available")
            return []

        direction, rank_type = self.DIRECTIONS.get(scan_type, ('active', 'volume'))

        try:
            print(f"[SCANNER] Fetching {scan_type} ({direction}/{rank_type}) from Webull...")
            result = wb.active_gainer_loser(direction=direction, rank_type=rank_type, count=count)
        except Exception as e:
            print(f"[SCANNER] Webull API error: {e}")
            return []

        if not result or not isinstance(result, dict):
            print("[SCANNER] Empty response from Webull")
            return []

        items = result.get('data', [])
        if items and len(items) > 0:
            sample_ticker = items[0].get('ticker', {})
            vol_keys = [k for k in sample_ticker.keys() if 'vol' in k.lower() or 'avg' in k.lower()]
            print(f"[SCANNER] Screener ticker keys with vol/avg: {vol_keys}")
            print(f"[SCANNER] Sample ticker volume fields: volume={sample_ticker.get('volume')}, avgVol10D={sample_ticker.get('avgVol10D')}, avgVolume={sample_ticker.get('avgVolume')}, avgVol3M={sample_ticker.get('avgVol3M')}")
        candidates = []

        for item in items:
            t = item.get('ticker', {})
            try:
                symbol = t.get('symbol', '')
                if not symbol:
                    continue

                close_price = float(t.get('close', 0))
                pre_close = float(t.get('preClose', 0))
                open_price = float(t.get('open', 0))
                high = float(t.get('high', 0))
                low = float(t.get('low', 0))
                volume = int(t.get('volume', 0))
                change = float(t.get('change', 0))
                change_ratio = float(t.get('changeRatio', 0))
                ticker_id = str(t.get('tickerId', ''))
                name = t.get('name', '')
                exchange = t.get('disExchangeCode', '')
                turnover_rate = float(t.get('turnoverRate', 0))
                market_value = float(t.get('marketValue', 0))
                avg_vol_10d = int(t.get('avgVol3M', 0) or t.get('avgVolume', 0) or 0)

                price = close_price if close_price > 0 else pre_close
                if price <= 0:
                    continue
                if price < min_price or price > max_price:
                    continue
                if min_volume > 0 and volume < min_volume:
                    continue

                gap_pct = None
                if pre_close > 0 and open_price > 0:
                    gap_pct = round((open_price - pre_close) / pre_close * 100, 2)

                candidates.append({
                    'symbol': symbol,
                    'name': name,
                    'exchange': exchange,
                    'price': price,
                    'pre_close': pre_close,
                    'open_price': open_price,
                    'high': high,
                    'low': low,
                    'volume': volume,
                    'change': change,
                    'change_pct': round(change_ratio * 100, 2),
                    'gap_pct': gap_pct,
                    'turnover_rate': turnover_rate,
                    'market_cap': market_value,
                    'avg_vol_10d': avg_vol_10d,
                    'ticker_id': ticker_id,
                    'scan_type': scan_type,
                })

                if ticker_id:
                    self._ticker_ids[symbol] = ticker_id

            except (ValueError, TypeError, KeyError):
                continue

        with self._lock:
            self._candidates.clear()
            for c in candidates[:MAX_SCANNER_SYMBOLS]:
                self._candidates[c['symbol']] = c
            self._last_scan_time = time.time()

        symbols = set(self._candidates.keys())
        self.subscribe_symbols(symbols)
        self._fetch_avg_volumes_bg(list(symbols))

        print(f"[SCANNER] ✓ Found {len(candidates)} stocks, tracking {len(self._candidates)}")
        return list(self._candidates.values())

    def scan_manual(self, symbols_str: str) -> List[Dict]:
        raw = [s.strip().upper() for s in symbols_str.replace(';', ',').split(',') if s.strip()]
        symbols = [s for s in raw if s.isalpha() and 1 <= len(s) <= 6][:MAX_SCANNER_SYMBOLS]
        if not symbols:
            return []

        with self._lock:
            self._candidates.clear()
            for sym in symbols:
                self._candidates[sym] = {
                    'symbol': sym, 'name': '', 'exchange': '', 'price': 0,
                    'pre_close': 0, 'open_price': 0, 'high': 0, 'low': 0,
                    'volume': 0, 'change': 0, 'change_pct': 0, 'gap_pct': None,
                    'turnover_rate': 0, 'market_cap': 0, 'avg_vol_10d': 0,
                    'ticker_id': '', 'scan_type': 'manual',
                }
            self._last_scan_time = time.time()

        self._lookup_ticker_ids_and_volumes_bg(symbols)
        self.subscribe_symbols(set(symbols))
        return list(self._candidates.values())

    def _lookup_ticker_ids_bg(self, symbols: List[str]):
        def _lookup():
            wb = self._get_webull_instance()
            if not wb:
                return
            hub = self._get_hub('webull')
            for sym in symbols:
                try:
                    tid = None
                    if hub and hasattr(hub, 'get_ticker_id'):
                        tid = hub.get_ticker_id(sym)
                    if not tid and hasattr(wb, 'get_ticker'):
                        info = wb.get_ticker(stock=sym)
                        if isinstance(info, dict):
                            tid = str(info.get('tickerId', ''))
                    if tid:
                        self._ticker_ids[sym] = tid
                        self._webull_stream_subscribe(sym, tid)
                        if hub and hasattr(hub, 'register_ticker_id'):
                            hub.register_ticker_id(sym, tid)
                except Exception:
                    pass
        threading.Thread(target=_lookup, daemon=True).start()

    def _lookup_ticker_ids_and_volumes_bg(self, symbols: List[str]):
        def _work():
            try:
                from webull import webull as WebullClass
                wb = WebullClass()
            except Exception:
                wb = self._get_webull_instance()
            if not wb:
                return
            hub = self._get_hub('webull')
            updated = 0
            for sym in symbols:
                try:
                    tid = None
                    if hub and hasattr(hub, 'get_ticker_id'):
                        tid = hub.get_ticker_id(sym)
                    if not tid and hasattr(wb, 'get_ticker'):
                        info = wb.get_ticker(stock=sym)
                        if isinstance(info, dict):
                            tid = str(info.get('tickerId', ''))
                    if tid:
                        self._ticker_ids[sym] = tid
                        self._webull_stream_subscribe(sym, tid)
                        if hub and hasattr(hub, 'register_ticker_id'):
                            hub.register_ticker_id(sym, tid)
                    try:
                        quote = wb.get_quote(stock=sym)
                        if isinstance(quote, dict):
                            avg_vol = int(quote.get('avgVol3M', 0) or quote.get('avgVol10D', 0) or 0)
                            if avg_vol > 0:
                                with self._lock:
                                    if sym in self._candidates:
                                        self._candidates[sym]['avg_vol_10d'] = avg_vol
                                        updated += 1
                        time.sleep(0.25)
                    except Exception:
                        pass
                except Exception:
                    pass
            if updated:
                print(f"[SCANNER] Manual scan RVOL: {updated}/{len(symbols)} stocks")
        threading.Thread(target=_work, daemon=True).start()

    def _fetch_avg_volumes_bg(self, symbols: List[str]):
        def _fetch():
            try:
                from webull import webull as WebullClass
                wb = WebullClass()
            except Exception as e:
                print(f"[SCANNER] RVOL: cannot create webull instance: {e}")
                return
            print(f"[SCANNER] RVOL: fetching avg volume for {len(symbols)} stocks via get_quote...")
            updated = 0
            errors = 0
            for sym in symbols:
                try:
                    quote = wb.get_quote(stock=sym)
                    if isinstance(quote, dict):
                        avg_vol = int(quote.get('avgVol3M', 0) or quote.get('avgVol10D', 0) or 0)
                        vol = int(quote.get('volume', 0) or 0)
                        if avg_vol > 0:
                            with self._lock:
                                if sym in self._candidates:
                                    self._candidates[sym]['avg_vol_10d'] = avg_vol
                                    if vol > 0:
                                        self._candidates[sym]['volume'] = max(
                                            self._candidates[sym].get('volume', 0), vol)
                                    updated += 1
                            rvol = round(vol / avg_vol, 1) if avg_vol > 0 else 0
                            print(f"[SCANNER] RVOL {sym}: vol={vol:,} avg10D={avg_vol:,} → {rvol}x")
                    else:
                        errors += 1
                    time.sleep(0.2)
                except Exception as e:
                    errors += 1
                    print(f"[SCANNER] RVOL {sym} error: {e}")
                    continue
            print(f"[SCANNER] RVOL complete: {updated}/{len(symbols)} enriched, {errors} errors")
        threading.Thread(target=_fetch, daemon=True).start()

    def subscribe_symbols(self, symbols: Set[str]):
        new_symbols = symbols - self._subscribed_symbols
        if not new_symbols:
            return

        try:
            schwab_hub = self._get_hub('schwab')
            if schwab_hub and hasattr(schwab_hub, 'request_subscribe_equities'):
                schwab_hub.request_subscribe_equities(new_symbols)
        except Exception as e:
            print(f"[SCANNER] Schwab subscribe error: {e}")

        try:
            ibkr_hub = self._get_hub('ibkr')
            if ibkr_hub and hasattr(ibkr_hub, 'subscribe_symbol'):
                for sym in new_symbols:
                    ibkr_hub.subscribe_symbol(sym)
        except Exception as e:
            print(f"[SCANNER] IBKR subscribe error: {e}")

        try:
            tt_hub = self._get_hub('tastytrade')
            if tt_hub and hasattr(tt_hub, 'subscribe_symbol'):
                for sym in new_symbols:
                    tt_hub.subscribe_symbol(sym)
        except Exception as e:
            print(f"[SCANNER] Tastytrade subscribe error: {e}")

        for sym in new_symbols:
            tid = self._ticker_ids.get(sym)
            if tid:
                self._webull_stream_subscribe(sym, tid)

        self._subscribed_symbols |= new_symbols
        print(f"[SCANNER] Subscribed {len(new_symbols)} symbols to broker hubs")

    def _webull_stream_subscribe(self, symbol: str, ticker_id: str):
        try:
            from gui_app.routes import _bot_instance
            if _bot_instance and hasattr(_bot_instance, 'broker') and _bot_instance.broker:
                sc = getattr(_bot_instance.broker, '_streaming_client', None)
                if sc and hasattr(sc, 'subscribe_symbol'):
                    sc.subscribe_symbol(symbol, str(ticker_id), is_option=False)
        except Exception:
            pass

    def _get_hub(self, hub_key: str) -> Optional[Any]:
        hub_map = {
            'schwab': ('src.services.schwab_data_hub', 'get_schwab_data_hub'),
            'ibkr': ('src.services.ibkr_data_hub', 'get_ibkr_data_hub'),
            'tastytrade': ('src.services.tastytrade_data_hub', 'get_tastytrade_data_hub'),
            'webull': ('src.services.webull_data_hub', 'get_webull_data_hub'),
        }
        entry = hub_map.get(hub_key)
        if not entry:
            return None
        try:
            mod = importlib.import_module(entry[0])
            return getattr(mod, entry[1])()
        except Exception:
            return None

    def get_enriched_quotes(self) -> List[Dict]:
        with self._lock:
            symbols = list(self._candidates.keys())
            disc_data = dict(self._candidates)
        if not symbols:
            return []

        try:
            from src.services.unified_price_hub import UnifiedPriceHub
            uph = UnifiedPriceHub.instance()
        except Exception:
            uph = None

        results = []
        for sym in symbols:
            disc = disc_data.get(sym, {})
            entry = {
                'symbol': sym,
                'name': disc.get('name', ''),
                'exchange': disc.get('exchange', ''),
                'bid': 0, 'ask': 0, 'last': 0, 'volume': 0,
                'high': 0, 'low': 0, 'open_price': 0, 'pre_close': 0,
                'change': 0, 'change_pct': disc.get('change_pct', 0),
                'gap_pct': disc.get('gap_pct'),
                'turnover_rate': disc.get('turnover_rate', 0),
                'market_cap': disc.get('market_cap', 0),
                'avg_vol_10d': disc.get('avg_vol_10d', 0),
                'rvol': None,
                'freshness': 'discovery', 'source': 'webull_api',
            }

            disc_vol = disc.get('volume', 0)

            if uph:
                quote = uph.get_quote(sym)
                if quote and (quote.last > 0 or quote.bid > 0):
                    entry['bid'] = quote.bid
                    entry['ask'] = quote.ask
                    entry['last'] = quote.last
                    entry['volume'] = max(quote.volume, disc_vol) if quote.volume > 0 else disc_vol
                    entry['high'] = max(quote.high, disc.get('high', 0)) if quote.high > 0 else disc.get('high', 0)
                    entry['low'] = quote.low if quote.low > 0 else disc.get('low', 0)
                    entry['open_price'] = quote.open_price if quote.open_price > 0 else disc.get('open_price', 0)
                    entry['freshness'] = quote.freshness
                    entry['source'] = quote.source_hub

                    pre_close = disc.get('pre_close', 0) or quote.close_price
                    entry['pre_close'] = pre_close
                    if pre_close > 0 and quote.last > 0:
                        entry['change'] = round(quote.last - pre_close, 4)
                        entry['change_pct'] = round((quote.last - pre_close) / pre_close * 100, 2)
                    if pre_close > 0 and entry['open_price'] > 0:
                        entry['gap_pct'] = round((entry['open_price'] - pre_close) / pre_close * 100, 2)

            if entry['last'] == 0 and disc.get('price', 0) > 0:
                entry['last'] = disc['price']
                entry['volume'] = disc_vol
                entry['high'] = disc.get('high', 0)
                entry['low'] = disc.get('low', 0)
                entry['open_price'] = disc.get('open_price', 0)
                entry['pre_close'] = disc.get('pre_close', 0)

            cur_vol = entry.get('volume', 0) or disc_vol
            avg_vol = entry.get('avg_vol_10d', 0)
            if avg_vol > 0 and cur_vol > 0:
                entry['rvol'] = round(cur_vol / avg_vol, 1)

            results.append(entry)

        return results

    def get_candidates(self) -> List[Dict]:
        with self._lock:
            return list(self._candidates.values())

    def clear(self):
        with self._lock:
            self._candidates.clear()
            self._ticker_ids.clear()
            count = len(self._subscribed_symbols)
            self._subscribed_symbols.clear()
            self._last_scan_time = 0
        return count
