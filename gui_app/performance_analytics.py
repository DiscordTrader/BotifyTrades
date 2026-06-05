import json
import math
import statistics
from datetime import datetime, timedelta, timezone
from collections import defaultdict

from gui_app.database import get_connection

EST = timezone(timedelta(hours=-5))
EDT = timezone(timedelta(hours=-4))


def _utc_to_est(dt_str):
    if not dt_str:
        return dt_str
    try:
        raw = str(dt_str)
        if 'T' in raw:
            raw = raw.replace('T', ' ')
        if '.' in raw:
            raw = raw[:raw.index('.')]
        dt = datetime.strptime(raw[:19], '%Y-%m-%d %H:%M:%S')
        dt_utc = dt.replace(tzinfo=timezone.utc)
        mar_start = _dst_start(dt_utc.year)
        nov_end = _dst_end(dt_utc.year)
        if mar_start <= dt_utc < nov_end:
            dt_local = dt_utc.astimezone(EDT)
        else:
            dt_local = dt_utc.astimezone(EST)
        return dt_local.strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, TypeError):
        return dt_str


def _dst_start(year):
    mar1 = datetime(year, 3, 1, tzinfo=timezone.utc)
    first_sun = 1 + (6 - mar1.weekday()) % 7
    second_sun = first_sun + 7
    return datetime(year, 3, second_sun, 7, 0, tzinfo=timezone.utc)


def _dst_end(year):
    nov1 = datetime(year, 11, 1, tzinfo=timezone.utc)
    first_sun = 1 + (6 - nov1.weekday()) % 7
    return datetime(year, 11, first_sun, 6, 0, tzinfo=timezone.utc)


def _resolve_broker(trade_broker, channel_id, conn):
    if trade_broker:
        return trade_broker
    if not channel_id:
        return ''
    row = conn.execute(
        "SELECT enabled_brokers FROM channels WHERE id = ?",
        [channel_id]
    ).fetchone()
    if row and row['enabled_brokers']:
        try:
            brokers = json.loads(row['enabled_brokers'])
            if isinstance(brokers, list) and brokers:
                return brokers[0]
        except (json.JSONDecodeError, TypeError):
            pass
    return ''


def _build_broker_filter(broker):
    return """
        (
            lc.lot_id IN (
                SELECT sl_bf.id FROM signal_lots sl_bf
                JOIN trades t_bf ON t_bf.id = sl_bf.trade_id
                WHERE UPPER(COALESCE(t_bf.broker, '')) = UPPER(?)
            )
            OR (
                lc.lot_id IN (
                    SELECT sl_bf2.id FROM signal_lots sl_bf2
                    LEFT JOIN trades t_bf2 ON t_bf2.id = sl_bf2.trade_id
                    LEFT JOIN channels c_bf ON CAST(c_bf.id AS TEXT) = sl_bf2.channel_id
                    LEFT JOIN channels c_bf2 ON c_bf2.discord_channel_id = CAST(sl_bf2.channel_id AS TEXT)
                    WHERE t_bf2.id IS NULL
                      AND (
                          UPPER(COALESCE(c_bf.enabled_brokers, c_bf2.enabled_brokers, '')) LIKE '%"' || UPPER(?) || '"%'
                      )
                )
            )
        )
    """


def _broker_filter_params(broker):
    return [broker, broker]


def _resolve_broker_from_row(row):
    b = row.get('broker') if isinstance(row, dict) else (row['broker'] if row else None)
    if b:
        return b.upper()
    eb = row.get('ch_enabled_brokers') if isinstance(row, dict) else None
    if eb:
        try:
            brokers = json.loads(eb)
            if isinstance(brokers, list) and brokers:
                return brokers[0].upper()
        except (json.JSONDecodeError, TypeError):
            pass
    return ''


def _resolve_date_range(period=None, start_date=None, end_date=None):
    if start_date and end_date:
        if len(start_date) == 10:
            start_date = start_date + ' 00:00:00'
        if len(end_date) == 10:
            end_date = end_date + ' 23:59:59'
        return start_date, end_date

    now = datetime.now()
    ed = now.strftime('%Y-%m-%d 23:59:59')

    if period == 'today':
        sd = now.strftime('%Y-%m-%d 00:00:00')
    elif period == '7d':
        sd = (now - timedelta(days=7)).strftime('%Y-%m-%d 00:00:00')
    elif period == '30d':
        sd = (now - timedelta(days=30)).strftime('%Y-%m-%d 00:00:00')
    elif period == '90d':
        sd = (now - timedelta(days=90)).strftime('%Y-%m-%d 00:00:00')
    elif period == 'year':
        sd = (now - timedelta(days=365)).strftime('%Y-%m-%d 00:00:00')
    elif period == 'all' or period is None:
        return None, None
    else:
        return None, None

    return sd, ed


def _build_date_filter(col, start_date, end_date, params):
    clauses = []
    if start_date:
        clauses.append(f"{col} >= ?")
        params.append(start_date)
    if end_date:
        clauses.append(f"{col} <= ?")
        params.append(end_date)
    return clauses


def _safe_round(val, digits=2):
    if val is None:
        return 0.0
    try:
        return round(float(val), digits)
    except (TypeError, ValueError):
        return 0.0


