# AI Natural Language Signal Pipeline + Robinhood MCP — Implementation Plan

**Date:** 2026-06-18  
**Version baseline:** 12.1.7 (commit b0315b1e)  
**Status:** Plan complete — not yet implemented  
**Author:** Architecture review session

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [What Already Exists](#2-what-already-exists)
3. [Signal Pattern Reference — Phoenix & ProTrader](#3-signal-pattern-reference--phoenix--protrader)
4. [Track 1 — Robinhood MCP Integration](#4-track-1--robinhood-mcp-integration)
5. [Track 2 — Enhanced NL Signal Pipeline](#5-track-2--enhanced-nl-signal-pipeline)
6. [Track 3 — AI Agent Platform (SENTINEL/ANALYST/EXECUTOR)](#6-track-3--ai-agent-platform-sentinelanalystexecutor)
7. [Track 4 — Latency Architecture](#7-track-4--latency-architecture)
8. [What Does NOT Change](#8-what-does-not-change)
9. [Implementation Phases](#9-implementation-phases)
10. [File Map — All New and Changed Files](#10-file-map--all-new-and-changed-files)
11. [Already Fixed — Webull Health Monitor](#11-already-fixed--webull-health-monitor)

---

## 1. Problem Statement

Four distinct problems to solve:

| # | Problem | Severity |
|---|---------|----------|
| 1 | Robinhood uses unofficial `robin_stocks` (email/password/TOTP) — hidden in Settings because it breaks without notice | HIGH |
| 2 | Phoenix and ProTrader channels post natural language signals that don't match any Tier 1–4 regex — routed to AI (150–200ms) or silently missed | HIGH |
| 3 | NL selling signals ("out of AAPL", "selling 80%") require admin approval via AI fallback — not auto-executed even when position is confirmed open | HIGH |
| 4 | AI Agent Platform (SENTINEL/ANALYST/EXECUTOR from `docs/AI_AGENT_PLATFORM.md`) has no execution target — Robinhood MCP is the intended broker | MEDIUM |

**Already fixed (commit b0315b1e):** WEBULL_OFFICIAL orders rejected at startup — health monitor not registered synchronously at connect time.

---

## 2. What Already Exists

Before implementing anything, understand what the codebase already has:

### Signal Parsing Pipeline (`src/services/signal_parsing_pipeline.py`)
- 5-tier cascade: Embeds → Registry (80+ patterns) → Trader-specific → Standard BTO/STC → AI Fallback
- `ParsedSignal.can_execute()` — security gate; AI signals require `admin_approved=True`
- `SignalDeduplicator` — 5-min TTL, prevents double-execution

### AI Signal Parser (`src/services/ai_signal_parser.py`)
- Supports Claude Haiku 4.5, Gemini 2.0 Flash, OpenAI GPT-4o-mini, Ollama
- `AIParseResult` has: `action`, `symbol`, `is_conditional`, `trigger_price`, `trigger_type`, `profit_targets`, `stop_loss`, `stop_loss_pct`, `is_trim`
- 1-hour result cache keyed by message hash
- 3-concurrent semaphore

### AI → Conditional Order Bridge (`src/selfbot_webull.py:14142–14204`)
- Already implemented: when AI returns `is_conditional=True` and `action='BTO'` → calls `conditional_order_router.create_order()`
- **Gap:** STC/exit NL signals still require `admin_approved` — no position-aware auto-approve path

### Robinhood Settings (`gui_app/templates/settings.html:772`)
- Card exists but hidden: `style="display:none"`
- Currently uses email/password/TOTP (unofficial `robin_stocks`)
- Full UI already built — just hidden

### AI Parser System Prompt
- Already handles: `is_conditional`, `trigger_price`, conditional format detection
- **Gap:** No few-shot examples for Phoenix/ProTrader exact formats
- **Gap:** No NL exit examples ("out of X", "selling 80% X", "SL hit")

---

## 3. Signal Pattern Reference — Phoenix & ProTrader

**Analysis source:** 1,000 messages from `🚨┃phoenix` + 597 from `🚨┃protrader` (extracted 2026-06-18)  
**Both channels: stocks only — no options signals found**

### 3.1 Phoenix Channel (`1443262702515650713`) — Author: Arlette (phoenix88804)

#### Signal Ratio
| Type | Approximate % |
|------|--------------|
| BTO conditional | ~20% |
| Watchlist/conditional | ~20% |
| Partial exits (selling X%) | ~15% |
| Full exits (out of X) | ~8% |
| Commentary/updates/social | ~30% |
| Image only | ~5% |

#### FORMAT A — BTO Conditional (primary, ~20%)
```
@everyone TGE over 1.43
SL 10%

@everyone ELTX over 3.75
SL 8%

@everyone BIRD over 5.08
SL 4.85

<@&1291579062350905414> CCTG over 1.58
SL 10%

Daytrades AHMA over 2.40
SL 10%
```
- `@everyone` or role mention `<@&1291579062350905414>` or `Daytrades` prefix
- **Edge case:** `@everyoneTICKER` (no space — happens frequently)
- SL is either percentage (`10%`) or dollar price (`4.85`)
- Optional follow-up in same message: `first target 0.92`, `first profits 6`
- Regex:
```python
r'(?:@everyone|<@&\d+>|Daytrades)\s*([A-Z]{2,6})\s+over\s+([\d.]+)(?:\s*\n\s*[Ss][Ll]\s+([\d.%]+))?'
```

#### FORMAT B — Partial Sell / Trim (~15%)
```
@everyone selling 80% CCTG
selling 85% here ELTX watching vol
selling 90% BIRD
selling 80% YMAT
selling 10% more EHGO moving SL to my entry for remaining shares
leaving 15% here ICCM
leaving 5% SUGP
```
- Regex (primary):
```python
r'selling\s+(\d{1,3})%\s+(?:here\s+)?([A-Z]{2,6})'
```
- "leaving X%" means keep X%, sell rest (inverse trim)

#### FORMAT C — Full Exit (~8%)
```
out of TGE  dont like where its going
out of CCTG
out of CUPR
out witha loss AHMA
getting out of AHMA dont like that the red vol
closing my position with CAST now for the remaining shares
OBAI hit my SL
hit my SL with RGNT
@everyone selling here            ← no ticker, needs context
```
- Regexes:
```python
r'(?:getting\s+)?out\s+(?:of|witha?\s+loss\s+(?:of\s+)?)(?:everything|([A-Z]{2,6}))'
r'([A-Z]{2,6})\s+hit\s+my\s+SL'
r'hit\s+my\s+SL\s+with\s+([A-Z]{2,6})'
r'closing\s+my\s+position\s+with\s+([A-Z]{2,6})'
```

#### FORMAT D — Watchlist (~20%)
```
@everyone watching ICCM
@everyone watching CLWT
watching: MAMO, OBAI, NIVF, AHMA
watching:\n* CUPR\n* CAST\n* QTEX
will be watching GRNT and CUPR
<@&...> watching RUBI for re entry around 1.2
@everyone watching CUPR  will be entering around 13.50-13.70
```
- Regex:
```python
r'(?:@everyone|<@&\d+>)\s*(?:will\s+be\s+)?watching\s+([A-Z]{2,6}(?:[\s,]+(?:and\s+)?[A-Z]{2,6})*)'
```

#### Ambiguous / IGNORE Patterns
```
profits 6              ← profit update, no ticker in message
we got 6%              ← performance
first target 3.95      ← orphan PT (no ticker)
SL 10%                 ← orphan SL (linked to prior signal)
RUBI is back           ← price commentary
no entry yet on OBAI   ← negation — NOT a signal
```

---

### 3.2 ProTrader Channel (`1443262702515650713`) — Author: Protrader Alerts / Momentum Alerts

#### Signal Ratio
| Type | Approximate % |
|------|--------------|
| BTO structured block | ~25% |
| Performance/target updates | ~30% |
| Commentary/watchlist chat | ~25% |
| Cancel/invalidate signals | ~10% |
| Admin/Atlantic Trading bot ads | ~5% |
| Images | ~2% |
| Atlantic Trading bot | ~3% (filter by author_id `1478385086276702251`) |

#### FORMAT E — BTO Structured Block (~25%)
```
Ticker: ICCM
Entry range: Break of 5.30
Targs: 5.35-5.40-5.45-5.50- if. 5.51 can break...room to 5.60-5.80-6.00+  SL- Manage your SL
Buying 50 shares in 10k account  - Day/swing trade

Ticker: PIII
Entry range: 7.77-7.30
SL below : 7.15
Targs: 8.00-8.20-8.40-8.50-8.80+
Buying 50 shares in 10k account  - Day trade - RISKY

Ticker: VSME
Entry range: 4.30 break
Targs: 4.35-4.40-4.45-4.50- if 4.52 can break room to 4.60-4.70
Buying 100 shares in 10k account  - Day/swing trade
```
- Regex (block header):
```python
r'Ticker:\s+([A-Z]{2,6})\s*\n\s*Entry\s+range:\s+(?:Break\s+of\s+)?([\d.]+(?:\s*-\s*[\d.]+)?)'
```
- Target extraction:
```python
r'Targs?:\s+([\d.,\-+\s]+)'
# Split by '-' to get individual targets, stop at 'if' or '+'
```
- Qty from: `Buying N shares` → `r'Buying\s+(\d+)\s+shares'`

#### FORMAT F — Signal Cancel/Invalidate (~10%)
```
cancel the AMST alert.. ran up from 1.75
SUNE cancel this.. ran up from 2.15
MASK - please cancel the alert.. our entry was 1.80
RUBI- We cutting this.. even 2.78 didnt hold.. small loss.
VSME.. failed.. hit 5.35 and halting down
```
- Regex:
```python
r'(?:cancel\s+(?:the\s+)?([A-Z]{2,6})\s+alert|([A-Z]{2,6})\s*[-–]\s*(?:cancel|We\s+cutting\s+this))'
```
- Action: `CANCEL` — calls `conditional_order_router.cancel_by_symbol(channel_id, symbol)`

#### FORMAT G — Freeform Entry (~5% — needs AI)
```
CODX.. Buying break of 2.60 for a move to 2.70-2.80-2.85-3.05
ONDS- Buy this 7.55-7.00 and have a 10% SL .. Targs : 8-8.50+
ALIT - Buying 0.85/more adds 0.68 - Get ur avd Mid 70s... Keep 20% SL
```
- Falls through to AI Tier 5 — these are irregular enough to warrant AI parsing

#### Ambiguous / IGNORE Patterns
```
ICCM 8.84 ✅              ← target confirmation, NOT a new signal
ICCM 8.32 from 5.30       ← performance report
VCIG 4.10 ✅ - 4.11 break may give 4.15-4.20   ← update with next level hint
TDIC.. almost halt down   ← warning/commentary
Enjoying the alerts? [link]   ← Atlantic Trading bot ad
```

---

## 4. Track 1 — Robinhood MCP Integration

### 4.1 Overview

Replace unofficial `robin_stocks` (email/password/TOTP) with Robinhood's official agentic MCP endpoint. The broker key `"ROBINHOOD"` stays the same throughout the stack — only the transport layer changes.

```
CURRENT:                                PROPOSED:
────────────────────────────────────    ────────────────────────────────────
robin_stocks library                    https://agent.robinhood.com/mcp/trading
email + password + TOTP                 OAuth 2.1 with PKCE
Unofficial — breaks without notice      Official Robinhood agentic API
Hidden in Settings (display:none)       Visible in Settings (OAuth flow UI)
```

### 4.2 New File: `src/brokers/robinhood_mcp_broker.py`

```
RobinhoodMCPBroker
│
├── connect()
│     OAuth 2.1 PKCE authorization flow
│     Exchanges code for access + refresh tokens
│     Stores refresh token via broker_credentials_service (Fernet encrypted)
│     Returns True if connected
│
├── disconnect()
│     Revokes token, clears stored credentials
│
├── is_connected()
│     Returns True if access token valid (checks expiry)
│
├── reconnect()
│     Uses stored refresh token → fetches new access token
│     Called automatically on 401 response
│
├── place_order(symbol, qty, action, order_type, price=None, **kwargs)
│     POST /mcp/trading/orders
│     action: 'BTO'/'STC' → side: 'buy'/'sell'
│     order_type: 'market'/'limit'
│     Equities only (no options until Robinhood MCP adds support)
│     Returns order_id
│
├── cancel_order(order_id)
│     DELETE /mcp/trading/orders/{order_id}
│
├── get_positions()
│     GET /mcp/trading/positions
│     Returns list of position dicts normalized to bot schema
│
├── get_quote(symbol)
│     GET /mcp/trading/quotes/{symbol}
│     Returns {last, bid, ask, volume}
│
├── get_account_info()
│     GET /mcp/trading/account
│     Returns {buying_power, portfolio_value, account_id}
│
└── get_order_status(order_id)
      GET /mcp/trading/orders/{order_id}
      Returns {status, filled_qty, avg_price}

Constants:
  BASE_URL = "https://agent.robinhood.com/mcp/trading"
  TOKEN_URL = "https://api.robinhood.com/oauth2/token"
  AUTH_URL  = "https://robinhood.com/oauth2/authorize"

Token storage keys (broker_credentials_service):
  'robinhood_mcp_access_token'    ← short-lived, not persisted
  'robinhood_mcp_refresh_token'   ← persisted Fernet-encrypted
  'robinhood_mcp_account_id'      ← agentic sub-account ID
```

### 4.3 Settings UI Changes (`gui_app/templates/settings.html`)

**Change:** Remove `style="display:none"` from the Robinhood card (line 773). Replace the email/password/TOTP form content with an OAuth 2.1 flow UI.

```
BEFORE (hidden, unofficial API):          AFTER (visible, OAuth 2.1):
──────────────────────────────────        ──────────────────────────────────────
🪶 Robinhood (LIVE Only) [hidden]         🪶 Robinhood MCP (Agentic Account)
─────────────────────────────────         ──────────────────────────────────────
Email:    [________________]              ✅ Official Robinhood MCP API
Password: [________________]              ─────────────────────────────────────
TOTP:     [________________]              Connection status: 🔴 Not connected
[Save] [Connect]                          ─────────────────────────────────────
                                          [🔗 Authorize with Robinhood]
                                            Opens Robinhood OAuth page in browser
                                            After approval → token stored encrypted
                                          ─────────────────────────────────────
                                          Account:       [Agentic sub-account ▼]
                                          Buying Power:  $2,840.00
                                          Max per trade: [500] (configurable)
                                          ─────────────────────────────────────
                                          ⚠️ Equities only (options not yet
                                             supported by Robinhood MCP beta)
                                          [Disconnect]
```

### 4.4 Backend Routes (`gui_app/routes.py` additions)

```python
@app.route('/api/robinhood/oauth-start', methods=['GET'])
# Generate PKCE code_verifier + code_challenge
# Return {auth_url, state, code_verifier} — state + verifier stored in session

@app.route('/api/robinhood/oauth-callback', methods=['POST'])
# Receive {code, state} from frontend after redirect
# Exchange code for tokens using stored code_verifier
# Encrypt and store refresh_token via broker_credentials_service
# Return {success, account_id, buying_power}

@app.route('/api/robinhood/status', methods=['GET'])
# Test connection, return {connected, buying_power, account_id, account_type}

@app.route('/api/robinhood/disconnect', methods=['POST'])
# Delete stored tokens, update broker status
```

### 4.5 Selfbot Integration (`src/selfbot_webull.py`)

In the broker initialization section (near the other broker inits), add:

```python
# Initialize Robinhood MCP broker
self.robinhood_broker = None
try:
    from src.brokers.robinhood_mcp_broker import RobinhoodMCPBroker
    rh_refresh = broker_credentials_service.get_api_keys_extended().get('robinhood_mcp_refresh_token')
    if rh_refresh:
        self.robinhood_broker = RobinhoodMCPBroker(loop=self.loop)
        connected = await asyncio.wait_for(self.robinhood_broker.connect(), timeout=30.0)
        if connected:
            account_info = await self.robinhood_broker.get_account_info()
            set_broker_status('robinhood', True, 'connected', account_info=account_info)
            from src.services.broker_health_monitor import get_health_monitor
            get_health_monitor().update_broker_status('ROBINHOOD', True, account_info=account_info)
except Exception as e:
    print(f"[ROBINHOOD_MCP] ⚠️ Init failed: {e}")
    self.robinhood_broker = None
```

---

## 5. Track 2 — Enhanced NL Signal Pipeline

### 5.1 New Regex Patterns (add to `src/services/signal_format_registry.py`)

These move Phoenix and ProTrader signals from AI Tier 5 (~150ms) to regex Tier 2 (~2ms).

```python
# ── PHOENIX CHANNEL ─────────────────────────────────────────────

# FORMAT A: "@everyone TICKER over PRICE\nSL X%"
# Handles: @everyone, role pings, Daytrades prefix, no-space typo
PHOENIX_BTO = re.compile(
    r'(?:@everyone|<@&\d+>|Daytrades)\s*([A-Z]{2,6})\s+over\s+([\d.]+)'
    r'(?:\s*\n\s*[Ss][Ll]\s+([\d.]+%?))?',
    re.IGNORECASE
)

# FORMAT B: "selling X% [here] TICKER" (partial exit)
PHOENIX_PARTIAL_SELL = re.compile(
    r'selling\s+(\d{1,3})%\s+(?:here\s+)?([A-Z]{2,6})',
    re.IGNORECASE
)

# "leaving X% [here] TICKER" (keep runner — inverse of selling)
PHOENIX_LEAVE_RUNNER = re.compile(
    r'leaving\s+(\d{1,3})%\s+(?:here\s+)?([A-Z]{2,6})',
    re.IGNORECASE
)

# FORMAT C: Full exit NL patterns
PHOENIX_OUT_OF = re.compile(
    r'(?:getting\s+)?out\s+(?:of|witha?\s+loss(?:\s+of)?)\s+(?:everything|([A-Z]{2,6}))',
    re.IGNORECASE
)
PHOENIX_CLOSING = re.compile(
    r'closing\s+my\s+position\s+with\s+([A-Z]{2,6})',
    re.IGNORECASE
)
PHOENIX_SL_HIT = re.compile(
    r'([A-Z]{2,6})\s+hit\s+my\s+SL|hit\s+my\s+SL\s+with\s+([A-Z]{2,6})',
    re.IGNORECASE
)

# FORMAT D: Watchlist
PHOENIX_WATCH = re.compile(
    r'(?:@everyone|<@&\d+>)\s*(?:will\s+be\s+)?watchin[gG]?\s+'
    r'([A-Z]{2,6}(?:[\s,]+(?:and\s+)?[A-Z]{2,6})*)',
    re.IGNORECASE
)

# ── PROTRADER CHANNEL ────────────────────────────────────────────

# FORMAT E: Structured entry block
PROTRADER_ENTRY_BLOCK = re.compile(
    r'Ticker:\s+([A-Z]{2,6})\s*\n\s*Entry\s+range:\s+'
    r'(?:Break\s+of\s+)?([\d.]+(?:\s*-\s*[\d.]+)?)',
    re.IGNORECASE | re.MULTILINE
)
PROTRADER_TARGETS = re.compile(
    r'Targs?:\s+([\d.,\-\s]+)',
    re.IGNORECASE
)
PROTRADER_QTY = re.compile(
    r'Buying\s+(\d+)\s+shares',
    re.IGNORECASE
)
PROTRADER_SL_BELOW = re.compile(
    r'SL\s+below\s*:?\s*([\d.]+)',
    re.IGNORECASE
)

# FORMAT F: Cancel/invalidate signal
PROTRADER_CANCEL = re.compile(
    r'(?:cancel\s+(?:the\s+)?([A-Z]{2,6})\s+alert'
    r'|([A-Z]{2,6})\s*[-–]\s*(?:please\s+cancel|cancel\s+this|We\s+cutting\s+this))',
    re.IGNORECASE
)
```

### 5.2 ParsedSignal Extensions Needed

Add to `ParsedSignal` dataclass in `signal_parsing_pipeline.py`:

```python
trim_pct: Optional[int] = None        # for FORMAT B: selling 80% → trim_pct=80
runner_pct: Optional[int] = None      # for PHOENIX_LEAVE_RUNNER: leaving 15%
cancel_symbol: Optional[str] = None   # for FORMAT F: cancel signal
```

### 5.3 SignalSource Additions

Add to `SignalSource` enum:

```python
REGISTRY_PHOENIX = "phoenix"
REGISTRY_PROTRADER = "protrader"
```

### 5.4 Position-Aware STC Auto-Approve Gate

**Location:** `src/selfbot_webull.py` — in the AI fallback block around line 14133, add a new execution path for AI `action='STC'`:

```python
# ── After existing AI BTO conditional handler (line ~14200) ──

elif _ai_action == 'STC' and _ai_sym:
    # Position-aware auto-approve: closing a confirmed open position is safe
    _open_pos = self._get_open_position(channel_id, _ai_sym)
    if _open_pos:
        # Position exists → auto-approve and execute STC
        print(f"[AI_FALLBACK] ✓ NL STC auto-approved: {_ai_sym} (open position confirmed)")
        _stc_signal = {
            'action': 'STC',
            'symbol': _ai_sym,
            'asset': _ai_result.get('asset', 'stock'),
            'is_trim': _ai_result.get('is_trim', False),
            'trim_pct': _ai_result.get('trim_pct'),
            'qty': _open_pos.get('quantity', 1) if not _ai_result.get('is_trim') else None,
            '_ai_fallback': True,
            '_ai_confidence': _ai_conf,
            '_position_verified': True,
        }
        for _stc_broker in cond_brokers:
            await self._execute_exit_signal(_stc_signal, _stc_broker, channel_info)
    else:
        # No confirmed open position → flag for review, do not execute
        print(f"[AI_FALLBACK] ⚠️ NL STC for {_ai_sym} — no open position found, skipping auto-execute")
        self._notify_admin_review(_ai_signal, reason="NL STC without confirmed open position")
```

**Helper needed:** `_get_open_position(channel_id, symbol)` — queries position cache for open position matching symbol in the given channel's brokers.

### 5.5 Signal Cancel Handler (`src/services/conditional_orders/router.py`)

Add method to `ConditionalOrderRouter`:

```python
def cancel_by_symbol(self, channel_id: str, symbol: str) -> int:
    """Cancel all pending conditional orders for a symbol in a channel.
    Returns count of cancelled orders."""
    cancelled = 0
    with self._lock:
        for order_id, order in list(self._pending_orders.items()):
            if (order.get('channel_id') == channel_id
                    and order.get('symbol', '').upper() == symbol.upper()
                    and order.get('status') in ('PENDING', 'ACTIVE_MONITORING')):
                self._cancel_order(order_id)
                cancelled += 1
    if cancelled:
        print(f"[COND_ROUTER] ✓ Cancelled {cancelled} pending order(s) for {symbol} in channel {channel_id}")
    return cancelled
```

### 5.6 AI Few-Shot Examples to Add (`src/services/ai_signal_parser.py`)

Add these to `_few_shot_examples` or `_registry_examples_str` in `_build_system_prompt()`:

```python
# Add to KNOWN CHANNEL FORMATS section of the system prompt:

"""
PHOENIX CHANNEL FORMATS (Arlette):
Input: "@everyone TGE over 1.43\nSL 10%"
Output: {"action":"BTO","asset":"stock","symbol":"TGE","is_conditional":true,
         "trigger_type":"over","trigger_price":1.43,"stop_loss_pct":10,"confidence":0.98}

Input: "@everyone selling 80% CCTG"
Output: {"action":"STC","asset":"stock","symbol":"CCTG","is_trim":true,"trim_pct":80,"confidence":0.97}

Input: "selling 85% here ELTX watching vol"
Output: {"action":"STC","asset":"stock","symbol":"ELTX","is_trim":true,"trim_pct":85,"confidence":0.95}

Input: "out of TGE  dont like where its going"
Output: {"action":"STC","asset":"stock","symbol":"TGE","is_trim":false,"confidence":0.93}

Input: "out witha loss AHMA"
Output: {"action":"STC","asset":"stock","symbol":"AHMA","is_trim":false,"confidence":0.92}

Input: "OBAI hit my SL"
Output: {"action":"STC","asset":"stock","symbol":"OBAI","is_trim":false,"confidence":0.90}

Input: "closing my position with CAST now for the remaining shares"
Output: {"action":"STC","asset":"stock","symbol":"CAST","is_trim":false,"confidence":0.94}

Input: "@everyone watching ICCM"
Output: {"action":null,"asset":"stock","symbol":"ICCM","confidence":0.85,"rationale":"Watchlist mention only, no entry price or trigger — informational"}

Input: "profits 6"
Output: {"action":null,"confidence":0.1,"rationale":"Profit update with no ticker context"}

PROTRADER CHANNEL FORMATS:
Input: "Ticker: ICCM\nEntry range: Break of 5.30\nTargs: 5.35-5.40-5.45-5.50\nBuying 50 shares in 10k account"
Output: {"action":"BTO","asset":"stock","symbol":"ICCM","is_conditional":true,
         "trigger_type":"over","trigger_price":5.30,
         "profit_targets":[5.35,5.40,5.45,5.50],"qty":50,"confidence":0.97}

Input: "cancel the AMST alert.. ran up from 1.75"
Output: {"action":"CANCEL","asset":"stock","symbol":"AMST","confidence":0.96}

Input: "RUBI- We cutting this.. even 2.78 didnt hold.. small loss."
Output: {"action":"CANCEL","asset":"stock","symbol":"RUBI","confidence":0.93}

Input: "ICCM 8.84 ✅"
Output: {"action":null,"confidence":0.05,"rationale":"Target hit update — not a new signal"}
"""
```

---

## 6. Track 3 — AI Agent Platform (SENTINEL/ANALYST/EXECUTOR)

Full spec in `docs/AI_AGENT_PLATFORM.md`. Summary of what needs to be built:

### 6.1 New Files

```
src/agents/
├── agent_manager.py       Lifecycle: start/stop/health-check all agents as asyncio tasks
├── sentinel_agent.py      Discord monitor → noise filter → Claude conviction → watchlist
├── analyst_agent.py       VWAP/Fib scoring → 0-100 score → threshold routing
└── executor_agent.py      Robinhood MCP execution → risk handoff

src/services/
└── vwap_fib_engine.py     VWAP reclaim detection, Fibonacci retrace/extension levels

gui_app/templates/
└── ai_agents.html         Dashboard: agent status, watchlist, trade log, decision log
```

### 6.2 Execution Routing (EXECUTOR)

```
EXECUTOR receives approved trade:
    │
    ├── asset_type == 'stock'  →  Robinhood MCP broker  (Track 1)
    └── asset_type == 'option' →  Schwab or Tastytrade  (Robinhood MCP doesn't support options yet)
```

### 6.3 Risk Handoff

After EXECUTOR places an order, call existing risk engine registration:
```python
# Same handoff as any other broker order
await self._notify_risk_engine(symbol, broker='ROBINHOOD', entry_price=fill_price, qty=fill_qty)
```

### 6.4 Safety Integration

All 7 safety layers from `docs/AI_AGENT_PLATFORM.md` use existing infrastructure:
- Daily P&L Limit → existing `DailyPnLLimitService`
- Circuit Breaker → existing `circuit_breaker.is_triggered()`
- Channel execute_enabled → existing `channel_info.get('execute_enabled')`

### 6.5 New Routes (`gui_app/routes.py`)

```python
GET  /api/agents/status            → all 3 agents health + mode (AUTO/ALERT/PAPER)
POST /api/agents/{name}/start      → start specific agent
POST /api/agents/{name}/stop       → stop specific agent
GET  /api/agents/watchlist         → current watchlist with scores
GET  /api/agents/trades            → AI agent trade history + P&L
POST /api/agents/mode              → set execution mode (auto/alert/paper)
```

---

## 7. Track 4 — Latency Architecture

### 7.1 Current vs Proposed Latency

```
CURRENT — Sequential:
  Tier 1 regex   →  ~1ms  (hit → done)
  Tier 2 regex   →  ~2ms  (hit → done)
  Tier 3 parser  →  ~3ms  (hit → done)
  Tier 4 regex   →  ~4ms  (hit → done)
  AI fallback    →  ~150-200ms  ← all NL signals go here

PROPOSED — Concurrent + Cached:
  Known format (regex Tier 2):     2ms    ← 95%+ after format learning
  AI cache hit (repeat NL):       <1ms   ← all repeats of known NL
  AI cold call (new NL format):   150ms  ← only first occurrence per format
  After N=3 confirmations:         2ms   ← format promoted to Tier 2 forever
```

### 7.2 Format Learning Pipeline

After AI successfully parses a new format N=3 times with confidence ≥ 0.9, automatically add it to `SignalFormatRegistry` as a learned pattern.

**Hook in `src/services/format_trainer.py`:**
```python
class FormatLearner:
    def record_ai_success(self, raw_text: str, result: AIParseResult, channel_id: str):
        """Track AI parsing successes. After N confirmations, promote to registry."""
        key = self._fingerprint(raw_text)  # strips numbers, keeps structure
        count = self._increment(key, channel_id)
        if count >= 3 and result.confidence >= 0.9:
            self._promote_to_registry(raw_text, result, channel_id)

    def _promote_to_registry(self, example: str, result: AIParseResult, channel_id: str):
        """Generate regex from example and add to SignalFormatRegistry."""
        # Replace specific prices with \d+\.?\d* pattern
        # Replace specific symbols with [A-Z]{2,6} pattern
        # Store as REGISTRY_LEARNED source
        ...
```

### 7.3 Channel Pre-Warming on Bot Start

```python
async def _prewarm_ai_cache(self):
    """Pre-populate AI result cache from recent signal history at startup."""
    channels_with_ai = self._get_channels_with_ai_enabled()
    for channel_id in channels_with_ai:
        recent = db.get_recent_signals(channel_id, limit=50, days=7)
        tasks = [ai_parser.parse(msg.raw_text) for msg in recent
                 if not ai_parser.cache.get(msg.raw_text)]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
            print(f"[AI_PREWARM] ✓ {channel_id}: {len(tasks)} signals cached")
```

Call from `selfbot_webull.py` during initialization, after brokers connect.

### 7.4 Concurrent Tier Evaluation (Future Optimization)

For channels where AI is enabled and regex Tier 1-4 has a low hit rate, start AI call concurrently with regex evaluation:

```python
async def parse_concurrent(self, text, ...):
    """Start AI call at T=0, run regex Tiers 1-4 simultaneously."""
    ai_task = asyncio.ensure_future(self._ai_parser.parse(text))  # starts immediately

    regex_result = self._try_tiers_1_to_4(text)  # synchronous, ~2ms
    if regex_result:
        ai_task.cancel()  # regex won, cancel AI
        return regex_result

    ai_result = await ai_task  # already running, just await
    return ai_result
```

**Net effect:** AI latency for NL signals becomes ~150ms from Discord message arrival, not ~4ms + 150ms. Saves 4ms — marginal but it's the correct architecture.

---

## 8. What Does NOT Change

These files/systems require **zero modifications**:

| Component | Reason unchanged |
|-----------|-----------------|
| `src/services/conditional_orders/base.py` | CANCEL action → only adds `cancel_by_symbol` to router |
| `src/risk/position_monitor.py` | NL STC uses existing `_execute_exit()` method |
| `src/risk/risk_engine.py` | No changes needed |
| `src/risk/risk_types.py` | No changes needed |
| All broker files (Schwab, Webull, IBKR, Alpaca, Tastytrade) | RH MCP is additive |
| `src/services/unified_price_hub.py` | No changes |
| Existing regex patterns in SignalFormatRegistry | Only additions, no removals |
| `src/services/signal_parsing_pipeline.py` | Only adds new regex, new `trim_pct` field |
| AI parser security gates | `admin_approved`, `confidence >= 0.8` gates unchanged |
| 5-tier pipeline ordering | Only adds patterns to existing Tier 2 |
| Deduplication logic | No changes |

---

## 9. Implementation Phases

### Phase 1 — Week 1: Robinhood MCP Foundation

**Deliverables:**
- [ ] `src/brokers/robinhood_mcp_broker.py` — OAuth 2.1, place_order, get_positions
- [ ] `gui_app/templates/settings.html` — unhide RH card, replace form with OAuth UI
- [ ] `gui_app/routes.py` — `/api/robinhood/oauth-start`, `/oauth-callback`, `/status`, `/disconnect`
- [ ] `gui_app/broker_credentials_service.py` — add `robinhood_mcp_refresh_token` storage
- [ ] `src/selfbot_webull.py` — add RH MCP broker initialization block

**Validation:**
- OAuth flow completes → token stored encrypted
- `get_positions()` returns normalized position list
- `place_order()` submits equity market order
- Health monitor registers `ROBINHOOD` at connect time

### Phase 2 — Week 2: Phoenix + ProTrader Regex + NL Exits

**Deliverables:**
- [ ] Add `PHOENIX_BTO`, `PHOENIX_PARTIAL_SELL`, `PHOENIX_FULL_EXIT`, `PHOENIX_WATCH` to `SignalFormatRegistry`
- [ ] Add `PROTRADER_ENTRY_BLOCK`, `PROTRADER_CANCEL` to `SignalFormatRegistry`
- [ ] Add `trim_pct`, `runner_pct`, `cancel_symbol` fields to `ParsedSignal`
- [ ] Add `REGISTRY_PHOENIX`, `REGISTRY_PROTRADER` to `SignalSource` enum
- [ ] Implement position-aware STC auto-approve gate in `selfbot_webull.py`
- [ ] Add `cancel_by_symbol()` to `ConditionalOrderRouter`
- [ ] Add Phoenix + ProTrader few-shot examples to AI system prompt
- [ ] Add NL exit examples to AI system prompt

**Validation:**
- Phoenix `@everyone TGE over 1.43\nSL 10%` → parsed in <5ms, creates conditional order
- Phoenix `selling 80% CCTG` → parsed, position-aware STC fires if CCTG open
- Phoenix `out of TGE` → position-aware STC fires if TGE open
- ProTrader structured block → parsed, conditional order created with targets
- ProTrader `cancel the AMST alert` → pending conditional for AMST cancelled
- Atlantic Trading bot messages → filtered by author_id

### Phase 3 — Week 3: AI Agent Platform Foundation

**Deliverables:**
- [ ] `src/agents/agent_manager.py` — async task lifecycle management
- [ ] `src/agents/sentinel_agent.py` — TrendVision monitor, noise filter, watchlist DB ops
- [ ] `src/services/vwap_fib_engine.py` — VWAP/Fibonacci calculations using UPH data
- [ ] `gui_app/templates/ai_agents.html` — dashboard skeleton (agent status + watchlist table)
- [ ] `gui_app/routes.py` — agent status/start/stop/watchlist routes

**Validation:**
- SENTINEL correctly filters noise (MC > 50M rejected, RV < 3x rejected)
- Watchlist DB table populated from TrendVision alerts
- Dashboard shows agent health and watchlist

### Phase 4 — Week 4: Full AI Platform + Latency Optimization

**Deliverables:**
- [ ] `src/agents/analyst_agent.py` — VWAP/Fib scoring, 0-100 score, score persistence
- [ ] `src/agents/executor_agent.py` — Robinhood MCP execution, slippage guard, risk handoff
- [ ] Format learning pipeline in `src/services/format_trainer.py`
- [ ] Channel AI cache pre-warming on bot start
- [ ] Concurrent Tier evaluation (optional, low-priority optimization)
- [ ] AI agents GUI: score threshold display, trade log, decision log

**Validation:**
- Score ≥ 80 triggers automatic Robinhood MCP order
- Score 60–79 sends relay/Discord alert, awaits approval
- After 3 AI parses of same format → format auto-promoted to Tier 2
- Bot restart → AI cache pre-warmed from last 50 signals per channel

---

## 10. File Map — All New and Changed Files

### New Files
| File | Purpose | Phase |
|------|---------|-------|
| `src/brokers/robinhood_mcp_broker.py` | Robinhood MCP broker implementation | 1 |
| `src/agents/agent_manager.py` | AI agent lifecycle manager | 3 |
| `src/agents/sentinel_agent.py` | TrendVision signal filter + watchlist | 3 |
| `src/agents/analyst_agent.py` | VWAP/Fib scoring engine | 4 |
| `src/agents/executor_agent.py` | Robinhood MCP trade execution | 4 |
| `src/services/vwap_fib_engine.py` | Technical analysis calculations | 3 |
| `gui_app/templates/ai_agents.html` | AI agents dashboard page | 3 |

### Modified Files
| File | Changes | Phase |
|------|---------|-------|
| `gui_app/templates/settings.html` | Unhide + replace RH card with OAuth UI | 1 |
| `gui_app/routes.py` | RH MCP OAuth routes + agent API routes | 1 + 3 |
| `gui_app/broker_credentials_service.py` | RH MCP token storage | 1 |
| `src/selfbot_webull.py` | RH MCP broker init + NL STC auto-approve gate | 1 + 2 |
| `src/services/signal_format_registry.py` | Phoenix + ProTrader regex patterns | 2 |
| `src/services/signal_parsing_pipeline.py` | `ParsedSignal` new fields + new SignalSource enums | 2 |
| `src/services/ai_signal_parser.py` | New few-shot examples for Phoenix/ProTrader/NL exits | 2 |
| `src/services/conditional_orders/router.py` | `cancel_by_symbol()` method | 2 |
| `src/services/format_trainer.py` | Format learning pipeline | 4 |

---

## 11. Already Fixed — Webull Health Monitor

**Fixed in commit `b0315b1e` (2026-06-18)**

**Bug:** WEBULL_OFFICIAL conditional orders rejected at startup with:
```
[HEALTH] ❌ Trade rejected (ID=1075): CAST - Broker WEBULL_OFFICIAL not tracked - waiting for first sync
```

**Root cause:** `set_broker_status()` writes to the GUI status dict only — `BrokerHealthMonitor._broker_states` remained empty for `WEBULL_OFFICIAL*`. The `_prewarm_account_caches()` async path ran too late. Any conditional order firing in the ~15s window between broker connect and first sync was rejected.

**Fix applied (`selfbot_webull.py:8161–8167`):**
```python
set_broker_status('webull_official', True, 'connected', account_info=account_info)
try:
    from src.services.broker_health_monitor import get_health_monitor
    _wo_hm_key = 'WEBULL_OFFICIAL_PAPER' if paper_mode else 'WEBULL_OFFICIAL_LIVE'
    get_health_monitor().update_broker_status(_wo_hm_key, True, account_info=account_info)
    _original_print(f"[WEBULL_OFFICIAL] ✓ Health monitor registered as {_wo_hm_key}", flush=True)
except Exception as _hm_err:
    _original_print(f"[WEBULL_OFFICIAL] ⚠️ Health monitor registration failed: {_hm_err}", flush=True)
```

**Secondary investigation needed (not yet fixed):**
- `BrokerSyncService` at startup only lists `['Webull']` in its broker list — `webull_official_broker` not being picked up by the sync service at first cycle. Verify `broker_sync_service.py:362` — check if `self.broker_manager.webull_official_broker` attribute is set before first sync runs.
