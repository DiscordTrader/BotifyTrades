"""
Live Snapshot Cache Layer
=========================
Background daemon thread that periodically fetches positions from all connected brokers,
stores results in a thread-safe in-memory cache, and provides instant reads (<50ms)
for the Live Monitoring page instead of blocking on broker APIs.
"""

import asyncio
import copy
import logging
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

import gui_app.database as db

_snapshot_cache: Dict[str, Any] = {
    'positions': [],
    'prices': {},
    'risk_states': {},
    'broker_status': {},
    'last_updated': 0,
    'updating': False,
}
_snapshot_lock = threading.Lock()

_daemon_thread: Optional[threading.Thread] = None
_daemon_stop_event = threading.Event()
_daemon_started = False

_snapshot_version = 0
_snapshot_version_lock = threading.Lock()
_sse_clients: List = []
_sse_clients_lock = threading.Lock()
_prev_position_ids: set = set()

_BROKER_INTERVALS = {
    'WEBULL': 3,
    'ALPACA_PAPER': 5,
    'ROBINHOOD': 5,
    'SCHWAB': 5,
    'IBKR': 5,
    'TASTYTRADE': 5,
    'TRADING212': 6,
    'WEBULL_OFFICIAL': 6,
}
_broker_last_fetch: Dict[str, float] = {}
_broker_last_fetch_lock = threading.Lock()

_force_refresh_event = threading.Event()


def request_force_refresh():
    _force_refresh_event.set()


def get_snapshot_version() -> int:
    with _snapshot_version_lock:
        return _snapshot_version


def subscribe_sse():
    import queue
    q = queue.Queue(maxsize=50)
    with _sse_clients_lock:
        _sse_clients.append(q)
    return q


def unsubscribe_sse(q):
    with _sse_clients_lock:
        try:
            _sse_clients.remove(q)
        except ValueError:
            pass


def _notify_sse_clients(payload):
    with _sse_clients_lock:
        dead = []
        for q in _sse_clients:
            try:
                q.put_nowait(payload)
            except Exception:
                dead.append(q)
        for q in dead:
            try:
                _sse_clients.remove(q)
            except ValueError:
                pass


_snapshot_log_verbose = False
_snapshot_log_last_summary = 0
_snapshot_log_seen_warnings = set()

def _log(msg: str):
    if not _snapshot_log_verbose and '[ENRICH]' in msg:
        return
    global _snapshot_log_last_summary
    if msg.startswith('Refreshed:'):
        now = time.time()
        if now - _snapshot_log_last_summary < 60:
            return
        _snapshot_log_last_summary = now
    if 'option fallback' in msg or 'fetch error' in msg:
        if msg in _snapshot_log_seen_warnings:
            return
        _snapshot_log_seen_warnings.add(msg)
    import sys
    sys.stderr.write(f"[SNAPSHOT] {msg}\n")
    sys.stderr.flush()


def _make_position(
    pos_id,
    symbol: str,
    asset_type: str = 'stock',
    strike=None,
    expiry=None,
    call_put=None,
    quantity: int = 0,
    entry_price: float = 0.0,
    current_price: float = 0.0,
    bid: float = 0.0,
    ask: float = 0.0,
    mid: float = 0.0,
    last: float = 0.0,
    unrealized_pnl: float = 0.0,
    pnl_pct: float = 0.0,
    broker: str = '',
    source: str = 'live_brokerage',
    status: str = 'OPEN',
    direction: str = '',
    order_id=None,
    fill_status=None,
    raw_symbol: str = '',
) -> Dict[str, Any]:
    return {
        'id': pos_id,
        'symbol': symbol,
        'asset_type': asset_type,
        'strike': strike,
        'expiry': expiry,
        'call_put': call_put,
        'quantity': int(quantity) if quantity else 0,
        'entry_price': float(entry_price or 0),
        'current_price': float(current_price or 0),
        'bid': float(bid or 0),
        'ask': float(ask or 0),
        'mid': float(mid or 0),
        'last': float(last or 0),
        'unrealized_pnl': float(unrealized_pnl or 0),
        'pnl_pct': float(pnl_pct or 0),
        'broker': broker,
        'source': source,
        'status': status,
        'direction': direction,
        'order_id': order_id,
        'fill_status': fill_status,
        'raw_symbol': raw_symbol or '',
    }


def _try_hub_positions(hub_getter, broker_label: str) -> Optional[List[Dict]]:
    try:
        hub = hub_getter()
        if not hub or not hub.is_streaming():
            return None
        cached = hub.get_positions()
        if cached is None:
            return None
        return cached
    except Exception:
        return None


def _fetch_webull(bot) -> List[Dict]:
    try:
        if not hasattr(bot, 'broker') or bot.broker is None:
            return []

        broker = bot.broker
        webull_broker = None
        if hasattr(broker, 'brokers'):
            webull_broker = broker.brokers.get('Webull')
        elif hasattr(broker, '_client') or hasattr(broker, 'wb'):
            webull_broker = broker

        if not webull_broker:
            return []

        wb_client = getattr(webull_broker, '_client', None) or getattr(webull_broker, 'wb', None)
        if not wb_client:
            return []

        positions_raw = None
        try:
            from src.services.webull_data_hub import get_webull_data_hub
            hub = get_webull_data_hub()
            if hub.is_streaming() and hub.get_positions_age() < 60:
                cached = hub.get_positions()
                if cached is not None:
                    positions_raw = list(cached)
        except Exception:
            pass

        if positions_raw is None:
            positions_raw = wb_client.get_positions() or []

        positions = []
        for pos in positions_raw:
            position_qty = float(pos.get('position', 0))
            if position_qty <= 0:
                continue

            symbol = pos.get('ticker', {}).get('symbol', '') or pos.get('symbol', '')
            asset_type = pos.get('assetType', 'unknown')
            ticker_data = pos.get('ticker', {})
            is_option = (
                'optionId' in pos or
                'strikePrice' in pos or
                'strikePrice' in ticker_data or
                asset_type.lower() in ('option', 'opt')
            )

            strike = None
            expiry = None
            call_put = None
            if is_option:
                strike = float(pos.get('strikePrice', 0) or ticker_data.get('strikePrice', 0) or 0)
                direction = (pos.get('direction', '') or pos.get('optionType', '') or ticker_data.get('direction', '') or '').upper()
                call_put = 'C' if direction in ('CALL', 'C') else ('P' if direction in ('PUT', 'P') else '')
                raw_expiry = pos.get('expireDate', '') or ticker_data.get('expireDate', '') or ''
                if raw_expiry and '-' in raw_expiry:
                    from datetime import datetime
                    try:
                        exp_date = datetime.strptime(raw_expiry, '%Y-%m-%d')
                        expiry = exp_date.strftime('%m/%d')
                    except Exception:
                        expiry = raw_expiry
                else:
                    expiry = raw_expiry

                if (not strike or strike == 0.0) and ticker_data:
                    import re
                    dis_symbol = ticker_data.get('disSymbol', '') or ''
                    name_val = ticker_data.get('name', '') or ''
                    _log(f"[WEBULL-POS] {symbol} option fallback: disSymbol='{dis_symbol}', name='{name_val}', assetType={asset_type}")

                    opt_id_for_reverse = pos.get('optionId', 0) or ticker_data.get('tickerId', 0)
                    reverse_found = False
                    if opt_id_for_reverse and webull_broker:
                        try:
                            reverse = webull_broker.get_option_details_by_id(opt_id_for_reverse)
                            if not reverse:
                                tid_for_reverse = ticker_data.get('tickerId', 0)
                                if tid_for_reverse and tid_for_reverse != opt_id_for_reverse:
                                    reverse = webull_broker.get_option_details_by_id(tid_for_reverse)
                            if reverse:
                                strike = reverse['strike']
                                call_put = reverse['option_type']
                                raw_exp = reverse['expiry']
                                if raw_exp and '-' in raw_exp:
                                    from datetime import datetime as dt
                                    try:
                                        expiry = dt.strptime(raw_exp, '%Y-%m-%d').strftime('%m/%d')
                                    except Exception:
                                        expiry = raw_exp
                                else:
                                    expiry = raw_exp
                                reverse_found = True
                                _log(f"[WEBULL-POS] ✓ Reverse cache enriched: {symbol} {strike} {call_put} {expiry}")
                        except Exception:
                            pass

                    if not reverse_found:
                        m = re.match(r'^(\w+)\s+(\d{2}/\d{2}/\d{4})\s+([\d.]+)\s+(Put|Call)$', dis_symbol, re.IGNORECASE)
                        if m:
                            from datetime import datetime as dt
                            try:
                                exp_date = dt.strptime(m.group(2), '%m/%d/%Y')
                                expiry = exp_date.strftime('%m/%d')
                            except Exception:
                                expiry = m.group(2)[:5]
                            strike = float(m.group(3))
                            call_put = 'C' if m.group(4).upper() == 'CALL' else 'P'
                        else:
                            name_field = ticker_data.get('name', '') or ''
                            m2 = re.search(r'(\d+(?:\.\d+)?)\s+(Put|Call)\s+(\d{2}/\d{2}/\d{2,4})', name_field, re.IGNORECASE)
                            if m2:
                                strike = float(m2.group(1))
                                call_put = 'C' if m2.group(2).upper() == 'CALL' else 'P'
                                try:
                                    from datetime import datetime as dt
                                    exp_str = m2.group(3)
                                    if len(exp_str) == 8:
                                        exp_date = dt.strptime(exp_str, '%m/%d/%y')
                                    else:
                                        exp_date = dt.strptime(exp_str, '%m/%d/%Y')
                                    expiry = exp_date.strftime('%m/%d')
                                except Exception:
                                    expiry = m2.group(3)[:5]

            avg_cost = float(pos.get('costPrice', 0))
            cur_price = float(pos.get('latestPrice', 0) or pos.get('lastPrice', 0))
            if is_option and cur_price > 0 and avg_cost > 0 and cur_price / avg_cost > 50:
                market_value = float(pos.get('marketValue', 0))
                mv_price = market_value / (position_qty * 100) if position_qty > 0 else 0
                if mv_price > 0 and (mv_price / avg_cost if avg_cost > 0 else 0) < 50:
                    cur_price = mv_price
                else:
                    cur_price = avg_cost
            unrealized = (cur_price - avg_cost) * position_qty
            if is_option:
                unrealized *= 100
            pnl_pct = ((cur_price - avg_cost) / avg_cost * 100) if avg_cost > 0 else 0.0

            positions.append(_make_position(
                pos_id=pos.get('position_id', f"WB_{symbol}"),
                symbol=symbol,
                asset_type='option' if is_option else 'stock',
                strike=strike,
                expiry=expiry,
                call_put=call_put,
                quantity=position_qty,
                entry_price=avg_cost,
                current_price=cur_price,
                bid=float(pos.get('bid', 0)),
                ask=float(pos.get('ask', 0)),
                mid=float(pos.get('mid', 0)),
                last=float(pos.get('last', cur_price)),
                unrealized_pnl=unrealized,
                pnl_pct=pnl_pct,
                broker='WEBULL',
                source='live_brokerage',
            ))
        return positions
    except Exception as e:
        _log(f"Webull fetch error: {e}")
        return []