def get_performance_v2(user_id, start_date=None, end_date=None, broker=None, period=None):
    sd, ed = _resolve_date_range(period, start_date, end_date)
    conn = get_connection()

    params_closed = []
    where_closed = ["(lc.user_id IS NULL OR lc.user_id = ?)"]
    params_closed.append(user_id)
    where_closed += _build_date_filter("lc.closed_at", sd, ed, params_closed)

    if broker:
        where_closed.append(_build_broker_filter(broker))
        params_closed.extend(_broker_filter_params(broker))

    closed_sql = f"""
        SELECT lc.pnl, lc.pnl_percent, lc.holding_days, lc.closed_at,
               sl.symbol, lc.lot_id, lc.closed_qty,
               sl.asset_type, sl.call_put
        FROM lot_closures lc
        LEFT JOIN signal_lots sl ON sl.id = lc.lot_id
        WHERE {' AND '.join(where_closed)}
          AND lc.pnl IS NOT NULL
        ORDER BY lc.closed_at ASC
    """
    rows = conn.execute(closed_sql, params_closed).fetchall()

    trade_agg = {}
    daily_pnl = defaultdict(float)
    for r in rows:
        pnl = float(r['pnl'] or 0)
        pnl_pct = float(r['pnl_percent'] or 0)
        hd = float(r['holding_days'] or 0)
        sym = r['symbol'] or ''
        qty = int(r['closed_qty'] or 1)
        closed_at = _utc_to_est(r['closed_at']) or ''
        lot_id = r['lot_id'] or id(r)

        asset_type = r['asset_type'] or 'stock'
        call_put = r['call_put'] or ''
        if asset_type == 'option' and call_put == 'C':
            direction = 'calls'
        elif asset_type == 'option' and call_put == 'P':
            direction = 'puts'
        else:
            direction = 'stocks'

        if lot_id not in trade_agg:
            trade_agg[lot_id] = {'pnl': 0.0, 'pnl_pct_weighted': 0.0,
                                 'qty_sum': 0, 'hold_days': 0.0,
                                 'symbol': sym, 'last_closed': closed_at,
                                 'direction': direction}

        t = trade_agg[lot_id]
        t['pnl'] += pnl
        t['pnl_pct_weighted'] += pnl_pct * qty
        t['qty_sum'] += qty
        if hd > t['hold_days']:
            t['hold_days'] = hd
        if closed_at and closed_at > t['last_closed']:
            t['last_closed'] = closed_at

        if closed_at:
            day_key = closed_at[:10]
            daily_pnl[day_key] += pnl

    wins = 0
    losses = 0
    breakeven = 0
    gross_profit = 0.0
    gross_loss = 0.0
    pnl_list = []
    pnl_pct_list = []
    hold_days_list = []
    best_trade = 0.0
    worst_trade = 0.0
    best_trade_symbol = ''
    worst_trade_symbol = ''

    for t in trade_agg.values():
        pnl = t['pnl']
        avg_pnl_pct_t = (t['pnl_pct_weighted'] / t['qty_sum']) if t['qty_sum'] > 0 else 0.0
        pnl_list.append(pnl)
        pnl_pct_list.append(avg_pnl_pct_t)
        hold_days_list.append(t['hold_days'])

        if pnl > 0:
            wins += 1
            gross_profit += pnl
        elif pnl < 0:
            losses += 1
            gross_loss += abs(pnl)
        else:
            breakeven += 1

        if pnl > best_trade:
            best_trade = pnl
            best_trade_symbol = t['symbol']
        if pnl < worst_trade:
            worst_trade = pnl
            worst_trade_symbol = t['symbol']

    total_closed = len(trade_agg)

    total_pnl = _safe_round(sum(pnl_list))
    win_rate = _safe_round((wins / total_closed * 100) if total_closed > 0 else 0)
    loss_rate = _safe_round(((losses / total_closed) * 100) if total_closed > 0 else 0)
    avg_pnl = _safe_round(total_pnl / total_closed) if total_closed > 0 else 0.0
    avg_pnl_pct = _safe_round(sum(pnl_pct_list) / len(pnl_pct_list)) if pnl_pct_list else 0.0

    win_pnls = [p for p in pnl_list if p > 0]
    loss_pnls = [p for p in pnl_list if p < 0]
    avg_win = _safe_round(sum(win_pnls) / len(win_pnls)) if win_pnls else 0.0
    avg_loss = _safe_round(sum(loss_pnls) / len(loss_pnls)) if loss_pnls else 0.0

    if gross_loss > 0:
        profit_factor = _safe_round(min(gross_profit / gross_loss, 10.0))
    else:
        profit_factor = _safe_round(min(gross_profit, 10.0)) if gross_profit > 0 else 0.0

    wr_frac = wins / total_closed if total_closed > 0 else 0
    lr_frac = losses / total_closed if total_closed > 0 else 0
    expectancy = _safe_round(avg_win * wr_frac - abs(avg_loss) * lr_frac)

    avg_hold_days = _safe_round(sum(hold_days_list) / len(hold_days_list), 4) if hold_days_list else 0.0
    median_pnl = _safe_round(statistics.median(pnl_list)) if pnl_list else 0.0

    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnl_list:
        cumulative += p
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd

    max_drawdown = _safe_round(max_dd)
    max_drawdown_pct = _safe_round((max_dd / peak * 100) if peak > 0 else 0)

    current_streak = 0
    longest_win_streak = 0
    longest_loss_streak = 0
    streak = 0
    for p in pnl_list:
        if p > 0:
            if streak > 0:
                streak += 1
            else:
                streak = 1
            longest_win_streak = max(longest_win_streak, streak)
        elif p < 0:
            if streak < 0:
                streak -= 1
            else:
                streak = -1
            longest_loss_streak = max(longest_loss_streak, abs(streak))
        else:
            streak = 0
    current_streak = streak

    sharpe_ratio = 0.0
    if len(daily_pnl) >= 5:
        daily_returns = list(daily_pnl.values())
        mean_ret = sum(daily_returns) / len(daily_returns)
        if len(daily_returns) > 1:
            std_ret = statistics.stdev(daily_returns)
            if std_ret > 0:
                sharpe_ratio = _safe_round((mean_ret / std_ret) * math.sqrt(252))

    risk_reward_ratio = _safe_round(avg_win / abs(avg_loss)) if avg_loss != 0 else 0.0

    params_open = [user_id]
    where_open = ["(t.user_id IS NULL OR t.user_id = ?)", "UPPER(t.status) = 'OPEN'"]
    if broker:
        where_open.append("UPPER(COALESCE(t.broker, '')) = UPPER(?)")
        params_open.append(broker)
    open_sql = f"""
        SELECT COUNT(*) as cnt, COALESCE(SUM(t.pnl), 0) as unrealized
        FROM trades t
        WHERE {' AND '.join(where_open)}
    """
    open_row = conn.execute(open_sql, params_open).fetchone()
    total_open = int(open_row['cnt'] or 0)
    unrealized_pnl = _safe_round(open_row['unrealized'])

    total_trades = total_closed + total_open

    # Direction breakdown (Stocks / Calls / Puts)
    direction_breakdown = {}
    for t in trade_agg.values():
        d = t.get('direction', 'stocks')
        if d not in direction_breakdown:
            direction_breakdown[d] = {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0}
        direction_breakdown[d]['trades'] += 1
        direction_breakdown[d]['pnl'] += t['pnl']
        if t['pnl'] > 0:
            direction_breakdown[d]['wins'] += 1
        else:
            direction_breakdown[d]['losses'] += 1
    for d in direction_breakdown.values():
        d['win_rate'] = _safe_round((d['wins'] / d['trades'] * 100) if d['trades'] > 0 else 0, 1)
        d['pnl'] = _safe_round(d['pnl'])

    return {
        'total_trades': total_trades,
        'total_closed': total_closed,
        'total_open': total_open,
        'wins': wins,
        'losses': losses,
        'breakeven': breakeven,
        'win_rate': win_rate,
        'total_pnl': total_pnl,
        'unrealized_pnl': unrealized_pnl,
        'gross_profit': _safe_round(gross_profit),
        'gross_loss': _safe_round(gross_loss),
        'avg_pnl': avg_pnl,
        'avg_pnl_pct': avg_pnl_pct,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'best_trade': _safe_round(best_trade),
        'worst_trade': _safe_round(worst_trade),
        'best_trade_symbol': best_trade_symbol,
        'worst_trade_symbol': worst_trade_symbol,
        'profit_factor': profit_factor,
        'expectancy': expectancy,
        'avg_hold_days': avg_hold_days,
        'median_pnl': median_pnl,
        'max_drawdown': max_drawdown,
        'max_drawdown_pct': max_drawdown_pct,
        'current_streak': current_streak,
        'longest_win_streak': longest_win_streak,
        'longest_loss_streak': longest_loss_streak,
        'sharpe_ratio': sharpe_ratio,
        'risk_reward_ratio': risk_reward_ratio,
        'total_fees': 0.0,
        'direction_breakdown': direction_breakdown,
    }


