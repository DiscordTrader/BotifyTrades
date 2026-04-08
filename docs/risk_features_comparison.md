# Risk Features Comparison: Early Trailing vs Dynamic SL vs Dynamic SL + Escalation Only

---

## Quick Summary

| Feature | What It Does | When SL Moves | Sells Shares? | Best For |
|---------|-------------|---------------|---------------|----------|
| **Early Trailing** | Locks breakeven, then ratchets up in fixed steps | Every X% gain above activation | No (full exit only when stop hit) | Protecting gains with a rising floor |
| **Dynamic SL** | Moves SL to fixed % above entry when PTs hit | Only when a Profit Target tier is hit | Yes (partial sells at each PT) | Taking profits in chunks + SL protection |
| **Dynamic SL + Escalation Only** | Same SL escalation, but NO partial sells | Only when PT thresholds are crossed | No (SL moves up, but no trimming) | Riding winners with rising SL floor |

---

## Feature 1: Early Trailing

### How It Works
Early Trailing is a **percentage-based trailing stop** that activates early and locks in profit in fixed steps.

**Two Settings:**
- **Activation %** (default 5%) — the gain needed before the trail turns on
- **Step %** (default 3%) — how often the stop ratchets up

### Lifecycle

1. **Before Activation**: Normal SL applies. Early trail is dormant.
2. **Activation**: When P&L reaches the Activation %, the stop moves to **breakeven** (entry price).
3. **Step Locking**: For every additional Step % gained, the stop ratchets up by that step amount.
4. **Exit**: If price drops to or below the current early stop price → **full exit**.

### Example: UCAR Entry at $1.00, Activation 10%, Step 5%

| Price | P&L | What Happens | Stop Price |
|-------|-----|-------------|------------|
| $1.00 | 0% | Trade opened. Early trail dormant. | Original SL (e.g. $0.90) |
| $1.05 | +5% | Still below 10% activation. No change. | $0.90 |
| $1.10 | +10% | **Activated!** Stop moves to breakeven. | **$1.00** (breakeven) |
| $1.15 | +15% | +5% above activation → Step 1 locked. | **$1.05** (+5%) |
| $1.20 | +20% | +10% above activation → Step 2 locked. | **$1.10** (+10%) |
| $1.25 | +25% | +15% above activation → Step 3 locked. | **$1.15** (+15%) |
| $1.18 | +18% | Price dipped but still above $1.15 stop. **Holds.** | $1.15 (unchanged) |
| $1.30 | +30% | +20% above activation → Step 4 locked. | **$1.20** (+20%) |
| $1.19 | +19% | Price drops below $1.20 stop → **FULL EXIT** | Exit at ~$1.20 |

**Result**: Entered at $1.00, exited at ~$1.20. Locked in +20% profit even though price peaked at $1.30.

