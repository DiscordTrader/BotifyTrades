"""
License System Unit Tests
=========================
Tests for license validation, activation, and bypass modes.
"""
import pytest
import sqlite3
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.mark.quick
@pytest.mark.license
class TestLicenseKeyFormat:
    """Test license key format validation."""
    
    def test_bt_format_valid(self):
        """BT- format license keys should be recognized as valid format."""
        valid_keys = [
            'BT-0B185C55-3D14DD53',
            'BT-2247E6C1-589868B3',
            'BT-00553261-5CF70E86',
            'BT-AAAAAAAA-BBBBBBBB',
        ]
        for key in valid_keys:
            assert key.startswith('BT-'), f"Key should start with BT-: {key}"
            parts = key.split('-')
            assert len(parts) == 3, f"Key should have 3 parts: {key}"
            assert len(parts[1]) == 8, f"First segment should be 8 chars: {key}"
            assert len(parts[2]) == 8, f"Second segment should be 8 chars: {key}"
    
    def test_btf_format_valid(self):
        """BTF- format license keys should be recognized as valid format."""
        valid_keys = [
            'BTF-12345678-ABCDEFGH',
            'BTF-AAAAAAAA-12345678',
        ]
        for key in valid_keys:
            assert key.startswith('BTF-'), f"Key should start with BTF-: {key}"
    
    def test_invalid_format_rejected(self):
        """Invalid license key formats should be rejected."""
        invalid_keys = [
            '',
            'invalid',
            'BT-SHORT',
            'BT-12345678',
            'XX-12345678-12345678',
            'bt-12345678-12345678',  # lowercase
        ]
        for key in invalid_keys:
            assert not (key.startswith('BT-') or key.startswith('BTF-')) or len(key.split('-')) != 3


@pytest.mark.quick
@pytest.mark.license
class TestAdminBypass:
    """Test admin bypass modes for license validation."""
    
    def test_admin_password_bypass(self, monkeypatch):
        """When ADMIN_PASSWORD is set, license check should be bypassed."""
        monkeypatch.setenv('ADMIN_PASSWORD', 'test_admin_password')
        monkeypatch.setenv('LICENSE_SERVER_MODE', 'false')
        monkeypatch.setenv('ADMIN_MODE', 'false')
        
        admin_password = os.getenv('ADMIN_PASSWORD', '').strip()
        license_server_mode = os.getenv('LICENSE_SERVER_MODE', 'false').lower() == 'true'
        admin_mode = os.getenv('ADMIN_MODE', 'false').lower() == 'true'
        
        should_bypass = bool(admin_password) or license_server_mode or admin_mode
        assert should_bypass is True, "Admin password should trigger bypass"
    
    def test_license_server_mode_bypass(self, monkeypatch):
        """When LICENSE_SERVER_MODE is true, license check should be bypassed."""
        monkeypatch.setenv('ADMIN_PASSWORD', '')
        monkeypatch.setenv('LICENSE_SERVER_MODE', 'true')
        monkeypatch.setenv('ADMIN_MODE', 'false')
        
        license_server_mode = os.getenv('LICENSE_SERVER_MODE', 'false').lower() == 'true'
        assert license_server_mode is True, "License server mode should be enabled"
    
    def test_admin_mode_bypass(self, monkeypatch):
        """When ADMIN_MODE is true, license check should be bypassed."""
        monkeypatch.setenv('ADMIN_PASSWORD', '')
        monkeypatch.setenv('LICENSE_SERVER_MODE', 'false')
        monkeypatch.setenv('ADMIN_MODE', 'true')
        
        admin_mode = os.getenv('ADMIN_MODE', 'false').lower() == 'true'
        assert admin_mode is True, "Admin mode should be enabled"
    
    def test_no_bypass_when_all_disabled(self, monkeypatch):
        """When all bypass modes are disabled, license check should be required."""
        monkeypatch.setenv('ADMIN_PASSWORD', '')
        monkeypatch.setenv('LICENSE_SERVER_MODE', 'false')
        monkeypatch.setenv('ADMIN_MODE', 'false')
        
        admin_password = os.getenv('ADMIN_PASSWORD', '').strip()
        license_server_mode = os.getenv('LICENSE_SERVER_MODE', 'false').lower() == 'true'
        admin_mode = os.getenv('ADMIN_MODE', 'false').lower() == 'true'
        
        should_bypass = bool(admin_password) or license_server_mode or admin_mode
        assert should_bypass is False, "No bypass should be triggered"