def _resolve_broker_chain(trade_broker, enabled_brokers_json):
    if trade_broker:
        return trade_broker.upper()
    if enabled_brokers_json:
        try:
            brokers = json.loads(enabled_brokers_json)
            if isinstance(brokers, list) and brokers:
                return brokers[0].upper()
        except (json.JSONDecodeError, TypeError):
            pass
    return 'Unknown'


def get_broker_breakdown(user_id, start_date=None, end_date=None, period=None):
    sd, ed = _resolve_date_range(period, start_date, end_date)
    conn = get_connection()

    params = [user_id]
    where = ["(lc.user_id IS NULL OR lc.user_id = ?)"]
    where += _build_date_filter("lc.closed_at", sd, ed, params)

    sql = f"""
        SELECT t.broker, lc.pnl, lc.lot_id,
               COALESCE(c.enabled_brokers, c2.enabled_brokers) as ch_enabled_brokers
        FROM lot_closures lc
        LEFT JOIN signal_lots sl ON sl.id = lc.lot_id
        LEFT JOIN trades t ON t.id = sl.trade_id
        LEFT JOIN channels c ON CAST(c.id AS TEXT) = sl.channel_id
        LEFT JOIN channels c2 ON c2.discord_channel_id = CAST(sl.channel_id AS TEXT)
        WHERE {' AND '.join(where)}
          AND (lc.pnl IS NOT NULL AND lc.pnl != 0)
        ORDER BY t.broker
    """
    rows = conn.execute(sql, params).fetchall()

    lot_agg = {}
    for r in rows:
        b = _resolve_broker_chain(r['broker'], r['ch_enabled_brokers'])
        lot_id = r['lot_id'] or id(r)
        key = (b, lot_id)
        if key not in lot_agg:
            lot_agg[key] = {'broker': b, 'pnl': 0.0}
        lot_agg[key]['pnl'] += float(r['pnl'] or 0)

    brokers = defaultdict(lambda: {
        'trades': 0, 'wins': 0, 'losses': 0,
        'total_pnl': 0.0, 'gross_profit': 0.0, 'gross_loss': 0.0,
        'best': 0.0, 'worst': 0.0
    })

    for la in lot_agg.values():
        b = la['broker']
        pnl = la['pnl']
        d = brokers[b]
        d['trades'] += 1
        d['total_pnl'] += pnl
        if pnl > 0:
            d['wins'] += 1
            d['gross_profit'] += pnl
        elif pnl < 0:
            d['losses'] += 1
            d['gross_loss'] += abs(pnl)
        if pnl > d['best']:
            d['best'] = pnl
        if pnl < d['worst']:
            d['worst'] = pnl

    result = []
    for broker_name, d in brokers.items():
        wr = _safe_round((d['wins'] / d['trades'] * 100) if d['trades'] > 0 else 0)
        ap = _safe_round(d['total_pnl'] / d['trades']) if d['trades'] > 0 else 0.0
        if d['gross_loss'] > 0:
            pf = _safe_round(min(d['gross_profit'] / d['gross_loss'], 10.0))
        else:
            pf = _safe_round(min(d['gross_profit'], 10.0)) if d['gross_profit'] > 0 else 0.0

        result.append({
            'broker': broker_name,
            'total_trades': d['trades'],
            'wins': d['wins'],
            'losses': d['losses'],
            'win_rate': wr,
            'total_pnl': _safe_round(d['total_pnl']),
            'avg_pnl': ap,
            'profit_factor': pf,
            'best_trade': _safe_round(d['best']),
            'worst_trade': _safe_round(d['worst']),
        })

    result.sort(key=lambda x: x['total_pnl'], reverse=True)
    return result


