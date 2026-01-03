"""
Charles Schwab OAuth Authentication Blueprint
Handles OAuth2 flow for Schwab API integration
"""

import os
import json
import asyncio
from flask import Blueprint, redirect, request, url_for, flash, jsonify
from . import database as db

schwab_auth = Blueprint("schwab_auth", __name__)

SCHWAB_TOKEN_FILE = "schwab_token.json"


def get_schwab_credentials():
    """Get Schwab credentials from database"""
    try:
        result = db.get_broker_credentials('SCHWAB')
        if result:
            creds = result.get('credentials', {})
            return {
                'client_id': creds.get('client_id', ''),
                'client_secret': creds.get('client_secret', ''),
                'redirect_uri': creds.get('redirect_uri', get_default_redirect_uri())
            }
    except Exception as e:
        print(f"[SCHWAB AUTH] Error getting credentials: {e}")
    return None


def get_default_redirect_uri():
    """Get the default redirect URI based on environment"""
    if os.environ.get("REPLIT_DEV_DOMAIN"):
        return f'https://{os.environ["REPLIT_DEV_DOMAIN"]}/schwab/callback'
    return 'https://127.0.0.1'


def is_schwab_configured():
    """Check if Schwab is properly configured"""
    creds = get_schwab_credentials()
    return creds and creds.get('client_id') and creds.get('client_secret')


def is_schwab_authenticated():
    """Check if we have valid Schwab tokens"""
    try:
        if os.path.exists(SCHWAB_TOKEN_FILE):
            with open(SCHWAB_TOKEN_FILE, 'r') as f:
                data = json.load(f)
                return bool(data.get('access_token') and data.get('refresh_token'))
    except Exception:
        pass
    return False


@schwab_auth.route("/schwab/login")
def schwab_login():
    """Initiate Schwab OAuth login flow"""
    if not is_schwab_configured():
        flash("Schwab is not configured. Please add Client ID and Secret in Settings.", "error")
        return redirect(url_for('settings_page'))
    
    try:
        import urllib.parse
        
        creds = get_schwab_credentials()
        
        params = {
            'response_type': 'code',
            'client_id': creds['client_id'],
            'redirect_uri': creds['redirect_uri'],
            'scope': 'readonly'
        }
        
        auth_url = f"https://api.schwabapi.com/v1/oauth/authorize?{urllib.parse.urlencode(params)}"
        
        print(f"[SCHWAB AUTH] Redirecting to Schwab for authorization...")
        print(f"[SCHWAB AUTH] Callback URL: {creds['redirect_uri']}")
        
        return redirect(auth_url)
        
    except Exception as e:
        print(f"[SCHWAB AUTH] Error initiating login: {e}")
        flash(f"Failed to connect to Schwab: {str(e)}", "error")
        return redirect(url_for('settings_page'))


@schwab_auth.route("/schwab/callback")
def schwab_callback():
    """Handle Schwab OAuth callback"""
    try:
        code = request.args.get('code')
        error = request.args.get('error')
        
        if error:
            flash(f"Schwab authorization failed: {error}", "error")
            return redirect(url_for('settings_page'))
        
        if not code:
            flash("No authorization code received from Schwab", "error")
            return redirect(url_for('settings_page'))
        
        creds = get_schwab_credentials()
        if not creds:
            flash("Schwab credentials not found", "error")
            return redirect(url_for('settings_page'))
        
        success = exchange_code_for_tokens(code, creds)
        
        if success:
            flash("Successfully connected to Schwab!", "success")
            db.update_broker_connection_status('SCHWAB', True)
        else:
            flash("Failed to exchange authorization code for tokens", "error")
        
        return redirect(url_for('settings_page'))
        
    except Exception as e:
        print(f"[SCHWAB AUTH] Callback error: {e}")
        import traceback
        traceback.print_exc()
        flash(f"Authentication failed: {str(e)}", "error")
        return redirect(url_for('settings_page'))


def exchange_code_for_tokens(code: str, creds: dict) -> bool:
    """Exchange authorization code for access/refresh tokens"""
    try:
        import httpx
        import base64
        from datetime import datetime
        
        credentials = base64.b64encode(
            f"{creds['client_id']}:{creds['client_secret']}".encode()
        ).decode()
        
        headers = {
            'Authorization': f'Basic {credentials}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        data = {
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': creds['redirect_uri']
        }
        
        with httpx.Client() as client:
            response = client.post(
                'https://api.schwabapi.com/v1/oauth/token',
                headers=headers,
                data=data
            )
            
            if response.status_code == 200:
                token_data = response.json()
                
                expires_in = token_data.get('expires_in', 1800)
                token_expiry = datetime.now().timestamp() + expires_in
                
                save_data = {
                    'access_token': token_data.get('access_token'),
                    'refresh_token': token_data.get('refresh_token'),
                    'token_expiry': token_expiry
                }
                
                with open(SCHWAB_TOKEN_FILE, 'w') as f:
                    json.dump(save_data, f)
                
                print(f"[SCHWAB AUTH] Tokens saved successfully")
                return True
            else:
                print(f"[SCHWAB AUTH] Token exchange failed: {response.status_code}")
                print(f"[SCHWAB AUTH] Response: {response.text}")
                return False
                
    except Exception as e:
        print(f"[SCHWAB AUTH] Error exchanging code: {e}")
        import traceback
        traceback.print_exc()
        return False


@schwab_auth.route("/schwab/status")
def schwab_status():
    """Get Schwab connection status"""
    return jsonify({
        'configured': is_schwab_configured(),
        'authenticated': is_schwab_authenticated(),
        'redirect_uri': get_default_redirect_uri()
    })


@schwab_auth.route("/schwab/disconnect", methods=['POST'])
def schwab_disconnect():
    """Disconnect from Schwab (remove tokens)"""
    try:
        if os.path.exists(SCHWAB_TOKEN_FILE):
            os.remove(SCHWAB_TOKEN_FILE)
        db.update_broker_connection_status('SCHWAB', False)
        return jsonify({'success': True, 'message': 'Disconnected from Schwab'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
