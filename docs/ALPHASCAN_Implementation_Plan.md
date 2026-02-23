# ALPHASCAN — Trading Scanner & Algo Engine Implementation Plan

**Project:** BotifyTrades
**Status:** Planned (Not Yet Implemented)
**Date:** February 23, 2026
**Version:** 1.0

---

## 1. Overview

ALPHASCAN is a real-time stock scanning and algorithmic analysis dashboard to be integrated into BotifyTrades. It will provide:

- **Scanner:** Real-time market scanning for Top Gappers (>4%), Top Losers (<-4%), Penny Stocks (<$5), and Relative Volume leaders
- **Watchlist:** Live-updating watchlist with price, volume, and catalyst tracking
- **Chart + Algo:** Interactive candlestick charts with technical indicator overlays and a built-in scalping algorithm that generates BUY/SELL signals
- **Backtesting:** Multi-strategy backtesting engine with equity curve visualization

A React JSX prototype exists at `attached_assets/trading_scanner_dashboard_1771745266540.jsx` and will be converted to vanilla HTML/CSS/JS (Flask templates) to match the existing BotifyTrades UI.

---

## 2. Architecture

### 2.1 Three-Tier Data Strategy

```
TIER 1: UNIVERSE SCANNER (External Market Data Provider)
│
│   Scans 200+ stocks every 3-5 seconds
│   Sources: Finnhub (free tier) + yfinance (Phase 1)
│            Polygon.io or Alpaca paid data (Phase 3)
│
▼
TIER 2: ENRICHMENT LAYER (Connected Broker Streams)
│
│   When user clicks a stock or adds to watchlist:
│   • Webull MQTT stream → real-time ticks
│   • Schwab WebSocket stream → real-time ticks
│   • Alpaca REST/WebSocket → real-time ticks
│   Used ONLY for selected/watched symbols (not bulk scanning)
│
▼
TIER 3: ALGO + CHART ENGINE (User-Selected Symbols Only)
│
│   Runs on the ONE symbol user clicked:
│   • Fetch 200 x 1-min candles from broker API
│   • Subscribe to live tick stream
│   • Run indicator pipeline (EMA, RSI, VWAP, BB)
│   • Generate BUY/SELL signals with strength %
│   • Connects to existing Quick Trade for order execution
```

### 2.2 Component Isolation

```
┌──────────────────────────────────────────────────────────────┐
│                     BotifyTrades Process                      │
│                                                              │
│  ┌────────────────────┐    ┌────────────────────┐           │
│  │  EXISTING ENGINE   │    │  NEW: SCANNER      │           │
│  │  (unchanged)       │    │  SERVICE            │           │
│  │                    │    │                    │           │
│  │  • Discord Bot     │    │  • Own thread      │           │
│  │  • Telegram        │    │  • Own cache       │           │
│  │  • Order Queue     │    │  • Own rate limits │           │
│  │  • Risk Engine     │    │  • NO access to    │           │
│  │  • Broker Sync     │    │    order queue     │           │
│  │  • Webull Stream   │    │  • NO access to    │           │
│  │  • Schwab Stream   │    │    risk engine     │           │
│  │  • Position Hub    │    │  • READ-ONLY       │           │
│  │                    │    │    broker status   │           │
│  └────────────────────┘    └────────────────────┘           │
│           │                         │                        │
│           ▼                         ▼                        │
│  ┌──────────────────────────────────────────────┐           │
│  │              FLASK WEB SERVER                 │           │
│  │                                              │           │
│  │  Existing:             New:                   │           │
│  │  /api/trades/*         /api/scanner/*         │           │
│  │  /api/streaming/*      /api/scanner/chart/*   │           │
│  │  /api/settings/*       /api/scanner/algo/*    │           │
│  │                                              │           │
│  │  templates/            templates/             │           │
│  │  trades.html           scanner.html (new)     │           │
│  │  index.html                                   │           │
│  └──────────────────────────────────────────────┘           │
└──────────────────────────────────────────────────────────────┘
```

### 2.3 Data Flow

