"""
India Bot Flask Application
Web control panel for India market trading bot
"""

from flask import Flask, render_template, jsonify, request, make_response
import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from gui_app import database as db

app = Flask(__name__, 
            template_folder='templates',
            static_folder='static')
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'india-bot-secret-key-change-me')

_bot_instance = None

def set_bot_instance(bot):
    """Register bot instance for API access"""
    global _bot_instance
    _bot_instance = bot

def register_routes(app):
    """Register all routes for India bot"""
    
    @app.route('/')
    def index():
        return render_template('index.html')
    
    @app.route('/channels')
    def channels():
        return render_template('channels_india.html')
    
    @app.route('/api/health')
    def api_health():
        return jsonify({
            'status': 'ok',
            'bot_connected': _bot_instance is not None,
            'market': 'INDIA'
        })
    
    @app.route('/api/channels', methods=['GET'])
    def api_get_channels():
        """Get all India channels"""
        try:
            channels = db.get_telegram_channels()
            return jsonify({'success': True, 'channels': channels})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/channels/<chat_id>', methods=['GET'])
    def api_get_channel(chat_id):
        """Get channel settings"""
        try:
            settings = db.get_channel_settings(chat_id)
            if settings:
                return jsonify({'success': True, 'channel': settings})
            return jsonify({'success': False, 'error': 'Channel not found'}), 404
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/conditional-orders', methods=['GET'])
    def api_get_conditional_orders():
        """Get conditional orders"""
        try:
            status = request.args.get('status')
            orders = db.get_conditional_orders(status)
            return jsonify({'success': True, 'orders': orders})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/broker/status', methods=['GET'])
    def api_broker_status():
        """Get broker connection status"""
        status = {
            'upstox': {'connected': False, 'status': 'disconnected'},
            'zerodha': {'connected': False, 'status': 'disconnected'},
            'dhanq': {'connected': False, 'status': 'disconnected'}
        }
        
        if _bot_instance:
            upstox = getattr(_bot_instance, 'upstox_broker', None)
            if upstox and getattr(upstox, 'connected', False):
                status['upstox'] = {'connected': True, 'status': 'connected'}
            
            zerodha = getattr(_bot_instance, 'zerodha_broker', None)
            if zerodha and getattr(zerodha, 'connected', False):
                status['zerodha'] = {'connected': True, 'status': 'connected'}
            
            dhanq = getattr(_bot_instance, 'dhanq_broker', None)
            if dhanq and getattr(dhanq, 'connected', False):
                status['dhanq'] = {'connected': True, 'status': 'connected'}
        
        return jsonify(status)
    
    @app.route('/api/broker/<broker_name>/credentials', methods=['GET'])
    def api_get_broker_credentials(broker_name):
        """Get broker credentials (masked)"""
        try:
            creds = db.get_broker_credentials(broker_name)
            if creds:
                masked = {}
                for key, value in creds.items():
                    if value and isinstance(value, str) and len(value) > 4:
                        masked[key] = value[:4] + '*' * (len(value) - 4)
                    else:
                        masked[key] = '****'
                return jsonify({'success': True, 'credentials': masked})
            return jsonify({'success': True, 'credentials': {}})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/broker/<broker_name>/credentials', methods=['POST'])
    def api_save_broker_credentials(broker_name):
        """Save broker credentials"""
        try:
            data = request.get_json()
            db.save_broker_credentials(broker_name, data)
            return jsonify({'success': True, 'message': f'{broker_name} credentials saved'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    def run_async_in_bot_loop(coro):
        """Run async coroutine in bot's event loop from Flask thread"""
        import asyncio
        import concurrent.futures
        if _bot_instance and hasattr(_bot_instance, 'event_loop') and _bot_instance.event_loop:
            loop = _bot_instance.event_loop
            future = asyncio.run_coroutine_threadsafe(coro, loop)
            try:
                return future.result(timeout=10.0)
            except concurrent.futures.TimeoutError:
                return None
        return None
    
    @app.route('/api/upstox/orders', methods=['GET'])
    def api_upstox_orders():
        """Get Upstox order book"""
        try:
            if _bot_instance and hasattr(_bot_instance, 'upstox_broker'):
                broker = _bot_instance.upstox_broker
                if broker and broker.connected:
                    orders = run_async_in_bot_loop(broker.get_order_book())
                    if orders is not None:
                        return jsonify({'success': True, 'orders': orders})
                    return jsonify({'success': False, 'error': 'Timeout fetching orders'})
            return jsonify({'success': False, 'error': 'Upstox not connected'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/upstox/positions', methods=['GET'])
    def api_upstox_positions():
        """Get Upstox positions"""
        try:
            if _bot_instance and hasattr(_bot_instance, 'upstox_broker'):
                broker = _bot_instance.upstox_broker
                if broker and broker.connected:
                    positions = run_async_in_bot_loop(broker.get_positions())
                    if positions is not None:
                        return jsonify({'success': True, 'positions': positions})
                    return jsonify({'success': False, 'error': 'Timeout fetching positions'})
            return jsonify({'success': False, 'error': 'Upstox not connected'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/signals', methods=['GET'])
    def api_get_signals():
        """Get India signals"""
        try:
            with db.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM india_signals ORDER BY created_at DESC LIMIT 100')
                rows = cursor.fetchall()
                signals = [dict(row) for row in rows]
            return jsonify({'success': True, 'signals': signals})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/pending-orders', methods=['GET'])
    def api_pending_orders():
        """Get pending Upstox orders"""
        try:
            orders = db.get_upstox_pending_orders()
            return jsonify({'success': True, 'orders': orders})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

register_routes(app)

def run_app(host='0.0.0.0', port=5000, debug=False):
    """Run the Flask application"""
    print(f"[INDIA BOT] Starting web server on http://{host}:{port}")
    app.run(host=host, port=port, debug=debug, use_reloader=False)

if __name__ == '__main__':
    run_app(debug=True)
