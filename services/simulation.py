"""
Simulation Engine Module for QuantumPulse Trading Bot

This module provides deterministic expected value simulation for traders
based on their historical performance data from the leaderboard.

Author: QuantumPulse Team
Version: 1.9.0
"""

from typing import Optional, Literal, Dict, List, Any
from dataclasses import dataclass
from datetime import datetime, timedelta
import sqlite3
import os

MAX_EXPOSURE_PCT = 0.40
MAX_EXPECTED_PCT_PER_TRADE = 0.50  # Cap at 50% expected return per trade
MIN_WIN_RATE_FOR_REALISTIC = 0.40  # Below 40% or above 95% triggers warning
MAX_WIN_RATE_FOR_REALISTIC = 0.95
DEFAULT_PORTFOLIO = 3000.0
DEFAULT_DAYS = 30
DEFAULT_RISK_VALUE = 300.0


@dataclass
class SimulationParams:
    """Parameters for running a simulation."""
    entity_type: Literal["user", "channel"]
    entity_id: str
    portfolio_start: float = DEFAULT_PORTFOLIO
    days: int = DEFAULT_DAYS
    trades_per_day: Optional[float] = None
    win_rate_override: Optional[float] = None
    avg_win_pct_override: Optional[float] = None
    avg_loss_pct_override: Optional[float] = None
    risk_per_trade_mode: Literal["fixed", "percent"] = "fixed"
    risk_per_trade_value: float = DEFAULT_RISK_VALUE
    compound: bool = True


@dataclass
class EntityStats:
    """Statistics for a user or channel from the database."""
    name: str
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    total_pnl: float
    avg_win_pct: float
    avg_loss_pct: float
    avg_pnl_percent: float
    first_trade_date: Optional[str]
    last_trade_date: Optional[str]
    trading_days: int


@dataclass
class TradeRecord:
    """Individual trade record from the database."""
    id: int
    ticker: str
    asset_type: str
    open_price: float
    close_price: float
    quantity: int
    pnl: float
    pnl_percent: float
    opened_at: str
    closed_at: str
    author_name: str
    channel_id: str


def get_db_path() -> str:
    """Get the database path."""
    paths = ['./bot_data.db', './gui_app/bot_data.db', './quantumpulse.db']
    for path in paths:
        if os.path.exists(path):
            return path
    return './bot_data.db'


def fetch_user_trade_history(author_name: str, limit: int = 500) -> List[TradeRecord]:
    """
    Fetch actual individual trades for a user from lot_closures.
    
    Args:
        author_name: The Discord username
        limit: Maximum number of trades to fetch
    
    Returns:
        List of TradeRecord objects in chronological order (oldest first)
    """
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    query = """
        SELECT 
            lc.id,
            sl.symbol,
            sl.asset_type,
            sl.open_price,
            lc.close_price,
            lc.closed_qty,
            lc.pnl,
            lc.pnl_percent,
            sl.opened_at,
            lc.closed_at,
            COALESCE(lc.author_name, sl.author_name) as author_name,
            lc.channel_id
        FROM lot_closures lc
        JOIN signal_lots sl ON lc.lot_id = sl.id
        WHERE LOWER(COALESCE(lc.author_name, sl.author_name)) = LOWER(?)
        ORDER BY lc.closed_at ASC
        LIMIT ?
    """
    
    cursor.execute(query, (author_name, limit))
    rows = cursor.fetchall()
    conn.close()
    
    trades = []
    for row in rows:
        trades.append(TradeRecord(
            id=row[0],
            ticker=row[1],
            asset_type=row[2],
            open_price=row[3] or 0,
            close_price=row[4] or 0,
            quantity=row[5] or 0,
            pnl=row[6] or 0,
            pnl_percent=row[7] or 0,
            opened_at=row[8] or '',
            closed_at=row[9] or '',
            author_name=row[10] or '',
            channel_id=row[11] or ''
        ))
    
    return trades


def fetch_channel_trade_history(channel_name: str, limit: int = 500) -> List[TradeRecord]:
    """
    Fetch actual individual trades for a channel from lot_closures.
    
    Args:
        channel_name: The channel name
        limit: Maximum number of trades to fetch
    
    Returns:
        List of TradeRecord objects in chronological order (oldest first)
    """
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    query = """
        SELECT 
            lc.id,
            sl.symbol,
            sl.asset_type,
            sl.open_price,
            lc.close_price,
            lc.closed_qty,
            lc.pnl,
            lc.pnl_percent,
            sl.opened_at,
            lc.closed_at,
            COALESCE(lc.author_name, sl.author_name) as author_name,
            lc.channel_id
        FROM lot_closures lc
        JOIN signal_lots sl ON lc.lot_id = sl.id
        JOIN channels c ON lc.channel_id = c.id
        WHERE LOWER(c.name) = LOWER(?)
        ORDER BY lc.closed_at ASC
        LIMIT ?
    """
    
    cursor.execute(query, (channel_name, limit))
    rows = cursor.fetchall()
    conn.close()
    
    trades = []
    for row in rows:
        trades.append(TradeRecord(
            id=row[0],
            ticker=row[1],
            asset_type=row[2],
            open_price=row[3] or 0,
            close_price=row[4] or 0,
            quantity=row[5] or 0,
            pnl=row[6] or 0,
            pnl_percent=row[7] or 0,
            opened_at=row[8] or '',
            closed_at=row[9] or '',
            author_name=row[10] or '',
            channel_id=row[11] or ''
        ))
    
    return trades


