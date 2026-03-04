import time
import threading
from datetime import datetime

_sod_cache = {}
_sod_lock = threading.Lock()
_instance = None


def get_sod_cache():
    global _instance
    if _instance is None:
        _instance = SODBalanceCache()
    return _instance


class SODBalanceCache:

    def __init__(self):
        self._cache = {}
        self._captured_date = None

    def capture_snapshot(self, broker_name, buying_power, options_buying_power):
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo
        now_et = datetime.now(ZoneInfo('America/New_York'))
        today_str = now_et.strftime('%Y-%m-%d')
        self._cache[broker_name] = {
            'buying_power': float(buying_power or 0),
            'options_buying_power': float(options_buying_power or 0),
            'captured_at': now_et.isoformat(),
        }
        self._captured_date = today_str
        print(f"[SOD] ✓ Captured {broker_name}: Stock BP=${buying_power:,.2f}, Options BP=${options_buying_power:,.2f}")

    def get_snapshot(self, broker_name):
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo
        now_et = datetime.now(ZoneInfo('America/New_York'))
        today_str = now_et.strftime('%Y-%m-%d')
        if self._captured_date != today_str:
            return None
        return self._cache.get(broker_name)

    def is_captured_today(self, broker_name):
        snapshot = self.get_snapshot(broker_name)
        return snapshot is not None

    def get_all_snapshots(self):
        return dict(self._cache)

    def clear(self):
        self._cache.clear()
        self._captured_date = None
        print("[SOD] Cache cleared")

    async def capture_all_brokers(self, bot_instance):
        brokers_to_capture = []
        if hasattr(bot_instance, 'broker') and bot_instance.broker:
            b = bot_instance.broker
            if hasattr(b, 'name') and hasattr(b, 'get_account_info'):
                brokers_to_capture.append(b)
        if hasattr(bot_instance, 'webull_paper_broker') and bot_instance.webull_paper_broker:
            b = bot_instance.webull_paper_broker
            if hasattr(b, 'name') and hasattr(b, 'get_account_info'):
                brokers_to_capture.append(b)
        if hasattr(bot_instance, 'paper_broker') and bot_instance.paper_broker:
            b = bot_instance.paper_broker
            if hasattr(b, 'name') and hasattr(b, 'get_account_info'):
                brokers_to_capture.append(b)
        if hasattr(bot_instance, 'schwab_broker') and bot_instance.schwab_broker:
            b = bot_instance.schwab_broker
            if hasattr(b, 'name') and hasattr(b, 'get_account_info'):
                brokers_to_capture.append(b)
        if hasattr(bot_instance, 'tastytrade_broker') and bot_instance.tastytrade_broker:
            b = bot_instance.tastytrade_broker
            if hasattr(b, 'name') and hasattr(b, 'get_account_info'):
                brokers_to_capture.append(b)
        if hasattr(bot_instance, 'robinhood_broker') and bot_instance.robinhood_broker:
            b = bot_instance.robinhood_broker
            if hasattr(b, 'name') and hasattr(b, 'get_account_info'):
                brokers_to_capture.append(b)
        if hasattr(bot_instance, 'ibkr_broker') and bot_instance.ibkr_broker:
            b = bot_instance.ibkr_broker
            if hasattr(b, 'name') and hasattr(b, 'get_account_info'):
                brokers_to_capture.append(b)

        if not brokers_to_capture:
            print("[SOD] ⚠️ No brokers available for SOD capture")
            return

        print(f"[SOD] 📸 Capturing start-of-day balances for {len(brokers_to_capture)} broker(s)...")
        for broker in brokers_to_capture:
            try:
                account_info = await broker.get_account_info()
                if account_info:
                    bp = float(account_info.get('buying_power') or account_info.get('net_liquidation') or 0)
                    opts_bp = float(account_info.get('options_buying_power') or bp)
                    self.capture_snapshot(broker.name, bp, opts_bp)
                else:
                    print(f"[SOD] ⚠️ {broker.name}: get_account_info returned empty")
            except Exception as e:
                print(f"[SOD] ⚠️ {broker.name}: Failed to capture - {e}")

        print(f"[SOD] ✓ SOD capture complete: {list(self._cache.keys())}")
