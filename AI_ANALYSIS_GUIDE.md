# AI-Powered Trade Analysis - User Guide

## Overview

Your Discord trading bot now includes **AI-powered analysis** that provides intelligent insights after each trade execution. The AI analyzes your trades using advanced language models to give you:

- 📊 **Technical Analysis**: Support/resistance levels, trends, and chart patterns
- 📈 **Options Greeks Analysis**: Delta, gamma, theta, vega, and overall risk profile
- 🎯 **Profit/Loss Predictions**: Probability-based outlook on your trades
- 📰 **Market Sentiment**: Most-discussed stocks and overall market pulse (optional)

---

## Quick Start

### 1. Enable AI Analysis

Edit `config.ini`:

```ini
[ai_analysis]
enable_ai_analysis = true
ai_model = gpt-4o-mini
```

**That's it!** The bot will now analyze every BTO (Buy To Open) trade automatically.

---

## How It Works

### After Every BTO Trade:
1. Bot executes your trade on Webull
2. AI immediately analyzes the trade
3. Console displays comprehensive analysis including:
   - Technical indicators (support/resistance, patterns)
   - Options Greeks (for options trades)
   - Profit probability
   - Risk assessment
   - Recommended stop-loss levels

### Example Output:

```
🤖 AI TRADE ANALYSIS - TSLA
======================================================================
Trade: BTO 2 TSLA $250C 12/20 @$5.50
Model: gpt-4o-mini
Time: 2025-11-12T14:30:00
----------------------------------------------------------------------
**Technical Analysis:**
- Current trend: Bullish (uptrend since Nov 1)
- Key support: $245, $240
- Key resistance: $255, $260
- Pattern: Ascending triangle forming

**Options Greeks Assessment:**
- Delta: ~0.65 (moderate directional exposure)
- Theta: -$15/day (time decay accelerates after 30 DTE)
- IV: Elevated at 45% (earnings in 2 weeks)
- Risk: Moderate - theta decay manageable with 38 days to expiry

**Probability Analysis:**
- Breakeven: $255.50 (2% above current price)
- Profit probability: 55-60% based on current momentum
- Time to target: 5-10 trading days recommended

**Risk/Reward:**
- Max loss: $1,100 (if held to expiration worthless)
- Target 1: $7.50 (+36% at $260)
- Target 2: $10.00 (+82% at $270)
- Recommended stop: Exit if stock drops below $245

**Key Risks:**
- Earnings volatility crush (Nov 20)
- Theta decay accelerates in final 2 weeks
- Macro headwinds from Fed meeting (Nov 15)
======================================================================
```

---

## Configuration Options

### AI Models

Choose your AI model based on quality vs. cost:

```ini
ai_model = gpt-4o-mini       # Fast, cost-effective (recommended)
ai_model = gpt-4o            # More detailed analysis
ai_model = gpt-5-mini        # Latest, balanced
ai_model = gpt-5             # Most advanced (highest cost)
```

**Recommendation**: Start with `gpt-4o-mini` - it provides excellent analysis at low cost.

### Market Sentiment Analysis (Optional)

Track overall market pulse and most-discussed stocks:

```ini
enable_sentiment_analysis = true
sentiment_interval = 600      # Analyze every 10 minutes
```

**Example Sentiment Output:**
```
📊 MARKET SENTIMENT ANALYSIS
======================================================================
Messages Analyzed: 47
Time: 2025-11-12T14:45:00
----------------------------------------------------------------------
**Most Discussed Stocks:**
1. TSLA - 12 mentions (bullish sentiment)
2. NVDA - 8 mentions (mixed sentiment)
3. SPY - 6 mentions (neutral to bearish)
4. AAPL - 4 mentions (bullish)
5. META - 3 mentions (bullish)

**Overall Sentiment:** 65% Bullish
- Strong momentum in tech sector
- Options activity heavily weighted toward calls
- Multiple traders scaling into positions

**Market Pulse:**
- Key themes: Tech breakout, AI stocks rallying
- Common strategies: Call spreads, momentum plays
- Risk-on environment with low VIX

**Notable Patterns:**
- Several traders taking TSLA 250C for Dec expiry
- Repeated mentions of support at SPY 455
- Bullish conviction on NVDA earnings

**Contrarian Indicators:** None detected
======================================================================
```