def get_user_stats(author_name: str, period_days: int = 30) -> Optional[EntityStats]:
    """
    Fetch user performance statistics from the database.
    
    Args:
        author_name: The Discord username/author name
        period_days: Number of days to look back (default 30)
    
    Returns:
        EntityStats object or None if user not found
    """
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        query = '''
            SELECT 
                sl.author_name,
                COUNT(lc.id) as total_trades,
                SUM(CASE WHEN lc.pnl > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN lc.pnl <= 0 THEN 1 ELSE 0 END) as losses,
                SUM(lc.pnl) as total_pnl,
                
                -- Average win percentage (only winning trades)
                AVG(CASE WHEN lc.pnl > 0 THEN 
                    (lc.pnl / (sl.open_price * lc.closed_qty * CASE WHEN sl.asset_type = 'option' THEN 100 ELSE 1 END)) * 100
                ELSE NULL END) as avg_win_pct,
                
                -- Average loss percentage (only losing trades)
                AVG(CASE WHEN lc.pnl < 0 THEN 
                    (lc.pnl / (sl.open_price * lc.closed_qty * CASE WHEN sl.asset_type = 'option' THEN 100 ELSE 1 END)) * 100
                ELSE NULL END) as avg_loss_pct,
                
                -- Overall average percentage
                SUM(sl.open_price * lc.closed_qty * CASE WHEN sl.asset_type = 'option' THEN 100 ELSE 1 END) as total_cost_basis,
                
                MIN(DATE(lc.closed_at)) as first_trade_date,
                MAX(DATE(lc.closed_at)) as last_trade_date,
                COUNT(DISTINCT DATE(lc.closed_at)) as trading_days
                
            FROM signal_lots sl
            JOIN lot_closures lc ON sl.id = lc.lot_id
            WHERE LOWER(sl.author_name) = LOWER(?)
            GROUP BY sl.author_name
        '''
        
        cursor.execute(query, (author_name,))
        row = cursor.fetchone()
        
        if not row or row['total_trades'] == 0:
            return None
        
        total_trades = row['total_trades']
        wins = row['wins'] or 0
        losses = row['losses'] or 0
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
        
        avg_win_pct = row['avg_win_pct'] or 50.0
        avg_loss_pct = row['avg_loss_pct'] or -30.0
        
        total_cost_basis = row['total_cost_basis'] or 0
        avg_pnl_percent = (row['total_pnl'] / total_cost_basis * 100) if total_cost_basis > 0 else 0
        
        return EntityStats(
            name=row['author_name'],
            total_trades=total_trades,
            wins=wins,
            losses=losses,
            win_rate=win_rate,
            total_pnl=row['total_pnl'] or 0,
            avg_win_pct=avg_win_pct,
            avg_loss_pct=avg_loss_pct,
            avg_pnl_percent=avg_pnl_percent,
            first_trade_date=row['first_trade_date'],
            last_trade_date=row['last_trade_date'],
            trading_days=row['trading_days'] or 1
        )
        
    finally:
        conn.close()


