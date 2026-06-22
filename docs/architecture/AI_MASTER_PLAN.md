# AI Trading Intelligence — Master Implementation Plan

**Date**: 2026-06-20
**Version**: 2.0 — Architect-reviewed, rewritten for actual bot stack
**Status**: Ready for phased implementation
**Stack**: Python 3.11 / Flask / SQLite / ib_insync / Telethon / discord.py

---

## Executive Summary

7 AI modules deployed across 4 phases, each independently shippable with feature flags. Phase 0 (foundation) enables all subsequent phases. Phase 1 (signal intelligence) delivers the fastest user value. Phase 2 (adaptive risk) provides the biggest P&L impact. Phase 3 (AI co-pilot) ties everything together with natural language control. Total: ~4,500 lines of new Python across 12 new files + 8 new DB tables. Zero changes to existing execution pipeline.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                    Existing Bot (unchanged)                          │
│  Signal → Parser → Sizing → Queue → Worker → Broker → Risk → Exit  │
└────┬───────┬─────────┬───────────────┬──────────────────┬───────────┘
     │       │         │               │                  │
     ▼       ▼         ▼               ▼                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    AI Intelligence Layer (NEW)                       │
│                                                                     │
│  Phase 0: Foundation                                                │
│    ├── Feature flag service (ai_features table)                     │
│    ├── AI cost tracker (api_usage table)                            │
│    └── Event bus hooks (on_trade_close, on_signal_arrive)           │
│                                                                     │
│  Phase 1: Signal Intelligence                                       │
│    ├── Local Signal Classifier (scikit-learn, 5ms, no API)          │
│    ├── Self-improving loop (classify → learn → regex → instant)    │
│    └── Cross-channel consensus detector                             │
│                                                                     │
│  Phase 2: Adaptive Risk                                             │
│    ├── Channel Performance Scoring (0-100, auto-sizing)             │
│    ├── Market Regime Detection (VIX/SPY → risk adjustment)          │
│    ├── Execution Quality Analysis (slippage/latency per broker)     │
│    └── Adaptive Risk Tuning (AI proposes SL/PT changes)             │
│                                                                     │
│  Phase 3: AI Co-Pilot                                               │
│    ├── MCP Server (30 tools, Claude Desktop + Dashboard chat)       │
│    └── Enhanced chatbot (format commands + full bot control)        │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Phase 0: Foundation (must ship first)

### What: Feature flags + event hooks + cost tracking

**Files to create:**
```
src/ai/                          ← new package
src/ai/__init__.py               ← package init
src/ai/feature_flags.py          ← feature flag service (~80 lines)
src/ai/event_bus.py              ← event hooks for AI modules (~60 lines)
src/ai/cost_tracker.py           ← API usage tracking (~50 lines)
```

**DB table:**
```sql
CREATE TABLE ai_feature_flags (
    feature_key TEXT PRIMARY KEY,     -- 'channel_scoring', 'market_regime', etc.
    enabled INTEGER DEFAULT 0,        -- 0=off, 1=on
    config_json TEXT DEFAULT '{}',    -- per-feature configuration
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE ai_api_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT,                     -- 'claude', 'gemini', 'local'
    model TEXT,                       -- 'haiku', 'sonnet', 'tfidf_classifier'
    feature TEXT,                     -- 'signal_parse', 'risk_tuning', etc.
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0,
    latency_ms INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Event bus hooks (3 insertion points in existing code):**
```python
# selfbot_webull.py — after trade saved to DB (~line 20800)
from src.ai.event_bus import emit_trade_close
emit_trade_close(trade_data)  # fire-and-forget, never blocks

# selfbot_webull.py — before order_queue.put (~line 16900)
from src.ai.event_bus import emit_signal_arrive
emit_signal_arrive(signal)  # fire-and-forget

