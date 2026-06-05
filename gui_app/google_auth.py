# Google OAuth Authentication for End Users
# Integration: flask_google_oauth blueprint

import json
import os
import requests
from flask import Blueprint, redirect, request, url_for, session, flash
from oauthlib.oauth2 import WebApplicationClient
from . import database as db

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"

google_auth = Blueprint("google_auth", __name__)

def is_google_auth_configured():
    """Check if Google OAuth is properly configured."""
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)

def get_redirect_url():
    """Get the appropriate redirect URL."""
    if os.environ.get("REPLIT_DEV_DOMAIN"):
        return f'https://{os.environ["REPLIT_DEV_DOMAIN"]}/google_login/callback'
    return None

if is_google_auth_configured():
    client = WebApplicationClient(GOOGLE_CLIENT_ID)
    redirect_url = get_redirect_url()
    if redirect_url:
        print(f"""[GOOGLE AUTH] To complete Google authentication setup:
1. Go to https://console.cloud.google.com/apis/credentials
2. Create a new OAuth 2.0 Client ID
3. Add {redirect_url} to Authorized redirect URIs

For detailed instructions, see:
https://docs.replit.com/additional-resources/google-auth-in-flask#set-up-your-oauth-app--client
""")
else:
    client = None
    print("[GOOGLE AUTH] Google OAuth not configured. Set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET to enable.")


@google_auth.route("/google_login")
def google_login():
    """Initiate Google OAuth login flow."""
    if not is_google_auth_configured():
        flash("Google authentication is not configured.", "error")
        return redirect(url_for('user_login'))
    
    try:
        google_provider_cfg = requests.get(GOOGLE_DISCOVERY_URL).json()
        authorization_endpoint = google_provider_cfg["authorization_endpoint"]

        request_uri = client.prepare_request_uri(
            authorization_endpoint,
            redirect_uri=request.base_url.replace("http://", "https://") + "/callback",
            scope=["openid", "email", "profile"],
        )
        return redirect(request_uri)
    except Exception as e:
        print(f"[GOOGLE AUTH] Error initiating login: {e}")
        flash("Failed to connect to Google. Please try again.", "error")
        return redirect(url_for('user_login'))


@google_auth.route("/google_login/callback")
def google_callback():
    """Handle Google OAuth callback."""
    if not is_google_auth_configured():
        flash("Google authentication is not configured.", "error")
        return redirect(url_for('user_login'))
    
    try:
        code = request.args.get("code")
        if not code:
            flash("Authentication cancelled.", "error")
            return redirect(url_for('user_login'))
        
        google_provider_cfg = requests.get(GOOGLE_DISCOVERY_URL).json()
        token_endpoint = google_provider_cfg["token_endpoint"]

        token_url, headers, body = client.prepare_token_request(
            token_endpoint,
            authorization_response=request.url.replace("http://", "https://"),
            redirect_url=request.base_url.replace("http://", "https://"),
            code=code,
        )
        token_response = requests.post(
            token_url,
            headers=headers,
            data=body,
            auth=(GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET),
        )

        client.parse_request_body_response(json.dumps(token_response.json()))

        userinfo_endpoint = google_provider_cfg["userinfo_endpoint"]
        uri, headers, body = client.add_token(userinfo_endpoint)
        userinfo_response = requests.get(uri, headers=headers, data=body)

        userinfo = userinfo_response.json()
        if not userinfo.get("email_verified"):
            flash("Your Google email is not verified.", "error")
            return redirect(url_for('user_login'))
        
        users_email = userinfo["email"]
        users_name = userinfo.get("given_name", "User")
        users_last_name = userinfo.get("family_name", "")
        
        # Check if user exists
        user = db.get_end_user_by_email(users_email)
        
        if not user:
            # Create new user with Google account
            # Generate username from email
            username = users_email.split('@')[0].lower()
            base_username = username
            counter = 1
            while db.get_end_user_by_username(username):
                username = f"{base_username}{counter}"
                counter += 1
            
            # Create user without password (Google auth only)
            import secrets
            temp_password = secrets.token_hex(32)  # Random password they won't use
            
            user_id = db.create_end_user(
                username=username,
                email=users_email,
                password=temp_password,
                first_name=users_name,
                last_name=users_last_name
            )
            
            if not user_id:
                flash("Failed to create account. Please try again.", "error")
                return redirect(url_for('signup'))
            
            user = db.get_end_user_by_id(user_id)
            flash("Account created successfully with Google!", "success")
        
        # Log in the user
        session['user_logged_in'] = True
        session['user_id'] = user['id']
        session['user_username'] = user['username']
        session['user_first_name'] = user.get('first_name', user['username'])
        session.permanent = True
        
        return redirect(url_for('user_dashboard'))
        
    except Exception as e:
        print(f"[GOOGLE AUTH] Callback error: {e}")
        import traceback
        traceback.print_exc()
        flash("Authentication failed. Please try again.", "error")
        return redirect(url_for('user_login'))


@google_auth.route("/user/logout")
def user_logout():
    """Log out the end user."""
    session.pop('user_logged_in', None)
    session.pop('user_id', None)
    session.pop('user_username', None)
    session.pop('user_first_name', None)
    flash("You have been logged out.", "info")
    return redirect(url_for('architecture'))