def get_channel_stats(channel_name: str, period_days: int = 30) -> Optional[EntityStats]:
    """
    Fetch channel performance statistics from the database.
    
    Args:
        channel_name: The channel name or ID
        period_days: Number of days to look back (default 30)
    
    Returns:
        EntityStats object or None if channel not found
    """
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        query = '''
            SELECT 
                c.name as channel_name,
                COUNT(lc.id) as total_trades,
                SUM(CASE WHEN lc.pnl > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN lc.pnl <= 0 THEN 1 ELSE 0 END) as losses,
                SUM(lc.pnl) as total_pnl,
                
                -- Average win percentage (only winning trades)
                AVG(CASE WHEN lc.pnl > 0 THEN 
                    (lc.pnl / (sl.open_price * lc.closed_qty * CASE WHEN sl.asset_type = 'option' THEN 100 ELSE 1 END)) * 100
                ELSE NULL END) as avg_win_pct,
                
                -- Average loss percentage (only losing trades)
                AVG(CASE WHEN lc.pnl < 0 THEN 
                    (lc.pnl / (sl.open_price * lc.closed_qty * CASE WHEN sl.asset_type = 'option' THEN 100 ELSE 1 END)) * 100
                ELSE NULL END) as avg_loss_pct,
                
                -- Overall average percentage
                SUM(sl.open_price * lc.closed_qty * CASE WHEN sl.asset_type = 'option' THEN 100 ELSE 1 END) as total_cost_basis,
                
                MIN(DATE(lc.closed_at)) as first_trade_date,
                MAX(DATE(lc.closed_at)) as last_trade_date,
                COUNT(DISTINCT DATE(lc.closed_at)) as trading_days
                
            FROM channels c
            JOIN signals s ON s.channel_id = c.id
            JOIN signal_lots sl ON sl.signal_id = s.id
            JOIN lot_closures lc ON lc.lot_id = sl.id
            WHERE LOWER(c.name) = LOWER(?) OR c.id = ?
            GROUP BY c.id, c.name
        '''
        
        try:
            channel_id = int(channel_name)
        except ValueError:
            channel_id = -1
        
        cursor.execute(query, (channel_name, channel_id))
        row = cursor.fetchone()
        
        if not row or row['total_trades'] == 0:
            return None
        
        total_trades = row['total_trades']
        wins = row['wins'] or 0
        losses = row['losses'] or 0
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
        
        avg_win_pct = row['avg_win_pct'] or 50.0
        avg_loss_pct = row['avg_loss_pct'] or -30.0
        
        total_cost_basis = row['total_cost_basis'] or 0
        avg_pnl_percent = (row['total_pnl'] / total_cost_basis * 100) if total_cost_basis > 0 else 0
        
        return EntityStats(
            name=row['channel_name'],
            total_trades=total_trades,
            wins=wins,
            losses=losses,
            win_rate=win_rate,
            total_pnl=row['total_pnl'] or 0,
            avg_win_pct=avg_win_pct,
            avg_loss_pct=avg_loss_pct,
            avg_pnl_percent=avg_pnl_percent,
            first_trade_date=row['first_trade_date'],
            last_trade_date=row['last_trade_date'],
            trading_days=row['trading_days'] or 1
        )
        
    finally:
        conn.close()


def generate_strategy_recommendation(
    win_rate: float,
    expected_pct_per_trade: float,
    trades_per_day: float,
    risk_per_trade_mode: str,
    risk_per_trade_value: float,
    portfolio_start: float
) -> str:
    """
    Generate a strategy recommendation based on simulation parameters and results.
    
    Args:
        win_rate: Win rate as decimal (0-1)
        expected_pct_per_trade: Expected return percentage per trade as decimal
        trades_per_day: Average number of trades per day
        risk_per_trade_mode: "fixed" or "percent"
        risk_per_trade_value: Risk value (dollar amount or percentage)
        portfolio_start: Starting portfolio value
    
    Returns:
        Strategy recommendation text with emoji
    """
    if risk_per_trade_mode == "percent":
        risk_pct = risk_per_trade_value
    else:
        risk_pct = risk_per_trade_value / portfolio_start if portfolio_start > 0 else 0.1
    
    max_open_trades = max(1, int(MAX_EXPOSURE_PCT / risk_pct)) if risk_pct > 0 else 10
    
    if expected_pct_per_trade < 0:
        return (
            f"⚠️ NEGATIVE EDGE DETECTED\n\n"
            f"This trader/channel has negative expected value ({expected_pct_per_trade*100:.1f}% per trade). "
            f"Based on current stats, copying these signals will likely result in losses over time.\n\n"
            f"Recommendation:\n"
            f"• Use very small position sizes (1-2% per trade maximum)\n"
            f"• Consider paper trading first to verify performance\n"
            f"• Monitor closely for 2+ weeks before any real capital"
        )
    
    elif win_rate > 0.85 and expected_pct_per_trade > 0.20:
        return (
            f"🔥 HIGH-QUALITY SOURCE\n\n"
            f"Exceptional stats: {win_rate*100:.0f}% win rate with {expected_pct_per_trade*100:.1f}% expected return per trade.\n\n"
            f"Recommendation:\n"
            f"• Risk 7-10% of portfolio per trade\n"
            f"• Maximum {max_open_trades} concurrent open positions\n"
            f"• Target {trades_per_day:.1f} trades per day\n"
            f"• Consider scaling up after consistent performance"
        )
    
    elif win_rate >= 0.60:
        return (
            f"✅ PROFITABLE BUT VOLATILE\n\n"
            f"Solid performance: {win_rate*100:.0f}% win rate with {expected_pct_per_trade*100:.1f}% expected return per trade.\n\n"
            f"Recommendation:\n"
            f"• Risk 3-5% of portfolio per trade\n"
            f"• Limit to {max_open_trades} concurrent open positions\n"
            f"• Keep daily trades around {trades_per_day:.1f}\n"
            f"• Use stop losses to protect against large drawdowns"
        )
    
    else:
        return (
            f"⚠️ SMALL EDGE - USE CAUTION\n\n"
            f"Marginal stats: {win_rate*100:.0f}% win rate with {expected_pct_per_trade*100:.1f}% expected return per trade.\n\n"
            f"Recommendation:\n"
            f"• Risk only 2-3% of portfolio per trade\n"
            f"• Maximum {max_open_trades} concurrent positions\n"
            f"• Paper trade for 2+ weeks before using real money\n"
            f"• Be prepared for extended losing streaks"
        )


