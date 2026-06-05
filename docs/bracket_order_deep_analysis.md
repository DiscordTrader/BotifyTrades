# Bracket Order Deep Analysis — All Brokers
## Based on actual code in `src/risk/position_monitor.py` and `src/brokers/*.py`

---

## Overview: What is a Bracket Order in BotifyTrades?

When the risk engine detects a new position, it places **two protective orders**:
1. **SL (Stop Loss)** — A stop order to sell if price drops below a threshold
2. **PT1 (Profit Target 1)** — A limit order to sell partial quantity at a profit target

These are placed via `_place_initial_broker_bracket()`. When trailing stops move, `_sync_stop_to_broker_inner()` cancels the old stop and replaces it with a new one at the updated price.

---

## Price Calculation (Common to All Brokers)

```
entry_price = cache.entry_price
sl_price  = entry_price * (1 - stop_loss_pct / 100)
pt1_price = entry_price * (1 + profit_target_1_pct / 100)
```

**Example**: AAPL entry $150, SL=10%, PT1=20%
```
sl_price  = $150 * 0.90 = $135.00
pt1_price = $150 * 1.20 = $180.00
```

---

## CBOE Tick Increment Rounding (Options Only)

Options exchanges require prices in specific increments:
- **Under $3.00**: $0.05 increments (penny pilot exceptions exist)
- **$3.00 and above**: $0.10 increments

```
_round_to_cboe_increment(price, is_sell, is_stop_trigger)
```

| Scenario | Direction |
|---|---|
| Sell Limit (PT) | Round DOWN (floor) — ensures fillable |
| Buy Limit | Round UP (ceil) — ensures fillable |
| Sell Stop Trigger | Round UP (ceil) — trigger not delayed |
| Buy Stop Trigger | Round DOWN (floor) — trigger not delayed |

---

# BROKER-BY-BROKER ANALYSIS

---

## 1. SCHWAB

### Stock Bracket — Initial Placement
```
Signal: BTO 100 AAPL @ $150.00, SL=10%, PT1=20%

┌─────────────────────────────────────────────────────────────────┐
│  _place_initial_broker_bracket (SCHWAB, stock)                  │
│                                                                 │
│  1. Auth check: schwab_broker.is_authenticated()                │
│  2. asset_type = 'EQUITY'                                       │
│  3. symbol used as-is (raw ticker: "AAPL")                      │
│                                                                 │
│  SL ORDER:                                                      │
│  ┌───────────────────────────────────────────────────────┐      │
│  │ schwab_broker.place_stop_order(                       │      │
│  │   symbol    = "AAPL",                                 │      │
│  │   quantity  = 100,                                    │      │
│  │   stop_price= 135.00,                                │      │
│  │   side      = "sell",                                 │      │
│  │   asset_type= "EQUITY",                              │      │
│  │   duration  = "GOOD_TILL_CANCEL"                      │      │
│  │ )                                                     │      │
│  │                                                       │      │
│  │ Schwab API payload:                                   │      │
│  │   orderType: "STOP"                                   │      │
│  │   stopPrice: 135.00                                   │      │
│  │   session: "NORMAL" (SEAMLESS forced to NORMAL)       │      │
│  │   instruction: "SELL"                                 │      │
│  │   assetType: "EQUITY"                                 │      │
│  └───────────────────────────────────────────────────────┘      │
│                                                                 │
│  PT1 ORDER:                                                     │
│  ┌───────────────────────────────────────────────────────┐      │
│  │ schwab_broker.place_stock_order(                      │      │
│  │   symbol   = "AAPL",                                  │      │
│  │   action   = "STC",                                   │      │
│  │   quantity = pt1_qty (calculated from tier allocation),│      │
│  │   price    = 180.00,                                  │      │
│  │   _skip_cancel_check = True                           │      │
│  │ )                                                     │      │
│  └───────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

### Option Bracket — Initial Placement
```
Signal: BTO 5 AAPL $150C 4/18 @ $3.50, SL=30%, PT1=50%
sl_price = $3.50 * 0.70 = $2.45
pt1_price = $3.50 * 1.50 = $5.25

