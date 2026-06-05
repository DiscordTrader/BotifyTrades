#!/usr/bin/env python3
"""
BotifyTrades System Validation Script
Run from shell: python scripts/validate_system.py
"""

import sys
import os
import sqlite3
import json
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

DB_PATH = os.path.join(PROJECT_ROOT, 'bot_data.db')

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'

def ok(msg): print(f"{Colors.GREEN}✓{Colors.END} {msg}")
def fail(msg): print(f"{Colors.RED}✗{Colors.END} {msg}")
def warn(msg): print(f"{Colors.YELLOW}⚠{Colors.END} {msg}")
def info(msg): print(f"{Colors.BLUE}ℹ{Colors.END} {msg}")
def header(msg): print(f"\n{Colors.BOLD}{'='*60}\n{msg}\n{'='*60}{Colors.END}")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def check_database():
    header("DATABASE CHECKS")
    errors = 0
    
    if not os.path.exists(DB_PATH):
        fail(f"Database file not found: {DB_PATH}")
        return 1
    ok(f"Database file exists: {DB_PATH}")
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        required_tables = [
            'channels', 'signals', 'trades', 'signal_lots', 'lot_closures',
            'settings', 'synced_orders', 'trade_monitor_settings', 'webhook_channels'
        ]
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        existing = {row[0] for row in cursor.fetchall()}
        
        for table in required_tables:
            if table in existing:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                ok(f"Table '{table}' exists ({count} rows)")
            else:
                fail(f"Table '{table}' MISSING")
                errors += 1
        
        conn.close()
    except Exception as e:
        fail(f"Database error: {e}")
        errors += 1
    
    return errors

