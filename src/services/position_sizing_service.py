"""
PositionSizingService - Proportional position sizing for copy trading

Provides three sizing modes:
1. Mirror (proportional) - Match analyst's portfolio percentage
2. Fixed Dollar - Use fixed dollar amount per trade
3. Fixed Contracts - Use raw analyst quantity (current behavior)

Handles both entry and exit scaling with ratio tracking.
"""

import math
from datetime import datetime
from typing import Dict, Optional, Any
from dataclasses import dataclass


@dataclass
class SizingResult:
    scaled_qty: int
    sizing_mode: str
    analyst_portfolio: Optional[float]
    analyst_qty: int
    analyst_position_pct: Optional[float]
    user_portfolio: Optional[float]
    user_position_pct: Optional[float]
    cost_basis: float
    capped: bool
    cap_reason: Optional[str]
    details: Dict[str, Any]


@dataclass
class ExitSizingResult:
    exit_qty: int
    exit_ratio: float
    user_entry_qty: int
    remaining_after: int
    details: Dict[str, Any]


class PositionSizingService:
    
    SIZING_MODES = ['mirror', 'fixed_dollar', 'fixed_contracts']
    
    def __init__(self, db):
        self.db = db
    
    def get_analyst_portfolio(self, channel_id: str) -> Optional[float]:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT portfolio_value FROM analyst_portfolios WHERE channel_id = ?',
            (str(channel_id),)
        )
        row = cursor.fetchone()
        return row['portfolio_value'] if row else None
    
    def get_sizing_settings(self, channel_id: str) -> Dict[str, Any]:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            'SELECT * FROM user_sizing_settings WHERE channel_id = ?',
            (str(channel_id),)
        )
        channel_settings = cursor.fetchone()
        
        if channel_settings:
            return dict(channel_settings)
        
        cursor.execute(
            'SELECT * FROM user_sizing_settings WHERE is_global = 1'
        )
        global_settings = cursor.fetchone()
        
        if global_settings:
            return dict(global_settings)
        
        return {
            'sizing_mode': 'fixed_contracts',
            'fixed_dollar_amount': None,
            'fixed_contracts': None,
            'max_position_pct': 25.0,
            'min_contracts': 1,
            'max_contracts': None,
            'user_portfolio_value': None
        }
    
    def calculate_entry_quantity(
        self,
        channel_id: str,
        analyst_qty: int,
        signal_price: float,
        asset_type: str = 'option',
        signal_detected_at: Optional[datetime] = None
    ) -> SizingResult:
        settings = self.get_sizing_settings(channel_id)
        analyst_portfolio = self.get_analyst_portfolio(channel_id)
        
        sizing_mode = settings.get('sizing_mode', 'fixed_contracts')
        user_portfolio = settings.get('user_portfolio_value')
        max_position_pct = settings.get('max_position_pct', 25.0)
        min_contracts = settings.get('min_contracts', 1)
        max_contracts = settings.get('max_contracts')
        fixed_dollar = settings.get('fixed_dollar_amount')
        fixed_qty = settings.get('fixed_contracts')
        
        multiplier = 100 if asset_type == 'option' else 1
        analyst_cost = analyst_qty * signal_price * multiplier
        
        analyst_position_pct = None
        if analyst_portfolio and analyst_portfolio > 0:
            analyst_position_pct = (analyst_cost / analyst_portfolio) * 100
        
        scaled_qty = analyst_qty
        capped = False
        cap_reason = None
        user_position_pct = None
        cost_basis = analyst_cost
        
        if sizing_mode == 'mirror':
            if analyst_portfolio and analyst_portfolio > 0 and user_portfolio and user_portfolio > 0:
                target_cost = (analyst_position_pct / 100) * user_portfolio
                
                if max_position_pct and max_position_pct > 0:
                    max_cost = (max_position_pct / 100) * user_portfolio
                    if target_cost > max_cost:
                        target_cost = max_cost
                        capped = True
                        cap_reason = f'max_position_pct={max_position_pct}%'
                
                scaled_qty = max(1, int(target_cost / (signal_price * multiplier)))
                cost_basis = scaled_qty * signal_price * multiplier
                user_position_pct = (cost_basis / user_portfolio) * 100
            else:
                scaled_qty = analyst_qty
                cap_reason = 'missing_portfolio_values'
        
        elif sizing_mode == 'fixed_dollar':
            if fixed_dollar and fixed_dollar > 0:
                scaled_qty = max(1, int(fixed_dollar / (signal_price * multiplier)))
                cost_basis = scaled_qty * signal_price * multiplier
                
                if user_portfolio and user_portfolio > 0:
                    user_position_pct = (cost_basis / user_portfolio) * 100
                    if max_position_pct and user_position_pct > max_position_pct:
                        max_cost = (max_position_pct / 100) * user_portfolio
                        scaled_qty = max(1, int(max_cost / (signal_price * multiplier)))
                        cost_basis = scaled_qty * signal_price * multiplier
                        user_position_pct = (cost_basis / user_portfolio) * 100
                        capped = True
                        cap_reason = f'max_position_pct={max_position_pct}%'
            else:
                scaled_qty = analyst_qty
                cap_reason = 'fixed_dollar_not_set'
        
        elif sizing_mode == 'fixed_contracts':
            if fixed_qty and fixed_qty > 0:
                scaled_qty = fixed_qty
            else:
                scaled_qty = analyst_qty
            cost_basis = scaled_qty * signal_price * multiplier
            if user_portfolio and user_portfolio > 0:
                user_position_pct = (cost_basis / user_portfolio) * 100
        
        if min_contracts and scaled_qty < min_contracts:
            scaled_qty = min_contracts
            cost_basis = scaled_qty * signal_price * multiplier
        
        if max_contracts and scaled_qty > max_contracts:
            scaled_qty = max_contracts
            cost_basis = scaled_qty * signal_price * multiplier
            capped = True
            cap_reason = f'max_contracts={max_contracts}'
        
        return SizingResult(
            scaled_qty=scaled_qty,
            sizing_mode=sizing_mode,
            analyst_portfolio=analyst_portfolio,
            analyst_qty=analyst_qty,
            analyst_position_pct=analyst_position_pct,
            user_portfolio=user_portfolio,
            user_position_pct=user_position_pct,
            cost_basis=round(cost_basis, 2),
            capped=capped,
            cap_reason=cap_reason,
            details={
                'signal_price': signal_price,
                'asset_type': asset_type,
                'multiplier': multiplier,
                'settings': settings
            }
        )
    
    def calculate_exit_quantity(
        self,
        channel_id: str,
        user_entry_qty: int,
        analyst_exit_qty: int,
        analyst_entry_qty: int
    ) -> ExitSizingResult:
        if analyst_entry_qty <= 0:
            return ExitSizingResult(
                exit_qty=user_entry_qty,
                exit_ratio=1.0,
                user_entry_qty=user_entry_qty,
                remaining_after=0,
                details={'reason': 'invalid_analyst_entry_qty', 'full_exit': True}
            )
        
        exit_ratio = min(1.0, analyst_exit_qty / analyst_entry_qty)
        
        exit_qty = max(1, round(user_entry_qty * exit_ratio))
        
        if exit_qty > user_entry_qty:
            exit_qty = user_entry_qty
        
        remaining_after = user_entry_qty - exit_qty
        
        return ExitSizingResult(
            exit_qty=exit_qty,
            exit_ratio=round(exit_ratio, 4),
            user_entry_qty=user_entry_qty,
            remaining_after=remaining_after,
            details={
                'analyst_exit_qty': analyst_exit_qty,
                'analyst_entry_qty': analyst_entry_qty,
                'calculated_exit': user_entry_qty * exit_ratio,
                'rounded_to': exit_qty
            }
        )
    
    def save_analyst_portfolio(
        self,
        channel_id: str,
        portfolio_value: float,
        source: str = 'manual',
        notes: str = None
    ) -> bool:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO analyst_portfolios (channel_id, portfolio_value, source, notes, last_updated)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(channel_id) DO UPDATE SET
                    portfolio_value = excluded.portfolio_value,
                    source = excluded.source,
                    notes = excluded.notes,
                    last_updated = CURRENT_TIMESTAMP
            ''', (str(channel_id), portfolio_value, source, notes))
            conn.commit()
            return True
        except Exception as e:
            print(f"[SIZING] Error saving analyst portfolio: {e}")
            return False
    
    def save_sizing_settings(
        self,
        channel_id: Optional[str],
        sizing_mode: str,
        fixed_dollar_amount: Optional[float] = None,
        fixed_contracts: Optional[int] = None,
        max_position_pct: float = 25.0,
        min_contracts: int = 1,
        max_contracts: Optional[int] = None,
        user_portfolio_value: Optional[float] = None
    ) -> bool:
        if sizing_mode not in self.SIZING_MODES:
            raise ValueError(f"Invalid sizing mode: {sizing_mode}")
        
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        is_global = 1 if channel_id is None else 0
        
        try:
            if is_global:
                cursor.execute('''
                    UPDATE user_sizing_settings SET
                        sizing_mode = ?,
                        fixed_dollar_amount = ?,
                        fixed_contracts = ?,
                        max_position_pct = ?,
                        min_contracts = ?,
                        max_contracts = ?,
                        user_portfolio_value = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE is_global = 1
                ''', (sizing_mode, fixed_dollar_amount, fixed_contracts,
                      max_position_pct, min_contracts, max_contracts, user_portfolio_value))
            else:
                cursor.execute('''
                    INSERT INTO user_sizing_settings 
                    (channel_id, sizing_mode, fixed_dollar_amount, fixed_contracts,
                     max_position_pct, min_contracts, max_contracts, user_portfolio_value, is_global)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                    ON CONFLICT(channel_id) DO UPDATE SET
                        sizing_mode = excluded.sizing_mode,
                        fixed_dollar_amount = excluded.fixed_dollar_amount,
                        fixed_contracts = excluded.fixed_contracts,
                        max_position_pct = excluded.max_position_pct,
                        min_contracts = excluded.min_contracts,
                        max_contracts = excluded.max_contracts,
                        user_portfolio_value = excluded.user_portfolio_value,
                        updated_at = CURRENT_TIMESTAMP
                ''', (str(channel_id), sizing_mode, fixed_dollar_amount, fixed_contracts,
                      max_position_pct, min_contracts, max_contracts, user_portfolio_value))
            
            conn.commit()
            return True
        except Exception as e:
            print(f"[SIZING] Error saving sizing settings: {e}")
            return False


def get_position_sizing_service(db) -> PositionSizingService:
    return PositionSizingService(db)
