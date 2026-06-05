"""
Schwab OAuth Callback Server
Temporary HTTPS server on port 8182 to capture OAuth callbacks automatically.

Features:
- Self-signed certificate for local HTTPS
- PKCE support for enhanced security
- Auto-shutdown after callback received
- PyInstaller compatible
"""

import os
import ssl
import json
import time
import socket
import secrets
import hashlib
import base64
import ipaddress
import threading
import tempfile
from typing import Optional, Tuple, Callable
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime

# OAuth callback port - must match Schwab portal registration
CALLBACK_PORT = 8182
CALLBACK_HOST = "127.0.0.1"
CALLBACK_PATH = "/callback"


class PKCEManager:
    """
    Manages PKCE (Proof Key for Code Exchange) for OAuth2.
    
    PKCE adds an additional layer of security for OAuth flows,
    especially important for native/desktop applications.
    """
    
    def __init__(self):
        self.code_verifier: Optional[str] = None
        self.code_challenge: Optional[str] = None
    
    def generate(self) -> Tuple[str, str]:
        """
        Generate a new PKCE code verifier and challenge.
        
        Returns:
            Tuple of (code_verifier, code_challenge)
        """
        # Generate code_verifier: 43-128 characters, URL-safe
        self.code_verifier = secrets.token_urlsafe(64)[:128]
        
        # Generate code_challenge: SHA256 hash of verifier, base64url encoded
        digest = hashlib.sha256(self.code_verifier.encode('ascii')).digest()
        self.code_challenge = base64.urlsafe_b64encode(digest).decode('ascii').rstrip('=')
        
        print(f"[PKCE] Generated new code_verifier (len={len(self.code_verifier)})")
        print(f"[PKCE] Generated code_challenge: {self.code_challenge[:20]}...")
        
        return self.code_verifier, self.code_challenge
    
    def get_verifier(self) -> Optional[str]:
        """Get the current code verifier for token exchange."""
        return self.code_verifier
    
    def clear(self):
        """Clear PKCE data after use."""
        self.code_verifier = None
        self.code_challenge = None