┌─────────────────────────────────────────────────────────────────┐
│  _place_initial_broker_bracket (SCHWAB, option)                 │
│                                                                 │
│  1. Build OCC symbol:                                           │
│     _build_option_symbol("AAPL", "2026-04-18", 150.0, "C")     │
│     → "AAPL  260418C00150000"                                   │
│     (6-char padded + YYMMDD + C/P + strike*1000 8-digit)        │
│                                                                 │
│  2. INVALID_EXPIRY check — if OCC contains "INVALID_EXPIRY"     │
│     → skip order, don't submit bad symbol                       │
│                                                                 │
│  3. Index mapping: SPX→SPXW, NDX→NDXP, RUT→RUTW, DJX→DJXW     │
│                                                                 │
│  SL ORDER:                                                      │
│  ┌───────────────────────────────────────────────────────┐      │
│  │ schwab_broker.place_stop_order(                       │      │
│  │   symbol    = "AAPL  260418C00150000",  ← OCC format  │      │
│  │   quantity  = 5,                                      │      │
│  │   stop_price= 2.45,                                   │      │
│  │   side      = "sell_to_close",                        │      │
│  │   asset_type= "OPTION",                              │      │
│  │   duration  = "GOOD_TILL_CANCEL"                      │      │
│  │ )                                                     │      │
│  │                                                       │      │
│  │ INSIDE place_stop_order:                              │      │
│  │   CBOE snap: $2.45 → $2.45 (already on $0.05 tick)   │      │
│  │   is_stop_trigger=True → round UP for sell stops      │      │
│  │   instruction: "SELL_TO_CLOSE"                        │      │
│  │   session forced: SEAMLESS → NORMAL for STOP orders   │      │
│  └───────────────────────────────────────────────────────┘      │
│                                                                 │
│  PT1 ORDER:                                                     │
│  ┌───────────────────────────────────────────────────────┐      │
│  │ schwab_broker.place_option_order(                     │      │
│  │   symbol   = "AAPL",       ← underlying, NOT OCC      │      │
│  │   strike   = 150.0,                                   │      │
│  │   expiry   = "4/18",                                  │      │
│  │   option_type = "C",                                  │      │
│  │   action   = "STC",                                   │      │
│  │   quantity = pt1_qty,                                 │      │
│  │   price    = 5.25,                                    │      │
│  │   _skip_cancel_check = True                           │      │
│  │ )                                                     │      │
│  │                                                       │      │
│  │ INSIDE place_option_order:                            │      │
│  │   CBOE snap: $5.25 → $5.30 (round UP for buy fill,   │      │
│  │              but is_sell=True for STC → round DOWN)    │      │
│  │   Actually: $5.25 → $5.20 (floor to $0.10 tick)      │      │
│  │   Builds OCC internally via _build_option_symbol      │      │
│  │   instruction: "SELL_TO_CLOSE"                        │      │
│  └───────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

### Stop Sync (trailing stop update)
```
┌─────────────────────────────────────────────────────────────────┐
│  _sync_stop_to_broker_inner (SCHWAB)                            │
│                                                                 │
│  1. Cancel old stop: schwab_broker.cancel_order(old_id)         │
│     — If cancel fails → SKIP new stop (avoid duplicates)        │
│                                                                 │
│  2. For options: rebuild OCC symbol (same logic as initial)     │
│     — INVALID_EXPIRY check → skip if bad                        │
│                                                                 │
│  3. schwab_broker.place_stop_order(                             │
│       symbol = OCC or ticker,                                   │
│       stop_price = new_trailing_stop,                           │
│       side = "sell_to_close" (opt) / "sell" (stock),            │
│       asset_type = "OPTION" / "EQUITY",                         │
│       duration = "GOOD_TILL_CANCEL"                             │
│     )                                                           │
│     — CBOE rounding done INSIDE place_stop_order for options    │
└─────────────────────────────────────────────────────────────────┘
```

### Schwab API Facts (per official Schwab Trader API docs)
- Supports STOP orders for both EQUITY and OPTION
- Options require OCC symbol format (6-char padded underlying + YYMMDD + C/P + 8-digit strike)
- SEAMLESS session does NOT support STOP orders → forced to NORMAL
- STOP order triggers a MARKET order when hit
- GTC duration supported for both equity and option stops
- CBOE tick rounding handled inside broker module

---

## 2. ALPACA

### Stock Bracket — Initial Placement
```
Signal: BTO 50 TSLA @ $200.00, SL=8%, PT1=15%
sl_price = $184.00, pt1_price = $230.00

┌─────────────────────────────────────────────────────────────────┐
│  _place_initial_broker_bracket (ALPACA, stock)                  │
│                                                                 │
│  1. Connected check: alpaca_broker.connected                    │
│  2. Uses trading_client.submit_order() directly (not broker     │
│     wrapper methods)                                            │
│                                                                 │
│  SL ORDER:                                                      │
│  ┌───────────────────────────────────────────────────────┐      │
│  │ StopOrderRequest(                                     │      │
│  │   symbol      = "TSLA",                               │      │
│  │   qty         = 50,                                   │      │
│  │   side        = OrderSide.SELL,                       │      │
│  │   stop_price  = 184.00,   ← round(sl_price, 2)       │      │
│  │   time_in_force = TimeInForce.GTC                     │      │
│  │ )                                                     │      │
│  │ → trading_client.submit_order(req)                    │      │
│  └───────────────────────────────────────────────────────┘      │
│                                                                 │
│  PT1 ORDER:                                                     │
│  ┌───────────────────────────────────────────────────────┐      │
│  │ LimitOrderRequest(                                    │      │
│  │   symbol      = "TSLA",                               │      │
│  │   qty         = pt1_qty,                              │      │
│  │   side        = OrderSide.SELL,                       │      │
│  │   limit_price = 230.00,   ← round(pt1_price, 2)      │      │
│  │   time_in_force = TimeInForce.GTC                     │      │
│  │ )                                                     │      │
│  │ → trading_client.submit_order(req)                    │      │
│  └───────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

### Option Bracket — Initial Placement
```
Signal: BTO 3 SPY $450C 4/18 @ $5.00, SL=25%, PT1=40%
sl_price = $3.75, pt1_price = $7.00