```
                    ┌─────────────────────────┐
                    │   MARKET DATA PROVIDER   │
                    │  (Finnhub / yfinance /   │
                    │   Polygon / Alpaca)      │
                    └────────────┬────────────┘
                                 │
                    Every 3-5 seconds (REST)
                    or real-time (WebSocket)
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │    SCANNER SERVICE       │
                    │   (Python, own thread)   │
                    │                         │
                    │  • Fetches bulk quotes   │
                    │  • Calculates:           │
                    │    - Gap % from prev     │
                    │      close               │
                    │    - Relative Volume     │
                    │    - Float category      │
                    │    - Grade (A+ to C)     │
                    │  • Sorts into buckets:   │
                    │    - Gappers (>4%)       │
                    │    - Losers (<-4%)       │
                    │    - Penny (<$5)         │
                    │    - RVOL leaders        │
                    │  • Caches in memory      │
                    │    (TTL: 5 seconds)      │
                    └────────────┬────────────┘
                                 │
            ┌────────────────────┼────────────────────┐
            ▼                    ▼                    ▼
   ┌────────────────┐  ┌────────────────┐  ┌────────────────┐
   │ /api/scanner/  │  │ /api/scanner/  │  │ /api/scanner/  │
   │   gappers      │  │   chart/{sym}  │  │   algo/{sym}   │
   │                │  │                │  │                │
   │ Returns top 20 │  │ Returns 200    │  │ Returns algo   │
   │ sorted stocks  │  │ 1-min candles  │  │ signals +      │
   │ with metadata  │  │ + indicators   │  │ backtest data  │
   └───────┬────────┘  └───────┬────────┘  └───────┬────────┘
           │                   │                    │
           └───────────────────┼────────────────────┘
                               │
                               ▼
                    ┌─────────────────────────┐
                    │     FLASK FRONTEND      │
                    │   (scanner.html page)   │
                    │                         │
                    │  Polls every 3-5 sec    │
                    │  for scanner data       │
                    │                         │
                    │  On symbol click:       │
                    │  • Fetches chart data   │
                    │  • Fetches algo signals │
                    │  • Shows BUY/SELL panel │
                    │  • Links to Quick Trade │
                    └─────────────────────────┘
```

---

## 3. Broker API Capabilities for Chart + Algo

The chart and algo engine requires data for only ONE symbol at a time. All connected brokers can handle this with zero additional cost.

| Broker | 1-Min Candles | Live Streaming | API Call | Free? |
|--------|--------------|----------------|----------|-------|
| **Webull** | `get_bars("NVDA", "m1")` | MQTT (already running) | 1 REST call | Yes |
| **Schwab** | `/pricehistory?periodType=day` | WebSocket (already running) | 1 REST call | Yes |
| **Alpaca** | `client.get_bars("NVDA", "1Min")` | WebSocket available | 1 REST call | Yes |
| **IBKR** | `reqHistoricalData()` | TWS streaming | 1 TWS call | Yes |
| **Robinhood** | Daily/weekly charts only | No real-time stream | REST polling | Yes |
| **Tastytrade** | Daily charts only | No real-time stream | REST polling | Yes |

### Chart + Algo Data Flow (Per Symbol)

