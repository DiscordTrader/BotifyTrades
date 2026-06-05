"""
Email Service for Admin Panel - Gmail Integration

Uses Replit's Gmail connector for sending password reset emails.
"""

import os
import json


def get_gmail_credentials():
    """Get Gmail OAuth credentials from Replit connector"""
    hostname = os.environ.get('REPLIT_CONNECTORS_HOSTNAME') or os.environ.get('CONNECTORS_HOSTNAME')
    
    x_replit_token = None
    if os.environ.get('REPL_IDENTITY'):
        x_replit_token = 'repl ' + os.environ.get('REPL_IDENTITY')
    elif os.environ.get('WEB_REPL_RENEWAL'):
        x_replit_token = 'depl ' + os.environ.get('WEB_REPL_RENEWAL')
    
    if not hostname or not x_replit_token:
        return None
    
    try:
        import urllib.request
        import urllib.error
        
        url = f'https://{hostname}/api/v2/connection?include_secrets=true&connector_names=google-mail'
        req = urllib.request.Request(url)
        req.add_header('Accept', 'application/json')
        req.add_header('X_REPLIT_TOKEN', x_replit_token)
        
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            
        if not data.get('items'):
            return None
        
        connection = data['items'][0]
        settings = connection.get('settings', {})
        
        access_token = settings.get('access_token')
        if not access_token:
            oauth = settings.get('oauth', {})
            credentials = oauth.get('credentials', {})
            access_token = credentials.get('access_token')
        
        return access_token
    except Exception as e:
        print(f"[EMAIL] Failed to get Gmail credentials: {e}")
        return None


def send_password_reset_email(to_email: str, username: str, reset_link: str) -> bool:
    """Send password reset email using Gmail API"""
    access_token = get_gmail_credentials()
    
    if not access_token:
        print("[EMAIL] Gmail not configured - cannot send reset email")
        return False
    
    try:
        import base64
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        import urllib.request
        import urllib.error
        
        msg = MIMEMultipart('alternative')
        msg['Subject'] = 'BotifyTrades Admin - Password Reset Request'
        msg['To'] = to_email
        
        text_content = f"""
BotifyTrades Admin Password Reset

Hi {username},

You requested a password reset for your BotifyTrades Admin account.

Click the link below to reset your password (expires in 1 hour):
{reset_link}

If you didn't request this, please ignore this email.

- BotifyTrades Team
"""
        
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
        .header h1 {{ color: white; margin: 0; font-size: 24px; }}
        .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
        .button {{ display: inline-block; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; font-weight: bold; margin: 20px 0; }}
        .footer {{ text-align: center; color: #888; font-size: 12px; margin-top: 20px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>BotifyTrades Admin</h1>
        </div>
        <div class="content">
            <h2>Password Reset Request</h2>
            <p>Hi {username},</p>
            <p>You requested a password reset for your BotifyTrades Admin account.</p>
            <p>Click the button below to reset your password:</p>
            <p style="text-align: center;">
                <a href="{reset_link}" class="button">Reset Password</a>
            </p>
            <p><small>This link expires in 1 hour.</small></p>
            <p>If you didn't request this, please ignore this email.</p>
        </div>
        <div class="footer">
            <p>&copy; BotifyTrades - Automated Trading Solutions</p>
        </div>
    </div>
</body>
</html>
"""
        
        part1 = MIMEText(text_content, 'plain')
        part2 = MIMEText(html_content, 'html')
        msg.attach(part1)
        msg.attach(part2)
        
        raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode('utf-8')
        
        url = 'https://gmail.googleapis.com/gmail/v1/users/me/messages/send'
        data = json.dumps({'raw': raw_message}).encode('utf-8')
        
        req = urllib.request.Request(url, data=data, method='POST')
        req.add_header('Authorization', f'Bearer {access_token}')
        req.add_header('Content-Type', 'application/json')
        
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode())
            print(f"[EMAIL] ✓ Password reset email sent to {to_email}")
            return True
            
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.read else str(e)
        print(f"[EMAIL] HTTP error sending email: {e.code} - {error_body}")
        return False
    except Exception as e:
        print(f"[EMAIL] Failed to send email: {e}")
        return False
