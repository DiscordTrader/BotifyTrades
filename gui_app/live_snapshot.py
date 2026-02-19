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


def _log(msg: str):
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
    }


def _fetch_webull(bot) -> List[Dict]:
    try:
        if not hasattr(bot, 'broker') or bot.broker is None:
            return []

        broker = bot.broker
        webull_broker = None
        if hasattr(broker, 'brokers'):
            webull_broker = broker.brokers.get('Webull')
        elif hasattr(broker, 'wb'):
            webull_broker = broker

        if not webull_broker or not hasattr(webull_broker, 'wb'):
            return []

        positions_raw = webull_broker.wb.get_positions() or []

        positions = []
        for pos in positions_raw:
            position_qty = float(pos.get('position', 0))
            if position_qty <= 0:
                continue

            symbol = pos.get('ticker', {}).get('symbol', '') or pos.get('symbol', '')
            asset_type = pos.get('assetType', 'unknown')
            is_option = (
                'optionId' in pos or
                'strikePrice' in pos or
                asset_type.lower() in ('option', 'opt')
            )

            strike = None
            expiry = None
            call_put = None
            if is_option:
                strike = float(pos.get('strikePrice', 0))
                direction = pos.get('direction', '').upper()
                call_put = 'C' if direction == 'CALL' else ('P' if direction == 'PUT' else '')
                raw_expiry = pos.get('expireDate', '')
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


def _fetch_robinhood(bot) -> List[Dict]:
    try:
        if not hasattr(bot, 'robinhood_broker') or bot.robinhood_broker is None:
            return []

        rh_broker = bot.robinhood_broker
        raw = rh_broker.get_all_positions()
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

        future = asyncio.run_coroutine_threadsafe(
            schwab_broker.get_positions_detailed(),
            bot.loop
        )
        raw = future.result(timeout=10) or []

        positions = []
        for pos in raw:
            qty = float(pos.get('quantity', 0))
            avg_cost = float(pos.get('avg_cost', 0))
            cur_price = float(pos.get('current_price', 0))
            unrealized = float(pos.get('unrealized_pl', 0))
            pnl_pct = ((cur_price - avg_cost) / avg_cost * 100) if avg_cost > 0 else 0.0
            asset = pos.get('asset', 'stock')

            positions.append(_make_position(
                pos_id=pos.get('position_id', f"SCH_{pos.get('symbol', '')}"),
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
                broker='SCHWAB',
                source='live_brokerage',
            ))
        return positions
    except Exception as e:
        _log(f"Schwab fetch error: {e}")
        return []


