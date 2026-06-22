# AI Trading Intelligence — Enterprise Architecture

**Date**: 2026-06-20
**Author**: Senior Fintech Architect
**Status**: Design Specification — Ready for phased implementation

---

## Vision

Transform the bot from a **signal relay** (receives signal → places order) into an **AI-powered autonomous trading co-pilot** that learns, adapts, and improves with every trade. No other retail platform combines real-time signal intelligence, adaptive risk management, execution optimization, and a live AI co-pilot in a single system.

---

## Architecture: 4-Layer AI Intelligence Stack

```
                    ┌─────────────────────────────────────────────┐
                    │           Layer 4: AI Co-Pilot              │
                    │  MCP Server + Natural Language Control       │
                    │  "Tighten SL on GONZO to 15%"               │
                    │  "Why did TSLA lose money?"                  │
                    │  "Which channels should I disable?"          │
                    └──────────────────┬──────────────────────────┘
                                       │
                    ┌──────────────────▼──────────────────────────┐
                    │        Layer 3: Adaptive Intelligence        │
                    │  Channel Scoring · Risk Auto-Tuning          │
                    │  Market Regime Detection · Execution QA      │
                    │  Cross-Channel Consensus · Pattern Memory    │
                    └──────────────────┬──────────────────────────┘
                                       │
                    ┌──────────────────▼──────────────────────────┐
                    │       Layer 2: Signal Intelligence           │
                    │  Format Registry · AI Fallback Parser        │
                    │  Auto-Learn Pipeline · Confidence Scoring    │
                    │  Duplicate Detection · Sentiment Analysis    │
                    └──────────────────┬──────────────────────────┘
                                       │
                    ┌──────────────────▼──────────────────────────┐
                    │        Layer 1: Execution Engine             │
                    │  Multi-Broker Dispatch · Position Sizing     │
                    │  Risk Engine · Bracket Management · OCO      │
                    │  Conditional Orders · Price Monitoring       │
                    └─────────────────────────────────────────────┘
```

**Layer 1** exists today (built in this session). **Layer 2** partially exists (AI fallback + auto-learn built today). **Layer 3 and 4** are the enterprise differentiators.

---

## Layer 3: Adaptive Intelligence (6 Modules)

### Module 1: Channel Performance Scoring

**What**: Every signal channel gets a live AI-computed score (0-100) based on historical win rate, average P&L, signal quality, and recent trend. The score auto-adjusts position sizing and can auto-disable underperforming channels.

**How it works**:
```
Every trade close (STC, SL, PT exit):
  │
  ├── Update channel_scores table:
  │     ├── win_rate_7d, win_rate_30d, win_rate_all
  │     ├── avg_pnl_pct, avg_win_pct, avg_loss_pct
  │     ├── sharpe_ratio, profit_factor, max_drawdown
  │     ├── signal_frequency, avg_hold_time
  │     └── ai_confidence_correlation (how well AI confidence predicts outcome)
  │
  ├── Compute composite score (0-100):
  │     score = w1×win_rate + w2×profit_factor + w3×sharpe + w4×trend
  │
  └── Actions based on score:
        90-100: ✅ Increase position size by 20%
        70-89:  ✅ Normal sizing
        50-69:  ⚠️ Reduce position size by 30%
        30-49:  ⚠️ Track only (auto-disable execute)
        0-29:   🔴 Alert user "Channel X underperforming — recommend disable"
```

**Dashboard Widget**: Channel leaderboard with live scores, sparkline charts, trend arrows.

**Unique**: No retail platform scores signal providers dynamically and adjusts sizing in real-time.

### Module 2: Adaptive Risk Tuning

**What**: AI analyzes your trade history weekly and proposes risk setting changes per channel. The user approves or dismisses in the Dashboard (same approval UX as format auto-learn).