```
User clicks "NVDA" in scanner
        │
        ▼
┌─────────────────────────────────────────┐
│ STEP 1: Select best data source         │
│                                         │
│  Priority order:                        │
│  1. Webull (best candle API)            │
│  2. Schwab (good candle API)            │
│  3. Alpaca (good candle API)            │
│  4. IBKR (if TWS running)              │
│  5. yfinance fallback (FREE, no broker) │
└──────────────────┬──────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────┐
│ STEP 2: Fetch 200 x 1-min candles      │
│                                         │
│  ONE API call to the broker             │
│  Fields: Open, High, Low, Close, Volume │
│  Well within any broker's rate limit    │
└──────────────────┬──────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────┐
│ STEP 3: Subscribe to live ticks         │
│                                         │
│  Add symbol to existing stream:         │
│  • Webull MQTT: subscribe(["NVDA"])     │
│  • Schwab WS: ADD command for NVDA     │
│  Costs ZERO extra API calls — streams   │
│  are already running                    │
└──────────────────┬──────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────┐
│ STEP 4: Run algo pipeline (Python)      │
│                                         │
│  Calculate:                             │
│  • EMA(9) + EMA(21) — trend direction   │
│  • RSI(14) — momentum                  │
│  • VWAP — volume-weighted fair value    │
│  • Bollinger Bands(20,2) — volatility   │
│  • Volume EMA(20) — volume baseline    │
│                                         │
│  Generate signals:                      │
│  • EMA crossover + RSI + VWAP → BUY    │
│  • BB squeeze + trend → BUY/SELL       │
│  • Volume surge confirmation            │
│                                         │
│  Output: "BUY 82%" or "SELL 71%"        │
│  Execution time: <5ms per calculation   │
└──────────────────┬──────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────┐
│ STEP 5: Frontend renders                │
│                                         │
│  • SVG candlestick chart                │
│  • Indicator overlays (EMA, VWAP, BB)   │
│  • Signal arrows with strength %        │
│  • RSI sub-chart                        │
│  • BUY/SELL buttons → Quick Trade       │
│  • Updates every 2 seconds              │
└─────────────────────────────────────────┘
```

---

## 4. Scanner Data Sources — Comparison

### For Full Market Scanning (200+ symbols)

| Provider | Cost | Update Speed | WebSocket | Pre-Market | Best For |
|----------|------|-------------|-----------|------------|----------|
| **yfinance** | FREE | 5-10 sec | No (REST) | Yes | Phase 1 prototype |
| **Finnhub** (free) | FREE | 60 req/min | Yes | Yes | Phase 1 supplement |
| **Alpaca Data** (paid) | $9/mo | Real-time | Yes | Yes | Phase 3 upgrade |
| **Polygon.io** | $29-199/mo | Real-time | Yes | Yes | Phase 3 premium |
| **Finnhub** (premium) | $49/mo | Real-time | Yes | Yes | Phase 3 alternative |

### Broker APIs for Scanning — Why NOT Suitable

| Broker | Can Scan Full Market? | Max Symbols in Stream | Rate Limit |
|--------|----------------------|----------------------|------------|
| Webull | No | ~200 | Varies |
| Schwab | No | ~100 | 120 req/min |
| Alpaca | No | ~200 | 200 req/min (free) |
| IBKR | Yes (scanner API) | ~100 | Pacing rules |
| Robinhood | No | N/A | ~5 req/sec |
| Tastytrade | No | N/A | ~60 req/min |

**Key Insight:** Broker streams are designed for tracking positions you own (10-50 symbols), not scanning 8,000+ stocks. Use an external data provider for scanning, and broker APIs for chart + algo on individual symbols.

---

## 5. Subscription Requirements Summary

| Component | Needs Paid Subscription? | Data Source | Cost |
|-----------|------------------------|-------------|------|
| **Scanner** (Phase 1) | No | Finnhub free + yfinance | $0/mo |
| **Scanner** (Phase 3) | Yes | Polygon or Alpaca paid | $9-29/mo |
| **Chart** (any phase) | No | Connected broker API | $0/mo |
| **Algo signals** | No | Calculated from chart candles | $0/mo |
| **Live tick updates** | No | Existing Webull MQTT / Schwab WS | $0/mo |
| **Backtesting** | No | Historical candles (broker/yfinance) | $0/mo |

---

## 6. Scanner Features

### 6.1 Scan Categories

| Category | Filter Logic | Sort By | Key Columns |
|----------|-------------|---------|-------------|
| **Top Gappers** | chgPct > 4% | chgPct DESC | Symbol, Price, Chg%, Volume, RVOL, Catalyst |
| **Top Losers** | chgPct < -4% | chgPct ASC | Symbol, Price, Chg%, Volume, RVOL, Catalyst |
| **Penny Stocks** | price < $5 | RVOL DESC | Symbol, Price, Float, Volume, RVOL, Grade |
| **RVOL Leaders** | rvol > 3x | RVOL DESC | Symbol, Price, RVOL, Volume, ATR, Grade |

### 6.2 Stock Metrics Calculated

