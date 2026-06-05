# AI Signal Parser — Architecture Review & Integration Plan

**Date**: May 15, 2026  
**Version**: 10.2.0  
**Reviewer**: AI Industry Architect  

---

## 1. Current State Assessment

### What Already Exists (Well-Architected)

| Component | File | Status |
|-----------|------|--------|
| AI Signal Parser | `src/services/ai_signal_parser.py` | Built — uses OpenAI GPT-4o-mini |
| Parsing Pipeline | `src/services/signal_parsing_pipeline.py` | Built — 5-tier cascade with AI at Tier 5 |
| Format Trainer | `gui_app/format_trainer.py` | Built — teach-once pattern learning |
| Config Service | `gui_app/config_service.py` | Built — provider toggle (replit_ai/openai/disabled) |
| Security Gating | `signal_parsing_pipeline.py:93-99` | Built — `can_execute()` blocks AI signals without admin approval |
| Deduplification | `signal_parsing_pipeline.py:116-145` | Built — 5-min TTL hash-based dedupe |
| Few-Shot Prompting | `ai_signal_parser.py:126-153` | Built — 6 hardcoded examples |

**Verdict**: The architecture is already production-grade. The AI integration exists but is locked behind OpenAI (paid). The task is to **add free model providers** as drop-in alternatives, not redesign the pipeline.

---

## 2. Risk Assessment: AI in a Trading Pipeline

### CRITICAL PRINCIPLE: AI = Pattern Recognition Only

```
Discord Message ──→ [Regex Parsers Tier 1-4] ──→ MATCH → Execute
                           │
                           ↓ (no match)
                    [AI Parser Tier 5] ──→ Extract structured JSON
                           │
                           ↓
                    [Validation Layer] ──→ Reject if invalid
                           │
                           ↓
                    [Admin Approval Gate] ──→ Block execution until approved
                           │
                           ↓
                    [Broker Execution] ──→ Only if all gates pass
```

### Safety Guardrails (Already Implemented)

| Guardrail | Location | How It Works |
|-----------|----------|--------------|
| **AI cannot execute by default** | `pipeline.py:164` | `_ai_execution_allowed = False` |
| **Requires admin approval** | `pipeline.py:416` | `admin_approved=False` always |
| **Confidence threshold** | `pipeline.py:218-220` | Rejects if `confidence < 0.8` |
| **Security gate** | `pipeline.py:222-228` | Returns `None` for unapproved AI signals |
| **`can_execute()` check** | `pipeline.py:93-99` | Double-gate: `admin_approved AND execution_allowed` |
| **Per-channel toggle** | `database.py` | `execute_enabled`, `paper_trade_enabled` per channel |

### What AI Must NEVER Do

| Prohibited | Why | How Prevented |
|------------|-----|---------------|
| Choose position size | AI could hallucinate qty | Channel settings control qty |
| Override stop loss | Could remove risk protection | SL comes from channel risk settings, not AI |
| Decide broker | Could route to wrong account | Broker comes from channel config |
| Execute without approval | Hallucinated signals | `admin_approved=False` hardcoded for AI |
| Modify existing positions | Phantom exits | AI only parses NEW messages, no state access |

---

## 3. Free Model Provider Comparison

### Evaluation Criteria for Trading Bot

| Criteria | Weight | Why |
|----------|--------|-----|
| Latency | HIGH | Signal → order speed matters |
| Free tier generosity | HIGH | Bot runs 24/5, many messages/day |
| JSON mode support | HIGH | Must return structured data reliably |
| Uptime/reliability | MEDIUM | Fallback only — regex handles 95%+ |
| Model quality | MEDIUM | Simple extraction task, not reasoning |

### Provider Matrix