# position_monitor.py — after fill detected (~line 5620)
from src.ai.event_bus import emit_fill_detected
emit_fill_detected(fill_data)  # fire-and-forget
```

**UI:** Add toggle grid to Admin → Settings → AI Intelligence Hub (6 toggles)

**Acceptance:** All flags default OFF. Bot behavior byte-identical to pre-Phase-0.

**Effort:** ~200 lines

---

## Phase 1: Signal Intelligence

### Module 1A: Local Signal Classifier

**What:** On-device ML model trained on your AI parse history. Parses any signal in 5ms without API calls.

**Files:**
```
src/ai/signal_classifier.py      ← classifier + training pipeline (~300 lines)
src/ai/models/                   ← saved model files (auto-generated)
```

**DB table:**
```sql
CREATE TABLE ai_classifier_training_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    training_samples INTEGER,
    accuracy REAL,
    precision_score REAL,
    recall_score REAL,
    model_version INTEGER,
    trained_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Integration (2 lines in existing code):**
```python
# listener.py and selfbot_webull.py — between registry and AI API fallback:
if not signal and ai_flags.is_enabled('local_classifier'):
    signal = local_classifier.predict(msg.content)
```

**MVP scope:**
- TF-IDF vectorizer + SGD classifier (binary: is_signal / not_signal)
- Entity extraction via learned regex patterns from ai_format_candidates
- Retrain weekly from ai_format_candidates table (approved + executed entries)
- Confidence threshold: 0.85 (below → falls through to API)

**Full scope:**
- Multi-class: BTO_OPTION / BTO_STOCK / STC / CONDITIONAL / NOT_SIGNAL
- Named entity recognition: symbol, strike, expiry, price, action
- Incremental learning (retrain on every new approved format)
- A/B testing: run classifier and API in parallel, compare accuracy

**Effort:** ~300 lines

### Module 1B: Cross-Channel Consensus

**What:** When 2+ channels signal the same symbol within 10 minutes, boost sizing.

**Files:**
```
src/ai/consensus.py               ← consensus detector (~150 lines)
```

**DB table:**
```sql
CREATE TABLE ai_consensus_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    asset_type TEXT DEFAULT 'option',
    strike REAL,
    expiry TEXT,
    channel_count INTEGER,
    channel_ids TEXT,               -- JSON array of matching channel IDs
    first_signal_at TIMESTAMP,
    consensus_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sizing_boost REAL DEFAULT 1.0,  -- 1.5 for 2 channels, 2.0 for 3+
    outcome_pnl_pct REAL            -- filled after trade closes
);
```

**Integration (5 lines before order_queue.put):**
```python
if ai_flags.is_enabled('consensus'):
    consensus = check_consensus(signal['symbol'], signal.get('strike'), signal.get('expiry'))
    if consensus and consensus['channel_count'] >= 2:
        signal['_consensus_boost'] = consensus['sizing_boost']
        signal['_consensus_channels'] = consensus['channel_count']
```

**MVP:** Detect consensus + log. No auto-sizing boost (user reviews in Dashboard).
**Full:** Auto-boost sizing by 1.5x (2 channels) or 2x (3+), capped by max_position_size.

**Effort:** ~150 lines

---

## Phase 2: Adaptive Risk

### Module 2A: Channel Performance Scoring

**Files:**
```
src/ai/channel_scoring.py         ← scoring engine (~250 lines)
```

**DB table:**
```sql
CREATE TABLE ai_channel_scores (
    channel_id INTEGER PRIMARY KEY,
    score INTEGER DEFAULT 50,           -- 0-100 composite
    win_rate_7d REAL, win_rate_30d REAL, win_rate_all REAL,
    avg_pnl_pct REAL, avg_win_pct REAL, avg_loss_pct REAL,
    profit_factor REAL,                 -- gross profit / gross loss
    sharpe_ratio REAL,
    total_trades INTEGER DEFAULT 0,
    streak_current INTEGER DEFAULT 0,   -- positive=wins, negative=losses
    last_computed_at TIMESTAMP,
    auto_sizing_multiplier REAL DEFAULT 1.0  -- 0.5-1.5 based on score
);
```

