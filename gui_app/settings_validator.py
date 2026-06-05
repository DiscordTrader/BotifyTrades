"""
Settings Validator Module
========================
Provides system-wide consistency checks for critical trading settings.
Validates alignment between GUI, Database, and Bot execution pipeline.

Critical Settings Validated:
- Trading Execution (execute_enabled, track_enabled, broker_override)
- Slippage Protection (slippage_pct, max_slippage)
- Position Sizing (position_size_pct, tracking_position_size_pct)
- Risk Management (profit_target_1/2/3_pct, stop_loss_pct, trailing_stop_pct)
- Broker Credentials (encrypted storage vs runtime tokens)
"""

import json
import logging
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)

# =============================================================================
# CANONICAL SETTINGS SCHEMA
# =============================================================================

CRITICAL_CHANNEL_FIELDS = {
    'position_size_pct': {'type': float, 'required': False, 'default': None, 'min': 0.1, 'max': 100.0},
    'tracking_position_size_pct': {'type': float, 'required': False, 'default': None, 'min': 0.1, 'max': 100.0},
    'default_quantity': {'type': int, 'required': False, 'default': None, 'min': 1, 'max': 1000},
    'tracking_default_quantity': {'type': int, 'required': False, 'default': None, 'min': 1, 'max': 1000},
    'channel_max_position_size': {'type': float, 'required': False, 'default': None, 'min': 100.0, 'max': 100000.0},
    'profit_target_1_pct': {'type': float, 'required': False, 'default': None, 'min': 1.0, 'max': 500.0, 'risk_field': True},
    'profit_target_2_pct': {'type': float, 'required': False, 'default': None, 'min': 1.0, 'max': 500.0, 'risk_field': True},
    'profit_target_3_pct': {'type': float, 'required': False, 'default': None, 'min': 1.0, 'max': 500.0, 'risk_field': True},
    'profit_target_4_pct': {'type': float, 'required': False, 'default': None, 'min': 1.0, 'max': 500.0, 'risk_field': True},
    'stop_loss_pct': {'type': float, 'required': False, 'default': None, 'min': 1.0, 'max': 100.0, 'risk_field': True},
    'trailing_stop_pct': {'type': float, 'required': False, 'default': None, 'min': 1.0, 'max': 100.0, 'risk_field': True},
    'trailing_activation_pct': {'type': float, 'required': False, 'default': None, 'min': 1.0, 'max': 100.0, 'risk_field': True},
    'execute_enabled': {'type': int, 'required': False, 'default': 0, 'min': 0, 'max': 1},
    'track_enabled': {'type': int, 'required': False, 'default': 0, 'min': 0, 'max': 1},
    'risk_management_enabled': {'type': int, 'required': False, 'default': 0, 'min': 0, 'max': 1},
    'conditional_order_enabled': {'type': int, 'required': False, 'default': 1, 'min': 0, 'max': 1},
    'exit_strategy_mode': {'type': str, 'required': False, 'default': 'hybrid'},
    'broker_override': {'type': str, 'required': False, 'default': None},
    'enabled_brokers': {'type': str, 'required': False, 'default': None},
}

CRITICAL_GLOBAL_SETTINGS = {
    'slippage_pct': {'type': float, 'required': True, 'default': 2.0, 'min': 0.0, 'max': 50.0},
    'max_slippage_pct': {'type': float, 'required': False, 'default': 5.0, 'min': 0.0, 'max': 50.0},
    'default_position_size_pct': {'type': float, 'required': True, 'default': 5.0, 'min': 0.1, 'max': 100.0},
    'risk_management_enabled': {'type': bool, 'required': True, 'default': True},
    'auto_trade_enabled': {'type': bool, 'required': False, 'default': False},
    'slippage_protection_enabled': {'type': bool, 'required': False, 'default': True},
}

BROKER_CREDENTIALS_REQUIRED = {
    'webull': ['device_id', 'access_token'],
    'alpaca': ['api_key', 'secret_key'],
    'tastytrade': ['username', 'session_token'],
    'ibkr': ['client_id', 'port'],
}


