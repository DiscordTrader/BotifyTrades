# BotifyTrades AI Agent Platform — Penny Stock Intelligence

> Three-agent pipeline: Discord signal filtering → Technical analysis → Robinhood MCP execution

**Architecture Presentation:** `docs/ai_agent_architecture.html`
**Version:** 11.1.2 | **Status:** Architecture Complete, Implementation Pending

---

## Overview

Multi-agent AI system that monitors TrendVision penny stock alerts from Discord channel `1507850557505671209`, filters noise, performs technical analysis (VWAP, Fibonacci, momentum), and autonomously executes trades on Robinhood via official MCP endpoint.

```
Discord Channel ──→ SENTINEL ──→ ANALYST ──→ EXECUTOR ──→ Robinhood
  (TrendVision)     (Filter)     (Score)     (Trade)      (MCP)
```

---

## Alert Format (TrendVision)

Three alert types from the channel:

```
# Breakout/Momentum Alert
GLXG  • #3 · BREAKOUT · ↑58% · $2.05 • FT 1.7M · MC 2.0M · RV 65x · 1V 179K

# Short/Borrow Data (noise — don't trade, info only)
🔥 DSS  · 0 BORROW · CTB: 0.74% | SI: 6.36%

# Whale Alert
🐋 DSS  - LARGE WHALE · Direction: → | Price: 0.69 | Shares: 425.25K | Value: $292.96K
```

Parsed fields: `symbol, rank, signal_type (BREAKOUT/MOMENTUM), change_pct, price, float, market_cap, relative_volume, one_min_volume, news_link`

---

## Agent 1 — SENTINEL (Signal Filter)

**Purpose:** Monitor Discord channel, parse alerts, reject noise, build dynamic watchlist

### Noise Filter Rules

| Filter | Reject When | Why |
|--------|------------|-----|
| Market Cap | MC > $50M | Not a penny stock |
| Float | FT > 50M | Too liquid, no squeeze potential |
| Relative Volume | RV < 3x | No conviction / dead volume |
| Price Range | Price > $20 or < $0.10 | Outside penny stock range |
| Signal Type | Borrow/CTB only | Info alert, not actionable |
| Change % | ↑ > 200% | Overextended, chase risk |

### Dynamic Watchlist

- **Auto-Add:** BREAKOUT/MOMENTUM alerts passing all filters + Claude AI approval
- **Auto-Promote:** Whale activity on watchlisted ticker → priority bump
- **Auto-Expire:** Removed after 30min if no re-alert
- **Auto-Remove:** Volume dies (RV < 2x) or price drops below entry zone
- **Max Size:** 10 tickers — lowest-scored removed first

### Watchlist Schema

```
symbol, price, change_pct, signal_type, rank, float, market_cap,
relative_volume, alert_count, momentum_score (1-10 from Claude),
whale_activity, entry_zone, status (WATCHING/SETUP/TRIGGERED/EXPIRED),
added_at, expires_at
```

---

## Agent 2 — ANALYST (Technical Analysis)

**Purpose:** Continuously monitor watchlist tickers, calculate technical levels, score trade setups

### Analysis Layers

1. **VWAP Engine** — Reclaim/hold/distance analysis using UPH streaming data
2. **Fibonacci Analyzer** — 38.2/50/61.8% retracement for dip buy zones, 161.8/261.8% extensions for targets
3. **Momentum Scanner** — Volume surges, consolidation breaks, higher lows, RV decay detection
4. **Whale Correlation** — Large whale buys during consolidation = smart money signal

### Setup Scoring (0-100)

| Factor | Weight | Signal |
|--------|--------|--------|
| VWAP Position | 20% | Above = bullish, reclaim = strongest |
| Fib Zone | 15% | At 50-61.8% retrace = high score |
| Volume Profile | 20% | RV > 20x + rising = max points |
| Momentum Trend | 15% | Consecutive higher-rank alerts |
| Float Scarcity | 10% | FT < 5M + MC < 10M = squeeze potential |
| Whale Activity | 10% | Buy-side whale = +20 points |
| Claude AI Conviction | 10% | AI expert assessment (1-10 scaled) |

### Score Thresholds

- **80-100:** AUTO-EXECUTE — Agent 3 triggers immediately
- **60-79:** ALERT — Notify user via relay/Discord, await approval
- **40-59:** WATCH — Continue monitoring, re-score each cycle
- **0-39:** DROP — Remove from watchlist, log reason

### Overextension Guard

Any ticker with ↑ > 100% from open AND declining RV → auto-capped at score 50 regardless of other factors.

---

## Agent 3 — EXECUTOR (Robinhood MCP)

**Purpose:** Execute trades on Robinhood via official MCP endpoint, hand off to risk engine

### Robinhood MCP Connection

- **Endpoint:** `https://agent.robinhood.com/mcp/trading`
- **Auth:** OAuth 2.1 with PKCE → Robinhood 2FA phone approval
- **Account:** Dedicated agentic sub-account (separate from main)
- **Assets:** Equities only (beta) — options/crypto coming soon
- **Order Types:** Market, Limit, Extended Hours
- **Limitation:** Cannot use IRA/Roth IRA — individual brokerage only

### Execution Rules

- Position sizing: % of agentic account buying power (configurable per score tier)
- Entry: Limit order at VWAP/Fib level from Agent 2
- Slippage guard: Reject if price moved > 5% since analysis
- Max concurrent positions: 3 (configurable)
- Daily trade limit: Integrates with existing Daily P&L Limit service

### Risk Handoff (Existing Infrastructure)