**Scoring formula:**
```python
score = (
    0.30 * normalize(win_rate_30d, 0.3, 0.7) +     # 30% weight: win rate
    0.25 * normalize(profit_factor, 0.5, 3.0) +      # 25% weight: profit factor
    0.20 * normalize(sharpe_ratio, -1, 3) +           # 20% weight: risk-adjusted
    0.15 * trend_score(win_rate_7d, win_rate_30d) +   # 15% weight: recent trend
    0.10 * normalize(total_trades, 10, 100)            # 10% weight: sample size
) * 100
```

**Auto-sizing tiers:**
```
90-100: sizing × 1.2  (top performer — increase exposure)
70-89:  sizing × 1.0  (normal)
50-69:  sizing × 0.7  (underperforming — reduce exposure)
30-49:  sizing × 0.3  (poor — minimal exposure, alert user)
0-29:   sizing × 0.0  (terrible — auto-disable execute, alert)
```

**Dashboard widget:** Channel leaderboard card with score badges, sparkline, trend arrows.

**MVP:** Score computation on trade close. Dashboard display. No auto-sizing.
**Full:** Auto-sizing multiplier + auto-disable at score <30 + weekly email report.

**Effort:** ~250 lines

### Module 2B: Market Regime Detection

**Files:**
```
src/ai/market_regime.py           ← regime classifier (~200 lines)
```

**DB table:**
```sql
CREATE TABLE ai_market_regime (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    regime TEXT,                     -- TRENDING_UP/DOWN, CHOPPY, HIGH_VOL, LOW_VOL
    vix_level REAL,
    spy_intraday_range_pct REAL,
    confidence REAL,
    sizing_multiplier REAL DEFAULT 1.0,
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Data sources (no paid APIs needed):**
```python
# VIX: free from Yahoo Finance or existing broker quote
vix = uph.get_quote_price('VIX') or uph.get_quote_price('^VIX')

# SPY range: from existing streaming data
spy = uph.get_quote('SPY')
spy_range_pct = (spy.high - spy.low) / spy.open * 100

