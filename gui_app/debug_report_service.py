"""
Debug Report Service
Collects error logs, filters sensitive data, and sends reports to admin via email.
"""
import re
import os
import sys
import platform
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

from gui_app import database as db


SENSITIVE_PATTERNS = [
    (r'(api[_-]?key|secret[_-]?key|password|token|credential|access[_-]?token|refresh[_-]?token)\s*[:=]\s*[\'"]?[\w\-\.]+[\'"]?', '[REDACTED]'),
    (r'(ALPACA_API_KEY|ALPACA_SECRET_KEY|WEBULL_PASSWORD|WEBULL_TRADE_PIN|DISCORD_TOKEN|OPENAI_API_KEY|GMAIL_APP_PASSWORD|SMTP_PASSWORD)\s*[:=]\s*[^\s]+', '[REDACTED]'),
    (r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b', '[CARD REDACTED]'),
    (r'(buying[_\s]?power|cash[_\s]?balance|net[_\s]?liq|account[_\s]?value|balance|equity|portfolio[_\s]?value)\s*[:=]?\s*\$?[\d,]+\.?\d*', '[BALANCE REDACTED]'),
    (r'\$[\d,]+\.?\d{0,2}\b', '[AMOUNT REDACTED]'),
    (r'Account\s*#?:?\s*[\w\d\-]+', '[ACCOUNT REDACTED]'),
    (r'Account\s*ID:?\s*[\w\d\-]+', '[ACCOUNT ID REDACTED]'),
    (r'Token starts with[:\s]+[A-Za-z0-9]+\.{3}', '[TOKEN PREFIX REDACTED]'),
    (r'Token ends with[:\s]+\.{3}[A-Za-z0-9\-_]+', '[TOKEN SUFFIX REDACTED]'),
    (r'NDg5MjUxODk3ODIwMDUz[A-Za-z0-9\.\-_]+', '[DISCORD TOKEN REDACTED]'),
    (r'[A-Za-z0-9]{20,}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27}', '[DISCORD TOKEN REDACTED]'),
    (r'pk_live_[A-Za-z0-9]+', '[STRIPE KEY REDACTED]'),
    (r'sk_live_[A-Za-z0-9]+', '[STRIPE SECRET REDACTED]'),
    (r'pk_test_[A-Za-z0-9]+', '[STRIPE TEST KEY REDACTED]'),
    (r'sk_test_[A-Za-z0-9]+', '[STRIPE TEST SECRET REDACTED]'),
    (r'xoxb-[A-Za-z0-9\-]+', '[SLACK TOKEN REDACTED]'),
    (r'ghp_[A-Za-z0-9]+', '[GITHUB TOKEN REDACTED]'),
    (r'sk-[A-Za-z0-9]{48}', '[OPENAI KEY REDACTED]'),
    (r'[A-Z]{2,5}[0-9]{5,10}', '[BROKER ACCOUNT REDACTED]'),
    (r'user:\s*[^\s@]+@[^\s]+', '[EMAIL REDACTED]'),
    (r'email[:\s]+[^\s@]+@[^\s]+', '[EMAIL REDACTED]'),
    (r'DID:\s*[\w]+', '[DEVICE ID REDACTED]'),
    (r'machine[_\s]?id[:\s]+[\w\-]+', '[MACHINE ID REDACTED]'),
]


class DebugReportService:
    """Service for generating and sending debug reports."""
    
    def __init__(self, admin_email: str = None):
        self.admin_email = admin_email or os.getenv('ADMIN_EMAIL', 'admin@botifytrades.com')
    
    def filter_sensitive_data(self, text: str) -> str:
        """Remove sensitive information from text."""
        if not text:
            return text
        
        filtered = text
        for pattern, replacement in SENSITIVE_PATTERNS:
            filtered = re.sub(pattern, replacement, filtered, flags=re.IGNORECASE)
        
        return filtered
    
    def collect_error_logs(self, limit: int = 50) -> List[Dict]:
        """Collect recent error logs from database (errors only, no sensitive data)."""
        try:
            conn = db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT error_type, error_code, error_message, component, context,
                       stack_trace, severity, occurrence_count, first_seen, last_seen
                FROM error_logs
                WHERE severity IN ('error', 'critical')
                  AND resolved = 0
                ORDER BY last_seen DESC
                LIMIT ?
            ''', (limit,))
            
            errors = []
            for row in cursor.fetchall():
                error = dict(row)
                error['error_message'] = self.filter_sensitive_data(error.get('error_message', ''))
                error['context'] = self.filter_sensitive_data(error.get('context', ''))
                error['stack_trace'] = self.filter_sensitive_data(error.get('stack_trace', ''))
                errors.append(error)
            
            return errors
        except Exception as e:
            return [{'error': f'Failed to collect error logs: {e}'}]
    
    def collect_system_info(self) -> Dict[str, Any]:
        """Collect non-sensitive system information."""
        try:
            license_key = db.get_setting('license_key', '')
            if license_key and len(license_key) > 10:
                license_key = license_key[:8] + '...'
            
            return {
                'platform': platform.system(),
                'platform_version': platform.version()[:50] if platform.version() else 'Unknown',
                'python_version': sys.version.split()[0],
                'bot_version': 'DEV',
                'license_prefix': license_key,
                'timestamp': datetime.now().isoformat(),
                'debug_mode': db.get_setting('debug_mode', 'false'),
            }
        except Exception as e:
            return {'error': f'Failed to collect system info: {e}'}
    
    def collect_recent_console_errors(self) -> str:
        """Collect recent console errors from log files if available."""
        try:
            log_files = [
                '/tmp/logs/User_Trading_Bot_latest.log',
                'bot_errors.log',
                'error.log'
            ]
            
            errors_found = []
            for log_file in log_files:
                if os.path.exists(log_file):
                    try:
                        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                            lines = f.readlines()[-200:]
                            for line in lines:
                                line_lower = line.lower()
                                if 'error' in line_lower or 'exception' in line_lower or 'traceback' in line_lower or 'failed' in line_lower:
                                    errors_found.append(self.filter_sensitive_data(line.strip()))
                    except Exception:
                        pass
            
            if errors_found:
                return '\n'.join(errors_found[-100:])
            return 'No recent console errors found'
        except Exception as e:
            return f'Error collecting console logs: {e}'
    
    def generate_report(self, user_description: str = '') -> Tuple[str, Dict]:
        """
        Generate a complete debug report.
        
        Returns:
            Tuple of (reference_number, report_data)
        """
        reference_number = db.generate_debug_reference()
        
        error_logs = self.collect_error_logs()
        system_info = self.collect_system_info()
        console_errors = self.collect_recent_console_errors()
        
        report_data = {
            'reference_number': reference_number,
            'user_description': user_description,
            'error_logs': error_logs,
            'system_info': system_info,
            'console_errors': console_errors,
            'created_at': datetime.now().isoformat()
        }
        
        import json
        db.save_debug_report(
            reference_number=reference_number,
            user_description=user_description,
            error_logs=json.dumps(error_logs),
            system_info=json.dumps(system_info),
            admin_email=self.admin_email
        )
        
        return reference_number, report_data
    
    def format_email_body(self, report_data: Dict) -> str:
        """Format the debug report for email as plain text only."""
        ref = report_data.get('reference_number', 'Unknown')
        user_desc = report_data.get('user_description', 'No description provided')
        system_info = report_data.get('system_info', {})
        error_logs = report_data.get('error_logs', [])
        console_errors = report_data.get('console_errors', '')
        
        # Format error logs as readable text table
        error_section = ""
        if error_logs:
            error_section = f"ERROR LOGS ({len(error_logs)} errors)\n"
            error_section += "=" * 60 + "\n\n"
            for i, err in enumerate(error_logs[:30], 1):
                severity = err.get('severity', 'error').upper()
                component = err.get('component', 'Unknown')
                message = err.get('error_message', '')
                count = err.get('occurrence_count', 1)
                error_section += f"[{i}] {severity} - {component}\n"
                error_section += f"    Message: {message}\n"
                error_section += f"    Occurrences: {count}\n\n"
        else:
            error_section = "ERROR LOGS\n" + "=" * 60 + "\nNo database errors found.\n"
        
        text_body = f"""
================================================================================
                    BOTIFYTRADES DEBUG REPORT
================================================================================

REFERENCE NUMBER: {ref}
GENERATED: {report_data.get('created_at', 'Unknown')}

--------------------------------------------------------------------------------
USER DESCRIPTION
--------------------------------------------------------------------------------
{user_desc or 'No description provided'}

--------------------------------------------------------------------------------
SYSTEM INFORMATION
--------------------------------------------------------------------------------
Platform:      {system_info.get('platform', 'Unknown')}
Python:        {system_info.get('python_version', 'Unknown')}
Bot Version:   {system_info.get('bot_version', 'Unknown')}
License:       {system_info.get('license_prefix', '[FILTERED]')}
Debug Mode:    {system_info.get('debug_mode', 'Unknown')}

--------------------------------------------------------------------------------
{error_section}
--------------------------------------------------------------------------------
CONSOLE ERRORS
--------------------------------------------------------------------------------
{console_errors[:8000] if console_errors else 'No console errors captured.'}

================================================================================
This report was automatically generated by BotifyTrades.
Sensitive data (credentials, balances, account numbers) has been filtered.
================================================================================
"""
        
        return text_body
    
    async def send_report_email(self, report_data: Dict) -> Dict[str, Any]:
        """Send the debug report via email using Gmail service."""
        ref = report_data.get('reference_number', 'Unknown')
        print(f"[DEBUG-REPORT] Attempting to send report {ref} to {self.admin_email}")
        
        try:
            from src.services.gmail_service import get_gmail_service
            
            gmail = get_gmail_service()
            text_body = self.format_email_body(report_data)
            
            subject = f"BotifyTrades Debug Report - {ref}"
            
            print(f"[DEBUG-REPORT] Using Gmail connector to send email...")
            result = await gmail.send_email(
                to=self.admin_email,
                subject=subject,
                body=text_body
            )
            
            print(f"[DEBUG-REPORT] Gmail result: {result}")
            
            if result.get('success'):
                db.update_debug_report_sent(ref)
                return {
                    'success': True,
                    'reference_number': ref,
                    'message': f'Debug report sent successfully. Reference: {ref}'
                }
            else:
                print(f"[DEBUG-REPORT] Gmail failed, trying SMTP fallback...")
                return await self._send_via_smtp(report_data)
        except ImportError as e:
            print(f"[DEBUG-REPORT] Gmail service not available ({e}), trying SMTP...")
            return await self._send_via_smtp(report_data)
        except Exception as e:
            print(f"[DEBUG-REPORT] Gmail error ({e}), trying SMTP fallback...")
            return await self._send_via_smtp(report_data)
    
    async def _send_via_smtp(self, report_data: Dict) -> Dict[str, Any]:
        """Fallback to SMTP email if Gmail connector not available."""
        ref = report_data.get('reference_number', 'Unknown')
        print(f"[DEBUG-REPORT] Attempting SMTP fallback for {ref}")
        
        try:
            from gui_app.email_service import get_email_service
            
            email_service = get_email_service()
            if not email_service.is_configured():
                error_msg = 'Email service not configured. Please set SENDER_EMAIL and GMAIL_APP_PASSWORD in secrets.'
                print(f"[DEBUG-REPORT] SMTP not configured: {error_msg}")
                return {
                    'success': False,
                    'reference_number': ref,
                    'error': error_msg
                }
            
            text_body = self.format_email_body(report_data)
            
            print(f"[DEBUG-REPORT] Sending via SMTP to {self.admin_email}...")
            result = email_service._send_email(
                to_email=self.admin_email,
                subject=f"BotifyTrades Debug Report - {ref}",
                text_body=text_body
            )
            
            print(f"[DEBUG-REPORT] SMTP result: {result}")
            
            if result.get('success'):
                db.update_debug_report_sent(ref)
            
            return {
                'success': result.get('success', False),
                'reference_number': ref,
                'message': result.get('message', ''),
                'error': result.get('error', '')
            }
        except ImportError as e:
            error_msg = f'Email service module not available: {e}'
            print(f"[DEBUG-REPORT] {error_msg}")
            return {
                'success': False,
                'reference_number': ref,
                'error': error_msg
            }
        except Exception as e:
            error_msg = f'SMTP error: {e}'
            print(f"[DEBUG-REPORT] {error_msg}")
            return {
                'success': False,
                'reference_number': ref,
                'error': error_msg
            }


def get_debug_report_service(admin_email: str = None) -> DebugReportService:
    """Factory function to get debug report service instance."""
    return DebugReportService(admin_email)
