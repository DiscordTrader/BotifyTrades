# Webull Official API vs Bot Implementation — Endpoint Comparison

**Date**: 2026-06-20
**Source**: Official Webull OpenAPI v2 documentation at developer.webull.com
**Scope**: Entry/exit execution, risk engine brackets, and order management

---

## Endpoint Coverage

| Webull API Endpoint | Bot Implementation | Status |
|---|---|---|
| `POST /openapi/trade/order/place` | `orders.py:place_stock_order`, `place_option_order`, `place_bracket_order`, `place_trailing_stop` | ✅ Used |
| `POST /openapi/trade/order/cancel` | `orders.py:cancel_order`, `cancel_order_by_broker_id` | ✅ Used |
| `POST /openapi/trade/order/replace` | `orders.py:replace_order` → `broker.py:replace_stop_price`, `modify_order` | ✅ Used |
| `GET /openapi/trade/order/open` | `orders.py:get_open_orders` | ✅ Used |
| `GET /openapi/trade/order/detail` | `orders.py:get_order_detail` | ✅ Used |
| `GET /openapi/trade/order/history` | `orders.py:get_order_history` | ✅ Used |
| `POST /openapi/trade/order/preview` | Not implemented | ❌ **Missing** |
| `POST /openapi/trade/order/batch-place` | Not implemented | ❌ **Missing** |
| `GET /openapi/assets/positions` | `positions.py:get_positions` | ✅ Used |
| `GET /openapi/assets/balance` | `accounts.py:get_balance` | ✅ Used |
| `GET /openapi/account/list` | `accounts.py:list_accounts` | ✅ Used |
| `GET /openapi/quote/option/query` | `broker.py:get_option_quote` | ✅ Used |
| gRPC `Subscribe Trade Events` | Not implemented | ❌ **Missing** |
| gRPC `Subscribe Position Events` | Not implemented | ❌ **Missing** |

---

## Order Type Comparison

### Stocks

| Webull API `order_type` | Bot `place_stock_order` | Status |
|---|---|---|
| `MARKET` | ✅ Mapped: `MARKET` → `MARKET` | ✅ Working |
| `LIMIT` | ✅ Mapped: `LIMIT` → `LIMIT` | ✅ Working |
| `STOP_LOSS` | ✅ Mapped: `STOP` → `STOP_LOSS` | ✅ Working |
| `STOP_LOSS_LIMIT` | ✅ Mapped: `STOP_LIMIT` → `STOP_LOSS_LIMIT` | ✅ Working |
| `TRAILING_STOP_LOSS` | ✅ Via `place_trailing_stop()` | ✅ Working |
| `MARKET_ON_OPEN` | Not implemented | ⚠️ Institutional only |
| `MARKET_ON_CLOSE` | Not implemented | ⚠️ Institutional only |
| `LIMIT_ON_OPEN` | Not implemented | ⚠️ Institutional only |

### Options

| Webull API `order_type` | Bot `place_option_order` | Status |
|---|---|---|
| `LIMIT` | ✅ Default order type | ✅ Working |
| `STOP_LOSS` | ✅ Mapped via `_opt_type_map` | ✅ **Fixed this session** |
| `STOP_LOSS_LIMIT` | ✅ Mapped: `STOP_LIMIT` → `STOP_LOSS_LIMIT` | ✅ **Fixed this session** |
| `MARKET` | ❌ Not supported by Webull API | ✅ Correctly simulated as LIMIT with live bid/ask |
| `TRAILING_STOP_LOSS` | ❌ Not supported for options | ✅ Correctly excluded |

---

## Parameter Comparison — Place Order

### Stock Order (`place_stock_order`)

| API Field | Required | Bot Implementation | Status |
|---|---|---|---|
| `client_order_id` | Yes | ✅ Auto-generated UUID | ✅ |
| `combo_type` | Yes | ✅ `"NORMAL"` | ✅ |
| `instrument_type` | Yes | ✅ `"EQUITY"` | ✅ |
| `entrust_type` | Yes | ✅ `"QTY"` | ✅ |
| `symbol` | Yes | ✅ Passed through | ✅ |
| `market` | Yes | ✅ `"US"` | ✅ |
| `side` | Yes | ✅ Mapped: BTO→BUY, STC→SELL, SHORT→SHORT, COVER→BUY | ✅ |
| `order_type` | Yes | ✅ Mapped: STOP→STOP_LOSS, STOP_LIMIT→STOP_LOSS_LIMIT | ✅ |
| `time_in_force` | Yes | ✅ DAY/GTC/IOC supported | ✅ |
| `quantity` | Yes | ✅ String-converted | ✅ |
| `limit_price` | Conditional | ✅ Rounded per Webull rules (2dp ≥$1, 4dp <$1) | ✅ |
| `stop_price` | Conditional | ✅ Rounded per Webull rules | ✅ |
| `support_trading_session` | No | ✅ `"ALL"` if extended_hours else `"CORE"` | ✅ **Fixed this session** |
| `total_cash_amount` | No | ❌ Not implemented (fractional shares) | ⚠️ Gap |
| `trailing_type` | Conditional | ✅ Via `place_trailing_stop` — `"AMOUNT"` | ✅ |
| `trailing_stop_step` | Conditional | ✅ Via `place_trailing_stop` | ✅ |

