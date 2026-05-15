"""Test new channel messages (Ashley, Angela, Rocky) against existing parsers."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from services.signal_format_registry import SignalFormatRegistry

registry = SignalFormatRegistry()

# ---- ASHLEY BTO ENTRIES (RedAlert emoji format) ----
ashley_bto = [
    '<a:RedAlert:759583962237763595> SEDG - $60 CALLS 5/29 $1.15 @everyone \n\nSMALL OVERNIGHT SWING',
    '<a:RedAlert:759583962237763595> GS - $985 CALLS EXPIRATION THIS WEEK $2.50\n\nSTOP LOSS AT $2.00, ROUND #2, ROLLING PROFITS @everyone',
    '<a:RedAlert:759583962237763595> CRCL - $150 CALLS EXPIRATION NEXT WEEK $3.60\n\nSTOP LOSS AT $3.20 @everyone',
    '<a:RedAlert:759583962237763595> AVGO - $450 CALLS EXPIRATION 5/20 $4.80 @everyone \n\nSTOP LOSS AT $4.00, SMALL POSITION ONLY',
    '<a:RedAlert:759583962237763595> SPX - 7400 CALLS 0DTE $1.50 @everyone \n\nCHEAP LOTTO PLAY',
    '<a:RedAlert:759583962237763595> SPY - $735 PUTS 0DTE $2.40 @everyone \n\nSTOP LOSS AT $2.00, ROLLING PROFITS, SMALL POSITION',
    '<a:RedAlert:759583962237763595> CSCO - $125 CALLS 6/18 .97\n\nCHEAP EARNINGS LOTTO PLAY, HERO OR ZERO @everyone',
    '<a:RedAlert:759583962237763595> WMT - $131 CALLS EXPIRATION THIS WEEK $1.45 @everyone \n\nSTOP LOSS AT $1.15',
    '<a:RedAlert:759583962237763595> GS - $1100 CALLS EXPIRATION 6/18 $3.00\n\nSWING PLAY, CAN SET YOUR OWN SL @everyone',
    '<a:RedAlert:759583962237763595> PANW - $225 CALLS EXPIRATION THIS WEEK $1.40 @everyone',
    '<a:RedAlert:759583962237763595> JD - $33.5 CALLS EXPIRATION THIS WEEK .90\n\nSTOP LOSS AT .70, LOTTO SIZE @everyone',
    '<a:RedAlert:759583962237763595> WMT - $134 CALLS EXPIRATION THIS WEEK .80\n\nCHEAP LOTTO PLAY @everyone',
    '<a:RedAlert:759583962237763595> PANW - $230 CALLS EXPIRATION THIS WEEK .60\n\nSUPER LOTTOS @everyone',
]

# ---- ASHLEY TRIMS/EXITS ----
ashley_trims = [
    'TRIM PARTIAL HERE AT $1.65 @everyone',
    'GS CALLS TRIMMING LITTLE MORE @everyone',
    'AVGO TRIMMED MORE @everyone',
    'AVGO FLYING, TRIMMED MOST @everyone',
    'UP $100 PER CONTRACT, TRIMMED 50% HERE @everyone',
    'WMT TRIMMED PARTIAL AT $1.85 @everyone',
    'GS TRIMMED 25% MORE @everyone',
    'TRIMMED MOST',
]
ashley_exits = [
    'FCEL ALL OUT @everyone',
    'OKAY ALL OUT NOW, 350%  @everyone',
    'ALL OUT @everyone',
    'PANW 217.5 CALLS ALL OUT @everyone',
    'SPX LOTTOS ALL OUT @everyone',
]

# ---- ANGELA BTO ENTRIES (siren_blue emoji format) ----
angela_bto = [
    '@everyone <a:8375_siren_blue:785286170904625152> ENPH calls $50 $1.83 5/22 added SL 1.6 possible swing',
    '@everyone <a:8375_siren_blue:785286170904625152> GOOGL calls $405 $1.72 5/15 added SL 1.4',
    '@everyone <a:8375_siren_blue:785286170904625152> IONQ calls  $58 $1.24 5/15 added SL 0.9',
    '@everyone <a:8375_siren_blue:785286170904625152> TSLA calls $460 $2.4 5/15 added SL 2',
    '@everyone META calls $635 $2.26 5/15 added SL 1.9',
    '@everyone <a:8375_siren_blue:785286170904625152> AVGO calls $445 $2.4 5/15 added SL  2',
    '@everyone <a:8375_siren_blue:785286170904625152> AMZN calls $275 $1.09 5/15 added for swing. Stop 1.7',
    '@everyone <a:8375_siren_blue:785286170904625152> F calls $14 $0.22 5/15 lotto',
    '@everyone <a:8375_siren_blue:785286170904625152> WULF lotto calls $24.5 $0.41 5/15 aDDDED',
    '@everyone <a:8375_siren_blue:785286170904625152> TSLA lotto calls $452.5 $1.14 5/13 added SL  0.8',
    '@everyone <a:8375_siren_blue:785286170904625152> MRVL calls $190 $1.68 5/15 added SL 1.2',
]

# ---- ANGELA TRIMS/EXITS ----
angela_trims = [
    '@everyone TSLA taking 40% at $2.84',
    '@everyone GOOGL calls at $2.30 taking more 20%',
    '@everyone MRVL calls at $2.75 taking 50%',
    '@everyone AVGO taking 50% at $2.9',
    '@everyone AAPL calls at $3.85. closing 70% in total down to last 30%. will swing them',
    '@everyone RKLB taking 50% at $3.20',
]
angela_exits = [
    '@everyone CLOSED REST TSLA',
    '@everyone SPX closed',
    '@everyone TSLA clotto closed',
]
angela_stops = [
    '@everyone TSLA hit stop',
    '@everyone TSLA stop hit. $448.40 support. can hold it little longer',
]

# ---- ROCKY BTO ENTRIES (🚨 format) ----
rocky_bto = [
    '@everyone 🚨 MU calls $850 $3.45 tomorrow expiry added only 3',
    '@everyone 🚨 COIN calls $225 $2.45 this week expiry added here. Stop at $2',
    '@everyone 🚨 SMCI calls $33.5 $0.68 this week expiry added stop at $0.4',
    '@everyone 🚨 NBIS calls $230 $2.88 5/15  expiry added SL 2.4',
    '@everyone 🚨 QUBT calls $12 $0.74 6/5 expiry added',
    '@everyone 🚨 TSLA calls $445 $2 today expiry added stop at $1.5',
    '@everyone 🚨 RDDT calls $167.5 $2.38 this week expiry added stop at $1.8',
    '@everyone 🚨 BABA $150 calls 5/15 expiry added at $2.9 stop at $2.4 swing play most likely',
    '@everyone 🚨 AMZN calls $277.5 this week expiry added at $1.76 stop at $1.3',
    '@everyone 🚨 MU $600 calls $3.35 this week expiry added 5 stop at 2.8',
    '@everyone 🚨 HOOD calls $76 $1.82 next week expiry added stop at 1.4',
    '@everyone 🚨 TSLA calls $440 $2.  5/13 expiry added for swing. Stop at 1.6',
    '@everyone 🚨 MU calls $630 $3.80 5/15 expiry added stop at $3.',
]

# ---- ROCKY TRIMS/EXITS ----
rocky_trims = [
    '@everyone COIN taking 1/3rd at $2.94',
    '@everyone QUBT calls at $1.05 heree taking 1/3rd',
    '@everyone NBIS took half at $4.60',
    '@everyone TSLA calls at $3.15 taking half. nice run',
    '@everyone HOOD swings taking 1/3rd at $2.50',
    '@everyone TSLA calls 400%. taking profits here',
]
rocky_exits = [
    '@everyone MU closed faked out a breakout',
]

# ---- ROCKY FLOW ALERTS (should NOT match) ----
rocky_flow_reject = [
    '@everyone $COIN massive bullish flow spotted 👀🔥\n\n🟢 COIN 207.5C 05/15/2026\n💰 $8M+ call buyer hits the tape\n📊 Huge green candle followed aggressive ask-side sweeps\n⚡ 11K+ contracts traded at the ask\n\nBig money loading short-dated COIN calls into tomorrow\'s expiry as bulls continue pressing upside momentum. 🚀',
    '$NVDA MASSIVE call buyer still holding 👀🔥\n\n🟢 NVDA 247.5C 05/22/2026\n💰 Premium: $9.76M\n📊 23K+ contracts traded\n⚡ Next week expiration\n\nThis whale loaded calls near open and continues to hold throughout the session despite volatility. Aggressive bullish positioning remains intact into next week. 🚀 @everyone',
    '@everyone $OKLO FLOW ALERT 👀⚛️\n\n🟢 Flow Sentiment: BULLISH\n📞 Call Flow: $417.6K (86.2%)\n📉 Put Flow: $72K (13.8%)\n⚖️ Put/Call Ratio: 0.16\n\nDespite the stock being down over 6% today, traders were aggressively buying calls on the dip.',
]


def test_section(name, messages, expect_match):
    matched = 0
    unmatched = 0
    false_pos = 0
    for msg in messages:
        result = registry.parse(msg)
        if expect_match:
            if result:
                matched += 1
            else:
                unmatched += 1
                print(f"  [GAP] No match: {msg[:80]}...")
        else:
            if result and result.get('action') not in ('SKIP',) and not result.get('_flow_alert'):
                false_pos += 1
                print(f"  [FALSE POS] Matched '{result.get('_format_name')}': {msg[:80]}...")
            else:
                matched += 1  # correctly rejected or SKIP

    if expect_match:
        print(f"\n{name}: {matched}/{len(messages)} matched, {unmatched} GAPS")
    else:
        print(f"\n{name}: {matched}/{len(messages)} correctly rejected, {false_pos} FALSE POSITIVES")
    return unmatched if expect_match else false_pos


print("=" * 70)
print("TESTING NEW CHANNEL MESSAGES AGAINST EXISTING PARSERS")
print("=" * 70)

total_gaps = 0
total_gaps += test_section("ASHLEY BTO", ashley_bto, True)
total_gaps += test_section("ASHLEY TRIMS", ashley_trims, True)
total_gaps += test_section("ASHLEY EXITS", ashley_exits, True)
total_gaps += test_section("ANGELA BTO", angela_bto, True)
total_gaps += test_section("ANGELA TRIMS", angela_trims, True)
total_gaps += test_section("ANGELA EXITS", angela_exits, True)
total_gaps += test_section("ANGELA STOPS", angela_stops, True)
total_gaps += test_section("ROCKY BTO", rocky_bto, True)
total_gaps += test_section("ROCKY TRIMS", rocky_trims, True)
total_gaps += test_section("ROCKY EXITS", rocky_exits, True)
total_gaps += test_section("ROCKY FLOW REJECT", rocky_flow_reject, False)

print(f"\n{'=' * 70}")
print(f"TOTAL GAPS/ISSUES: {total_gaps}")
print(f"{'=' * 70}")