┌─────────────────────────────────────────────────────────────────┐
│  _place_initial_broker_bracket (ALPACA, option)                 │
│                                                                 │
│  1. INDEX GUARD: check position.symbol against                  │
│     {SPX, SPXW, NDX, NDXP, RUT, RUTW, VIX, VIXW, XSP, DJX}   │
│     → If index option: SKIP entire bracket, set placed=True     │
│     ⚠️ Alpaca does NOT support index options                    │
│                                                                 │
│  2. TIF = TimeInForce.DAY (options)                             │
│     position_intent = PositionIntent.SELL_TO_CLOSE              │
│                                                                 │
│  SL ORDER:                                                      │
│  ┌───────────────────────────────────────────────────────┐      │
│  │ StopOrderRequest(                                     │      │
│  │   symbol          = "SPY250418C00450000", ← contract  │      │
│  │   qty             = 3,                                │      │
│  │   side            = OrderSide.SELL,                   │      │
│  │   stop_price      = 3.75,  ← round(sl_price, 2)      │      │
│  │   time_in_force   = TimeInForce.DAY,                  │      │
│  │   position_intent = PositionIntent.SELL_TO_CLOSE      │      │
│  │ )                                                     │      │
│  └───────────────────────────────────────────────────────┘      │
│                                                                 │
│  PT1 ORDER:                                                     │
│  ┌───────────────────────────────────────────────────────┐      │
│  │ LimitOrderRequest(                                    │      │
│  │   symbol          = "SPY250418C00450000",             │      │
│  │   qty             = pt1_qty,                          │      │
│  │   side            = OrderSide.SELL,                   │      │
│  │   limit_price     = 7.00,                             │      │
│  │   time_in_force   = TimeInForce.DAY,                  │      │
│  │   position_intent = PositionIntent.SELL_TO_CLOSE      │      │
│  │ )                                                     │      │
│  └───────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

### Stop Sync
```
┌─────────────────────────────────────────────────────────────────┐
│  _sync_stop_to_broker_inner (ALPACA)                            │
│                                                                 │
│  1. Cancel old: trading_client.cancel_order_by_id(old_id)       │
│  2. Index guard: same check for options, skip if index          │
│  3. StopOrderRequest(                                           │
│       symbol, qty, OrderSide.SELL, stop_price=new_price,        │
│       time_in_force=DAY(opt)/GTC(stock),                        │
│       position_intent=SELL_TO_CLOSE (options only)              │
│     )                                                           │
└─────────────────────────────────────────────────────────────────┘
```

### Alpaca API Facts (per official Alpaca Trading API docs)
- Supports StopOrderRequest for both stocks and equity options
- Options use contract symbol format (resolved via GetOptionContractsRequest)
- Options require `position_intent` (SELL_TO_CLOSE) to avoid uncovered-option errors
- Options TIF: DAY only (GTC not supported for option stop orders)
- NO index options (SPX/NDX/VIX/RUT) — equity options only
- $0.01 tick increments accepted (no CBOE rounding needed)
- ExerciseStyle.AMERICAN only

---

## 3. IBKR (Interactive Brokers)

### Stock Bracket — Initial Placement
```
Signal: BTO 200 MSFT @ $400.00, SL=5%, PT1=10%
sl_price = $380.00, pt1_price = $440.00

┌─────────────────────────────────────────────────────────────────┐
│  _place_initial_broker_bracket (IBKR, stock)                    │
│                                                                 │
│  1. Connection check: ibkr_broker.ib.isConnected()              │
│  2. Contract: Stock("MSFT", "SMART", "USD")                     │
│     → qualifyContractsAsync(contract)                           │
│                                                                 │
│  SL ORDER:                                                      │
│  ┌───────────────────────────────────────────────────────┐      │
│  │ sl_order = StopOrder("SELL", 200, 380.00)             │      │
│  │ sl_order.tif = "GTC"        ← CRITICAL: explicit GTC  │      │
│  │ sl_order.outsideRth = True/False (from settings)      │      │
│  │ → ib.placeOrder(contract, sl_order)                   │      │
│  │ → sleep(1s) for acknowledgment                        │      │
│  │ → check status in whitelist:                          │      │
│  │   ('Submitted','PreSubmitted','PendingSubmit',        │      │
│  │    'Filled','ApiPending')                             │      │
│  └───────────────────────────────────────────────────────┘      │
│                                                                 │
│  PT1 ORDER:                                                     │
│  ┌───────────────────────────────────────────────────────┐      │
│  │ pt_order = LimitOrder("SELL", pt1_qty, 440.00)        │      │
│  │ pt_order.tif = "GTC"                                  │      │
│  │ pt_order.outsideRth = True/False                      │      │
│  │ → ib.placeOrder(contract, pt_order)                   │      │
│  └───────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

### Option Bracket — Initial Placement
```
Signal: BTO 10 AAPL $180C 4/25 @ $4.20, SL=30%, PT1=50%
sl_price = $2.94, pt1_price = $6.30