### Option Order (`place_option_order`)

| API Field | Required | Bot Implementation | Status |
|---|---|---|---|
| `client_order_id` | Yes | ✅ Auto-generated UUID | ✅ |
| `combo_type` | Yes | ✅ `"NORMAL"` | ✅ |
| `option_strategy` | Yes | ✅ `"SINGLE"` | ✅ |
| `instrument_type` | Yes | ✅ `"OPTION"` | ✅ |
| `entrust_type` | Yes | ✅ `"QTY"` | ✅ |
| `symbol` | Yes | ✅ Underlying symbol | ✅ |
| `market` | Yes | ✅ `"US"` | ✅ |
| `side` | Yes | ✅ BUY/SELL | ✅ |
| `order_type` | Yes | ✅ Mapped: STOP_LIMIT→STOP_LOSS_LIMIT, STOP→STOP_LOSS | ✅ **Fixed** |
| `time_in_force` | Yes | ✅ DAY for sell, GTC for buy | ✅ Matches API restriction |
| `quantity` | Yes | ✅ String-converted, int-forced | ✅ |
| `limit_price` | Conditional | ✅ With market sim + fallback | ✅ |
| `stop_price` | Conditional | ✅ Forwarded to API | ✅ **Fixed this session** |
| `position_intent` | No | ✅ BUY_TO_OPEN/SELL_TO_CLOSE/etc. | ✅ |
| `legs[].side` | Yes | ✅ From parent `side` | ✅ |
| `legs[].quantity` | Yes | ✅ String-converted | ✅ |
| `legs[].symbol` | Yes | ✅ Underlying | ✅ |
| `legs[].strike_price` | Yes | ✅ String-converted | ✅ |
| `legs[].option_expire_date` | Yes | ✅ Normalized to YYYY-MM-DD | ✅ |
| `legs[].instrument_type` | Yes | ✅ `"OPTION"` | ✅ |
| `legs[].option_type` | Yes | ✅ CALL/PUT | ✅ |
| `legs[].market` | Yes | ✅ `"US"` | ✅ |
| `legs[].position_effect` | No | ✅ OPEN/CLOSE | ✅ |

### Bracket Order (`place_bracket_order`)

| API Field | Required | Bot Implementation | Status |
|---|---|---|---|
| `client_combo_order_id` | Yes | ✅ Auto-generated UUID | ✅ |
| MASTER leg | Yes | ✅ Entry order with `combo_type: "MASTER"` | ✅ |
| STOP_PROFIT leg | No | ✅ Take profit with `combo_type: "STOP_PROFIT"`, `order_type: "LIMIT"` | ✅ |
| STOP_LOSS leg | No | ✅ Stop loss with `combo_type: "STOP_LOSS"`, `order_type: "STOP_LOSS"` | ✅ |
| OTO combo_type | Supported | ❌ Not implemented | ⚠️ Gap |
| OCO combo_type | Supported | ❌ Not implemented | ⚠️ Gap |
| OTOCO combo_type | Supported | ❌ Not implemented | ⚠️ Gap |

### Replace Order

| API Field | Bot Implementation | Status |
|---|---|---|
| `client_order_id` | ✅ Passed through | ✅ |
| `limit_price` | ✅ Optional | ✅ |
| `stop_price` | ✅ Optional | ✅ |
| `quantity` | ✅ Optional | ✅ |
| `time_in_force` | ✅ Optional | ✅ |
| `order_type` | ❌ Not passed (API allows changing STOP→MARKET etc.) | ⚠️ Gap |
| `trailing_stop_step` | ❌ Not passed | ⚠️ Gap |
| `legs` (option modify) | ❌ Not passed — option replace requires leg `id` + `quantity` | 🔴 **Gap** |

---

## Remaining Gaps (API features not used)

### 🔴 CRITICAL — Affects current functionality

| # | Gap | Impact | Status |
|---|---|---|---|
| 1 | **Option Replace `legs` array support** | `replace_order()` now accepts `leg_id` + `leg_quantity` and includes `legs: [{id, quantity}]` in the API call. Risk engine needs to store and forward `leg_id` from original placement. | ✅ **FIXED** — `replace_order()` + `modify_order()` both support `leg_id` param |
| 2 | **`STOP_LOSS` (pure stop) for options** | Added `place_option_stop()` — triggers market sell when stop_price reached. No limit floor needed. | ✅ **FIXED** — `broker.py:place_option_stop()` added |
| 3 | **gRPC Trade/Position Events** | Bot uses 5s polling for fill detection. Official API offers real-time gRPC streams. | ○ TODO (requires gRPC client implementation) |

