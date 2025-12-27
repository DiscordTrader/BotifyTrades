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

import random
import math
from statistics import mean, stdev

MAX_EXPOSURE_PCT = 0.40
MAX_EXPECTED_PCT_PER_TRADE = 0.50  # Cap at 50% expected return per trade
MIN_WIN_RATE_FOR_REALISTIC = 0.40  # Below 40% or above 95% triggers warning
MAX_WIN_RATE_FOR_REALISTIC = 0.95
DEFAULT_PORTFOLIO = 3000.0
DEFAULT_DAYS = 30
DEFAULT_RISK_VALUE = 300.0

# Risk optimizer position size percentages to test
RISK_OPTIMIZER_PERCENTAGES = [1, 2, 3, 5, 10, 15, 20, 25]

# Monte Carlo settings
MONTE_CARLO_ITERATIONS = 1000


def get_asset_multiplier(asset_type: str) -> int:
    """Get the contract multiplier for an asset type."""
    if asset_type and asset_type.lower() == 'option':
        return 100
    return 1


def calculate_affordable_quantity(
    budget: float,
    price_per_share: float,
    asset_type: str
) -> tuple:
    """
    Calculate how many contracts/shares can be afforded with the given budget.
    
    Args:
        budget: Dollar amount available for position
        price_per_share: Price per share (for options, this is the premium per share)
        asset_type: 'option' or 'stock'
    
    Returns:
        Tuple of (quantity, actual_position_value, skip_reason or None)
    """
    if budget <= 0:
        return (0, 0, "Zero budget")
    
    if price_per_share is None or price_per_share <= 0:
        return (0, 0, "Invalid price (zero or negative)")
    
    multiplier = get_asset_multiplier(asset_type)
    cost_per_unit = price_per_share * multiplier
    
    if cost_per_unit <= 0:
        return (0, 0, "Zero cost per unit")
    
    # Calculate affordable quantity (floor to whole number)
    quantity = int(budget / cost_per_unit)
    
    if quantity < 1:
        return (0, 0, f"Cannot afford 1 unit (need ${cost_per_unit:.2f}, have ${budget:.2f})")
    
    actual_position_value = quantity * cost_per_unit
    return (quantity, actual_position_value, None)


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


# =============================================================================
# ADVANCED RISK METRICS
# =============================================================================

def calculate_kelly_criterion(win_rate: float, avg_win_pct: float, avg_loss_pct: float) -> Dict[str, Any]:
    """
    Calculate Kelly Criterion for optimal position sizing.
    
    Kelly % = (Win Probability × Win/Loss Ratio - Loss Probability) / Win/Loss Ratio
    Or simplified: Kelly % = W - (1-W)/R where W=win rate, R=win/loss ratio
    
    Args:
        win_rate: Win probability (0-1)
        avg_win_pct: Average winning trade percentage (e.g., 25 for 25%)
        avg_loss_pct: Average losing trade percentage as positive number (e.g., 15 for -15%)
    
    Returns:
        Dict with full_kelly, half_kelly, quarter_kelly percentages and recommendation
    """
    if avg_loss_pct <= 0 or avg_win_pct <= 0:
        return {
            'full_kelly': 0,
            'half_kelly': 0,
            'quarter_kelly': 0,
            'recommendation': 'Insufficient data',
            'edge': 0,
            'is_valid': False
        }
    
    # Win/Loss ratio (R)
    win_loss_ratio = avg_win_pct / avg_loss_pct
    
    # Kelly formula: K = W - (1-W)/R
    loss_rate = 1 - win_rate
    full_kelly = (win_rate - (loss_rate / win_loss_ratio)) * 100
    
    # Cap at reasonable levels
    full_kelly = max(0, min(full_kelly, 50))  # Cap between 0-50%
    half_kelly = full_kelly / 2
    quarter_kelly = full_kelly / 4
    
    # Calculate edge (expected value per unit risked)
    edge = (win_rate * win_loss_ratio) - loss_rate
    
    # Generate recommendation
    if full_kelly <= 0:
        recommendation = "AVOID: Negative edge - this strategy loses money long-term"
    elif full_kelly < 5:
        recommendation = f"CONSERVATIVE: Risk {quarter_kelly:.1f}-{half_kelly:.1f}% per trade (small edge)"
    elif full_kelly < 15:
        recommendation = f"MODERATE: Risk {half_kelly:.1f}% per trade (use Half Kelly for safety)"
    elif full_kelly < 25:
        recommendation = f"AGGRESSIVE: Full Kelly suggests {full_kelly:.1f}%, but use {half_kelly:.1f}% to reduce volatility"
    else:
        recommendation = f"CAUTION: Kelly {full_kelly:.1f}% is very high - use Quarter Kelly ({quarter_kelly:.1f}%) to avoid ruin"
    
    return {
        'full_kelly': round(full_kelly, 2),
        'half_kelly': round(half_kelly, 2),
        'quarter_kelly': round(quarter_kelly, 2),
        'win_loss_ratio': round(win_loss_ratio, 2),
        'recommendation': recommendation,
        'edge': round(edge, 3),
        'is_valid': full_kelly > 0
    }


def calculate_expectancy(win_rate: float, avg_win_pct: float, avg_loss_pct: float, avg_position: float = 100) -> Dict[str, Any]:
    """
    Calculate trade expectancy (expected value per trade).
    
    Expectancy = (Win% × Avg Win) - (Loss% × Avg Loss)
    
    Args:
        win_rate: Win probability (0-1)
        avg_win_pct: Average winning trade percentage
        avg_loss_pct: Average losing trade percentage (positive number)
        avg_position: Average position size in dollars
    
    Returns:
        Dict with expectancy metrics
    """
    loss_rate = 1 - win_rate
    
    # Expectancy as percentage
    expectancy_pct = (win_rate * avg_win_pct) - (loss_rate * avg_loss_pct)
    
    # Expectancy in dollars (per trade)
    expectancy_dollars = (expectancy_pct / 100) * avg_position
    
    # Profit factor = (Wins × Avg Win) / (Losses × Avg Loss)
    if loss_rate > 0 and avg_loss_pct > 0:
        profit_factor = (win_rate * avg_win_pct) / (loss_rate * avg_loss_pct)
    else:
        profit_factor = float('inf') if win_rate > 0 else 0
    
    # Determine quality
    if expectancy_pct <= 0:
        quality = 'NEGATIVE EDGE'
        quality_color = 'danger'
    elif expectancy_pct < 2:
        quality = 'MARGINAL'
        quality_color = 'warning'
    elif expectancy_pct < 5:
        quality = 'GOOD'
        quality_color = 'info'
    else:
        quality = 'EXCELLENT'
        quality_color = 'success'
    
    return {
        'expectancy_pct': round(expectancy_pct, 2),
        'expectancy_dollars': round(expectancy_dollars, 2),
        'profit_factor': round(profit_factor, 2) if profit_factor != float('inf') else 999,
        'quality': quality,
        'quality_color': quality_color,
        'is_positive': expectancy_pct > 0
    }