**How it works**:
```
Weekly AI analysis (Sunday night, or on-demand):
  │
  ├── For each channel with 20+ trades:
  │     ├── Analyze: where do most losses occur?
  │     │     → SL too wide (avg loss > 2× SL%)
  │     │     → SL too tight (many stopped out that later recovered)
  │     │     → PT too aggressive (never hit → trail exit instead)
  │     │     → PT too conservative (left money on table)
  │     │
  │     ├── Simulate alternatives:
  │     │     → What if SL was 20% instead of 60%? → backtest on last 50 trades
  │     │     → What if PT1 was 15% instead of 25%? → compare outcomes
  │     │
  │     └── Generate recommendation:
  │           {
  │             channel: "GONZO",
  │             current: {sl: 60%, pt1: 25%, trailing: 30%},
  │             proposed: {sl: 25%, pt1: 15%, trailing: 20%},
  │             evidence: "62% of losses occurred between -25% and -60%. 
  │                        Tighter SL would have saved $1,247 over 30 days.",
  │             confidence: 0.87,
  │             backtested_improvement: "+18% P&L over last 50 trades"
  │           }
  │
  └── Dashboard: "🧠 AI Risk Recommendations" panel
        [Review] [Apply] [Dismiss]
```

**Unique**: Bloomberg Terminal has backtesting. Retail bots have fixed risk settings. Nobody auto-generates per-channel risk recommendations with backtest evidence.

### Module 3: Market Regime Detection

**What**: AI identifies the current market regime (trending, choppy, high-vol, low-vol, sector rotation) and auto-adjusts risk behavior system-wide.

**How it works**:
```
Continuous monitoring (every 5 minutes):
  │
  ├── Inputs:
  │     ├── VIX level + VIX trend (rising/falling/stable)
  │     ├── SPY/QQQ intraday range vs 20-day average
  │     ├── Market breadth (advance/decline ratio)
  │     ├── Recent bot trade outcomes (last 2 hours win rate)
  │     └── Time of day (open/midday/power hour/close)
  │
  ├── Regime classification:
  │     ├── TRENDING_UP:    wide PT, tight trail, normal sizing
  │     ├── TRENDING_DOWN:  no new BTO, tighten SL, reduce sizing 50%
  │     ├── CHOPPY:         reduce sizing 30%, tighten SL, skip conditionals
  │     ├── HIGH_VOL:       reduce sizing 50%, widen SL (avoid whipsaw), skip market orders
  │     ├── LOW_VOL:        normal, but widen PT (let winners run)
  │     └── POWER_HOUR:     all entries use limit only, aggressive trailing
  │
  └── Auto-adjustments (with user-configurable aggressiveness):
        Conservative: alerts only ("Market is choppy — consider reducing size")
        Standard:     auto-reduce sizing, tighten SL (user can override)
        Aggressive:   auto-disable entries during bearish regimes
```

**Unique**: Institutional desks have regime detection. No retail bot connects regime to automated risk adjustment.

### Module 4: Execution Quality Analysis

**What**: AI analyzes every order execution and generates a quality score, identifying patterns like "Webull Official has 200ms slower fills than IBKR for options" or "Market orders during power hour get 3% worse fills than limit orders."

**How it works**:
```
Every trade fill:
  │
  ├── Record:
  │     ├── signal_price vs fill_price → slippage
  │     ├── signal_time vs fill_time → latency
  │     ├── order_type used (market/limit)
  │     ├── broker used
  │     ├── time of day
  │     ├── market conditions (VIX, volume)
  │     └── option vs stock, underlying IV
  │
  ├── Weekly report:
  │     ├── Avg slippage by broker: IBKR 0.3%, WO 0.8%, Schwab 0.5%
  │     ├── Avg latency by broker: IBKR 210ms, WO 450ms, Schwab 320ms
  │     ├── Worst slippage scenarios (sorted)
  │     └── Recommendations:
  │           "Switch CAR from Webull to IBKR — saved $47/month in slippage"
  │           "Use limit orders for power hour entries — 2.1% better fills"
  │
  └── Dashboard: Execution Quality tab with broker comparison charts
```

### Module 5: Cross-Channel Consensus

**What**: When multiple channels signal the same symbol within a time window, AI detects consensus and can boost confidence/sizing.

