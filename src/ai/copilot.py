"""AI Co-Pilot — Tiered intelligence for the chatbot.

3-tier response generation:
  Tier 0: Template response from local data (FREE, <50ms)
  Tier 1: Diagnostic engine with error→explanation maps (FREE, <50ms)
  Tier 2: Gemini Flash for synthesis (FREE quota, <2s)
  Tier 3: Claude/OpenAI for complex advisory ($0.001, <3s)

90%+ of queries answered at Tier 0-1 (zero cost, instant).
"""
import re
import time
import asyncio
from typing import Optional, Dict, Any, List, Tuple
from enum import Enum


class Intent(Enum):
    STATUS = "status"
    LOOKUP = "lookup"
    DIAGNOSIS = "diagnosis"
    COMPARISON = "comparison"
    ADVISORY = "advisory"
    SYSTEM = "system"
    GENERAL = "general"


# ═══ Error Code → Human Explanation Map ═══════════════════════════════════
# Every broker error, risk event, and system failure mapped to plain English

ERROR_EXPLANATIONS = {
    # IBKR
    'error 201': 'IBKR rejected the order. Common causes: insufficient margin, short sell on cash account, or contract not available.',
    'short stock positions': 'The position was already closed by the broker bracket (SL/PT filled). The bot tried to sell again, which would create a short. The anti-short guard should prevent this.',
    'margin requirement': 'IBKR cash account cannot short sell. The position was already closed by a bracket order.',
    'error 110': 'IBKR: Order price is outside the acceptable range for this contract.',
    'error 135': 'IBKR: Cannot find the contract. The symbol may be delisted or the contract expired.',
    'error 10089': 'IBKR: Market data subscription not available for this symbol.',
    'no security definition': 'IBKR cannot find this security. Check if the symbol is correct and the contract is still active.',

    # Schwab
    'settled cash': 'Schwab: Insufficient settled cash. Funds from recent sales may not have settled yet (T+1 for stocks, T+1 for options).',
    'good faith violation': 'Trading with unsettled funds. Wait for settlement or use only settled cash.',
    'timeouterror': 'Schwab API timed out. The pre-market/after-hours API is slower. The bot will retry.',
    'readerror': 'Network error reading from Schwab API. Connection was interrupted.',

    # Webull Official
    'generate_new_short': 'Webull Official: Position already closed. Selling would create a new short position.',
    'oauth_openapi': 'Webull Official API authentication error. Token may need refresh.',
    '417': 'Webull Official rejected the order. Common: wrong trading session (CORE vs ALL) or invalid order type.',
    'insufficient': 'Not enough buying power or settled cash for this order.',

    # Risk engine
    'breakout_reset': 'Price was already above the trigger when the order was created. Breakout reset waits for a pullback first. Increase conditional timeout or disable breakout reset.',
    'expired': 'Conditional order timed out before the trigger price was reached.',
    'no_callback': 'Bot was still starting up when the order triggered. The execution callback was not wired yet. Resubmit the order.',
    'execute_disabled': 'The channel has execution disabled. Enable it in Channel Settings.',
    'staleness': 'Price data is too old to safely execute. The bot waits for fresh data.',

    # Position sizing
    'channel max position': 'Order exceeds the channel\'s max position size ($) limit. Reduce quantity or increase the limit.',
    'buying power': 'Not enough buying power. Check account balance.',
    'position_size': 'Position sizing calculated 0 shares/contracts. The account balance may be too low for this price.',
}

# ═══ Query Classifier ════════════════════════════════════════════════════

_DIAG_PATTERNS = [
    re.compile(r'\bwhy\b.*\b(fail|reject|cancel|stop|close|exit|error|block|not|didn)', re.I),
    re.compile(r'\bwhat\s+happened\b', re.I),
    re.compile(r'\bwhat\s+went\s+wrong\b', re.I),
    re.compile(r'\bwhy\s+(did|was|is|does|didn)\b', re.I),
    re.compile(r'\b(fail|reject|error|issue|problem|wrong|broken|crash)\b', re.I),
]

_STATUS_PATTERNS = [
    re.compile(r'\b(show|list|get|display|what\'?s?)\s+(my|the|all|open|current|active)\b', re.I),
    re.compile(r'\b(position|order|trade|conditional|monitor)\s*(status|state|info|list)?\b', re.I),
    re.compile(r'\b(how is|how\'s|check)\s+\w+\b', re.I),
    re.compile(r'\b(market|regime|vix|broker|system|streaming|risk)\b.*\b(status|state|health)\b', re.I),
]