---

## Cost Information

### Replit AI Integrations Pricing

This feature uses Replit AI Integrations (billed to your Replit credits):

**Per 1,000 tokens:**
- **Input tokens**: $3 (reading data)
- **Output tokens**: $15 (AI writing analysis)

**Typical trade analysis:**
- Input: ~500 tokens ($1.50)
- Output: ~600 tokens ($9.00)
- **Total per trade: ~$10-12**

**Monthly estimates:**
- 10 trades/day: ~$3,000-$3,600/month
- 5 trades/day: ~$1,500-$1,800/month
- 2 trades/day: ~$600-$720/month

**Sentiment analysis:**
- ~$5-10 per analysis
- Every 10 min = ~$720-1,440/day

**Replit Credits:**
- Core subscribers: $25/month included
- Teams subscribers: $40/user/month included
- Additional usage billed after credits exhausted

---

## Running on Local Machine

**Important**: Replit AI Integrations only work when running on Replit, not on your local Windows machine.

**Options for Local Use:**

### Option 1: Use Your Own OpenAI API Key
1. Sign up at https://platform.openai.com/
2. Get your API key
3. Set environment variable:
   ```cmd
   set OPENAI_API_KEY=your-key-here
   ```
4. Modify `src/ai_analyzer.py` to use your key instead of Replit's

### Option 2: Disable AI Analysis Locally
In `config.ini`:
```ini
enable_ai_analysis = false
```

### Option 3: Run Bot on Replit 24/7
- Keep bot running on Replit
- AI analysis works automatically
- Monitor via console logs

---

## Best Practices

### 1. Review Analysis Before Adjusting Trades
- AI provides insights, not financial advice
- Use analysis to inform your decisions
- Always do your own due diligence

### 2. Monitor Costs
- Start with sentiment analysis disabled
- Enable sentiment only if you find it valuable
- Use `gpt-4o-mini` for cost efficiency

### 3. Save Important Analysis
- Console output includes all trade analysis
- Review logs to track AI recommendations vs. actual outcomes
- Improve your trading based on patterns

### 4. Understand Limitations
- AI analyzes based on general market knowledge
- Cannot access real-time stock prices or charts
- Cannot see your specific risk tolerance
- Provides probabilistic guidance, not guarantees

---

## Troubleshooting

### "AI analysis failed"
- Check that you're running on Replit (not local machine)
- Verify Replit AI Integrations is set up
- Check your credit balance

### "AI analyzer not available"
- OpenAI package not installed
- Run: `pip install -r requirements.txt`

### Analysis seems generic
- Try upgrading to `gpt-4o` or `gpt-5-mini`
- More advanced models provide deeper insights

### High costs
- Switch to `gpt-4o-mini`
- Disable sentiment analysis
- Only analyze critical trades

---

## Example Workflows

### Conservative Trader:
```ini
enable_ai_analysis = true
ai_model = gpt-4o-mini
enable_sentiment_analysis = false
```
- Get trade analysis only
- Minimize costs
- Focus on position management

### Active Day Trader:
```ini
enable_ai_analysis = true
ai_model = gpt-4o
enable_sentiment_analysis = true
sentiment_interval = 300      # Every 5 minutes
```
- Full analysis on every trade
- Real-time market pulse
- Maximum insights

### Paper Trading / Testing:
```ini
enable_ai_analysis = true
ai_model = gpt-5
enable_sentiment_analysis = true
```
- Test with best AI model
- Learn from detailed analysis
- Evaluate before live trading

---

## Security & Privacy

- AI analysis happens on Replit's servers
- Your trades are sent to OpenAI for analysis
- No trade data is stored long-term
- Replit AI Integrations handles authentication automatically
- No API keys needed (when running on Replit)

---

## Support

This AI feature integrates with your existing bot. All standard bot features continue to work:
- Risk management (profit targets, stop losses)
- Position monitoring
- Auto-quantity calculation

AI analysis is an **add-on** that enhances your trading decisions.

---

## Disclaimer

AI-generated analysis is for informational purposes only and does not constitute financial advice. Trading involves substantial risk of loss. Past performance does not guarantee future results. Always conduct your own research and consult with qualified financial professionals before making trading decisions.
