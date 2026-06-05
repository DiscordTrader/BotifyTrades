"""
Gmail Integration Service for QuantumPulse
Uses Replit's Gmail connector to send waitlist notifications
"""
import os
import base64
import asyncio
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, List, Optional
import aiohttp


class GmailService:
    """Service for sending emails via Gmail using Replit's connector"""
    
    def __init__(self):
        self.hostname = os.environ.get('REPLIT_CONNECTORS_HOSTNAME', 'connectors.replit.com')
        self._connection_settings = None
    
    async def _get_access_token(self) -> str:
        """Get OAuth access token from Replit connector"""
        repl_identity = os.environ.get('REPL_IDENTITY')
        web_repl_renewal = os.environ.get('WEB_REPL_RENEWAL')
        
        if repl_identity:
            x_replit_token = f'repl {repl_identity}'
        elif web_repl_renewal:
            x_replit_token = f'depl {web_repl_renewal}'
        else:
            raise Exception('Replit identity token not found')
        
        url = f'https://{self.hostname}/api/v2/connection?include_secrets=true&connector_names=google-mail'
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers={
                    'Accept': 'application/json',
                    'X_REPLIT_TOKEN': x_replit_token
                }
            ) as response:
                if response.status != 200:
                    raise Exception(f'Failed to get Gmail connection: {response.status}')
                
                data = await response.json()
                items = data.get('items', [])
                
                if not items:
                    raise Exception('Gmail not connected. Please set up the Gmail integration.')
                
                self._connection_settings = items[0]
                settings = self._connection_settings.get('settings', {})
                
                access_token = settings.get('access_token')
                if not access_token:
                    oauth = settings.get('oauth', {})
                    credentials = oauth.get('credentials', {})
                    access_token = credentials.get('access_token')
                
                if not access_token:
                    raise Exception('Gmail access token not found')
                
                return access_token
    
    def _create_message(self, to: str, subject: str, body: str, html_body: Optional[str] = None) -> str:
        """Create a base64-encoded email message"""
        if html_body:
            message = MIMEMultipart('alternative')
            message['to'] = to
            message['subject'] = subject
            
            part1 = MIMEText(body, 'plain')
            part2 = MIMEText(html_body, 'html')
            
            message.attach(part1)
            message.attach(part2)
        else:
            message = MIMEText(body)
            message['to'] = to
            message['subject'] = subject
        
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
        return raw
    
    async def send_email(
        self, 
        to: str, 
        subject: str, 
        body: str, 
        html_body: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send an email via Gmail API
        
        Args:
            to: Recipient email address
            subject: Email subject
            body: Plain text body
            html_body: Optional HTML body
            
        Returns:
            Dict with success status and message details
        """
        try:
            access_token = await self._get_access_token()
            raw_message = self._create_message(to, subject, body, html_body)
            
            url = 'https://gmail.googleapis.com/gmail/v1/users/me/messages/send'
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    headers={
                        'Authorization': f'Bearer {access_token}',
                        'Content-Type': 'application/json'
                    },
                    json={'raw': raw_message}
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        return {
                            'success': True,
                            'message_id': result.get('id'),
                            'thread_id': result.get('threadId')
                        }
                    else:
                        error_text = await response.text()
                        return {
                            'success': False,
                            'error': f'Gmail API error ({response.status}): {error_text}'
                        }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    async def send_waitlist_invite(
        self, 
        to: str, 
        name: Optional[str], 
        queue_position: int,
        referral_code: str
    ) -> Dict[str, Any]:
        """Send a waitlist invite email"""
        display_name = name or 'there'
        
        subject = "You're Invited to QuantumPulse Beta!"
        
        body = f"""Hello {display_name},

Congratulations! You've been selected for early access to QuantumPulse.

Your queue position: #{queue_position}
Your referral code: {referral_code}

Share your referral code with friends to move up the queue!

Welcome aboard!
The QuantumPulse Team
"""
        
        html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #0a1628; color: #e0e6ed; padding: 20px; }}
        .container {{ max-width: 600px; margin: 0 auto; background: linear-gradient(135deg, #0d2a3a 0%, #0f3a4f 100%); border-radius: 16px; padding: 40px; border: 1px solid rgba(0, 212, 255, 0.3); }}
        .logo {{ font-family: 'Orbitron', sans-serif; font-size: 28px; color: #00d4ff; margin-bottom: 30px; text-align: center; }}
        h1 {{ color: #00d4ff; font-size: 24px; margin-bottom: 20px; }}
        .highlight {{ background: rgba(0, 212, 255, 0.1); padding: 20px; border-radius: 12px; margin: 20px 0; border-left: 4px solid #00d4ff; }}
        .position {{ font-size: 32px; font-weight: bold; color: #00d4ff; }}
        .referral {{ font-family: monospace; background: rgba(0, 212, 255, 0.2); padding: 8px 16px; border-radius: 6px; font-size: 18px; }}
        .footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid rgba(0, 212, 255, 0.2); font-size: 14px; color: #8899a6; text-align: center; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="logo">Ψ∿ QuantumPulse</div>
        <h1>You're Invited!</h1>
        <p>Hello {display_name},</p>
        <p>Congratulations! You've been selected for early access to QuantumPulse - the automated Discord trading bot.</p>
        
        <div class="highlight">
            <p>Your queue position: <span class="position">#{queue_position}</span></p>
            <p>Your referral code: <span class="referral">{referral_code}</span></p>
        </div>
        
        <p>Share your referral code with friends to move up the queue!</p>
        
        <div class="footer">
            <p>Welcome aboard!</p>
            <p>The QuantumPulse Team</p>
        </div>
    </div>
</body>
</html>
"""
        
        return await self.send_email(to, subject, body, html_body)
    
    async def send_waitlist_update(
        self, 
        to: str, 
        name: Optional[str],
        subject: str,
        body_template: str,
        queue_position: int,
        referral_code: str
    ) -> Dict[str, Any]:
        """Send a custom update email to waitlist user"""
        display_name = name or 'there'
        
        body = body_template.replace('{name}', display_name)
        body = body.replace('{position}', str(queue_position))
        body = body.replace('{referral_code}', referral_code)
        
        return await self.send_email(to, subject, body)
    
    async def send_bulk_emails(
        self,
        recipients: List[Dict[str, Any]],
        subject: str,
        body_template: str,
        email_type: str = 'update'
    ) -> Dict[str, Any]:
        """
        Send emails to multiple recipients
        
        Args:
            recipients: List of dicts with email, name, queue_position, referral_code
            subject: Email subject
            body_template: Email body with {name}, {position}, {referral_code} placeholders
            email_type: 'invite' or 'update'
            
        Returns:
            Summary of sent/failed emails
        """
        results = {
            'total': len(recipients),
            'sent': 0,
            'failed': 0,
            'errors': []
        }
        
        for recipient in recipients:
            try:
                if email_type == 'invite':
                    result = await self.send_waitlist_invite(
                        to=recipient['email'],
                        name=recipient.get('name'),
                        queue_position=recipient.get('queue_position', 0),
                        referral_code=recipient.get('referral_code', '')
                    )
                else:
                    result = await self.send_waitlist_update(
                        to=recipient['email'],
                        name=recipient.get('name'),
                        subject=subject,
                        body_template=body_template,
                        queue_position=recipient.get('queue_position', 0),
                        referral_code=recipient.get('referral_code', '')
                    )
                
                if result.get('success'):
                    results['sent'] += 1
                else:
                    results['failed'] += 1
                    results['errors'].append({
                        'email': recipient['email'],
                        'error': result.get('error')
                    })
                    
                await asyncio.sleep(0.5)
                
            except Exception as e:
                results['failed'] += 1
                results['errors'].append({
                    'email': recipient['email'],
                    'error': str(e)
                })
        
        return results


_gmail_service = None

def get_gmail_service() -> GmailService:
    """Get singleton Gmail service instance"""
    global _gmail_service
    if _gmail_service is None:
        _gmail_service = GmailService()
    return _gmail_service
