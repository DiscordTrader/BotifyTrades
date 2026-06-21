# AI Intelligence Hub — Architecture & Gap Analysis

**Date**: 2026-06-20
**Scope**: Full audit of AI capabilities, wiring, format learning pipeline, and the critical gap between AI fallback and auto-learning

---

## Architecture

```
Discord Message
  │
  ├── SignalFormatRegistry.parse() — ~100 built-in + learned regex patterns (priority order)
  │     ├── Match → Order Queue → Broker Execution
  │     └── No Match ↓
  │
  ├── AI_FALLBACK (selfbot:14061/17883) — parse_signal_with_ai()
  │     ├── confidence ≥ 0.80 → Queue for execution
  │     ├── confidence < 0.80 → Drop (logged)
  │     └── ❌ GAP: Result discarded — no learning feedback
  │
  └── Format Learning Pipeline (MANUAL TRIGGER ONLY)
        ├── Chat: "analyze channel <id>" → 5-phase pipeline → candidates → user approves
        ├── Chat: "teach this format: <signal>" → AI generates regex → auto-registered
        └── Result → learned_patterns DB → Registry hot-reload
```

## 5 AI Capabilities — Status

| # | Capability | File | Status | Wiring |
|---|---|---|---|---|
| 1 | **AI Signal Fallback** | `ai_signal_parser.py` | ✅ Working | Triggers when registry fails. Confidence ≥ 0.80 gate. Detects conditionals, targets, SL. |
| 2 | **Chat Assistant** | `chat_assistant.py` | ✅ Working | Format commands: `teach`, `analyze channel`, `scan channel`, `approve`, `show formats` |
| 3 | **Trade Analysis** | `ai_analyzer.py` | ✅ Working | Post-trade AI analysis (risk, technicals, options greeks) |
| 4 | **Sentiment Analysis** | `ai_analyzer.py` | ✅ Working | Channel message buffer sentiment scoring |
| 5 | **Format Learning** | `format_learning_pipeline.py` + `format_trainer.py` | ✅ Working | 5-phase pipeline: heuristic + AI scan → candidates → approve → register |

## THE CRITICAL GAP

### AI Fallback → Format Learning is DISCONNECTED

When AI_FALLBACK successfully parses `### CAR 6/26 185p $5.09`:
- ✅ Extracts action, symbol, strike, option_type, expiry, price
- ✅ Detects conditional vs immediate
- ✅ Extracts profit targets and stop losses
- ✅ Executes the trade
- ❌ **Does NOT store the message text for learning**
- ❌ **Does NOT generate a regex pattern**
- ❌ **Does NOT register in learned_patterns**
- ❌ **Does NOT call format_learning_pipeline or format_trainer**

**Result**: Every time the same format appears, the system pays another AI API call ($0.001-0.01 per parse). The `### SYMBOL DATE STRIKE $PRICE` format from the GONZO channel will NEVER be auto-learned — it requires the user to manually say `teach this format: ### CAR 6/26 185p $5.09` or `analyze channel <id>` in the chatbot.

### Cost Impact

| Scenario | First Occurrence | Second+ Occurrence |
|---|---|---|
| Current (no auto-learn) | AI API call (~200ms + $0.001) | AI API call again (~200ms + $0.001) |
| With auto-learn | AI API call (~200ms + $0.001) | **Regex match (<1ms, $0)** |

For a channel with 50 signals/day in the same format: **$1.50/month wasted on repeated AI calls** that a single regex would eliminate.

## Settings Page — Admin → Settings → AI Intelligence Hub

| Setting | UI Element | DB Column | Status |
|---|---|---|---|
| AI Provider | Dropdown (Claude/Gemini/OpenAI/Disabled) | `ai_provider` | ✅ Working |
| API Key | Input field (per provider) | `api_keys` JSON | ✅ Working |
| Trade Analysis | Toggle | `ai_analysis_enabled` | ✅ Working |
| Sentiment Analysis | Toggle | `sentiment_analysis_enabled` | ✅ Working |
| Live Status | 3-badge grid (Chatbot/Fallback/Analysis) | API: `/api/ai/status` | ✅ Working |
| Auto-Learn Toggle | **DOES NOT EXIST** | N/A | ❌ Missing |
| Auto-Learn Confidence | **DOES NOT EXIST** | N/A | ❌ Missing |
| Learning Stats | **DOES NOT EXIST** | N/A | ❌ Missing |

## Chatbot Commands — Status

| Command | Handler | Status |
|---|---|---|
| `teach this format: <signal>` | `teach_signal_format()` | ✅ Working — generates regex + auto-registers |
| `analyze channel <id>` | `_handle_analyze_channel()` | ✅ Working — 5-phase pipeline |
| `scan channel <id>` | `_handle_scan_channel()` | ✅ Working — older single-phase path |
| `show formats` / `list formats` | `_handle_list_formats()` | ✅ Working |
| `show candidates` | `_handle_list_candidates()` | ✅ Working |
| `approve format #N` | `_handle_approve_candidate()` | ✅ Working |
| `approve all formats` | `_handle_approve_all()` | ✅ Working |
| `delete format <name>` | `_handle_delete_format()` | ✅ Working |
| `enable/disable format` | `_handle_toggle_format()` | ✅ Working |
| `test format: <signal>` | `_handle_test_format()` | ✅ Working |

## Priority Fix List

```
1. CRITICAL: Wire AI_FALLBACK → format_trainer auto-learning
   → After successful AI parse + execute, call format_trainer.learn_format_from_example()
   → Auto-register as learned_pattern (or save as candidate for approval)
   → Next occurrence matches regex — no AI call needed

2. HIGH: Add Auto-Learn settings to AI Intelligence Hub page
   → Toggle: "Auto-learn unrecognized formats" (default: on)
   → Confidence threshold: "Auto-approve above %" (default: 0.90)
   → Counter: "Formats auto-learned: N"

3. MEDIUM: Add learning stats to AI Intelligence Hub
   → "AI fallback calls today: N"
   → "Formats auto-learned: N"
   → "Patterns saved: N / registry match %"
```
