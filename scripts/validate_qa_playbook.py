"""
QA Playbook Validator — checks all routes, tables, and columns exist.
Run: python scripts/validate_qa_playbook.py
"""
import sys, os, re, sqlite3
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('FLASK_ENV', 'testing')

# Suppress print noise from database init
import io
old_stdout = sys.stdout
sys.stdout = io.StringIO()
try:
    from gui_app.app import create_app
    app = create_app()
finally:
    sys.stdout = old_stdout

def normalize(route):
    return re.sub(r'<[^>]+>', '<P>', route)

# Build route map
route_map = {}
for rule in app.url_map.iter_rules():
    methods = set(rule.methods) - {'HEAD', 'OPTIONS'}
    key = normalize(rule.rule)
    if key not in route_map:
        route_map[key] = set()
    route_map[key].update(methods)

# ═══════════════════════════════════════════
# ALL PLAYBOOK ENDPOINTS BY SECTION
# ═══════════════════════════════════════════
endpoints = [
    # S1: Dashboard
    ("GET", "/"), ("GET", "/api/v2/broker-states"), ("GET", "/api/v2/broker-states/<b>"),
    ("POST", "/api/v2/broker-states/<b>/refresh"), ("POST", "/api/v2/broker-states/refresh-all"),
    ("GET", "/api/v2/broker-states/by-region/<r>"), ("GET", "/api/sod-balance"),
    ("POST", "/api/sod-balance/capture"), ("GET", "/api/brokers/status"),
    ("GET", "/api/brokers/health"), ("GET", "/api/stats"),
    # S2: Channels
    ("GET", "/channels"), ("GET", "/channels/canada"),
    ("GET", "/api/channels"), ("POST", "/api/channels"),
    ("PUT", "/api/channels/<id>"), ("DELETE", "/api/channels/<id>"),
    ("POST", "/api/channels/<id>/reset"),
    ("GET", "/api/channels/<id>/allowed_users"), ("POST", "/api/channels/<id>/allowed_users"),
    ("DELETE", "/api/channels/<id>/allowed_users/<uid>"),
    ("GET", "/api/channels/<id>/users"), ("GET", "/api/channels/<id>/recent-messages"),
    ("POST", "/api/channels/<id>/scan"),
    # S3: Execution
    ("GET", "/execution"), ("GET", "/api/execution-pnl"), ("GET", "/api/execution-pnl/filters"),
    ("GET", "/api/execution-lots"), ("GET", "/api/signal-summary"),
    ("GET", "/api/signal-summary/<id>/executions"),
    # S4: P&L
    ("GET", "/pnl"), ("GET", "/api/pnl/detailed"), ("GET", "/api/pnl/users"),
    ("POST", "/api/reset/pnl"), ("POST", "/api/pnl/purge/by-date"),
    ("POST", "/api/pnl/purge/by-author"), ("GET", "/api/pnl/authors"), ("GET", "/api/pnl/dates"),
    # S5: Trades
    ("GET", "/trades"), ("GET", "/api/trades"), ("GET", "/api/trades/summary"),
    ("GET", "/api/trades/live-snapshot"), ("POST", "/api/trades/close-all"),
    ("POST", "/api/trades/<id>/close"), ("POST", "/api/trades/<id>/force-close-db"),
    ("GET", "/api/trades/<id>/risk-settings"), ("PUT", "/api/trades/<id>/risk-settings"),
    ("GET", "/api/trades/merged"), ("POST", "/api/trades/clear-stale"),
    ("GET", "/api/trades/stale-count"), ("GET", "/api/trades/rejected"),
    ("POST", "/api/refresh_prices"), ("POST", "/api/trades/realtime-prices"),
    # S6: Options
    ("GET", "/options"), ("GET", "/api/options/expirations"), ("GET", "/api/options/chain"),
    ("POST", "/api/options/strike-quote"), ("GET", "/api/options/quick-chain"),
    ("POST", "/api/options/subscribe-stream"), ("GET", "/api/options/stream-quotes"),
    ("GET", "/api/options/chain-stream"), ("POST", "/api/options/chain-stream/update-keys"),
    ("POST", "/api/options/order"),
    # S7: Performance
    ("GET", "/api/performance-v2"), ("GET", "/api/performance"),
    ("GET", "/api/performance/summary"), ("GET", "/api/performance/pnl"),
    ("GET", "/api/performance/pnl/users"), ("GET", "/api/broker-performance"),
    # S8: Leaderboard
    ("GET", "/leaderboard"), ("GET", "/api/leaderboard"), ("GET", "/api/leaderboard/users"),
    ("GET", "/api/leaderboard/enhanced"), ("GET", "/api/leaderboard/execution"),
    # S9: Simulate
    ("GET", "/simulation"), ("POST", "/api/simulate"), ("GET", "/api/simulate/presets"),
    ("GET", "/api/simulate/stats/<t>/<id>"), ("POST", "/api/simulate/exact"),
    ("POST", "/api/simulate/historical"), ("POST", "/api/simulate/custom"),
    ("GET", "/api/simulate/autocomplete/<t>"), ("POST", "/api/simulate/optimizer"),
    ("POST", "/api/simulate/copy1to1"), ("POST", "/api/simulate/recovery"),
    ("POST", "/api/simulate/monte-carlo"), ("POST", "/api/simulate/comprehensive"),
    ("POST", "/api/simulate/correlation"), ("GET", "/api/simulate/risk-presets"),
    # S10: Verification
    ("GET", "/verification"), ("GET", "/api/verification/broker-status"),
    ("POST", "/api/verification/verify"),
    ("GET", "/api/verification/report/<t>/<id>"), ("GET", "/api/verification/analyze/<t>/<id>"),
    ("GET", "/api/verification/stats/<t>/<id>"),
    ("GET", "/api/verification/users"), ("GET", "/api/verification/channels"),
    # S11: Signals
    ("GET", "/signals"), ("GET", "/signals/us"), ("GET", "/signals/canada"),
    ("GET", "/api/signals"), ("GET", "/api/signals/history"),
    ("GET", "/api/signals/<id>"), ("GET", "/api/signals/statistics"),
    ("GET", "/api/signals/export"),
    # S12: Health
    ("GET", "/health"), ("GET", "/api/health/full"), ("POST", "/api/health/test/<c>"),
    ("GET", "/api/health/diagnostics"), ("POST", "/api/health/run-tests"),
    ("GET", "/api/health/migrations"), ("POST", "/api/health/migrations/upgrade"),
    ("GET", "/api/system/build-info"), ("GET", "/api/code-version"),
    ("GET", "/api/bot/status"), ("POST", "/api/bot/stop"), ("POST", "/api/bot/restart"),
    ("GET", "/api/qa/validate"), ("GET", "/api/qa/features"),
    ("GET", "/api/qa/database-schema"), ("GET", "/api/qa/workflows"),
    ("GET", "/api/qa/trading-pipeline"), ("POST", "/api/qa/pytest"),
    ("GET", "/api/qa/feature/<n>"), ("POST", "/api/qa/impact"), ("POST", "/api/qa/tests/run"),
    # S13: Settings
    ("GET", "/settings"),
    ("GET", "/api/settings/trading"), ("POST", "/api/settings/trading"),
    ("GET", "/api/settings/global-risk"), ("POST", "/api/settings/global-risk"),
    ("GET", "/api/settings/conditional_orders"), ("POST", "/api/settings/conditional_orders"),
    ("GET", "/api/settings/slippage"), ("POST", "/api/settings/slippage"),
    ("GET", "/api/settings/discord"), ("POST", "/api/settings/discord"),
    ("GET", "/api/settings/discord_notifications"), ("POST", "/api/settings/discord_notifications"),
    ("GET", "/api/settings/telegram"), ("POST", "/api/settings/telegram"),
    ("POST", "/api/telegram/test-connection"), ("POST", "/api/telegram/verify-code"),
    ("POST", "/api/telegram/verify-2fa"),
    ("GET", "/api/settings/ai_analysis"), ("POST", "/api/settings/ai_analysis"),
    ("GET", "/api/settings/signal_conversion"), ("POST", "/api/settings/signal_conversion"),
    ("GET", "/api/settings/trade_monitor"), ("POST", "/api/settings/trade_monitor"),
    ("GET", "/api/settings/risk_management"), ("POST", "/api/settings/risk_management"),
    ("GET", "/api/settings/background_services"), ("POST", "/api/settings/background_services"),
    ("GET", "/api/settings/debug"), ("POST", "/api/settings/debug"),
    ("GET", "/api/settings/api_keys"), ("POST", "/api/settings/api_keys"),
    ("GET", "/api/sizing-settings"), ("POST", "/api/sizing-settings"),
    ("POST", "/api/analyst-portfolio"),
    ("POST", "/api/settings/test_webhook"),
    # Broker credentials
    ("GET", "/api/brokers/credentials/discord"), ("POST", "/api/brokers/credentials/discord"),
    ("GET", "/api/brokers/credentials/alpaca"), ("POST", "/api/brokers/credentials/alpaca"),
    ("POST", "/api/brokers/credentials/alpaca_live"),
    ("GET", "/api/brokers/credentials/tastytrade"), ("POST", "/api/brokers/credentials/tastytrade"),
    ("POST", "/api/brokers/credentials/tastytrade/clear"),
    ("GET", "/api/brokers/credentials/trading212"), ("POST", "/api/brokers/credentials/trading212"),
    ("GET", "/api/brokers/credentials/ibkr"), ("POST", "/api/brokers/credentials/ibkr"),
    ("GET", "/api/brokers/credentials/webull"), ("POST", "/api/brokers/credentials/webull"),
    ("POST", "/api/brokers/credentials/webull/clear-tokens"),
    ("POST", "/api/brokers/connect/<id>"), ("POST", "/api/brokers/disconnect/<id>"),
    ("POST", "/api/brokers/reload"), ("GET", "/api/brokers/grouped"),
    ("GET", "/api/brokers/<n>/profile"), ("GET", "/api/brokers/<n>/credentials"),
    ("POST", "/api/brokers/<n>/credentials"),
    ("POST", "/api/brokers/<n>/test"), ("POST", "/api/brokers/<n>/reconnect"),
    ("GET", "/api/brokers/by-country/<c>"), ("GET", "/api/brokers/extended-hours"),
    ("GET", "/api/broker/available"),
    # Schwab OAuth
    ("GET", "/schwab/auth-url"), ("GET", "/schwab/callback"),
    ("GET", "/schwab/oauth-status"), ("POST", "/schwab/oauth-reset"),
    ("GET", "/schwab/status"), ("POST", "/schwab/refresh"),
    ("POST", "/schwab/disconnect"), ("POST", "/schwab/manual-code"),
    # Google OAuth
    ("GET", "/google_login"),
    # Webull auth
    ("POST", "/api/webull/auth/login"), ("POST", "/api/webull/auth/request-mfa"),
    ("POST", "/api/webull/auth/security-question"), ("POST", "/api/webull/auth/session-login"),
    # S14: License
    ("GET", "/license"), ("GET", "/api/license/status"), ("GET", "/api/license/machine-info"),
    ("POST", "/api/license/activate"), ("POST", "/api/license/validate"),
    ("POST", "/api/license/deactivate"), ("GET", "/api/v1/license/health"),
    ("POST", "/api/v1/license/trial"),
    # S15: Docs
    ("GET", "/architecture"),
    # S16: Help
    ("GET", "/help"), ("POST", "/api/chat"), ("POST", "/api/chat/upload-log"),
    ("GET", "/api/chat/suggestions"), ("GET", "/api/chat/topics"),
    ("GET", "/api/chat/status"), ("POST", "/api/chat/errors/seen"), ("GET", "/api/chat/logs"),
    # S17: Signal Processing
    ("GET", "/api/signal-formats"), ("PUT", "/api/signal-formats/<id>"),
    ("DELETE", "/api/signal-formats/<id>"), ("POST", "/api/signal-formats/<id>/toggle"),
    ("POST", "/api/signal-formats/test-parse"), ("GET", "/api/signal-formats/ai-status"),
    ("POST", "/api/signal-formats/discover"),
    # S18: Multi-Broker Balance
    ("GET", "/api/schwab/balance"), ("GET", "/api/alpaca/balance"),
    ("GET", "/api/webull/balance"), ("GET", "/api/webull_paper/balance"),
    ("GET", "/api/tastytrade/balance"), ("GET", "/api/trading212/balance"),
    ("GET", "/api/ibkr/balance"), ("GET", "/api/robinhood/balance"),
    # S20: Conditional Orders
    ("GET", "/api/conditional_orders"), ("GET", "/api/conditional_orders/<id>"),
    ("POST", "/api/conditional_orders/<id>/cancel"),
    ("GET", "/api/conditional_orders/<id>/audit"),
    ("POST", "/api/conditional_orders/purge"),
    ("GET", "/api/conditional_orders/status"), ("GET", "/api/conditional_orders/live_prices"),
    ("POST", "/api/conditional_orders/<id>/offset"),
    # S21: Signal Routing
    ("GET", "/admin/signal-routing"),
    ("GET", "/api/admin/signal-routing"), ("POST", "/api/admin/signal-routing"),
    ("GET", "/api/admin/signal-routing/<id>"), ("PUT", "/api/admin/signal-routing/<id>"),
    ("DELETE", "/api/admin/signal-routing/<id>"),
    ("GET", "/api/admin/signal-routing/positions"), ("GET", "/api/admin/signal-routing/pnl"),
    ("GET", "/api/admin/signal-routing/risk/<ch>"), ("PUT", "/api/admin/signal-routing/risk/<ch>"),
    # S22: Auth
    ("GET", "/login"), ("POST", "/login"), ("GET", "/logout"),
    ("GET", "/signup"), ("POST", "/signup"),
    ("GET", "/consent"), ("POST", "/api/consent/accept"), ("GET", "/api/consent/status"),
    ("GET", "/forgot-password"), ("GET", "/local-reset"),
    ("GET", "/setup"), ("GET", "/user/dashboard"), ("GET", "/user/simulation"),
    # S23: Upgrade
    ("GET", "/api/upgrade/version"), ("POST", "/api/upgrade/check"),
    ("GET", "/api/upgrade/readiness"), ("GET", "/api/upgrade/backups"),
    ("POST", "/api/upgrade/backup"), ("POST", "/api/upgrade/backup/restore"),
    ("POST", "/api/upgrade/run"), ("GET", "/api/upgrade/history"),
    ("POST", "/api/upgrade/skip"), ("POST", "/api/upgrade/remind-later"),
    # S24: Errors
    ("GET", "/api/errors"), ("GET", "/api/errors/frequent"),
    ("POST", "/api/errors/<id>/resolve"), ("GET", "/api/errors/known-issues"),
    ("POST", "/api/errors/log"), ("POST", "/api/debug-report/submit"),
    ("GET", "/api/debug-report/history"),
    # S25: Services
    ("GET", "/api/services"), ("PUT", "/api/services/<id>"),
    ("POST", "/api/services/<id>/toggle"), ("GET", "/api/services/status"),
    ("GET", "/api/broker-limits"), ("GET", "/api/order-events"),
    ("POST", "/api/order-events/clear"), ("GET", "/api/order-events/stats"),
    # S26: India/Upstox
    ("GET", "/api/brokers/upstox/funds"), ("GET", "/api/brokers/upstox/positions"),
    ("GET", "/api/brokers/upstox/orders"), ("GET", "/api/brokers/upstox/trades"),
    ("GET", "/api/brokers/upstox/execution-timing"), ("GET", "/api/brokers/upstox/holdings"),
    ("GET", "/api/brokers/upstox/account"), ("POST", "/api/brokers/upstox/cancel-order"),
    ("GET", "/api/upstox/pending-orders"), ("DELETE", "/api/upstox/pending-orders/<id>"),
    ("GET", "/api/upstox/amo-queue-enabled"), ("POST", "/api/upstox/amo-queue-enabled"),
    # S27: Streaming
    ("GET", "/api/snapshot/stream"), ("POST", "/api/snapshot/force-refresh"),
    ("GET", "/api/streaming/quotes"), ("GET", "/api/streaming/stock-quote"),
    # S28: Discord Sending
    ("POST", "/api/discord/send-signal"), ("POST", "/api/discord/send-signal-multi"),
    ("GET", "/api/discord/send-channels"),
    # S29: Channel Messages
    ("GET", "/api/channel-messages/settings"), ("POST", "/api/channel-messages/settings"),
    ("POST", "/api/channel-messages/purge"), ("GET", "/api/channel-messages"),
    # S30: Notifications
    ("GET", "/api/notifications"), ("POST", "/api/notifications/clear"),
    ("GET", "/api/notifications/settings"), ("POST", "/api/notifications/settings"),
    ("POST", "/api/notifications/test"),
    ("GET", "/api/brokers/notifications"), ("POST", "/api/brokers/notifications/mark-read"),
    # S31: Risk/Diag
    ("GET", "/api/risk-status"), ("GET", "/api/unprotected-trades"),
    ("GET", "/api/debug-risk-keys"), ("GET", "/api/diagnostics"),
    ("GET", "/api/diagnostics/category/<c>"),
    ("GET", "/api/daily-pnl-status"), ("POST", "/api/daily-pnl-unlock"),
    ("GET", "/api/uph/status"),
    # S32: System
    ("POST", "/api/system/backfill-fill-prices"), ("GET", "/api/system/consistency-check"),
    ("GET", "/api/system/validate-channel/<id>"),
    ("POST", "/api/sync-positions"), ("GET", "/api/trade_monitor/synced_orders"),
    ("POST", "/api/wizard/launch"), ("GET", "/api/wizard/status"),
    # S34: Broker Analytics
    ("GET", "/api/broker/analytics/<id>"), ("GET", "/api/broker/positions/<id>"),
    ("GET", "/api/bot-trades"), ("GET", "/api/brokers/all_accounts"),
    ("POST", "/api/schwab/positions/<s>/close"), ("POST", "/api/robinhood/positions/<s>/close"),
    ("POST", "/api/ibkr/positions/<s>/close"), ("POST", "/api/tastytrade/positions/<s>/close"),
    ("POST", "/api/alpaca/positions/<s>/close"),
    ("POST", "/api/robinhood/orders/<id>/cancel"), ("POST", "/api/alpaca/orders/<id>/cancel"),
    ("POST", "/api/orders/<b>/<id>/cancel"),
    # S35: Channel Mappings
    ("GET", "/api/channel_mappings"), ("POST", "/api/channel_mappings"),
    ("PUT", "/api/channel_mappings/<id>"), ("DELETE", "/api/channel_mappings/<id>"),
    # Webhook
    ("GET", "/api/webhook/config"), ("POST", "/api/webhook/config"),
    ("POST", "/api/webhook/test"), ("POST", "/api/webhook/post_bto"),
    ("POST", "/api/webhook/post_stc"), ("GET", "/api/webhook/positions"),
    ("POST", "/api/webhook/find_position"),
    ("GET", "/api/webhook/channels"), ("POST", "/api/webhook/channels"),
    ("PUT", "/api/webhook/channels/<id>"), ("DELETE", "/api/webhook/channels/<id>"),
    ("POST", "/api/webhook/channels/<id>/test"),
    # Telegram channels
    ("GET", "/api/telegram/channels"), ("POST", "/api/telegram/channels"),
    ("PUT", "/api/telegram/channels/<id>"), ("DELETE", "/api/telegram/channels/<id>"),
]

passed = 0
failed = 0
fails = []
for method, path in endpoints:
    norm = normalize(path)
    if norm in route_map and method in route_map[norm]:
        passed += 1
    else:
        failed += 1
        fails.append(f"  MISSING: {method:6s} {path}")

print(f"\n{'='*60}")
print(f"QA PLAYBOOK ROUTE VALIDATION")
print(f"{'='*60}")
print(f"Checked: {len(endpoints)} endpoints")
print(f"PASS:    {passed}")
print(f"FAIL:    {failed}")
if fails:
    print(f"\nMissing routes:")
    for f in fails:
        print(f)
else:
    print("\nALL ENDPOINTS VERIFIED!")
print(f"{'='*60}")