| Provider | Model | Free Tier | Latency | JSON Mode | Reliability |
|----------|-------|-----------|---------|-----------|-------------|
| **Google Gemini** | Flash 2.0 | 15 RPM, 1M tokens/day | ~300ms | ✅ `response_mime_type` | ★★★★☆ |
| **Groq** | Llama 3.3 70B | 30 RPM, 14.4K req/day | ~150ms | ✅ `response_format` | ★★★☆☆ |
| **Ollama** | Llama 3.1 8B | Unlimited (local) | ~500ms (no GPU) | ⚠️ Manual parse | ★★★★★ |
| **OpenRouter** | Various free | 20 RPM, limited | ~400ms | ⚠️ Model-dependent | ★★☆☆☆ |
| **Cloudflare AI** | Llama 3 8B | 10K req/day | ~200ms | ⚠️ Workers AI format | ★★★☆☆ |

### Recommendation: Multi-Provider with Automatic Fallback

```
Priority 1: Gemini Flash (best free tier, reliable JSON)
Priority 2: Groq Llama 3.3 (fastest, backup if Gemini down)
Priority 3: Ollama local (zero-dependency fallback, if installed)
```

**Why not single provider?** Free tiers have rate limits. If 15 RPM is hit on Gemini, Groq catches the overflow. Ollama is insurance against both being down.

---

## 4. Integration Architecture

### 4.1 Provider Abstraction Layer (New File)

```
src/services/ai_providers.py  (~150 lines)
```

**Design**: OpenAI-compatible interface for all providers. Gemini and Groq both support the OpenAI chat completions format, so the existing `AsyncOpenAI` client works with just a `base_url` swap.

```python
PROVIDERS = {
    'gemini': {
        'base_url': 'https://generativelanguage.googleapis.com/v1beta/openai/',
        'model': 'gemini-2.0-flash',
        'env_key': 'GEMINI_API_KEY',
        'rpm_limit': 15,
    },
    'groq': {
        'base_url': 'https://api.groq.com/openai/v1',
        'model': 'llama-3.3-70b-versatile',
        'env_key': 'GROQ_API_KEY',
        'rpm_limit': 30,
    },
    'openai': {
        'base_url': None,  # default
        'model': 'gpt-4o-mini',
        'env_key': 'OPENAI_API_KEY',
        'rpm_limit': 60,
    },
    'ollama': {
        'base_url': 'http://localhost:11434/v1',
        'model': 'llama3.1:8b',
        'env_key': None,  # no key needed
        'rpm_limit': 999,
    }
}
```

**Key insight**: Gemini and Groq both offer OpenAI-compatible endpoints. This means `AsyncOpenAI(base_url=..., api_key=...)` works for all four providers with zero code changes to the parser logic.

### 4.2 Changes to Existing Files

| File | Change | Lines |
|------|--------|-------|
| `ai_signal_parser.py` | Replace hardcoded OpenAI with provider resolver | ~30 lines changed |
| `config_service.py` | Expand `AI_PROVIDERS` list: gemini, groq, openai, ollama, disabled | ~10 lines |
| `format_trainer.py` | Use same provider resolver instead of direct OpenAI | ~15 lines changed |
| `gui_app/templates/settings.html` | Add provider dropdown + API key fields for Gemini/Groq | ~40 lines HTML |
| `gui_app/routes.py` | Save/load Gemini/Groq API keys | ~20 lines |

**Total new code**: ~150 lines (provider layer) + ~115 lines (modifications)  
**No changes to**: signal_parsing_pipeline.py, selfbot_webull.py, risk engine, brokers

### 4.3 Provider Selection Flow

```
User sets in Settings GUI:
  AI Provider: [Gemini ▼]  ←── dropdown
  Gemini API Key: [sk-xxxxx]
  Groq API Key: [gsk-xxxxx]  (optional backup)
  Ollama URL: [localhost:11434]  (optional backup)
  
  [x] Enable AI fallback parsing
  [x] Enable auto-fallback to next provider on error
  [ ] Allow AI-parsed signals to execute (requires admin approval per signal)
```

### 4.4 Runtime Flow (No Change to Pipeline)