**How it works**:
```
Signal arrives: "BTO SPY 580C 6/21 @ $2.50" from Channel A
  │
  ├── Check recent signals (last 10 minutes):
  │     Channel B: "SPY 580C 6/21 $2.55" (3 min ago) ← MATCH
  │     Channel C: "SPY 585C 6/21 $1.80" (7 min ago) ← NEAR MATCH
  │
  ├── Consensus level:
  │     2/15 active channels agree → MODERATE (2x)
  │     3+/15 active channels agree → STRONG (3x)
  │
  └── Actions:
        MODERATE: increase position size by 50% (capped by max_position_size)
        STRONG:   increase position size by 100% + tighten SL to 15%
        Log: "[CONSENSUS] 3 channels agree on SPY 580C — boosted sizing 2x"
```

**Unique**: No retail platform detects cross-provider consensus and auto-adjusts sizing.

### Module 6: Pattern Memory

**What**: AI remembers which signal patterns, from which channels, at which times of day, in which market conditions, produce the best outcomes. Uses this to pre-filter signals.

**How it works**:
```
Every trade outcome (win/loss):
  │
  ├── Store in pattern_memory table:
  │     ├── channel_id, format_name, asset_type
  │     ├── time_of_day (bucket: open/morning/midday/afternoon/power_hour)
  │     ├── day_of_week (Mon-Fri)
  │     ├── market_regime at entry
  │     ├── signal_confidence (if AI-parsed)
  │     ├── underlying_sector (tech/healthcare/energy/etc.)
  │     ├── outcome (win/loss, pnl_pct, hold_time)
  │     └── entry_delay_ms (time from signal to fill)
  │
  ├── Pattern queries:
  │     "GONZO options on Monday morning in choppy markets: 22% win rate"
  │     "ZZ scalp stocks during power hour: 78% win rate"
  │     "Any channel + SPY options + VIX > 25: 31% win rate"
  │
  └── Pre-filter actions:
        If pattern win_rate < 30% with 20+ samples:
          → Block signal + alert: "⚠️ Pattern historically loses — skipped"
          → Or reduce sizing by 70%
```

---

## Layer 4: AI Co-Pilot (MCP Server)

### MCP Tools (30 tools across 6 categories)

```python
# ═══ Positions & Trading ═══
get_live_positions()             # All open positions with real-time P&L
get_position_detail(symbol)      # Deep position info: entry, SL, PT, brackets, hub price
close_position(symbol, pct=100)  # Close full or partial position
place_order(action, symbol, qty) # Manual BTO/STC with full sizing cascade
get_pending_orders()             # Open orders awaiting fill

# ═══ Channel Management ═══
get_channels(platform=None)      # All channels with scores, settings, stats
get_channel_settings(id)         # Full 70+ settings for a channel
update_channel_settings(id, {})  # Modify any settings (batch)
get_channel_performance(id, days)# Win rate, P&L, trade count, sharpe
disable_channel(id)              # Disable execute (keep tracking)

# ═══ Risk & Analytics ═══
get_risk_state()                 # System-wide risk: open positions, exposure, margin
get_trade_history(filters)       # Queryable: symbol, channel, date, broker, outcome
get_execution_quality(broker)    # Slippage, latency, fill rate by broker
get_market_regime()              # Current regime + VIX + breadth
get_ai_recommendations()        # Pending risk tuning proposals

# ═══ Format & Parsing ═══
get_format_candidates()          # Pending AI auto-learn approvals
approve_format(id)               # Approve → regex generated → registry hot-reload
test_parse(text)                 # Parse a signal text through all parsers
get_registry_stats()             # Format match rates, AI fallback rate

# ═══ System Health ═══
get_broker_status()              # All brokers: connected, streaming, health
get_hub_stats()                  # UPH ticks, cache size, staleness
get_conditional_orders()         # Pending conditional triggers with distance-to-trigger
get_system_metrics()             # CPU, memory, uptime, cycle times

# ═══ Intelligence ═══
get_channel_scores()             # Live scores for all channels (0-100)
get_pattern_insights(channel)    # Best/worst patterns for a channel
get_consensus_signals()          # Current cross-channel consensus
ask_ai(question)                 # Freeform AI analysis with full context
```

### Natural Language Examples