_ADVISORY_PATTERNS = [
    re.compile(r'\bshould\s+I\b', re.I),
    re.compile(r'\b(optimize|improve|recommend|suggest|advice|change)\b', re.I),
    re.compile(r'\b(best|better|optimal)\s+(setting|config|strategy)\b', re.I),
]

_TICKER_RE = re.compile(r'\b([A-Z]{2,5})\b')
_TICKER_STOPWORDS = {
    'THE', 'AND', 'FOR', 'WHY', 'DID', 'NOT', 'WAS', 'HAS', 'HOW', 'GET',
    'SET', 'ALL', 'MY', 'IS', 'IT', 'OR', 'IF', 'AT', 'TO', 'DO', 'ON',
    'IN', 'SO', 'UP', 'BE', 'BY', 'NO', 'YES', 'SL', 'PT', 'PL', 'API',
    'MCP', 'BOT', 'FAQ', 'AI', 'OUT', 'OFF', 'BTO', 'STC', 'BUY', 'SELL',
    'DAY', 'GTC', 'EST', 'UTC', 'NOW', 'NEW', 'OLD',
}


def _extract_tickers(query: str) -> List[str]:
    candidates = _TICKER_RE.findall(query.upper())
    return [c for c in candidates if c not in _TICKER_STOPWORDS]


def classify_query(query: str) -> Tuple[Intent, List[str], int]:
    """Classify query into intent + tickers + tier. <1ms, zero cost."""
    tickers = _extract_tickers(query)

    if any(p.search(query) for p in _DIAG_PATTERNS):
        return Intent.DIAGNOSIS, tickers, 1  # rule engine first, may escalate

    if any(p.search(query) for p in _STATUS_PATTERNS):
        return Intent.STATUS, tickers, 0  # MCP tools, instant

    if any(p.search(query) for p in _ADVISORY_PATTERNS):
        return Intent.ADVISORY, tickers, 2  # needs AI

    return Intent.GENERAL, tickers, 2  # default: AI with context


# ═══ Context Assembler ═══════════════════════════════════════════════════

def _assemble_context(tickers: List[str], intent: Intent) -> Dict[str, Any]:
    """Fetch relevant data from DB based on intent + tickers. <20ms."""
    context = {}
    try:
        from gui_app.database import get_connection
        conn = get_connection()
        cursor = conn.cursor()

        if tickers:
            sym = tickers[0]
            # Order events for this symbol
            cursor.execute(
                "SELECT timestamp, event_type, broker, direction, price, quantity, status, reason "
                "FROM order_events WHERE symbol=? ORDER BY timestamp DESC LIMIT 20",
                (sym,)
            )
            context['order_events'] = [dict(r) for r in cursor.fetchall()]

            # Trades
            cursor.execute(
                "SELECT id, symbol, broker, direction, status, executed_price, current_price, "
                "pnl, pnl_percent, close_reason, executed_at, closed_at "
                "FROM trades WHERE symbol=? ORDER BY id DESC LIMIT 10",
                (sym,)
            )
            context['trades'] = [dict(r) for r in cursor.fetchall()]

            # Conditional orders
            cursor.execute(
                "SELECT id, status, trigger_price, current_price, error_message, "
                "triggered_at, executed_at, expires_at, breakout_reset_enabled "
                "FROM conditional_orders WHERE symbol=? ORDER BY created_at DESC LIMIT 5",
                (sym,)
            )
            context['conditional_orders'] = [dict(r) for r in cursor.fetchall()]

        if intent == Intent.DIAGNOSIS:
            # Recent failures across all symbols
            cursor.execute(
                "SELECT timestamp, symbol, broker, event_type, reason "
                "FROM order_events WHERE status IN ('FAILED','REJECTED','ERROR') "
                "ORDER BY timestamp DESC LIMIT 10"
            )
            context['recent_failures'] = [dict(r) for r in cursor.fetchall()]

        conn.close()
    except Exception as e:
        context['error'] = str(e)

    return context


# ═══ Diagnostic Engine (Rule-Based, FREE) ════════════════════════════════

