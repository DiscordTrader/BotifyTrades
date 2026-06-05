"""
QA Playbook Live Endpoint Validator
Tests every API endpoint returns a valid response (not 500).
Run: python scripts/validate_qa_live.py
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('FLASK_ENV', 'testing')

import io
old_stdout = sys.stdout
sys.stdout = io.StringIO()
try:
    from gui_app.app import create_app
    app = create_app()
finally:
    sys.stdout = old_stdout

# Use Flask test client (bypasses network, simulates logged-in session)
client = app.test_client()

# Login first
with client.session_transaction() as sess:
    sess['logged_in'] = True
    sess['username'] = 'admin'
    sess['is_admin'] = True

results = {"pass": 0, "fail": 0, "errors": []}

def test(method, path, section, expect_json=True):
    try:
        if method == "GET":
            resp = client.get(path)
        elif method == "POST":
            resp = client.post(path, json={}, content_type='application/json')
        elif method == "PUT":
            resp = client.put(path, json={}, content_type='application/json')
        elif method == "DELETE":
            resp = client.delete(path)

        if resp.status_code < 500:
            results["pass"] += 1
            return True
        else:
            results["fail"] += 1
            results["errors"].append(f"  [{section}] {method} {path} -> {resp.status_code}")
            return False
    except Exception as e:
        results["fail"] += 1
        results["errors"].append(f"  [{section}] {method} {path} -> EXCEPTION: {str(e)[:80]}")
        return False

# ═══════════════════════════════════════════
# SECTION 1: Dashboard
# ═══════════════════════════════════════════
print("Testing Section 1: Dashboard...")
test("GET", "/", "S1")
test("GET", "/api/v2/broker-states", "S1")
test("GET", "/api/v2/broker-states/refresh-all", "S1")
test("GET", "/api/sod-balance", "S1")
test("GET", "/api/brokers/status", "S1")
test("GET", "/api/brokers/health", "S1")
test("GET", "/api/stats", "S1")

# SECTION 2: Channels
print("Testing Section 2: Channels...")
test("GET", "/channels", "S2")
test("GET", "/channels/canada", "S2")
test("GET", "/api/channels", "S2")

# SECTION 3: Execution
print("Testing Section 3: Execution...")
test("GET", "/execution", "S3")
test("GET", "/api/execution-pnl", "S3")
test("GET", "/api/execution-pnl/filters", "S3")
test("GET", "/api/execution-lots", "S3")
test("GET", "/api/signal-summary", "S3")

# SECTION 4: P&L
print("Testing Section 4: P&L...")
test("GET", "/pnl", "S4")
test("GET", "/api/pnl/detailed", "S4")
test("GET", "/api/pnl/users", "S4")
test("GET", "/api/pnl/authors", "S4")
test("GET", "/api/pnl/dates", "S4")

# SECTION 5: Trades
print("Testing Section 5: Trades...")
test("GET", "/trades", "S5")
test("GET", "/api/trades", "S5")
test("GET", "/api/trades/summary", "S5")
test("GET", "/api/trades/live-snapshot", "S5")
test("GET", "/api/trades/merged", "S5")
test("GET", "/api/trades/stale-count", "S5")
test("GET", "/api/trades/rejected", "S5")

# SECTION 6: Options
print("Testing Section 6: Options...")
test("GET", "/options", "S6")
test("GET", "/api/options/expirations?symbol=SPY", "S6")

# SECTION 7: Performance
print("Testing Section 7: Performance...")
test("GET", "/api/performance-v2?sections=overview", "S7")
test("GET", "/api/performance", "S7")
test("GET", "/api/performance/summary", "S7")
test("GET", "/api/broker-performance", "S7")

# SECTION 8: Leaderboard
print("Testing Section 8: Leaderboard...")
test("GET", "/leaderboard", "S8")
test("GET", "/api/leaderboard", "S8")
test("GET", "/api/leaderboard/users", "S8")
test("GET", "/api/leaderboard/enhanced", "S8")
test("GET", "/api/leaderboard/execution", "S8")

# SECTION 9: Simulate
print("Testing Section 9: Simulate...")
test("GET", "/simulation", "S9")
test("GET", "/api/simulate/presets", "S9")
test("GET", "/api/simulate/risk-presets", "S9")

# SECTION 10: Verification
print("Testing Section 10: Verification...")
test("GET", "/verification", "S10")
test("GET", "/api/verification/broker-status", "S10")
test("GET", "/api/verification/users", "S10")
test("GET", "/api/verification/channels", "S10")

# SECTION 11: Signals
print("Testing Section 11: Signals...")
test("GET", "/signals", "S11")
test("GET", "/signals/us", "S11")
test("GET", "/signals/canada", "S11")
test("GET", "/api/signals", "S11")
test("GET", "/api/signals/history", "S11")
test("GET", "/api/signals/statistics", "S11")

# SECTION 12: System Health
print("Testing Section 12: System Health...")
test("GET", "/health", "S12")
test("GET", "/api/health/full", "S12")
test("GET", "/api/health/diagnostics", "S12")
test("GET", "/api/system/build-info", "S12")
test("GET", "/api/code-version", "S12")
test("GET", "/api/bot/status", "S12")
test("GET", "/api/qa/validate", "S12")
test("GET", "/api/qa/features", "S12")
test("GET", "/api/qa/database-schema", "S12")
test("GET", "/api/qa/workflows", "S12")
test("GET", "/api/qa/trading-pipeline", "S12")
test("GET", "/api/health/migrations", "S12")

# SECTION 13: Settings
print("Testing Section 13: Settings...")
test("GET", "/settings", "S13")
test("GET", "/api/settings/trading", "S13")
test("GET", "/api/settings/global-risk", "S13")
test("GET", "/api/settings/conditional_orders", "S13")
test("GET", "/api/settings/slippage", "S13")
test("GET", "/api/settings/discord", "S13")
test("GET", "/api/settings/discord_notifications", "S13")
test("GET", "/api/settings/telegram", "S13")
test("GET", "/api/settings/ai_analysis", "S13")
test("GET", "/api/settings/trade_monitor", "S13")
test("GET", "/api/settings/risk_management", "S13")
test("GET", "/api/settings/background_services", "S13")
test("GET", "/api/settings/debug", "S13")
test("GET", "/api/settings/api_keys", "S13")
test("GET", "/api/sizing-settings", "S13")
test("GET", "/api/brokers/credentials/discord", "S13")
test("GET", "/api/brokers/credentials/alpaca", "S13")
test("GET", "/api/brokers/credentials/tastytrade", "S13")
test("GET", "/api/brokers/credentials/trading212", "S13")
test("GET", "/api/brokers/credentials/ibkr", "S13")
test("GET", "/api/brokers/credentials/webull", "S13")
test("GET", "/api/brokers/grouped", "S13")
test("GET", "/api/brokers/extended-hours", "S13")
test("GET", "/api/broker/available", "S13")
test("GET", "/schwab/status", "S13")

# SECTION 14: License
print("Testing Section 14: License...")
test("GET", "/license", "S14")
test("GET", "/api/license/status", "S14")
test("GET", "/api/license/machine-info", "S14")
test("GET", "/api/v1/license/health", "S14")

# SECTION 15-16: Docs & Help
print("Testing Section 15-16: Docs & Help...")
test("GET", "/architecture", "S15")
test("GET", "/help", "S16")
test("GET", "/api/chat/suggestions", "S16")
test("GET", "/api/chat/topics", "S16")
test("GET", "/api/chat/status", "S16")

# SECTION 17: Signal Formats
print("Testing Section 17: Signal Formats...")
test("GET", "/api/signal-formats", "S17")
test("GET", "/api/signal-formats/ai-status", "S17")

# SECTION 18: Multi-Broker Balance
print("Testing Section 18: Broker Balances...")
test("GET", "/api/schwab/balance", "S18")
test("GET", "/api/alpaca/balance", "S18")
test("GET", "/api/tastytrade/balance", "S18")
test("GET", "/api/ibkr/balance", "S18")
test("GET", "/api/robinhood/balance", "S18")

# SECTION 20: Conditional Orders
print("Testing Section 20: Conditional Orders...")
test("GET", "/api/conditional_orders", "S20")
test("GET", "/api/conditional_orders/status", "S20")

# SECTION 21: Signal Routing
print("Testing Section 21: Signal Routing...")
test("GET", "/admin/signal-routing", "S21")
test("GET", "/api/admin/signal-routing", "S21")
test("GET", "/api/admin/signal-routing/positions", "S21")
test("GET", "/api/admin/signal-routing/pnl", "S21")

# SECTION 22: Auth pages
print("Testing Section 22: Auth...")
test("GET", "/login", "S22")
test("GET", "/signup", "S22")
test("GET", "/consent", "S22")
test("GET", "/api/consent/status", "S22")
test("GET", "/forgot-password", "S22")
test("GET", "/setup", "S22")

# SECTION 23: Upgrade
print("Testing Section 23: Upgrade...")
test("GET", "/api/upgrade/version", "S23")
test("GET", "/api/upgrade/readiness", "S23")
test("GET", "/api/upgrade/backups", "S23")
test("GET", "/api/upgrade/history", "S23")

# SECTION 24: Errors
print("Testing Section 24: Errors...")
test("GET", "/api/errors", "S24")
test("GET", "/api/errors/frequent", "S24")
test("GET", "/api/errors/known-issues", "S24")
test("GET", "/api/debug-report/history", "S24")

# SECTION 25: Services
print("Testing Section 25: Services...")
test("GET", "/api/services", "S25")
test("GET", "/api/services/status", "S25")
test("GET", "/api/broker-limits", "S25")
test("GET", "/api/order-events", "S25")
test("GET", "/api/order-events/stats", "S25")

# SECTION 26: India/Upstox
print("Testing Section 26: India/Upstox...")
test("GET", "/api/brokers/upstox/funds", "S26")
test("GET", "/api/brokers/upstox/positions", "S26")
test("GET", "/api/brokers/upstox/orders", "S26")
test("GET", "/api/upstox/pending-orders", "S26")
test("GET", "/api/upstox/amo-queue-enabled", "S26")

# SECTION 27: Streaming
print("Testing Section 27: Streaming...")
# Skip SSE endpoints as they block

# SECTION 28: Discord Sending
print("Testing Section 28: Discord Sending...")
test("GET", "/api/discord/send-channels", "S28")

# SECTION 29: Channel Messages
print("Testing Section 29: Channel Messages...")
test("GET", "/api/channel-messages/settings", "S29")
test("GET", "/api/channel-messages", "S29")

# SECTION 30: Notifications
print("Testing Section 30: Notifications...")
test("GET", "/api/notifications", "S30")
test("GET", "/api/notifications/settings", "S30")
test("GET", "/api/brokers/notifications", "S30")

# SECTION 31: Risk/Diagnostics
print("Testing Section 31: Risk/Diagnostics...")
test("GET", "/api/risk-status", "S31")
test("GET", "/api/unprotected-trades", "S31")
test("GET", "/api/debug-risk-keys", "S31")
test("GET", "/api/diagnostics", "S31")
test("GET", "/api/daily-pnl-status", "S31")
test("GET", "/api/uph/status", "S31")

# SECTION 32: System Utilities
print("Testing Section 32: System Utilities...")
test("GET", "/api/trade_monitor/synced_orders", "S32")
test("GET", "/api/wizard/status", "S32")
test("GET", "/api/system/consistency-check", "S32")

# SECTION 34: Broker Analytics
print("Testing Section 34: Broker Analytics...")
test("GET", "/api/bot-trades", "S34")
test("GET", "/api/brokers/all_accounts", "S34")

# SECTION 35: Channel Mappings
print("Testing Section 35: Channel Mappings...")
test("GET", "/api/channel_mappings", "S35")

# Webhooks
print("Testing Webhooks...")
test("GET", "/api/webhook/config", "S13-webhook")
test("GET", "/api/webhook/positions", "S13-webhook")
test("GET", "/api/webhook/channels", "S13-webhook")

# ═══════════════════════════════════════════
# RESULTS
# ═══════════════════════════════════════════
print(f"\n{'='*60}")
print(f"QA PLAYBOOK LIVE ENDPOINT VALIDATION")
print(f"{'='*60}")
print(f"Tested:  {results['pass'] + results['fail']} endpoints")
print(f"PASS:    {results['pass']} (HTTP < 500)")
print(f"FAIL:    {results['fail']} (HTTP 500 / Exception)")
if results["errors"]:
    print(f"\nFailed endpoints:")
    for e in results["errors"]:
        print(e)
else:
    print(f"\nALL ENDPOINTS RESPONDING!")
print(f"{'='*60}")