```
"Show my worst performing channel this week"
→ get_channel_performance(all, days=7) → sort by P&L → present with evidence

"Why am I losing on GONZO options?"
→ get_trade_history(channel='GONZO', asset='option', days=30)
→ get_channel_settings('GONZO')
→ AI analyzes: "78% of losses are SL exits. Your SL is 60% but avg loss is -42%.
   Trades that hit -25% never recovered. Recommend: SL to 25%."

"Pause all entries, market is crashing"
→ get_channels(execute_enabled=True)
→ For each: update_channel_settings(id, {execute_enabled: False})
→ "Paused 12 channels. Existing positions still monitored by risk engine."

"Set all options channels to 20% SL and enable OCO brackets"
→ get_channels() → filter asset_type=option
→ batch update_channel_settings({stop_loss_pct: 20, broker_bracket_mode: 'both'})
→ "Updated 8 channels. OCO brackets will activate on next position entry."

"Show me a trade I should close right now"
→ get_live_positions() → get_risk_state()
→ AI identifies: "TSLA 350C is -18% with declining momentum, 
   no support until -35%. Close for a -18% loss vs potential -35%?"
→ User: "Close it" → close_position('TSLA')
```

---

## Implementation Phases

```
Phase 1: MCP Server Foundation (Week 1)                              ~300 lines
  └── 15 core tools: positions, channels, trades, health, risk
  └── JSON-RPC transport over stdio or SSE
  └── Claude Desktop integration working

Phase 2: Channel Performance Scoring (Week 2)                        ~400 lines
  └── channel_scores table, compute on trade close
  └── Dashboard leaderboard widget
  └── Auto-sizing adjustment based on score (configurable)

Phase 3: Execution Quality Analysis (Week 3)                         ~300 lines
  └── execution_quality table, record every fill
  └── Weekly report generation
  └── Dashboard Execution Quality tab

Phase 4: Market Regime Detection (Week 4)                            ~500 lines
  └── VIX/SPY/breadth monitoring
  └── Regime classification model
  └── Auto-adjustment hooks (conservative mode first)
  └── Dashboard regime indicator

Phase 5: Adaptive Risk Tuning (Week 5)                               ~600 lines
  └── Backtest engine for alternative risk params
  └── AI recommendation generator
  └── Dashboard approval panel (same UX as format auto-learn)
  └── One-click apply

Phase 6: Cross-Channel Consensus + Pattern Memory (Week 6)           ~400 lines
  └── Consensus detection on signal arrival
  └── Pattern memory table + query engine
  └── Signal pre-filter with pattern win-rate gate

Phase 7: Full MCP (30 tools) + AI Co-Pilot Polish (Week 7)           ~500 lines
  └── Remaining 15 MCP tools
  └── ask_ai() freeform analysis with full context
  └── Voice-ready responses (structured for TTS)
```

---

## What Makes This Unique in the Industry

| Feature | Traditional Bots | Institutional Platforms | THIS Bot |
|---|---|---|---|
| Signal parsing | Regex only | N/A (no signals) | Registry + AI + auto-learn |
| Risk management | Fixed settings | Quant models | AI-adaptive per channel |
| Channel scoring | None | Analyst ratings | Live AI scoring 0-100 |
| Market regime | None | Proprietary models | Auto-adjusts risk in real-time |
| Execution analysis | None | TCA (expensive) | Built-in quality scoring |
| Cross-signal consensus | None | Desk communication | Automated consensus detection |
| AI co-pilot | Chatbot (text) | Bloomberg Terminal | MCP + natural language control |
| Format learning | Manual config | N/A | AI auto-learn + user approval |
| Risk auto-tuning | None | Risk committee | AI proposes, human approves |

**No retail platform combines all 7 intelligence layers.** Each one individually exists in expensive institutional tools. Having them all in a self-hosted bot with natural language control is unprecedented.

---

## Scalability

Each module is independent — can be enabled/disabled per deployment:
- **Small trader**: Layer 1 + 2 (execution + signal parsing) — already built
- **Active trader**: + Channel Scoring + Execution Quality
- **Power user**: + Market Regime + Adaptive Risk + Consensus
- **Enterprise**: + Full MCP + Pattern Memory + AI Co-Pilot

New modules plug into the same event bus:
```python
@on_trade_close
def update_channel_score(trade): ...

@on_trade_close  
def update_pattern_memory(trade): ...

@on_signal_arrive
def check_consensus(signal): ...

@on_market_tick
def update_regime(tick): ...
```

No module depends on another. Any can be added or removed without affecting the rest.
