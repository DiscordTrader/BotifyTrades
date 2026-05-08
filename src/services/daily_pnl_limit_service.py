import json
import threading
from datetime import datetime

_instance = None
_instance_lock = threading.Lock()


def get_daily_pnl_service():
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = DailyPnLLimitService()
    return _instance


_BROKER_NAME_MAP = {
    'webull': 'WEBULL', 'webull_live': 'WEBULL', 'webull_paper': 'WEBULL_PAPER',
    'alpaca': 'ALPACA', 'alpaca_paper': 'ALPACA',
    'schwab': 'SCHWAB', 'schwab_live': 'SCHWAB',
    'tastytrade': 'TASTYTRADE', 'tastytrade_live': 'TASTYTRADE', 'tastytrade_paper': 'TASTYTRADE',
    'robinhood': 'ROBINHOOD',
    'ibkr': 'IBKR', 'ibkr_live': 'IBKR', 'ibkr_paper': 'IBKR',
    'questrade': 'QUESTRADE',
}


def _normalize(name):
    if not name:
        return name
    return _BROKER_NAME_MAP.get(name.lower().strip(), name.upper())


class DailyPnLLimitService:

    def __init__(self):
        self._lock = threading.Lock()
        self._states = {}
        self._warned = set()
        self._last_reset_date = None
        self._last_tracking_log_ts = {}
        self._load_from_db()

    def _load_from_db(self):
        try:
            from gui_app.database import get_all_daily_pnl_states
            rows = get_all_daily_pnl_states()
            with self._lock:
                for r in rows:
                    self._states[r['broker_name']] = {
                        'lock_type': r.get('lock_type', 'none'),
                        'locked_at': r.get('locked_at'),
                        'sod_equity': float(r.get('sod_equity', 0)),
                        'current_equity': float(r.get('current_equity', 0)),
                        'daily_pnl': float(r.get('daily_pnl', 0)),
                        'daily_pnl_pct': float(r.get('daily_pnl_pct', 0)),
                        'trading_date': r.get('trading_date'),
                        'daily_trade_count': int(r.get('daily_trade_count', 0) or 0),
                    }
        except Exception as e:
            print(f"[DAILY P&L] Error loading from DB: {e}")

    def _get_settings(self):
        try:
            from gui_app.database import get_global_risk_settings
            return get_global_risk_settings()
        except Exception:
            return {}

    def _today_str(self):
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo('America/New_York')).strftime('%Y-%m-%d')

    def _now_iso(self):
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo('America/New_York')).isoformat()

    def _resolve_snapshot_type(self, settings):
        reset_time_str = settings.get('daily_pnl_reset_time') or '09:30'
        if not isinstance(reset_time_str, str):
            reset_time_str = '09:30'
        try:
            parts = reset_time_str.split(':')
            reset_hour = int(parts[0])
            reset_minute = int(parts[1]) if len(parts) > 1 else 0
        except (ValueError, IndexError):
            reset_hour, reset_minute = 9, 30
        if reset_hour < 9 or (reset_hour == 9 and reset_minute < 30):
            return 'pre_market'
        return 'start_of_day'

    def _get_trade_limit_for_broker(self, settings, broker_name):
        default_limit = int(settings.get('max_daily_trades_default', 0) or 0)
        overrides_raw = settings.get('max_daily_trades_overrides', '{}')
        if isinstance(overrides_raw, str):
            try:
                overrides = json.loads(overrides_raw)
            except (json.JSONDecodeError, TypeError):
                overrides = {}
        elif isinstance(overrides_raw, dict):
            overrides = overrides_raw
        else:
            overrides = {}
        normalized = _normalize(broker_name) if broker_name else broker_name
        if normalized in overrides:
            try:
                return int(overrides[normalized])
            except (ValueError, TypeError):
                pass
        if broker_name in overrides:
            try:
                return int(overrides[broker_name])
            except (ValueError, TypeError):
                pass
        return default_limit

    def update_broker_pnl(self, broker_name, current_portfolio_value):
        normalized = _normalize(broker_name)
        settings = self._get_settings()
        if not settings.get('daily_pnl_limit_enabled'):
            return

        snapshot_type = self._resolve_snapshot_type(settings)
        from src.services.sod_balance_cache import get_sod_cache
        sod_cache = get_sod_cache()
        snapshot = sod_cache.get_snapshot(normalized, snapshot_type=snapshot_type)

        if not snapshot and snapshot_type == 'start_of_day':
            snapshot = sod_cache.get_snapshot(normalized, snapshot_type='pre_market')
            if snapshot:
                print(f"[DAILY P&L] {normalized}: SOD snapshot not yet available, using pre-market snapshot as fallback")

        if not snapshot:
            return

        sod_equity = snapshot.get('portfolio_value', 0)
        if sod_equity <= 0:
            return

        if snapshot_type == 'start_of_day':
            pre_market_snap = sod_cache.get_snapshot(normalized, snapshot_type='pre_market')
            if pre_market_snap:
                pre_market_equity = pre_market_snap.get('portfolio_value', 0)
                if pre_market_equity > 0:
                    sod_equity = pre_market_equity

        current_val = float(current_portfolio_value or 0)
        if current_val <= 0:
            return

        daily_pnl = current_val - sod_equity
        daily_pnl_pct = (daily_pnl / sod_equity) * 100.0
        today = self._today_str()

        import time as _time
        _now_ts = _time.monotonic()
        _last_log = self._last_tracking_log_ts.get(normalized, 0)
        if _now_ts - _last_log >= 300:
            print(f"[DAILY P&L] {normalized}: SOD=${sod_equity:,.2f} → Now=${current_val:,.2f} | P&L: ${daily_pnl:+,.2f} ({daily_pnl_pct:+.1f}%)")
            self._last_tracking_log_ts[normalized] = _now_ts

        with self._lock:
            state = self._states.get(normalized, {})
            existing_lock = state.get('lock_type', 'none')
            preserved_trade_count = state.get('daily_trade_count', 0)

            if existing_lock != 'none' and state.get('trading_date') == today:
                state['sod_equity'] = sod_equity
                state['current_equity'] = current_val
                state['daily_pnl'] = daily_pnl
                state['daily_pnl_pct'] = daily_pnl_pct
                self._states[normalized] = state
                self._persist_state(normalized, state)
                return

            new_lock = 'none'
            lock_reason = ''

            loss_limit_dollar = float(settings.get('daily_loss_limit_dollar', 0) or settings.get('global_daily_loss_limit', 0))
            loss_limit_pct = float(settings.get('daily_loss_limit_pct', 0))
            profit_limit_dollar = float(settings.get('daily_profit_limit', 0))
            profit_limit_pct = float(settings.get('daily_profit_limit_pct', 0))
            warning_pct = float(settings.get('daily_pnl_warning_pct', 80))

            if daily_pnl < 0:
                if loss_limit_dollar > 0 and abs(daily_pnl) >= loss_limit_dollar:
                    new_lock = 'loss'
                    lock_reason = f'Loss ${abs(daily_pnl):,.2f} >= limit ${loss_limit_dollar:,.2f}'
                elif loss_limit_pct > 0 and abs(daily_pnl_pct) >= loss_limit_pct:
                    new_lock = 'loss'
                    lock_reason = f'Loss {abs(daily_pnl_pct):.1f}% >= limit {loss_limit_pct:.1f}%'
            elif daily_pnl > 0:
                if profit_limit_dollar > 0 and daily_pnl >= profit_limit_dollar:
                    new_lock = 'profit'
                    lock_reason = f'Profit ${daily_pnl:,.2f} >= target ${profit_limit_dollar:,.2f}'
                elif profit_limit_pct > 0 and daily_pnl_pct >= profit_limit_pct:
                    new_lock = 'profit'
                    lock_reason = f'Profit {daily_pnl_pct:.1f}% >= target {profit_limit_pct:.1f}%'

            now_iso = self._now_iso()
            state = {
                'lock_type': new_lock,
                'locked_at': now_iso if new_lock != 'none' else None,
                'sod_equity': sod_equity,
                'current_equity': current_val,
                'daily_pnl': daily_pnl,
                'daily_pnl_pct': daily_pnl_pct,
                'trading_date': today,
                'daily_trade_count': preserved_trade_count if state.get('trading_date') == today else 0,
            }
            self._states[normalized] = state
            state_copy = dict(state)
            self._persist_state(normalized, state_copy)

        if new_lock != 'none':
            print(f"[DAILY P&L] ⛔ {normalized} LOCKED ({new_lock}) — {lock_reason} | P&L: ${daily_pnl:+,.2f} ({daily_pnl_pct:+.1f}%)")
            self._log_lock_event(normalized, new_lock, lock_reason, state)
            try:
                from src.services.relay_client import get_relay_client
                _rc = get_relay_client()
                if _rc and _rc.connected:
                    import asyncio, time as _t
                    asyncio.ensure_future(_rc.send_alert({
                        'level': 'critical',
                        'msg': f"Daily {new_lock} limit reached on {normalized} — {lock_reason}",
                        'ts': _t.time(),
                    }))
            except Exception:
                pass
        else:
            self._check_warning(normalized, daily_pnl, daily_pnl_pct, settings, warning_pct)

    def _check_warning(self, broker_name, daily_pnl, daily_pnl_pct, settings, warning_pct):
        if warning_pct <= 0 or warning_pct >= 100:
            return
        warn_key = f"{broker_name}_{self._today_str()}"
        if warn_key in self._warned:
            return

        loss_limit_dollar = float(settings.get('daily_loss_limit_dollar', 0) or settings.get('global_daily_loss_limit', 0))
        loss_limit_pct = float(settings.get('daily_loss_limit_pct', 0))
        profit_limit_dollar = float(settings.get('daily_profit_limit', 0))
        profit_limit_pct = float(settings.get('daily_profit_limit_pct', 0))
        threshold_ratio = warning_pct / 100.0

        warned = False
        if daily_pnl < 0:
            if loss_limit_dollar > 0 and abs(daily_pnl) >= loss_limit_dollar * threshold_ratio:
                print(f"[DAILY P&L] ⚠️ {broker_name} WARNING: Loss ${abs(daily_pnl):,.2f} approaching limit ${loss_limit_dollar:,.2f} ({warning_pct:.0f}% threshold)")
                warned = True
            elif loss_limit_pct > 0 and abs(daily_pnl_pct) >= loss_limit_pct * threshold_ratio:
                print(f"[DAILY P&L] ⚠️ {broker_name} WARNING: Loss {abs(daily_pnl_pct):.1f}% approaching limit {loss_limit_pct:.1f}% ({warning_pct:.0f}% threshold)")
                warned = True
        elif daily_pnl > 0:
            if profit_limit_dollar > 0 and daily_pnl >= profit_limit_dollar * threshold_ratio:
                print(f"[DAILY P&L] ⚠️ {broker_name} WARNING: Profit ${daily_pnl:,.2f} approaching target ${profit_limit_dollar:,.2f} ({warning_pct:.0f}% threshold)")
                warned = True
            elif profit_limit_pct > 0 and daily_pnl_pct >= profit_limit_pct * threshold_ratio:
                print(f"[DAILY P&L] ⚠️ {broker_name} WARNING: Profit {daily_pnl_pct:.1f}% approaching target {profit_limit_pct:.1f}% ({warning_pct:.0f}% threshold)")
                warned = True
        if warned:
            self._warned.add(warn_key)

    def _persist_state(self, broker_name, state):
        try:
            from gui_app.database import update_daily_pnl_state
            update_daily_pnl_state(
                broker_name=broker_name,
                lock_type=state.get('lock_type', 'none'),
                sod_equity=state.get('sod_equity', 0),
                current_equity=state.get('current_equity', 0),
                daily_pnl=state.get('daily_pnl', 0),
                daily_pnl_pct=state.get('daily_pnl_pct', 0),
                trading_date=state.get('trading_date'),
                locked_at=state.get('locked_at'),
                daily_trade_count=state.get('daily_trade_count'),
            )
        except Exception as e:
            print(f"[DAILY P&L] Error persisting state for {broker_name}: {e}")

    def _log_lock_event(self, broker_name, lock_type, reason, state):
        try:
            from gui_app.database import log_risk_event
            log_risk_event(
                event_type=f'DAILY_PNL_{lock_type.upper()}_LOCK',
                source='daily_pnl_limit_service',
                details={
                    'broker': broker_name,
                    'lock_type': lock_type,
                    'reason': reason,
                    'daily_pnl': state.get('daily_pnl', 0),
                    'daily_pnl_pct': state.get('daily_pnl_pct', 0),
                    'sod_equity': state.get('sod_equity', 0),
                    'current_equity': state.get('current_equity', 0),
                    'daily_trade_count': state.get('daily_trade_count', 0),
                }
            )
        except Exception as e:
            print(f"[DAILY P&L] Error logging lock event: {e}")

    def record_bto_trade(self, broker_name):
        normalized = _normalize(broker_name)
        settings = self._get_settings()
        pnl_enabled = settings.get('daily_pnl_limit_enabled')
        trade_limit = self._get_trade_limit_for_broker(settings, normalized)
        if not pnl_enabled and trade_limit <= 0:
            return
        today = self._today_str()

        should_lock = False
        with self._lock:
            state = self._states.get(normalized)
            if not state or state.get('trading_date') != today:
                state = {
                    'lock_type': 'none',
                    'locked_at': None,
                    'sod_equity': 0,
                    'current_equity': 0,
                    'daily_pnl': 0,
                    'daily_pnl_pct': 0,
                    'trading_date': today,
                    'daily_trade_count': 0,
                }
            if not pnl_enabled and state.get('lock_type', 'none') not in ('none', 'trades'):
                state['lock_type'] = 'none'
                state['locked_at'] = None

            new_count = state.get('daily_trade_count', 0) + 1
            state['daily_trade_count'] = new_count

            current_lock = state.get('lock_type', 'none')
            if trade_limit > 0 and new_count >= trade_limit and current_lock == 'none':
                state['lock_type'] = 'trades'
                state['locked_at'] = self._now_iso()
                should_lock = True

            self._states[normalized] = state
            state_copy = dict(state)
            self._persist_state(normalized, state_copy)

        if should_lock:
            print(f"[DAILY P&L] ⛔ {normalized} LOCKED (trades) — {new_count}/{trade_limit} trades reached")
            self._log_lock_event(normalized, 'trades', f'{new_count}/{trade_limit} daily trades reached', state_copy)
        elif trade_limit > 0:
            print(f"[DAILY P&L] {normalized}: Trade {new_count}/{trade_limit} recorded")
        else:
            print(f"[DAILY P&L] {normalized}: Trade {new_count} recorded (no limit set)")

    def decrement_bto_trade(self, broker_name, reason=''):
        normalized = _normalize(broker_name)
        settings = self._get_settings()
        trade_limit = self._get_trade_limit_for_broker(settings, normalized)
        today = self._today_str()
        unlocked = False

        with self._lock:
            state = self._states.get(normalized)
            if not state or state.get('trading_date') != today:
                return
            current_count = state.get('daily_trade_count', 0)
            if current_count <= 0:
                return
            new_count = current_count - 1
            state['daily_trade_count'] = new_count

            if state.get('lock_type') == 'trades' and trade_limit > 0 and new_count < trade_limit:
                state['lock_type'] = 'none'
                state['locked_at'] = None
                unlocked = True

            self._states[normalized] = state
            self._persist_state(normalized, dict(state))

        reason_str = f" ({reason})" if reason else ""
        if unlocked:
            print(f"[DAILY P&L] 🔓 {normalized} UNLOCKED — trade count decremented to {new_count}/{trade_limit}{reason_str}")
        else:
            print(f"[DAILY P&L] {normalized}: Trade count decremented to {new_count}/{trade_limit}{reason_str}")

    def check_broker_locked(self, broker_name) -> dict:
        normalized = _normalize(broker_name)
        settings = self._get_settings()
        pnl_enabled = settings.get('daily_pnl_limit_enabled')
        trade_limit = self._get_trade_limit_for_broker(settings, normalized)
        if not pnl_enabled and trade_limit <= 0:
            return {'locked': False, 'lock_type': None, 'daily_pnl': 0, 'daily_pnl_pct': 0, 'sod_equity': 0, 'current_equity': 0, 'daily_trade_count': 0}

        today = self._today_str()
        state_copy = None

        with self._lock:
            state = self._states.get(normalized, {})
            if state.get('trading_date') != today:
                return {'locked': False, 'lock_type': None, 'daily_pnl': 0, 'daily_pnl_pct': 0, 'sod_equity': 0, 'current_equity': 0, 'daily_trade_count': 0}

            lock_type = state.get('lock_type', 'none')
            trade_count = state.get('daily_trade_count', 0)

            if not pnl_enabled and lock_type not in ('none', 'trades'):
                lock_type = 'none'
                state['lock_type'] = 'none'
                state['locked_at'] = None

            if lock_type == 'none' and trade_limit > 0 and trade_count >= trade_limit:
                lock_type = 'trades'
                state['lock_type'] = 'trades'
                state['locked_at'] = self._now_iso()

            self._states[normalized] = state
            if state.get('lock_type') == 'trades' and lock_type == 'trades':
                state_copy = dict(state)
                self._persist_state(normalized, state_copy)

        if state_copy:
            print(f"[DAILY P&L] ⛔ {normalized} LOCKED (trades) — {trade_count}/{trade_limit} trades (caught in check)")
            self._log_lock_event(normalized, 'trades', f'{trade_count}/{trade_limit} daily trades reached (catch-up)', state_copy)

        return {
            'locked': lock_type != 'none',
            'lock_type': lock_type if lock_type != 'none' else None,
            'daily_pnl': state.get('daily_pnl', 0),
            'daily_pnl_pct': state.get('daily_pnl_pct', 0),
            'sod_equity': state.get('sod_equity', 0),
            'current_equity': state.get('current_equity', 0),
            'daily_trade_count': trade_count,
            'daily_trade_limit': trade_limit,
        }

    def get_all_states(self) -> list:
        settings = self._get_settings()
        enabled = bool(settings.get('daily_pnl_limit_enabled'))
        today = self._today_str()
        result = []
        with self._lock:
            for broker_name, state in self._states.items():
                if state.get('trading_date') == today:
                    lock_type = state.get('lock_type', 'none')
                    trade_count = state.get('daily_trade_count', 0)
                    trade_limit = self._get_trade_limit_for_broker(settings, broker_name)
                    result.append({
                        'broker_name': broker_name,
                        'locked': lock_type != 'none',
                        'lock_type': lock_type if lock_type != 'none' else None,
                        'locked_at': state.get('locked_at'),
                        'daily_pnl': state.get('daily_pnl', 0),
                        'daily_pnl_pct': state.get('daily_pnl_pct', 0),
                        'sod_equity': state.get('sod_equity', 0),
                        'current_equity': state.get('current_equity', 0),
                        'daily_trade_count': trade_count,
                        'daily_trade_limit': trade_limit,
                    })

        loss_limit = float(settings.get('daily_loss_limit_dollar', 0) or settings.get('global_daily_loss_limit', 0))
        loss_limit_pct = float(settings.get('daily_loss_limit_pct', 0))
        profit_limit = float(settings.get('daily_profit_limit', 0))
        profit_limit_pct = float(settings.get('daily_profit_limit_pct', 0))
        warning_pct = float(settings.get('daily_pnl_warning_pct', 80))
        max_trades_default = int(settings.get('max_daily_trades_default', 0) or 0)

        for item in result:
            pnl = item['daily_pnl']
            pnl_pct = item['daily_pnl_pct']
            warning = 'none'
            if not item['locked']:
                threshold_ratio = warning_pct / 100.0 if warning_pct > 0 else 0
                if pnl < 0 and threshold_ratio > 0:
                    if (loss_limit > 0 and abs(pnl) >= loss_limit * threshold_ratio) or \
                       (loss_limit_pct > 0 and abs(pnl_pct) >= loss_limit_pct * threshold_ratio):
                        warning = 'loss'
                elif pnl > 0 and threshold_ratio > 0:
                    if (profit_limit > 0 and pnl >= profit_limit * threshold_ratio) or \
                       (profit_limit_pct > 0 and pnl_pct >= profit_limit_pct * threshold_ratio):
                        warning = 'profit'
            item['warning'] = warning

        snapshot_type = self._resolve_snapshot_type(settings)
        return {
            'enabled': enabled,
            'snapshot_type': snapshot_type,
            'limits': {
                'loss_dollar': loss_limit,
                'loss_pct': loss_limit_pct,
                'profit_dollar': profit_limit,
                'profit_pct': profit_limit_pct,
                'warning_pct': warning_pct,
                'max_trades_default': max_trades_default,
            },
            'brokers': result,
        }

    def unlock_broker(self, broker_name: str) -> bool:
        normalized = _normalize(broker_name)
        with self._lock:
            state = self._states.get(normalized)
            if not state or state.get('lock_type', 'none') == 'none':
                return False
            old_lock = state.get('lock_type')
            state['lock_type'] = 'none'
            state['locked_at'] = None
            self._states[normalized] = state
            self._persist_state(normalized, dict(state))
        self._warned.discard(normalized)
        print(f"[DAILY P&L] 🔓 {normalized} MANUALLY UNLOCKED (was: {old_lock})")
        return True

    def reset_all(self):
        with self._lock:
            self._states.clear()
            self._warned.clear()
        try:
            from gui_app.database import reset_daily_pnl_states
            reset_daily_pnl_states()
        except Exception as e:
            print(f"[DAILY P&L] Error resetting DB states: {e}")
        print("[DAILY P&L] All locks and trade counts cleared — new trading day")

    def check_and_reset_if_new_day(self):
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo
        now_et = datetime.now(ZoneInfo('America/New_York'))
        today = now_et.strftime('%Y-%m-%d')
        settings = self._get_settings()
        reset_time_str = settings.get('daily_pnl_reset_time', '09:30')
        try:
            parts = reset_time_str.split(':')
            reset_hour = int(parts[0])
            reset_minute = int(parts[1]) if len(parts) > 1 else 0
        except (ValueError, IndexError):
            reset_hour, reset_minute = 9, 30

        reset_key = f"{today}_{reset_hour}:{reset_minute:02d}"
        if self._last_reset_date == reset_key:
            return

        if now_et.hour > reset_hour or (now_et.hour == reset_hour and now_et.minute >= reset_minute):
            if self._last_reset_date is not None and self._last_reset_date != reset_key:
                self.reset_all()
            self._last_reset_date = reset_key