def calculate_risk_of_ruin(
    win_rate: float,
    avg_win_pct: float,
    avg_loss_pct: float,
    position_size_pct: float,
    ruin_threshold: float = 0.5
) -> Dict[str, Any]:
    """
    Estimate Risk of Ruin probability using simplified formula.
    
    Risk of Ruin approximation for fixed fractional betting:
    RoR ≈ ((1-edge)/(1+edge))^(bankroll_units)
    
    Args:
        win_rate: Win probability (0-1)
        avg_win_pct: Average winning trade percentage
        avg_loss_pct: Average losing trade percentage (positive)
        position_size_pct: Position size as percentage of portfolio (e.g., 10 for 10%)
        ruin_threshold: What percentage loss counts as "ruin" (0.5 = 50% loss)
    
    Returns:
        Dict with risk of ruin probabilities at various thresholds
    """
    # Calculate edge
    loss_rate = 1 - win_rate
    edge = (win_rate * avg_win_pct) - (loss_rate * avg_loss_pct)
    
    # Normalize edge to per-unit
    edge_normalized = edge / 100
    
    # Number of "units" in bankroll based on position size
    if position_size_pct > 0:
        bankroll_units = 100 / position_size_pct
    else:
        bankroll_units = 100
    
    # Calculate risk of ruin at different thresholds
    results = {}
    thresholds = [('50%', 0.5), ('75%', 0.75), ('100%', 1.0)]
    
    for label, threshold in thresholds:
        units_to_lose = bankroll_units * threshold
        
        if edge_normalized <= 0:
            # Negative or zero edge = eventual ruin is certain
            ror = 100.0
        elif edge_normalized >= 1:
            # Edge > 100% = theoretically can't lose
            ror = 0.0
        else:
            # Simplified RoR formula
            try:
                ratio = (1 - edge_normalized) / (1 + edge_normalized)
                ror = min(100, max(0, (ratio ** units_to_lose) * 100))
            except:
                ror = 50.0  # Default if calculation fails
        
        results[f'ror_{label}'] = round(ror, 1)
    
    # Overall risk assessment
    ror_50 = results['ror_50%']
    if ror_50 >= 50:
        risk_level = 'CRITICAL'
        risk_color = 'danger'
        advice = 'REDUCE position size immediately! High probability of catastrophic loss.'
    elif ror_50 >= 20:
        risk_level = 'HIGH'
        risk_color = 'warning'
        advice = 'Consider reducing position size. Risk of significant drawdown is elevated.'
    elif ror_50 >= 5:
        risk_level = 'MODERATE'
        risk_color = 'info'
        advice = 'Acceptable risk level, but monitor closely during losing streaks.'
    else:
        risk_level = 'LOW'
        risk_color = 'success'
        advice = 'Well-sized positions. Continue current risk management approach.'
    
    return {
        **results,
        'edge_pct': round(edge, 2),
        'risk_level': risk_level,
        'risk_color': risk_color,
        'advice': advice,
        'position_size_pct': position_size_pct
    }


def analyze_streaks(trades: List[TradeRecord]) -> Dict[str, Any]:
    """
    Analyze winning and losing streaks in trade history.
    
    Args:
        trades: List of TradeRecord objects
    
    Returns:
        Dict with streak statistics
    """
    if not trades:
        return {
            'max_win_streak': 0,
            'max_loss_streak': 0,
            'current_streak': 0,
            'current_streak_type': 'none',
            'avg_win_streak': 0,
            'avg_loss_streak': 0,
            'streak_insight': 'Insufficient data'
        }
    
    win_streaks = []
    loss_streaks = []
    current_streak = 0
    current_type = None
    
    for trade in trades:
        is_win = trade.pnl >= 0
        
        if current_type is None:
            current_type = 'win' if is_win else 'loss'
            current_streak = 1
        elif (is_win and current_type == 'win') or (not is_win and current_type == 'loss'):
            current_streak += 1
        else:
            # Streak ended, save it
            if current_type == 'win':
                win_streaks.append(current_streak)
            else:
                loss_streaks.append(current_streak)
            current_type = 'win' if is_win else 'loss'
            current_streak = 1
    
    # Don't forget the last streak
    if current_type == 'win':
        win_streaks.append(current_streak)
    elif current_type == 'loss':
        loss_streaks.append(current_streak)
    
    max_win_streak = max(win_streaks) if win_streaks else 0
    max_loss_streak = max(loss_streaks) if loss_streaks else 0
    avg_win_streak = mean(win_streaks) if win_streaks else 0
    avg_loss_streak = mean(loss_streaks) if loss_streaks else 0
    
    # Generate insight
    if max_loss_streak >= 5:
        insight = f"⚠️ Experienced {max_loss_streak} consecutive losses. Size positions to survive 2× this streak."
    elif max_loss_streak >= 3:
        insight = f"Max losing streak: {max_loss_streak}. Plan for at least {max_loss_streak + 2} consecutive losses."
    else:
        insight = f"Good streak management. Max loss streak of {max_loss_streak} is manageable."
    
    return {
        'max_win_streak': max_win_streak,
        'max_loss_streak': max_loss_streak,
        'current_streak': current_streak,
        'current_streak_type': current_type or 'none',
        'avg_win_streak': round(avg_win_streak, 1),
        'avg_loss_streak': round(avg_loss_streak, 1),
        'streak_insight': insight,
        'total_win_streaks': len(win_streaks),
        'total_loss_streaks': len(loss_streaks)
    }