def get_trade_journal(user_id, start_date=None, end_date=None, broker=None, period=None,
                      page=1, per_page=50, sort_by='closed_at', sort_dir='desc',
                      symbol_filter=None, status_filter=None):
    sd, ed = _resolve_date_range(period, start_date, end_date)
    conn = get_connection()

    allowed_sort = {'closed_at', 'pnl', 'pnl_percent', 'symbol', 'executed_at', 'holding_days'}
    if sort_by not in allowed_sort:
        sort_by = 'closed_at'
    sort_dir = 'ASC' if sort_dir.upper() == 'ASC' else 'DESC'

    trades_out = []

    if status_filter is None or status_filter.upper() in ('CLOSED', 'PARTIAL', 'ALL', ''):
        params_c = [user_id]
        where_c = ["(lc.user_id IS NULL OR lc.user_id = ?)"]
        where_c += _build_date_filter("lc.closed_at", sd, ed, params_c)

        if broker:
            where_c.append(_build_broker_filter(broker))
            params_c.extend(_broker_filter_params(broker))

        if symbol_filter:
            where_c.append("UPPER(sl.symbol) = UPPER(?)")
            params_c.append(symbol_filter)

        closed_sql = f"""
            SELECT sl.id as lot_id, sl.symbol, sl.asset_type, sl.strike, sl.expiry,
                   sl.call_put, sl.open_price, sl.original_qty, sl.remaining_qty, sl.status as lot_status,
                   t.direction, t.broker, t.source, t.channel_id as trade_channel_id, t.executed_at,
                   sl.channel_id as sl_channel_id,
                   lc.id as lc_id, lc.closed_qty, lc.close_price, lc.pnl, lc.pnl_percent,
                   lc.exit_reason, lc.holding_days, lc.closed_at,
                   COALESCE(c.name, c2.name) as channel_name,
                   c2.enabled_brokers as ch_enabled_brokers
            FROM lot_closures lc
            LEFT JOIN signal_lots sl ON sl.id = lc.lot_id
            LEFT JOIN trades t ON t.id = sl.trade_id
            LEFT JOIN channels c ON c.discord_channel_id = t.channel_id
            LEFT JOIN channels c2 ON CAST(c2.id AS TEXT) = sl.channel_id
            WHERE {' AND '.join(where_c)}
            ORDER BY lc.closed_at DESC
        """
        closed_rows = conn.execute(closed_sql, params_c).fetchall()

        lot_groups = defaultdict(lambda: {
            'info': None, 'exits': [], 'total_pnl': 0.0,
            'total_exit_qty': 0, 'weighted_pnl_pct_sum': 0.0,
            'weighted_price_sum': 0.0, 'max_closed_at': '',
            'min_closed_at': 'Z', 'max_holding_days': 0.0,
        })

        for r in closed_rows:
            lid = r['lot_id'] or r['lc_id']
            g = lot_groups[lid]
            if g['info'] is None:
                g['info'] = dict(r)

            pnl = float(r['pnl'] or 0)
            pnl_pct = float(r['pnl_percent'] or 0)
            qty = int(r['closed_qty'] or 0)
            price = float(r['close_price'] or 0)
            hd = float(r['holding_days'] or 0)
            g['total_pnl'] += pnl
            g['total_exit_qty'] += qty
            g['weighted_pnl_pct_sum'] += pnl_pct * qty
            g['weighted_price_sum'] += price * qty
            if hd > g['max_holding_days']:
                g['max_holding_days'] = hd
            closed_at_str = _utc_to_est(r['closed_at']) or ''
            if closed_at_str and closed_at_str > g['max_closed_at']:
                g['max_closed_at'] = closed_at_str
            if closed_at_str and closed_at_str < g['min_closed_at']:
                g['min_closed_at'] = closed_at_str

            g['exits'].append({
                'qty': qty,
                'price': _safe_round(price),
                'pnl': _safe_round(pnl),
                'pnl_pct': _safe_round(pnl_pct),
                'exit_reason': r['exit_reason'] or '',
                'date': closed_at_str,
            })

        for lid, g in lot_groups.items():
            info = g['info']
            if not info:
                continue
            open_qty = int(info['original_qty'] or 0)
            remaining = int(info['remaining_qty'] or 0)
            if remaining > 0:
                status = 'PARTIAL'
            else:
                status = 'CLOSED'

            avg_exit = _safe_round(g['weighted_price_sum'] / g['total_exit_qty']) if g['total_exit_qty'] > 0 else 0.0
            total_pnl_pct = _safe_round(g['weighted_pnl_pct_sum'] / g['total_exit_qty']) if g['total_exit_qty'] > 0 else 0.0

            close_date = g['max_closed_at'] if g['max_closed_at'] else ''
            open_date = g['min_closed_at'] if g['min_closed_at'] != 'Z' else ''

            direction = info['direction'] or ''
            if not direction:
                direction = 'BTO'

            trades_out.append({
                'id': lid,
                'symbol': info['symbol'] or '',
                'asset_type': info['asset_type'] or '',
                'strike': info['strike'] or '',
                'expiry': info['expiry'] or '',
                'call_put': info['call_put'] or '',
                'direction': direction,
                'entry_price': _safe_round(info['open_price']),
                'entry_qty': open_qty,
                'entry_date': _utc_to_est(info['executed_at']) or open_date,
                'closed_date': close_date,
                'exit_price': avg_exit,
                'total_exit_qty': g['total_exit_qty'],
                'pnl': _safe_round(g['total_pnl']),
                'pnl_pct': total_pnl_pct,
                'broker': _resolve_broker_from_row(info),
                'channel_name': info['channel_name'] or '',
                'source': info['source'] or '',
                'status': status,
                'holding_days': _safe_round(g['max_holding_days']),
                'partial_exits': g['exits'],
            })

    if status_filter is None or status_filter.upper() in ('OPEN', 'ALL', ''):
        params_o = [user_id]
        where_o = ["(t.user_id IS NULL OR t.user_id = ?)", "UPPER(t.status) = 'OPEN'"]
        if broker:
            where_o.append("UPPER(COALESCE(t.broker, '')) = UPPER(?)")
            params_o.append(broker)
        if symbol_filter:
            where_o.append("UPPER(t.symbol) = UPPER(?)")
            params_o.append(symbol_filter)

        open_sql = f"""
            SELECT t.id, t.symbol, t.asset_type, t.strike, t.expiry, t.call_put,
                   t.direction, t.executed_price, t.quantity, t.current_price,
                   t.pnl, t.pnl_percent, t.broker, t.source, t.channel_id,
                   t.executed_at,
                   c.name as channel_name
            FROM trades t
            LEFT JOIN channels c ON c.discord_channel_id = t.channel_id
            WHERE {' AND '.join(where_o)}
        """
        open_rows = conn.execute(open_sql, params_o).fetchall()

        for r in open_rows:
            entry_date = _utc_to_est(r['executed_at']) or ''
            trades_out.append({
                'id': r['id'],
                'symbol': r['symbol'] or '',
                'asset_type': r['asset_type'] or '',
                'strike': r['strike'] or '',
                'expiry': r['expiry'] or '',
                'call_put': r['call_put'] or '',
                'direction': r['direction'] or '',
                'entry_price': _safe_round(r['executed_price']),
                'entry_qty': int(r['quantity'] or 0),
                'entry_date': entry_date,
                'closed_date': '',
                'exit_price': 0.0,
                'total_exit_qty': 0,
                'pnl': _safe_round(r['pnl']),
                'pnl_pct': _safe_round(r['pnl_percent']),
                'broker': r['broker'] or '',
                'channel_name': r['channel_name'] or '',
                'source': r['source'] or '',
                'status': 'OPEN',
                'holding_days': 0,
                'partial_exits': [],
            })

    is_desc = (sort_dir == 'DESC')

    def _date_sort_key(x):
        date_val = x.get('closed_date', '') or x.get('entry_date', '') or ''
        return date_val

    sort_key_map = {
        'closed_at': _date_sort_key,
        'pnl': lambda x: x.get('pnl', 0),
        'pnl_percent': lambda x: x.get('pnl_pct', 0),
        'symbol': lambda x: x.get('symbol', ''),
        'executed_at': lambda x: x.get('entry_date', '') or '',
        'holding_days': lambda x: x.get('holding_days', 0),
    }
    key_fn = sort_key_map.get(sort_by, _date_sort_key)
    trades_out.sort(key=key_fn, reverse=is_desc)

    if sort_by in ('closed_at', 'executed_at'):
        open_trades = [t for t in trades_out if t.get('status') == 'OPEN']
        closed_trades = [t for t in trades_out if t.get('status') != 'OPEN']
        if is_desc:
            trades_out = open_trades + closed_trades
        else:
            trades_out = closed_trades + open_trades

    total_trades = len(trades_out)
    total_pages = max(1, math.ceil(total_trades / per_page))
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    page_trades = trades_out[start_idx:end_idx]

    params_filters = [user_id]
    symbols_rows = conn.execute(
        "SELECT DISTINCT symbol FROM trades WHERE (user_id IS NULL OR user_id = ?) AND symbol IS NOT NULL ORDER BY symbol",
        params_filters
    ).fetchall()
    brokers_rows = conn.execute(
        "SELECT DISTINCT broker FROM trades WHERE (user_id IS NULL OR user_id = ?) AND broker IS NOT NULL ORDER BY broker",
        params_filters
    ).fetchall()
    channel_brokers_rows = conn.execute(
        "SELECT DISTINCT enabled_brokers FROM channels WHERE enabled_brokers IS NOT NULL AND enabled_brokers != '[]'"
    ).fetchall()
    all_broker_names = set(r['broker'].upper() for r in brokers_rows if r['broker'])
    for cbr in channel_brokers_rows:
        try:
            bl = json.loads(cbr['enabled_brokers'])
            if isinstance(bl, list):
                for b in bl:
                    if b:
                        all_broker_names.add(b.upper())
        except (json.JSONDecodeError, TypeError):
            pass
    all_broker_names.discard('')
    all_broker_names.discard(None)

    return {
        'trades': page_trades,
        'pagination': {
            'page': page,
            'per_page': per_page,
            'total_trades': total_trades,
            'total_pages': total_pages,
        },
        'filters': {
            'symbols': [r['symbol'] for r in symbols_rows],
            'brokers': sorted(all_broker_names),
            'statuses': ['OPEN', 'CLOSED', 'PARTIAL'],
        },
    }