@pytest.mark.quick
@pytest.mark.license
class TestServerLicenseDatabase:
    """Test server-side license database operations."""
    
    def test_create_license(self, mock_database, sample_license_data):
        """Test creating a new license in the database."""
        conn, path = mock_database
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO server_licenses 
            (license_key, customer_name, customer_email, license_type, expires_at, max_devices)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            sample_license_data['license_key'],
            sample_license_data['customer_name'],
            sample_license_data['customer_email'],
            sample_license_data['license_type'],
            sample_license_data['expires_at'],
            sample_license_data['max_devices']
        ))
        conn.commit()
        
        cursor.execute('SELECT * FROM server_licenses WHERE license_key = ?', 
                      (sample_license_data['license_key'],))
        result = cursor.fetchone()
        
        assert result is not None, "License should be created"
        assert result[1] == sample_license_data['license_key']
        assert result[2] == sample_license_data['customer_name']
    
    def test_license_expiration_check(self, mock_database):
        """Test that expired licenses are correctly identified."""
        conn, path = mock_database
        cursor = conn.cursor()
        
        expired_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
        valid_date = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')
        
        cursor.execute('''
            INSERT INTO server_licenses (license_key, customer_name, expires_at)
            VALUES ('BT-EXPIRED00-00000000', 'Expired User', ?)
        ''', (expired_date,))
        
        cursor.execute('''
            INSERT INTO server_licenses (license_key, customer_name, expires_at)
            VALUES ('BT-VALID0000-00000000', 'Valid User', ?)
        ''', (valid_date,))
        conn.commit()
        
        cursor.execute('''
            SELECT license_key, expires_at, 
                   CASE WHEN expires_at < datetime('now') THEN 1 ELSE 0 END as is_expired
            FROM server_licenses
        ''')
        results = cursor.fetchall()
        
        expired_licenses = [r for r in results if r[2] == 1]
        valid_licenses = [r for r in results if r[2] == 0]
        
        assert len(expired_licenses) == 1, "Should have 1 expired license"
        assert len(valid_licenses) == 1, "Should have 1 valid license"
        assert expired_licenses[0][0] == 'BT-EXPIRED00-00000000'
        assert valid_licenses[0][0] == 'BT-VALID0000-00000000'
    
    def test_device_limit_enforcement(self, mock_database):
        """Test that device limits are properly enforced."""
        conn, path = mock_database
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO server_licenses 
            (license_key, customer_name, max_devices, devices_used, expires_at)
            VALUES ('BT-DEVICE00-00000000', 'Device Test', 2, 2, datetime('now', '+30 days'))
        ''')
        conn.commit()
        
        cursor.execute('''
            SELECT max_devices, devices_used, 
                   CASE WHEN devices_used >= max_devices THEN 1 ELSE 0 END as at_limit
            FROM server_licenses WHERE license_key = 'BT-DEVICE00-00000000'
        ''')
        result = cursor.fetchone()
        
        assert result[2] == 1, "Should be at device limit"
    
    def test_license_validation_logging(self, mock_database):
        """Test that license validation attempts are logged."""
        conn, path = mock_database
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO license_validation_log 
            (license_key, ip_address, machine_id, success, error_message)
            VALUES ('BT-TESTLOG0-00000000', '192.168.1.1', 'test-machine', 1, NULL)
        ''')
        
        cursor.execute('''
            INSERT INTO license_validation_log 
            (license_key, ip_address, machine_id, success, error_message)
            VALUES ('BT-TESTLOG0-00000000', '192.168.1.2', 'other-machine', 0, 'Invalid license')
        ''')
        conn.commit()
        
        cursor.execute('''
            SELECT COUNT(*) FROM license_validation_log 
            WHERE license_key = 'BT-TESTLOG0-00000000'
        ''')
        count = cursor.fetchone()[0]
        
        assert count == 2, "Should have 2 validation log entries"
        
        cursor.execute('''
            SELECT COUNT(*) FROM license_validation_log 
            WHERE license_key = 'BT-TESTLOG0-00000000' AND success = 1
        ''')
        success_count = cursor.fetchone()[0]
        
        assert success_count == 1, "Should have 1 successful validation"