# 20-day average range: computed from trade history
avg_range = db.query("SELECT AVG(high_pct - low_pct) FROM daily_ranges WHERE date > ?", 20_days_ago)
```

**Regime classification:**
```
VIX > 25 AND spy_range > 2× avg      → HIGH_VOL (reduce sizing 50%)
VIX > 25 AND spy_range < avg          → CHOPPY (reduce sizing 30%)
VIX < 18 AND spy_trend_up             → TRENDING_UP (normal sizing)
VIX < 18 AND spy_trend_down           → TRENDING_DOWN (reduce sizing 50%, BTO alert)
VIX 18-25                             → NORMAL
```

**MVP:** Classification + Dashboard indicator. No auto-adjustment.
**Full:** Auto-adjust sizing multiplier. Alert on regime change. Time-of-day awareness.

**Effort:** ~200 lines

### Module 2C: Execution Quality Analysis

**Files:**
```
src/ai/execution_quality.py       ← quality recorder + analyzer (~200 lines)
```

**DB table:**
```sql
CREATE TABLE ai_execution_quality (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER,
    broker TEXT,
    symbol TEXT,
    asset_type TEXT,
    order_type TEXT,                  -- market/limit
    signal_price REAL,
    fill_price REAL,
    slippage_pct REAL,               -- (fill - signal) / signal * 100
    signal_to_fill_ms INTEGER,       -- latency
    time_of_day TEXT,                -- open/morning/midday/afternoon/power_hour
    market_regime TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**MVP:** Record every fill. Dashboard broker comparison table.
**Full:** Weekly AI report. Broker routing recommendations.

**Effort:** ~200 lines

### Module 2D: Adaptive Risk Tuning

**Files:**
```
src/ai/risk_tuning.py             ← backtest + recommendation engine (~400 lines)
```

**DB table:**
```sql
CREATE TABLE ai_risk_recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER,
    channel_name TEXT,
    current_settings TEXT,           -- JSON {sl: 60, pt1: 25, ...}
    proposed_settings TEXT,          -- JSON {sl: 25, pt1: 15, ...}
    evidence TEXT,                   -- "62% of losses at -25% to -60%..."
    backtested_improvement TEXT,     -- "+18% P&L over 50 trades"
    confidence REAL,
    status TEXT DEFAULT 'pending',   -- pending/approved/dismissed
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TIMESTAMP
);
```

**How it works:**
```python
# Weekly cron (Sunday 8pm ET) or on-demand from Dashboard
for channel in channels_with_20_plus_trades:
    trades = get_trades(channel, last_50)
    
    # Simulate alternative SL values
    for alt_sl in [10, 15, 20, 25, 30]:
        simulated_pnl = backtest(trades, sl_pct=alt_sl, pt=current_pt)
        if simulated_pnl > current_pnl * 1.10:  # 10%+ improvement
            store_recommendation(channel, current_sl, alt_sl, simulated_pnl)
```

**Dashboard:** "🧠 AI Risk Recommendations" panel (same approval UX as format auto-learn).

**MVP:** Weekly backtest. Dashboard approval panel.
**Full:** Daily analysis. What-if simulator. Multi-parameter optimization.

**Effort:** ~400 lines

---

## Phase 3: AI Co-Pilot

### Module 3A: MCP Server

**Files:**
```
src/ai/mcp_server.py              ← MCP JSON-RPC server (~500 lines)
src/ai/mcp_tools.py               ← 30 tool implementations (~400 lines)
```

**Transport:** stdio (Claude Desktop) or SSE (Dashboard chat)

**30 tools across 6 categories:**
```python
TOOLS = {
    # Positions (5)
    'get_live_positions': ...,
    'get_position_detail': ...,
    'close_position': ...,
    'place_order': ...,
    'get_pending_orders': ...,
    
    # Channels (5)
    'get_channels': ...,
    'get_channel_settings': ...,
    'update_channel_settings': ...,
    'get_channel_performance': ...,
    'disable_channel': ...,
    
    # Risk & Analytics (5)
    'get_risk_state': ...,
    'get_trade_history': ...,
    'get_execution_quality': ...,
    'get_market_regime': ...,
    'get_ai_recommendations': ...,
    
    # Formats (4)
    'get_format_candidates': ...,
    'approve_format': ...,
    'test_parse': ...,
    'get_registry_stats': ...,
    
    # System (5)
    'get_broker_status': ...,
    'get_hub_stats': ...,
    'get_conditional_orders': ...,
    'get_system_metrics': ...,
    'get_ai_feature_status': ...,
    
    # Intelligence (6)
    'get_channel_scores': ...,
    'get_consensus_signals': ...,
    'get_pattern_insights': ...,
    'ask_ai': ...,
    'run_backtest': ...,
    'get_cost_report': ...,
}
```

**MVP:** 15 read-only tools (positions, channels, trades, health, formats).
**Full:** 30 tools including write operations (update settings, place orders, close positions).

**Effort:** ~900 lines

### Module 3B: Enhanced Dashboard Chat

**Files:**
```
gui_app/chat_assistant.py         ← MODIFY existing (add MCP tool routing)
```

**Change (~50 lines added):**
```python
async def handle_message(user_input):
    # Priority 1: Fast format commands (existing — no change)
    if _is_format_command(user_input):
        return await _handle_format_command(user_input)
    
    # Priority 2: Quick status queries (new — local, no AI call)
    if _is_status_query(user_input):
        return await _handle_status_query(user_input)
    
    # Priority 3: AI Co-Pilot (new — Claude with MCP tools)
    return await _handle_ai_copilot(user_input, tools=MCP_TOOLS)
```

**MVP:** Status queries ("show positions", "broker status") handled locally.
**Full:** AI co-pilot with full tool access for natural language control.

**Effort:** ~50 lines (modification to existing file)

---

## Implementation Order & Dependencies

```
Phase 0: Foundation                    ← MUST be first
  │      (feature flags, event bus)
  │      ~200 lines, 0 risk
  │
  ├──► Phase 1A: Local Classifier      ← highest user value / effort ratio
  │    (5ms signal detection)
  │    ~300 lines, depends on Phase 0
  │
  ├──► Phase 1B: Consensus             ← independent
  │    (cross-channel detection)
  │    ~150 lines, depends on Phase 0
  │
  ├──► Phase 2A: Channel Scoring       ← biggest P&L impact
  │    (auto-sizing adjustment)
  │    ~250 lines, depends on Phase 0
  │
  ├──► Phase 2B: Market Regime         ← independent
  │    (VIX/SPY risk adjustment)
  │    ~200 lines, depends on Phase 0
  │
  ├──► Phase 2C: Execution Quality     ← independent
  │    (slippage/latency tracking)
  │    ~200 lines, depends on Phase 0
  │
  ├──► Phase 2D: Risk Tuning           ← depends on 2A (needs scores)
  │    (AI proposes SL/PT changes)
  │    ~400 lines, depends on Phase 0 + 2A
  │
  └──► Phase 3: AI Co-Pilot            ← depends on all Phase 2 modules
       (MCP server + enhanced chat)
       ~950 lines, depends on Phase 0 + all Phase 2

Total: ~2,650 new lines + ~50 lines modifying existing files
```

---

## Feature Interaction Matrix

```
                    Classifier  Consensus  Scoring  Regime  ExecQA  RiskTune  CoPilot
Local Classifier      —          ·          ·        ·       ·        ·        reads
Consensus             ·          —          boosts   ·       ·        ·        reads
Channel Scoring       ·         data        —       adjusts  ·       feeds     reads
Market Regime         ·          ·         adjusts   —       ·       context   reads
Execution Quality     ·          ·          data     ·       —       feeds     reads
Risk Tuning           ·          ·         needs     uses   uses      —        reads
AI Co-Pilot          reads      reads      reads    reads   reads    reads      —

Key:
  reads  = co-pilot queries this module's data
  feeds  = output feeds into this module
  boosts = consensus boosts scoring signal
  adjusts = regime adjusts scoring thresholds
  needs  = hard dependency (must be built first)
  data   = provides data but not required
```

---

## Risk Mitigation

| Risk | Mitigation |
|---|---|
| Module crashes | Every module wrapped in try/except. Feature flag → instant disable. |
| Slows execution | All modules are fire-and-forget async. Never in signal→broker path. |
| Wrong AI recommendation | User approval required. Never auto-applied without "Apply" click. |
| Local model wrong | Confidence gate (0.85). Falls through to API if unsure. |
| API cost overrun | Cost tracker with daily/monthly limits. Alert at 80% budget. |
| Regime mis-detection | Conservative default (alerts only, no auto-adjust in MVP). |
| Consensus false positive | Require 2+ channels + same strike + same expiry (not just symbol). |

---

## What Makes This Unique

| Feature | TradeStation | Thinkorswim | TradingView | Signal Bots | THIS Bot |
|---|---|---|---|---|---|
| Multi-broker execution | 1 broker | 1 broker | 0 (alerts only) | 1-2 brokers | **11 brokers** |
| Signal auto-parse | ❌ | ❌ | ❌ | Regex only | **Registry + Local ML + AI** |
| Self-improving | ❌ | ❌ | ❌ | ❌ | **Auto-learn loop** |
| Channel scoring | ❌ | ❌ | ❌ | ❌ | **Live 0-100 scores** |
| Adaptive risk | Manual | Manual | Manual | Fixed | **AI-proposed per channel** |
| Market regime | Manual | VIX chart | Indicator | ❌ | **Auto-adjusts risk** |
| Cross-signal consensus | ❌ | ❌ | ❌ | ❌ | **Auto-detects + boosts** |
| Execution analysis | ❌ | Basic | ❌ | ❌ | **Per-broker TCA** |
| AI co-pilot | ❌ | ❌ | ❌ | ❌ | **MCP + natural language** |
| Per-channel risk | ❌ | ❌ | ❌ | Limited | **65+ settings per channel** |
