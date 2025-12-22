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
        self.admin_email = admin_email or os.getenv('ADMIN_EMAIL', 'uk15286@gmail.com')
    
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
                        with open(log_file, 'r', errors='ignore') as f:
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
    
    def format_email_body(self, report_data: Dict) -> Tuple[str, str]:
        """Format the debug report for email (text and HTML versions)."""
        import json
        
        ref = report_data.get('reference_number', 'Unknown')
        user_desc = report_data.get('user_description', 'No description provided')
        system_info = report_data.get('system_info', {})
        error_logs = report_data.get('error_logs', [])
        console_errors = report_data.get('console_errors', '')
        
        text_body = f"""
BotifyTrades Debug Report
========================
Reference: {ref}
Generated: {report_data.get('created_at', 'Unknown')}

USER DESCRIPTION:
{user_desc}

SYSTEM INFO:
Platform: {system_info.get('platform', 'Unknown')} {system_info.get('platform_version', '')}
Python: {system_info.get('python_version', 'Unknown')}
Bot Version: {system_info.get('bot_version', 'Unknown')}
License: {system_info.get('license_prefix', 'Unknown')}
Debug Mode: {system_info.get('debug_mode', 'Unknown')}

ERROR LOGS ({len(error_logs)} errors):
{json.dumps(error_logs, indent=2) if error_logs else 'No database errors found'}

CONSOLE ERRORS:
{console_errors[:5000] if console_errors else 'No console errors'}

---
This report was automatically generated by BotifyTrades.
Sensitive data (credentials, balances, account numbers) has been filtered.
"""
        
        error_rows = ''
        for err in error_logs[:20]:
            error_rows += f"""
            <tr>
                <td style="padding: 8px; border-bottom: 1px solid #333;">{err.get('severity', 'error').upper()}</td>
                <td style="padding: 8px; border-bottom: 1px solid #333;">{err.get('component', 'Unknown')}</td>
                <td style="padding: 8px; border-bottom: 1px solid #333;">{err.get('error_message', '')[:100]}</td>
                <td style="padding: 8px; border-bottom: 1px solid #333;">{err.get('occurrence_count', 1)}</td>
            </tr>
            """
        
        html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #0a1628; color: #e0e6ed; padding: 20px; }}
        .container {{ max-width: 800px; margin: 0 auto; background: #0d2a3a; border-radius: 12px; padding: 30px; border: 1px solid rgba(0, 212, 255, 0.3); }}
        h1 {{ color: #00d4ff; margin-bottom: 10px; }}
        .ref {{ font-family: monospace; background: rgba(0, 212, 255, 0.2); padding: 8px 16px; border-radius: 6px; font-size: 18px; display: inline-block; }}
        .section {{ margin: 25px 0; padding: 20px; background: rgba(0, 0, 0, 0.3); border-radius: 8px; }}
        .section h3 {{ color: #00ff88; margin-bottom: 15px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th {{ text-align: left; padding: 10px; background: rgba(0, 212, 255, 0.1); color: #00d4ff; }}
        pre {{ background: #000; padding: 15px; border-radius: 6px; overflow-x: auto; font-size: 12px; max-height: 300px; overflow-y: auto; }}
        .footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid rgba(0, 212, 255, 0.2); font-size: 12px; color: #6c757d; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🔧 Debug Report</h1>
        <p>Reference: <span class="ref">{ref}</span></p>
        <p style="color: #6c757d;">Generated: {report_data.get('created_at', 'Unknown')}</p>
        
        <div class="section">
            <h3>📝 User Description</h3>
            <p>{user_desc or 'No description provided'}</p>
        </div>
        
        <div class="section">
            <h3>💻 System Info</h3>
            <table>
                <tr><td style="padding: 5px; width: 150px;">Platform:</td><td>{system_info.get('platform', 'Unknown')} {system_info.get('platform_version', '')[:30]}</td></tr>
                <tr><td style="padding: 5px;">Python:</td><td>{system_info.get('python_version', 'Unknown')}</td></tr>
                <tr><td style="padding: 5px;">Bot Version:</td><td>{system_info.get('bot_version', 'Unknown')}</td></tr>
                <tr><td style="padding: 5px;">License:</td><td>{system_info.get('license_prefix', 'Unknown')}</td></tr>
                <tr><td style="padding: 5px;">Debug Mode:</td><td>{system_info.get('debug_mode', 'Unknown')}</td></tr>
            </table>
        </div>
        
        <div class="section">
            <h3>❌ Error Logs ({len(error_logs)} errors)</h3>
            <table>
                <tr>
                    <th>Severity</th>
                    <th>Component</th>
                    <th>Message</th>
                    <th>Count</th>
                </tr>
                {error_rows if error_rows else '<tr><td colspan="4" style="padding: 10px; text-align: center;">No database errors found</td></tr>'}
            </table>
        </div>
        
        <div class="section">
            <h3>📋 Console Errors</h3>
            <pre>{console_errors[:3000] if console_errors else 'No console errors'}</pre>
        </div>
        
        <div class="footer">
            <p>This report was automatically generated by BotifyTrades.</p>
            <p>⚠️ Sensitive data (credentials, balances, account numbers) has been automatically filtered.</p>
        </div>
    </div>
</body>
</html>
"""
        
        return text_body, html_body
    
    async def send_report_email(self, report_data: Dict) -> Dict[str, Any]:
        """Send the debug report via email using Gmail service."""
        try:
            from services.gmail_service import get_gmail_service
            
            gmail = get_gmail_service()
            text_body, html_body = self.format_email_body(report_data)
            
            ref = report_data.get('reference_number', 'Unknown')
            subject = f"🔧 BotifyTrades Debug Report - {ref}"
            
            result = await gmail.send_email(
                to=self.admin_email,
                subject=subject,
                body=text_body,
                html_body=html_body
            )
            
            if result.get('success'):
                db.update_debug_report_sent(ref)
                return {
                    'success': True,
                    'reference_number': ref,
                    'message': f'Debug report sent successfully. Reference: {ref}'
                }
            else:
                return {
                    'success': False,
                    'reference_number': ref,
                    'error': result.get('error', 'Failed to send email')
                }
        except ImportError:
            return await self._send_via_smtp(report_data)
        except Exception as e:
            return {
                'success': False,
                'reference_number': report_data.get('reference_number', 'Unknown'),
                'error': str(e)
            }
    
    async def _send_via_smtp(self, report_data: Dict) -> Dict[str, Any]:
        """Fallback to SMTP email if Gmail connector not available."""
        try:
            from gui_app.email_service import get_email_service
            
            email_service = get_email_service()
            if not email_service.is_configured():
                return {
                    'success': False,
                    'reference_number': report_data.get('reference_number', 'Unknown'),
                    'error': 'Email service not configured. Please set SENDER_EMAIL and GMAIL_APP_PASSWORD.'
                }
            
            text_body, html_body = self.format_email_body(report_data)
            ref = report_data.get('reference_number', 'Unknown')
            
            result = email_service._send_email(
                to_email=self.admin_email,
                subject=f"🔧 BotifyTrades Debug Report - {ref}",
                text_body=text_body,
                html_body=html_body
            )
            
            if result.get('success'):
                db.update_debug_report_sent(ref)
            
            return {
                'success': result.get('success', False),
                'reference_number': ref,
                'message': result.get('message', ''),
                'error': result.get('error', '')
            }
        except Exception as e:
            return {
                'success': False,
                'reference_number': report_data.get('reference_number', 'Unknown'),
                'error': str(e)
            }


def get_debug_report_service(admin_email: str = None) -> DebugReportService:
    """Factory function to get debug report service instance."""
    return DebugReportService(admin_email)
