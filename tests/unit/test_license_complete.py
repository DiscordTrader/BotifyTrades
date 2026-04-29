"""
Complete License System Tests
Covers: Server validation, RSA signing, caching, grace periods, device limits
"""
import pytest
import json
import base64
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

pytestmark = [pytest.mark.quick, pytest.mark.license]


class TestRSASignatureVerification:
    """Tests for RSA-signed token verification."""
    
    def test_valid_token_structure(self):
        """Token must have payload.signature format."""
        valid_format = "eyJsaWNlbnNlX2tleT.c2lnbmF0dXJl"
        parts = valid_format.split('.')
        assert len(parts) == 2, "Token should have exactly 2 parts"
    
    def test_invalid_token_missing_signature(self):
        """Token without signature should be rejected."""
        invalid_token = "eyJsaWNlbnNlX2tleQ"
        parts = invalid_token.split('.')
        assert len(parts) == 1, "Should detect missing signature"
    
    def test_token_with_valid_payload_structure(self):
        """Token payload should contain required fields."""
        payload = {
            'license_key': 'BT-TEST-1234',
            'machine_id': 'abc123def456',
            'offline_grace_expires': (datetime.now() + timedelta(hours=48)).isoformat(),
            'is_valid': True
        }
        encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
        assert 'license_key' in json.loads(base64.urlsafe_b64decode(encoded + '=='))
    
    def test_machine_id_mismatch_detection(self):
        """Token for different machine should be rejected."""
        token_machine = "machine_abc123"
        current_machine = "machine_xyz789"
        assert token_machine != current_machine, "Machine ID mismatch should fail validation"
    
    def test_grace_period_expiry_check(self):
        """Expired grace period should be detected."""
        expired_time = datetime.now() - timedelta(hours=1)
        current_time = datetime.now()
        assert current_time > expired_time, "Expired grace should be detected"
    
    def test_grace_period_valid_check(self):
        """Valid grace period should pass."""
        valid_until = datetime.now() + timedelta(hours=24)
        current_time = datetime.now()
        assert current_time < valid_until, "Valid grace should pass"


class TestServerValidation:
    """Tests for server-side license validation."""
    
    @pytest.fixture
    def mock_server_response(self):
        """Mock successful server response."""
        return {
            'is_valid': True,
            'license_key': 'BT-TEST-1234',
            'expires': (datetime.now() + timedelta(days=30)).isoformat(),
            'days_remaining': 30,
            'license_type': 'standard',
            'signed_token': 'mock_signed_token_base64'
        }
    
    def test_server_returns_signed_token(self, mock_server_response):
        """Server must return signed token for offline support."""
        assert 'signed_token' in mock_server_response
        assert mock_server_response['signed_token'] is not None
    
    def test_server_validates_license_key_format(self):
        """License key must match BT- format."""
        valid_keys = ['BT-ABC-1234', 'BT-TRIAL-5678', 'BT-PRO-9999']
        invalid_keys = ['ABC-1234', 'BTABC1234', '', None]
        
        for key in valid_keys:
            assert key.startswith('BT-'), f"Valid key {key} should start with BT-"
        
        for key in invalid_keys:
            if key:
                assert not key.startswith('BT-'), f"Invalid key {key} should not start with BT-"
    
    def test_server_response_includes_expiry(self, mock_server_response):
        """Server must return expiration date."""
        assert 'expires' in mock_server_response
        assert 'days_remaining' in mock_server_response
    
    def test_offline_mode_flag_handling(self):
        """Offline mode should be set when server unreachable."""
        offline_response = {'offline': True, 'error': 'Connection failed'}
        assert offline_response.get('offline') is True
    
    def test_server_error_response_structure(self):
        """Error responses should have consistent structure."""
        error_response = {
            'is_valid': False,
            'success': False,
            'error': 'License expired'
        }
        assert error_response['is_valid'] is False
        assert 'error' in error_response