┌─────────────────────────────────────────────────────────────────┐
│  _place_initial_broker_bracket (IBKR, option)                   │
│                                                                 │
│  1. Contract: Option("AAPL", "20260425", 180.0, "C", "SMART")  │
│     → _normalize_expiry_yyyymmdd("4/25") → "20260425"          │
│     → qualifyContractsAsync(contract)                           │
│                                                                 │
│  2. CBOE rounding:                                              │
│     SL: $2.94 → _round_to_cboe(2.94, sell=True, stop=True)     │
│         Under $3 → $0.05 tick, stop trigger → round UP          │
│         $2.94 → $2.95                                           │
│     PT: $6.30 → _round_to_cboe(6.30, sell=True, stop=False)    │
│         Over $3 → $0.10 tick, sell limit → round DOWN           │
│         $6.30 → $6.30 (already on tick)                         │
│                                                                 │
│  SL ORDER:                                                      │
│  ┌───────────────────────────────────────────────────────┐      │
│  │ sl_order = StopOrder("SELL", 10, 2.95)  ← CBOE snapped│     │
│  │ sl_order.tif = "GTC"                                  │      │
│  │ sl_order.outsideRth = True/False                      │      │
│  │ → ib.placeOrder(option_contract, sl_order)            │      │
│  │ → check status whitelist                              │      │
│  └───────────────────────────────────────────────────────┘      │
│                                                                 │
│  PT1 ORDER:                                                     │
│  ┌───────────────────────────────────────────────────────┐      │
│  │ pt_order = LimitOrder("SELL", pt1_qty, 6.30)          │      │
│  │ pt_order.tif = "GTC"                                  │      │
│  │ pt_order.outsideRth = True/False                      │      │
│  │ → ib.placeOrder(option_contract, pt_order)            │      │
│  └───────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

### Stop Sync
```
┌─────────────────────────────────────────────────────────────────┐
│  _sync_stop_to_broker_inner (IBKR)                              │
│                                                                 │
│  1. Cancel old via _cancel_single_order()                       │
│  2. Build contract (Stock or Option with qualifyContractsAsync) │
│  3. For options: CBOE snap new_stop_price                       │
│     _round_to_cboe(price, sell=True, stop_trigger=True)         │
│  4. StopOrder("SELL", qty, snapped_price)                       │
│     tif = "GTC"                                                 │
│     outsideRth from settings                                    │
│  5. Check status whitelist                                      │
└─────────────────────────────────────────────────────────────────┘
```

### IBKR API Facts (per official IB TWS/Gateway API docs)
- Supports StopOrder for both stocks and options natively
- Options use ib_insync Option(symbol, expiry_YYYYMMDD, strike, right, exchange)
- Contract must be qualified via qualifyContractsAsync before order placement
- Default TIF is empty string which IB treats as DAY → must set tif="GTC" explicitly
- outsideRth controls extended hours execution
- Status "PreSubmitted" is valid (means held by IB gateway, not yet at exchange)
- Supports index options natively (SPX, NDX, VIX via CBOE)
- CBOE tick rounding required — IB rejects off-tick prices

---

## 4. TASTYTRADE

### Stock Bracket — Initial Placement
```
Signal: BTO 100 AMD @ $120.00, SL=7%, PT1=12%
sl_price = $111.60, pt1_price = $134.40

┌─────────────────────────────────────────────────────────────────┐
│  _place_initial_broker_bracket (TASTYTRADE, stock)              │
│                                                                 │
│  1. Session check: _ensure_session_valid()                      │
│  2. Get equity instrument: Equity.get(session, "AMD")           │
│                                                                 │
│  SL ORDER:                                                      │
│  ┌───────────────────────────────────────────────────────┐      │
│  │ sl_leg = equity.build_leg(Decimal("100"),             │      │
│  │                           OrderAction.SELL_TO_CLOSE)  │      │
│  │ sl_order = NewOrder(                                  │      │
│  │   time_in_force = OrderTimeInForce.GTC,               │      │
│  │   order_type    = OrderType.STOP,                     │      │
│  │   legs          = [sl_leg],                           │      │
│  │   stop_trigger  = Decimal("111.60")                   │      │
│  │ )                                                     │      │
│  │ → account.place_order(session, sl_order, dry_run=False)│     │
│  └───────────────────────────────────────────────────────┘      │
│                                                                 │
│  PT1 ORDER:                                                     │
│  ┌───────────────────────────────────────────────────────┐      │
│  │ Uses _place_tastytrade_stock_limit_gtc() helper       │      │
│  │ → Builds Equity leg + NewOrder(LIMIT, GTC, price)     │      │
│  └───────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

### Option Bracket — Initial Placement
```
Signal: BTO 5 NVDA $900C 5/16 @ $12.00, SL=25%, PT1=40%
sl_price = $9.00, pt1_price = $16.80