def _fetch_webull_paper(bot) -> List[Dict]:
    try:
        paper_broker = getattr(bot, 'webull_paper_broker', None)
        if not paper_broker:
            if hasattr(bot, 'broker') and hasattr(bot.broker, 'brokers'):
                paper_broker = bot.broker.brokers.get('Webull_Paper') or bot.broker.brokers.get('WEBULL_PAPER')
            if not paper_broker:
                return []

        wb_client = getattr(paper_broker, '_client', None) or getattr(paper_broker, 'wb', None)
        if not wb_client:
            return []

        positions_raw = wb_client.get_positions() or []
        positions = []
        for pos in positions_raw:
            position_qty = float(pos.get('position', 0))
            if position_qty <= 0:
                continue

            symbol = pos.get('ticker', {}).get('symbol', '') or pos.get('symbol', '')
            asset_type = pos.get('assetType', 'unknown')
            ticker_data = pos.get('ticker', {})
            is_option = (
                'optionId' in pos or
                'strikePrice' in pos or
                'strikePrice' in ticker_data or
                asset_type.lower() in ('option', 'opt')
            )

            strike = None
            expiry = None
            call_put = None
            if is_option:
                strike = float(pos.get('strikePrice', 0) or ticker_data.get('strikePrice', 0) or 0)
                direction = (pos.get('direction', '') or pos.get('optionType', '') or ticker_data.get('direction', '') or '').upper()
                call_put = 'C' if direction in ('CALL', 'C') else ('P' if direction in ('PUT', 'P') else '')
                raw_expiry = pos.get('expireDate', '') or ticker_data.get('expireDate', '') or ''
                if raw_expiry and '-' in raw_expiry:
                    from datetime import datetime
                    try:
                        exp_date = datetime.strptime(raw_expiry, '%Y-%m-%d')
                        expiry = exp_date.strftime('%m/%d')
                    except Exception:
                        expiry = raw_expiry
                else:
                    expiry = raw_expiry

            avg_cost = float(pos.get('costPrice', 0))
            cur_price = float(pos.get('latestPrice', 0) or pos.get('lastPrice', 0))
            if is_option and cur_price > 0 and avg_cost > 0 and cur_price / avg_cost > 50:
                market_value = float(pos.get('marketValue', 0))
                mv_price = market_value / (position_qty * 100) if position_qty > 0 else 0
                if mv_price > 0 and (mv_price / avg_cost if avg_cost > 0 else 0) < 50:
                    cur_price = mv_price
                else:
                    cur_price = avg_cost
            unrealized = (cur_price - avg_cost) * position_qty
            if is_option:
                unrealized *= 100
            pnl_pct = ((cur_price - avg_cost) / avg_cost * 100) if avg_cost > 0 else 0.0

            positions.append(_make_position(
                pos_id=pos.get('position_id', f"WBP_{symbol}"),
                symbol=symbol,
                asset_type='option' if is_option else 'stock',
                strike=strike,
                expiry=expiry,
                call_put=call_put,
                quantity=position_qty,
                entry_price=avg_cost,
                current_price=cur_price,
                bid=float(pos.get('bid', 0)),
                ask=float(pos.get('ask', 0)),
                mid=float(pos.get('mid', 0)),
                last=float(pos.get('last', cur_price)),
                unrealized_pnl=unrealized,
                pnl_pct=pnl_pct,
                broker='WEBULL_PAPER',
                source='live_brokerage',
            ))
        return positions
    except Exception as e:
        _log(f"Webull Paper fetch error: {e}")
        return []


def _fetch_alpaca(bot) -> List[Dict]:
    try:
        paper_broker = None
        if hasattr(bot, 'paper_broker') and bot.paper_broker is not None:
            paper_broker = bot.paper_broker
        elif hasattr(bot, 'broker') and hasattr(bot.broker, 'brokers'):
            paper_broker = bot.broker.brokers.get('Alpaca') or bot.broker.brokers.get('ALPACA_PAPER')

        if not paper_broker:
            return []
        if not hasattr(paper_broker, 'trading_client') or not paper_broker.trading_client:
            return []

        positions_raw = paper_broker.trading_client.get_all_positions()
        results = []
        for pos in positions_raw:
            symbol = str(getattr(pos, 'symbol', ''))
            qty = float(getattr(pos, 'qty', 0))
            avg_entry = float(getattr(pos, 'avg_entry_price', 0))
            current = float(getattr(pos, 'current_price', 0))
            unrealized = float(getattr(pos, 'unrealized_pl', 0))
            asset_class = str(getattr(pos, 'asset_class', 'us_equity')).lower()
            is_option = 'option' in asset_class

            pnl_pct = ((current - avg_entry) / avg_entry * 100) if avg_entry > 0 else 0.0

            results.append(_make_position(
                pos_id=str(getattr(pos, 'asset_id', f"ALP_{symbol}")),
                symbol=symbol,
                asset_type='option' if is_option else 'stock',
                quantity=qty,
                entry_price=avg_entry,
                current_price=current,
                last=current,
                unrealized_pnl=unrealized,
                pnl_pct=pnl_pct,
                broker='ALPACA_PAPER',
                source='live_brokerage',
            ))
        return results
    except Exception as e:
        _log(f"Alpaca fetch error: {e}")
        return []


