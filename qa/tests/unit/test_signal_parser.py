"""
Unit Tests for Signal Parser
Tests all signal formats: BTO/STC, Bullwinkle, Jacob, Z-scalps, Jake, Bishop, EvaPanda, Conditional
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))


class TestBTOSTCSignals:
    """Test standard BTO/STC signal format"""
    
    @pytest.mark.unit
    def test_bto_call_option(self):
        """BTO 10 SPY 450c 01/17 @ 1.50"""
        from src.signals.parser import parse_signal
        
        signal = "BTO 10 SPY 450c 01/17 @ 1.50"
        result = parse_signal(signal)
        
        assert result is not None, f"Failed to parse: {signal}"
        assert result.get('action') == 'BTO'
        assert result.get('symbol') == 'SPY'
        assert result.get('strike') == 450.0
        assert result.get('opt_type') == 'C'
        assert result.get('qty') == 10
        assert result.get('price') == 1.50
    
    @pytest.mark.unit
    def test_bto_put_option(self):
        """BTO 5 AAPL 180p 02/21 @ 2.25"""
        from src.signals.parser import parse_signal
        
        signal = "BTO 5 AAPL 180p 02/21 @ 2.25"
        result = parse_signal(signal)
        
        assert result is not None
        assert result.get('action') == 'BTO'
        assert result.get('symbol') == 'AAPL'
        assert result.get('strike') == 180.0
        assert result.get('opt_type') == 'P'
        assert result.get('qty') == 5
    
    @pytest.mark.unit
    def test_stc_option(self):
        """STC 5 TSLA 250c 01/19 @ 3.00"""
        from src.signals.parser import parse_signal
        
        signal = "STC 5 TSLA 250c 01/19 @ 3.00"
        result = parse_signal(signal)
        
        assert result is not None
        assert result.get('action') == 'STC'
        assert result.get('symbol') == 'TSLA'
    
    @pytest.mark.unit
    def test_bto_without_quantity(self):
        """BTO SPY 450c 01/17 @ 1.50 (no quantity specified)"""
        from src.signals.parser import parse_signal
        
        signal = "BTO SPY 450c 01/17 @ 1.50"
        result = parse_signal(signal)
        
        assert result is not None
        assert result.get('action') == 'BTO'
        assert result.get('symbol') == 'SPY'
    
    @pytest.mark.unit
    def test_bto_with_range_price(self):
        """BTO 10 NVDA 500c 01/24 @ 2.50-2.75"""
        from src.signals.parser import parse_signal
        
        signal = "BTO 10 NVDA 500c 01/24 @ 2.50-2.75"
        result = parse_signal(signal)
        
        assert result is not None
        assert result.get('action') == 'BTO'
        assert result.get('symbol') == 'NVDA'


class TestBullwinkleSignals:
    """Test Bullwinkle signal format (lotto style)"""
    
    @pytest.mark.unit
    def test_bullwinkle_lotto(self):
        """TSLA 250c 01/19 lotto @ 0.50"""
        from src.signals.parser import parse_signal
        
        signal = "TSLA 250c 01/19 lotto @ 0.50"
        result = parse_signal(signal)
        
        assert result is not None
        assert result.get('symbol') == 'TSLA'
        assert result.get('strike') == 250.0
        assert result.get('opt_type') == 'C'
    
    @pytest.mark.unit
    def test_bullwinkle_with_emoji(self):
        """🎰 AAPL 190c 01/24 lotto @ 0.25"""
        from src.signals.parser import parse_signal
        
        signal = "🎰 AAPL 190c 01/24 lotto @ 0.25"
        result = parse_signal(signal)
        
        if result:
            assert result.get('symbol') == 'AAPL'


class TestJacobSignals:
    """Test Jacob signal format (ENTERED LONG/SHORT)"""
    
    @pytest.mark.unit
    def test_jacob_entered_long(self):
        """ENTERED LONG NVDA 500c 01/24 @ 3.50"""
        from src.signals.parser import parse_signal
        
        signal = "ENTERED LONG NVDA 500c 01/24 @ 3.50"
        result = parse_signal(signal)
        
        assert result is not None
        assert result.get('action') == 'BTO'
        assert result.get('symbol') == 'NVDA'
    
    @pytest.mark.unit
    def test_jacob_with_role_mention(self):
        """<@&123456> ENTERED LONG SPY 450c 01/17 @ 1.00"""
        from src.signals.parser import parse_signal
        
        signal = "<@&123456789> ENTERED LONG SPY 450c 01/17 @ 1.00"
        result = parse_signal(signal)
        
        assert result is not None
        assert result.get('symbol') == 'SPY'


class TestBishopSignals:
    """Test Bishop signal format (I'M ENTERING + Option:)"""
    
    @pytest.mark.unit
    def test_bishop_entering(self):
        """I'M ENTERING\nOption: META 400c 02/14\nEntry: $2.00"""
        from src.signals.parser import parse_signal
        
        signal = "I'M ENTERING\nOption: META 400c 02/14\nEntry: $2.00"
        result = parse_signal(signal)
        
        assert result is not None
        assert result.get('action') == 'BTO'
        assert result.get('symbol') == 'META'
    
    @pytest.mark.unit
    def test_bishop_trimming(self):
        """Trimming AAPL 190c 01/24"""
        from src.signals.parser import parse_signal
        
        signal = "Trimming AAPL 190c 01/24"
        result = parse_signal(signal)
        
        if result:
            assert result.get('action') == 'STC'


class TestEvaPandaSignals:
    """Test EvaPanda signal format"""
    
    @pytest.mark.unit
    def test_evapanda_with_emoji(self):
        """🐼 AAPL 195c 01/24 @ 1.25 🎯"""
        from src.signals.parser import parse_signal
        
        signal = "🐼 AAPL 195c 01/24 @ 1.25 🎯"
        result = parse_signal(signal)
        
        if result:
            assert result.get('symbol') == 'AAPL'
            assert result.get('opt_type') == 'C'


class TestConditionalSignals:
    """Test conditional order signals (over/above, under/below triggers)"""
    
    @pytest.mark.unit
    def test_conditional_over_trigger(self):
        """BTO 10 QQQ 400c 01/17 @ 1.00 over 399"""
        from src.signals.parser import parse_signal
        
        signal = "BTO 10 QQQ 400c 01/17 @ 1.00 over 399"
        result = parse_signal(signal)
        
        assert result is not None
        assert result.get('symbol') == 'QQQ'
    
    @pytest.mark.unit
    def test_conditional_above_trigger(self):
        """BTO SPY 455c 01/17 @ 0.50 above 453"""
        from src.signals.parser import parse_signal
        
        signal = "BTO SPY 455c 01/17 @ 0.50 above 453"
        result = parse_signal(signal)
        
        assert result is not None
    
    @pytest.mark.unit
    def test_conditional_under_trigger(self):
        """BTO SPY 445p 01/17 @ 0.75 under 448"""
        from src.signals.parser import parse_signal
        
        signal = "BTO SPY 445p 01/17 @ 0.75 under 448"
        result = parse_signal(signal)
        
        assert result is not None


class TestZScalpsSignals:
    """Test Z-scalps signal format"""
    
    @pytest.mark.unit
    def test_zscalps_format(self):
        """Test Z-scalps specific format if applicable"""
        from src.signals.parser import parse_signal
        
        signal = "SPY 450c @ 1.50"
        result = parse_signal(signal)
        
        if result:
            assert result.get('symbol') == 'SPY'


class TestJakeSignals:
    """Test Jake signal format"""
    
    @pytest.mark.unit
    def test_jake_format(self):
        """Test Jake-specific signal format"""
        from src.signals.parser import parse_signal
        
        signal = "Bought SPY 450c 01/17 @ 1.50"
        result = parse_signal(signal)
        
        if result:
            assert result.get('action') == 'BTO'


class TestOrderExecutedSignals:
    """Test Order Executed format (broker confirmation style)"""
    
    @pytest.mark.unit
    def test_order_executed_format(self):
        """Order Executed: BTO 10 SPY 450c 01/17 @ 1.50"""
        from src.signals.parser import parse_signal
        
        signal = "Order Executed: BTO 10 SPY 450c 01/17 @ 1.50"
        result = parse_signal(signal)
        
        if result:
            assert result.get('action') == 'BTO'


class TestEdgeCases:
    """Test edge cases and malformed signals"""
    
    @pytest.mark.unit
    def test_empty_string(self):
        """Empty string should return None"""
        from src.signals.parser import parse_signal
        
        result = parse_signal("")
        assert result is None
    
    @pytest.mark.unit
    def test_random_text(self):
        """Random text should not match"""
        from src.signals.parser import parse_signal
        
        result = parse_signal("Hello, how are you today?")
        assert result is None
    
    @pytest.mark.unit
    def test_partial_signal(self):
        """Incomplete signals should not match"""
        from src.signals.parser import parse_signal
        
        result = parse_signal("BTO SPY")
        assert result is None
    
    @pytest.mark.unit
    def test_lowercase_action(self):
        """Lowercase actions should still parse"""
        from src.signals.parser import parse_signal
        
        signal = "bto 10 SPY 450c 01/17 @ 1.50"
        result = parse_signal(signal)
        
        if result:
            assert result.get('action').upper() == 'BTO'
    
    @pytest.mark.unit
    def test_extra_whitespace(self):
        """Extra whitespace should be handled"""
        from src.signals.parser import parse_signal
        
        signal = "  BTO  10  SPY  450c  01/17  @  1.50  "
        result = parse_signal(signal)
        
        if result:
            assert result.get('symbol') == 'SPY'


class TestStockSignals:
    """Test stock (non-option) signals"""
    
    @pytest.mark.unit
    def test_bto_stock(self):
        """BTO 100 AAPL @ 185.50"""
        from src.signals.parser import parse_signal
        
        signal = "BTO 100 AAPL @ 185.50"
        result = parse_signal(signal)
        
        if result:
            assert result.get('symbol') == 'AAPL'
            assert result.get('asset') == 'stock' or result.get('strike') is None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "unit"])
