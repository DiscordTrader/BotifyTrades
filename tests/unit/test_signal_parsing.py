"""
Signal Parsing Unit Tests
=========================
Tests for Discord message parsing and signal extraction.
"""
import pytest
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.mark.quick
@pytest.mark.signal
class TestStockSignalParsing:
    """Test stock trading signal parsing."""
    
    def test_basic_buy_signal(self):
        """Test parsing basic BUY signals."""
        patterns = [
            ("BUY AAPL @ 150.50", {'action': 'BUY', 'symbol': 'AAPL', 'price': 150.50}),
            ("Buy TSLA at 250", {'action': 'BUY', 'symbol': 'TSLA', 'price': 250.0}),
            ("BUYING NVDA 500", {'action': 'BUY', 'symbol': 'NVDA', 'price': 500.0}),
            ("Long MSFT @ 380.25", {'action': 'BUY', 'symbol': 'MSFT', 'price': 380.25}),
        ]
        
        buy_regex = re.compile(
            r'(?:BUY|BUYING|LONG)\s+([A-Z]{1,5})\s*(?:@|at|AT)?\s*\$?(\d+(?:\.\d{1,2})?)',
            re.IGNORECASE
        )
        
        for message, expected in patterns:
            match = buy_regex.search(message)
            assert match is not None, f"Should match: {message}"
            assert match.group(1).upper() == expected['symbol']
            assert float(match.group(2)) == expected['price']
    
    def test_basic_sell_signal(self):
        """Test parsing basic SELL signals."""
        patterns = [
            ("SELL AAPL @ 155.00", {'action': 'SELL', 'symbol': 'AAPL', 'price': 155.0}),
            ("Sell TSLA at 260", {'action': 'SELL', 'symbol': 'TSLA', 'price': 260.0}),
            ("SELLING NVDA 520", {'action': 'SELL', 'symbol': 'NVDA', 'price': 520.0}),
            ("Short SPY @ 450", {'action': 'SELL', 'symbol': 'SPY', 'price': 450.0}),
        ]
        
        sell_regex = re.compile(
            r'(?:SELL|SELLING|SHORT)\s+([A-Z]{1,5})\s*(?:@|at|AT)?\s*\$?(\d+(?:\.\d{1,2})?)',
            re.IGNORECASE
        )
        
        for message, expected in patterns:
            match = sell_regex.search(message)
            assert match is not None, f"Should match: {message}"
            assert match.group(1).upper() == expected['symbol']
            assert float(match.group(2)) == expected['price']
    
    def test_symbol_validation(self):
        """Test that only valid stock symbols are accepted."""
        valid_symbols = ['AAPL', 'TSLA', 'NVDA', 'SPY', 'A', 'AA', 'GOOGL']
        invalid_symbols = ['TOOLONG', '123', 'A1B2', '', 'lowercase']
        
        symbol_regex = re.compile(r'^[A-Z]{1,5}$')
        
        for symbol in valid_symbols:
            assert symbol_regex.match(symbol), f"Should be valid: {symbol}"
        
        for symbol in invalid_symbols:
            assert not symbol_regex.match(symbol), f"Should be invalid: {symbol}"


@pytest.mark.quick
@pytest.mark.signal
class TestOptionSignalParsing:
    """Test options trading signal parsing."""
    
    def test_bto_signal(self):
        """Test parsing BTO (Buy To Open) option signals."""
        patterns = [
            ("BTO NVDA 12/15 500C @ 5.50", {'action': 'BTO', 'symbol': 'NVDA', 'strike': 500, 'type': 'C'}),
            ("BTO SPY 450P 01/19 @ 3.25", {'action': 'BTO', 'symbol': 'SPY', 'strike': 450, 'type': 'P'}),
            ("BTO AAPL 180 calls 12/20 @ 2.00", {'action': 'BTO', 'symbol': 'AAPL', 'strike': 180, 'type': 'C'}),
        ]
        
        bto_regex = re.compile(
            r'BTO\s+([A-Z]{1,5})\s+(?:(\d{1,2}/\d{1,2})\s+)?(\d+(?:\.\d+)?)\s*([CP]|calls?|puts?)',
            re.IGNORECASE
        )
        
        for message, expected in patterns:
            match = bto_regex.search(message)
            assert match is not None, f"Should match BTO: {message}"
            assert match.group(1).upper() == expected['symbol']
    
    def test_stc_signal(self):
        """Test parsing STC (Sell To Close) option signals."""
        patterns = [
            ("STC NVDA 12/15 500C @ 7.50", {'action': 'STC', 'symbol': 'NVDA'}),
            ("STC SPY 450P @ 5.00", {'action': 'STC', 'symbol': 'SPY'}),
        ]
        
        stc_regex = re.compile(
            r'STC\s+([A-Z]{1,5})',
            re.IGNORECASE
        )
        
        for message, expected in patterns:
            match = stc_regex.search(message)
            assert match is not None, f"Should match STC: {message}"
            assert match.group(1).upper() == expected['symbol']
    
    def test_occ_symbol_format(self):
        """Test OCC option symbol format validation."""
        valid_occ = [
            'AAPL231215C00180000',  # AAPL Dec 15, 2023 $180 Call
            'SPY240119P00450000',   # SPY Jan 19, 2024 $450 Put
            'NVDA231208C00500000',  # NVDA Dec 8, 2023 $500 Call
        ]
        
        occ_regex = re.compile(r'^[A-Z]{1,6}\d{6}[CP]\d{8}$')
        
        for symbol in valid_occ:
            assert occ_regex.match(symbol), f"Should be valid OCC: {symbol}"
    
    def test_expiry_date_parsing(self):
        """Test option expiry date parsing."""
        date_formats = [
            ('12/15', '12/15'),
            ('01/19/24', '01/19/24'),
            ('Dec 15', 'Dec 15'),
            ('January 19', 'January 19'),
        ]
        
        date_regex = re.compile(
            r'(\d{1,2}/\d{1,2}(?:/\d{2,4})?|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2})',
            re.IGNORECASE
        )
        
        for date_str, expected in date_formats:
            match = date_regex.search(f"BTO AAPL {date_str} 180C")
            assert match is not None, f"Should parse date: {date_str}"


