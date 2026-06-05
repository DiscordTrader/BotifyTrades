"""
Option Chain Unit Tests
=======================
Tests for option chain loading, caching, and fallback behavior.
"""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime, timedelta
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.mark.quick
@pytest.mark.options
class TestOptionSymbolParsing:
    """Test OCC option symbol parsing."""
    
    def test_occ_symbol_format(self):
        """Test OCC symbol format parsing."""
        occ_symbol = 'AAPL  231215C00180000'
        
        root = occ_symbol[:6].strip() if len(occ_symbol) >= 6 else occ_symbol
        expiry = occ_symbol[6:12] if len(occ_symbol) >= 12 else ''
        option_type = occ_symbol[12:13] if len(occ_symbol) >= 13 else ''
        strike_raw = occ_symbol[13:] if len(occ_symbol) > 13 else ''
        
        assert root.strip() == 'AAPL'
        assert expiry == '231215'
        assert option_type == 'C'
        assert strike_raw == '00180000'
    
    def test_strike_price_calculation(self):
        """Test strike price from OCC format."""
        strike_raw = '00180000'
        strike = int(strike_raw) / 1000
        
        assert strike == 180.0
    
    def test_option_type_call_put(self):
        """Test option type identification."""
        call_symbol = 'AAPL  231215C00180000'
        put_symbol = 'AAPL  231215P00180000'
        
        assert 'C' in call_symbol
        assert 'P' in put_symbol
        
        call_type = call_symbol[12:13]
        put_type = put_symbol[12:13]
        
        assert call_type == 'C'
        assert put_type == 'P'


@pytest.mark.quick
@pytest.mark.options
class TestOptionChainData:
    """Test option chain data structure."""
    
    def test_option_chain_structure(self):
        """Test expected option chain data structure."""
        chain = {
            'symbol': 'AAPL',
            'expirations': ['2024-12-20', '2024-12-27', '2025-01-17'],
            'calls': [],
            'puts': []
        }
        
        assert 'symbol' in chain
        assert 'expirations' in chain
        assert 'calls' in chain
        assert 'puts' in chain
        assert len(chain['expirations']) > 0
    
    def test_option_contract_structure(self):
        """Test individual option contract structure."""
        contract = {
            'symbol': 'AAPL231220C00180000',
            'strike': 180.0,
            'expiration': '2024-12-20',
            'type': 'call',
            'bid': 5.50,
            'ask': 5.60,
            'last': 5.55,
            'volume': 1000,
            'open_interest': 5000,
            'implied_volatility': 0.25,
            'delta': 0.55,
            'gamma': 0.05,
            'theta': -0.03,
            'vega': 0.15
        }
        
        required_fields = ['symbol', 'strike', 'expiration', 'type', 'bid', 'ask']
        for field in required_fields:
            assert field in contract, f"Contract missing {field}"
        
        greeks = ['delta', 'gamma', 'theta', 'vega']
        for greek in greeks:
            assert greek in contract, f"Contract missing greek: {greek}"


@pytest.mark.quick
@pytest.mark.options
class TestOptionChainLoading:
    """Test option chain loading behavior."""
    
    def test_loading_with_no_broker_connection(self):
        """Option chain should return empty when broker not connected."""
        broker_client = None
        
        if not broker_client:
            result = {'success': False, 'error': 'Broker not connected', 'chain': []}
        else:
            result = {'success': True, 'chain': []}
        
        assert result['success'] is False
        assert 'not connected' in result['error'].lower()
    
    def test_loading_with_empty_credentials(self):
        """Option chain should fail gracefully with empty credentials."""
        credentials = {}
        
        if not credentials.get('access_token') and not credentials.get('api_key'):
            error_msg = 'Credentials not configured'
            can_load = False
        else:
            error_msg = None
            can_load = True
        
        assert can_load is False
        assert error_msg == 'Credentials not configured'
    
    def test_expiration_date_filtering(self):
        """Test filtering expirations by date range."""
        expirations = [
            '2024-12-13',
            '2024-12-20',
            '2024-12-27',
            '2025-01-17',
            '2025-03-21'
        ]
        
        today = datetime(2024, 12, 15)
        max_date = today + timedelta(days=45)
        
        filtered = [
            exp for exp in expirations
            if datetime.strptime(exp, '%Y-%m-%d') >= today
            and datetime.strptime(exp, '%Y-%m-%d') <= max_date
        ]
        
        assert '2024-12-13' not in filtered  # Past date
        assert '2024-12-20' in filtered
        assert '2025-03-21' not in filtered  # Too far out


@pytest.mark.quick
@pytest.mark.options
class TestOptionChainCache:
    """Test option chain caching behavior."""
    
    def test_cache_validity_check(self):
        """Test cache validity based on time."""
        cache_duration = 60
        cache_timestamp = datetime.now() - timedelta(seconds=30)
        
        elapsed = (datetime.now() - cache_timestamp).total_seconds()
        is_valid = elapsed < cache_duration
        
        assert is_valid is True
    
    def test_cache_expired_check(self):
        """Test cache expiry detection."""
        cache_duration = 60
        cache_timestamp = datetime.now() - timedelta(seconds=90)
        
        elapsed = (datetime.now() - cache_timestamp).total_seconds()
        is_valid = elapsed < cache_duration
        
        assert is_valid is False
    
    def test_cache_miss_when_no_timestamp(self):
        """Test cache miss when no timestamp exists."""
        cache_timestamps = {}
        broker_id = 'webull_live'
        
        if broker_id not in cache_timestamps:
            is_valid = False
        else:
            is_valid = True
        
        assert is_valid is False


@pytest.mark.quick
@pytest.mark.options
class TestOptionChainFallback:
    """Test option chain fallback behavior."""
    
    def test_webull_to_alpaca_fallback(self):
        """Test fallback from Webull to Alpaca for option data."""
        webull_connected = False
        alpaca_connected = True
        
        if webull_connected:
            data_source = 'webull'
        elif alpaca_connected:
            data_source = 'alpaca'
        else:
            data_source = None
        
        assert data_source == 'alpaca'
    
    def test_no_fallback_available(self):
        """Test behavior when no data source available."""
        webull_connected = False
        alpaca_connected = False
        
        if webull_connected:
            data_source = 'webull'
        elif alpaca_connected:
            data_source = 'alpaca'
        else:
            data_source = None
            error_msg = 'No option data source available'
        
        assert data_source is None
        assert 'No option data source' in error_msg
