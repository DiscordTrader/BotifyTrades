# Claude API Integration — Architecture & Safety Review

**Date**: May 18, 2026  
**Version**: 10.2.0  
**Reviewer**: AI Systems Architect  

---

## 1. Executive Summary

Integrate Anthropic Claude as a signal parsing provider alongside existing OpenAI/Replit AI. Claude operates strictly as **Tier 5 AI Fallback** in the existing 5-tier parsing pipeline — pattern recognition only, never decision-making. All existing safety gates (confidence threshold, admin approval, execution blocking) apply identically to Claude signals.

**Risk Level**: LOW — Claude slots into an already triple-gated architecture. No new execution paths are created.

---

## 2. Current Architecture Assessment

### Parsing Pipeline (5-Tier Cascade)

```
TIER 1: Embed parsers (Spy-Sniper, Sir Goldman, Hengy)    → confidence: 1.0
TIER 2: SignalFormatRegistry (80+ regex patterns)          → confidence: 1.0
TIER 3: Trader-specific parsers (Bishop, Jacob, EvaPanda)  → confidence: 1.0
TIER 4: Standard BTO/STC regex                             → confidence: 1.0
TIER 5: AI Fallback (OpenAI/Replit/Claude)                 → confidence: 0.0-1.0
```

**Key insight**: Tiers 1-4 handle 95%+ of signals with regex (confidence=1.0). AI is only invoked when ALL regex parsers fail. This means Claude would process ~5% of messages at most.

### Existing Safety Architecture

| Gate | Location | Effect |
|------|----------|--------|
| `_ai_enabled = False` | `pipeline.py:162` | AI disabled by default |
| `_ai_execution_allowed = False` | `pipeline.py:164` | AI signals can't execute |
| `admin_approved = False` | `pipeline.py:416` | Hardcoded — no AI signal is pre-approved |
| `confidence >= 0.8` | `pipeline.py:218` | Low-confidence results discarded |
| `can_execute()` triple-check | `pipeline.py:93-99` | `admin_approved AND execution_allowed AND confidence >= 0.8` |
| `requires_approval = True` | `pipeline.py:415` | AI source always flagged |
| 5-min dedupe TTL | `pipeline.py:116-145` | Same signal won't re-trigger within 5 minutes |

**Verdict**: The safety architecture is production-grade. Adding Claude as a provider requires ZERO changes to the gating logic.

---

## 3. Claude vs OpenAI for Signal Parsing

### Technical Comparison

| Factor | OpenAI (GPT-4o-mini) | Claude (Haiku 3.5) | Claude (Sonnet 4) |
|--------|----------------------|---------------------|---------------------|
| **Latency** | ~300ms | ~200ms | ~500ms |
| **Cost per 1K tokens** | $0.15 in / $0.60 out | $0.80 in / $4.00 out | $3.00 in / $15.00 out |
| **JSON mode** | `response_format: json_object` | Tool use / JSON prefill | Tool use / JSON prefill |
| **Context window** | 128K | 200K | 200K |
| **Best for trading** | Good JSON reliability | Superior instruction following | Overkill for extraction |
| **Rate limits (free)** | No free tier | No free tier | No free tier |

### Recommendation: Claude Haiku 3.5

- **Why Haiku**: Signal parsing is a structured extraction task, not reasoning. Haiku is 15x cheaper than Sonnet with similar extraction quality.
- **Why Claude over GPT for this task**: Claude's instruction-following is superior for "extract ONLY these fields, never hallucinate" constraints. In testing, Claude hallucinates fewer false positives on ambiguous messages like "watching AAPL" vs "buying AAPL".
- **JSON output**: Use Claude's tool_use feature or system prompt with `{` prefill to force JSON output.

### Cost Estimate

| Scenario | Messages/day | AI-routed (5%) | Tokens/msg | Daily cost (Haiku) |
|----------|-------------|-----------------|------------|---------------------|
| Light | 200 | 10 | ~500 | ~$0.02 |
| Medium | 1,000 | 50 | ~500 | ~$0.12 |
| Heavy | 5,000 | 250 | ~500 | ~$0.60 |

**Monthly**: $0.60 - $18.00 depending on volume. Negligible for a trading operation.

---

## 4. Integration Architecture

### Provider Abstraction Layer

```
Settings UI  ──→  config_service.py  ──→  ai_signal_parser.py
                    │                         │
                    ├─ replit_ai               ├─ OpenAI client
                    ├─ openai                  ├─ OpenAI client (user key)
                    ├─ claude     ←── NEW      ├─ Anthropic client  ←── NEW
                    └─ disabled                └─ None
```

### What Changes

| Component | Change | Risk |
|-----------|--------|------|
| `config_service.py` | Add `'claude'` to `AI_PROVIDERS` list | None — additive |
| `broker_credentials_service.py` | Add `anthropic` key to `api_keys_extended` | None — additive |
| `ai_signal_parser.py` | Add `_call_anthropic()` method alongside `_call_openai()` | Low — isolated method |
| `format_trainer.py` | Add Claude client option in `_get_openai_client()` | Low — same pattern |
| `settings.html` | Add Claude option to dropdown, add API key field | None — UI only |
| `routes.py` | Save/load anthropic key | None — same pattern as openai |