┌─────────────────────────────────────────────────────────────────┐
│  _place_initial_broker_bracket (TASTYTRADE, option)             │
│                                                                 │
│  ⚠️ TastyTrade does NOT support STOP orders for options.        │
│  SL is placed as a SELL LIMIT order at the stop price instead.  │
│                                                                 │
│  1. CBOE rounding:                                              │
│     SL: $9.00 → _round_to_cboe(9.00, sell=True)                │
│         Over $3 → $0.10 tick, sell limit → round DOWN           │
│         $9.00 → $9.00 (on tick)                                 │
│     PT: $16.80 → _round_to_cboe(16.80, sell=True)              │
│         $16.80 → $16.80 (on tick)                               │
│                                                                 │
│  SL ORDER (actually a LIMIT):                                   │
│  ┌───────────────────────────────────────────────────────┐      │
│  │ tastytrade_broker.place_option_order(                 │      │
│  │   symbol      = "NVDA",                               │      │
│  │   strike      = 900.0,                                │      │
│  │   expiry      = "5/16",                               │      │
│  │   option_type = "C",                                  │      │
│  │   action      = "STC",                                │      │
│  │   quantity    = 5,                                    │      │
│  │   price       = 9.00   ← CBOE snapped                │      │
│  │ )                                                     │      │
│  │                                                       │      │
│  │ INSIDE place_option_order:                            │      │
│  │   → get_option_chain(session, "NVDA")                 │      │
│  │   → find matching strike/expiry/type                  │      │
│  │   → build_leg(Decimal("5"), SELL_TO_CLOSE)            │      │
│  │   → NewOrder(DAY, LIMIT, legs, price=Decimal("9.00")) │      │
│  │   ⚠️ TIF = DAY (not GTC) for TastyTrade options      │      │
│  └───────────────────────────────────────────────────────┘      │
│                                                                 │
│  PT1 ORDER:                                                     │
│  ┌───────────────────────────────────────────────────────┐      │
│  │ Same as SL: place_option_order(..., price=16.80)      │      │
│  │ → NewOrder(DAY, LIMIT, price=Decimal("16.80"))        │      │
│  └───────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

### Stop Sync
```
┌─────────────────────────────────────────────────────────────────┐
│  _sync_stop_to_broker_inner (TASTYTRADE)                        │
│                                                                 │
│  STOCK:                                                         │
│    Cancel old → Equity.get → build_leg(SELL_TO_CLOSE)           │
│    → NewOrder(GTC, STOP, stop_trigger=new_price)                │
│                                                                 │
│  OPTION:                                                        │
│    Cancel old → CBOE snap new_stop_price (sell=True)            │
│    → place_option_order(action="STC", price=snapped_price)      │
│    → Places as LIMIT (not STOP) with TIF=DAY                   │
└─────────────────────────────────────────────────────────────────┘
```

### TastyTrade API Facts (per official tastytrade API docs)
- Stock STOP orders: supported with `stop_trigger` parameter, GTC TIF
- Option STOP orders: NOT supported — API rejects stop_trigger on option legs
- Option orders use LIMIT type only, TIF=DAY (not GTC) per API constraint
- Option chain resolution via `get_option_chain(session, symbol)`
- Price is negative Decimal for BTO (debit), positive for STC (credit)
- Supports index options (SPX, NDX) via option chain lookup
- CBOE tick rounding required — exchange rejects off-tick prices

---

## 5. WEBULL

### Stock Bracket — Initial Placement
```
Signal: BTO 100 META @ $500.00, SL=6%, PT1=10%
sl_price = $470.00, pt1_price = $550.00

┌─────────────────────────────────────────────────────────────────┐
│  _place_initial_broker_bracket (WEBULL, stock)                  │
│                                                                 │
│  1. Get raw client: broker._client or broker.wb                 │
│  2. Resolve ticker ID: webull_data_hub → wb_client.get_ticker() │
│                                                                 │
│  SL ORDER:                                                      │
│  ┌───────────────────────────────────────────────────────┐      │
│  │ wb_client.place_order(                                │      │
│  │   stock   = "META",                                   │      │
│  │   tId     = 913255135,     ← Webull internal ticker ID│      │
│  │   stpPrice= 470.00,       ← round(sl_price, 2)       │      │
│  │   action  = "SELL",                                   │      │
│  │   orderType = "STP",                                  │      │
│  │   enforce = "GTC",                                    │      │
│  │   quant   = 100,                                      │      │
│  │   outsideRegularTradingHour = True                    │      │
│  │ )                                                     │      │
│  │                                                       │      │
│  │ RETRY: If extHrs=True fails → retry with extHrs=False │      │
│  │ Response: {data: {orderId: "123456"}} or {msg: "..."}│      │
│  └───────────────────────────────────────────────────────┘      │
│                                                                 │
│  PT1 ORDER:                                                     │
│  ┌───────────────────────────────────────────────────────┐      │
│  │ wb_client.place_order(                                │      │
│  │   stock   = "META",                                   │      │
│  │   tId     = 913255135,                                │      │
│  │   price   = 550.00,                                   │      │
│  │   action  = "SELL",                                   │      │
│  │   orderType = "LMT",                                  │      │
│  │   enforce = "GTC",                                    │      │
│  │   quant   = pt1_qty,                                  │      │
│  │   outsideRegularTradingHour = True                    │      │
│  │ )                                                     │      │
│  └───────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

### Option Bracket — Initial Placement
```
Signal: BTO 2 SPY $520C 4/18 @ $4.50, SL=30%, PT1=50%