```
1. Discord message arrives
2. Tier 1-4 regex parsers → 95%+ matched here → execute immediately
3. No match → Tier 5 AI fallback triggered
4. ai_signal_parser.py:
   a. Check cache (1hr TTL) → return cached if hit
   b. Resolve provider (Gemini → Groq → Ollama → fail gracefully)
   c. Send message + few-shot examples → get JSON response
   d. Validate response structure (symbol exists, action valid, confidence present)
   e. Return AIParseResult
5. Pipeline security gate:
   a. confidence >= 0.8? → if no, reject
   b. admin_approved? → if no, LOG but do NOT execute
   c. can_execute()? → if no, reject
6. If approved: execute through normal broker path
```

---

## 5. Validation Layer (NEW — Critical Safety Addition)

The current AI parser trusts the JSON output. Add a validation layer between AI response and pipeline:

```python
def validate_ai_result(result: dict) -> tuple[bool, str]:
    """Validate AI-parsed signal before it enters the pipeline."""
    
    # 1. Symbol must be 1-5 uppercase letters
    symbol = result.get('symbol', '')
    if not re.match(r'^[A-Z]{1,5}$', symbol):
        return False, f"Invalid symbol: {symbol}"
    
    # 2. Action must be known
    if result.get('action') not in ('BTO', 'STC', None):
        return False, f"Invalid action: {result.get('action')}"
    
    # 3. Price must be positive if present
    price = result.get('price')
    if price is not None and (not isinstance(price, (int, float)) or price <= 0):
        return False, f"Invalid price: {price}"
    
    # 4. Strike must be positive if present
    strike = result.get('strike')
    if strike is not None and (not isinstance(strike, (int, float)) or strike <= 0):
        return False, f"Invalid strike: {strike}"
    
    # 5. Option type must be C or P
    opt_type = result.get('option_type')
    if opt_type and opt_type not in ('C', 'P'):
        return False, f"Invalid option type: {opt_type}"
    
    # 6. Confidence must be 0.0-1.0
    confidence = result.get('confidence', 0)
    if not (0.0 <= confidence <= 1.0):
        return False, f"Invalid confidence: {confidence}"
    
    # 7. NEVER allow AI to set qty > 1 (channel settings control size)
    if result.get('qty', 1) > 1:
        result['qty'] = 1  # Force to 1, log warning
    
    return True, "OK"
```

**Why this matters**: LLMs hallucinate. A model could return `symbol: "AAPL123"` or `price: -5.0` or `action: "SHORT"`. This layer catches garbage before it reaches the pipeline.

---

## 6. What AI Should NOT Touch (Hardcoded Boundaries)

| Field | Source | AI Access |
|-------|--------|-----------|
| Position size / qty | Channel config `default_quantity` | ❌ Read-only |
| Stop loss % | Channel risk settings | ❌ Cannot override |
| Profit target % | Channel risk settings | ❌ Cannot override |
| Broker selection | Channel `enabled_brokers` | ❌ Cannot choose |
| Order type (market/limit) | Channel `entry_order_mode` | ❌ Cannot choose |
| Risk engine params | Channel risk settings | ❌ No access |

**The AI's only job**: Given raw text → return `{action, symbol, strike, opt_type, expiry, price, confidence}`. Nothing else.

---

## 7. Monitoring & Observability

### AI Parse Log Table (New DB Table)

```sql
CREATE TABLE ai_parse_log (
    id INTEGER PRIMARY KEY,
    timestamp TEXT NOT NULL,
    provider TEXT NOT NULL,          -- 'gemini', 'groq', 'ollama'
    raw_message TEXT NOT NULL,
    parsed_result TEXT,              -- JSON
    confidence REAL,
    latency_ms INTEGER,
    was_executed INTEGER DEFAULT 0,
    was_correct INTEGER,             -- NULL until reviewed
    channel_id TEXT,
    error TEXT
);
```

**Why**: Track AI accuracy over time. If a provider starts hallucinating, you'll see it in the logs before it causes damage. Also useful for finding new regex patterns — if AI successfully parses a format 10+ times, that's a signal to write a proper regex for it.