_rh_cache = {'positions': [], 'ts': 0}

def _fetch_robinhood(bot) -> List[Dict]:
    try:
        if not hasattr(bot, 'robinhood_broker') or bot.robinhood_broker is None:
            return []

        rh_broker = bot.robinhood_broker
        if time.time() - _rh_cache['ts'] < 15 and _rh_cache['positions']:
            raw = _rh_cache['positions']
        else:
            raw = rh_broker.get_all_positions()
            if raw:
                _rh_cache['positions'] = raw
                _rh_cache['ts'] = time.time()
        if not raw:
            return []

        positions = []
        for pos in raw:
            qty = float(pos.get('quantity', 0))
            avg_price = float(pos.get('avg_price') or pos.get('average_buy_price') or 0)
            cur_price = float(pos.get('current_price', 0))
            unrealized = float(pos.get('unrealized_pnl', 0))
            pnl_pct = ((cur_price - avg_price) / avg_price * 100) if avg_price > 0 else 0.0
            asset_type = pos.get('asset_type') or pos.get('type', 'stock')

            call_put = None
            if pos.get('call_put'):
                call_put = pos['call_put']
            elif pos.get('option_type'):
                ot = str(pos['option_type']).upper()
                call_put = 'C' if ot.startswith('C') else 'P' if ot.startswith('P') else None

            positions.append(_make_position(
                pos_id=f"RH_{pos.get('symbol', '')}_{pos.get('strike', '')}",
                symbol=pos.get('symbol', ''),
                asset_type='option' if asset_type == 'option' else 'stock',
                strike=pos.get('strike') or pos.get('strike_price'),
                expiry=pos.get('expiry') or pos.get('expiration_date'),
                call_put=call_put,
                quantity=qty,
                entry_price=avg_price,
                current_price=cur_price,
                last=cur_price,
                unrealized_pnl=unrealized,
                pnl_pct=pnl_pct,
                broker='ROBINHOOD',
                source='live_brokerage',
            ))
        return positions
    except Exception as e:
        _log(f"Robinhood fetch error: {e}")
        return []

# Schwab last-good-price cache (same pattern as IBKR)
_schwab_last_good_prices: Dict[str, float] = {}
_schwab_last_good_prices_lock = threading.Lock()

def _fetch_schwab(bot) -> List[Dict]:
    try:
        schwab_broker = None
        if hasattr(bot, 'schwab_broker') and bot.schwab_broker:
            schwab_broker = bot.schwab_broker
        elif hasattr(bot, 'broker_manager') and hasattr(bot.broker_manager, 'schwab_broker'):
            schwab_broker = bot.broker_manager.schwab_broker

        if not schwab_broker or not schwab_broker.is_authenticated():
            return []
        if not hasattr(bot, 'loop') or bot.loop is None or bot.loop.is_closed():
            return []

        raw = None
        try:
            from src.services.schwab_data_hub import get_schwab_data_hub
            hub = get_schwab_data_hub()
            cached = hub.get_positions(detailed=True)
            if cached is not None:
                raw = list(cached)
        except Exception:
            pass

        if raw is None:
            if hasattr(schwab_broker, '_last_valid_positions') and schwab_broker._last_valid_positions:
                raw = list(schwab_broker._last_valid_positions)

        if raw is None:
            try:
                future = asyncio.run_coroutine_threadsafe(
                    schwab_broker.get_positions_detailed(),
                    bot.loop
                )
                raw = future.result(timeout=8) or []
            except Exception:
                raw = []

        # Try streaming overlay from Schwab hub for real-time prices
        _schwab_hub = None
        try:
            from src.services.schwab_data_hub import get_schwab_data_hub
            _schwab_hub = get_schwab_data_hub()
        except Exception:
            pass

        positions = []
        for pos in raw:
            qty = float(pos.get('quantity', 0))
            avg_cost = float(pos.get('avg_cost', 0))
            cur_price = float(pos.get('current_price', 0))
            unrealized = float(pos.get('unrealized_pl', 0))
            asset = pos.get('asset', 'stock')
            pos_id = pos.get('position_id', f"SCH_{pos.get('symbol', '')}")
            symbol = pos.get('symbol', '')

            # Price waterfall: streaming quote → REST price → last-good cache
            if _schwab_hub and cur_price <= 0:
                try:
                    _sq = _schwab_hub.get_quote(symbol)
                    if _sq and getattr(_sq, 'last', 0) > 0:
                        cur_price = float(_sq.last)
                    elif _sq and getattr(_sq, 'bid', 0) > 0 and getattr(_sq, 'ask', 0) > 0:
                        cur_price = round((float(_sq.bid) + float(_sq.ask)) / 2, 4)
                except Exception:
                    pass

            # Last-good-price cache (same pattern as IBKR)
            with _schwab_last_good_prices_lock:
                if cur_price > 0:
                    _schwab_last_good_prices[pos_id] = cur_price
                elif pos_id in _schwab_last_good_prices:
                    cur_price = _schwab_last_good_prices[pos_id]

            if avg_cost > 0 and qty != 0:
                cost_basis = avg_cost * abs(qty)
                if asset == 'option':
                    cost_basis *= 100
                pnl_pct = (unrealized / cost_basis * 100) if cost_basis > 0 else 0.0
            else:
                pnl_pct = ((cur_price - avg_cost) / avg_cost * 100) if avg_cost > 0 else 0.0

            positions.append(_make_position(
                pos_id=pos_id,
                symbol=symbol,
                asset_type='option' if asset == 'option' else 'stock',
                strike=pos.get('strike'),
                expiry=pos.get('expiry'),
                call_put=pos.get('direction', ''),
                quantity=qty,
                entry_price=avg_cost,
                current_price=cur_price,
                last=cur_price,
                unrealized_pnl=unrealized,
                pnl_pct=pnl_pct,
                broker='SCHWAB',
                source='live_brokerage',
                raw_symbol=pos.get('raw_symbol', ''),
            ))
        return positions
    except Exception as e:
        _log(f"Schwab fetch error: {e}")
        return []


# Cache last known good prices to prevent $0 flicker when IB data is between refreshes.
# Keyed by position_id (conId). Thread-safe — only accessed from snapshot daemon thread
# or ThreadPoolExecutor workers under _broker_position_cache_lock.
_ibkr_last_good_prices: Dict[str, float] = {}
_ibkr_last_good_prices_lock = threading.Lock()