┌─────────────────────────────────────────────────────────────────┐
│  _place_initial_broker_bracket (WEBULL, option)                 │
│                                                                 │
│  SL ORDER:                                                      │
│  ┌───────────────────────────────────────────────────────┐      │
│  │ ⚠️ "Webull does not support stop orders for options"  │      │
│  │ → SL monitored locally by risk engine (software stop) │      │
│  │ → No broker-side stop placed                          │      │
│  └───────────────────────────────────────────────────────┘      │
│                                                                 │
│  PT1 ORDER:                                                     │
│  ┌───────────────────────────────────────────────────────┐      │
│  │ 1. Resolve option_id from Webull option chain         │      │
│  │    _resolve_webull_option_id(broker, position)        │      │
│  │    → Gets Webull's internal option_id string          │      │
│  │                                                       │      │
│  │ 2. broker.place_option_order(                         │      │
│  │      symbol    = "SPY",                               │      │
│  │      strike    = 520.0,                               │      │
│  │      expiry    = "4/18",                              │      │
│  │      option_type = "C",                               │      │
│  │      action    = "STC",                               │      │
│  │      quantity  = pt1_qty,                             │      │
│  │      price     = pt1_price,                           │      │
│  │      option_id = "abc123..."                          │      │
│  │    )                                                  │      │
│  │                                                       │      │
│  │ INSIDE place_option_order:                            │      │
│  │   → Get bid price for STC aggressive fill             │      │
│  │   → CBOE snap: _round_to_cboe_increment(price, sell) │      │
│  │   → wb.place_order_option(option_id, lmtPrice, ...)  │      │
│  │   → Retry with tighter buffers if unfilled            │      │
│  └───────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

### Stop Sync
```
┌─────────────────────────────────────────────────────────────────┐
│  _sync_stop_to_broker_inner (WEBULL)                            │
│                                                                 │
│  OPTION: "Webull options don't support stop orders" → return    │
│                                                                 │
│  STOCK:                                                         │
│    Cancel old → check _webull_stp_unsupported flag              │
│    → wb_client.place_order(STP, GTC, extHrs retry)              │
│    → round(price, 4 if <$1 else 2)                             │
└─────────────────────────────────────────────────────────────────┘
```

### Webull API Facts (per Webull OpenAPI/webull-python-sdk)
- Stock stops: STP orderType with stpPrice, GTC enforce, outsideRegularTradingHour
- Option stops: NOT SUPPORTED by Webull API — no stop order type for options
- Option limit orders: require option_id resolved from Webull's chain
- Requires internal tId (ticker ID) for all stock orders — not just ticker symbol
- Extended hours: outsideRegularTradingHour=True may be rejected for some order types
- CBOE rounding done inside place_option_order for limit orders
- No CBOE rounding needed for stock stop triggers (exchange handles)

---

## 6. ROBINHOOD

### Stock Bracket — Initial Placement
```
Signal: BTO 50 GOOGL @ $170.00, SL=5%, PT1=10%
sl_price = $161.50, pt1_price = $187.00

┌─────────────────────────────────────────────────────────────────┐
│  _place_initial_broker_bracket (ROBINHOOD, stock)               │
│                                                                 │
│  1. Login check: robinhood_broker._logged_in                    │
│                                                                 │
│  SL ORDER:                                                      │
│  ┌───────────────────────────────────────────────────────┐      │
│  │ robinhood_broker.place_stock_order(                   │      │
│  │   symbol     = "GOOGL",                               │      │
│  │   action     = "STC",                                 │      │
│  │   quantity   = 50,                                    │      │
│  │   stop_price = 161.50                                 │      │
│  │ )                                                     │      │
│  │                                                       │      │
│  │ INSIDE place_stock_order:                             │      │
│  │   → rh.orders.order_sell_stop_loss(                   │      │
│  │       symbol="GOOGL", quantity=50,                    │      │
│  │       stopPrice=161.50, timeInForce="gtc"             │      │
│  │     )                                                 │      │
│  │   ⚠️ Extended hours DISABLED for stop orders          │      │
│  │   (Robinhood doesn't support extHrs stops)            │      │
│  └───────────────────────────────────────────────────────┘      │
│                                                                 │
│  PT1 ORDER:                                                     │
│  ┌───────────────────────────────────────────────────────┐      │
│  │ robinhood_broker.place_stock_order(                   │      │
│  │   symbol   = "GOOGL",                                 │      │
│  │   action   = "STC",                                   │      │
│  │   quantity = pt1_qty,                                 │      │
│  │   price    = 187.00                                   │      │
│  │ )                                                     │      │
│  │   → rh.orders.order_sell_limit(                       │      │
│  │       symbol="GOOGL", quantity=pt1_qty,               │      │
│  │       limitPrice=187.00, timeInForce="gtc",           │      │
│  │       extendedHours=True/False (from settings)        │      │
│  │     )                                                 │      │
│  └───────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

### Option Bracket — Initial Placement
```
Signal: BTO 3 AMZN $190C 4/25 @ $5.20, SL=25%, PT1=40%

┌─────────────────────────────────────────────────────────────────┐
│  _place_initial_broker_bracket (ROBINHOOD, option)              │
│                                                                 │
│  SL ORDER:                                                      │
│  ┌───────────────────────────────────────────────────────┐      │
│  │ ⚠️ "Robinhood does not support stop orders for        │      │
│  │    options — SL will be monitored locally"             │      │
│  │ → No broker-side stop placed                          │      │
│  └───────────────────────────────────────────────────────┘      │
│                                                                 │
│  PT1 ORDER:                                                     │
│  ┌───────────────────────────────────────────────────────┐      │
│  │ robinhood_broker.place_option_order(                  │      │
│  │   symbol      = "AMZN",                               │      │
│  │   strike      = 190.0,                                │      │
│  │   expiry      = "4/25",                               │      │
│  │   option_type = "C",                                  │      │
│  │   action      = "STC",                                │      │
│  │   quantity    = pt1_qty,                              │      │
│  │   price       = pt1_price                             │      │
│  │ )                                                     │      │
│  │                                                       │      │
│  │ INSIDE place_option_order:                            │      │
│  │   → _normalize_expiry("4/25") → "2026-04-25"         │      │
│  │   → Tick rounding:                                    │      │
│  │     Index options: $0.05 (round(price*20)/20)         │      │
│  │     Standard: $0.01 (round(price*100)/100)            │      │
│  │     ⚠️ NOT CBOE standard ($0.05/$0.10)               │      │
│  │     Robinhood API accepts $0.01 ticks for standard    │      │
│  │   → rh.orders.order_sell_option_limit(                │      │
│  │       positionEffect="close",                         │      │
│  │       creditOrDebit="credit",                         │      │
│  │       price=snapped_price, ...)                       │      │
│  └───────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

