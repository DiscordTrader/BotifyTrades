"""
Admin License Server - Flask Application

Lean Flask app for license management ONLY.
No trading, broker, or dashboard functionality.
"""

import os
from functools import wraps
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, make_response
from datetime import datetime, timedelta

from . import database as db


def login_required(f):
    """Decorator to require admin login"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_logged_in' not in session:
            if request.is_json:
                return jsonify({'error': 'Authentication required'}), 401
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function


def create_app():
    """Create the admin panel Flask application"""
    app = Flask(__name__,
                template_folder='templates',
                static_folder='static')
    
    # Use stable secret key - FLASK_SECRET_KEY env var or generate stable fallback
    # IMPORTANT: In production, always set FLASK_SECRET_KEY to a random 32+ char string
    secret_key = os.environ.get('FLASK_SECRET_KEY')
    if not secret_key:
        # Generate stable fallback from machine-specific data (not random each restart)
        import hashlib
        stable_seed = f"botifytrades-admin-{os.environ.get('REPL_ID', 'local')}"
        secret_key = hashlib.sha256(stable_seed.encode()).hexdigest()
        print("[ADMIN] Warning: Using generated secret key. Set FLASK_SECRET_KEY for production.")
    app.secret_key = secret_key
    
    # Session cookie settings - detect production (HTTPS) environment
    is_production = os.environ.get('REPL_SLUG') is not None or os.environ.get('REPLIT_DEPLOYMENT') == '1'
    app.config['SESSION_COOKIE_SECURE'] = is_production  # True for HTTPS in production
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)
    
    print("[ADMIN] ✓ License-only admin panel initialized")
    print("[ADMIN] ✓ No trading functionality loaded")
    
    @app.route('/')
    def index():
        if 'admin_logged_in' in session:
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('admin_login'))
    
    @app.route('/login', methods=['GET', 'POST'])
    def admin_login():
        error = None
        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')
            
            admin = db.verify_admin(username, password)
            if admin:
                session['admin_logged_in'] = True
                session['admin_username'] = username
                session.permanent = True
                db.add_audit_log('login', admin_user=username, ip_address=request.remote_addr)
                return redirect(url_for('admin_dashboard'))
            else:
                error = 'Invalid username or password'
        
        return render_template('login.html', error=error)
    
    @app.route('/logout')
    def admin_logout():
        username = session.get('admin_username')
        if username:
            db.add_audit_log('logout', admin_user=username, ip_address=request.remote_addr)
        session.clear()
        return redirect(url_for('admin_login'))
    
    @app.route('/forgot-password', methods=['GET', 'POST'])
    def forgot_password():
        from . import email_service
        
        message = None
        error = None
        
        if request.method == 'POST':
            email = request.form.get('email', '').strip().lower()
            
            if not email:
                error = 'Please enter your email address'
            else:
                admin = db.get_admin_by_email(email)
                if admin:
                    token = db.create_password_reset_token(admin['id'])
                    
                    base_url = request.host_url.rstrip('/')
                    reset_link = f"{base_url}/reset-password/{token}"
                    
                    if email_service.send_password_reset_email(admin['email'], admin['username'], reset_link):
                        db.add_audit_log('password_reset_requested', 
                                        admin_user=admin['username'],
                                        details=f'Reset email sent to {email}',
                                        ip_address=request.remote_addr)
                        message = 'If an account exists with that email, a reset link has been sent.'
                    else:
                        error = 'Failed to send reset email. Please contact support.'
                else:
                    message = 'If an account exists with that email, a reset link has been sent.'
        
        return render_template('forgot_password.html', message=message, error=error)
    
    @app.route('/reset-password/<token>', methods=['GET', 'POST'])
    def reset_password(token):
        token_data = db.verify_reset_token(token)
        
        if not token_data:
            return render_template('reset_password.html', 
                                 error='Invalid or expired reset link. Please request a new one.',
                                 token_valid=False)
        
        error = None
        if request.method == 'POST':
            password = request.form.get('password', '')
            confirm = request.form.get('confirm_password', '')
            
            if not password:
                error = 'Password is required'
            elif len(password) < 8:
                error = 'Password must be at least 8 characters'
            elif password != confirm:
                error = 'Passwords do not match'
            else:
                if db.use_reset_token(token, password):
                    db.add_audit_log('password_reset_completed',
                                    admin_user=token_data['username'],
                                    ip_address=request.remote_addr)
                    return render_template('reset_password.html',
                                         success=True,
                                         token_valid=False)
                else:
                    error = 'Failed to reset password. Please try again.'
        
        return render_template('reset_password.html',
                             token_valid=True,
                             username=token_data['username'],
                             error=error)
    
    @app.route('/setup', methods=['GET', 'POST'])
    def admin_setup():
        """First-time admin setup"""
        stats = db.get_license_stats()
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM admin_users')
            admin_count = cursor.fetchone()[0]
        
        if admin_count > 0:
            return redirect(url_for('admin_login'))
        
        error = None
        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')
            confirm = request.form.get('confirm_password', '')
            email = request.form.get('email', '').strip()
            
            if not username or not password:
                error = 'Username and password are required'
            elif password != confirm:
                error = 'Passwords do not match'
            elif len(password) < 8:
                error = 'Password must be at least 8 characters'
            else:
                if db.create_admin(username, password, email):
                    db.add_audit_log('admin_created', admin_user=username, 
                                    details='Initial admin setup', ip_address=request.remote_addr)
                    session['admin_logged_in'] = True
                    session['admin_username'] = username
                    session.permanent = True
                    return redirect(url_for('admin_dashboard'))
                else:
                    error = 'Failed to create admin account'
        
        return render_template('setup.html', error=error)
    
    @app.route('/dashboard')
    @login_required
    def admin_dashboard():
        stats = db.get_license_stats()
        return render_template('dashboard.html',
                              admin_username=session.get('admin_username'),
                              stats=stats,
                              active_page='dashboard')
    
    @app.route('/licenses')
    @login_required
    def admin_licenses():
        stats = db.get_license_stats()
        return render_template('licenses.html', 
                              admin_username=session.get('admin_username'),
                              stats=stats,
                              active_page='licenses')
    
    @app.route('/audit')
    @login_required
    def admin_audit():
        return render_template('audit.html',
                              admin_username=session.get('admin_username'),
                              active_page='audit')
    
    @app.route('/settings')
    @login_required
    def admin_settings():
        server_url = os.environ.get('REPLIT_DEV_DOMAIN', 'localhost:5000')
        return render_template('settings.html',
                              admin_username=session.get('admin_username'),
                              server_url=server_url,
                              active_page='settings')
    
    @app.route('/api/licenses', methods=['GET'])
    @login_required
    def api_get_licenses():
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)
        status = request.args.get('status')
        search = request.args.get('search')
        sort_by = request.args.get('sort_by', 'created_at')
        sort_order = request.args.get('sort_order', 'desc')
        
        result = db.get_all_licenses(
            page=page,
            per_page=per_page,
            status=status,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order
        )
        
        return jsonify(result)
    
    @app.route('/api/licenses', methods=['POST'])
    @login_required
    def api_create_license():
        data = request.get_json() or {}
        
        license_type = data.get('license_type', 'standard')
        customer_email = data.get('customer_email')
        customer_name = data.get('customer_name')
        max_devices = data.get('max_devices', 1)
        duration_days = data.get('duration_days', 365)
        notes = data.get('notes')
        
        try:
            result = db.create_license(
                license_type=license_type,
                customer_email=customer_email,
                customer_name=customer_name,
                max_devices=max_devices,
                duration_days=duration_days,
                notes=notes
            )
            
            db.add_audit_log('license_created', 
                           license_key=result['license_key'],
                           admin_user=session.get('admin_username'),
                           details=f"Type: {license_type}, Email: {customer_email}",
                           ip_address=request.remote_addr)
            
            return jsonify({'success': True, 'license': result})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 400
    
    @app.route('/api/licenses/<license_key>', methods=['GET'])
    @login_required
    def api_get_license(license_key):
        license_data = db.get_license(license_key)
        if not license_data:
            return jsonify({'error': 'License not found'}), 404
        
        license_data['devices'] = db.get_device_activations(license_key)
        return jsonify(license_data)
    
    @app.route('/api/licenses/<license_key>', methods=['DELETE'])
    @login_required
    def api_revoke_license(license_key):
        data = request.get_json() or {}
        reason = data.get('reason', 'Revoked by admin')
        
        if db.revoke_license(license_key, reason):
            db.add_audit_log('license_revoked',
                           license_key=license_key,
                           admin_user=session.get('admin_username'),
                           details=reason,
                           ip_address=request.remote_addr)
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'License not found'}), 404
    
    @app.route('/api/licenses/<license_key>/extend', methods=['POST'])
    @login_required
    def api_extend_license(license_key):
        data = request.get_json() or {}
        days = data.get('days', 30)
        
        if db.extend_license(license_key, days):
            db.add_audit_log('license_extended',
                           license_key=license_key,
                           admin_user=session.get('admin_username'),
                           details=f"Extended by {days} days",
                           ip_address=request.remote_addr)
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'License not found'}), 404
    
    @app.route('/api/licenses/<license_key>/reactivate', methods=['POST'])
    @login_required
    def api_reactivate_license(license_key):
        if db.reactivate_license(license_key):
            db.add_audit_log('license_reactivated',
                           license_key=license_key,
                           admin_user=session.get('admin_username'),
                           ip_address=request.remote_addr)
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'License not found'}), 404
    
    @app.route('/api/licenses/<license_key>/reset-devices', methods=['POST'])
    @login_required
    def api_reset_devices(license_key):
        count = db.reset_device_activations(license_key)
        db.add_audit_log('devices_reset',
                        license_key=license_key,
                        admin_user=session.get('admin_username'),
                        details=f"Reset {count} device(s)",
                        ip_address=request.remote_addr)
        return jsonify({'success': True, 'devices_removed': count})
    
    @app.route('/api/stats', methods=['GET'])
    @login_required
    def api_get_stats():
        stats = db.get_license_stats()
        return jsonify(stats)
    
    @app.route('/api/licenses/<license_key>/reset', methods=['POST'])
    @login_required
    def api_reset_devices_alt(license_key):
        """Alternative route for resetting devices"""
        count = db.reset_device_activations(license_key)
        db.add_audit_log('devices_reset',
                        license_key=license_key,
                        admin_user=session.get('admin_username'),
                        details=f"Reset {count} device(s)",
                        ip_address=request.remote_addr)
        return jsonify({'success': True, 'devices_removed': count})
    
    @app.route('/api/licenses/<license_key>/revoke', methods=['POST'])
    @login_required
    def api_revoke_license_alt(license_key):
        """Alternative route for revoking licenses"""
        if db.revoke_license(license_key, 'Revoked by admin'):
            db.add_audit_log('license_revoked',
                           license_key=license_key,
                           admin_user=session.get('admin_username'),
                           ip_address=request.remote_addr)
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'License not found'}), 404
    
    @app.route('/api/licenses/<license_key>/devices', methods=['GET'])
    @login_required
    def api_get_devices(license_key):
        """Get device activations for a license"""
        devices = db.get_device_activations(license_key)
        return jsonify({'devices': devices})
    
    @app.route('/api/audit', methods=['GET'])
    @login_required
    def api_get_audit_log():
        """Get paginated audit log"""
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 25, type=int)
        action = request.args.get('action')
        search = request.args.get('search')
        
        result = db.get_audit_logs(page=page, per_page=per_page, action=action, search=search)
        return jsonify(result)
    
    @app.route('/api/admin/password', methods=['POST'])
    @login_required
    def api_change_password():
        """Change admin password"""
        data = request.get_json() or {}
        current_password = data.get('current_password')
        new_password = data.get('new_password')
        
        if not current_password or not new_password:
            return jsonify({'success': False, 'error': 'Both passwords required'}), 400
        
        if len(new_password) < 8:
            return jsonify({'success': False, 'error': 'Password must be at least 8 characters'}), 400
        
        username = session.get('admin_username')
        if db.verify_admin(username, current_password):
            if db.update_admin_password(username, new_password):
                db.add_audit_log('password_changed', admin_user=username, ip_address=request.remote_addr)
                return jsonify({'success': True})
            return jsonify({'success': False, 'error': 'Failed to update password'}), 500
        return jsonify({'success': False, 'error': 'Current password is incorrect'}), 400
    
    @app.route('/api/validate', methods=['POST'])
    def api_validate_license():
        """Public endpoint for clients to validate their license"""
        data = request.get_json() or {}
        license_key = data.get('license_key')
        device_id = data.get('device_id')
        
        if not license_key:
            return jsonify({'valid': False, 'error': 'License key required'}), 400
        
        result = db.validate_license(license_key, device_id)
        
        if result['valid']:
            db.add_audit_log('license_validated',
                           license_key=license_key,
                           details=f"Device: {device_id}",
                           ip_address=request.remote_addr)
        
        return jsonify(result)
    
    @app.route('/api/v1/license/activate', methods=['POST'])
    def api_activate_license():
        """Client activation endpoint - activates a license on a device"""
        data = request.get_json() or {}
        license_key = data.get('license_key')
        machine_id = data.get('machine_id')
        machine_info = data.get('machine_info', {})
        
        if not license_key:
            return jsonify({'success': False, 'is_valid': False, 'error': 'License key required'}), 400
        if not machine_id:
            return jsonify({'success': False, 'is_valid': False, 'error': 'Machine ID required'}), 400
        
        result = db.activate_license(license_key, machine_id, machine_info)
        
        if result.get('success'):
            db.add_audit_log('license_activated',
                           license_key=license_key,
                           details=f"Machine: {machine_id[:16]}...",
                           ip_address=request.remote_addr)
        
        return jsonify(result)
    
    @app.route('/api/v1/license/validate', methods=['POST'])
    def api_validate_license_v1():
        """Client validation endpoint - validates a license"""
        data = request.get_json() or {}
        license_key = data.get('license_key')
        machine_id = data.get('machine_id')
        
        if not license_key:
            return jsonify({'success': False, 'is_valid': False, 'error': 'License key required'}), 400
        
        result = db.validate_license_for_client(license_key, machine_id)
        return jsonify(result)
    
    @app.route('/api/v1/license/trial', methods=['POST'])
    def api_request_trial():
        """Client trial request endpoint"""
        data = request.get_json() or {}
        machine_id = data.get('machine_id')
        machine_info = data.get('machine_info', {})
        
        if not machine_id:
            return jsonify({'success': False, 'error': 'Machine ID required'}), 400
        
        result = db.create_trial_license(machine_id, machine_info)
        
        if result.get('success'):
            db.add_audit_log('trial_created',
                           license_key=result.get('license_key'),
                           details=f"Machine: {machine_id[:16]}...",
                           ip_address=request.remote_addr)
        
        return jsonify(result)
    
    @app.route('/api/v1/license/deactivate', methods=['POST'])
    def api_deactivate_license():
        """Client deactivation endpoint"""
        data = request.get_json() or {}
        license_key = data.get('license_key')
        machine_id = data.get('machine_id')
        
        if not license_key or not machine_id:
            return jsonify({'success': False, 'error': 'License key and machine ID required'}), 400
        
        result = db.deactivate_device(license_key, machine_id)
        
        if result.get('success'):
            db.add_audit_log('device_deactivated',
                           license_key=license_key,
                           details=f"Machine: {machine_id[:16]}...",
                           ip_address=request.remote_addr)
        
        return jsonify(result)
    
    @app.after_request
    def add_cache_headers(response):
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response
    
    return app