def _fetch_ibkr(bot) -> List[Dict]:
    try:
        ibkr_broker = None
        if hasattr(bot, 'ibkr_broker') and bot.ibkr_broker:
            ibkr_broker = bot.ibkr_broker
        elif hasattr(bot, 'broker_manager') and hasattr(bot.broker_manager, 'ibkr_broker'):
            ibkr_broker = bot.broker_manager.ibkr_broker

        if not ibkr_broker or not hasattr(ibkr_broker, 'get_positions_detailed'):
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
            unrealized = float(pos.get('unrealized_pl', 0))
            pnl_pct = ((cur_price - avg_cost) / avg_cost * 100) if avg_cost > 0 else 0.0
            asset = pos.get('asset', 'stock')

            positions.append(_make_position(
                pos_id=pos.get('position_id', f"IBKR_{pos.get('symbol', '')}"),
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


def _enrich_with_db_trades(positions: List[Dict], db_trades: List[Dict]) -> List[Dict]:
    trade_map: Dict[str, Dict] = {}
    for t in db_trades:
        symbol = t.get('symbol', '')
        broker = str(t.get('broker', '')).upper()
        strike = t.get('strike')
        expiry = t.get('expiry')
        call_put = t.get('call_put')
        key = f"{broker}|{symbol}|{strike}|{expiry}|{call_put}"
        trade_map[key] = t

    enriched = []
    seen_db_ids = set()

    for pos in positions:
        symbol = pos.get('symbol', '')
        broker = pos.get('broker', '').upper()
        strike = pos.get('strike')
        expiry = pos.get('expiry')
        call_put = pos.get('call_put')
        key = f"{broker}|{symbol}|{strike}|{expiry}|{call_put}"

        matched_trade = trade_map.get(key)
        if matched_trade:
            trade_id = matched_trade.get('id')
            seen_db_ids.add(trade_id)
            pos['id'] = trade_id
            pos['source'] = 'database'
            pos['status'] = matched_trade.get('status', 'OPEN')
            pos['direction'] = matched_trade.get('direction', pos.get('direction', ''))
            pos['order_id'] = matched_trade.get('order_id')
            pos['fill_status'] = matched_trade.get('fill_status')

            if not pos.get('entry_price') and matched_trade.get('entry_price'):
                pos['entry_price'] = float(matched_trade['entry_price'])

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

        enriched.append(pos)

    for t in db_trades:
        tid = t.get('id')
        if tid not in seen_db_ids:
            entry_price = float(t.get('entry_price') or 0)
            cur_price = float(t.get('current_price') or entry_price)
            pnl_pct = ((cur_price - entry_price) / entry_price * 100) if entry_price > 0 else 0.0
            unrealized = float(t.get('unrealized_pnl') or (cur_price - entry_price) * float(t.get('quantity') or 0))

            pos = _make_position(
                pos_id=tid,
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
                broker=str(t.get('broker', '')).upper(),
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

            enriched.append(pos)

    return enriched


def _build_prices(positions: List[Dict]) -> Dict:
    prices = {}
    for pos in positions:
        pid = pos.get('id')
        if pid is not None:
            prices[pid] = {
                'bid': pos.get('bid', 0),
                'ask': pos.get('ask', 0),
                'mid': pos.get('mid', 0),
                'last': pos.get('last', pos.get('current_price', 0)),
            }
    return prices


def _refresh_snapshot(bot_instance):
    global _snapshot_cache

    with _snapshot_lock:
        if _snapshot_cache.get('updating'):
            _log("Skipping refresh - already updating")
            return
        _snapshot_cache['updating'] = True

    try:
        db_trades = []
        try:
            open_trades = db.get_trades(status='OPEN', limit=500)
            pending_trades = db.get_trades(status='PENDING', limit=100)
            db_trades = open_trades + pending_trades
        except Exception as e:
            _log(f"DB trades fetch error: {e}")

        broker_fetchers = {
            'WEBULL': (_fetch_webull, bot_instance),
            'ALPACA_PAPER': (_fetch_alpaca, bot_instance),
            'ROBINHOOD': (_fetch_robinhood, bot_instance),
            'SCHWAB': (_fetch_schwab, bot_instance),
            'IBKR': (_fetch_ibkr, bot_instance),
            'TASTYTRADE': (_fetch_tastytrade, bot_instance),
        }

        all_live_positions: List[Dict] = []
        broker_status: Dict[str, Dict] = {}

        with ThreadPoolExecutor(max_workers=6, thread_name_prefix='snapshot') as executor:
            future_map = {}
            for broker_name, (fetcher, bot) in broker_fetchers.items():
                f = executor.submit(fetcher, bot)
                future_map[f] = broker_name

            for f in as_completed(future_map, timeout=15):
                broker_name = future_map[f]
                try:
                    result = f.result(timeout=10)
                    all_live_positions.extend(result)
                    broker_status[broker_name] = {
                        'connected': len(result) > 0 or True,
                        'last_updated': time.time(),
                        'error': None,
                        'position_count': len(result),
                    }
                except Exception as e:
                    broker_status[broker_name] = {
                        'connected': False,
                        'last_updated': time.time(),
                        'error': str(e),
                        'position_count': 0,
                    }
                    _log(f"{broker_name} future error: {e}")

        merged = _enrich_with_db_trades(all_live_positions, db_trades)

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
            _snapshot_cache['last_updated'] = time.time()
            _snapshot_cache['updating'] = False

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
    _log(f"Daemon started (interval={interval}s)")
    while not _daemon_stop_event.is_set():
        try:
            _refresh_snapshot(bot_instance)
        except Exception as e:
            _log(f"Daemon loop error: {e}")
            traceback.print_exc()

        _daemon_stop_event.wait(timeout=interval)

    _log("Daemon stopped")


def start_snapshot_daemon(bot_instance, interval: int = 5):
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