def _fetch_ibkr(bot) -> List[Dict]:
    """Fetch IBKR positions — hub-first architecture.
    
    Priority chain (eliminates the $0 flicker):
      1. IBKRDataHub cached positions + streaming quotes (zero API calls, sub-ms)
      2. Fallback: get_positions_detailed() via asyncio bridge (legacy path)
      3. Last-good-price cache (prevents any $0 from reaching the dashboard)
    """
    try:
        ibkr_broker = None
        if hasattr(bot, 'ibkr_broker') and bot.ibkr_broker:
            ibkr_broker = bot.ibkr_broker
        elif hasattr(bot, 'broker_manager') and hasattr(bot.broker_manager, 'ibkr_broker'):
            ibkr_broker = bot.broker_manager.ibkr_broker

        if not ibkr_broker:
            return []

        # ── Path 1: IBKRDataHub (streaming, zero API calls) ──────────────
        try:
            from src.services.ibkr_data_hub import get_ibkr_data_hub
            ibkr_hub = get_ibkr_data_hub()
            if ibkr_hub and ibkr_hub.is_streaming():
                hub_positions = ibkr_hub.get_positions(max_age_seconds=30)
                if hub_positions and len(hub_positions) > 0:
                    _IB_SENTINEL = 1.7976931348623157e+308
                    positions = []
                    for p in hub_positions:
                        symbol = p.get('symbol', '')
                        asset = p.get('asset', 'stock')
                        qty = float(p.get('quantity', 0))
                        if qty == 0:
                            continue
                        avg_cost = float(p.get('avg_cost', 0))
                        pos_id = str(p.get('position_id', f"IBKR_{symbol}"))
                        raw_sym = p.get('raw_symbol', '')

                        # Price waterfall: streaming quote → portfolio price → last-good cache
                        cur_price = 0.0

                        # 1) Streaming quote from reqMktData (freshest, sub-ms)
                        _lookup = raw_sym if asset == 'option' and raw_sym else symbol
                        _q = ibkr_hub.get_quote(_lookup)
                        if _q and _q.last and _q.last > 0 and _q.last < _IB_SENTINEL:
                            cur_price = float(_q.last)
                        elif _q and _q.bid and _q.ask and _q.bid > 0 and _q.ask > 0:
                            cur_price = round((float(_q.bid) + float(_q.ask)) / 2, 4)

                        # 2) Portfolio market price (from ib.portfolio event)
                        if cur_price <= 0:
                            mp = float(p.get('market_price', 0) or p.get('current_price', 0) or 0)
                            if 0 < mp < _IB_SENTINEL:
                                cur_price = mp

                        # 3) Allow-stale hub price (up to 300s old — better than $0)
                        if cur_price <= 0:
                            sp = ibkr_hub.get_quote_price(_lookup, allow_stale=True)
                            if sp and sp > 0 and sp < _IB_SENTINEL:
                                cur_price = sp

                        # 4) Last-good-price cache (absolute backstop against $0)
                        with _ibkr_last_good_prices_lock:
                            if cur_price > 0:
                                _ibkr_last_good_prices[pos_id] = cur_price
                            elif pos_id in _ibkr_last_good_prices:
                                cur_price = _ibkr_last_good_prices[pos_id]

                        # Compute P&L
                        unrealized = float(p.get('unrealized_pnl', 0) or 0)
                        if unrealized == 0 and cur_price > 0 and avg_cost > 0:
                            unrealized = (cur_price - avg_cost) * qty
                            if asset == 'option':
                                unrealized *= 100
                        pnl_pct = ((cur_price - avg_cost) / avg_cost * 100) if avg_cost > 0 and cur_price > 0 else 0.0

                        positions.append(_make_position(
                            pos_id=pos_id,
                            symbol=symbol,
                            asset_type='option' if asset == 'option' else 'stock',
                            strike=p.get('strike'),
                            expiry=p.get('expiry'),
                            call_put=p.get('direction', ''),
                            quantity=qty,
                            entry_price=avg_cost,
                            current_price=cur_price,
                            last=cur_price,
                            bid=float(_q.bid) if _q and _q.bid else 0,
                            ask=float(_q.ask) if _q and _q.ask else 0,
                            mid=round((float(_q.bid) + float(_q.ask)) / 2, 4) if _q and _q.bid and _q.ask and _q.bid > 0 and _q.ask > 0 else 0,
                            unrealized_pnl=unrealized,
                            pnl_pct=pnl_pct,
                            broker='IBKR',
                            source='live_brokerage',
                            raw_symbol=raw_sym,
                        ))
                    if positions:
                        return positions
        except Exception as hub_err:
            _log(f"IBKR hub path error (falling back to REST): {hub_err}")

        # ── Path 2: Legacy get_positions_detailed (fallback) ──────────────
        if not hasattr(ibkr_broker, 'get_positions_detailed'):
            return []
        if not hasattr(bot, 'loop') or bot.loop is None or bot.loop.is_closed():
            return []

        future = asyncio.run_coroutine_threadsafe(
            ibkr_broker.get_positions_detailed(),
            bot.loop
        )
        raw = future.result(timeout=10) or []

        positions = []
        for pos in raw:
            qty = float(pos.get('quantity', 0))
            avg_cost = float(pos.get('avg_cost', 0))
            cur_price = float(pos.get('current_price', 0))
            pos_id = pos.get('position_id', f"IBKR_{pos.get('symbol', '')}")

            # Last-good-price guard
            with _ibkr_last_good_prices_lock:
                if cur_price > 0:
                    _ibkr_last_good_prices[pos_id] = cur_price
                elif pos_id in _ibkr_last_good_prices:
                    cur_price = _ibkr_last_good_prices[pos_id]

            unrealized = float(pos.get('unrealized_pl', 0))
            if cur_price > 0 and avg_cost > 0 and unrealized == 0:
                unrealized = (cur_price - avg_cost) * qty
                if pos.get('asset') == 'option':
                    unrealized *= 100
            pnl_pct = ((cur_price - avg_cost) / avg_cost * 100) if avg_cost > 0 and cur_price > 0 else 0.0
            asset = pos.get('asset', 'stock')

            positions.append(_make_position(
                pos_id=pos_id,
                symbol=pos.get('symbol', ''),
                asset_type='option' if asset == 'option' else 'stock',
                strike=pos.get('strike'),
                expiry=pos.get('expiry'),
                call_put=pos.get('direction', ''),
                quantity=qty,
                entry_price=avg_cost,
                current_price=cur_price,
                last=cur_price,
                unrealized_pnl=unrealized,
                pnl_pct=pnl_pct,
                broker='IBKR',
                source='live_brokerage',
                raw_symbol=pos.get('raw_symbol', ''),
            ))
        return positions
    except Exception as e:
        _log(f"IBKR fetch error: {e}")
        return []


def _fetch_tastytrade(bot) -> List[Dict]:
    try:
        tt_broker = None
        if hasattr(bot, 'tastytrade_broker') and bot.tastytrade_broker:
            tt_broker = bot.tastytrade_broker
        elif hasattr(bot, 'broker_manager') and hasattr(bot.broker_manager, 'tastytrade_broker'):
            tt_broker = bot.broker_manager.tastytrade_broker

        if not tt_broker:
            return []

        if hasattr(tt_broker, 'get_positions_detailed'):
            if not hasattr(bot, 'loop') or bot.loop is None or bot.loop.is_closed():
                return []
            future = asyncio.run_coroutine_threadsafe(
                tt_broker.get_positions_detailed(),
                bot.loop
            )
            raw = future.result(timeout=10) or []
        elif hasattr(tt_broker, 'get_all_positions'):
            raw = tt_broker.get_all_positions() or []
        else:
            return []

        positions = []
        for pos in raw:
            if isinstance(pos, dict):
                qty = float(pos.get('quantity', 0))
                avg_cost = float(pos.get('avg_cost') or pos.get('avg_price') or 0)
                cur_price = float(pos.get('current_price', 0))
                unrealized = float(pos.get('unrealized_pl') or pos.get('unrealized_pnl') or 0)
                pnl_pct = ((cur_price - avg_cost) / avg_cost * 100) if avg_cost > 0 else 0.0
                asset = pos.get('asset', pos.get('asset_type', 'stock'))

                positions.append(_make_position(
                    pos_id=pos.get('position_id', f"TT_{pos.get('symbol', '')}"),
                    symbol=pos.get('symbol', ''),
                    asset_type='option' if asset == 'option' else 'stock',
                    strike=pos.get('strike'),
                    expiry=pos.get('expiry'),
                    call_put=pos.get('direction') or pos.get('call_put', ''),
                    quantity=qty,
                    entry_price=avg_cost,
                    current_price=cur_price,
                    last=cur_price,
                    unrealized_pnl=unrealized,
                    pnl_pct=pnl_pct,
                    broker='TASTYTRADE',
                    source='live_brokerage',
                ))
            else:
                symbol = getattr(pos, 'symbol', str(pos))
                qty = int(float(getattr(pos, 'quantity', 0)))
                positions.append(_make_position(
                    pos_id=f"TT_{symbol}",
                    symbol=symbol,
                    quantity=qty,
                    broker='TASTYTRADE',
                    source='live_brokerage',
                ))
        return positions
    except Exception as e:
        _log(f"Tastytrade fetch error: {e}")
        return []


_t212_hub_cache: List[Dict] = []
_t212_hub_cache_ts: float = 0
_t212_hub_cache_lock = threading.Lock()


