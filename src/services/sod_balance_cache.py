import threading
from datetime import datetime

_instance = None
_instance_lock = threading.Lock()

_BROKER_NAME_MAP = {
    'webull': 'WEBULL',
    'webull_live': 'WEBULL',
    'webull_paper': 'WEBULL_PAPER',
    'alpaca': 'ALPACA',
    'alpaca_paper': 'ALPACA',
    'schwab': 'SCHWAB',
    'schwab_live': 'SCHWAB',
    'tastytrade': 'TASTYTRADE',
    'tastytrade_live': 'TASTYTRADE',
    'tastytrade_paper': 'TASTYTRADE',
    'robinhood': 'ROBINHOOD',
    'ibkr': 'IBKR',
    'ibkr_live': 'IBKR',
    'ibkr_paper': 'IBKR',
    'questrade': 'QUESTRADE',
}


def _normalize_broker_name(name):
    if not name:
        return name
    lower = name.lower().strip()
    return _BROKER_NAME_MAP.get(lower, name.upper())


def get_sod_cache():
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = SODBalanceCache()
    return _instance


class SODBalanceCache:

    def __init__(self):
        self._cache = {}
        self._captured_date = {}
        self._lock = threading.Lock()

    def capture_snapshot(self, broker_name, buying_power, options_buying_power, portfolio_value=None, snapshot_type="start_of_day"):
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo
        now_et = datetime.now(ZoneInfo('America/New_York'))
        today_str = now_et.strftime('%Y-%m-%d')
        normalized = _normalize_broker_name(broker_name)
        pv = float(portfolio_value or 0)
        cache_key = f"{normalized}_{snapshot_type}"
        label = "Pre-Market 4AM" if snapshot_type == "pre_market" else "SOD 9:30AM"
        with self._lock:
            self._cache[cache_key] = {
                'buying_power': float(buying_power or 0),
                'options_buying_power': float(options_buying_power or 0),
                'portfolio_value': pv,
                'captured_at': now_et.isoformat(),
                'snapshot_type': snapshot_type,
            }
            self._captured_date[cache_key] = today_str
        print(f"[SOD] [{label}] Captured {normalized}: Stock BP=${buying_power:,.2f}, Options BP=${options_buying_power:,.2f}, Portfolio=${pv:,.2f}")

    def get_snapshot(self, broker_name, snapshot_type="start_of_day"):
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo
        now_et = datetime.now(ZoneInfo('America/New_York'))
        today_str = now_et.strftime('%Y-%m-%d')
        normalized = _normalize_broker_name(broker_name)
        cache_key = f"{normalized}_{snapshot_type}"
        with self._lock:
            if self._captured_date.get(cache_key) != today_str:
                return None
            return self._cache.get(cache_key)

    def is_captured_today(self, broker_name, snapshot_type="start_of_day"):
        snapshot = self.get_snapshot(broker_name, snapshot_type=snapshot_type)
        return snapshot is not None

    def get_all_snapshots(self):
        with self._lock:
            return dict(self._cache)

    def clear(self, snapshot_type=None):
        with self._lock:
            if snapshot_type:
                keys_to_remove = [k for k in self._cache if k.endswith(f"_{snapshot_type}")]
                for k in keys_to_remove:
                    del self._cache[k]
                    self._captured_date.pop(k, None)
                print(f"[SOD] Cache cleared for type={snapshot_type}")
            else:
                self._cache.clear()
                self._captured_date.clear()
                print("[SOD] Cache cleared (all types)")

    async def capture_all_brokers(self, bot_instance, snapshot_type="start_of_day"):
        broker_attrs = [
            'broker', 'webull_paper_broker', 'paper_broker', 'schwab_broker',
            'tastytrade_broker', 'robinhood_broker', 'ibkr_broker', 'questrade_broker'
        ]
        brokers_to_capture = []
        for attr in broker_attrs:
            b = getattr(bot_instance, attr, None)
            if b and hasattr(b, 'name') and hasattr(b, 'get_account_info'):
                brokers_to_capture.append(b)

        if not brokers_to_capture:
            print(f"[SOD] No brokers available for {snapshot_type} capture")
            return

        import asyncio
        label = "Pre-Market 4AM" if snapshot_type == "pre_market" else "SOD 9:30AM"
        print(f"[SOD] [{label}] Capturing balances for {len(brokers_to_capture)} broker(s)...")

        async def _capture_one(broker):
            try:
                account_info = await asyncio.wait_for(broker.get_account_info(), timeout=15)
                if account_info:
                    bp = float(account_info.get('buying_power') or account_info.get('net_liquidation') or 0)
                    opts_bp = float(account_info.get('options_buying_power') or bp)
                    pv = float(account_info.get('net_liquidation') or account_info.get('portfolio_value') or account_info.get('total_equity') or bp)
                    self.capture_snapshot(broker.name, bp, opts_bp, portfolio_value=pv, snapshot_type=snapshot_type)
                else:
                    print(f"[SOD] {broker.name}: get_account_info returned empty")
            except asyncio.TimeoutError:
                print(f"[SOD] {broker.name}: Timed out after 15s")
            except Exception as e:
                print(f"[SOD] {broker.name}: Failed to capture - {e}")

        await asyncio.gather(*[_capture_one(b) for b in brokers_to_capture])

        with self._lock:
            captured = [k for k in self._cache.keys() if k.endswith(f"_{snapshot_type}")]
        print(f"[SOD] [{label}] Capture complete: {captured}")