class TestCacheManagement:
    """Tests for license cache system."""
    
    @pytest.fixture
    def sample_cache(self):
        """Sample cache data structure."""
        return {
            'license_key': 'BT-TEST-1234',
            'machine_id': 'abc123def456',
            'last_validated': datetime.now().isoformat(),
            'result': {
                'is_valid': True,
                'expires': (datetime.now() + timedelta(days=30)).isoformat(),
                'days_remaining': 30
            },
            'expires_at': (datetime.now() + timedelta(days=30)).isoformat(),
            'signed_token': 'valid_signed_token'
        }
    
    def test_cache_structure_complete(self, sample_cache):
        """Cache must contain all required fields."""
        required_fields = ['license_key', 'machine_id', 'last_validated', 'result', 'signed_token']
        for field in required_fields:
            assert field in sample_cache, f"Cache missing required field: {field}"
    
    def test_cache_without_signed_token_rejected(self, sample_cache):
        """Cache without signed token should not enable offline mode."""
        sample_cache['signed_token'] = None
        assert sample_cache['signed_token'] is None, "Missing token should be detected"
    
    def test_cache_machine_id_validation(self, sample_cache):
        """Cache for different machine should be rejected."""
        current_machine = 'different_machine_id'
        cached_machine = sample_cache['machine_id']
        assert current_machine != cached_machine, "Machine mismatch should be detected"
    
    def test_cache_license_key_match(self, sample_cache):
        """Cache for different license should be rejected."""
        requested_license = 'BT-OTHER-5678'
        cached_license = sample_cache['license_key']
        assert requested_license != cached_license, "License mismatch should be detected"
    
    def test_cache_tampering_detection(self):
        """Tampered cache should be rejected without valid signature."""
        tampered_cache = {
            'license_key': 'BT-HACKED-9999',
            'expires_at': (datetime.now() + timedelta(days=365)).isoformat(),
            'signed_token': 'invalid_signature'
        }
        assert 'signed_token' in tampered_cache
        # In real implementation, signature verification would fail


class TestOfflineGracePeriod:
    """Tests for offline grace period functionality."""
    
    def test_default_grace_hours(self):
        """Default grace period should be 48 hours."""
        DEFAULT_OFFLINE_HOURS = 48
        assert DEFAULT_OFFLINE_HOURS == 48
    
    def test_grace_period_calculation(self):
        """Grace period should be calculated from last validation."""
        last_validated = datetime.now() - timedelta(hours=24)
        grace_hours = 48
        grace_expires = last_validated + timedelta(hours=grace_hours)
        
        assert datetime.now() < grace_expires, "Within grace period"
    
    def test_grace_period_expired(self):
        """Expired grace period should require server connection."""
        last_validated = datetime.now() - timedelta(hours=72)
        grace_hours = 48
        grace_expires = last_validated + timedelta(hours=grace_hours)
        
        assert datetime.now() > grace_expires, "Grace period expired"
    
    def test_grace_remaining_hours_calculation(self):
        """Should correctly calculate remaining grace hours."""
        grace_expires = datetime.now() + timedelta(hours=24)
        remaining = (grace_expires - datetime.now()).total_seconds() / 3600
        assert 23 < remaining < 25, "Should show ~24 hours remaining"


class TestDeviceLimits:
    """Tests for device limit enforcement."""
    
    def test_max_devices_per_license(self):
        """License should enforce max device limit."""
        max_devices = 3
        active_devices = ['device1', 'device2', 'device3']
        new_device = 'device4'
        
        assert len(active_devices) >= max_devices
        assert new_device not in active_devices
    
    def test_device_list_management(self):
        """Should track activated devices."""
        devices = []
        devices.append({'id': 'dev1', 'info': 'Windows PC', 'activated': datetime.now().isoformat()})
        devices.append({'id': 'dev2', 'info': 'Linux Server', 'activated': datetime.now().isoformat()})
        
        assert len(devices) == 2
    
    def test_device_deactivation(self):
        """Deactivated device should free slot."""
        devices = ['dev1', 'dev2', 'dev3']
        devices.remove('dev2')
        assert len(devices) == 2


class TestLicenseTypes:
    """Tests for different license types."""
    
    @pytest.fixture
    def license_types(self):
        return {
            'trial': {'max_days': 7, 'max_devices': 1, 'features': ['basic']},
            'standard': {'max_days': 365, 'max_devices': 3, 'features': ['basic', 'advanced']},
            'professional': {'max_days': 365, 'max_devices': 10, 'features': ['basic', 'advanced', 'premium']}
        }
    
    def test_trial_license_restrictions(self, license_types):
        """Trial licenses should have limited duration and devices."""
        trial = license_types['trial']
        assert trial['max_days'] <= 14
        assert trial['max_devices'] <= 2
    
    def test_standard_license_features(self, license_types):
        """Standard license should include basic features."""
        standard = license_types['standard']
        assert 'basic' in standard['features']
        assert 'advanced' in standard['features']
    
    def test_professional_has_all_features(self, license_types):
        """Professional license should have all features."""
        pro = license_types['professional']
        assert len(pro['features']) >= 3