def _fetch_trading212(bot) -> List[Dict]:
    global _t212_hub_cache, _t212_hub_cache_ts
    try:
        from src.services.trading212_data_hub import get_trading212_data_hub
        hub = get_trading212_data_hub()
        if not hub.is_stale:
            hub_positions = hub.get_positions(max_age_seconds=10)
            if hub_positions is not None and not hub.is_stale:
                positions = _convert_t212_raw(hub_positions)
                with _t212_hub_cache_lock:
                    _t212_hub_cache = positions
                    _t212_hub_cache_ts = time.time()
                return positions
    except Exception:
        pass

    try:
        t212_broker = None
        if hasattr(bot, 'trading212_broker') and bot.trading212_broker:
            t212_broker = bot.trading212_broker
        elif hasattr(bot, 'broker_manager') and hasattr(bot.broker_manager, 'trading212_broker'):
            t212_broker = bot.broker_manager.trading212_broker
        elif hasattr(bot, '_broker_manager') and hasattr(bot._broker_manager, 'trading212_broker'):
            t212_broker = bot._broker_manager.trading212_broker

        if not t212_broker:
            with _t212_hub_cache_lock:
                if _t212_hub_cache and (time.time() - _t212_hub_cache_ts) < 30:
                    return list(_t212_hub_cache)
            return []

        connected = getattr(t212_broker, 'connected', False)
        if not connected:
            with _t212_hub_cache_lock:
                if _t212_hub_cache and (time.time() - _t212_hub_cache_ts) < 30:
                    return list(_t212_hub_cache)
            return []

        if not hasattr(bot, 'loop') or bot.loop is None or bot.loop.is_closed():
            with _t212_hub_cache_lock:
                if _t212_hub_cache and (time.time() - _t212_hub_cache_ts) < 30:
                    return list(_t212_hub_cache)
            return []

        future = asyncio.run_coroutine_threadsafe(
            t212_broker.get_positions(),
            bot.loop
        )
        raw = future.result(timeout=10) or []

        positions = _convert_t212_raw(raw)
        with _t212_hub_cache_lock:
            _t212_hub_cache = positions
            _t212_hub_cache_ts = time.time()
        return positions
    except Exception as e:
        err_msg = str(e).strip() if str(e).strip() else type(e).__name__
        _log(f"T212 fetch error: {err_msg}")
        with _t212_hub_cache_lock:
            if _t212_hub_cache and (time.time() - _t212_hub_cache_ts) < 30:
                return list(_t212_hub_cache)
        return []


def _convert_t212_raw(raw: list) -> List[Dict]:
    positions = []
    for idx, pos in enumerate(raw):
        if isinstance(pos, dict):
            sym = str(pos.get('symbol', '') or '').strip()
            if not sym:
                ticker = str(pos.get('ticker', '') or '').strip()
                if ticker:
                    sym = ticker.split('_')[0] if '_' in ticker else ticker
            qty = float(pos.get('quantity', 0))
            avg_cost = float(pos.get('avg_cost', 0))
            cur_price = float(pos.get('current_price', 0))
            unrealized = float(pos.get('unrealized_pnl', 0))
            pnl_pct = ((cur_price - avg_cost) / avg_cost * 100) if avg_cost > 0 else 0.0
            pos_id = f"T212_{sym}" if sym else f"T212_pos{idx}"

            positions.append(_make_position(
                pos_id=pos_id,
                symbol=sym,
                asset_type='stock',
                strike=None,
                expiry=None,
                call_put='',
                quantity=qty,
                entry_price=avg_cost,
                current_price=cur_price,
                last=cur_price,
                unrealized_pnl=unrealized,
                pnl_pct=pnl_pct,
                broker='TRADING212',
                source='live_brokerage',
            ))
    return positions


_wo_cache: List[Dict] = []
_wo_cache_ts: float = 0.0
_wo_cache_lock = threading.Lock()

_wo_last_good_prices: Dict[str, float] = {}
_wo_last_good_prices_lock = threading.Lock()

def _fetch_webull_official(bot) -> List[Dict]:
    global _wo_cache, _wo_cache_ts
    try:
        wo_broker = getattr(bot, 'webull_official_broker', None)
        if not wo_broker:
            wo_broker = getattr(getattr(bot, 'broker_manager', None), 'webull_official_broker', None)

        if not wo_broker or not getattr(wo_broker, 'connected', False):
            with _wo_cache_lock:
                if _wo_cache and (time.time() - _wo_cache_ts) < 30:
                    return list(_wo_cache)
            return []

        if not hasattr(bot, 'loop') or bot.loop is None or bot.loop.is_closed():
            with _wo_cache_lock:
                if _wo_cache and (time.time() - _wo_cache_ts) < 30:
                    return list(_wo_cache)
            return []

        future = asyncio.run_coroutine_threadsafe(
            wo_broker.get_positions(max_age_seconds=10),
            bot.loop
        )
        raw = future.result(timeout=10) or []

        broker_label = 'WEBULL_OFFICIAL_LIVE' if not getattr(wo_broker, 'paper_trade', True) else 'WEBULL_OFFICIAL_PAPER'
        positions = []
        for idx, pos in enumerate(raw):
            sym = str(pos.get('symbol', '') or '').strip()
            if not sym:
                continue
            qty = float(pos.get('quantity', 0) or 0)
            if qty == 0:
                continue
            avg_cost = float(pos.get('avg_cost', 0) or 0)
            cur_price = float(pos.get('current_price', 0) or 0)

            # Streaming price overlay from WebullDataHub (zero API calls)
            if cur_price <= 0:
                try:
                    from src.services.webull_data_hub import get_webull_data_hub
                    _wb_hub = get_webull_data_hub()
                    _wq = _wb_hub.get_quote(sym)
                    if _wq and getattr(_wq, 'last', 0) > 0:
                        cur_price = float(_wq.last)
                except Exception:
                    pass

            unrealized = float(pos.get('unrealized_pl', 0) or 0)
            pnl_pct = ((cur_price - avg_cost) / avg_cost * 100) if avg_cost > 0 and cur_price > 0 else 0.0
            asset = pos.get('asset', 'stock')
            is_option = asset == 'option'
            ot = (pos.get('option_type') or '').upper()
            call_put = 'C' if 'CALL' in ot else ('P' if 'PUT' in ot else '')
            strike = float(pos.get('strike_price') or 0) or None
            expiry = pos.get('expiry_date')
            pos_id = f"WO_{sym}_{idx}" if not is_option else f"WO_{sym}_{strike}_{expiry}_{call_put}"

            # Last-good-price cache (prevents $0 flicker)
            with _wo_last_good_prices_lock:
                if cur_price > 0:
                    _wo_last_good_prices[pos_id] = cur_price
                elif pos_id in _wo_last_good_prices:
                    cur_price = _wo_last_good_prices[pos_id]

            raw_symbol = ''
            if is_option and sym and expiry and strike and call_put:
                try:
                    _exp = str(expiry).replace('-', '')[2:]  # '2025-06-20' -> '250620'
                    _strike_int = int(round(float(strike) * 1000))
                    raw_symbol = f"{sym.upper()}{_exp}{call_put}{_strike_int:08d}"
                except (ValueError, TypeError):
                    raw_symbol = ''

            positions.append(_make_position(
                pos_id=pos_id,
                symbol=sym,
                asset_type='option' if is_option else 'stock',
                strike=strike,
                expiry=expiry,
                call_put=call_put,
                quantity=qty,
                entry_price=avg_cost,
                current_price=cur_price,
                last=cur_price,
                unrealized_pnl=unrealized,
                pnl_pct=pnl_pct,
                broker=broker_label,
                source='live_brokerage',
                raw_symbol=raw_symbol,
            ))

        with _wo_cache_lock:
            _wo_cache = positions
            _wo_cache_ts = time.time()
        return positions
    except Exception as e:
        err_msg = str(e).strip() if str(e).strip() else type(e).__name__
        _log(f"Webull Official fetch error: {err_msg}")
        with _wo_cache_lock:
            if _wo_cache and (time.time() - _wo_cache_ts) < 30:
                return list(_wo_cache)
        return []


def _normalize_strike(val):
    if val is None or val == '':
        return ''
    try:
        return str(float(val))
    except (ValueError, TypeError):
        return str(val)

def _normalize_expiry(val):
    if not val:
        return ''
    val = str(val).strip()
    import re
    m = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})$', val)
    if m:
        return f"{int(m.group(2)):02d}/{int(m.group(3)):02d}"
    m = re.match(r'^(\d{1,2})/(\d{1,2})$', val)
    if m:
        return f"{int(m.group(1)):02d}/{int(m.group(2)):02d}"
    return val

_SYMBOL_CANONICAL = {
    'SPXW': 'SPX', 'NDXP': 'NDX',
}

def _canonical_symbol(sym):
    return _SYMBOL_CANONICAL.get(str(sym).upper(), str(sym).upper())