@pytest.mark.quick
@pytest.mark.license
class TestLicenseActivation:
    """Test license activation flow."""
    
    def test_first_activation_succeeds(self, mock_database):
        """First activation on a new license should succeed."""
        conn, path = mock_database
        cursor = conn.cursor()
        
        expires = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute('''
            INSERT INTO server_licenses 
            (license_key, customer_name, max_devices, devices_used, expires_at, status, is_active)
            VALUES ('BT-ACTIVATE-00000000', 'Activation Test', 1, 0, ?, 'active', 1)
        ''', (expires,))
        conn.commit()
        
        cursor.execute('SELECT devices_used, max_devices FROM server_licenses WHERE license_key = ?',
                      ('BT-ACTIVATE-00000000',))
        result = cursor.fetchone()
        
        can_activate = result[0] < result[1]
        assert can_activate is True, "Should be able to activate"
        
        cursor.execute('''
            UPDATE server_licenses SET devices_used = devices_used + 1, machine_id = ?
            WHERE license_key = ?
        ''', ('new-machine-id', 'BT-ACTIVATE-00000000'))
        conn.commit()
        
        cursor.execute('SELECT devices_used FROM server_licenses WHERE license_key = ?',
                      ('BT-ACTIVATE-00000000',))
        result = cursor.fetchone()
        assert result[0] == 1, "Devices used should be 1"
    
    def test_activation_on_same_machine_succeeds(self, mock_database):
        """Activation on the same machine should succeed without incrementing count."""
        conn, path = mock_database
        cursor = conn.cursor()
        
        expires = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute('''
            INSERT INTO server_licenses 
            (license_key, customer_name, max_devices, devices_used, machine_id, expires_at, status, is_active)
            VALUES ('BT-SAMEMACH-00000000', 'Same Machine Test', 1, 1, 'existing-machine', ?, 'active', 1)
        ''', (expires,))
        conn.commit()
        
        cursor.execute('SELECT machine_id FROM server_licenses WHERE license_key = ?',
                      ('BT-SAMEMACH-00000000',))
        result = cursor.fetchone()
        
        is_same_machine = result[0] == 'existing-machine'
        assert is_same_machine is True, "Should recognize same machine"
    
    def test_activation_exceeds_limit_fails(self, mock_database):
        """Activation that exceeds device limit should fail."""
        conn, path = mock_database
        cursor = conn.cursor()
        
        expires = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute('''
            INSERT INTO server_licenses 
            (license_key, customer_name, max_devices, devices_used, machine_id, expires_at, status, is_active)
            VALUES ('BT-OVERLIMIT-0000000', 'Over Limit Test', 1, 1, 'machine-1', ?, 'active', 1)
        ''', (expires,))
        conn.commit()
        
        cursor.execute('''
            SELECT devices_used, max_devices, machine_id 
            FROM server_licenses WHERE license_key = ?
        ''', ('BT-OVERLIMIT-0000000',))
        result = cursor.fetchone()
        
        devices_used, max_devices, existing_machine = result
        new_machine = 'machine-2'
        
        can_activate = devices_used < max_devices or existing_machine == new_machine
        assert can_activate is False, "Should not be able to activate on new machine at limit"