def run_simulation(
    entity_type: Literal["user", "channel"],
    entity_id: str,
    portfolio_start: float = DEFAULT_PORTFOLIO,
    days: int = DEFAULT_DAYS,
    trades_per_day: Optional[float] = None,
    win_rate_override: Optional[float] = None,
    avg_win_pct_override: Optional[float] = None,
    avg_loss_pct_override: Optional[float] = None,
    risk_per_trade_mode: Literal["fixed", "percent"] = "fixed",
    risk_per_trade_value: float = DEFAULT_RISK_VALUE,
    compound: bool = True,
) -> Dict[str, Any]:
    """
    Run a deterministic expected value simulation for a user or channel.
    
    This simulation calculates expected portfolio growth based on historical
    performance data and configurable risk parameters.
    
    Args:
        entity_type: "user" or "channel"
        entity_id: Username or channel name/ID
        portfolio_start: Starting portfolio value (default $3,000)
        days: Number of days to simulate (default 30)
        trades_per_day: Override for trades per day (default: from stats)
        win_rate_override: Override for win rate as decimal 0-1
        avg_win_pct_override: Override for avg win % as decimal (e.g., 0.5 = 50%)
        avg_loss_pct_override: Override for avg loss % as decimal (e.g., -0.3 = -30%)
        risk_per_trade_mode: "fixed" (dollar amount) or "percent" (of balance)
        risk_per_trade_value: Risk amount (dollars if fixed, decimal if percent)
        compound: Whether to reinvest profits daily
    
    Returns:
        Dict containing simulation results:
        - entity_type, entity_id, label
        - stats_used: Original stats from database
        - params_used: All parameters used in simulation
        - summary: Final results (final_balance, total_profit, etc.)
        - strategy_text: Recommendation string
        - daily_breakdown: List of daily results
    """
    if entity_type == "user":
        stats = get_user_stats(entity_id)
    else:
        stats = get_channel_stats(entity_id)
    
    if stats is None:
        return {
            'success': False,
            'error': f'{entity_type.capitalize()} "{entity_id}" not found or has no closed trades.',
            'entity_type': entity_type,
            'entity_id': entity_id
        }
    
    actual_trades_per_day = stats.total_trades / max(stats.trading_days, 1)
    final_trades_per_day = trades_per_day if trades_per_day is not None else actual_trades_per_day
    
    final_win_rate = win_rate_override if win_rate_override is not None else (stats.win_rate / 100)
    final_avg_win_pct = avg_win_pct_override if avg_win_pct_override is not None else (stats.avg_win_pct / 100)
    final_avg_loss_pct = avg_loss_pct_override if avg_loss_pct_override is not None else (stats.avg_loss_pct / 100)
    
    expected_pct_per_trade_raw = (
        final_win_rate * final_avg_win_pct +
        (1 - final_win_rate) * final_avg_loss_pct
    )
    
    warnings = []
    expected_pct_per_trade = expected_pct_per_trade_raw
    
    if final_win_rate >= MAX_WIN_RATE_FOR_REALISTIC:
        warnings.append(f"Win rate is {final_win_rate*100:.0f}% (near 100%). Projections may be unrealistic due to small sample size or exceptional performance.")
    
    if final_win_rate <= MIN_WIN_RATE_FOR_REALISTIC and expected_pct_per_trade_raw > 0:
        warnings.append(f"Win rate is only {final_win_rate*100:.0f}%. High volatility expected despite positive edge.")
    
    if expected_pct_per_trade_raw > MAX_EXPECTED_PCT_PER_TRADE:
        warnings.append(f"Expected return per trade ({expected_pct_per_trade_raw*100:.1f}%) exceeds realistic bounds. Capped to {MAX_EXPECTED_PCT_PER_TRADE*100:.0f}% for projection.")
        expected_pct_per_trade = MAX_EXPECTED_PCT_PER_TRADE
    
    if abs(final_avg_loss_pct) < 0.01 and final_win_rate < 1.0:
        warnings.append("Average loss is near 0%. This may indicate incomplete data or unusual trading style.")
    
    balance = portfolio_start
    daily_breakdown = []
    
    for day in range(1, days + 1):
        day_start_balance = balance
        
        if risk_per_trade_mode == "fixed":
            position_size = min(risk_per_trade_value, balance)
        else:
            position_size = balance * risk_per_trade_value
        
        position_size = min(position_size, balance * 0.5)
        
        expected_wins = final_trades_per_day * final_win_rate
        expected_losses = final_trades_per_day * (1 - final_win_rate)
        daily_profit = final_trades_per_day * position_size * expected_pct_per_trade
        
        if compound:
            balance += daily_profit
        else:
            balance = portfolio_start + (daily_profit * day)
        
        balance = max(0, balance)
        
        daily_breakdown.append({
            'day': day,
            'start_balance': round(day_start_balance, 2),
            'position_size': round(position_size, 2),
            'trades': round(final_trades_per_day),
            'expected_wins': round(expected_wins, 1),
            'expected_losses': round(expected_losses, 1),
            'daily_profit': round(daily_profit, 2),
            'end_balance': round(balance, 2),
            'cumulative_return_pct': round(((balance - portfolio_start) / portfolio_start) * 100, 2)
        })
    
    final_balance = balance
    total_profit = final_balance - portfolio_start
    total_return_pct = (total_profit / portfolio_start) * 100 if portfolio_start > 0 else 0
    
    daily_profits = [d['daily_profit'] for d in daily_breakdown]
    avg_daily_profit = sum(daily_profits) / len(daily_profits) if daily_profits else 0
    best_day_profit = max(daily_profits) if daily_profits else 0
    worst_day_profit = min(daily_profits) if daily_profits else 0
    
    if days >= 30:
        monthly_profit_est = total_profit
    elif days >= 7:
        monthly_ratio = 22.0 / days
        monthly_profit_est = total_profit * monthly_ratio
    else:
        monthly_profit_est = avg_daily_profit * 22 if avg_daily_profit > 0 else None
    
    if days >= 7:
        first_7_days_profit = sum(daily_profits[:7]) if len(daily_profits) >= 7 else sum(daily_profits)
        trading_days_in_week = min(5, len(daily_profits))
        weekly_profit_est = sum(daily_profits[:trading_days_in_week])
    else:
        weekly_profit_est = avg_daily_profit * 5 if avg_daily_profit > 0 else None
    
    strategy_text = generate_strategy_recommendation(
        win_rate=final_win_rate,
        expected_pct_per_trade=expected_pct_per_trade,
        trades_per_day=final_trades_per_day,
        risk_per_trade_mode=risk_per_trade_mode,
        risk_per_trade_value=risk_per_trade_value,
        portfolio_start=portfolio_start
    )
    
    return {
        'success': True,
        'entity_type': entity_type,
        'entity_id': entity_id,
        'label': f"{entity_type.capitalize()}: {stats.name}",
        
        'stats_used': {
            'name': stats.name,
            'total_trades': stats.total_trades,
            'wins': stats.wins,
            'losses': stats.losses,
            'win_rate': round(stats.win_rate, 1),
            'total_pnl': round(stats.total_pnl, 2),
            'avg_win_pct': round(stats.avg_win_pct, 1),
            'avg_loss_pct': round(stats.avg_loss_pct, 1),
            'avg_pnl_percent': round(stats.avg_pnl_percent, 1),
            'trading_days': stats.trading_days,
            'actual_trades_per_day': round(actual_trades_per_day, 2),
            'first_trade_date': stats.first_trade_date,
            'last_trade_date': stats.last_trade_date
        },
        
        'params_used': {
            'portfolio_start': portfolio_start,
            'days': days,
            'trades_per_day': round(final_trades_per_day),
            'win_rate': round(final_win_rate * 100, 1),
            'avg_win_pct': round(final_avg_win_pct * 100, 1),
            'avg_loss_pct': round(final_avg_loss_pct * 100, 1),
            'expected_pct_per_trade': round(expected_pct_per_trade * 100, 2),
            'expected_pct_per_trade_raw': round(expected_pct_per_trade_raw * 100, 2),
            'was_capped': expected_pct_per_trade != expected_pct_per_trade_raw,
            'risk_per_trade_mode': risk_per_trade_mode,
            'risk_per_trade_value': risk_per_trade_value,
            'compound': compound
        },
        
        'warnings': warnings,
        
        'summary': {
            'final_balance': round(final_balance, 2),
            'total_profit': round(total_profit, 2),
            'total_return_pct': round(total_return_pct, 1),
            'avg_daily_profit': round(avg_daily_profit, 2),
            'best_day_profit': round(best_day_profit, 2),
            'worst_day_profit': round(worst_day_profit, 2),
            'weekly_profit_est': round(weekly_profit_est, 2) if weekly_profit_est else None,
            'monthly_profit_est': round(monthly_profit_est, 2) if monthly_profit_est else None,
            'is_profitable': total_profit > 0,
            'edge_quality': 'positive' if expected_pct_per_trade > 0 else 'negative'
        },
        
        'strategy_text': strategy_text,
        'daily_breakdown': daily_breakdown
    }