### Stop Sync
```
┌─────────────────────────────────────────────────────────────────┐
│  _sync_stop_to_broker_inner (ROBINHOOD)                         │
│                                                                 │
│  OPTION: "Robinhood options don't support stop orders" → return │
│                                                                 │
│  STOCK:                                                         │
│    Cancel old → place_stock_order(action="STC",                 │
│                   stop_price=new_price)                          │
│    → rh.orders.order_sell_stop_loss(timeInForce="gtc")          │
└─────────────────────────────────────────────────────────────────┘
```

### Robinhood API Facts (per robin_stocks library / Robinhood API)
- Stock stops: order_sell_stop_loss with timeInForce="gtc"
- Stock limits: order_sell_limit with optional extendedHours
- Option stops: NOT SUPPORTED — only limit orders for options
- Options: LIMIT orders only, require limit price always
- Tick rounding: $0.01 for standard options, $0.05 for index options
- Extended hours: disabled for stop orders, optional for limit orders
- Options require positionEffect and creditOrDebit parameters

---

## 7. TRADING212

### Stock Bracket — Initial Placement
```
Signal: BTO 20 AAPL @ $180.00, SL=5%, PT1=10%
sl_price = $171.00, pt1_price = $198.00

┌─────────────────────────────────────────────────────────────────┐
│  _place_initial_broker_bracket (TRADING212, stock)              │
│                                                                 │
│  1. Connected check + instruments_ready check                   │
│  2. Options guard: "T212 does not support options" → skip       │
│                                                                 │
│  SL ORDER:                                                      │
│  ┌───────────────────────────────────────────────────────┐      │
│  │ trading212_broker.place_stop_order(                   │      │
│  │   symbol     = "AAPL",                                │      │
│  │   action     = "STC",                                 │      │
│  │   quantity   = 20,                                    │      │
│  │   stop_price = 171.00                                 │      │
│  │ )                                                     │      │
│  │                                                       │      │
│  │ INSIDE place_stop_order:                              │      │
│  │   → _translate_ticker("AAPL") → T212 internal ticker  │      │
│  │   → qty = -20 (negative for STC)                      │      │
│  │   → client.place_stop_order(ticker, -20, 171.00, GTC) │      │
│  │   → Returns {success, data: {id, status}}             │      │
│  └───────────────────────────────────────────────────────┘      │
│                                                                 │
│  PT1 ORDER:                                                     │
│  ┌───────────────────────────────────────────────────────┐      │
│  │ trading212_broker.place_stock_order(                  │      │
│  │   symbol   = "AAPL",                                  │      │
│  │   action   = "STC",                                   │      │
│  │   quantity = pt1_qty,                                 │      │
│  │   price    = 198.00                                   │      │
│  │ )                                                     │      │
│  │   → _translate_ticker → place limit order             │      │
│  └───────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

### Option Bracket
```
┌─────────────────────────────────────────────────────────────────┐
│  ⚠️ Trading212 does NOT support options trading at all.         │
│  If is_option → "T212 does not support options"                 │
│  → broker_orders_placed = True (skip silently)                  │
└─────────────────────────────────────────────────────────────────┘
```

### Stop Sync
```
┌─────────────────────────────────────────────────────────────────┐
│  _sync_stop_to_broker_inner (TRADING212)                        │
│                                                                 │
│  OPTION: silent return (no options support)                     │
│                                                                 │
│  STOCK:                                                         │
│    Cancel old → place_stop_order(symbol, "STC", qty, new_price) │
│    → _translate_ticker → client.place_stop_order(GTC)           │
└─────────────────────────────────────────────────────────────────┘
```

### Trading212 API Facts (per official T212 API v0 docs)
- Stocks only — no options support
- Stop orders: POST with negative quantity for sell, GTC supported
- Limit orders: POST with price parameter
- StopLimit orders: supported (stop_price + limit_price)
- Requires ticker translation (AAPL → T212 internal instrument ticker)
- All order types work on both LIVE and DEMO accounts
- Rate limits: POST 1 req/2s, GET/DELETE 1 req/5s

---

## SUMMARY MATRIX

```
┌──────────────┬──────────┬──────────┬──────────────┬──────────┬───────────────┬──────────────┐
│              │ STOCK SL │ STOCK PT │ OPTION SL    │ OPTION PT│ CBOE ROUNDING │ INDEX OPTS   │
├──────────────┼──────────┼──────────┼──────────────┼──────────┼───────────────┼──────────────┤
│ SCHWAB       │ STOP/GTC │ LMT/GTC  │ STOP/GTC     │ LMT/GTC  │ YES (broker)  │ YES (mapped) │
│              │          │          │ OCC symbol   │ OCC built│ stop_trigger  │ SPX→SPXW etc │
├──────────────┼──────────┼──────────┼──────────────┼──────────┼───────────────┼──────────────┤
│ ALPACA       │ STOP/GTC │ LMT/GTC  │ STOP/DAY     │ LMT/DAY  │ NO ($0.01 ok) │ NO (blocked) │
│              │          │          │ +SELL_TO_CLOSE│ +STC     │               │ guard in code│
├──────────────┼──────────┼──────────┼──────────────┼──────────┼───────────────┼──────────────┤
│ IBKR         │ STOP/GTC │ LMT/GTC  │ STOP/GTC     │ LMT/GTC  │ YES (monitor) │ YES (native) │
│              │ outsideRth│outsideRth│ CBOE snapped │ CBOE snap│ stop_trigger  │ via Option() │
├──────────────┼──────────┼──────────┼──────────────┼──────────┼───────────────┼──────────────┤
│ TASTYTRADE   │ STOP/GTC │ LMT/GTC  │ LIMIT/DAY ⚠️ │ LMT/DAY  │ YES (monitor) │ YES (chain)  │
│              │stop_trig │          │ (no stop API)│ CBOE snap│               │              │
├──────────────┼──────────┼──────────┼──────────────┼──────────┼───────────────┼──────────────┤
│ WEBULL       │ STP/GTC  │ LMT/GTC  │ LOCAL ONLY ⚠️│ LMT/DAY  │ YES (broker)  │ N/A          │
│              │ extHrs   │ extHrs   │ (no stop API)│ option_id│ (options only)│ (chain fail) │
├──────────────┼──────────┼──────────┼──────────────┼──────────┼───────────────┼──────────────┤
│ ROBINHOOD    │ STOP/GTC │ LMT/GTC  │ LOCAL ONLY ⚠️│ LMT only │ NO ($0.01 ok) │ YES (sends)  │
│              │ no extHrs│ extHrs ok│ (no stop API)│ limit req│ $0.05 for idx │ API decides  │
├──────────────┼──────────┼──────────┼──────────────┼──────────┼───────────────┼──────────────┤
│ TRADING212   │ STOP/GTC │ LMT/GTC  │ N/A          │ N/A      │ N/A           │ N/A          │
│              │ neg qty  │ neg qty  │ (no options) │          │ (stocks only) │ (stocks only)│
└──────────────┴──────────┴──────────┴──────────────┴──────────┴───────────────┴──────────────┘
```

⚠️ = Known API limitation, handled by design (SL monitored locally by risk engine)

---

## GAPS FOUND AND FIXED IN THIS AUDIT

### Gap 1: IBKR option stop-sync missing CBOE rounding (FIXED)
- **Where**: `_sync_stop_to_broker_inner` → IBKR option path
- **Problem**: `new_stop_price` was passed raw to `IBStopOrder` without CBOE tick rounding
- **Risk**: IB gateway rejects off-tick stop prices for options
- **Fix**: Added `_round_to_cboe_increment(new_stop_price, is_sell=True, is_stop_trigger=True)` before building StopOrder

### Gap 2: TastyTrade option stop-sync missing CBOE rounding (FIXED)
- **Where**: `_sync_stop_to_broker_inner` → TastyTrade option path
- **Problem**: `new_stop_price` passed directly to `place_option_order` without CBOE snap
- **Risk**: Exchange rejects off-tick limit prices
- **Fix**: Added `_round_to_cboe_increment(new_stop_price, is_sell=True)` before calling place_option_order

### Previously Fixed (prior audit)
- Schwab OCC symbol building for option stops (was passing raw ticker)
- Alpaca position_intent missing on option exit orders (uncovered-option errors)
- Alpaca index option rejection (SPX/NDX/VIX not supported)
- IBKR initial bracket missing explicit tif='GTC' (defaulted to DAY)
- IBKR initial bracket CBOE rounding with stop_trigger semantics
- TastyTrade initial bracket CBOE rounding
- TastyTrade dead stop_price parameter
- T212 LIVE stop/limit order support enabled
- 6 broken base_broker imports

---

## DESIGN NOTES

### Why TastyTrade option SL uses LIMIT instead of STOP
TastyTrade's API does not support `stop_trigger` on option legs. The `OrderType.STOP` with `stop_trigger` only works for equity legs. For options, we place a SELL LIMIT at the stop-loss price. This means the order fills immediately if the option is already at or below the SL price. The TIF is DAY (not GTC) because TastyTrade does not support GTC for option orders.

### Why Webull/Robinhood option SL is monitored locally
Neither Webull nor Robinhood support stop orders for options via their APIs. The risk engine monitors the position price locally and triggers a market/aggressive-limit exit when the SL threshold is breached. This is a software stop, not a broker-side stop.

### Why Alpaca uses DAY TIF for option orders
Alpaca's API does not support GTC for option orders. Option stops placed with DAY TIF expire at market close and must be re-placed daily. The risk engine re-places them on the next cycle.

### Why Schwab forces NORMAL session for STOP orders
Schwab's API does not support STOP orders in SEAMLESS session mode. The broker module detects SEAMLESS and forces NORMAL with a log message. This only affects the session parameter, not the order itself.
