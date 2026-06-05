"""
Email Service for Password Recovery and Notifications
Supports Gmail and SMTP
"""
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, Dict
from datetime import datetime


class EmailService:
    """Email service for sending password recovery and notification emails"""
    
    def __init__(self):
        """Initialize email service with Gmail or SMTP configuration"""
        self.provider = os.environ.get('EMAIL_PROVIDER', 'gmail').lower()
        self.sender_email = os.environ.get('SENDER_EMAIL', '')
        self.sender_name = os.environ.get('SENDER_NAME', 'BotifyTrades')
        
        if self.provider == 'gmail':
            self.smtp_host = 'smtp.gmail.com'
            self.smtp_port = 587
            self.sender_password = os.environ.get('GMAIL_APP_PASSWORD', '')
        else:
            self.smtp_host = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
            self.smtp_port = int(os.environ.get('SMTP_PORT', '587'))
            self.sender_password = os.environ.get('SMTP_PASSWORD', '')
    
    def is_configured(self) -> bool:
        """Check if email service is properly configured"""
        return bool(self.sender_email and self.sender_password)
    
    def send_password_reset_email(self, to_email: str, username: str, reset_token: str,
                                  base_url: str = None) -> Dict:
        """
        Send password reset email with recovery link
        
        Args:
            to_email: Recipient email address
            username: Username of the account
            reset_token: Password reset token
            base_url: Application base URL for the reset link
        
        Returns:
            Dict with 'success' and 'error' keys
        """
        if not self.is_configured():
            return {'success': False, 'error': 'Email service not configured'}

        if base_url is None:
            import os as _os
            _port = _os.environ.get('GUI_PORT', '5000')
            base_url = f'http://localhost:{_port}'

        try:
            reset_link = f"{base_url}/reset-password/{reset_token}"
            
            subject = "BotifyTrades - Password Reset Request"
            html_body = f"""
            <html>
                <head>
                    <style>
                        body {{ font-family: Arial, sans-serif; color: #333; }}
                        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                        .header {{ background: linear-gradient(135deg, #00d4ff 0%, #00ff88 100%); color: #000; padding: 20px; border-radius: 10px 10px 0 0; text-align: center; }}
                        .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
                        .button {{ display: inline-block; background: linear-gradient(135deg, #00d4ff 0%, #00ff88 100%); color: #000; padding: 12px 30px; text-decoration: none; border-radius: 6px; font-weight: bold; margin: 20px 0; }}
                        .footer {{ color: #666; font-size: 12px; margin-top: 20px; padding-top: 20px; border-top: 1px solid #ddd; }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="header">
                            <h1>BotifyTrades</h1>
                            <p>Password Recovery</p>
                        </div>
                        <div class="content">
                            <p>Hi <strong>{username}</strong>,</p>
                            <p>We received a request to reset your BotifyTrades password. If you didn't make this request, you can safely ignore this email.</p>
                            <p>Click the button below to reset your password:</p>
                            <a href="{reset_link}" class="button">Reset Password</a>
                            <p>Or copy this link: <code>{reset_link}</code></p>
                            <p><strong>This link expires in 24 hours.</strong></p>
                            <div class="footer">
                                <p>If you have any questions, please contact support.</p>
                                <p>© {datetime.now().year} BotifyTrades. All rights reserved.</p>
                            </div>
                        </div>
                    </div>
                </body>
            </html>
            """
            
            text_body = f"""
            Password Reset Request

            Hi {username},

            We received a request to reset your BotifyTrades password. If you didn't make this request, you can safely ignore this email.

            Reset your password here: {reset_link}

            This link expires in 24 hours.

            If you have any questions, please contact support.
            © {datetime.now().year} BotifyTrades. All rights reserved.
            """
            
            return self._send_email(to_email, subject, text_body, html_body)
        
        except Exception as e:
            print(f"[EMAIL] Error preparing reset email: {e}")
            return {'success': False, 'error': str(e)}
    
    def send_welcome_email(self, to_email: str, username: str) -> Dict:
        """Send welcome email to new user"""
        if not self.is_configured():
            return {'success': False, 'error': 'Email service not configured'}
        
        try:
            subject = "Welcome to BotifyTrades"
            html_body = f"""
            <html>
                <head>
                    <style>
                        body {{ font-family: Arial, sans-serif; color: #333; }}
                        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                        .header {{ background: linear-gradient(135deg, #00d4ff 0%, #00ff88 100%); color: #000; padding: 20px; border-radius: 10px 10px 0 0; text-align: center; }}
                        .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
                        .footer {{ color: #666; font-size: 12px; margin-top: 20px; padding-top: 20px; border-top: 1px solid #ddd; }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="header">
                            <h1>Welcome to BotifyTrades</h1>
                        </div>
                        <div class="content">
                            <p>Hi <strong>{username}</strong>,</p>
                            <p>Your account has been successfully created! You can now log in to the control panel and start configuring your trading bot.</p>
                            <p><strong>Next Steps:</strong></p>
                            <ul>
                                <li>Connect your Discord account</li>
                                <li>Configure your brokerage accounts (Webull, Alpaca, or Interactive Brokers)</li>
                                <li>Set up your trading channels</li>
                                <li>Configure risk management and AI analysis</li>
                            </ul>
                            <p>Happy trading!</p>
                            <div class="footer">
                                <p>© {datetime.now().year} BotifyTrades. All rights reserved.</p>
                            </div>
                        </div>
                    </div>
                </body>
            </html>
            """
            
            text_body = f"""
            Welcome to BotifyTrades

            Hi {username},

            Your account has been successfully created! You can now log in to the control panel and start configuring your trading bot.

            Next Steps:
            - Connect your Discord account
            - Configure your brokerage accounts (Webull, Alpaca, or Interactive Brokers)
            - Set up your trading channels
            - Configure risk management and AI analysis

            Happy trading!

            © {datetime.now().year} BotifyTrades. All rights reserved.
            """
            
            return self._send_email(to_email, subject, text_body, html_body)
        
        except Exception as e:
            print(f"[EMAIL] Error preparing welcome email: {e}")
            return {'success': False, 'error': str(e)}
    
    def _send_email(self, to_email: str, subject: str, text_body: str, html_body: str) -> Dict:
        """Internal method to send email via SMTP"""
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = f"{self.sender_name} <{self.sender_email}>"
            msg['To'] = to_email
            
            msg.attach(MIMEText(text_body, 'plain'))
            msg.attach(MIMEText(html_body, 'html'))
            
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender_email, self.sender_password)
                server.send_message(msg)
            
            print(f"[EMAIL] ✓ Email sent to {to_email}")
            return {'success': True, 'message': 'Email sent successfully'}
        
        except smtplib.SMTPAuthenticationError:
            error = 'Email authentication failed. Check credentials.'
            print(f"[EMAIL] ✗ {error}")
            return {'success': False, 'error': error}
        
        except smtplib.SMTPException as e:
            error = f'SMTP error: {str(e)}'
            print(f"[EMAIL] ✗ {error}")
            return {'success': False, 'error': error}
        
        except Exception as e:
            error = f'Error sending email: {str(e)}'
            print(f"[EMAIL] ✗ {error}")
            return {'success': False, 'error': error}


def get_email_service() -> EmailService:
    """Factory function to get email service instance"""
    return EmailService()