### Dashboard Metrics (GUI)

- AI parse attempts / day
- Success rate (confidence >= 0.8)
- Average latency per provider
- False positive rate (parsed but shouldn't have)
- Provider fallback rate (primary → backup switches)

---

## 8. Cost Analysis

### Daily Volume Estimate

| Metric | Estimate |
|--------|----------|
| Discord messages/day | ~500-2000 |
| Matched by regex (Tier 1-4) | ~95% = 475-1900 |
| Sent to AI (Tier 5) | ~5% = 25-100 |
| Tokens per AI call | ~400 input + 200 output = 600 |
| Daily AI tokens | ~15K-60K tokens |

### Provider Cost at This Volume

| Provider | Daily Cost | Monthly Cost |
|----------|-----------|--------------|
| Gemini Flash | **$0.00** (well within 1M/day free) | **$0.00** |
| Groq Llama 3.3 | **$0.00** (well within 14.4K/day free) | **$0.00** |
| Ollama local | **$0.00** (electricity only) | **$0.00** |
| OpenAI GPT-4o-mini | ~$0.01-0.04/day | ~$0.30-1.20/mo |

**Verdict**: At 25-100 AI calls/day, all free tiers are more than sufficient. Even if every message hit AI (worst case), Gemini's 1M tokens/day handles it.

---

## 9. Implementation Priority

### Phase 1: Provider Abstraction (2-3 hours)
1. Create `src/services/ai_providers.py` — multi-provider resolver
2. Update `ai_signal_parser.py` — use provider resolver instead of hardcoded OpenAI
3. Update `config_service.py` — expand provider list
4. Add validation layer to `ai_signal_parser.py`

### Phase 2: GUI Settings (1-2 hours)
5. Update `settings.html` — provider dropdown, API key fields
6. Update `routes.py` — save/load provider settings and keys

### Phase 3: Monitoring (1-2 hours)
7. Create `ai_parse_log` table in database.py
8. Add logging to `ai_signal_parser.py` — track latency, provider, success
9. Add AI stats endpoint to routes.py
10. Add AI stats card to dashboard

### Phase 4: Format Trainer Update (1 hour)
11. Update `format_trainer.py` — use same provider resolver

---

## 10. Security Checklist

| # | Check | Status |
|---|-------|--------|
| 1 | AI signals blocked from execution by default | ✅ Already implemented |
| 2 | Admin approval required for AI signal execution | ✅ Already implemented |
| 3 | Confidence threshold (0.8) enforced | ✅ Already implemented |
| 4 | API keys stored in database (not env vars exposed to AI) | 🔧 Need to implement |
| 5 | No trading message content sent to AI contains account info | ✅ Only signal text sent |
| 6 | AI response validation (symbol, price, action format) | 🔧 Need to implement |
| 7 | Rate limiting per provider | 🔧 Need to implement |
| 8 | Graceful degradation (AI down → skip, don't crash) | ✅ Already implemented |
| 9 | AI cannot access position state / portfolio info | ✅ No access path exists |
| 10 | AI cannot modify risk parameters | ✅ No access path exists |

---

## 11. Summary

**The architecture is already 80% done.** The parsing pipeline, security gates, confidence scoring, and admin approval are all production-ready. The remaining work is:

1. **Swap OpenAI for a multi-provider layer** (Gemini/Groq/Ollama) — ~150 lines
2. **Add response validation** — ~40 lines
3. **Update GUI settings** — ~60 lines HTML + ~20 lines Python
4. **Add monitoring table** — ~30 lines SQL + ~40 lines Python

**Total estimated new code: ~340 lines**  
**Risk level: LOW** — AI is a fallback parser, not a decision maker. Triple-gated (confidence + approval + can_execute). Cannot access risk settings, position state, or broker credentials.

**Key principle enforced**: AI extracts patterns → Human approves → Bot executes. The AI never makes trading decisions.
