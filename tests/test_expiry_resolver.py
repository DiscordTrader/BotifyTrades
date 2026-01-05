"""
Unit tests for ExpiryResolver service

Tests cover:
- Missing expiry -> picks next expiry
- Invalid expiry -> falls back correctly
- Weekly vs monthly -> automatically resolved via instrument master
- Futures month parsing
- Lot size from instrument master
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.expiry_resolver import (
    ExpiryResolver,
    ResolvedContract,
    resolve_instrument,
    get_next_expiry,
)


MOCK_UPSTOX_INSTRUMENTS = [
    {
        'instrument_key': 'NSE_FO|64934',
        'trading_symbol': 'NIFTY2610626300PE',
        'expiry': '2026-01-06',
        'strike_price': 26300,
        'instrument_type': 'PE',
        'lot_size': 25,
        'underlying_symbol': 'NIFTY',
    },
    {
        'instrument_key': 'NSE_FO|64935',
        'trading_symbol': 'NIFTY2610626300CE',
        'expiry': '2026-01-06',
        'strike_price': 26300,
        'instrument_type': 'CE',
        'lot_size': 25,
        'underlying_symbol': 'NIFTY',
    },
    {
        'instrument_key': 'NSE_FO|64940',
        'trading_symbol': 'NIFTY2611326300PE',
        'expiry': '2026-01-13',
        'strike_price': 26300,
        'instrument_type': 'PE',
        'lot_size': 25,
        'underlying_symbol': 'NIFTY',
    },
    {
        'instrument_key': 'NSE_FO|64945',
        'trading_symbol': 'NIFTY2612726300PE',
        'expiry': '2026-01-27',
        'strike_price': 26300,
        'instrument_type': 'PE',
        'lot_size': 25,
        'underlying_symbol': 'NIFTY',
    },
    {
        'instrument_key': 'NSE_FO|64950',
        'trading_symbol': 'NIFTY26JANFUT',
        'expiry': '2026-01-29',
        'strike_price': 0,
        'instrument_type': 'FUT',
        'lot_size': 25,
        'underlying_symbol': 'NIFTY',
    },
    {
        'instrument_key': 'NSE_FO|64960',
        'trading_symbol': 'NIFTY26FEBFUT',
        'expiry': '2026-02-26',
        'strike_price': 0,
        'instrument_type': 'FUT',
        'lot_size': 25,
        'underlying_symbol': 'NIFTY',
    },
]

MOCK_ZERODHA_INSTRUMENTS = [
    {
        'tradingsymbol': 'NIFTY2610626300PE',
        'name': 'NIFTY',
        'instrument_token': 12345678,
        'expiry': '2026-01-06',
        'strike': 26300.0,
        'instrument_type': 'PE',
        'lot_size': 25,
        'segment': 'NFO-OPT',
        'exchange': 'NFO',
    },
    {
        'tradingsymbol': 'NIFTY2610626300CE',
        'name': 'NIFTY',
        'instrument_token': 12345679,
        'expiry': '2026-01-06',
        'strike': 26300.0,
        'instrument_type': 'CE',
        'lot_size': 25,
        'segment': 'NFO-OPT',
        'exchange': 'NFO',
    },
    {
        'tradingsymbol': 'NIFTY2611326300PE',
        'name': 'NIFTY',
        'instrument_token': 12345680,
        'expiry': '2026-01-13',
        'strike': 26300.0,
        'instrument_type': 'PE',
        'lot_size': 25,
        'segment': 'NFO-OPT',
        'exchange': 'NFO',
    },
    {
        'tradingsymbol': 'NIFTY26JANFUT',
        'name': 'NIFTY',
        'instrument_token': 12345690,
        'expiry': '2026-01-29',
        'strike': 0,
        'instrument_type': 'FUT',
        'lot_size': 25,
        'segment': 'NFO-FUT',
        'exchange': 'NFO',
    },
]


@pytest.fixture
def resolver():
    """Create a fresh resolver instance with cleared cache"""
    ExpiryResolver._instance = None
    r = ExpiryResolver()
    r._caches.clear()
    return r


@pytest.fixture
def mock_upstox_api(resolver):
    """Mock Upstox API responses"""
    with patch.object(resolver, '_get_upstox_instruments', return_value=MOCK_UPSTOX_INSTRUMENTS):
        yield resolver


@pytest.fixture
def mock_zerodha_api(resolver):
    """Mock Zerodha API responses"""
    with patch.object(resolver, '_get_zerodha_instruments', return_value=MOCK_ZERODHA_INSTRUMENTS):
        yield resolver


class TestExpiryParsing:
    """Test expiry string parsing"""
    
    def test_parse_mm_dd(self, resolver):
        with patch.object(resolver, '_get_today', return_value=datetime(2026, 1, 5)):
            result = resolver._parse_expiry_string('01/06')
            assert result == datetime(2026, 1, 6)
    
    def test_parse_mm_dd_next_year(self, resolver):
        with patch.object(resolver, '_get_today', return_value=datetime(2026, 12, 15)):
            result = resolver._parse_expiry_string('01/06')
            assert result == datetime(2027, 1, 6)
    
    def test_parse_mm_dd_yy(self, resolver):
        result = resolver._parse_expiry_string('01/06/26')
        assert result == datetime(2026, 1, 6)
    
    def test_parse_yyyy_mm_dd(self, resolver):
        result = resolver._parse_expiry_string('2026-01-06')
        assert result == datetime(2026, 1, 6)
    
    def test_parse_dd_mmm_yy(self, resolver):
        result = resolver._parse_expiry_string('06-JAN-26')
        assert result == datetime(2026, 1, 6)
    
    def test_parse_ddmmmyy(self, resolver):
        result = resolver._parse_expiry_string('06JAN26')
        assert result == datetime(2026, 1, 6)
    
    def test_parse_month_code(self, resolver):
        with patch.object(resolver, '_get_today', return_value=datetime(2026, 1, 5)):
            result = resolver._parse_expiry_string('FEB')
            assert result.month == 2
            assert result.year == 2026
    
    def test_parse_invalid(self, resolver):
        result = resolver._parse_expiry_string('invalid')
        assert result is None


class TestSymbolNormalization:
    """Test symbol alias normalization"""
    
    def test_nifty50_alias(self, resolver):
        assert resolver._normalize_symbol('NIFTY50') == 'NIFTY'
    
    def test_bank_nifty_alias(self, resolver):
        assert resolver._normalize_symbol('BANK NIFTY') == 'BANKNIFTY'
    
    def test_lowercase(self, resolver):
        assert resolver._normalize_symbol('nifty') == 'NIFTY'


class TestOptionResolutionUpstox:
    """Test option resolution with Upstox"""
    
    def test_auto_pick_nearest_expiry(self, mock_upstox_api):
        with patch.object(mock_upstox_api, '_get_today', return_value=datetime(2026, 1, 5)):
            result = mock_upstox_api.resolve_option(
                underlying='NIFTY',
                strike=26300,
                option_type='PE',
                expiry=None,
                broker='upstox'
            )
            
            assert result is not None
            assert result.expiry_date == '2026-01-06'
            assert result.instrument_key == 'NSE_FO|64934'
            assert result.lot_size == 25
    
    def test_specific_expiry_match(self, mock_upstox_api):
        with patch.object(mock_upstox_api, '_get_today', return_value=datetime(2026, 1, 5)):
            result = mock_upstox_api.resolve_option(
                underlying='NIFTY',
                strike=26300,
                option_type='PE',
                expiry='01/13',
                broker='upstox'
            )
            
            assert result is not None
            assert result.expiry_date == '2026-01-13'
            assert result.instrument_key == 'NSE_FO|64940'
    
    def test_invalid_expiry_fallback(self, mock_upstox_api):
        with patch.object(mock_upstox_api, '_get_today', return_value=datetime(2026, 1, 5)):
            result = mock_upstox_api.resolve_option(
                underlying='NIFTY',
                strike=26300,
                option_type='PE',
                expiry='01/99',
                broker='upstox'
            )
            
            assert result is not None
            assert result.expiry_date == '2026-01-06'
    
    def test_ce_option_type(self, mock_upstox_api):
        with patch.object(mock_upstox_api, '_get_today', return_value=datetime(2026, 1, 5)):
            result = mock_upstox_api.resolve_option(
                underlying='NIFTY',
                strike=26300,
                option_type='CE',
                expiry=None,
                broker='upstox'
            )
            
            assert result is not None
            assert result.option_type == 'CE'
            assert result.instrument_key == 'NSE_FO|64935'
    
    def test_no_matching_strike(self, mock_upstox_api):
        with patch.object(mock_upstox_api, '_get_today', return_value=datetime(2026, 1, 5)):
            result = mock_upstox_api.resolve_option(
                underlying='NIFTY',
                strike=99999,
                option_type='PE',
                expiry=None,
                broker='upstox'
            )
            
            assert result is None


class TestOptionResolutionZerodha:
    """Test option resolution with Zerodha"""
    
    def test_auto_pick_nearest_expiry(self, mock_zerodha_api):
        with patch.object(mock_zerodha_api, '_get_today', return_value=datetime(2026, 1, 5)):
            result = mock_zerodha_api.resolve_option(
                underlying='NIFTY',
                strike=26300,
                option_type='PE',
                expiry=None,
                broker='zerodha'
            )
            
            assert result is not None
            assert result.expiry_date == '2026-01-06'
            assert result.instrument_token == 12345678
            assert result.lot_size == 25


class TestFuturesResolution:
    """Test futures resolution"""
    
    def test_auto_pick_nearest_future(self, mock_upstox_api):
        with patch.object(mock_upstox_api, '_get_today', return_value=datetime(2026, 1, 5)):
            result = mock_upstox_api.resolve_future(
                underlying='NIFTY',
                expiry=None,
                broker='upstox'
            )
            
            assert result is not None
            assert result.expiry_date == '2026-01-29'
            assert result.instrument_type == 'FUT'
    
    def test_month_code_future(self, mock_upstox_api):
        with patch.object(mock_upstox_api, '_get_today', return_value=datetime(2026, 1, 5)):
            result = mock_upstox_api.resolve_future(
                underlying='NIFTY',
                expiry='FEB',
                broker='upstox'
            )
            
            assert result is not None
            assert result.expiry_date == '2026-02-26'


class TestLotSize:
    """Test lot size extraction from instrument master"""
    
    def test_lot_size_from_instrument(self, mock_upstox_api):
        with patch.object(mock_upstox_api, '_get_today', return_value=datetime(2026, 1, 5)):
            result = mock_upstox_api.resolve_option(
                underlying='NIFTY',
                strike=26300,
                option_type='PE',
                broker='upstox'
            )
            
            assert result.lot_size == 25


class TestConvenienceFunctions:
    """Test convenience wrapper functions"""
    
    def test_resolve_instrument_option(self, mock_upstox_api):
        with patch('src.services.expiry_resolver.expiry_resolver', mock_upstox_api):
            with patch.object(mock_upstox_api, '_get_today', return_value=datetime(2026, 1, 5)):
                signal = {
                    'symbol': 'NIFTY',
                    'strike': 26300,
                    'opt_type': 'PE',
                    'asset': 'option',
                }
                
                result = resolve_instrument(signal, broker='upstox')
                assert result is not None
                assert result.expiry_date == '2026-01-06'
    
    def test_resolve_instrument_future(self, mock_upstox_api):
        with patch('src.services.expiry_resolver.expiry_resolver', mock_upstox_api):
            with patch.object(mock_upstox_api, '_get_today', return_value=datetime(2026, 1, 5)):
                signal = {
                    'symbol': 'NIFTY',
                    'asset': 'future',
                    'instrument_type': 'FUT',
                }
                
                result = resolve_instrument(signal, broker='upstox')
                assert result is not None
                assert result.instrument_type == 'FUT'


class TestAvailableExpiries:
    """Test getting available expiries"""
    
    def test_get_available_expiries(self, mock_upstox_api):
        with patch.object(mock_upstox_api, '_get_today', return_value=datetime(2026, 1, 5)):
            expiries = mock_upstox_api.get_available_expiries('NIFTY', 'upstox')
            
            assert len(expiries) > 0
            assert '2026-01-06' in expiries
            assert '2026-01-13' in expiries


class TestCacheManagement:
    """Test cache functionality"""
    
    def test_cache_stats(self, resolver):
        stats = resolver.get_cache_stats()
        assert isinstance(stats, dict)
    
    def test_refresh_cache(self, resolver):
        resolver.refresh_cache()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