def _diagnose(query: str, tickers: List[str], context: Dict) -> Optional[str]:
    """Rule-based diagnosis from order events + error maps. FREE, <5ms.

    Returns a human-readable explanation, or None if can't diagnose.
    """
    parts = []

    # Check order events for failures
    events = context.get('order_events', [])
    failure_events = [e for e in events if e.get('status') in ('FAILED', 'REJECTED', 'ERROR')]

    if failure_events:
        for fe in failure_events[:3]:
            reason = str(fe.get('reason', '') or '')
            broker = fe.get('broker', '?')
            timestamp = fe.get('timestamp', '')
            event_type = fe.get('event_type', '')
            symbol = fe.get('symbol', tickers[0] if tickers else '?')

            # Match error to explanation
            explanation = None
            reason_lower = reason.lower()
            for pattern, explain in ERROR_EXPLANATIONS.items():
                if pattern.lower() in reason_lower:
                    explanation = explain
                    break

            if explanation:
                parts.append(f"**{symbol} {event_type}** ({broker}, {timestamp})")
                parts.append(f"❌ Error: {reason[:150]}")
                parts.append(f"💡 **Reason**: {explanation}")
                parts.append("")
            else:
                parts.append(f"**{symbol} {event_type}** ({broker}, {timestamp})")
                parts.append(f"❌ {reason[:200]}")
                parts.append("")

    # Check conditional orders
    cond_orders = context.get('conditional_orders', [])
    for co in cond_orders:
        status = co.get('status', '')
        error = co.get('error_message', '')
        if status in ('ERROR', 'EXPIRED') and error:
            error_lower = error.lower()
            explanation = None
            for pattern, explain in ERROR_EXPLANATIONS.items():
                if pattern.lower() in error_lower:
                    explanation = explain
                    break

            sym = tickers[0] if tickers else '?'
            parts.append(f"**{sym} Conditional Order #{co.get('id')}** — {status}")
            if status == 'EXPIRED':
                trigger = co.get('trigger_price', 0)
                current = co.get('current_price', 0)
                br = co.get('breakout_reset_enabled', 0)
                parts.append(f"Trigger: ${trigger}, Last price: ${current}")
                if br:
                    parts.append(f"💡 **Reason**: Breakout reset was ON — price was already above trigger. The order waited for a pullback that never happened before timeout.")
                else:
                    parts.append(f"💡 **Reason**: Price never reached the trigger point before the order expired.")
            elif explanation:
                parts.append(f"❌ {error[:150]}")
                parts.append(f"💡 **Reason**: {explanation}")
            else:
                parts.append(f"❌ {error[:200]}")
            parts.append("")

    # Check trades for close reasons
    trades = context.get('trades', [])
    for t in trades[:3]:
        close_reason = t.get('close_reason', '')
        if close_reason and 'broker_closed' in str(close_reason).lower():
            sym = t.get('symbol', '?')
            pnl = t.get('pnl_percent', 0) or 0
            parts.append(f"**{sym}** — Closed by broker bracket (native SL/PT fill)")
            parts.append(f"P&L: {pnl:+.1f}% | Broker: {t.get('broker', '?')}")
            parts.append("")

    if parts:
        return "🔍 **Diagnosis**\n\n" + "\n".join(parts)

    return None


# ═══ Main Co-Pilot Entry Point ═══════════════════════════════════════════

def copilot_respond(query: str) -> Optional[Dict]:
    """Main co-pilot entry point. Called from chatbot get_response().

    Returns None if it can't handle the query (falls through to other handlers).
    """
    intent, tickers, tier = classify_query(query)

    # Tier 0: Status queries → MCP tools (handled by _handle_mcp_query already)
    if intent == Intent.STATUS and tier == 0:
        return None  # Let MCP handler handle it

    # Tier 1: Diagnosis queries → rule engine + context assembly
    if intent == Intent.DIAGNOSIS:
        context = _assemble_context(tickers, intent)
        diagnosis = _diagnose(query, tickers, context)
        if diagnosis:
            return {
                "success": True,
                "response": diagnosis,
                "topic": "diagnosis",
                "confidence": 0.9,
                "ai_powered": False,
                "tier": 1,
            }
        # Couldn't diagnose with rules → fall through to AI (existing handler)
        return None

    # Tier 2+: Complex queries → let existing AI handler deal with it
    return None