def analyze_trading_times(trades: List[TradeRecord]) -> Dict[str, Any]:
    """
    Analyze performance by day of week and time of day.
    
    Args:
        trades: List of TradeRecord objects
    
    Returns:
        Dict with time-based performance analysis
    """
    if len(trades) < 10:
        return {
            'best_day': 'N/A',
            'worst_day': 'N/A',
            'day_breakdown': {},
            'has_enough_data': False,
            'insight': 'Need at least 10 trades for time analysis'
        }
    
    # Track P&L by day of week
    day_pnl = {i: {'pnl': 0, 'count': 0, 'wins': 0} for i in range(7)}
    day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    
    for trade in trades:
        try:
            if trade.closed_at:
                dt = datetime.fromisoformat(trade.closed_at.replace('Z', '+00:00').split('+')[0])
                day = dt.weekday()
                day_pnl[day]['pnl'] += trade.pnl_percent
                day_pnl[day]['count'] += 1
                if trade.pnl >= 0:
                    day_pnl[day]['wins'] += 1
        except:
            continue
    
    # Find best and worst days (only consider days with trades)
    active_days = {k: v for k, v in day_pnl.items() if v['count'] >= 2}
    
    if not active_days:
        return {
            'best_day': 'N/A',
            'worst_day': 'N/A',
            'day_breakdown': {},
            'has_enough_data': False,
            'insight': 'Not enough trades per day for analysis'
        }
    
    best_day_idx = max(active_days.keys(), key=lambda x: active_days[x]['pnl'])
    worst_day_idx = min(active_days.keys(), key=lambda x: active_days[x]['pnl'])
    
    # Build breakdown
    day_breakdown = {}
    for day_idx, data in active_days.items():
        avg_pnl = data['pnl'] / data['count'] if data['count'] > 0 else 0
        win_rate = (data['wins'] / data['count'] * 100) if data['count'] > 0 else 0
        day_breakdown[day_names[day_idx]] = {
            'avg_pnl': round(avg_pnl, 2),
            'trades': data['count'],
            'win_rate': round(win_rate, 1)
        }
    
    # Generate insight
    best_day = day_names[best_day_idx]
    worst_day = day_names[worst_day_idx]
    
    if active_days[best_day_idx]['pnl'] > 0 and active_days[worst_day_idx]['pnl'] < 0:
        insight = f"📅 Best: {best_day} | Worst: {worst_day}. Consider reducing size on {worst_day}s."
    else:
        insight = f"📅 Most active: {best_day}. Performance varies by day - track patterns."
    
    return {
        'best_day': best_day,
        'worst_day': worst_day,
        'day_breakdown': day_breakdown,
        'has_enough_data': True,
        'insight': insight
    }


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
                
                -- Average loss percentage (losing and breakeven trades)
                AVG(CASE WHEN lc.pnl <= 0 THEN 
                    (lc.pnl / NULLIF(sl.open_price * lc.closed_qty * CASE WHEN sl.asset_type = 'option' THEN 100 ELSE 1 END, 0)) * 100
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
                
                -- Average loss percentage (losing and breakeven trades)
                AVG(CASE WHEN lc.pnl <= 0 THEN 
                    (lc.pnl / NULLIF(sl.open_price * lc.closed_qty * CASE WHEN sl.asset_type = 'option' THEN 100 ELSE 1 END, 0)) * 100
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
        elif risk_per_trade_mode == "percent":
            # User enters percentage (e.g., 3 for 3%), convert to decimal
            position_size = balance * (risk_per_trade_value / 100)
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
        elif risk_per_trade_mode == "percent":
            # User enters percentage (e.g., 3 for 3%), convert to decimal
            position_size = balance * (risk_per_trade_value / 100)
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
    risk_per_trade_mode: Literal["fixed", "percent", "actual"] = "fixed",
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
        risk_per_trade_mode: "fixed" (dollar amount), "percent" (of balance), or "actual" (use real trade values)
        risk_per_trade_value: Risk amount per trade (ignored if mode is "actual")
    
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
    equity_curve = [portfolio_start]  # Start with initial balance
    wins = 0
    losses = 0
    total_win_pnl = 0
    total_loss_pnl = 0
    
    # Max drawdown tracking
    peak_balance = portfolio_start
    max_drawdown = 0
    max_drawdown_pct = 0
    
    # Track skipped trades
    skipped_trades = []
    executed_trades_count = 0
    
    for i, trade in enumerate(trades, 1):
        trade_start_balance = balance
        
        # Calculate actual position value for this trade (what the original trader used)
        multiplier = get_asset_multiplier(trade.asset_type)
        actual_position_value = trade.open_price * trade.quantity * multiplier if trade.open_price else 0
        
        # Calculate simulated position size based on mode
        skip_reason = None
        sim_quantity = 0
        budget = 0  # Initialize budget
        
        if risk_per_trade_mode == "actual":
            # Use actual trade value from database - replicate real position sizes
            sim_position_size = actual_position_value
            sim_quantity = trade.quantity
        else:
            # Calculate budget based on mode
            if risk_per_trade_mode == "fixed":
                budget = min(risk_per_trade_value, balance)
            elif risk_per_trade_mode == "percent":
                # User enters percentage (e.g., 3 for 3%), convert to decimal
                budget = balance * (risk_per_trade_value / 100)
            else:
                budget = balance * risk_per_trade_value
            
            # Cap at 50% of balance for safety
            budget = min(budget, balance * 0.5)
            
            # Calculate affordable quantity based on actual trade price
            sim_quantity, sim_position_size, skip_reason = calculate_affordable_quantity(
                budget=budget,
                price_per_share=trade.open_price,
                asset_type=trade.asset_type
            )
        
        # Handle skipped trades
        if skip_reason:
            skipped_trades.append({
                'trade_num': i,
                'ticker': trade.ticker,
                'asset_type': trade.asset_type,
                'closed_at': trade.closed_at[:10] if trade.closed_at else '',
                'original_position': round(actual_position_value, 2),
                'required_budget': round(trade.open_price * multiplier, 2) if trade.open_price else 0,
                'available_budget': round(budget, 2),
                'reason': skip_reason,
                'missed_pnl_pct': round(trade.pnl_percent, 1)
            })
            # Don't update equity curve for skipped trades - just continue
            continue
        
        executed_trades_count += 1
        
        # Use actual P&L percent from the trade
        pnl_pct = trade.pnl_percent / 100  # Convert to decimal
        is_win = pnl_pct > 0  # Only positive P&L counts as win (breakeven = loss)
        
        trade_pnl = sim_position_size * pnl_pct
        balance += trade_pnl
        balance = max(0, balance)
        
        # Track equity curve
        equity_curve.append(round(balance, 2))
        
        # Update peak and drawdown
        if balance > peak_balance:
            peak_balance = balance
        current_drawdown = peak_balance - balance
        current_drawdown_pct = (current_drawdown / peak_balance * 100) if peak_balance > 0 else 0
        if current_drawdown > max_drawdown:
            max_drawdown = current_drawdown
            max_drawdown_pct = current_drawdown_pct
        
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
            'original_qty': trade.quantity,
            'sim_quantity': sim_quantity,
            'entry_price': round(trade.open_price, 4) if trade.open_price else 0,
            'actual_position_value': round(actual_position_value, 2),
            'actual_pnl_pct': round(trade.pnl_percent, 1),
            'actual_pnl': round(trade.pnl, 2),
            'start_balance': round(trade_start_balance, 2),
            'position_size': round(sim_position_size, 2),
            'result': 'WIN' if is_win else 'LOSS',
            'pnl_pct': round(pnl_pct * 100, 1),
            'trade_pnl': round(trade_pnl, 2),
            'end_balance': round(balance, 2),
            'cumulative_return_pct': round(((balance - portfolio_start) / portfolio_start) * 100, 1),
            'drawdown_pct': round(current_drawdown_pct, 1)
        })
    
    final_balance = balance
    total_profit = final_balance - portfolio_start
    total_return_pct = (total_profit / portfolio_start) * 100 if portfolio_start > 0 else 0
    total_trades = len(trades)
    
    # Calculate averages based on executed trades (not skipped)
    avg_win_pnl = total_win_pnl / wins if wins > 0 else 0
    avg_loss_pnl = total_loss_pnl / losses if losses > 0 else 0
    win_rate = (wins / executed_trades_count * 100) if executed_trades_count > 0 else 0
    
    # Calculate average simulated position size
    avg_sim_position = sum(t['position_size'] for t in trade_breakdown) / len(trade_breakdown) if trade_breakdown else 0
    
    # Get date range
    first_trade_date = trades[0].closed_at[:10] if trades else ''
    last_trade_date = trades[-1].closed_at[:10] if trades else ''
    
    # Calculate capital requirements from actual trade values
    max_position_value = max(actual_position_values) if actual_position_values else 0
    min_position_value = min(actual_position_values) if actual_position_values else 0
    sorted_values = sorted(actual_position_values)
    position_75th = sorted_values[int(len(sorted_values) * 0.75)] if sorted_values else 0
    
    # Capital requirement calculations based on user's portfolio
    min_portfolio_all_trades = max_position_value  # To take ALL trades (largest trade size)
    safe_position_25pct = portfolio_start * 0.25  # 25% of user's current portfolio
    recommended_portfolio = max_position_value * 4  # If user wants largest trade to be only 25%
    
    # Suggested position size based on trade history
    suggested_fixed_size = round(median_position_size / 100) * 100  # Round to nearest $100
    suggested_percent = round((median_position_size / recommended_portfolio) * 100, 1) if recommended_portfolio > 0 else 10
    
    # Generate recommendations
    recommendations = []
    
    # Portfolio size recommendation
    if portfolio_start < min_portfolio_all_trades:
        recommendations.append({
            'type': 'warning',
            'title': 'Portfolio Below Minimum',
            'message': f'Your portfolio ${portfolio_start:,.0f} is below the ${min_portfolio_all_trades:,.0f} largest trade from this {entity_type}. '
                      f'You may not be able to take all trades at their original sizes.'
        })
    
    recommendations.append({
        'type': 'suggestion',
        'title': 'Safe Position Size',
        'message': f'With your ${portfolio_start:,.0f} portfolio, a safe 25% max position is ${safe_position_25pct:,.0f}. '
                  f'Largest trade taken was ${min_portfolio_all_trades:,.0f}, median was ${median_position_size:,.0f}.'
    })
    
    # Position size recommendation
    recommendations.append({
        'type': 'info',
        'title': 'Suggested Position Size',
        'message': f'Based on this {entity_type}\'s trades: ${suggested_fixed_size:,.0f} fixed per trade, '
                  f'or {suggested_percent}% of portfolio. Median trade value was ${median_position_size:,.0f}.'
    })
    
    # Risk analysis
    if risk_per_trade_mode == 'fixed':
        max_consecutive_losses = int(portfolio_start / risk_per_trade_value) if risk_per_trade_value > 0 else 0
    else:
        max_consecutive_losses = int(1 / risk_per_trade_value) if risk_per_trade_value > 0 else 0
    
    recommendations.append({
        'type': 'info',
        'title': 'Risk Tolerance',
        'message': f'With current settings, portfolio can sustain {max_consecutive_losses} consecutive 100% losses before depletion.'
    })
    
    # Skipped trades warning
    if skipped_trades:
        skipped_count = len(skipped_trades)
        skipped_pct = (skipped_count / total_trades * 100) if total_trades > 0 else 0
        recommendations.append({
            'type': 'warning',
            'title': f'{skipped_count} Trades Skipped',
            'message': f'{skipped_count} of {total_trades} trades ({skipped_pct:.0f}%) were skipped because your position size budget couldn\'t afford them. '
                      f'Consider increasing your portfolio or position size %.'
        })
    
    # Win rate analysis
    if win_rate < 50:
        recommendations.append({
            'type': 'warning',
            'title': 'Win Rate Below 50%',
            'message': f'This {entity_type} has {win_rate:.1f}% win rate. Consider smaller position sizes or higher win rate targets.'
        })
    elif win_rate >= 70:
        recommendations.append({
            'type': 'success',
            'title': 'Strong Win Rate',
            'message': f'This {entity_type} has {win_rate:.1f}% win rate. Consider compound mode for accelerated growth.'
        })
    
    return {
        'success': True,
        'simulation_mode': 'exact_historical',
        'entity_type': entity_type,
        'entity_id': entity_id,
        'label': f'{entity_type.capitalize()}: {entity_id}',
        
        'capital_requirements': {
            'min_to_take_all_trades': round(min_portfolio_all_trades, 2),
            'safe_position_25pct': round(safe_position_25pct, 2),  # 25% of user's portfolio
            'recommended_portfolio': round(recommended_portfolio, 2),
            'max_trade_value': round(max_position_value, 2),
            'avg_trade_value': round(avg_position_size, 2),
            'min_trade_value': round(min_position_value, 2),
            'median_trade_value': round(median_position_size, 2),
            'user_portfolio': round(portfolio_start, 2),
        },
        
        'suggested_settings': {
            'fixed_position_size': suggested_fixed_size,
            'percent_position_size': suggested_percent,
            'recommended_portfolio': round(recommended_portfolio, 2),
            'based_on_trades': total_trades,
        },
        
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
            'risk_per_trade_value': risk_per_trade_value if risk_per_trade_mode in ['fixed', 'actual'] else round(risk_per_trade_value, 1),
            'risk_per_trade_display': f"${risk_per_trade_value:,.0f}" if risk_per_trade_mode == 'fixed' else (
                "Original trade sizes" if risk_per_trade_mode == 'actual' else f"{risk_per_trade_value}%"
            ),
        },
        
        'summary': {
            'final_balance': round(final_balance, 2),
            'total_profit': round(total_profit, 2),
            'total_return_pct': round(total_return_pct, 1),
            'total_trades': total_trades,
            'executed_trades': executed_trades_count,
            'skipped_trades': len(skipped_trades),
            'wins': wins,
            'losses': losses,
            'total_win_pnl': round(total_win_pnl, 2),
            'total_loss_pnl': round(total_loss_pnl, 2),
            'avg_win_dollar': round(avg_win_pnl, 2),
            'avg_loss_dollar': round(avg_loss_pnl, 2),
            'is_profitable': total_profit > 0,
            'avg_simulated_position': round(avg_sim_position, 2),
            'max_drawdown': round(max_drawdown, 2),
            'max_drawdown_pct': round(max_drawdown_pct, 1),
            'peak_balance': round(peak_balance, 2),
        },
        
        'equity_curve': equity_curve,
        'skipped_trades': skipped_trades,
        'recommendations': recommendations,
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