After entry, the existing `position_monitor.py` risk engine manages the position:
- **Stop Loss:** Set at Fib/VWAP support from Agent 2 (typically -8% to -15%)
- **Profit Targets:** Tiered exits at Fib extensions (30% / 50% / 100% trim schedule)
- **Trailing Stop:** Activates after PT1 hit
- **Leave Runner:** Keep 10-25% for multi-day holds on low-float runners
- **Evaluation Cycle:** Every ~1s (critical for penny stock speed)

---

## Safety Architecture (7 Layers)

```
Layer 1: Agent Limits      — Max 3 positions | Max $500/trade | Max 5 trades/day
Layer 2: Score Gate         — Only score ≥ 80 auto-executes | 60-79 needs approval
Layer 3: Slippage Guard     — Reject if price > 5% from Agent 2 target
Layer 4: Risk Engine        — Existing SL/PT/trailing monitors every ~1s
Layer 5: Daily P&L Limit    — $X daily loss → ALL agents stopped
Layer 6: Circuit Breaker    — Emergency kill switch — stops agents + closes positions
Layer 7: Robinhood Account  — Dedicated agentic account with capped funds
```

---

## Existing Bot Integration

| Feature | How AI Agents Use It |
|---------|---------------------|
| Unified Price Hub | Real-time streaming quotes for VWAP/Fib calculations |
| Risk Engine (`position_monitor.py`) | Manages PT/SL/trailing after Agent 3 entry |
| Daily P&L Limits | Max daily trades + loss cap blocks all agents when hit |
| Circuit Breaker | Emergency kill switch for all agents |
| Broker Sync | Reconciles Robinhood positions with bot state every 30s |
| Mobile Relay | Push alerts when high-score setups detected |
| Chat Assistant | Ask Claude about agent status, decisions, watchlist |
| Trade History DB | Learning loop — P&L outcomes feed back into scoring model |

---

## AI Dashboard (Admin → AI Agents)

New GUI page with four panels:

1. **Agent Status Panel** — Live health of all 3 agents, start/stop controls, execution mode toggle (AUTO/ALERT/PAPER)
2. **Live Watchlist View** — Real-time table of all watched tickers with scores, VWAP distance, entry zones
3. **Trade Log & P&L** — AI agent trade history with entry reason, score snapshot, running P&L stats
4. **AI Decision Log** — Explainable AI — every filter/reject/trigger decision with Claude's reasoning

---

## Enhanced Features

### Learning Loop
After each trade closes, outcome feeds back into scoring weights. Tracks which signal types, ranks, float/MC ranges produce best results. Auto-adjusts scoring weights monthly.

### Whale Flow Intelligence
Aggregate whale alerts per ticker. Multiple whales same direction = accumulation signal. Whale sell while bot is long = early exit warning. Track whale prediction accuracy over time.

### Multi-Channel Fusion
Same ticker in 3+ Discord channels within 5min = conviction multiplier. Leverages existing channel mapping infrastructure.

### Multi-Broker Routing
Route penny stocks → Robinhood (commission-free), options → Schwab/Tastytrade, after-hours → IBKR. Agent 3 selects best broker per trade.

---

## Implementation Phases

| Phase | Timeline | Deliverables | Validation |
|-------|----------|-------------|------------|
| 1. Foundation | Week 1-2 | TrendVision parser, noise filter, watchlist DB, dashboard skeleton | Parser handles all alert formats |
| 2. Intelligence | Week 3-4 | VWAP/Fib engine, scoring system, Claude AI integration, whale aggregation | Sensible scores on historical data |
| 3. Execution | Week 5-6 | Robinhood MCP client, position sizing, risk handoff, P&L limits | Paper-mode with logged orders |
| 4. Live & Learn | Week 7+ | Live trading ($100-200/trade), learning loop, mobile alerts | 2-week performance review before scaling |

---

## Key Files (Planned)

```
src/agents/
├── sentinel_agent.py        # Agent 1: Discord monitor, parser, noise filter
├── analyst_agent.py         # Agent 2: VWAP, Fib, momentum, scoring engine
├── executor_agent.py        # Agent 3: Robinhood MCP execution
├── agent_manager.py         # Lifecycle: start/stop/monitor all agents
├── watchlist_service.py     # Dynamic watchlist CRUD + expiration
├── setup_scorer.py          # 0-100 scoring with configurable weights
└── learning_service.py      # P&L feedback → weight adjustment

src/services/
├── robinhood_mcp_client.py  # MCP protocol client for agent.robinhood.com
└── vwap_fib_engine.py       # Technical analysis calculations

gui_app/templates/
└── ai_agents.html           # Dashboard page (Admin → AI Agents)

docs/
├── ai_agent_architecture.html  # Premium presentation page
└── AI_AGENT_PLATFORM.md        # This document
```

---

## Discord Channel

- **Channel ID:** `1507850557505671209`
- **Bot:** TrendVision (APP)
- **Alert Types:** Breakout, Momentum, Borrow/Short, Whale
- **Frequency:** ~5-20 alerts/hour during market hours

---

## Technical Notes

- All agents run as async tasks inside the existing bot event loop
- Watchlist stored in SQLite (`bot_data.db`) — same DB as rest of bot
- Claude AI calls use existing `chat_assistant.py` infrastructure
- MCP client uses `httpx` (already a dependency) for HTTP transport
- Agents communicate via shared watchlist DB — no direct inter-agent messaging
- Each agent logs to `[SENTINEL]` / `[ANALYST]` / `[EXECUTOR]` prefixes