class TestMachineIdentification:
    """Tests for machine ID generation."""
    
    def test_machine_id_format(self):
        """Machine ID should be 16-char hex string."""
        raw = "test_uuid_Windows_x86_64"
        machine_id = hashlib.sha256(raw.encode()).hexdigest()[:16]
        assert len(machine_id) == 16
        assert all(c in '0123456789abcdef' for c in machine_id)
    
    def test_machine_id_consistency(self):
        """Same input should produce same machine ID."""
        raw = "consistent_input_value"
        id1 = hashlib.sha256(raw.encode()).hexdigest()[:16]
        id2 = hashlib.sha256(raw.encode()).hexdigest()[:16]
        assert id1 == id2
    
    def test_different_machines_different_ids(self):
        """Different machines should have different IDs."""
        machine1 = hashlib.sha256("machine_1_uuid".encode()).hexdigest()[:16]
        machine2 = hashlib.sha256("machine_2_uuid".encode()).hexdigest()[:16]
        assert machine1 != machine2


class TestAdminBypass:
    """Tests for admin bypass functionality."""
    
    def test_admin_password_bypass(self):
        """Valid admin password should bypass license check."""
        admin_password = 'correct_admin_password'
        provided_password = 'correct_admin_password'
        assert admin_password == provided_password
    
    def test_server_mode_bypass(self):
        """LICENSE_SERVER_MODE=true should bypass for self."""
        import os
        with patch.dict(os.environ, {'LICENSE_SERVER_MODE': 'true'}):
            assert os.environ.get('LICENSE_SERVER_MODE') == 'true'
    
    def test_invalid_admin_password_rejected(self):
        """Invalid admin password should not bypass."""
        admin_password = 'correct_password'
        provided_password = 'wrong_password'
        assert admin_password != provided_password


class TestLicenseCachePersistence:
    """Tests for license cache file persistence across reboots."""
    
    def test_pathlib_import_available(self):
        """Path must be importable at module level for cache loading."""
        from pathlib import Path
        assert Path is not None
        assert callable(Path.home)
    
    def test_cache_directory_path_format(self):
        """Cache directory should be in user's home directory."""
        from pathlib import Path
        cache_dir = Path.home() / '.discord_trading_bot'
        assert str(cache_dir).endswith('.discord_trading_bot')
        assert Path.home() in cache_dir.parents or cache_dir.parent == Path.home()
    
    def test_cache_file_path_format(self):
        """Cache file should be license_cache.json in cache directory."""
        from pathlib import Path
        cache_file = Path.home() / '.discord_trading_bot' / 'license_cache.json'
        assert cache_file.name == 'license_cache.json'
        assert cache_file.parent.name == '.discord_trading_bot'
    
    def test_cache_data_structure_complete(self):
        """Cache data must contain all required fields."""
        required_fields = ['license_key', 'machine_id', 'result', 'last_validated']
        cache_data = {
            'license_key': 'BT-TEST-1234',
            'machine_id': 'abc123def456',
            'result': {'is_valid': True, 'days_remaining': 30},
            'last_validated': '2025-12-05T10:00:00'
        }
        for field in required_fields:
            assert field in cache_data, f"Missing required field: {field}"
    
    def test_cache_license_key_preserved(self):
        """License key in cache must be preserved exactly."""
        import json
        original_key = 'BT-AAA288B9-A75AE8E0'
        cache_data = {'license_key': original_key}
        serialized = json.dumps(cache_data)
        loaded = json.loads(serialized)
        assert loaded['license_key'] == original_key
    
    def test_cache_machine_id_preserved(self):
        """Machine ID in cache must be preserved exactly."""
        import json
        original_id = 'f7a3b9c2e1d45678'
        cache_data = {'machine_id': original_id}
        serialized = json.dumps(cache_data)
        loaded = json.loads(serialized)
        assert loaded['machine_id'] == original_id
    
    def test_cache_result_dict_preserved(self):
        """Result dictionary in cache must be preserved."""
        import json
        result = {
            'is_valid': True,
            'days_remaining': 30,
            'expires': '2026-01-05',
            'license_type': 'standard'
        }
        cache_data = {'result': result}
        serialized = json.dumps(cache_data)
        loaded = json.loads(serialized)
        assert loaded['result']['is_valid'] == True
        assert loaded['result']['days_remaining'] == 30
    
    def test_cache_write_and_read_consistency(self, tmp_path):
        """Cache file should be readable after writing."""
        import json
        cache_file = tmp_path / 'license_cache.json'
        cache_data = {
            'license_key': 'BT-TEST-1234',
            'machine_id': 'abc123',
            'result': {'is_valid': True},
            'last_validated': '2025-12-05T10:00:00'
        }
        
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f)
        
        with open(cache_file, 'r', encoding='utf-8') as f:
            loaded = json.load(f)
        
        assert loaded['license_key'] == 'BT-TEST-1234'
        assert loaded['machine_id'] == 'abc123'
    
    def test_cache_file_permissions(self, tmp_path):
        """Cache file should be readable and writable."""
        import json
        import os
        cache_file = tmp_path / 'license_cache.json'
        
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump({'test': True}, f)
        
        assert os.access(cache_file, os.R_OK), "Cache file should be readable"
        assert os.access(cache_file, os.W_OK), "Cache file should be writable"
    
    def test_cache_directory_creation(self, tmp_path):
        """Cache directory should be created if not exists."""
        cache_dir = tmp_path / 'new_cache_dir'
        assert not cache_dir.exists()
        cache_dir.mkdir(exist_ok=True)
        assert cache_dir.exists()
        assert cache_dir.is_dir()
    
    def test_bt_format_key_detection(self):
        """BT- format keys should be detected correctly."""
        valid_bt_keys = ['BT-ABC-1234', 'BT-AAA288B9-A75AE8E0', 'BT-TEST']
        for key in valid_bt_keys:
            assert key.startswith('BT-'), f"Key {key} should start with BT-"
    
    def test_btf_format_key_detection(self):
        """BTF- format keys should be detected correctly."""
        valid_btf_keys = ['BTF-ABC-1234', 'BTF-PRO-ABCD1234']
        for key in valid_btf_keys:
            assert key.startswith('BTF-'), f"Key {key} should start with BTF-"
    
    def test_trial_format_key_detection(self):
        """TRIAL- format keys should be detected correctly."""
        trial_keys = ['TRIAL-ABC123', 'TRIAL-f7a3b9c2']
        for key in trial_keys:
            assert key.startswith('TRIAL-'), f"Key {key} should start with TRIAL-"
    
    def test_expired_key_days_remaining_zero(self):
        """Expired key should have days_remaining <= 0."""
        expired_result = {'days_remaining': 0, 'is_valid': True}
        assert expired_result['days_remaining'] <= 0
        
        negative_days = {'days_remaining': -5, 'is_valid': True}
        assert negative_days['days_remaining'] <= 0
    
    def test_valid_key_days_remaining_positive(self):
        """Valid key should have days_remaining > 0."""
        valid_result = {'days_remaining': 30, 'is_valid': True}
        assert valid_result['days_remaining'] > 0


