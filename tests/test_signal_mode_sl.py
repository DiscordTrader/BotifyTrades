"""
Test signal mode SL safety net.

Verifies that signal mode now evaluates:
1. Signal's own SL price (from cache.stop_loss_price)
2. Channel SL % as fallback (from channel_settings.stop_loss_pct)
"""
import sys
import os
import types
import importlib.util

_root = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, _root)

def _load_module_direct(name, filepath):
    spec = importlib.util.spec_from_file_location(name, filepath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

# Stub out packages so __init__.py doesn't pull the whole dependency tree
for pkg in ('src', 'src.risk', 'src.services', 'gui_app'):
    if pkg not in sys.modules:
        sys.modules[pkg] = types.ModuleType(pkg)

risk_types = _load_module_direct('src.risk.risk_types', os.path.join(_root, 'src', 'risk', 'risk_types.py'))
PositionSnapshot = risk_types.PositionSnapshot
PositionCacheEntry = risk_types.PositionCacheEntry
ChannelRiskSettings = risk_types.ChannelRiskSettings
ExitDecision = risk_types.ExitDecision

global_risk = _load_module_direct('src.risk.global_risk', os.path.join(_root, 'src', 'risk', 'global_risk.py'))
evaluate_price_based_stops = global_risk.evaluate_price_based_stops

tiered_targets = _load_module_direct('src.risk.tiered_targets', os.path.join(_root, 'src', 'risk', 'tiered_targets.py'))
evaluate_channel_stop_loss = tiered_targets.evaluate_channel_stop_loss


def make_position(symbol='TEST', price=8.0, avg_cost=10.0, qty=10, asset='option', broker='Schwab'):
    return PositionSnapshot(
        symbol=symbol, quantity=qty, avg_cost=avg_cost,
        current_price=price, asset=asset, broker=broker
    )

def make_cache(entry_price=10.0, sl_price=None):
    return PositionCacheEntry(
        entry_price=entry_price, highest_price=entry_price,
        stop_loss_price=sl_price
    )

def make_channel(sl_pct=15.0, mode='signal'):
    return ChannelRiskSettings(
        channel_id='123', channel_name='Phoenix',
        stop_loss_pct=sl_pct, exit_strategy_mode=mode
    )


def test_signal_sl_triggers():
    """Signal has SL at $8.50, price drops to $8.00 → signal SL fires."""
    pos = make_position(price=8.0)
    cache = make_cache(entry_price=10.0, sl_price=8.50)

    decision = evaluate_price_based_stops(pos, cache)
    assert decision.should_exit, "Signal SL should trigger when price <= sl_price"
    assert 'STOP LOSS PRICE' in decision.reason
    print(f"  PASS: {decision.reason}")


def test_signal_sl_not_triggered():
    """Signal has SL at $8.50, price is $9.00 → no exit."""
    pos = make_position(price=9.0)
    cache = make_cache(entry_price=10.0, sl_price=8.50)

    decision = evaluate_price_based_stops(pos, cache)
    assert not decision.should_exit, "Signal SL should NOT trigger when price > sl_price"
    print(f"  PASS: No exit (price above signal SL)")


def test_no_signal_sl_channel_fallback_triggers():
    """No signal SL, channel has 15% SL, price drops 20% → channel SL fires."""
    pos = make_position(price=8.0, avg_cost=10.0)  # -20%
    cache = make_cache(entry_price=10.0, sl_price=None)
    channel = make_channel(sl_pct=15.0, mode='signal')

    # Signal SL should NOT trigger (no sl_price)
    signal_decision = evaluate_price_based_stops(pos, cache)
    assert not signal_decision.should_exit, "No signal SL set — should not trigger"

    # Channel SL SHOULD trigger as fallback
    channel_decision = evaluate_channel_stop_loss(pos, cache, channel)
    assert channel_decision.should_exit, "Channel SL should trigger as fallback when no signal SL"
    assert 'Phoenix' in channel_decision.reason or 'CHANNEL' in channel_decision.reason
    print(f"  PASS: {channel_decision.reason}")


def test_no_signal_sl_channel_fallback_not_triggered():
    """No signal SL, channel has 15% SL, price drops only 5% → no exit."""
    pos = make_position(price=9.5, avg_cost=10.0)  # -5%
    cache = make_cache(entry_price=10.0, sl_price=None)
    channel = make_channel(sl_pct=15.0, mode='signal')

    signal_decision = evaluate_price_based_stops(pos, cache)
    assert not signal_decision.should_exit

    channel_decision = evaluate_channel_stop_loss(pos, cache, channel)
    assert not channel_decision.should_exit, "Channel SL should NOT trigger at -5% with 15% threshold"
    print(f"  PASS: No exit (loss within channel SL tolerance)")


def test_no_sl_anywhere():
    """No signal SL, no channel SL → no exit."""
    pos = make_position(price=5.0, avg_cost=10.0)  # -50%
    cache = make_cache(entry_price=10.0, sl_price=None)
    channel = make_channel(sl_pct=0.0, mode='signal')

    signal_decision = evaluate_price_based_stops(pos, cache)
    assert not signal_decision.should_exit

    channel_decision = evaluate_channel_stop_loss(pos, cache, channel)
    assert not channel_decision.should_exit, "No SL configured anywhere — should not exit"
    print(f"  PASS: No exit (no SL configured)")


def test_signal_sl_tighter_than_channel():
    """Signal SL at $9.00 (10%), channel SL 15%. Price at $8.80 → signal SL fires first."""
    pos = make_position(price=8.80, avg_cost=10.0)  # -12%
    cache = make_cache(entry_price=10.0, sl_price=9.00)
    channel = make_channel(sl_pct=15.0, mode='signal')

    # Signal SL triggers first (price $8.80 <= $9.00)
    signal_decision = evaluate_price_based_stops(pos, cache)
    assert signal_decision.should_exit, "Signal SL should trigger (tighter)"
    assert 'STOP LOSS PRICE' in signal_decision.reason
    print(f"  PASS: Signal SL fires first: {signal_decision.reason}")


def test_signal_sl_always_wins_over_channel():
    """Signal SL at $5.00 (50%), channel SL 15%. Price at $8.40 → signal SL wins, no exit yet."""
    pos = make_position(price=8.40, avg_cost=10.0)  # -16%
    cache = make_cache(entry_price=10.0, sl_price=5.00)
    channel = make_channel(sl_pct=15.0, mode='signal')

    _has_signal_sl = cache.stop_loss_price is not None and cache.stop_loss_price > 0
    _decision = evaluate_price_based_stops(pos, cache)
    if not _decision.should_exit and not _has_signal_sl:
        _decision = evaluate_channel_stop_loss(pos, cache, channel)

    assert not _decision.should_exit, "Signal SL exists — channel SL must NOT override it"
    print(f"  PASS: Signal SL wins -- no exit even though channel SL would trigger")


def test_manual_sl_override_in_signal_mode():
    """Trader posts 'SL at $9.20' → manual override takes precedence over channel SL."""
    pos = make_position(price=9.10, avg_cost=10.0)  # -9%
    cache = make_cache(entry_price=10.0, sl_price=None)
    cache.manual_sl_price = 9.20
    channel = make_channel(sl_pct=15.0, mode='signal')

    decision = evaluate_channel_stop_loss(pos, cache, channel)
    assert decision.should_exit, "Manual SL override should trigger"
    assert 'OVERRIDE' in decision.reason
    print(f"  PASS: Manual override fires: {decision.reason}")


def test_signal_pt_triggers():
    """Signal has PT at $12.00, price hits $12.50 → PT fires in signal mode."""
    pos = make_position(price=12.50, avg_cost=10.0)
    cache = make_cache(entry_price=10.0, sl_price=8.50)
    cache.profit_target_price = 12.00

    decision = evaluate_price_based_stops(pos, cache)
    assert decision.should_exit, "Signal PT should trigger"
    assert 'PROFIT TARGET' in decision.reason
    print(f"  PASS: Signal PT fires: {decision.reason}")


def test_manual_override_with_existing_signal_sl():
    """Signal SL at $5.00, trader posts 'SL at $9.20', price at $9.10 -> manual override fires."""
    pos = make_position(price=9.10, avg_cost=10.0)  # -9%
    cache = make_cache(entry_price=10.0, sl_price=5.00)
    cache.manual_sl_price = 9.20
    channel = make_channel(sl_pct=15.0, mode='signal')

    _has_signal_sl = cache.stop_loss_price is not None and cache.stop_loss_price > 0
    _has_manual_sl = cache.manual_sl_price is not None or cache.manual_sl_pct is not None
    _decision = evaluate_price_based_stops(pos, cache)
    if not _decision.should_exit and (not _has_signal_sl or _has_manual_sl):
        _decision = evaluate_channel_stop_loss(pos, cache, channel)

    assert _decision.should_exit, "Manual override must fire even when signal SL exists"
    assert 'OVERRIDE' in _decision.reason
    print(f"  PASS: Manual override fires despite signal SL: {_decision.reason}")


def test_flow_matches_implementation():
    """
    Simulate the exact flow from position_monitor.py:
      1. evaluate_price_based_stops first
      2. If no exit AND no signal SL exists, evaluate_channel_stop_loss as fallback
    """
    # Scenario A: no signal SL, channel SL 10%, price down 12% → channel fallback fires
    pos = make_position(price=8.80, avg_cost=10.0)
    cache = make_cache(entry_price=10.0, sl_price=None)
    channel = make_channel(sl_pct=10.0, mode='signal')

    _has_signal_sl = cache.stop_loss_price is not None and cache.stop_loss_price > 0
    _decision = evaluate_price_based_stops(pos, cache)
    if not _decision.should_exit and not _has_signal_sl:
        _decision = evaluate_channel_stop_loss(pos, cache, channel)

    assert _decision.should_exit, "Channel fallback should trigger when no signal SL"
    print(f"  PASS (A): No signal SL -> channel fallback: {_decision.reason}")

    # Scenario B: signal SL at $7.00, channel SL 10%, price down 12% → no exit (signal SL not hit)
    cache_b = make_cache(entry_price=10.0, sl_price=7.00)
    _has_signal_sl_b = cache_b.stop_loss_price is not None and cache_b.stop_loss_price > 0
    _decision_b = evaluate_price_based_stops(pos, cache_b)
    if not _decision_b.should_exit and not _has_signal_sl_b:
        _decision_b = evaluate_channel_stop_loss(pos, cache_b, channel)

    assert not _decision_b.should_exit, "Signal SL exists at $7 — channel SL must not override"
    print(f"  PASS (B): Signal SL exists -> channel skipped, no exit")


if __name__ == '__main__':
    tests = [
        ("Signal SL triggers", test_signal_sl_triggers),
        ("Signal SL not triggered", test_signal_sl_not_triggered),
        ("No signal SL — channel fallback triggers", test_no_signal_sl_channel_fallback_triggers),
        ("No signal SL — channel fallback not triggered", test_no_signal_sl_channel_fallback_not_triggered),
        ("No SL anywhere", test_no_sl_anywhere),
        ("Signal SL tighter than channel", test_signal_sl_tighter_than_channel),
        ("Signal SL always wins over channel", test_signal_sl_always_wins_over_channel),
        ("Manual SL override in signal mode", test_manual_sl_override_in_signal_mode),
        ("Signal PT triggers in signal mode", test_signal_pt_triggers),
        ("Manual override with existing signal SL", test_manual_override_with_existing_signal_sl),
        ("Flow matches implementation", test_flow_matches_implementation),
    ]

    passed = 0
    failed = 0
    for name, test_fn in tests:
        try:
            print(f"\n[TEST] {name}")
            test_fn()
            passed += 1
        except AssertionError as e:
            print(f"  FAIL: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)}")
    if failed == 0:
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED")
        sys.exit(1)
