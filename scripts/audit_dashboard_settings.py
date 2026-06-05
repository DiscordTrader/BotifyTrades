#!/usr/bin/env python3
"""
Dashboard Settings Audit
=========================
Validates consistency of dashboard settings including:
- Channel configurations (execute_enabled, track_enabled)
- Trade tracking from signal to database
- PNL calculations and tracking
- Leaderboard data integrity

Run: python scripts/audit_dashboard_settings.py
"""
import sys
import os
from pathlib import Path
from typing import Dict, List, Tuple, Any
from dataclasses import dataclass, field
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))

@dataclass
class AuditResult:
    category: str
    check: str
    status: str  # PASS, WARN, FAIL
    message: str
    details: List[str] = field(default_factory=list)

class DashboardAudit:
    def __init__(self):
        self.results: List[AuditResult] = []
        self.db = None
        
    def _load_db(self) -> bool:
        try:
            from gui_app import database as db
            self.db = db
            return True
        except ImportError as e:
            self.results.append(AuditResult(
                category="Setup",
                check="Database Import",
                status="FAIL",
                message=f"Could not import database: {e}"
            ))
            return False
    
    def run_all_audits(self) -> Dict[str, Any]:
        if not self._load_db():
            return self._summarize()
        
        self._audit_channel_configurations()
        self._audit_trade_channel_consistency()
        self._audit_pnl_calculations()
        self._audit_leaderboard_data()
        self._audit_orphan_trades()
        self._audit_lot_matching()
        
        return self._summarize()
    
    def _audit_channel_configurations(self):
        """Check channel configurations are valid."""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, discord_channel_id, name, category, execute_enabled, track_enabled, is_active
            FROM channels
        ''')
        channels = cursor.fetchall()
        
        issues = []
        valid_count = 0
        
        for ch in channels:
            ch_id, discord_id, name, category, execute, track, active = ch
            
            if not execute and not track and active:
                issues.append(f"Channel '{name}' (ID:{discord_id}) is active but neither execute nor track enabled")
            
            if execute and not track:
                pass
            
            if execute and track:
                valid_count += 1
            elif execute or track:
                valid_count += 1
            
            if category in ('EXECUTE', 'TRACK') and not (execute or track):
                issues.append(f"Channel '{name}' has legacy category='{category}' but no mode flags set")
        
        if issues:
            self.results.append(AuditResult(
                category="Channels",
                check="Configuration Validity",
                status="WARN",
                message=f"{len(issues)} configuration issues found",
                details=issues[:10]
            ))
        else:
            self.results.append(AuditResult(
                category="Channels",
                check="Configuration Validity",
                status="PASS",
                message=f"All {len(channels)} channels properly configured"
            ))
    
    def _audit_trade_channel_consistency(self):
        """Check trades have valid channel references."""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT t.id, t.symbol, t.channel_id, t.status, c.name
            FROM trades t
            LEFT JOIN channels c ON t.channel_id = c.discord_channel_id
            WHERE t.channel_id IS NOT NULL AND t.channel_id != '' AND c.id IS NULL
        ''')
        orphan_trades = cursor.fetchall()
        
        cursor.execute('SELECT COUNT(*) FROM trades WHERE channel_id IS NOT NULL')
        total_with_channel = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM trades WHERE channel_id IS NULL')
        total_without_channel = cursor.fetchone()[0]
        
        if orphan_trades:
            self.results.append(AuditResult(
                category="Trades",
                check="Channel References",
                status="WARN",
                message=f"{len(orphan_trades)} trades reference deleted channels",
                details=[f"Trade #{t[0]} ({t[1]}) -> channel_id={t[2]}" for t in orphan_trades[:5]]
            ))
        else:
            self.results.append(AuditResult(
                category="Trades",
                check="Channel References",
                status="PASS",
                message=f"All {total_with_channel} trades with channels are valid ({total_without_channel} without)"
            ))
    
    def _audit_pnl_calculations(self):
        """Check PNL calculations are consistent."""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, symbol, quantity, executed_price, current_price, pnl, pnl_percent, status, asset_type
            FROM trades
            WHERE status = 'CLOSED' AND executed_price > 0 AND quantity > 0
            LIMIT 100
        ''')
        closed_trades = cursor.fetchall()
        
        issues = []
        for trade in closed_trades:
            t_id, symbol, qty, exec_price, current_price, pnl, pnl_pct, status, asset_type = trade
            
            if current_price and current_price > 0 and exec_price and exec_price > 0:
                multiplier = 100 if asset_type == 'option' else 1
                expected_pnl = (current_price - exec_price) * qty * multiplier
                
                if pnl and abs(pnl - expected_pnl) > 1.0:
                    issues.append(f"Trade #{t_id} ({symbol}): PNL ${pnl:.2f} != expected ${expected_pnl:.2f}")
        
        if issues:
            self.results.append(AuditResult(
                category="PNL",
                check="Calculation Consistency",
                status="WARN",
                message=f"{len(issues)} PNL calculation discrepancies",
                details=issues[:5]
            ))
        else:
            self.results.append(AuditResult(
                category="PNL",
                check="Calculation Consistency",
                status="PASS",
                message=f"Checked {len(closed_trades)} closed trades - calculations consistent"
            ))
    
    def _audit_leaderboard_data(self):
        """Check leaderboard data integrity."""
        try:
            leaderboard = self.db.get_channel_leaderboard(time_period='all')
            
            issues = []
            for entry in leaderboard:
                total_closed = entry.get('total_closed', 0)
                wins = entry.get('win_count', 0)
                losses = entry.get('loss_count', 0)
                
                if wins + losses != total_closed:
                    issues.append(f"Channel '{entry.get('channel_name')}': wins({wins}) + losses({losses}) != total({total_closed})")
                
                tqs = entry.get('trader_quality_score', 0)
                if not 0 <= tqs <= 100:
                    issues.append(f"Channel '{entry.get('channel_name')}': TQS {tqs} out of range [0-100]")
            
            if issues:
                self.results.append(AuditResult(
                    category="Leaderboard",
                    check="Data Integrity",
                    status="WARN",
                    message=f"{len(issues)} leaderboard data issues",
                    details=issues[:5]
                ))
            else:
                self.results.append(AuditResult(
                    category="Leaderboard",
                    check="Data Integrity",
                    status="PASS",
                    message=f"All {len(leaderboard)} channel entries valid"
                ))
        except Exception as e:
            self.results.append(AuditResult(
                category="Leaderboard",
                check="Data Integrity",
                status="FAIL",
                message=f"Could not fetch leaderboard: {e}"
            ))
    
    def _audit_orphan_trades(self):
        """Check trades have valid source references."""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT COUNT(*) FROM trades WHERE source IS NULL OR source = ''
            ''')
            no_source = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM trades')
            total = cursor.fetchone()[0]
            
            if no_source > total * 0.5:
                self.results.append(AuditResult(
                    category="Trades",
                    check="Source Attribution",
                    status="WARN",
                    message=f"{no_source}/{total} trades have no source attribution"
                ))
            else:
                self.results.append(AuditResult(
                    category="Trades",
                    check="Source Attribution",
                    status="PASS",
                    message=f"{total - no_source}/{total} trades have source attribution"
                ))
        except Exception as e:
            self.results.append(AuditResult(
                category="Trades",
                check="Source Attribution",
                status="WARN",
                message=f"Could not check source attribution: {e}"
            ))
    
    def _audit_lot_matching(self):
        """Check FIFO lot matching consistency."""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT COUNT(*) FROM signal_lots WHERE status = 'OPEN' AND remaining_qty < 0
            ''')
            negative_qty = cursor.fetchone()[0]
            
            cursor.execute('''
                SELECT COUNT(*) FROM signal_lots WHERE status = 'CLOSED' AND remaining_qty > 0
            ''')
            closed_with_remaining = cursor.fetchone()[0]
            
            issues = []
            if negative_qty > 0:
                issues.append(f"{negative_qty} lots have negative remaining quantity")
            if closed_with_remaining > 0:
                issues.append(f"{closed_with_remaining} closed lots still have remaining quantity")
            
            if issues:
                self.results.append(AuditResult(
                    category="Lot Matching",
                    check="FIFO Consistency",
                    status="WARN",
                    message=f"{len(issues)} lot matching issues",
                    details=issues
                ))
            else:
                cursor.execute('SELECT COUNT(*) FROM signal_lots')
                total_lots = cursor.fetchone()[0]
                self.results.append(AuditResult(
                    category="Lot Matching",
                    check="FIFO Consistency",
                    status="PASS",
                    message=f"All {total_lots} lots have valid quantities"
                ))
        except Exception as e:
            self.results.append(AuditResult(
                category="Lot Matching",
                check="FIFO Consistency",
                status="WARN",
                message=f"Could not check lot matching: {e}"
            ))
    
    def _summarize(self) -> Dict[str, Any]:
        passed = sum(1 for r in self.results if r.status == "PASS")
        warnings = sum(1 for r in self.results if r.status == "WARN")
        failed = sum(1 for r in self.results if r.status == "FAIL")
        
        return {
            'passed': passed,
            'warnings': warnings,
            'failed': failed,
            'total': len(self.results),
            'results': self.results
        }
    
    def print_report(self):
        summary = self.run_all_audits()
        
        print("\n" + "=" * 60)
        print("DASHBOARD SETTINGS AUDIT REPORT")
        print("=" * 60)
        
        status_icons = {"PASS": "✓", "WARN": "⚠", "FAIL": "✗"}
        
        current_category = None
        for result in self.results:
            if result.category != current_category:
                print(f"\n[{result.category}]")
                current_category = result.category
            
            icon = status_icons.get(result.status, "?")
            print(f"  {icon} {result.check}: {result.message}")
            
            for detail in result.details:
                print(f"      - {detail}")
        
        print("\n" + "-" * 60)
        print(f"SUMMARY: {summary['passed']} passed, {summary['warnings']} warnings, {summary['failed']} failed")
        print("-" * 60)
        
        return summary['failed'] == 0 and summary['warnings'] <= 3


def main():
    audit = DashboardAudit()
    success = audit.print_report()
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