class SelfSignedCertificate:
    """
    Generates a self-signed certificate for local HTTPS.
    
    This is safe for local OAuth callbacks since:
    1. Only runs on 127.0.0.1 (localhost)
    2. Certificate is temporary and per-session
    3. User's browser will show a warning but can proceed
    """
    
    def __init__(self):
        self.cert_file: Optional[str] = None
        self.key_file: Optional[str] = None
        self._temp_dir: Optional[str] = None
    
    def generate(self) -> Tuple[str, str]:
        """
        Generate a self-signed certificate and key.
        
        Returns:
            Tuple of (cert_file_path, key_file_path)
        """
        try:
            from cryptography import x509
            from cryptography.x509.oid import NameOID
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import rsa
            from cryptography.hazmat.backends import default_backend
            from datetime import timedelta
            
            # Generate private key
            key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
                backend=default_backend()
            )
            
            # Generate certificate
            subject = issuer = x509.Name([
                x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
                x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Local"),
                x509.NameAttribute(NameOID.LOCALITY_NAME, "Localhost"),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "BotifyTrades"),
                x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1"),
            ])
            
            cert = (
                x509.CertificateBuilder()
                .subject_name(subject)
                .issuer_name(issuer)
                .public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(datetime.utcnow())
                .not_valid_after(datetime.utcnow() + timedelta(days=1))
                .add_extension(
                    x509.SubjectAlternativeName([
                        x509.DNSName("localhost"),
                        x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
                    ]),
                    critical=False,
                )
                .sign(key, hashes.SHA256(), default_backend())
            )
            
            # Write to temp files
            self._temp_dir = tempfile.mkdtemp(prefix="schwab_oauth_")
            self.cert_file = os.path.join(self._temp_dir, "cert.pem")
            self.key_file = os.path.join(self._temp_dir, "key.pem")
            
            with open(self.cert_file, "wb") as f:
                f.write(cert.public_bytes(serialization.Encoding.PEM))
            
            with open(self.key_file, "wb") as f:
                f.write(key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.NoEncryption()
                ))
            
            print(f"[CERT] Generated self-signed certificate in {self._temp_dir}")
            return self.cert_file, self.key_file
            
        except ImportError:
            print("[CERT] cryptography package not available, using fallback")
            return self._generate_openssl_fallback()
    
    def _generate_openssl_fallback(self) -> Tuple[str, str]:
        """Fallback using OpenSSL command if cryptography not available."""
        import subprocess
        
        self._temp_dir = tempfile.mkdtemp(prefix="schwab_oauth_")
        self.cert_file = os.path.join(self._temp_dir, "cert.pem")
        self.key_file = os.path.join(self._temp_dir, "key.pem")
        
        try:
            subprocess.run([
                "openssl", "req", "-x509", "-newkey", "rsa:2048",
                "-keyout", self.key_file,
                "-out", self.cert_file,
                "-days", "1",
                "-nodes",
                "-subj", "/CN=127.0.0.1/O=BotifyTrades"
            ], check=True, capture_output=True)
            
            print(f"[CERT] Generated certificate via OpenSSL in {self._temp_dir}")
            return self.cert_file, self.key_file
            
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"[CERT] OpenSSL fallback failed: {e}")
            raise RuntimeError("Cannot generate SSL certificate. Install cryptography package.")
    
    def cleanup(self):
        """Remove temporary certificate files."""
        import shutil
        if self._temp_dir and os.path.exists(self._temp_dir):
            shutil.rmtree(self._temp_dir, ignore_errors=True)
            print("[CERT] Cleaned up temporary certificate files")


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP request handler for OAuth callbacks."""
    
    # Class-level storage for callback data
    callback_received = threading.Event()
    auth_code: Optional[str] = None
    error: Optional[str] = None
    success_redirect: str = "http://127.0.0.1:5000/settings"
    
    def log_message(self, format, *args):
        """Override to use custom logging."""
        print(f"[CALLBACK] {args[0]}")
    
    def do_GET(self):
        """Handle GET request (OAuth callback)."""
        parsed = urlparse(self.path)
        
        if parsed.path == CALLBACK_PATH or parsed.path == "/":
            params = parse_qs(parsed.query)
            
            # Check for authorization code
            if 'code' in params:
                OAuthCallbackHandler.auth_code = params['code'][0]
                OAuthCallbackHandler.error = None
                print(f"[CALLBACK] Received authorization code: {OAuthCallbackHandler.auth_code[:20]}...")
                
                # Send success response and redirect to Flask UI
                self._send_success_response()
            
            # Check for error
            elif 'error' in params:
                OAuthCallbackHandler.error = params.get('error_description', params['error'])[0]
                OAuthCallbackHandler.auth_code = None
                print(f"[CALLBACK] OAuth error: {OAuthCallbackHandler.error}")
                
                self._send_error_response(OAuthCallbackHandler.error)
            
            else:
                self._send_error_response("No authorization code received")
            
            # Signal that callback was received
            OAuthCallbackHandler.callback_received.set()
        else:
            self.send_error(404, "Not Found")
    
    def _send_success_response(self):
        """Send HTML response that notifies opener via postMessage and auto-closes."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Schwab Connected</title>
            <style>
                body { font-family: Arial, sans-serif; background: #1a1a2e; color: #00ffa3;
                       display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
                .container { text-align: center; padding: 40px; background: #16213e; border-radius: 12px;
                             box-shadow: 0 4px 20px rgba(0,255,163,0.2); max-width: 420px; }
                h1 { margin-bottom: 16px; font-size: 24px; }
                p { color: #a0a0a0; margin-bottom: 20px; font-size: 14px; }
                .close-msg { font-size: 12px; color: #666; }
            </style>
            <script>
                (function() {
                    var result = { type: 'schwab-oauth-callback', status: 'success', message: 'Authorization successful! Exchanging tokens...' };
                    var origins = [
                        'http://localhost:5000', 'http://127.0.0.1:5000',
                        'http://localhost:3000', 'http://127.0.0.1:3000'
                    ];
                    if (window.opener) {
                        for (var i = 0; i < origins.length; i++) {
                            try { window.opener.postMessage(result, origins[i]); } catch(e) {}
                        }
                        if (window.location.hostname) {
                            try { window.opener.postMessage(result, window.location.origin); } catch(e) {}
                        }
                    }
                    setTimeout(function() {
                        try { window.close(); } catch(e) {}
                    }, 2000);
                    setTimeout(function() {
                        var el = document.getElementById('close-msg');
                        if (el) el.innerHTML = 'If this window did not close automatically, you can close it now.';
                    }, 3000);
                })();
            </script>
        </head>
        <body>
            <div class="container">
                <h1>&#10004; Schwab Connected!</h1>
                <p>Authorization successful. Exchanging tokens...</p>
                <p id="close-msg" class="close-msg">This window will close automatically...</p>
            </div>
        </body>
        </html>
        """
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(html.encode())

    def _send_error_response(self, error: str):
        """Send HTML error response that notifies opener via postMessage and auto-closes."""
        safe_error = error.replace("'", "\\'").replace('"', '&quot;')
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Schwab Auth Error</title>
            <style>
                body {{ font-family: Arial, sans-serif; background: #1a1a2e; color: #ff5555;
                       display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }}
                .container {{ text-align: center; padding: 40px; background: #16213e; border-radius: 12px;
                             max-width: 420px; }}
                h1 {{ margin-bottom: 16px; font-size: 24px; }}
                p {{ color: #a0a0a0; }}
                .error {{ color: #ff5555; margin: 16px 0; }}
                .close-msg {{ font-size: 12px; color: #666; margin-top: 20px; }}
            </style>
            <script>
                (function() {{
                    var result = {{ type: 'schwab-oauth-callback', status: 'error', message: '{safe_error}' }};
                    var origins = [
                        'http://localhost:5000', 'http://127.0.0.1:5000',
                        'http://localhost:3000', 'http://127.0.0.1:3000'
                    ];
                    if (window.opener) {{
                        for (var i = 0; i < origins.length; i++) {{
                            try {{ window.opener.postMessage(result, origins[i]); }} catch(e) {{}}
                        }}
                        if (window.location.hostname) {{
                            try {{ window.opener.postMessage(result, window.location.origin); }} catch(e) {{}}
                        }}
                    }}
                    setTimeout(function() {{
                        try {{ window.close(); }} catch(e) {{}}
                    }}, 4000);
                    setTimeout(function() {{
                        var el = document.getElementById('close-msg');
                        if (el) el.innerHTML = 'If this window did not close automatically, you can close it now.';
                    }}, 5000);
                }})();
            </script>
        </head>
        <body>
            <div class="container">
                <h1>&#10008; Authentication Failed</h1>
                <p class="error">{error}</p>
                <p id="close-msg" class="close-msg">This window will close automatically...</p>
            </div>
        </body>
        </html>
        """
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(html.encode())


class SchwabOAuthCallbackServer:
    """
    Temporary HTTPS server for capturing Schwab OAuth callbacks.
    
    Usage:
        server = SchwabOAuthCallbackServer()
        server.start()
        
        # Open browser to Schwab auth URL...
        
        code = server.wait_for_callback(timeout=300)  # 5 minute timeout
        server.stop()
        
        if code:
            # Exchange code for tokens
            pass
    """
    
    def __init__(self, host: str = CALLBACK_HOST, port: int = CALLBACK_PORT):
        self.host = host
        self.port = port
        self.server: Optional[HTTPServer] = None
        self.server_thread: Optional[threading.Thread] = None
        self.cert_manager = SelfSignedCertificate()
        self.pkce = PKCEManager()
        self._running = False
    
    @property
    def callback_url(self) -> str:
        """Get the full callback URL for Schwab portal registration."""
        return f"https://{self.host}:{self.port}{CALLBACK_PATH}"
    
    def start(self) -> bool:
        """
        Start the HTTPS callback server.
        
        Returns:
            True if server started successfully
        """
        if self._running:
            OAuthCallbackHandler.callback_received.clear()
            OAuthCallbackHandler.auth_code = None
            OAuthCallbackHandler.error = None
            print("[OAUTH SERVER] Already running, reset callback state for new flow")
            return True
        
        try:
            # Check if port is available
            if not self._is_port_available():
                print(f"[OAUTH SERVER] Port {self.port} is in use")
                return False
            
            # Generate certificate
            cert_file, key_file = self.cert_manager.generate()
            
            # Reset callback state
            OAuthCallbackHandler.callback_received.clear()
            OAuthCallbackHandler.auth_code = None
            OAuthCallbackHandler.error = None
            
            # Create HTTPS server
            self.server = HTTPServer((self.host, self.port), OAuthCallbackHandler)
            
            # Wrap with SSL
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert_file, key_file)
            self.server.socket = context.wrap_socket(
                self.server.socket,
                server_side=True
            )
            
            # Start server thread
            self.server_thread = threading.Thread(
                target=self._serve,
                daemon=True,
                name="SchwabOAuthServer"
            )
            self.server_thread.start()
            self._running = True
            
            print(f"[OAUTH SERVER] Started on {self.callback_url}")
            return True
            
        except Exception as e:
            print(f"[OAUTH SERVER] Failed to start: {e}")
            import traceback
            traceback.print_exc()
            self.cert_manager.cleanup()
            return False
    
    def _is_port_available(self) -> bool:
        """Check if the callback port is available."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((self.host, self.port))
                return True
        except socket.error:
            return False
    
    def _serve(self):
        """Server loop (runs in thread)."""
        print("[OAUTH SERVER] Waiting for callback...")
        while self._running and self.server:
            self.server.handle_request()
    
    def wait_for_callback(self, timeout: float = 300) -> Optional[str]:
        """
        Wait for OAuth callback to be received.
        
        Args:
            timeout: Maximum seconds to wait (default 5 minutes)
            
        Returns:
            Authorization code if received, None otherwise
        """
        print(f"[OAUTH SERVER] Waiting up to {timeout}s for callback...")
        
        received = OAuthCallbackHandler.callback_received.wait(timeout=timeout)
        
        if received:
            if OAuthCallbackHandler.auth_code:
                return OAuthCallbackHandler.auth_code
            elif OAuthCallbackHandler.error:
                print(f"[OAUTH SERVER] OAuth error: {OAuthCallbackHandler.error}")
                return None
        else:
            print("[OAUTH SERVER] Timeout waiting for callback")
            return None
    
    def stop(self):
        """Stop the callback server and cleanup."""
        self._running = False
        
        if self.server:
            try:
                self.server.shutdown()
            except Exception:
                pass
            self.server = None
        
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(timeout=2)
        
        self.cert_manager.cleanup()
        print("[OAUTH SERVER] Stopped")
    
    def get_pkce_challenge(self) -> Tuple[str, str]:
        """Generate and return PKCE values for authorization request."""
        return self.pkce.generate()
    
    def get_pkce_verifier(self) -> Optional[str]:
        """Get the PKCE verifier for token exchange."""
        return self.pkce.get_verifier()


# Singleton instance for the OAuth server
_oauth_server: Optional[SchwabOAuthCallbackServer] = None


def get_oauth_server() -> SchwabOAuthCallbackServer:
    """Get or create the OAuth callback server singleton."""
    global _oauth_server
    if _oauth_server is None:
        _oauth_server = SchwabOAuthCallbackServer()
    return _oauth_server


def start_oauth_flow(client_id: str, redirect_uri: str, use_pkce: bool = True) -> Tuple[str, Optional[SchwabOAuthCallbackServer]]:
    """
    Start the OAuth flow by generating the authorization URL.
    
    Args:
        client_id: Schwab API client ID
        redirect_uri: Registered redirect URI
        use_pkce: Whether to use PKCE (recommended)
        
    Returns:
        Tuple of (auth_url, oauth_server)
    """
    import urllib.parse
    
    # Start callback server
    server = get_oauth_server()
    if not server.start():
        print("[OAUTH] Failed to start callback server, using manual flow")
        server = None
    
    params = {
        'response_type': 'code',
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'scope': 'readonly'
    }
    
    # Add PKCE if enabled and server started
    if use_pkce and server:
        _, code_challenge = server.get_pkce_challenge()
        params['code_challenge'] = code_challenge
        params['code_challenge_method'] = 'S256'
    
    auth_url = f"https://api.schwabapi.com/v1/oauth/authorize?{urllib.parse.urlencode(params)}"
    
    return auth_url, server