| Metric | Formula | Data Source |
|--------|---------|-------------|
| **Gap %** | (current_price - prev_close) / prev_close * 100 | Market data provider |
| **Relative Volume** | current_volume / 20-day avg volume | Historical + live volume |
| **Float** | Outstanding shares - restricted shares | yfinance / provider |
| **ATR** | 14-period Average True Range | Calculated from candles |
| **Grade** | Composite of RVOL, float, catalyst, volume | Proprietary scoring |
| **Short Squeeze %** | Short interest / float * 100 | yfinance / provider |

### 6.3 Scalping Algorithm — Signal Logic

```
BUY SIGNAL (Strong):
  EMA(9) crosses ABOVE EMA(21)         — Trend confirmation
  AND RSI(14) between 40-65            — Not overbought
  AND Price ABOVE VWAP                  — Buying pressure
  AND Volume > 1.3x Volume EMA(20)     — Volume confirmation
  → Strength: 75-95%

BUY SIGNAL (Moderate):
  Bollinger Band squeeze detected       — Volatility compression
  AND EMA(9) > EMA(21) (uptrend)       — Trend alignment
  AND RSI(14) between 40-65            — Not overbought
  → Strength: 60-80%

SELL SIGNAL (Strong):
  EMA(9) crosses BELOW EMA(21)         — Trend reversal
  AND RSI(14) between 55-80            — Not oversold
  AND Price BELOW VWAP                  — Selling pressure
  AND Volume > 1.3x Volume EMA(20)     — Volume confirmation
  → Strength: 70-90%

SELL SIGNAL (Moderate):
  Bollinger Band squeeze detected       — Volatility compression
  AND EMA(9) < EMA(21) (downtrend)     — Trend alignment
  AND RSI(14) between 55-80            — Not oversold
  → Strength: 55-75%
```

---

## 7. Challenges & Mitigations

| Challenge | Risk Level | Mitigation |
|-----------|-----------|------------|
| Free data sources unreliable during market hours | Medium | Fallback chain: Finnhub → yfinance → broker REST |
| Rate limits on scanning 200+ symbols | Medium | Bulk snapshot endpoints (1 call = many symbols) |
| Relative Volume needs 20-day baseline | Low | Pre-compute daily, cache in SQLite |
| Scanner interfering with order execution | High | Complete isolation: own thread, own cache, no shared broker calls |
| Memory/CPU on Replit for indicators | Medium | Limit to top 200 symbols for scanning, algo on 1 symbol only |
| React prototype needs conversion | Low | Convert to vanilla JS + Flask templates (consistent with existing UI) |
| Market hours handling | Low | Show market state indicator, adjust scan frequency by session |
| Pre-market data availability | Medium | Limited sources for pre-market; Finnhub and Webull support it |

---

## 8. Implementation Phases

### Phase 1: Foundation (FREE — No Subscription)

**Scope:**
- Scanner service with Finnhub (free tier) + yfinance as data sources
- New `scanner.html` Flask template (converted from React prototype)
- Scan top 200 most-traded US stocks
- Update every 5-10 seconds
- Gappers / Losers / Penny / RVOL tabs
- Watchlist with add/remove
- Expert screening criteria panel

**New Files:**
- `src/services/scanner_service.py` — Scanner worker thread + cache
- `gui_app/templates/scanner.html` — Frontend page
- `gui_app/scanner_routes.py` — API endpoints

**API Endpoints:**
- `GET /api/scanner/stocks?type=gappers` — Returns top 20 for category
- `GET /api/scanner/watchlist` — Returns watchlist stocks
- `POST /api/scanner/watchlist` — Add/remove from watchlist

### Phase 2: Chart + Algo (FREE — Uses Broker APIs)

**Scope:**
- Candlestick chart rendered with SVG (server provides data, client renders)
- Indicator pipeline: EMA(9), EMA(21), RSI(14), VWAP, Bollinger Bands
- Scalping algo with BUY/SELL signals and strength percentage
- Uses broker API for 1-min candles (Webull → Schwab → Alpaca → yfinance fallback)
- Real-time tick updates via existing broker WebSocket/MQTT streams
- BUY/SELL buttons connected to existing Quick Trade system
- Multi-strategy backtesting with equity curve