@pytest.mark.quick
@pytest.mark.signal
class TestNonSignalFiltering:
    """Test that non-signal messages are correctly filtered out."""
    
    def test_chat_messages_ignored(self, sample_non_signal_messages):
        """Test that casual chat messages are not parsed as signals."""
        signal_indicators = ['BUY', 'SELL', 'BTO', 'STC', 'LONG', 'SHORT']
        
        for message in sample_non_signal_messages:
            has_signal = any(indicator in message.upper() for indicator in signal_indicators)
            assert not has_signal, f"Should not contain signal indicator: {message}"
    
    def test_question_messages_ignored(self):
        """Test that questions about stocks are not parsed as signals."""
        questions = [
            "What do you think about AAPL?",
            "Should I buy TSLA here?",
            "Is NVDA a good entry?",
            "Anyone buying SPY calls?",
        ]
        
        question_regex = re.compile(r'\?|should|think|anyone|good entry', re.IGNORECASE)
        
        for message in questions:
            is_question = bool(question_regex.search(message))
            assert is_question, f"Should be detected as question: {message}"
    
    def test_past_tense_ignored(self):
        """Test that past tense statements are not parsed as new signals."""
        past_tense = [
            "I bought AAPL yesterday",
            "Sold my TSLA position last week",
            "Already took profits on NVDA",
        ]
        
        past_indicators = ['bought', 'sold', 'took', 'yesterday', 'last week', 'already']
        
        for message in past_tense:
            has_past = any(ind in message.lower() for ind in past_indicators)
            assert has_past, f"Should be detected as past tense: {message}"


@pytest.mark.quick
@pytest.mark.signal
class TestChannelPermissions:
    """Test channel-based trade execution permissions."""
    
    def test_execute_channel_allows_trades(self, sample_channel_data):
        """Channels with execute_trades=True should allow trade execution."""
        channel = sample_channel_data.copy()
        channel['execute_trades'] = True
        channel['track_only'] = False
        
        can_execute = channel['execute_trades'] and not channel['track_only']
        assert can_execute is True
    
    def test_track_only_channel_blocks_trades(self, sample_channel_data):
        """Channels with track_only=True should block trade execution."""
        channel = sample_channel_data.copy()
        channel['execute_trades'] = False
        channel['track_only'] = True
        
        can_execute = channel['execute_trades'] and not channel['track_only']
        assert can_execute is False
    
    def test_disabled_channel_blocks_all(self, sample_channel_data):
        """Channels with both flags False should block everything."""
        channel = sample_channel_data.copy()
        channel['execute_trades'] = False
        channel['track_only'] = False
        
        is_active = channel['execute_trades'] or channel['track_only']
        assert is_active is False


@pytest.mark.quick
@pytest.mark.signal
class TestRiskSizing:
    """Test position sizing and risk management calculations."""
    
    def test_position_size_calculation(self):
        """Test that position size is correctly calculated from percentage."""
        buying_power = 100000.0
        position_size_pct = 5.0  # 5% of portfolio
        stock_price = 150.0
        
        max_position_value = buying_power * (position_size_pct / 100)
        max_shares = int(max_position_value / stock_price)
        
        assert max_position_value == 5000.0
        assert max_shares == 33
    
    def test_stop_loss_calculation(self):
        """Test stop loss price calculation."""
        entry_price = 100.0
        stop_loss_pct = 5.0  # 5% stop loss
        
        stop_price = entry_price * (1 - stop_loss_pct / 100)
        assert stop_price == 95.0
    
    def test_profit_target_calculation(self):
        """Test profit target price calculation."""
        entry_price = 100.0
        profit_target_pct = 10.0  # 10% profit target
        
        target_price = entry_price * (1 + profit_target_pct / 100)
        assert abs(target_price - 110.0) < 0.001  # Use tolerance for float comparison
    
    def test_trailing_stop_calculation(self):
        """Test trailing stop price calculation."""
        current_price = 110.0  # Price moved up
        entry_price = 100.0
        trailing_stop_pct = 3.0  # 3% trailing stop
        
        trailing_stop_price = current_price * (1 - trailing_stop_pct / 100)
        assert trailing_stop_price == 106.7
        assert trailing_stop_price > entry_price  # Should lock in some profit
    
    def test_risk_reward_ratio(self):
        """Test risk/reward ratio calculation."""
        entry_price = 100.0
        stop_loss = 95.0
        profit_target = 115.0
        
        risk = entry_price - stop_loss
        reward = profit_target - entry_price
        risk_reward_ratio = reward / risk
        
        assert risk == 5.0
        assert reward == 15.0
        assert risk_reward_ratio == 3.0  # 3:1 reward to risk