def run_risk_optimizer(
    entity_type: Literal["user", "channel"],
    entity_id: str,
    portfolio_start: float = DEFAULT_PORTFOLIO,
) -> Dict[str, Any]:
    """
    Run risk optimization by testing multiple position size percentages.
    
    Tests positions sizes at 1%, 2%, 3%, 5%, 10%, 15%, 20%, 25% and 
    recommends the optimal setting based on risk-adjusted returns.
    
    Args:
        entity_type: "user" or "channel"
        entity_id: Username or channel name
        portfolio_start: Starting portfolio value
    
    Returns:
        Dict with comparison table and recommendation
    """
    results = []
    
    for pct in RISK_OPTIMIZER_PERCENTAGES:
        result = run_exact_historical_simulation(
            entity_type=entity_type,
            entity_id=entity_id,
            portfolio_start=portfolio_start,
            risk_per_trade_mode="percent",
            risk_per_trade_value=pct
        )
        
        if not result.get('success'):
            return result  # Return error if simulation fails
        
        summary = result['summary']
        
        # Calculate risk-adjusted score (simplified Sharpe-like ratio)
        # Higher return with lower drawdown = better score
        total_return_pct = summary['total_return_pct']
        max_drawdown_pct = summary['max_drawdown_pct'] or 1  # Avoid division by zero
        risk_score = total_return_pct / max_drawdown_pct if max_drawdown_pct > 0 else total_return_pct
        
        results.append({
            'position_pct': pct,
            'final_balance': summary['final_balance'],
            'total_profit': summary['total_profit'],
            'total_return_pct': summary['total_return_pct'],
            'max_drawdown_pct': summary['max_drawdown_pct'],
            'executed_trades': summary['executed_trades'],
            'skipped_trades': summary['skipped_trades'],
            'wins': summary['wins'],
            'losses': summary['losses'],
            'win_rate': round(summary['wins'] / summary['executed_trades'] * 100, 1) if summary['executed_trades'] > 0 else 0,
            'avg_position': summary['avg_simulated_position'],
            'risk_score': round(risk_score, 2),
        })
    
    # Find best result (highest risk-adjusted score with reasonable execution)
    valid_results = [r for r in results if r['executed_trades'] > 0]
    if not valid_results:
        return {
            'success': False,
            'error': 'No trades could be executed at any position size. Portfolio too small.',
            'entity_type': entity_type,
            'entity_id': entity_id
        }
    
    # Sort by risk score descending
    sorted_results = sorted(valid_results, key=lambda x: x['risk_score'], reverse=True)
    best_result = sorted_results[0]
    
    # Check if ALL results are negative (no profitable sizing exists)
    all_negative = all(r['total_return_pct'] < 0 for r in valid_results)
    any_profitable = any(r['total_return_pct'] > 0 for r in valid_results)
    
    # Generate recommendation message
    if all_negative:
        recommendation_msg = f"WARNING: No position size yields positive returns with this trade history. {best_result['position_pct']}% is the LEAST BAD option (smallest loss ratio). Consider trading a different source or paper trading longer."
    elif any_profitable:
        recommendation_msg = f"Based on historical trades, {best_result['position_pct']}% position size offers the best risk-adjusted returns. "
        if best_result['skipped_trades'] > 0:
            recommendation_msg += f"Note: {best_result['skipped_trades']} trades would be skipped at this level."
    else:
        recommendation_msg = f"Breakeven result at {best_result['position_pct']}%. Consider paper trading longer to gather more data."
    
    return {
        'success': True,
        'entity_type': entity_type,
        'entity_id': entity_id,
        'portfolio_start': portfolio_start,
        'comparison': results,
        'recommended': best_result,
        'recommendation_message': recommendation_msg,
        'all_negative': all_negative,
        'any_profitable': any_profitable,
        'total_trades_in_history': results[0]['executed_trades'] + results[0]['skipped_trades'] if results else 0
    }