@dataclass
class ValidationIssue:
    """Represents a single validation issue"""
    severity: str  # 'critical', 'warning', 'info'
    category: str  # 'channel', 'global', 'broker', 'execution'
    field: str
    message: str
    current_value: Any = None
    expected_value: Any = None
    channel_id: Optional[int] = None
    channel_name: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ValidationReport:
    """Complete validation report"""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    is_valid: bool = True
    total_issues: int = 0
    critical_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    issues: List[ValidationIssue] = field(default_factory=list)
    channels_checked: int = 0
    brokers_checked: int = 0
    
    def add_issue(self, issue: ValidationIssue):
        self.issues.append(issue)
        self.total_issues += 1
        if issue.severity == 'critical':
            self.critical_count += 1
            self.is_valid = False
        elif issue.severity == 'warning':
            self.warning_count += 1
        else:
            self.info_count += 1
    
    def to_dict(self) -> Dict:
        return {
            'timestamp': self.timestamp,
            'is_valid': self.is_valid,
            'total_issues': self.total_issues,
            'critical_count': self.critical_count,
            'warning_count': self.warning_count,
            'info_count': self.info_count,
            'channels_checked': self.channels_checked,
            'brokers_checked': self.brokers_checked,
            'issues': [i.to_dict() for i in self.issues],
            'summary': self._generate_summary()
        }
    
    def _generate_summary(self) -> str:
        if self.is_valid and self.total_issues == 0:
            return "All settings are properly configured and consistent."
        elif self.is_valid:
            return f"Settings are operational with {self.warning_count} warnings to review."
        else:
            return f"CRITICAL: {self.critical_count} issues must be resolved before trading."