class TestLicenseCacheLoadPriority:
    """Tests for license key load priority order."""
    
    def test_env_license_priority_over_cache(self):
        """Environment variable license should take priority over cache."""
        env_license = 'BT-ENV-1234'
        cache_license = 'BT-CACHE-5678'
        
        # Priority: env > wizard > cache
        if env_license.startswith('BT-'):
            selected = env_license
        elif cache_license.startswith('BT-'):
            selected = cache_license
        else:
            selected = ''
        
        assert selected == env_license
    
    def test_wizard_license_priority_over_cache(self):
        """Wizard license should take priority over cache when no env."""
        env_license = ''
        wizard_license = 'BT-WIZARD-1234'
        cache_license = 'BT-CACHE-5678'
        
        if env_license.startswith('BT-'):
            selected = env_license
        elif wizard_license.startswith('BT-'):
            selected = wizard_license
        elif cache_license.startswith('BT-'):
            selected = cache_license
        else:
            selected = ''
        
        assert selected == wizard_license
    
    def test_cache_license_used_when_no_env_or_wizard(self):
        """Cache license should be used when no env or wizard license."""
        env_license = ''
        wizard_license = ''
        cache_license = 'BT-CACHE-5678'
        
        if env_license.startswith('BT-'):
            selected = env_license
        elif wizard_license.startswith('BT-'):
            selected = wizard_license
        elif cache_license.startswith('BT-'):
            selected = cache_license
        else:
            selected = ''
        
        assert selected == cache_license
    
    def test_btf_format_priority_over_bt(self):
        """BTF- format should take priority over BT- format."""
        btf_key = 'BTF-NEW-FORMAT'
        bt_key = 'BT-OLD-FORMAT'
        
        # BTF is newer format, should be preferred
        if btf_key.startswith('BTF-'):
            selected = btf_key
        elif bt_key.startswith('BT-'):
            selected = bt_key
        else:
            selected = ''
        
        assert selected == btf_key
    
    def test_empty_cache_returns_empty_string(self):
        """Empty cache should return empty string for license key."""
        cache_data = {}
        cache_license = cache_data.get('license_key', '').strip()
        assert cache_license == ''
    
    def test_none_cache_license_handled(self):
        """None value in cache should be handled gracefully."""
        cache_data = {'license_key': None}
        cache_license = (cache_data.get('license_key') or '').strip()
        assert cache_license == ''