### 🟡 HIGH — Missing enterprise features

| # | Gap | Impact | Status |
|---|---|---|---|
| 4 | **OCO (One Cancels Other)** | SL + PT linked, auto-cancel on fill | ✅ **FIXED** — `place_oco_order()` + `place_oco_bracket()` + risk engine OCO path |
| 5 | **OTO (One Triggers Other)** | Entry → bracket sequential, not atomic | ⚪ NOT NEEDED — entry and bracket are decoupled by design (fill confirmation gap) |
| 6 | **OTOCO (One Triggers OCO)** | Full atomic bracket in one API call | ⚪ NOT NEEDED — same reason as OTO; `place_bracket_order()` exists but unused |
| 7 | **Order Preview** | No pre-submission validation | ○ TODO (optional, BUY-side only, fail-open) |
| 8 | **Batch Place** | Sequential API calls for multi-position brackets | ○ TODO (optimization, not required) |
| 9 | **Trailing stop `PERCENTAGE` type** | Only `AMOUNT` was supported | ✅ **FIXED** — `trailing_type` param added to `place_trailing_stop()` |

### 🟢 LOW — Nice to have

| # | Gap | Impact | Status |
|---|---|---|---|
| 10 | **Fractional share trading** | API supports `entrust_type: "AMOUNT"` | ○ TODO |
| 11 | **Multi-leg option strategies** | VERTICAL, IRON_CONDOR, etc. | ○ TODO (requires strategy engine) |
| 12 | **`trailing_stop_step` modification via Replace** | Modify trail amount on active orders | ✅ **FIXED** — `replace_order()` + `modify_order()` accept `trailing_stop_step` |
---

## Risk Engine ↔ API Alignment

### Current Risk Engine Flow (per position)

```
Position Opens → _place_initial_broker_bracket()
  ├── Stocks:  place_stop_order(STOP_LOSS) + place_stock_order(LIMIT PT)  ← 2 API calls
  └── Options: place_option_stop_limit(STOP_LOSS_LIMIT) + place_option_order(LIMIT PT)  ← 2 API calls

SL Price Changes → replace_stop_price() → replace_order API  ← 1 API call (in-place modify) ✅

PT Fills → _replace_pt_bracket() → cancel old PT + place new PT  ← 2 API calls

SL Fills → _execute_exit() → cancel PT + place STC  ← 2 API calls
```

### Optimal Flow (using OCO/OTOCO)

```
Position Opens → place OTOCO bracket  ← 1 API call (entry + SL + PT atomically linked)
  ├── Entry fills → SL + PT auto-activate
  ├── SL fills → PT auto-cancels (no manual cancel needed)
  └── PT fills → SL auto-cancels (no manual cancel needed)

SL Price Changes → replace_order with stop_price  ← same as current ✅

PT Cascade → cancel OCO + place new OCO(SL+PT2)  ← 2 API calls (but SL/PT always linked)
```

### API Call Reduction

| Scenario | Current | With OTOCO/OCO |
|---|---|---|
| Initial bracket | 2-3 calls | **1 call** |
| SL fills, cancel PT | 2 calls | **0 calls** (auto) |
| PT fills, cancel SL | 2 calls | **0 calls** (auto) |
| PT cascade | 2 calls | 2 calls |
| **Total per position lifecycle** | **8-9 calls** | **3 calls** |

---

## Summary

### What's Working Well ✅
- All stock order types correctly mapped (MARKET, LIMIT, STOP_LOSS, STOP_LOSS_LIMIT, TRAILING_STOP_LOSS)
- Option order types now correctly mapped (post WO-1/WO-3 fix)
- stop_price now forwarded for option SL orders (post WO-1 fix)
- Extended hours session detection and auto-conversion
- In-place order modification via Replace API
- Price precision rules (2dp stocks ≥$1, 4dp <$1)
- Market order simulation for options (bid/ask → LIMIT)
- Buying power pre-validation

### Critical Gaps to Fix 🔴
1. **Option Replace needs `legs` array** — SL escalation via `replace_stop_price` may silently fail for options
2. **No OCO/OTOCO** — SL and PT are unlinked; manual cancel required when one fills
3. **No gRPC events** — 5s polling vs real-time fill detection

### Recommended Next Steps
1. Implement OCO for SL+PT pairing (biggest reliability win)
2. Add gRPC trade event subscription (fastest fill detection)
3. Store and forward `leg_id` for option Replace calls
4. Add `STOP_LOSS` (pure stop) as alternative to `STOP_LOSS_LIMIT` for options