def get_time_breakdown(user_id, bucket='daily', start_date=None, end_date=None, broker=None, period=None):
    sd, ed = _resolve_date_range(period, start_date, end_date)
    conn = get_connection()

    params = [user_id]
    where = ["(lc.user_id IS NULL OR lc.user_id = ?)"]
    where += _build_date_filter("lc.closed_at", sd, ed, params)

    if broker:
        where.append(_build_broker_filter(broker))
        params.extend(_broker_filter_params(broker))

    sql = f"""
        SELECT lc.pnl, lc.closed_at
        FROM lot_closures lc
        WHERE {' AND '.join(where)}
          AND (lc.pnl IS NOT NULL AND lc.pnl != 0)
        ORDER BY lc.closed_at ASC
    """
    rows = conn.execute(sql, params).fetchall()

    buckets_data = defaultdict(lambda: {'pnl': 0.0, 'trades': 0, 'wins': 0, 'losses': 0})

    for r in rows:
        pnl = float(r['pnl'] or 0)
        closed_at = _utc_to_est(r['closed_at']) or ''
        if not closed_at:
            continue

        try:
            dt = datetime.strptime(closed_at[:19], '%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError):
            try:
                dt = datetime.strptime(closed_at[:10], '%Y-%m-%d')
            except (ValueError, TypeError):
                continue

        if bucket == 'daily':
            label = dt.strftime('%Y-%m-%d')
        elif bucket == 'weekly':
            iso = dt.isocalendar()
            label = f"{iso[0]}-W{iso[1]:02d}"
        elif bucket == 'monthly':
            label = dt.strftime('%Y-%m')
        elif bucket == 'yearly':
            label = dt.strftime('%Y')
        else:
            label = dt.strftime('%Y-%m-%d')

        b = buckets_data[label]
        b['pnl'] += pnl
        b['trades'] += 1
        if pnl > 0:
            b['wins'] += 1
        elif pnl < 0:
            b['losses'] += 1

    sorted_labels = sorted(buckets_data.keys())
    result = []
    cumulative = 0.0
    for label in sorted_labels:
        b = buckets_data[label]
        cumulative += b['pnl']
        wr = _safe_round((b['wins'] / b['trades'] * 100) if b['trades'] > 0 else 0)
        result.append({
            'period_label': label,
            'pnl': _safe_round(b['pnl']),
            'cumulative_pnl': _safe_round(cumulative),
            'trades': b['trades'],
            'wins': b['wins'],
            'losses': b['losses'],
            'win_rate': wr,
        })

    return result


def get_performance_heatmap(user_id, start_date=None, end_date=None, broker=None, period=None):
    sd, ed = _resolve_date_range(period, start_date, end_date)
    conn = get_connection()

    params = [user_id]
    where = ["(lc.user_id IS NULL OR lc.user_id = ?)"]
    where += _build_date_filter("lc.closed_at", sd, ed, params)

    if broker:
        where.append(_build_broker_filter(broker))
        params.extend(_broker_filter_params(broker))

    sql = f"""
        SELECT lc.pnl, lc.closed_at
        FROM lot_closures lc
        WHERE {' AND '.join(where)}
          AND (lc.pnl IS NOT NULL AND lc.pnl != 0)
    """
    rows = conn.execute(sql, params).fetchall()

    day_data = defaultdict(lambda: {'trades': 0, 'pnl': 0.0, 'wins': 0})
    hour_data = defaultdict(lambda: {'trades': 0, 'pnl': 0.0, 'wins': 0})

    for r in rows:
        pnl = float(r['pnl'] or 0)
        closed_at = _utc_to_est(r['closed_at']) or ''
        if not closed_at:
            continue
        try:
            dt = datetime.strptime(closed_at[:19], '%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError):
            try:
                dt = datetime.strptime(closed_at[:10], '%Y-%m-%d')
            except (ValueError, TypeError):
                continue

        dow = dt.strftime('%a')
        hour = dt.hour

        d = day_data[dow]
        d['trades'] += 1
        d['pnl'] += pnl
        if pnl > 0:
            d['wins'] += 1

        h = hour_data[hour]
        h['trades'] += 1
        h['pnl'] += pnl
        if pnl > 0:
            h['wins'] += 1

    day_order = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    day_of_week = []
    for day in day_order:
        d = day_data.get(day, {'trades': 0, 'pnl': 0.0, 'wins': 0})
        wr = _safe_round((d['wins'] / d['trades'] * 100) if d['trades'] > 0 else 0)
        ap = _safe_round(d['pnl'] / d['trades']) if d['trades'] > 0 else 0.0
        day_of_week.append({
            'day': day,
            'trades': d['trades'],
            'pnl': _safe_round(d['pnl']),
            'avg_pnl': ap,
            'win_rate': wr,
        })

    hour_of_day = []
    for hr in range(24):
        h = hour_data.get(hr, {'trades': 0, 'pnl': 0.0, 'wins': 0})
        wr = _safe_round((h['wins'] / h['trades'] * 100) if h['trades'] > 0 else 0)
        ap = _safe_round(h['pnl'] / h['trades']) if h['trades'] > 0 else 0.0
        hour_of_day.append({
            'hour': hr,
            'trades': h['trades'],
            'pnl': _safe_round(h['pnl']),
            'avg_pnl': ap,
            'win_rate': wr,
        })

    return {
        'day_of_week': day_of_week,
        'hour_of_day': hour_of_day,
    }


def get_edge_analysis(user_id, start_date=None, end_date=None, broker=None, period=None):
    sd, ed = _resolve_date_range(period, start_date, end_date)
    conn = get_connection()

    params = [user_id]
    where = ["(lc.user_id IS NULL OR lc.user_id = ?)"]
    where += _build_date_filter("lc.closed_at", sd, ed, params)

    if broker:
        where.append(_build_broker_filter(broker))
        params.extend(_broker_filter_params(broker))

    sql = f"""
        SELECT sl.symbol, sl.asset_type, t.direction, t.source, t.channel_id,
               lc.pnl, lc.pnl_percent, lc.exit_reason, lc.holding_days,
               COALESCE(c.name, c2.name) as channel_name
        FROM lot_closures lc
        LEFT JOIN signal_lots sl ON sl.id = lc.lot_id
        LEFT JOIN trades t ON t.id = sl.trade_id
        LEFT JOIN channels c ON c.discord_channel_id = t.channel_id
        LEFT JOIN channels c2 ON CAST(c2.id AS TEXT) = sl.channel_id
        WHERE {' AND '.join(where)}
          AND (lc.pnl IS NOT NULL AND lc.pnl != 0)
    """
    rows = conn.execute(sql, params).fetchall()

    sym_data = defaultdict(lambda: {'trades': 0, 'pnl': 0.0, 'wins': 0, 'hold_sum': 0.0})
    asset_data = defaultdict(lambda: {'trades': 0, 'pnl': 0.0, 'wins': 0})
    dir_data = defaultdict(lambda: {'trades': 0, 'pnl': 0.0, 'wins': 0})
    src_data = defaultdict(lambda: {'trades': 0, 'pnl': 0.0, 'wins': 0})
    chan_data = defaultdict(lambda: {'trades': 0, 'pnl': 0.0, 'wins': 0})
    exit_data = defaultdict(lambda: {'trades': 0, 'pnl': 0.0, 'wins': 0})

    for r in rows:
        pnl = float(r['pnl'] or 0)
        sym = r['symbol'] or 'UNKNOWN'
        at = r['asset_type'] or 'unknown'
        direction = r['direction'] or 'unknown'
        source = r['source'] or 'unknown'
        ch_name = r['channel_name'] or 'Unknown'
        raw_exit = (r['exit_reason'] or 'UNKNOWN').upper().strip()
        if 'PT1' in raw_exit or 'PROFIT_TARGET_1' in raw_exit or 'TIER 1' in raw_exit or 'TARGET 1' in raw_exit:
            exit_r = 'PT1'
        elif 'PT2' in raw_exit or 'PROFIT_TARGET_2' in raw_exit or 'TIER 2' in raw_exit or 'TARGET 2' in raw_exit:
            exit_r = 'PT2'
        elif 'PT3' in raw_exit or 'PROFIT_TARGET_3' in raw_exit or 'TIER 3' in raw_exit or 'TARGET 3' in raw_exit:
            exit_r = 'PT3'
        elif 'PT4' in raw_exit or 'PROFIT_TARGET_4' in raw_exit or 'TIER 4' in raw_exit or 'TARGET 4' in raw_exit:
            exit_r = 'PT4'
        elif 'PROFIT' in raw_exit or 'TARGET' in raw_exit or 'TIER' in raw_exit:
            exit_r = 'PROFIT_TARGET'
        elif 'STOP' in raw_exit or 'SL' == raw_exit:
            exit_r = 'STOP_LOSS'
        elif 'EARLY TRAIL' in raw_exit or 'EARLY_TRAIL' in raw_exit:
            exit_r = 'EARLY_TRAILING'
        elif 'TRAIL' in raw_exit:
            exit_r = 'TRAILING_STOP'
        elif 'MANUAL' in raw_exit:
            exit_r = 'MANUAL'
        elif 'SIGNAL' in raw_exit or 'STC' in raw_exit:
            exit_r = 'SIGNAL_EXIT'
        elif 'CANCEL' in raw_exit:
            exit_r = 'CANCELLED'
        elif 'EMA' in raw_exit:
            exit_r = 'EMA_EXIT'
        elif 'GIVEBACK' in raw_exit:
            exit_r = 'GIVEBACK_GUARD'
        elif 'BREAKEVEN' in raw_exit:
            exit_r = 'BREAKEVEN'
        elif raw_exit == 'UNKNOWN' or raw_exit == '':
            exit_r = 'OTHER'
        else:
            exit_r = raw_exit[:20]
        hd = float(r['holding_days'] or 0)
        is_win = pnl > 0

        s = sym_data[sym]
        s['trades'] += 1
        s['pnl'] += pnl
        s['hold_sum'] += hd
        if is_win:
            s['wins'] += 1

        a = asset_data[at]
        a['trades'] += 1
        a['pnl'] += pnl
        if is_win:
            a['wins'] += 1

        d = dir_data[direction]
        d['trades'] += 1
        d['pnl'] += pnl
        if is_win:
            d['wins'] += 1

        sc = src_data[source]
        sc['trades'] += 1
        sc['pnl'] += pnl
        if is_win:
            sc['wins'] += 1

        ch = chan_data[ch_name]
        ch['trades'] += 1
        ch['pnl'] += pnl
        if is_win:
            ch['wins'] += 1

        ex = exit_data[exit_r]
        ex['trades'] += 1
        ex['pnl'] += pnl
        if is_win:
            ex['wins'] += 1

    def _build_breakdown(data, top_n=None, include_hold=False):
        items = []
        for key, d in data.items():
            wr = _safe_round((d['wins'] / d['trades'] * 100) if d['trades'] > 0 else 0)
            ap = _safe_round(d['pnl'] / d['trades']) if d['trades'] > 0 else 0.0
            entry = {
                'name': key,
                'trades': d['trades'],
                'pnl': _safe_round(d['pnl']),
                'win_rate': wr,
                'avg_pnl': ap,
            }
            if include_hold:
                entry['avg_hold'] = _safe_round(d['hold_sum'] / d['trades']) if d['trades'] > 0 else 0.0
            items.append(entry)
        items.sort(key=lambda x: x['trades'], reverse=True)
        if top_n:
            items = items[:top_n]
        return items

    return {
        'by_symbol': _build_breakdown(sym_data, top_n=15, include_hold=True),
        'by_asset_type': _build_breakdown(asset_data),
        'by_direction': _build_breakdown(dir_data),
        'by_source': _build_breakdown(src_data),
        'by_channel': _build_breakdown(chan_data),
        'by_exit_reason': _build_breakdown(exit_data),
    }


def get_calendar_data(user_id, year, month, broker=None):
    import calendar
    conn = get_connection()

    first_day = datetime(year, month, 1)
    if month == 12:
        last_day = datetime(year + 1, 1, 1) - timedelta(seconds=1)
    else:
        last_day = datetime(year, month + 1, 1) - timedelta(seconds=1)

    sd = first_day.strftime('%Y-%m-%d 00:00:00')
    ed = last_day.strftime('%Y-%m-%d 23:59:59')

    params = [user_id]
    where = ["(lc.user_id IS NULL OR lc.user_id = ?)"]
    where += _build_date_filter("lc.closed_at", sd, ed, params)

    if broker:
        where.append(_build_broker_filter(broker))
        params.extend(_broker_filter_params(broker))

    sql = f"""
        SELECT lc.pnl, lc.closed_at, sl.symbol
        FROM lot_closures lc
        LEFT JOIN signal_lots sl ON sl.id = lc.lot_id
        WHERE {' AND '.join(where)}
          AND lc.pnl IS NOT NULL
        ORDER BY lc.closed_at ASC
    """
    rows = conn.execute(sql, params).fetchall()

    daily = defaultdict(lambda: {'pnl': 0.0, 'trades': 0, 'wins': 0, 'losses': 0, 'symbols': set()})
    for r in rows:
        pnl = float(r['pnl'] or 0)
        closed_at = _utc_to_est(r['closed_at']) or ''
        if not closed_at:
            continue
        day_key = closed_at[:10]
        d = daily[day_key]
        d['pnl'] += pnl
        d['trades'] += 1
        if pnl > 0:
            d['wins'] += 1
        elif pnl < 0:
            d['losses'] += 1
        if r['symbol']:
            d['symbols'].add(r['symbol'])

    days_out = {}
    for day_key, d in daily.items():
        wr = _safe_round((d['wins'] / d['trades'] * 100) if d['trades'] > 0 else 0)
        days_out[day_key] = {
            'pnl': _safe_round(d['pnl']),
            'trades': d['trades'],
            'wins': d['wins'],
            'losses': d['losses'],
            'win_rate': wr,
        }

    weekly = defaultdict(lambda: {'pnl': 0.0, 'days': 0, 'trades': 0, 'wins': 0, 'losses': 0})
    cal = calendar.Calendar(firstweekday=6)
    week_num = 0
    prev_week_start = None
    for week_dates in cal.monthdatescalendar(year, month):
        week_start = week_dates[0]
        if week_start == prev_week_start:
            continue
        prev_week_start = week_start
        week_num += 1
        for dt in week_dates:
            if dt.month != month:
                continue
            day_str = dt.strftime('%Y-%m-%d')
            if day_str in days_out:
                dd = days_out[day_str]
                w = weekly[week_num]
                w['pnl'] += dd['pnl']
                w['days'] += 1
                w['trades'] += dd['trades']
                w['wins'] += dd['wins']
                w['losses'] += dd['losses']

    weeks_out = []
    for wn in sorted(weekly.keys()):
        w = weekly[wn]
        weeks_out.append({
            'week': wn,
            'pnl': _safe_round(w['pnl']),
            'days': w['days'],
            'trades': w['trades'],
            'wins': w['wins'],
            'losses': w['losses'],
        })

    total_pnl = sum(d['pnl'] for d in days_out.values())
    total_days = len(days_out)
    total_trades = sum(d['trades'] for d in days_out.values())

    cumulative_daily = []
    cum = 0.0
    for day_key in sorted(days_out.keys()):
        cum += days_out[day_key]['pnl']
        cumulative_daily.append({
            'date': day_key,
            'pnl': days_out[day_key]['pnl'],
            'cumulative': _safe_round(cum),
        })

    return {
        'year': year,
        'month': month,
        'days': days_out,
        'weeks': weeks_out,
        'cumulative_daily': cumulative_daily,
        'monthly_pnl': _safe_round(total_pnl),
        'trading_days': total_days,
        'total_trades': total_trades,
    }