### Key Characteristics
- Stop **only moves up**, never down (ratchet)
- No partial sells — it's all-or-nothing when the stop is hit
- Mutually exclusive with Legacy Trailing Stop (can't use both)
- Steps are **evenly spaced** based on the Step % setting

---

## Feature 2: Dynamic SL (with Normal Profit Targets)

### How It Works
Dynamic SL moves the stop loss **upward** each time a Profit Target tier is hit. Meanwhile, **partial sells happen** at each PT tier.

**Settings:**
- **Profile**: Conservative, Standard, or Aggressive (controls where SL moves after each PT)
- **Profit Target tiers**: PT1, PT2, PT3, PT4 — each with a % threshold
- Works together with the normal tiered PT system

### SL Profiles (where SL moves after each PT hit)

| PT Hit | Conservative | Standard | Aggressive |
|--------|-------------|----------|------------|
| PT1 hit | Breakeven (0%) | Breakeven (0%) | -2% (below entry) |
| PT2 hit | +3% | +5% | Breakeven (0%) |
| PT3 hit | +8% | +10% | +8% |
| PT4 hit | +15% | +17% | +15% |

### Example: SPY Options Entry at $2.00, Standard Profile, PTs at 10/15/25/40%

| Price | P&L | What Happens | Dynamic SL | Shares Sold |
|-------|-----|-------------|------------|-------------|
| $2.00 | 0% | Trade opened. Dynamic SL off (no PTs hit yet). | Original SL | None |
| $2.10 | +5% | Below PT1 (10%). No action. | Original SL | None |
| $2.20 | +10% | **PT1 hit!** SL moves to breakeven. Partial sell. | **$2.00** (0%) | ~25% of position |
| $2.15 | +7.5% | Dipped but above $2.00 SL. Holds. | $2.00 | — |
| $2.30 | +15% | **PT2 hit!** SL escalates to +5%. Partial sell. | **$2.10** (+5%) | ~25% of position |
| $2.50 | +25% | **PT3 hit!** SL escalates to +10%. Partial sell. | **$2.20** (+10%) | ~25% of position |
| $2.80 | +40% | **PT4 hit!** SL escalates to +17%. Partial sell. | **$2.34** (+17%) | ~25% of position |
| $2.40 | +20% | Price drops but still above $2.34 SL. | $2.34 | — |
| $2.30 | +15% | Price drops below $2.34 → **FULL EXIT of remaining** | Exit at ~$2.34 | Remaining shares |

**Result**: Sold chunks at $2.20, $2.30, $2.50, $2.80, and the remainder exited at ~$2.34. Blended profit across all sells.

### Key Characteristics
- SL only moves up (ratchet) — never goes back down
- **Partial sells happen** at each PT tier
- SL is always capped below current price (2% buffer) to avoid immediate trigger
- Leave Runner % can keep a small portion for max upside
- Quantity is auto-split evenly across enabled tiers

---

## Feature 3: Dynamic SL + Escalation Only Mode

### How It Works
This is Dynamic SL **without any partial sells**. PT thresholds are used purely as SL escalation triggers. When a PT level is hit, the SL moves up, but **no shares are sold**. You keep your full position until the SL is actually hit.

Additionally, once **all configured PTs are hit**, the system switches to a **ratcheting mode** — the SL follows the price up with a fixed giveback allowance, similar to a trailing stop.

**Settings:**
- Same Dynamic SL profiles (Conservative/Standard/Aggressive)
- Same PT tiers — but they only trigger SL moves, not sells
- **Escalation Only** toggle must be ON

### Example: AAPL Entry at $200.00, Standard Profile, PTs at 8/10/15%, Escalation Only ON

| Price | P&L | What Happens | Dynamic SL | Shares Sold |
|-------|-----|-------------|------------|-------------|
| $200 | 0% | Trade opened. Full position held. | Original SL (e.g. $180) | None |
| $210 | +5% | Below PT1 (8%). No action. | $180 | **None** |
| $216 | +8% | **PT1 threshold crossed!** SL escalates to breakeven. | **$200** (0%) | **None** |
| $212 | +6% | Dipped but above $200 SL. Holds full position. | $200 | **None** |
| $220 | +10% | **PT2 threshold crossed!** SL escalates to +5%. | **$210** (+5%) | **None** |
| $230 | +15% | **PT3 threshold crossed!** SL escalates to +10%. All PTs hit! | **$220** (+10%) | **None** |
| $240 | +20% | All PTs hit → **Ratchet mode active**. SL follows price. | **$230** (+15%) | **None** |
| $250 | +25% | Ratchet keeps following. Giveback = 5% below current. | **$240** (+20%) | **None** |
| $245 | +22.5% | Dipped but still above $240 ratchet SL. | $240 | **None** |
| $238 | +19% | Price drops below $240 ratchet SL → **FULL EXIT** | Exit at ~$240 | **All shares** |

**Result**: Entered at $200, held full position the entire time, exited at ~$240 for +20% on the entire position.

### The Ratchet (Post-All-PTs) Explained
Once all configured PT tiers are hit, the system calculates a "giveback" allowance:
- **Giveback** = Highest PT threshold - Highest PT's SL% from profile
- Example: PT3 at 15%, Standard profile PT3 SL = +10% → Giveback = 5%
- So if price is at +25%, ratchet SL = 25% - 5% = +20%
- The SL keeps following the price up, always 5% behind
- Minimum giveback is 5% if the calculated value is less than 1%

### Key Characteristics
- **Zero partial sells** — you hold the entire position
- PT tiers become pure SL triggers
- After all PTs hit, acts like a trailing stop with fixed giveback
- Maximum profit potential since no early trimming
- Higher risk: if price reverses before PT1, you exit at original SL with full position

---

## Side-by-Side Comparison

### Same Trade: Entry $10.00, price runs to $14.00 (+40%) then drops

**Setup**: PT1=10%, PT2=15%, PT3=25%, Standard Dynamic SL profile, Early Trail Activation=10%, Step=5%

#### Early Trailing Path

| Event | Price | Stop | Position |
|-------|-------|------|----------|
| Entry | $10.00 | $9.00 (original -10% SL) | 100 shares |
| +10% Activation | $11.00 | **$10.00** (breakeven) | 100 shares |
| +15% Step 1 | $11.50 | **$10.50** (+5%) | 100 shares |
| +20% Step 2 | $12.00 | **$11.00** (+10%) | 100 shares |
| +25% Step 3 | $12.50 | **$11.50** (+15%) | 100 shares |
| +30% Step 4 | $13.00 | **$12.00** (+20%) | 100 shares |
| +35% Step 5 | $13.50 | **$12.50** (+25%) | 100 shares |
| +40% Step 6 | $14.00 | **$13.00** (+30%) | 100 shares |
| Price drops... | $12.90 | Hit $13.00 stop → **EXIT** | 0 shares |
| **Total P&L** | | **+30% on 100 shares = $300** | |

#### Dynamic SL (Normal PTs) Path

| Event | Price | Stop | Position |
|-------|-------|------|----------|
| Entry | $10.00 | $9.00 (original -10% SL) | 100 shares |
| PT1 +10% | $11.00 | **$10.00** (breakeven) | 75 shares (sold 25) |
| PT2 +15% | $11.50 | **$10.50** (+5%) | 50 shares (sold 25) |
| PT3 +25% | $12.50 | **$11.00** (+10%) | 25 shares (sold 25) |
| +40% peak | $14.00 | $11.00 | 25 shares |
| Price drops... | $10.90 | Hit $11.00 stop → **EXIT** | 0 shares |
| **Total P&L** | | 25@$11 + 25@$11.50 + 25@$12.50 + 25@$11 = **$150** | |

#### Dynamic SL + Escalation Only Path

| Event | Price | Stop | Position |
|-------|-------|------|----------|
| Entry | $10.00 | $9.00 (original -10% SL) | 100 shares |
| PT1 +10% | $11.00 | **$10.00** (breakeven) | **100 shares** (no sell) |
| PT2 +15% | $11.50 | **$10.50** (+5%) | **100 shares** (no sell) |
| PT3 +25% | $12.50 | **$11.00** (+10%) All PTs hit → ratchet | **100 shares** (no sell) |
| +30% | $13.00 | **$11.50** (+15%) ratchet | 100 shares |
| +35% | $13.50 | **$12.00** (+20%) ratchet | 100 shares |
| +40% | $14.00 | **$12.50** (+25%) ratchet | 100 shares |
| Price drops... | $12.40 | Hit $12.50 stop → **EXIT** | 0 shares |
| **Total P&L** | | **+25% on 100 shares = $250** | |

---

## When Price Reverses Early (Bad Scenario)

**Same setup, but price only reaches +12% then crashes:**

| Feature | Max Price | What Happens | Exit Price | Result |
|---------|-----------|-------------|------------|--------|
| **Early Trailing** | $11.20 (+12%) | Trail activated at +10%, stop at breakeven $10.00 | $10.00 | **Breakeven** (0%) on 100 shares |
| **Dynamic SL** | $11.20 (+12%) | PT1 hit at +10%, SL at breakeven. Sold 25 at $11.00 | $10.00 for remaining 75 | **+$25** (25 shares × $1 profit) |
| **Escalation Only** | $11.20 (+12%) | PT1 crossed, SL at breakeven. No sells. | $10.00 | **Breakeven** (0%) on 100 shares |

---

## When Price Crashes Before Any Trigger

**Price drops -15% immediately, never recovers:**

| Feature | What Happens | Exit | Result |
|---------|-------------|------|--------|
| **Early Trailing** | Never activated (needed +10%). Original SL at -10% hits. | $9.00 | **-10% on 100 shares = -$100** |
| **Dynamic SL** | No PTs hit. Original SL at -10% hits. | $9.00 | **-10% on 100 shares = -$100** |
| **Escalation Only** | No PTs crossed. Original SL at -10% hits. | $9.00 | **-10% on 100 shares = -$100** |

All three behave identically when price never reaches any trigger — the original hard SL is the safety net.

---

## Decision Guide

| If you want... | Use |
|---------------|-----|
| Smooth, continuous profit locking as price rises | **Early Trailing** |
| Take profits in chunks + rising SL protection | **Dynamic SL** (normal PTs) |
| Ride the full position with rising SL, no trimming | **Dynamic SL + Escalation Only** |
| Maximum profit on big runners | **Escalation Only** (keeps all shares) |
| Most conservative, guaranteed partial profits | **Dynamic SL** (locks in chunks early) |
| Simplest to understand | **Early Trailing** (just activation + step) |

---

## Can They Be Combined?

- **Early Trailing + Dynamic SL**: Yes, both can be active. Dynamic SL takes priority (Priority 2) over Early Trailing (Priority 4). The **higher** stop price wins at any given time.
- **Early Trailing + Escalation Only**: Yes. PT thresholds escalate the Dynamic SL while Early Trailing provides a parallel rising floor.
- **Early Trailing replaces Legacy Trailing**: They are mutually exclusive. If Early Trailing is enabled, Legacy Trailing is skipped.

---

## Priority Order (When Multiple Features Active)

1. **Hard SL** (original stop loss) — always checked first
2. **Dynamic SL** (after PTs) — escalated stop from PT hits
3. **Giveback Guard** — max profit giveback protection
4. **Early Trailing** — breakeven + step-based trailing
5. **Legacy Trailing** — classic % trailing stop (skipped if Early Trail is on)
6. **Profit Target partial sells** — tiered trimming (skipped if Escalation Only is on)

The first trigger that fires wins. Higher priority = checked first.
