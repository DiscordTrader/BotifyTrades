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
    
    app.secret_key = os.environ.get('FLASK_SECRET_KEY', os.urandom(32).hex())
    app.config['SESSION_COOKIE_SECURE'] = False
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)
    
    print("[ADMIN] ✓ License-only admin panel initialized")
    print("[ADMIN] ✓ No trading functionality loaded")
    
    @app.route('/')
    def index():
        if 'admin_logged_in' in session:
            return redirect(url_for('admin_licenses'))
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
                return redirect(url_for('admin_licenses'))
            else:
                error = 'Invalid username or password'
        
        return render_template('admin_login.html', error=error)
    
    @app.route('/logout')
    def admin_logout():
        username = session.get('admin_username')
        if username:
            db.add_audit_log('logout', admin_user=username, ip_address=request.remote_addr)
        session.clear()
        return redirect(url_for('admin_login'))
    
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
                    return redirect(url_for('admin_licenses'))
                else:
                    error = 'Failed to create admin account'
        
        return render_template('admin_setup.html', error=error)
    
    @app.route('/licenses')
    @login_required
    def admin_licenses():
        stats = db.get_license_stats()
        return render_template('admin_licenses.html', 
                              admin_username=session.get('admin_username'),
                              stats=stats)
    
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
    
    @app.after_request
    def add_cache_headers(response):
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response
    
    return app