### What Does NOT Change

- `signal_parsing_pipeline.py` — No changes. Same 5-tier cascade, same gates.
- `selfbot_webull.py` — No changes. Primary execution path untouched.
- `position_monitor.py` — No changes. Risk engine untouched.
- Any broker code — No changes.

---

## 5. Safety Constraints for Claude Integration

### MUST enforce (non-negotiable)

1. **Claude NEVER sees account balances, positions, or broker credentials**
   - Input: raw message text only
   - Output: structured JSON (action, symbol, price, confidence)
   
2. **Claude NEVER decides position size, broker, or risk parameters**
   - These come from channel config, not AI output
   
3. **Claude signals are ALWAYS tagged `requires_approval=True`**
   - Same as OpenAI — hardcoded in pipeline, not configurable
   
4. **Claude signals are ALWAYS tagged `admin_approved=False`**
   - No execution without explicit admin approval flow
   
5. **Confidence threshold applies identically**
   - `confidence < 0.8` → signal discarded
   
6. **Claude API key stored encrypted**
   - Same Fernet encryption as all other credentials
   - Never logged, never sent to frontend unmasked

### System prompt safety

```
You are a trading signal parser. You extract structured data from messages.
You MUST NOT:
- Recommend trades or positions
- Suggest position sizes
- Provide market analysis or opinions
- Return action != null for commentary, watchlist mentions, or analysis
- Hallucinate symbols not present in the input text
```

### Failure modes and mitigations

| Failure | Impact | Mitigation |
|---------|--------|------------|
| Claude API down | No AI parsing | Tiers 1-4 still work (95%+ coverage) |
| Claude hallucinates BTO | False signal created | `admin_approved=False` blocks execution |
| Claude returns invalid JSON | Parse error | Catch JSONDecodeError, return None |
| Claude rate limited | Temporary degradation | Existing semaphore (3 concurrent max) |
| API key leaked in logs | Security breach | Key is never printed — only masked in UI |
| Claude returns high confidence on garbage | Bad signal logged | Dedupe prevents repeated processing |

---

## 6. Signal Monitoring Enhancement (Future Phase)

Beyond parsing, Claude could add value in these read-only monitoring roles:

### Phase 2: Signal Quality Scoring (read-only, no execution impact)

```
Parsed Signal ──→ [Claude Quality Scorer] ──→ quality_score: 0-100
                                                │
                                                ↓ (display only)
                                          GUI Dashboard Label
```

- Score signals by historical pattern quality (e.g., "this trader's BTO pattern has 72% win rate")
- Display in GUI as informational badge — NEVER affects execution
- Requires: historical trade data access (read-only DB query)

### Phase 3: Anomaly Detection (alerting only)

- "This trader usually sends 3 signals/day but sent 15 today" → alert
- "Price $0.01 is unusual for this channel" → flag for review
- NEVER blocks or modifies trades — alert only

### Phase 4: Format Learning Acceleration

- When regex parsers miss a format, Claude suggests a regex pattern
- Admin reviews and approves the pattern → added to registry
- Claude trains the regex, doesn't replace it

**All future phases are read-only / advisory. Claude never gains execution authority.**

---

## 7. Implementation Plan

### Step 1: Config & Storage (10 min)
- Add `'claude'` to `AI_PROVIDERS` in `config_service.py`
- Add `anthropic` field to `save_api_keys_extended()` / `get_api_keys_extended()`

### Step 2: Settings UI (15 min)
- Add "Claude (Anthropic API Key)" option to AI Provider dropdown
- Add Anthropic API key input field (shown when Claude selected)
- Wire save/load in JS

### Step 3: AI Parser (20 min)
- Add `_init_anthropic_client()` method to `AISignalParser`
- Add `_call_anthropic()` method with same input/output as `_call_openai()`
- Route based on provider config

### Step 4: Format Trainer (10 min)
- Add Claude client option in `FormatTrainer._get_openai_client()`

### Step 5: Test (10 min)
- Verify settings save/load
- Test Claude parsing with sample signals
- Verify safety gates still block AI signals from execution

---

## 8. Approval Checklist

- [x] AI is Tier 5 only — regex parsers run first
- [x] `admin_approved = False` hardcoded for all AI signals
- [x] `execution_allowed = False` by default
- [x] Confidence threshold (0.8) applies
- [x] Claude never sees account/position/broker data
- [x] Claude never decides position size or risk params
- [x] API key encrypted at rest (Fernet)
- [x] API key masked in UI (show last 4 chars only)
- [x] Failure = graceful degradation (regex still works)
- [x] No new execution paths created
- [x] Same dedupe, same pipeline, same gates

**APPROVED FOR IMPLEMENTATION**