def _make_match_key(broker, symbol, strike, expiry, call_put):
    return f"{str(broker).upper()}|{_canonical_symbol(symbol)}|{_normalize_strike(strike)}|{_normalize_expiry(expiry)}|{(call_put or '').upper()[:1]}"


def _build_channel_risk_map() -> Dict[str, Dict]:
    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT discord_channel_id, name, stop_loss_pct,
                   profit_target_1_pct, profit_target_2_pct, profit_target_3_pct
            FROM channels WHERE is_active = 1
        ''')
        rows = cursor.fetchall()
        result = {}
        for row in rows:
            cid = str(row[0]) if row[0] else None
            if cid:
                result[cid] = {
                    'channel_name': row[1] or '',
                    'stop_loss_pct': row[2],
                    'profit_target_1_pct': row[3],
                    'profit_target_2_pct': row[4],
                    'profit_target_3_pct': row[5],
                }
        return result
    except Exception:
        return {}


def _apply_channel_fields(pos: Dict, channel_id, channel_risk_map: Dict, trade: Dict):
    if not channel_id:
        return
    cid = str(channel_id)
    info = channel_risk_map.get(cid, {})
    if info.get('channel_name'):
        pos['channel_name'] = info['channel_name']
    pos['stop_loss_pct'] = info.get('stop_loss_pct')
    pos['profit_target_1_pct'] = info.get('profit_target_1_pct')
    pos['profit_target_2_pct'] = info.get('profit_target_2_pct')
    pos['profit_target_3_pct'] = info.get('profit_target_3_pct')
    try:
        pos['source_display'] = db.get_trade_source_display(trade)
    except Exception:
        pos['source_display'] = {'name': pos.get('channel_name', ''), 'color': 'gray', 'icon': '📊', 'full_name': ''}
    remaining = pos.get('remaining_qty')
    original = pos.get('original_qty')
    if remaining is not None and original is not None and remaining < original and remaining > 0:
        pos['display_status'] = 'PARTIAL'
    else:
        pos['display_status'] = pos.get('status', 'OPEN')


def _enrich_with_db_trades(positions: List[Dict], db_trades: List[Dict], broker_status: Dict[str, Dict] = None) -> List[Dict]:
    from collections import defaultdict
    channel_risk_map = _build_channel_risk_map()
    trade_map: Dict[str, Dict] = {}
    trade_map_all: Dict[str, list] = defaultdict(list)
    for t in db_trades:
        key = _make_match_key(
            t.get('broker', ''), t.get('symbol', ''),
            t.get('strike'), t.get('expiry'), t.get('call_put')
        )
        trade_map[key] = t
        trade_map_all[key].append(t)
        _log(f"[ENRICH] DB trade #{t.get('id')} key: {key}")

    enriched = []
    seen_db_ids = set()

    for pos in positions:
        key = _make_match_key(
            pos.get('broker', ''), pos.get('symbol', ''),
            pos.get('strike'), pos.get('expiry'), pos.get('call_put')
        )
        _log(f"[ENRICH] Live pos {pos.get('symbol')} ({pos.get('broker')}) key: {key} → match={'YES' if key in trade_map else 'NO'}")

        matched_trade = trade_map.get(key)
        if not matched_trade and pos.get('asset_type') == 'option' and (not pos.get('strike') or pos.get('strike') == 0):
            pos_broker = str(pos.get('broker', '')).upper()
            pos_symbol = pos.get('symbol', '')
            for tkey, ttrade in trade_map.items():
                if (tkey.startswith(f"{pos_broker}|{pos_symbol}|") and
                    ttrade.get('asset_type') == 'option'):
                    matched_trade = ttrade
                    pos['strike'] = ttrade.get('strike')
                    pos['expiry'] = ttrade.get('expiry')
                    pos['call_put'] = ttrade.get('call_put')
                    _log(f"[ENRICH] ✓ Fuzzy matched {pos_symbol} option to trade #{ttrade.get('id')}")
                    key = _make_match_key(
                        pos.get('broker', ''), pos_symbol,
                        ttrade.get('strike'), ttrade.get('expiry'), ttrade.get('call_put')
                    )
                    break
        if matched_trade:
            all_matching = trade_map_all.get(key, [matched_trade])
            for t in all_matching:
                seen_db_ids.add(t.get('id'))
            def _trade_rank(t):
                src = (t.get('source') or '').lower()
                has_oid = bool(t.get('order_id'))
                if src == 'discord' and has_oid: return 0
                if src == 'sync_discord' and has_oid: return 1
                if src == 'discord': return 2
                if src == 'sync_discord': return 3
                return 4
            matched_trade = min(all_matching, key=_trade_rank)
            trade_id = matched_trade.get('id')
            pos['id'] = str(trade_id) if trade_id is not None else trade_id
            if pos.get('source') != 'live_brokerage':
                pos['source'] = 'database'
            pos['status'] = matched_trade.get('status', 'OPEN')
            pos['direction'] = matched_trade.get('direction', pos.get('direction', ''))
            pos['order_id'] = matched_trade.get('order_id')
            pos['fill_status'] = matched_trade.get('fill_status')

            if not pos.get('entry_price'):
                db_entry = matched_trade.get('entry_price') or matched_trade.get('executed_price') or matched_trade.get('intended_price')
                if db_entry:
                    pos['entry_price'] = float(db_entry)

            try:
                remaining = db.get_trade_remaining_qty(trade_id)
                if remaining:
                    pos['remaining_qty'] = remaining.get('remaining_qty')
                    pos['original_qty'] = remaining.get('original_qty')
            except Exception:
                pass

            pos['channel_record_id'] = matched_trade.get('channel_record_id')
            pos['channel_id'] = matched_trade.get('channel_id')
            pos['routing_mapping_id'] = matched_trade.get('routing_mapping_id')
            _apply_channel_fields(pos, pos['channel_id'], channel_risk_map, matched_trade)

        enriched.append(pos)

    DECOMMISSIONED_BROKERS = {'WEBULL_PAPER'}

    synced_brokers = set()
    if broker_status:
        for bname, bstat in broker_status.items():
            if bstat.get('error') is None:
                synced_brokers.add(bname.upper())

    for t in db_trades:
        tid = t.get('id')
        if tid not in seen_db_ids:
            trade_broker = str(t.get('broker', '')).upper()

            if trade_broker in DECOMMISSIONED_BROKERS:
                continue

            if trade_broker in synced_brokers:
                trade_status = str(t.get('status', '')).upper()
                is_pending = trade_status in ('PENDING', 'PARTIAL')

                is_recent = False
                age_seconds = 0
                try:
                    executed_at = t.get('executed_at', '')
                    if executed_at:
                        from datetime import datetime, timezone
                        if isinstance(executed_at, str):
                            for fmt in ('%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S'):
                                try:
                                    trade_time = datetime.strptime(executed_at, fmt)
                                    break
                                except ValueError:
                                    continue
                            else:
                                trade_time = None
                        else:
                            trade_time = executed_at
                        if trade_time:
                            age_seconds = (datetime.now() - trade_time).total_seconds()
                            is_recent = age_seconds < 300
                except Exception:
                    pass

                # Don't show PENDING orders that the broker has been syncing for > 10 minutes
                # with no matching live position — the sync service will close them shortly
                if is_pending and age_seconds > 600:
                    _log(f"[ENRICH] Hiding stale PENDING trade #{tid} ({t.get('symbol')}) — {age_seconds:.0f}s old, broker synced with no match")
                    continue

                if is_pending or is_recent:
                    _log(f"[ENRICH] Keeping DB trade #{tid} ({t.get('symbol')}) - {'pending' if is_pending else 'recent'} order on {trade_broker}")
                else:
                    _log(f"[ENRICH] Skipping stale DB trade #{tid} ({t.get('symbol')}) - broker {trade_broker} synced with no matching live position")
                    continue

            entry_price = float(t.get('entry_price') or t.get('executed_price') or t.get('intended_price') or 0)
            cur_price = float(t.get('current_price') or entry_price)
            pnl_pct = ((cur_price - entry_price) / entry_price * 100) if entry_price > 0 else 0.0
            unrealized = float(t.get('unrealized_pnl') or (cur_price - entry_price) * float(t.get('quantity') or 0))

            pos = _make_position(
                pos_id=str(tid) if tid is not None else tid,
                symbol=t.get('symbol', ''),
                asset_type=t.get('asset_type', 'stock'),
                strike=t.get('strike'),
                expiry=t.get('expiry'),
                call_put=t.get('call_put'),
                quantity=t.get('quantity', 0),
                entry_price=entry_price,
                current_price=cur_price,
                unrealized_pnl=unrealized,
                pnl_pct=pnl_pct,
                broker=trade_broker,
                source='database',
                status=t.get('status', 'OPEN'),
                direction=t.get('direction', ''),
                order_id=t.get('order_id'),
                fill_status=t.get('fill_status'),
            )
            pos['channel_record_id'] = t.get('channel_record_id')
            pos['channel_id'] = t.get('channel_id')
            pos['routing_mapping_id'] = t.get('routing_mapping_id')

            try:
                remaining = db.get_trade_remaining_qty(tid)
                if remaining:
                    pos['remaining_qty'] = remaining.get('remaining_qty')
                    pos['original_qty'] = remaining.get('original_qty')
            except Exception:
                pass

            _apply_channel_fields(pos, pos.get('channel_id'), channel_risk_map, t)
            enriched.append(pos)

    return enriched


def _apply_streaming_quote(pos, quote, streaming_meta):
    if not quote:
        return
    last = quote.get('last', 0)
    # Enterprise guard: NEVER overlay a zero/negative price — it would clobber a valid cached price
    if not last or last <= 0:
        return
    pos['current_price'] = quote['last']
    pos['last'] = quote['last']
    if quote.get('bid', 0) > 0:
        pos['bid'] = quote['bid']
    if quote.get('ask', 0) > 0:
        pos['ask'] = quote['ask']
    if pos.get('bid', 0) > 0 and pos.get('ask', 0) > 0:
        pos['mid'] = round((pos['bid'] + pos['ask']) / 2, 4)
    entry = pos.get('entry_price', 0)
    qty = pos.get('quantity', 0)
    if entry > 0:
        pnl_pct = ((quote['last'] - entry) / entry) * 100
        unrealized = (quote['last'] - entry) * qty
        if pos.get('asset_type') == 'option':
            unrealized *= 100
        pos['pnl_pct'] = round(pnl_pct, 2)
        pos['unrealized_pnl'] = round(unrealized, 2)
    pid = pos.get('id')
    if pid:
        streaming_meta['sources'][str(pid)] = {
            'source': 'stream',
            'age': round(time.time() - quote.get('timestamp', 0), 1)
        }


def _overlay_streaming_prices(positions: List[Dict]) -> Dict[str, Any]:
    streaming_meta = {'webull': False, 'schwab': False, 'ibkr': False, 'sources': {}}

    wb_hub = None
    wb_streaming = False
    sch_hub = None
    sch_streaming = False
    ibkr_hub = None
    ibkr_streaming = False

    try:
        from src.services.webull_data_hub import get_webull_data_hub
        wb_hub = get_webull_data_hub()
        wb_streaming = wb_hub.is_streaming()
        if wb_streaming:
            streaming_meta['webull'] = True
    except Exception:
        pass

    try:
        from src.services.schwab_data_hub import get_schwab_data_hub
        sch_hub = get_schwab_data_hub()
        sch_streaming = sch_hub.is_streaming()
        if sch_streaming:
            streaming_meta['schwab'] = True
    except Exception:
        pass

    try:
        from src.services.ibkr_data_hub import get_ibkr_data_hub
        ibkr_hub = get_ibkr_data_hub()
        ibkr_streaming = ibkr_hub.is_streaming()
        if ibkr_streaming:
            streaming_meta['ibkr'] = True
    except Exception:
        pass

    for pos in positions:
        broker = (pos.get('broker') or '').upper()
        symbol = pos.get('symbol', '')
        asset_type = pos.get('asset_type', 'stock')
        if not symbol:
            continue

        quote = None

        if 'WEBULL' in broker and wb_streaming:
            if asset_type == 'option':
                raw_sym = pos.get('raw_symbol', '')
                if raw_sym:
                    quote = wb_hub.get_quote_detailed(raw_sym)
            else:
                quote = wb_hub.get_quote_detailed(symbol)
        elif broker == 'SCHWAB' and sch_hub:
            if asset_type == 'option':
                # OCC symbol stored in raw_symbol; streaming key matches OCC format
                raw_sym = pos.get('raw_symbol', '')
                if raw_sym and sch_streaming:
                    quote = sch_hub.get_quote_detailed(raw_sym)
                # No streaming fallback for options — REST price is already best available
            else:
                if sch_streaming:
                    quote = sch_hub.get_quote_detailed(symbol)
                if not quote or quote.get('last', 0) <= 0:
                    # Fallback: read price from hub quotes even if streaming flag is stale
                    price = sch_hub.get_quote_price(symbol)
                    if price and price > 0:
                        quote = {'last': price, 'bid': 0, 'ask': 0}
        elif 'IBKR' in broker and ibkr_hub:
            # IBKR streaming overlay — IBKRDataHub caches reqMktData ticks
            if asset_type == 'option':
                raw_sym = pos.get('raw_symbol', '')
                if raw_sym and ibkr_streaming:
                    _q = ibkr_hub.get_quote(raw_sym)
                    if _q and _q.last and _q.last > 0:
                        quote = {'last': _q.last, 'bid': _q.bid or 0, 'ask': _q.ask or 0, 'timestamp': _q.timestamp}
                if not quote:
                    _q = ibkr_hub.get_quote(symbol)
                    if _q and _q.last and _q.last > 0:
                        quote = {'last': _q.last, 'bid': _q.bid or 0, 'ask': _q.ask or 0, 'timestamp': _q.timestamp}
            else:
                if ibkr_streaming:
                    _q = ibkr_hub.get_quote(symbol)
                    if _q and _q.last and _q.last > 0:
                        quote = {'last': _q.last, 'bid': _q.bid or 0, 'ask': _q.ask or 0, 'timestamp': _q.timestamp}
                if not quote or quote.get('last', 0) <= 0:
                    # Fallback: hub quote price even if streaming flag is stale
                    price = ibkr_hub.get_quote_price(symbol, allow_stale=True)
                    if price and price > 0:
                        quote = {'last': price, 'bid': 0, 'ask': 0}
        elif 'TRADING212' in broker:
            if wb_streaming:
                quote = wb_hub.get_quote_detailed(symbol)
            if (not quote or quote.get('last', 0) <= 0) and sch_streaming:
                quote = sch_hub.get_quote_detailed(symbol)

        _apply_streaming_quote(pos, quote, streaming_meta)

    return streaming_meta


# Global last-known-good prices — prevents $0 from ever reaching the API/frontend.
# Keyed by position id. Updated every snapshot cycle.
_last_good_prices_global: Dict[str, Dict[str, float]] = {}
_last_good_prices_global_lock = threading.Lock()

def _build_prices(positions: List[Dict]) -> Dict:
    """Build prices dict for API response with zero-price suppression.
    
    Enterprise rule: a position that had a real price NEVER drops to $0.
    If current cycle returns 0, use the last known good price.
    """
    prices = {}
    # SNAP-7: Single lock acquisition for entire loop — not per-position
    with _last_good_prices_global_lock:
        # Evict stale entries for positions no longer in the current set (SNAP-5)
        current_ids = {str(p.get('id')) for p in positions if p.get('id') is not None}
        stale_keys = [k for k in _last_good_prices_global if k not in current_ids]
        for k in stale_keys:
            del _last_good_prices_global[k]

        for pos in positions:
            pid = pos.get('id')
            if pid is None:
                continue
            pid_str = str(pid)
            bid = pos.get('bid', 0)
            ask = pos.get('ask', 0)
            mid = pos.get('mid', 0)
            last = pos.get('last', pos.get('current_price', 0))

            # Zero-price suppression: use last known good price
            prev = _last_good_prices_global.get(pid_str)
            if last and last > 0:
                _last_good_prices_global[pid_str] = {'bid': bid, 'ask': ask, 'mid': mid, 'last': last}
            elif prev and prev.get('last', 0) > 0:
                bid = prev.get('bid', bid)
                ask = prev.get('ask', ask)
                mid = prev.get('mid', mid)
                last = prev['last']
                pos['current_price'] = last
                pos['last'] = last
                pos['bid'] = bid
                pos['ask'] = ask
                pos['mid'] = mid
                entry = pos.get('entry_price', 0)
                qty = pos.get('quantity', 0)
                if entry and entry > 0:
                    pnl = (last - entry) * qty
                    if pos.get('asset_type') == 'option':
                        pnl *= 100
                    pos['unrealized_pnl'] = round(pnl, 2)
                    pos['pnl_pct'] = round(((last - entry) / entry) * 100, 2)

            prices[pid_str] = {
                'bid': bid,
                'ask': ask,
                'mid': mid,
                'last': last,
            }
    return prices


_broker_position_cache: Dict[str, List[Dict]] = {}
_broker_position_cache_lock = threading.Lock()


def _refresh_snapshot(bot_instance, force_all: bool = False):
    global _snapshot_version

    with _snapshot_lock:
        if _snapshot_cache.get('updating'):
            return
        _snapshot_cache['updating'] = True

    try:
        db_trades = []
        try:
            open_trades = db.get_trades(status='OPEN', limit=500)
            pending_trades = db.get_trades(status='PENDING', limit=100)
            partial_trades = db.get_trades(status='PARTIAL', limit=200)
            db_trades = open_trades + pending_trades + partial_trades
        except Exception as e:
            _log(f"DB trades fetch error: {e}")

        broker_fetchers = {
            'WEBULL': (_fetch_webull, bot_instance),
            'ALPACA_PAPER': (_fetch_alpaca, bot_instance),
            'ROBINHOOD': (_fetch_robinhood, bot_instance),
            'SCHWAB': (_fetch_schwab, bot_instance),
            'IBKR': (_fetch_ibkr, bot_instance),
            'TASTYTRADE': (_fetch_tastytrade, bot_instance),
            'TRADING212': (_fetch_trading212, bot_instance),
            'WEBULL_OFFICIAL': (_fetch_webull_official, bot_instance),
        }

        now = time.time()
        brokers_due = {}
        with _broker_last_fetch_lock:
            for broker_name, (fetcher, bot) in broker_fetchers.items():
                interval = _BROKER_INTERVALS.get(broker_name, 5)
                last = _broker_last_fetch.get(broker_name, 0)
                if force_all or (now - last) >= interval:
                    brokers_due[broker_name] = (fetcher, bot)

        all_live_positions: List[Dict] = []
        broker_status: Dict[str, Dict] = {}

        if brokers_due:
            with ThreadPoolExecutor(max_workers=7, thread_name_prefix='snapshot') as executor:
                future_map = {}
                for broker_name, (fetcher, bot) in brokers_due.items():
                    f = executor.submit(fetcher, bot)
                    future_map[f] = broker_name

                for f in as_completed(future_map, timeout=15):
                    broker_name = future_map[f]
                    try:
                        result = f.result(timeout=10)
                        # SNAP-10: Only update cache with empty result if broker had
                        # positions before. An empty list from a successful fetch is valid
                        # (no positions held). But fetchers return [] on exceptions too,
                        # so we check: if we HAD positions and now get [], keep old cache
                        # and mark as degraded — prevents positions vanishing on transient errors.
                        with _broker_position_cache_lock:
                            prev = _broker_position_cache.get(broker_name, [])
                            if result or not prev:
                                _broker_position_cache[broker_name] = result
                            # else: keep previous good data — fetcher returned [] but we had positions
                        with _broker_last_fetch_lock:
                            _broker_last_fetch[broker_name] = time.time()
                        final_count = len(_broker_position_cache.get(broker_name, []))
                        broker_status[broker_name] = {
                            'connected': True,
                            'last_updated': time.time(),
                            'error': None if result else 'fetch returned empty (using cached)',
                            'position_count': final_count,
                        }
                    except Exception as e:
                        # SNAP-10: Do NOT overwrite cache on error — keep previous positions
                        broker_status[broker_name] = {
                            'connected': False,
                            'last_updated': time.time(),
                            'error': str(e),
                            'position_count': len(_broker_position_cache.get(broker_name, [])),
                        }
                        _log(f"{broker_name} future error: {e}")

        with _broker_position_cache_lock:
            for broker_name in broker_fetchers:
                if broker_name in _broker_position_cache:
                    all_live_positions.extend(_broker_position_cache[broker_name])
                if broker_name not in broker_status and broker_name in _broker_position_cache:
                    cached = _broker_position_cache[broker_name]
                    broker_status[broker_name] = {
                        'connected': True,
                        'last_updated': _broker_last_fetch.get(broker_name, 0),
                        'error': None,
                        'position_count': len(cached),
                    }

        merged = _enrich_with_db_trades(all_live_positions, db_trades, broker_status)

        merged = [dict(pos) for pos in merged]
        streaming_meta = _overlay_streaming_prices(merged)

        prices = _build_prices(merged)

        risk_states = {}
        try:
            from src.risk.position_cache import get_position_cache
            cache = get_position_cache()
            if cache:
                risk_states = cache.get_all_risk_states()
        except Exception as e:
            _log(f"Risk states fetch error: {e}")

        with _snapshot_lock:
            _snapshot_cache['positions'] = merged
            _snapshot_cache['prices'] = prices
            _snapshot_cache['risk_states'] = risk_states
            _snapshot_cache['broker_status'] = broker_status
            _snapshot_cache['streaming'] = streaming_meta
            _snapshot_cache['last_updated'] = time.time()
            _snapshot_cache['updating'] = False

        with _snapshot_version_lock:
            global _prev_position_ids
            _snapshot_version += 1
            ver = _snapshot_version
            def _pos_fingerprint(p):
                return (str(p.get('id')), str(p.get('status', '')), str(p.get('remaining_qty', '')))
            new_fingerprints = {_pos_fingerprint(p) for p in merged if p.get('id') is not None}
            event_type = 'structure_changed' if new_fingerprints != _prev_position_ids else 'tick'
            _prev_position_ids = new_fingerprints

        _notify_sse_clients({'type': event_type, 'version': ver})

        broker_summary = ', '.join(
            f"{k}({v.get('position_count', 0)})" for k, v in broker_status.items()
        )
        _log(f"Refreshed: {len(merged)} positions, {len(risk_states)} risk states, brokers: {broker_summary}")

    except Exception as e:
        _log(f"Refresh error: {e}")
        traceback.print_exc()
        with _snapshot_lock:
            _snapshot_cache['updating'] = False


def _daemon_loop(bot_instance, interval: int):
    _log(f"Daemon started (interval={interval}s, per-broker scheduling)")
    _refresh_snapshot(bot_instance, force_all=True)

    while not _daemon_stop_event.is_set():
        try:
            forced = _force_refresh_event.is_set()
            if forced:
                _force_refresh_event.clear()
                _refresh_snapshot(bot_instance, force_all=True)
            else:
                _refresh_snapshot(bot_instance)
        except Exception as e:
            _log(f"Daemon loop error: {e}")
            traceback.print_exc()

        _daemon_stop_event.wait(timeout=interval)

    _log("Daemon stopped")


def start_snapshot_daemon(bot_instance, interval: int = 2):
    global _daemon_thread, _daemon_started

    if _daemon_started and _daemon_thread and _daemon_thread.is_alive():
        _log("Daemon already running - skipping start")
        return

    _daemon_stop_event.clear()
    _daemon_thread = threading.Thread(
        target=_daemon_loop,
        args=(bot_instance, interval),
        name='SnapshotDaemon',
        daemon=True,
    )
    _daemon_thread.start()
    _daemon_started = True
    _log(f"Daemon thread started (interval={interval}s)")


def stop_snapshot_daemon():
    global _daemon_started

    _daemon_stop_event.set()
    _daemon_started = False

    if _daemon_thread and _daemon_thread.is_alive():
        _daemon_thread.join(timeout=5)
        _log("Daemon thread joined")
    else:
        _log("Daemon thread was not running")


def get_live_snapshot() -> Dict[str, Any]:
    with _snapshot_lock:
        return copy.deepcopy(_snapshot_cache)


def get_snapshot_age() -> float:
    with _snapshot_lock:
        last = _snapshot_cache.get('last_updated', 0)
    if last == 0:
        return float('inf')
    return time.time() - last