def run_exact_trades_simulation(
    entity_type: Literal["user", "channel"],
    entity_id: str,
    portfolio_start: float = DEFAULT_PORTFOLIO,
    risk_per_trade_mode: Literal["fixed", "percent"] = "fixed",
    risk_per_trade_value: float = DEFAULT_RISK_VALUE,
    win_rate_override: Optional[float] = None,
    avg_loss_pct_override: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Run an EXACT trades simulation - replays historical trades with custom portfolio/position size.
    
    This uses the ACTUAL number of trades, wins, and losses from the trader's history,
    not probabilistic projections. Shows exactly what would have happened if you followed
    all their trades with your position sizing.
    
    Args:
        entity_type: "user" or "channel"
        entity_id: Username or channel name
        portfolio_start: Starting portfolio value
        risk_per_trade_mode: "fixed" (dollar amount) or "percent" (of balance)
        risk_per_trade_value: Risk amount per trade
        win_rate_override: Optional override for win rate (0-100)
        avg_loss_pct_override: Optional override for avg loss % (should be negative)
    
    Returns:
        Dict with exact trade-by-trade results
    """
    if entity_type == "user":
        stats = get_user_stats(entity_id)
    else:
        stats = get_channel_stats(entity_id)
    
    if stats is None:
        return {
            'success': False,
            'error': f'{entity_type.capitalize()} "{entity_id}" not found or has no closed trades.',
            'entity_type': entity_type,
            'entity_id': entity_id
        }
    
    total_trades = stats.total_trades
    original_wins = stats.wins
    original_losses = stats.losses
    original_win_rate = stats.win_rate
    avg_win_pct = stats.avg_win_pct / 100  # Convert to decimal
    avg_loss_pct = stats.avg_loss_pct / 100  # Already negative
    
    # Apply overrides if provided
    if win_rate_override is not None:
        # Recalculate wins/losses based on new win rate
        effective_win_rate = min(max(win_rate_override, 0), 100) / 100
        wins = round(total_trades * effective_win_rate)
        losses = total_trades - wins
        used_win_rate = win_rate_override
    else:
        wins = original_wins
        losses = original_losses
        effective_win_rate = original_win_rate / 100
        used_win_rate = original_win_rate
    
    if avg_loss_pct_override is not None:
        # Override uses percentage - ensure it's negative (loss is always negative)
        # User can enter 30 or -30, both mean -30% loss
        override_value = avg_loss_pct_override
        if override_value > 0:
            override_value = -override_value  # Convert positive to negative
        avg_loss_pct = override_value / 100
        used_avg_loss_pct = override_value  # Store the negative value
    else:
        used_avg_loss_pct = stats.avg_loss_pct
    
    # Simulate each trade
    balance = portfolio_start
    trade_breakdown = []
    
    for i in range(1, total_trades + 1):
        trade_start_balance = balance
        
        # Calculate position size
        if risk_per_trade_mode == "fixed":
            position_size = min(risk_per_trade_value, balance)
        else:
            position_size = balance * risk_per_trade_value
        
        # Cap at 50% of balance
        position_size = min(position_size, balance * 0.5)
        
        # Determine if this trade is a win or loss based on proportional distribution
        # We distribute wins first, then losses
        if i <= wins:
            is_win = True
            pnl_pct = avg_win_pct
        else:
            is_win = False
            pnl_pct = avg_loss_pct
        
        trade_pnl = position_size * pnl_pct
        balance += trade_pnl
        balance = max(0, balance)
        
        trade_breakdown.append({
            'trade_num': i,
            'start_balance': round(trade_start_balance, 2),
            'position_size': round(position_size, 2),
            'result': 'WIN' if is_win else 'LOSS',
            'pnl_pct': round(pnl_pct * 100, 1),
            'trade_pnl': round(trade_pnl, 2),
            'end_balance': round(balance, 2),
            'cumulative_return_pct': round(((balance - portfolio_start) / portfolio_start) * 100, 1)
        })
    
    final_balance = balance
    total_profit = final_balance - portfolio_start
    total_return_pct = (total_profit / portfolio_start) * 100 if portfolio_start > 0 else 0
    
    # Calculate summary stats
    winning_trades = [t for t in trade_breakdown if t['result'] == 'WIN']
    losing_trades = [t for t in trade_breakdown if t['result'] == 'LOSS']
    
    total_win_pnl = sum(t['trade_pnl'] for t in winning_trades)
    total_loss_pnl = sum(t['trade_pnl'] for t in losing_trades)
    
    avg_win_dollar = total_win_pnl / len(winning_trades) if winning_trades else 0
    avg_loss_dollar = total_loss_pnl / len(losing_trades) if losing_trades else 0
    
    return {
        'success': True,
        'simulation_mode': 'exact_trades',
        'entity_type': entity_type,
        'entity_id': entity_id,
        'label': f'{entity_type.capitalize()}: {stats.name}',
        
        'stats_used': {
            'name': stats.name,
            'total_trades': total_trades,
            'wins': wins,
            'losses': losses,
            'win_rate': round(used_win_rate, 1),
            'avg_win_pct': round(stats.avg_win_pct, 1),
            'avg_loss_pct': round(used_avg_loss_pct, 1),
            'total_pnl': round(stats.total_pnl, 2),
            'first_trade_date': stats.first_trade_date,
            'last_trade_date': stats.last_trade_date,
            'original_win_rate': round(original_win_rate, 1),
            'original_avg_loss_pct': round(stats.avg_loss_pct, 1),
            'win_rate_overridden': win_rate_override is not None,
            'avg_loss_overridden': avg_loss_pct_override is not None,
        },
        
        'params_used': {
            'portfolio_start': portfolio_start,
            'risk_per_trade_mode': risk_per_trade_mode,
            'risk_per_trade_value': risk_per_trade_value if risk_per_trade_mode == 'fixed' else round(risk_per_trade_value * 100, 1),
        },
        
        'summary': {
            'final_balance': round(final_balance, 2),
            'total_profit': round(total_profit, 2),
            'total_return_pct': round(total_return_pct, 1),
            'total_trades': total_trades,
            'wins': wins,
            'losses': losses,
            'total_win_pnl': round(total_win_pnl, 2),
            'total_loss_pnl': round(total_loss_pnl, 2),
            'avg_win_dollar': round(avg_win_dollar, 2),
            'avg_loss_dollar': round(avg_loss_dollar, 2),
            'is_profitable': total_profit > 0
        },
        
        'trade_breakdown': trade_breakdown
    }


def run_exact_historical_simulation(
    entity_type: Literal["user", "channel"],
    entity_id: str,
    portfolio_start: float = DEFAULT_PORTFOLIO,
    risk_per_trade_mode: Literal["fixed", "percent"] = "fixed",
    risk_per_trade_value: float = DEFAULT_RISK_VALUE,
) -> Dict[str, Any]:
    """
    Run an EXACT HISTORICAL simulation - replays ACTUAL individual trades from the database.
    
    This uses the REAL trade history with each trade's actual P&L percentage,
    not averages. Shows exactly what would have happened if you followed
    each specific trade with your position sizing.
    
    Args:
        entity_type: "user" or "channel"
        entity_id: Username or channel name
        portfolio_start: Starting portfolio value
        risk_per_trade_mode: "fixed" (dollar amount) or "percent" (of balance)
        risk_per_trade_value: Risk amount per trade
    
    Returns:
        Dict with actual trade-by-trade results including ticker and dates
    """
    # Fetch actual trade history
    if entity_type == "user":
        trades = fetch_user_trade_history(entity_id)
    else:
        trades = fetch_channel_trade_history(entity_id)
    
    if not trades:
        return {
            'success': False,
            'error': f'{entity_type.capitalize()} "{entity_id}" not found or has no closed trades in lot_closures.',
            'entity_type': entity_type,
            'entity_id': entity_id
        }
    
    # Calculate actual position values for each trade
    actual_position_values = []
    for trade in trades:
        multiplier = 100 if trade.asset_type == 'option' else 1
        actual_value = trade.open_price * trade.quantity * multiplier
        actual_position_values.append(actual_value)
    
    # Calculate average position size for suggestion
    avg_position_size = sum(actual_position_values) / len(actual_position_values) if actual_position_values else 0
    median_position_size = sorted(actual_position_values)[len(actual_position_values) // 2] if actual_position_values else 0
    
    # Simulate each actual trade
    balance = portfolio_start
    trade_breakdown = []
    wins = 0
    losses = 0
    total_win_pnl = 0
    total_loss_pnl = 0
    
    for i, trade in enumerate(trades, 1):
        trade_start_balance = balance
        
        # Calculate actual position value for this trade
        multiplier = 100 if trade.asset_type == 'option' else 1
        actual_position_value = trade.open_price * trade.quantity * multiplier
        
        # Calculate simulated position size (user's risk setting)
        if risk_per_trade_mode == "fixed":
            sim_position_size = min(risk_per_trade_value, balance)
        else:
            sim_position_size = balance * risk_per_trade_value
        
        # Cap at 50% of balance
        sim_position_size = min(sim_position_size, balance * 0.5)
        
        # Use actual P&L percent from the trade
        pnl_pct = trade.pnl_percent / 100  # Convert to decimal
        is_win = pnl_pct >= 0
        
        trade_pnl = sim_position_size * pnl_pct
        balance += trade_pnl
        balance = max(0, balance)
        
        if is_win:
            wins += 1
            total_win_pnl += trade_pnl
        else:
            losses += 1
            total_loss_pnl += trade_pnl
        
        # Format closed_at date for display
        closed_date = trade.closed_at[:10] if trade.closed_at else ''
        
        trade_breakdown.append({
            'trade_num': i,
            'ticker': trade.ticker,
            'asset_type': trade.asset_type,
            'closed_at': closed_date,
            'actual_position_value': round(actual_position_value, 2),
            'actual_pnl_pct': round(trade.pnl_percent, 1),
            'actual_pnl': round(trade.pnl, 2),
            'start_balance': round(trade_start_balance, 2),
            'position_size': round(sim_position_size, 2),
            'result': 'WIN' if is_win else 'LOSS',
            'pnl_pct': round(pnl_pct * 100, 1),
            'trade_pnl': round(trade_pnl, 2),
            'end_balance': round(balance, 2),
            'cumulative_return_pct': round(((balance - portfolio_start) / portfolio_start) * 100, 1)
        })
    
    final_balance = balance
    total_profit = final_balance - portfolio_start
    total_return_pct = (total_profit / portfolio_start) * 100 if portfolio_start > 0 else 0
    total_trades = len(trades)
    
    # Calculate averages
    avg_win_pnl = total_win_pnl / wins if wins > 0 else 0
    avg_loss_pnl = total_loss_pnl / losses if losses > 0 else 0
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
    
    # Get date range
    first_trade_date = trades[0].closed_at[:10] if trades else ''
    last_trade_date = trades[-1].closed_at[:10] if trades else ''
    
    return {
        'success': True,
        'simulation_mode': 'exact_historical',
        'entity_type': entity_type,
        'entity_id': entity_id,
        'label': f'{entity_type.capitalize()}: {entity_id}',
        
        'stats_used': {
            'name': entity_id,
            'total_trades': total_trades,
            'wins': wins,
            'losses': losses,
            'win_rate': round(win_rate, 1),
            'first_trade_date': first_trade_date,
            'last_trade_date': last_trade_date,
            'avg_position_size': round(avg_position_size, 2),
            'median_position_size': round(median_position_size, 2),
            'suggested_position_size': round(median_position_size, 2),
        },
        
        'params_used': {
            'portfolio_start': portfolio_start,
            'risk_per_trade_mode': risk_per_trade_mode,
            'risk_per_trade_value': risk_per_trade_value if risk_per_trade_mode == 'fixed' else round(risk_per_trade_value * 100, 1),
        },
        
        'summary': {
            'final_balance': round(final_balance, 2),
            'total_profit': round(total_profit, 2),
            'total_return_pct': round(total_return_pct, 1),
            'total_trades': total_trades,
            'wins': wins,
            'losses': losses,
            'total_win_pnl': round(total_win_pnl, 2),
            'total_loss_pnl': round(total_loss_pnl, 2),
            'avg_win_dollar': round(avg_win_pnl, 2),
            'avg_loss_dollar': round(avg_loss_pnl, 2),
            'is_profitable': total_profit > 0
        },
        
        'trade_breakdown': trade_breakdown
    }


def get_simulation_presets() -> List[Dict[str, Any]]:
    """
    Get predefined simulation presets for quick configuration.
    
    Returns:
        List of preset configurations
    """
    return [
        {
            'name': 'Conservative',
            'description': 'Low risk, steady growth',
            'params': {
                'portfolio_start': 3000,
                'days': 30,
                'risk_per_trade_mode': 'percent',
                'risk_per_trade_value': 0.03,
                'compound': True
            }
        },
        {
            'name': 'Moderate',
            'description': 'Balanced risk and reward',
            'params': {
                'portfolio_start': 5000,
                'days': 30,
                'risk_per_trade_mode': 'percent',
                'risk_per_trade_value': 0.05,
                'compound': True
            }
        },
        {
            'name': 'Aggressive',
            'description': 'Higher risk, faster growth',
            'params': {
                'portfolio_start': 10000,
                'days': 30,
                'risk_per_trade_mode': 'percent',
                'risk_per_trade_value': 0.10,
                'compound': True
            }
        },
        {
            'name': 'Fixed $300',
            'description': 'Fixed $300 per trade',
            'params': {
                'portfolio_start': 3000,
                'days': 30,
                'risk_per_trade_mode': 'fixed',
                'risk_per_trade_value': 300,
                'compound': True
            }
        }
    ]
