"""
Test tiered target trim logic.

Verifies:
1. Trim % rounds to 0 on small positions -> sells 1 (not stuck)
2. Trim % = 0 explicitly -> escalation only (mark tier, no sell)
3. Normal trim % works correctly
4. Auto-split when no trim set
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

for pkg in ('src', 'src.risk', 'src.services', 'gui_app'):
    if pkg not in sys.modules:
        sys.modules[pkg] = types.ModuleType(pkg)

risk_types = _load_module_direct('src.risk.risk_types', os.path.join(_root, 'src', 'risk', 'risk_types.py'))
PositionSnapshot = risk_types.PositionSnapshot
PositionCacheEntry = risk_types.PositionCacheEntry
ChannelRiskSettings = risk_types.ChannelRiskSettings
ExitDecision = risk_types.ExitDecision

tiered = _load_module_direct('src.risk.tiered_targets', os.path.join(_root, 'src', 'risk', 'tiered_targets.py'))
calculate_tier_exit_qty = tiered.calculate_tier_exit_qty
evaluate_tiered_targets = tiered.evaluate_tiered_targets


def make_position(price=11.0, avg_cost=10.0, qty=10):
    return PositionSnapshot(
        symbol='TEST', quantity=qty, avg_cost=avg_cost,
        current_price=price, asset='option', broker='Schwab'
    )

def make_cache(entry_price=10.0, t1=False, t2=False, t3=False, t4=False):
    c = PositionCacheEntry(entry_price=entry_price, highest_price=entry_price)
    c.tier1_hit = t1
    c.tier2_hit = t2
    c.tier3_hit = t3
    c.tier4_hit = t4
    return c

def make_channel(pt1=8, pt2=10, pt3=15, pt4=20, sl=10,
                 trim1=None, trim2=None, trim3=None, trim4=None):
    return ChannelRiskSettings(
        channel_id='123', channel_name='Test',
        profit_target_1_pct=pt1, profit_target_2_pct=pt2,
        profit_target_3_pct=pt3, profit_target_4_pct=pt4,
        stop_loss_pct=sl,
        profit_target_trim_pct_1=trim1, profit_target_trim_pct_2=trim2,
        profit_target_trim_pct_3=trim3, profit_target_trim_pct_4=trim4,
    )


def test_trim_rounds_to_zero_sells_one():
    """4 contracts left, 20% trim = floor(0.8) = 0 -> should sell 1, not 0."""
    channel = make_channel(trim2=20)
    cache = make_cache(t1=True)
    exit_qty, is_partial = calculate_tier_exit_qty(2, 4, channel, cache)
    assert exit_qty == 1, f"Expected 1, got {exit_qty} -- trim should floor to 1 minimum"
    assert is_partial == True
    print(f"  PASS: 4 contracts, 20% trim -> sells {exit_qty} (minimum 1)")


def test_trim_normal_calculation():
    """10 contracts, 60% trim = floor(6.0) = 6."""
    channel = make_channel(trim1=60)
    cache = make_cache()
    exit_qty, is_partial = calculate_tier_exit_qty(1, 10, channel, cache)
    assert exit_qty == 6, f"Expected 6, got {exit_qty}"
    assert is_partial == True
    print(f"  PASS: 10 contracts, 60% trim -> sells {exit_qty}")


def test_trim_100_pct_sells_all():
    """5 contracts, 100% trim = sell all."""
    channel = make_channel(trim4=100)
    cache = make_cache(t1=True, t2=True, t3=True)
    exit_qty, is_partial = calculate_tier_exit_qty(4, 5, channel, cache)
    assert exit_qty == 5, f"Expected 5, got {exit_qty}"
    assert is_partial == False
    print(f"  PASS: 5 contracts, 100% trim -> sells {exit_qty} (all)")


def test_trim_zero_escalation_only():
    """Trim = 0 explicitly -> return 0 (escalation only, no sell)."""
    channel = make_channel(trim3=0)
    cache = make_cache(t1=True, t2=True)
    exit_qty, is_partial = calculate_tier_exit_qty(3, 4, channel, cache)
    assert exit_qty == 0, f"Expected 0 for escalation-only, got {exit_qty}"
    print(f"  PASS: trim=0 -> escalation only, exit_qty={exit_qty}")


def test_evaluate_escalation_marks_tier():
    """Full evaluate: trim=0 at PT2 should mark tier2_hit=True without selling."""
    channel = make_channel(pt1=8, pt2=10, trim1=60, trim2=0)
    cache = make_cache(t1=True)
    pos = make_position(price=11.0, avg_cost=10.0, qty=4)  # +10% -> PT2 triggers

    decision = evaluate_tiered_targets(pos, cache, channel)
    assert cache.tier2_hit == True, "tier2_hit should be True after escalation-only"
    assert decision.should_exit == False or decision.exit_qty == 0, \
        f"Should not sell for escalation-only tier, got should_exit={decision.should_exit}, qty={decision.exit_qty}"
    print(f"  PASS: PT2 escalation-only marked tier2_hit=True, no sell")


def test_evaluate_escalation_chain():
    """PT2=0 and PT3=0 both escalation-only, PT4 sells. Price at +20% triggers all."""
    channel = make_channel(pt1=8, pt2=10, pt3=15, pt4=20, trim1=60, trim2=0, trim3=0, trim4=100)
    cache = make_cache(t1=True)
    pos = make_position(price=12.0, avg_cost=10.0, qty=4)  # +20%

    decision = evaluate_tiered_targets(pos, cache, channel)
    assert cache.tier2_hit == True, "tier2 should be marked"
    assert cache.tier3_hit == True, "tier3 should be marked"
    assert decision.should_exit == True, "PT4 should fire and sell"
    assert decision.exit_qty == 4, f"PT4 trim 100% should sell all 4, got {decision.exit_qty}"
    assert decision.tier_hit == 4
    print(f"  PASS: Escalation chain PT2->PT3->PT4 sell all: qty={decision.exit_qty}")


def test_evaluate_normal_pt1_fires():
    """Standard PT1 with 60% trim on 10 contracts."""
    channel = make_channel(pt1=8, pt2=10, trim1=60)
    cache = make_cache()
    pos = make_position(price=10.80, avg_cost=10.0, qty=10)  # +8%

    decision = evaluate_tiered_targets(pos, cache, channel)
    assert decision.should_exit == True
    assert decision.exit_qty == 6
    assert decision.tier_hit == 1
    print(f"  PASS: PT1 fires, sells {decision.exit_qty} of 10")


def test_small_position_trim_minimum():
    """2 contracts, 20% trim -> should sell 1 (minimum)."""
    channel = make_channel(trim2=20)
    cache = make_cache(t1=True)
    exit_qty, is_partial = calculate_tier_exit_qty(2, 2, channel, cache)
    assert exit_qty == 1, f"Expected 1, got {exit_qty}"
    print(f"  PASS: 2 contracts, 20% trim -> sells {exit_qty} (minimum 1)")


if __name__ == '__main__':
    tests = [
        ("Trim rounds to 0 -> sells 1", test_trim_rounds_to_zero_sells_one),
        ("Normal trim calculation", test_trim_normal_calculation),
        ("Trim 100% sells all", test_trim_100_pct_sells_all),
        ("Trim = 0 escalation only", test_trim_zero_escalation_only),
        ("Evaluate: escalation marks tier", test_evaluate_escalation_marks_tier),
        ("Evaluate: escalation chain PT2->PT3->PT4", test_evaluate_escalation_chain),
        ("Normal PT1 fires", test_evaluate_normal_pt1_fires),
        ("Small position trim minimum", test_small_position_trim_minimum),
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