def run_recovery_calculator(
    entity_type: Literal["user", "channel"],
    entity_id: str,
    loss_amount: float,
    available_capital: float,
    target_recovery: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Calculate recovery timeline and probability for a trader who has lost money.
    
    Uses Monte Carlo simulation to estimate success probability and timeline.
    
    Args:
        entity_type: "user" or "channel"
        entity_id: Username or channel name
        loss_amount: Amount lost that user wants to recover
        available_capital: Current capital available for trading
        target_recovery: Target amount to recover (defaults to loss_amount)
    
    Returns:
        Dict with recovery projections for different risk profiles
    """
    if target_recovery is None:
        target_recovery = loss_amount
    
    # Fetch trade history
    if entity_type == "user":
        trades = fetch_user_trade_history(entity_id)
    else:
        trades = fetch_channel_trade_history(entity_id)
    
    if not trades:
        return {
            'success': False,
            'error': f'{entity_type.capitalize()} "{entity_id}" not found or has no trade history.',
            'entity_type': entity_type,
            'entity_id': entity_id
        }
    
    # Calculate trade frequency (trades per day)
    if len(trades) >= 2:
        first_date = datetime.fromisoformat(trades[0].closed_at[:10]) if trades[0].closed_at else datetime.now()
        last_date = datetime.fromisoformat(trades[-1].closed_at[:10]) if trades[-1].closed_at else datetime.now()
        days_span = max((last_date - first_date).days, 1)
        trades_per_day = len(trades) / days_span
    else:
        trades_per_day = 1  # Default
    
    # Extract P&L percentages for Monte Carlo
    pnl_percentages = [t.pnl_percent for t in trades]
    
    # Define risk profiles
    profiles = [
        {'name': 'Conservative', 'pct': 2, 'color': '#10b981'},
        {'name': 'Moderate', 'pct': 5, 'color': '#3b82f6'},
        {'name': 'Aggressive', 'pct': 10, 'color': '#ef4444'},
    ]
    
    profile_results = []
    
    for profile in profiles:
        pct = profile['pct']
        
        # Run deterministic simulation first
        det_result = run_exact_historical_simulation(
            entity_type=entity_type,
            entity_id=entity_id,
            portfolio_start=available_capital,
            risk_per_trade_mode="percent",
            risk_per_trade_value=pct
        )
        
        if not det_result.get('success'):
            continue
        
        # Monte Carlo simulation with proper affordability constraints
        success_count = 0
        total_trades_to_goal = []
        ruin_count = 0
        max_drawdowns_per_run = []  # Track max drawdown for each iteration
        skipped_in_mc = 0
        
        # Extract trade details for proper position sizing
        trade_details = [(t.pnl_percent, t.open_price, t.asset_type) for t in trades]
        
        for iteration in range(MONTE_CARLO_ITERATIONS):
            balance = available_capital
            peak = available_capital
            trades_count = 0
            skipped_this_run = 0
            max_drawdown_this_run = 0  # Reset per iteration
            target_balance = available_capital + target_recovery
            ruin_threshold = available_capital * 0.1  # 90% loss = ruin
            
            # Shuffle trade order for Monte Carlo (truly random - no fixed seed)
            shuffled_trades = trade_details.copy()
            random.shuffle(shuffled_trades)
            
            for pnl_pct, open_price, asset_type in shuffled_trades:
                if balance <= ruin_threshold:
                    ruin_count += 1
                    break
                
                # Calculate position budget with compounding
                budget = balance * (pct / 100)
                budget = min(budget, balance * 0.5)  # Cap at 50%
                
                # Use the shared calculate_affordable_quantity function
                sim_qty, actual_position, skip_reason = calculate_affordable_quantity(
                    budget=budget,
                    price_per_share=open_price,
                    asset_type=asset_type
                )
                
                if skip_reason:
                    # Skip this trade - can't afford
                    skipped_this_run += 1
                    continue
                
                trade_pnl = actual_position * (pnl_pct / 100)
                balance += trade_pnl
                balance = max(0, balance)
                trades_count += 1
                
                # Track peak and drawdown per iteration
                if balance > peak:
                    peak = balance
                drawdown = (peak - balance) / peak * 100 if peak > 0 else 0
                if drawdown > max_drawdown_this_run:
                    max_drawdown_this_run = drawdown
                
                if balance >= target_balance:
                    success_count += 1
                    total_trades_to_goal.append(trades_count)
                    break
            
            max_drawdowns_per_run.append(max_drawdown_this_run)
            skipped_in_mc += skipped_this_run
        
        # Calculate statistics
        success_probability = (success_count / MONTE_CARLO_ITERATIONS) * 100
        risk_of_ruin = (ruin_count / MONTE_CARLO_ITERATIONS) * 100
        avg_trades_to_goal = sum(total_trades_to_goal) / len(total_trades_to_goal) if total_trades_to_goal else len(trades) * 2
        
        # Calculate max drawdown as 95th percentile for realistic worst-case
        sorted_drawdowns = sorted(max_drawdowns_per_run)
        percentile_95_idx = int(len(sorted_drawdowns) * 0.95)
        max_dd_95th_percentile = sorted_drawdowns[percentile_95_idx] if sorted_drawdowns else 0
        
        # Estimate days to goal
        days_to_goal = avg_trades_to_goal / trades_per_day if trades_per_day > 0 else 999
        
        # Average skipped trades per run
        avg_skipped_per_run = skipped_in_mc / MONTE_CARLO_ITERATIONS
        
        profile_results.append({
            'profile': profile['name'],
            'position_pct': pct,
            'color': profile['color'],
            'success_probability': round(success_probability, 1),
            'risk_of_ruin': round(risk_of_ruin, 1),
            'avg_trades_to_goal': round(avg_trades_to_goal, 0),
            'estimated_days': round(days_to_goal, 0),
            'estimated_weeks': round(days_to_goal / 7, 1),
            'expected_final_balance': det_result['summary']['final_balance'],
            'max_drawdown_pct': round(max_dd_95th_percentile, 1),
            'skipped_trades': round(avg_skipped_per_run, 0),
        })
    
    # Find recommended profile (highest success probability with reasonable risk)
    valid_profiles = [p for p in profile_results if p['success_probability'] > 20]
    if valid_profiles:
        # Prefer moderate risk with good success rate
        recommended = max(valid_profiles, key=lambda x: x['success_probability'] - x['risk_of_ruin'])
    else:
        recommended = profile_results[0] if profile_results else None
    
    # Minimum capital calculation (binary search)
    min_capital = available_capital
    if recommended and recommended['success_probability'] < 50:
        # User needs more capital - estimate minimum
        for multiplier in [1.5, 2, 3, 5, 10]:
            test_capital = available_capital * multiplier
            # Simple estimate: more capital = higher success
            estimated_success = min(95, recommended['success_probability'] * multiplier * 0.5)
            if estimated_success >= 70:
                min_capital = test_capital
                break
    
    return {
        'success': True,
        'entity_type': entity_type,
        'entity_id': entity_id,
        'inputs': {
            'loss_amount': loss_amount,
            'available_capital': available_capital,
            'target_recovery': target_recovery,
        },
        'trade_stats': {
            'total_trades': len(trades),
            'trades_per_day': round(trades_per_day, 2),
            'win_rate': round(sum(1 for t in trades if t.pnl_percent > 0) / len(trades) * 100, 1),
            'avg_win_pct': round(mean([t.pnl_percent for t in trades if t.pnl_percent > 0]) if any(t.pnl_percent > 0 for t in trades) else 0, 1),
            'avg_loss_pct': round(mean([t.pnl_percent for t in trades if t.pnl_percent <= 0]) if any(t.pnl_percent <= 0 for t in trades) else 0, 1),
        },
        'profiles': profile_results,
        'recommended': recommended,
        'minimum_capital_for_70pct_success': round(min_capital, 2),
        'warning': 'Recovery target may be unrealistic' if (recommended and recommended['success_probability'] < 30) else None,
    }


def run_custom_trade_simulation(
    trades_data: List[Dict[str, Any]],
    portfolio_start: float = DEFAULT_PORTFOLIO,
    position_size_mode: Literal["fixed", "percent", "contract"] = "fixed",
    position_size_value: float = DEFAULT_RISK_VALUE,
    require_full_contract: bool = True,
    max_position_pct: float = 0.25,
    slippage_pct: float = 0.5,
    apply_pdt_rules: bool = False,
) -> Dict[str, Any]:
    """
    Run a simulation on custom trade data with trading standard rules.
    
    This function simulates portfolio growth using manually provided trade data,
    calculating minimum capital requirements, position sizing, and applying
    real-world trading constraints.
    
    Args:
        trades_data: List of trade dictionaries with:
            - symbol: Stock/option symbol
            - date: Trade date (YYYY-MM-DD)
            - trade_price: Total cost for 1 option contract (price * 100)
            - result: "WIN" or "LOSS"
            - return_pct: Return percentage (e.g., 22.5 for 22.5%)
        portfolio_start: Starting portfolio value
        position_size_mode: 
            - "fixed": Fixed dollar amount per trade
            - "percent": Percentage of current portfolio
            - "contract": Buy as many contracts as position allows
        position_size_value: Amount for position sizing
        require_full_contract: If True, skip trades if can't afford 1 contract
        max_position_pct: Maximum % of portfolio per single trade
        slippage_pct: Estimated slippage percentage (reduces gains, increases losses)
        apply_pdt_rules: Apply Pattern Day Trader rules ($25k minimum for 4+ day trades/week)
    
    Returns:
        Dict with simulation results and capital requirement analysis
    """
    if not trades_data:
        return {
            'success': False,
            'error': 'No trade data provided'
        }
    
    # Calculate capital requirements from trade data
    trade_prices = [float(t.get('trade_price', 0)) for t in trades_data if t.get('trade_price')]
    max_trade_price = max(trade_prices) if trade_prices else 0
    avg_trade_price = sum(trade_prices) / len(trade_prices) if trade_prices else 0
    min_trade_price = min(trade_prices) if trade_prices else 0
    
    # Calculate minimum portfolio requirements
    min_portfolio_all_trades = max_trade_price  # To take ALL trades
    min_portfolio_most_trades = sorted(trade_prices)[int(len(trade_prices) * 0.75)] if trade_prices else 0  # For 75% of trades
    recommended_portfolio = max_trade_price * 4  # 25% max position rule
    
    # PDT rule check
    pdt_minimum = 25000.0
    pdt_warning = None
    if apply_pdt_rules and portfolio_start < pdt_minimum:
        pdt_warning = f"Portfolio ${portfolio_start:,.2f} is below PDT minimum ${pdt_minimum:,.2f}. Limited to 3 day trades per 5 business days."
    
    # Run simulation
    balance = portfolio_start
    trade_breakdown = []
    skipped_trades = []
    wins = 0
    losses = 0
    total_win_pnl = 0
    total_loss_pnl = 0
    day_trades_this_week = 0
    current_week = None
    
    for i, trade in enumerate(trades_data, 1):
        symbol = trade.get('symbol', 'UNKNOWN')
        trade_date = trade.get('date', '')
        trade_price = float(trade.get('trade_price', 0))
        result = trade.get('result', 'LOSS').upper()
        return_pct = float(trade.get('return_pct', 0))
        
        trade_start_balance = balance
        
        # Calculate week for PDT tracking
        if trade_date:
            try:
                from datetime import datetime as dt
                trade_dt = dt.strptime(trade_date, '%Y-%m-%d')
                week_num = trade_dt.isocalendar()[1]
                if current_week != week_num:
                    current_week = week_num
                    day_trades_this_week = 0
            except:
                pass
        
        # Calculate position size based on mode
        if position_size_mode == "fixed":
            raw_position_size = position_size_value
        elif position_size_mode == "percent":
            raw_position_size = balance * (position_size_value / 100)
        else:  # contract mode
            if trade_price > 0:
                contracts = int(position_size_value)
                raw_position_size = trade_price * contracts
            else:
                raw_position_size = position_size_value
        
        # Apply max position limit
        max_position = balance * max_position_pct
        position_size = min(raw_position_size, max_position, balance)
        
        # Check if can afford trade
        can_afford = True
        skip_reason = None
        contracts_bought = 0
        
        if trade_price > 0:
            if require_full_contract:
                contracts_bought = int(position_size / trade_price)
                if contracts_bought < 1:
                    can_afford = False
                    skip_reason = f"Cannot afford 1 contract (${trade_price:,.0f} > ${position_size:,.0f} position)"
                else:
                    # Adjust position size to actual contracts
                    position_size = contracts_bought * trade_price
            else:
                # Fractional position (simulated)
                contracts_bought = position_size / trade_price if trade_price > 0 else 0
        else:
            contracts_bought = 1  # Stock trade
        
        # PDT check
        if apply_pdt_rules and portfolio_start < pdt_minimum and day_trades_this_week >= 3:
            can_afford = False
            skip_reason = "PDT limit reached (3 day trades this week)"
        
        if not can_afford:
            skipped_trades.append({
                'trade_num': i,
                'symbol': symbol,
                'date': trade_date,
                'trade_price': trade_price,
                'reason': skip_reason,
                'balance_at_skip': round(balance, 2)
            })
            trade_breakdown.append({
                'trade_num': i,
                'symbol': symbol,
                'date': trade_date,
                'trade_price': trade_price,
                'start_balance': round(trade_start_balance, 2),
                'position_size': 0,
                'contracts': 0,
                'result': 'SKIPPED',
                'return_pct': 0,
                'pnl': 0,
                'end_balance': round(balance, 2),
                'cumulative_return_pct': round(((balance - portfolio_start) / portfolio_start) * 100, 2),
                'skip_reason': skip_reason
            })
            continue
        
        # Apply slippage
        adjusted_return = return_pct
        if slippage_pct > 0:
            if return_pct > 0:
                adjusted_return = return_pct - slippage_pct  # Reduce gains
            elif return_pct < 0:
                adjusted_return = return_pct - slippage_pct  # Increase losses
        
        # Calculate P&L
        pnl = position_size * (adjusted_return / 100)
        balance += pnl
        balance = max(0, balance)
        
        is_win = result == 'WIN' and adjusted_return > 0
        if is_win:
            wins += 1
            total_win_pnl += pnl
        else:
            losses += 1
            total_loss_pnl += pnl
        
        day_trades_this_week += 1
        
        trade_breakdown.append({
            'trade_num': i,
            'symbol': symbol,
            'date': trade_date,
            'trade_price': trade_price,
            'start_balance': round(trade_start_balance, 2),
            'position_size': round(position_size, 2),
            'contracts': contracts_bought if isinstance(contracts_bought, int) else round(contracts_bought, 2),
            'result': result,
            'return_pct': round(adjusted_return, 2),
            'pnl': round(pnl, 2),
            'end_balance': round(balance, 2),
            'cumulative_return_pct': round(((balance - portfolio_start) / portfolio_start) * 100, 2)
        })
    
    # Calculate summary
    final_balance = balance
    total_profit = final_balance - portfolio_start
    total_return_pct = (total_profit / portfolio_start) * 100 if portfolio_start > 0 else 0
    executed_trades = [t for t in trade_breakdown if t['result'] != 'SKIPPED']
    
    avg_win_dollar = total_win_pnl / wins if wins > 0 else 0
    avg_loss_dollar = total_loss_pnl / losses if losses > 0 else 0
    win_rate = (wins / len(executed_trades) * 100) if executed_trades else 0
    
    # Generate recommendations
    recommendations = []
    
    if len(skipped_trades) > len(trades_data) * 0.3:
        recommendations.append({
            'type': 'warning',
            'title': 'High Skip Rate',
            'message': f'{len(skipped_trades)} of {len(trades_data)} trades ({len(skipped_trades)/len(trades_data)*100:.0f}%) were skipped. '
                      f'Consider increasing portfolio to ${min_portfolio_all_trades:,.0f} or position size to take all trades.'
        })
    
    if position_size_value < avg_trade_price and position_size_mode == 'fixed':
        recommendations.append({
            'type': 'info',
            'title': 'Position Size Below Average Trade',
            'message': f'Fixed position size ${position_size_value:,.0f} is below average trade price ${avg_trade_price:,.0f}. '
                      f'You may miss trades or need fractional positions.'
        })
    
    if portfolio_start < recommended_portfolio:
        recommendations.append({
            'type': 'suggestion',
            'title': 'Recommended Portfolio Size',
            'message': f'For 25% max position rule with these trades, recommended portfolio is ${recommended_portfolio:,.0f}. '
                      f'Current: ${portfolio_start:,.0f}'
        })
    
    if win_rate > 0:
        # Risk of ruin calculation (simplified)
        avg_risk = position_size_value if position_size_mode == 'fixed' else portfolio_start * (position_size_value / 100)
        max_consecutive_losses = int(portfolio_start / avg_risk) if avg_risk > 0 else 0
        recommendations.append({
            'type': 'info',
            'title': 'Risk Analysis',
            'message': f'With ${avg_risk:,.0f} per trade, portfolio can sustain {max_consecutive_losses} consecutive losses before depletion.'
        })
    
    return {
        'success': True,
        'simulation_mode': 'custom_trades',
        
        'capital_requirements': {
            'min_to_take_all_trades': round(max_trade_price, 2),
            'min_for_75pct_trades': round(min_portfolio_most_trades, 2),
            'recommended_portfolio': round(recommended_portfolio, 2),
            'max_trade_price': round(max_trade_price, 2),
            'avg_trade_price': round(avg_trade_price, 2),
            'min_trade_price': round(min_trade_price, 2),
            'pdt_minimum': pdt_minimum if apply_pdt_rules else None,
            'pdt_warning': pdt_warning
        },
        
        'params_used': {
            'portfolio_start': portfolio_start,
            'position_size_mode': position_size_mode,
            'position_size_value': position_size_value,
            'require_full_contract': require_full_contract,
            'max_position_pct': max_position_pct * 100,
            'slippage_pct': slippage_pct,
            'apply_pdt_rules': apply_pdt_rules
        },
        
        'summary': {
            'final_balance': round(final_balance, 2),
            'total_profit': round(total_profit, 2),
            'total_return_pct': round(total_return_pct, 2),
            'total_trades': len(trades_data),
            'executed_trades': len(executed_trades),
            'skipped_trades': len(skipped_trades),
            'wins': wins,
            'losses': losses,
            'win_rate': round(win_rate, 1),
            'total_win_pnl': round(total_win_pnl, 2),
            'total_loss_pnl': round(total_loss_pnl, 2),
            'avg_win_dollar': round(avg_win_dollar, 2),
            'avg_loss_dollar': round(avg_loss_dollar, 2),
            'is_profitable': total_profit > 0
        },
        
        'recommendations': recommendations,
        'trade_breakdown': trade_breakdown,
        'skipped_trades': skipped_trades
    }