**New Files:**
- `src/services/algo_engine.py` — Indicator calculations + signal generation
- `src/services/chart_data_service.py` — Candle fetching from brokers

**API Endpoints:**
- `GET /api/scanner/chart/{symbol}?timeframe=1m&bars=200` — Candle data
- `GET /api/scanner/algo/{symbol}` — Algo signals + indicators
- `GET /api/scanner/backtest/{symbol}?strategy=EMA_VWAP_RSI` — Backtest results

### Phase 3: Real-Time Upgrade ($9-29/mo Subscription)

**Scope:**
- Integrate Polygon.io or Alpaca paid market data
- WebSocket streaming for scanner (sub-second updates)
- Pre-market scanning (4:00 AM - 9:30 AM ET)
- Level 2 data integration (if broker supports)
- Expanded symbol universe (500+ stocks)

### Phase 4: Advanced Features (Future)

**Scope:**
- AI-powered stock grading (using existing OpenAI integration)
- Auto-watchlist (scanner feeds stocks to signal detection)
- Options flow integration
- Multi-timeframe analysis (1m, 5m, 15m, 1h)
- Custom scan criteria builder
- Scanner alerts (Discord/browser notifications)

---

## 9. Technical Specifications

### Scanner Service Thread Architecture

```python
class ScannerService:
    """Runs in its own thread, completely isolated from trading engine"""

    def __init__(self):
        self.cache = {}           # In-memory cache with TTL
        self.watchlist = []       # User's watchlist symbols
        self.vol_baselines = {}   # 20-day avg volume per symbol
        self.lock = threading.Lock()  # Thread safety

    def scan_loop(self):
        """Main loop: fetch quotes → calculate metrics → cache results"""
        while self.running:
            quotes = self.fetch_bulk_quotes()   # Finnhub/yfinance
            results = self.calculate_metrics(quotes)
            with self.lock:
                self.cache = results
            time.sleep(5)  # 5-second scan interval

    def get_gappers(self):     # Filter: chgPct > 4%, sort DESC
    def get_losers(self):      # Filter: chgPct < -4%, sort ASC
    def get_penny(self):       # Filter: price < $5, sort by RVOL
    def get_rvol_leaders(self): # Filter: rvol > 3x, sort DESC
```

### Algo Engine Specification

```python
class AlgoEngine:
    """Runs indicator pipeline on candle data for a single symbol"""

    def calculate(self, candles: list[dict]) -> dict:
        closes = [c['close'] for c in candles]
        volumes = [c['volume'] for c in candles]

        return {
            'ema9': self.ema(closes, 9),
            'ema21': self.ema(closes, 21),
            'rsi': self.rsi(closes, 14),
            'vwap': self.vwap(candles),
            'bb': self.bollinger_bands(closes, 20, 2),
            'vol_ema': self.ema(volumes, 20),
            'signals': self.generate_signals(...)  # BUY/SELL + strength
        }

    # Execution: <5ms per symbol on 200 candles
    # Memory: ~2KB per symbol
```

### Frontend Rendering

- SVG-based candlestick chart (no external charting library needed)
- SVG-based RSI sub-chart
- SVG-based equity curve for backtesting
- Mini sparkline charts for watchlist cards
- All rendering done client-side from JSON data served by Flask API
- Polling interval: 3-5 seconds for scanner, 2 seconds for chart updates

---

## 10. Reference: Prototype File

The original React JSX prototype is located at:
`attached_assets/trading_scanner_dashboard_1771745266540.jsx`

This contains the complete UI design, mock data generators, and algo logic that will be converted to vanilla JavaScript for the Flask template implementation.

Key components to convert:
- `MiniChart` → SVG sparkline (vanilla JS)
- `CandleChart` → SVG candlestick chart (vanilla JS)
- `EquityCurve` → SVG equity curve (vanilla JS)
- `App` → scanner.html template with JavaScript
- `runScalpAlgo()` → Python `AlgoEngine` class (server-side)
- `runBacktest()` → Python backtesting function (server-side)

---

*This document will be updated as implementation progresses through each phase.*