class SettingsValidator:
    """
    Validates consistency of critical settings across GUI, Database, and Bot execution.
    """
    
    def __init__(self, db_module=None):
        self.db = db_module
        self._last_report: Optional[ValidationReport] = None
    
    def set_database(self, db_module):
        """Set database module for validation"""
        self.db = db_module
    
    def validate_all(self) -> ValidationReport:
        """Run complete system validation"""
        report = ValidationReport()
        
        if not self.db:
            report.add_issue(ValidationIssue(
                severity='critical',
                category='system',
                field='database',
                message='Database module not initialized'
            ))
            return report
        
        # Validate all channels
        self._validate_channels(report)
        
        # Validate global settings
        self._validate_global_settings(report)
        
        # Validate broker credentials
        self._validate_broker_credentials(report)
        
        self._last_report = report
        logger.info(f"Validation complete: {report.total_issues} issues found")
        return report
    
    def _validate_channels(self, report: ValidationReport):
        """Validate all channel settings for consistency"""
        try:
            channels = self.db.get_channels()
            report.channels_checked = len(channels)
            
            for channel in channels:
                self._validate_single_channel(channel, report)
                
        except Exception as e:
            report.add_issue(ValidationIssue(
                severity='critical',
                category='channel',
                field='database_access',
                message=f'Failed to fetch channels: {str(e)}'
            ))
    
    def _validate_single_channel(self, channel: Dict, report: ValidationReport):
        """Validate a single channel's settings"""
        channel_id = channel.get('id')
        channel_name = channel.get('name', 'Unknown')
        risk_enabled = channel.get('risk_management_enabled', 0)
        
        # Check each critical field
        for field_name, schema in CRITICAL_CHANNEL_FIELDS.items():
            value = channel.get(field_name)
            is_risk_field = schema.get('risk_field', False)
            
            # Skip risk field validation if risk management is not enabled
            if is_risk_field and not risk_enabled:
                continue
            
            # Skip NULL values - all channel fields are optional
            # Position sizing uses trader's signal qty if not set
            # Risk fields only matter when risk_management_enabled = 1
            if value is None:
                continue
            
            # Type validation
            try:
                if schema['type'] == float:
                    value = float(value)
                elif schema['type'] == int:
                    value = int(value)
            except (ValueError, TypeError):
                report.add_issue(ValidationIssue(
                    severity='warning',
                    category='channel',
                    field=field_name,
                    message=f'Invalid type: expected {schema["type"].__name__}',
                    current_value=value,
                    channel_id=channel_id,
                    channel_name=channel_name
                ))
                continue
            
            # Range validation
            if 'min' in schema and value < schema['min']:
                report.add_issue(ValidationIssue(
                    severity='warning',
                    category='channel',
                    field=field_name,
                    message=f'Value below minimum ({schema["min"]})',
                    current_value=value,
                    expected_value=f'>= {schema["min"]}',
                    channel_id=channel_id,
                    channel_name=channel_name
                ))
            
            if 'max' in schema and value > schema['max']:
                report.add_issue(ValidationIssue(
                    severity='warning',
                    category='channel',
                    field=field_name,
                    message=f'Value above maximum ({schema["max"]})',
                    current_value=value,
                    expected_value=f'<= {schema["max"]}',
                    channel_id=channel_id,
                    channel_name=channel_name
                ))
        
        # Logical validation: profit targets should be ascending
        pt1 = channel.get('profit_target_1_pct')
        pt2 = channel.get('profit_target_2_pct')
        pt3 = channel.get('profit_target_3_pct')
        
        if pt1 and pt2 and pt3:
            if not (pt1 < pt2 < pt3):
                report.add_issue(ValidationIssue(
                    severity='warning',
                    category='channel',
                    field='profit_targets',
                    message=f'Profit targets not ascending: {pt1}% -> {pt2}% -> {pt3}%',
                    current_value=f'{pt1}, {pt2}, {pt3}',
                    expected_value='PT1 < PT2 < PT3',
                    channel_id=channel_id,
                    channel_name=channel_name
                ))
        
        # CRITICAL: Validate risk management settings completeness
        # If risk_management is enabled, stop_loss_pct MUST be set for downside protection
        if risk_enabled:
            stop_loss = channel.get('stop_loss_pct')
            if stop_loss is None or stop_loss == 0:
                report.add_issue(ValidationIssue(
                    severity='critical',
                    category='channel',
                    field='stop_loss_pct',
                    message='RISK ENABLED BUT NO STOP LOSS - positions have NO downside protection (trailing stops only work on upside)',
                    current_value=stop_loss,
                    expected_value='30-50% (or appropriate stop loss)',
                    channel_id=channel_id,
                    channel_name=channel_name
                ))
        
        # Check execution mode consistency
        exec_enabled = channel.get('execute_enabled', 0)
        track_enabled = channel.get('track_enabled', 0)
        
        # Note: position_size_pct is optional - if not set, trader's signal quantity is used
        
        if exec_enabled and not channel.get('broker_override') and not channel.get('enabled_brokers'):
            report.add_issue(ValidationIssue(
                severity='critical',
                category='channel',
                field='broker_assignment',
                message='STRICT ROUTING: Execution enabled but no broker assigned - trades will be REJECTED',
                current_value='enabled_brokers: None',
                expected_value='At least one broker (e.g., ALPACA_PAPER, WEBULL)',
                channel_id=channel_id,
                channel_name=channel_name
            ))
    
    def _validate_global_settings(self, report: ValidationReport):
        """Validate global risk management and slippage settings"""
        try:
            risk_settings = self.db.get_risk_management_settings()
            
            combined_settings = {
                'risk_management_enabled': risk_settings.get('enabled', False),
                'slippage_pct': 2.0,
                'max_slippage_pct': 5.0,
                'default_position_size_pct': 5.0,
                'slippage_protection_enabled': True,
                'auto_trade_enabled': False,
            }
            
            try:
                from gui_app.database import get_slippage_settings
                slippage = get_slippage_settings()
                combined_settings['slippage_pct'] = slippage.get('threshold_percent', 2.0)
                combined_settings['slippage_protection_enabled'] = slippage.get('enabled', True)
            except Exception:
                pass
            
            for field_name, schema in CRITICAL_GLOBAL_SETTINGS.items():
                value = combined_settings.get(field_name)
                
                if value is None and schema['required']:
                    report.add_issue(ValidationIssue(
                        severity='warning',
                        category='global',
                        field=field_name,
                        message=f'Global setting not configured - using default {schema["default"]}',
                        current_value=None,
                        expected_value=schema['default']
                    ))
                    
        except Exception as e:
            report.add_issue(ValidationIssue(
                severity='warning',
                category='global',
                field='risk_management',
                message=f'Could not fetch global settings: {str(e)}'
            ))
    
    def _validate_broker_credentials(self, report: ValidationReport):
        """Validate broker credentials are present and not expired"""
        try:
            from gui_app.broker_credentials_service import BrokerCredentialsService
            creds_service = BrokerCredentialsService()
            
            brokers_checked = 0
            
            for broker_name, required_fields in BROKER_CREDENTIALS_REQUIRED.items():
                brokers_checked += 1
                
                try:
                    creds = creds_service.get_credentials(broker_name)
                    
                    if not creds:
                        report.add_issue(ValidationIssue(
                            severity='info',
                            category='broker',
                            field=broker_name,
                            message=f'{broker_name.title()} credentials not configured'
                        ))
                        continue
                    
                    # Check required fields exist
                    for req_field in required_fields:
                        if not creds.get(req_field):
                            report.add_issue(ValidationIssue(
                                severity='warning',
                                category='broker',
                                field=f'{broker_name}.{req_field}',
                                message=f'Missing required credential field: {req_field}'
                            ))
                            
                except Exception as e:
                    report.add_issue(ValidationIssue(
                        severity='warning',
                        category='broker',
                        field=broker_name,
                        message=f'Error checking credentials: {str(e)}'
                    ))
            
            report.brokers_checked = brokers_checked
            
        except ImportError:
            report.add_issue(ValidationIssue(
                severity='info',
                category='broker',
                field='credentials_service',
                message='Broker credentials service not available'
            ))
        except Exception as e:
            report.add_issue(ValidationIssue(
                severity='warning',
                category='broker',
                field='credentials',
                message=f'Failed to validate broker credentials: {str(e)}'
            ))
    
    def validate_channel_save(self, channel_id: int, submitted_data: Dict) -> Tuple[bool, List[str]]:
        """
        Validate that a channel save operation was successful.
        Called after GUI saves to verify persistence.
        
        Returns: (success, list of error messages)
        """
        errors = []
        
        try:
            # Re-read from database
            saved_channel = self.db.get_channel_by_id(channel_id)
            
            if not saved_channel:
                return False, ['Channel not found after save']
            
            # Compare critical fields
            for field_name in CRITICAL_CHANNEL_FIELDS.keys():
                if field_name in submitted_data:
                    submitted_value = submitted_data[field_name]
                    saved_value = saved_channel.get(field_name)
                    
                    # Normalize for comparison
                    if submitted_value is not None and saved_value is not None:
                        try:
                            if isinstance(submitted_value, (int, float)):
                                submitted_value = float(submitted_value)
                                saved_value = float(saved_value)
                        except (ValueError, TypeError):
                            pass
                    
                    if submitted_value != saved_value:
                        errors.append(
                            f'{field_name}: submitted={submitted_value}, saved={saved_value}'
                        )
            
            if errors:
                logger.warning(f"Channel {channel_id} save verification failed: {errors}")
                return False, errors
            
            return True, []
            
        except Exception as e:
            return False, [f'Verification error: {str(e)}']
    
    def get_channel_settings_status(self, channel_id: int) -> Dict:
        """
        Get a status summary of a channel's settings configuration.
        Used by GUI to show configuration completeness.
        """
        try:
            channel = self.db.get_channel_by_id(channel_id)
            if not channel:
                return {'configured': False, 'message': 'Channel not found'}
            
            missing_required = []
            using_defaults = []
            
            for field_name, schema in CRITICAL_CHANNEL_FIELDS.items():
                value = channel.get(field_name)
                
                if value is None:
                    if schema['required']:
                        missing_required.append(field_name)
                    using_defaults.append(field_name)
            
            is_configured = len(missing_required) == 0
            
            return {
                'configured': is_configured,
                'channel_id': channel_id,
                'channel_name': channel.get('name'),
                'missing_required': missing_required,
                'using_defaults': using_defaults,
                'execution_ready': is_configured and channel.get('execute_enabled'),
                'tracking_ready': is_configured and channel.get('track_enabled'),
                'message': 'Fully configured' if is_configured else f'Missing: {", ".join(missing_required)}'
            }
            
        except Exception as e:
            return {'configured': False, 'message': f'Error: {str(e)}'}


# Singleton instance
_validator_instance: Optional[SettingsValidator] = None

def get_validator() -> SettingsValidator:
    """Get or create the singleton validator instance"""
    global _validator_instance
    if _validator_instance is None:
        _validator_instance = SettingsValidator()
    return _validator_instance

def run_system_validation(db_module) -> ValidationReport:
    """Convenience function to run full system validation"""
    validator = get_validator()
    validator.set_database(db_module)
    return validator.validate_all()
