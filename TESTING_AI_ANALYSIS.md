# Testing AI Analysis Feature

## Quick Test Guide

### 1. Send a Test BTO Signal in Discord

In one of your monitored channels, send:

```
BTO TSLA $250c 12/20 @5.50
```

or

```
BTO 100 AAPL @150
```

### 2. Watch Console Output

You should see:

1. **Trade execution** (normal bot output)
2. **AI analysis header** with timestamp
3. **Comprehensive analysis** including:
   - Technical indicators
   - Options Greeks (for options)
   - Profit probability
   - Risk assessment
   - Recommended actions

### 3. Example Expected Output

```
🤖 AI TRADE ANALYSIS - TSLA
======================================================================
Trade: BTO 2 TSLA $250C 12/20 @$5.50
Model: gpt-4o-mini
Time: 2025-11-12T14:30:00
----------------------------------------------------------------------
**Technical Analysis:**
- Current trend: Bullish momentum building since Nov 1
- Key support levels: $245, $240, $235
- Key resistance: $255 (near-term), $260 (major)
- Chart pattern: Ascending triangle forming
- Volume: Above average, confirming strength

**Options Greeks Assessment:**
- Delta: ~0.65 (moderately in-the-money positioning)
- Theta: -$15/day (time decay moderate at 38 DTE)
- Vega: High sensitivity to volatility (IV at 45%)
- Gamma: Moderate acceleration potential
- Overall Greeks profile: Balanced directional play

**Probability Analysis:**
- Breakeven: $255.50 (current: $250)
- Profit probability: 55-60% based on momentum
- Target 1 ($260): 40-45% probability
- Target 2 ($270): 25-30% probability
- Time to target: 5-10 trading days optimal

**Risk/Reward Assessment:**
- Max loss: $1,100 (if held to worthless)
- Reward at $260: $700 (+64%)
- Reward at $270: $1,900 (+173%)
- Risk/reward ratio: 1:1.7 (favorable)

**Key Risks & Considerations:**
1. Earnings announcement Nov 20 (IV crush risk)
2. Theta decay accelerates after 30 DTE
3. Macro event: Fed meeting Nov 15
4. Recommend exit before earnings or take partial profits

**Recommended Actions:**
- Set stop at stock price $245
- Consider taking 50% profits at $260
- Exit remaining before earnings (Nov 20)
- Monitor daily for momentum shifts
======================================================================
```

### 4. Verify BTO-Only Behavior

Send an STC signal:

```
STC TSLA $250c 12/20 @6.50
```

**Expected**: Trade executes normally but NO AI analysis appears (BTO-only feature).

### 5. Test Sentiment Analysis (Optional)

If you enabled `enable_sentiment_analysis = true` in config.ini:

1. Wait for the interval (default 10 minutes)
2. Console will show periodic sentiment reports
3. Shows most-discussed stocks from all channel messages

## Troubleshooting

### "AI analysis skipped" Error

**Possible causes:**
1. Running on local machine without OPENAI_API_KEY
2. Replit AI Integrations not enabled
3. Network connectivity issue

**Solutions:**
1. On Replit: Verify OpenAI integration is set up
2. On local: Set environment variable:
   ```cmd
   set OPENAI_API_KEY=sk-your-key-here
   ```
3. Check console for detailed error message

### No Analysis Appears

1. **Check config.ini**: Is `enable_ai_analysis = true`?
2. **Check action**: AI only analyzes BTO trades, not STC
3. **Check logs**: Look for "[AI] Analysis skipped" messages
4. **Verify API key**: Make sure integration is properly set up

### Analysis is Generic/Low Quality

1. **Upgrade model**: Change `ai_model` in config.ini:
   - `gpt-4o-mini` → `gpt-4o` (better analysis)
   - `gpt-4o` → `gpt-5-mini` (even better)
2. **Note**: Better models cost more credits

## Performance Expectations

### Analysis Timing
- **Non-blocking**: Trade executes immediately
- **AI analysis**: Appears 2-5 seconds after trade
- **No impact**: Discord monitoring continues normally

### Cost Estimates (Replit AI)
- **Per trade analysis**: ~$10-12 in credits
- **10 trades/day**: ~$3,000-3,600/month
- **5 trades/day**: ~$1,500-1,800/month
- **Sentiment poll**: ~$5-10 per analysis

## What to Look For

### Good AI Analysis Signs
✓ Specific support/resistance levels
✓ Mentions recent price action
✓ Greeks values provided (options)
✓ Probability percentages given
✓ Clear risk warnings
✓ Actionable recommendations

### Poor AI Analysis Signs
✗ Generic statements without specifics
✗ No numerical values
✗ Contradictory recommendations
✗ Missing Greeks assessment (options)
✗ No probability estimates

## Feedback Loop

As you test:
1. **Save interesting analyses** - Review them later
2. **Compare predictions to outcomes** - Did the AI's probabilities match reality?
3. **Note useful insights** - What helped your decision-making?
4. **Identify gaps** - What's missing from the analysis?

## Live Trading Considerations

Before enabling with real money:

1. **Test with paper trading first**
   - Set `paper_trade = true` in config.ini
   - Verify AI analysis quality
   - Ensure no bugs or errors

2. **Review several analyses**
   - Do they make sense?
   - Are probabilities realistic?
   - Are risks properly identified?

3. **Understand limitations**
   - AI doesn't see real-time charts
   - Cannot access your account details
   - Provides guidance, not guarantees

4. **Use as one input**
   - Combine with your own research
   - Don't blindly follow AI recommendations
   - Consider your risk tolerance

## Advanced Testing

### Test Different Asset Types

```
BTO SPY $450c 11/22 @2.50          # Standard option
BTO 50 AAPL @150                   # Stock trade
BTO QQQ $380p 12/15 @5.00          # Put option
BTO NVDA $500c 01/17/2026 @50      # LEAP option
```

### Test Auto-Quantity

```
BTO MSFT @350                      # Should calculate qty from max_position_size
```

### Monitor Performance

Watch for:
- Response time (should be 2-5 seconds)
- Analysis quality across different stocks
- Consistency of recommendations
- Accuracy of probability estimates

## Need Help?

If you encounter issues:
1. Check console logs for error messages
2. Verify config.ini settings
3. Ensure Replit AI Integrations is enabled
4. Review AI_ANALYSIS_GUIDE.md for detailed info

## Success Criteria

You'll know it's working when:
✓ Bot executes trades normally
✓ AI analysis appears 2-5 seconds after BTO trades
✓ Analysis is detailed with specific levels/probabilities
✓ No errors in console
✓ Discord monitoring continues uninterrupted
✓ STC trades don't trigger analysis (BTO-only)