def check_channels():
    header("CHANNEL CONFIGURATION CHECKS")
    errors = 0
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT discord_channel_id, name, category, execute_enabled, track_enabled, is_active, broker_override
            FROM channels
        """)
        channels = cursor.fetchall()
        
        info(f"Total channels configured: {len(channels)}")
        
        execute_count = 0
        track_count = 0
        mismatch_count = 0
        
        for ch in channels:
            ch_id, name, category, exec_en, track_en, is_active, broker = ch
            
            if exec_en == 1 and category != 'EXECUTE':
                fail(f"MISMATCH: '{name}' has execute_enabled=1 but category='{category}'")
                errors += 1
                mismatch_count += 1
            elif track_en == 1 and exec_en == 0 and category != 'TRACK':
                fail(f"MISMATCH: '{name}' has track_enabled=1 but category='{category}'")
                errors += 1
                mismatch_count += 1
            
            if exec_en == 1:
                execute_count += 1
                status = "ACTIVE" if is_active else "INACTIVE"
                broker_str = broker if broker else "default"
                ok(f"EXECUTE: {name} [{status}] -> {broker_str}")
            elif track_en == 1:
                track_count += 1
                ok(f"TRACK: {name}")
        
        if mismatch_count == 0:
            ok("All channel category/execute_enabled flags are synchronized")
        
        info(f"Summary: {execute_count} execution, {track_count} tracking channels")
        
        conn.close()
    except Exception as e:
        fail(f"Channel check error: {e}")
        errors += 1
    
    return errors

def check_broker_credentials():
    header("BROKER CREDENTIALS CHECKS")
    errors = 0
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        brokers_config = {
            'webull': 'webull_credentials',
            'alpaca': 'alpaca_credentials',
            'tastytrade': 'tastytrade_credentials',
            'robinhood': 'robinhood_credentials',
            'ibkr': 'ibkr_credentials'
        }
        
        brokers_settings = {
            'webull': ['webull_email', 'webull_password'],
            'alpaca': ['alpaca_api_key', 'alpaca_secret_key'],
            'tastytrade': ['tastytrade_username'],
            'robinhood': ['robinhood_username'],
            'ibkr': ['ibkr_host']
        }
        
        for broker, config_key in brokers_config.items():
            has_creds = False
            
            cursor.execute("SELECT value_encrypted FROM config WHERE key = ?", (config_key,))
            row = cursor.fetchone()
            if row and row[0] and len(str(row[0])) > 20:
                has_creds = True
                ok(f"{broker.upper()}: Credentials configured (encrypted)")
            
            if not has_creds and broker in brokers_settings:
                for key in brokers_settings[broker]:
                    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
                    row = cursor.fetchone()
                    if row and row[0]:
                        has_creds = True
                        ok(f"{broker.upper()}: Credentials in settings")
                        break
            
            if not has_creds:
                warn(f"{broker.upper()}: No credentials found")
        
        conn.close()
    except Exception as e:
        fail(f"Broker credentials check error: {e}")
        errors += 1
    
    return errors

def check_discord_settings():
    header("DISCORD SETTINGS CHECKS")
    errors = 0
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("SELECT key, value_encrypted FROM config WHERE key LIKE '%discord%' OR key LIKE '%token%'")
        discord_configs = cursor.fetchall()
        
        token_found = False
        for key, value in discord_configs:
            if value and len(value) > 50:
                ok(f"Discord config '{key}': Configured (encrypted)")
                token_found = True
        
        if not token_found:
            cursor.execute("SELECT token FROM discord_settings LIMIT 1")
            row = cursor.fetchone()
            if row and row[0] and len(str(row[0])) > 50:
                ok("Discord token configured in discord_settings")
                token_found = True
        
        if not token_found:
            warn("Discord token may be configured elsewhere or in environment")
        
        cursor.execute("SELECT COUNT(*) FROM channels WHERE is_active = 1")
        active = cursor.fetchone()[0]
        if active > 0:
            ok(f"Active monitored channels: {active}")
        else:
            warn("No active channels configured")
        
        conn.close()
    except Exception as e:
        fail(f"Discord settings check error: {e}")
        errors += 1
    
    return errors

def check_trade_monitor():
    header("TRADE MONITOR CHECKS")
    errors = 0
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM trade_monitor_settings WHERE id = 1")
        row = cursor.fetchone()
        
        if row:
            settings = dict(row)
            if settings.get('enabled'):
                ok("Trade Monitor: ENABLED")
                info(f"  Poll interval: {settings.get('poll_interval_seconds', 10)}s")
                info(f"  Include stocks: {bool(settings.get('include_stocks'))}")
                info(f"  Include options: {bool(settings.get('include_options'))}")
                info(f"  Post BTO: {bool(settings.get('post_bto_signals'))}")
                info(f"  Post STC: {bool(settings.get('post_stc_signals'))}")
                
                target = settings.get('target_webhook_channel_id')
                if target:
                    ok(f"  Target webhook channel: {target}")
                else:
                    warn("  No target webhook channel configured")
            else:
                info("Trade Monitor: DISABLED")
        else:
            warn("Trade Monitor settings not initialized")
        
        cursor.execute("SELECT COUNT(*) FROM synced_orders")
        synced = cursor.fetchone()[0]
        info(f"Synced orders in database: {synced}")
        
        conn.close()
    except Exception as e:
        fail(f"Trade Monitor check error: {e}")
        errors += 1
    
    return errors

def check_signal_patterns():
    header("SIGNAL PATTERN CHECKS")
    errors = 0
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("SELECT value FROM settings WHERE key = 'option_signal_pattern'")
        row = cursor.fetchone()
        if row and row[0]:
            ok(f"Option pattern configured: {row[0][:50]}...")
        else:
            warn("Option pattern using default")
        
        cursor.execute("SELECT value FROM settings WHERE key = 'stock_signal_pattern'")
        row = cursor.fetchone()
        if row and row[0]:
            ok(f"Stock pattern configured: {row[0][:50]}...")
        else:
            warn("Stock pattern using default")
        
        test_signals = [
            ("BTO 10 AAPL 200C 12/26 @ 2.61", "Standard BTO"),
            ("STC 5 SPY 600P 1/16 @ 1.50", "Standard STC"),
            ("BTO 100 MDB 430p 12/26 @ 1.85", "With quantity"),
        ]
        
        import re
        pattern_str = row[0] if row and row[0] else r'(?:^|\s)(BTO|STC)\s+(?:(\d+)\s+)?\$?([A-Za-z]+)\s+\$?([\d.]+)\s*([CPcp])\s*(\d{1,2}/\d{1,2})\s*@?\s*([\d.]+|[mM])'
        
        try:
            pattern = re.compile(pattern_str, re.IGNORECASE)
            info("Testing signal patterns:")
            for signal, desc in test_signals:
                match = pattern.search(signal)
                if match:
                    ok(f"  '{signal}' -> MATCHED ({desc})")
                else:
                    warn(f"  '{signal}' -> NO MATCH ({desc})")
        except Exception as e:
            fail(f"Pattern compilation error: {e}")
            errors += 1
        
        conn.close()
    except Exception as e:
        fail(f"Signal pattern check error: {e}")
        errors += 1
    
    return errors

def check_webhook_channels():
    header("WEBHOOK CHANNEL CHECKS")
    errors = 0
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("SELECT id, name, webhook_url, enabled FROM webhook_channels")
        webhooks = cursor.fetchall()
        
        if webhooks:
            for wh in webhooks:
                wh_id, name, url, enabled = wh
                status = "ENABLED" if enabled else "DISABLED"
                if url and 'discord.com/api/webhooks' in url:
                    ok(f"Webhook '{name}': {status}")
                else:
                    warn(f"Webhook '{name}': Invalid URL format")
        else:
            info("No webhook channels configured")
        
        cursor.execute("SELECT COUNT(*) FROM channel_mappings WHERE is_active = 1")
        mappings = cursor.fetchone()[0]
        info(f"Active channel->webhook mappings: {mappings}")
        
        conn.close()
    except Exception as e:
        fail(f"Webhook check error: {e}")
        errors += 1
    
    return errors

def check_risk_management():
    header("RISK MANAGEMENT CHECKS")
    errors = 0
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("SELECT value FROM settings WHERE key = 'risk_management_enabled'")
        row = cursor.fetchone()
        global_enabled = row and row[0] == '1'
        
        if global_enabled:
            ok("Global risk management: ENABLED")
        else:
            info("Global risk management: DISABLED")
        
        cursor.execute("""
            SELECT name, profit_target_1_pct, profit_target_2_pct, profit_target_3_pct, 
                   stop_loss_pct, trailing_stop_pct, risk_management_enabled
            FROM channels WHERE risk_management_enabled = 1
        """)
        risk_channels = cursor.fetchall()
        
        if risk_channels:
            info(f"Channels with per-channel risk management: {len(risk_channels)}")
            for ch in risk_channels:
                name, tp1, tp2, tp3, sl, ts, _ = ch
                ok(f"  {name}: TP={tp1}/{tp2}/{tp3}% SL={sl}% TS={ts}%")
        else:
            info("No channels have per-channel risk management enabled")
        
        conn.close()
    except Exception as e:
        fail(f"Risk management check error: {e}")
        errors += 1
    
    return errors

def check_environment():
    header("ENVIRONMENT CHECKS")
    errors = 0
    
    env_vars = [
        ('OPENAI_API_KEY', False),
        ('FINNHUB_API_KEY', False),
        ('ALPHA_VANTAGE_API_KEY', False),
        ('LICENSE_KEY', False),
    ]
    
    for var, required in env_vars:
        value = os.environ.get(var)
        if value:
            ok(f"{var}: Set (length: {len(value)})")
        elif required:
            fail(f"{var}: NOT SET (required)")
            errors += 1
        else:
            warn(f"{var}: Not set (optional)")
    
    return errors

def check_positions_and_trades():
    header("POSITIONS & TRADES SUMMARY")
    errors = 0
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM signal_lots WHERE remaining_qty > 0")
        open_lots = cursor.fetchone()[0]
        info(f"Open signal lots (tracking): {open_lots}")
        
        cursor.execute("SELECT COUNT(*) FROM trades WHERE status = 'OPEN'")
        open_trades = cursor.fetchone()[0]
        info(f"Open trades: {open_trades}")
        
        cursor.execute("SELECT COUNT(*) FROM lot_closures")
        closures = cursor.fetchone()[0]
        info(f"Total closures recorded: {closures}")
        
        cursor.execute("""
            SELECT SUM(pnl) FROM lot_closures
        """)
        total_pnl = cursor.fetchone()[0] or 0
        if total_pnl >= 0:
            ok(f"Total realized P&L: ${total_pnl:,.2f}")
        else:
            warn(f"Total realized P&L: ${total_pnl:,.2f}")
        
        conn.close()
    except Exception as e:
        fail(f"Positions check error: {e}")
        errors += 1
    
    return errors

def main():
    print(f"\n{Colors.BOLD}BotifyTrades System Validation{Colors.END}")
    print(f"Run time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    total_errors = 0
    
    total_errors += check_database()
    total_errors += check_channels()
    total_errors += check_discord_settings()
    total_errors += check_broker_credentials()
    total_errors += check_trade_monitor()
    total_errors += check_signal_patterns()
    total_errors += check_webhook_channels()
    total_errors += check_risk_management()
    total_errors += check_environment()
    total_errors += check_positions_and_trades()
    
    header("VALIDATION SUMMARY")
    if total_errors == 0:
        ok(f"All checks passed! System is healthy.")
    else:
        fail(f"{total_errors} error(s) found - review above for details")
    
    return total_errors

if __name__ == '__main__':
    sys.exit(main())
