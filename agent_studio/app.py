"""
Agent Studio — Standalone Flask application.
Runs independently from BotifyTrades on its own port.
"""
import os
import secrets
from flask import Flask, request, make_response


def create_app():
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), 'templates'),
        static_folder=os.path.join(os.path.dirname(__file__), 'static'),
    )

    app.config['SECRET_KEY'] = os.environ.get('AGENT_STUDIO_SECRET', secrets.token_hex(32))
    app.config['JSON_SORT_KEYS'] = False
    app.config['TEMPLATES_AUTO_RELOAD'] = True

    @app.before_request
    def handle_preflight():
        if request.method == 'OPTIONS':
            resp = make_response()
            resp.headers['Access-Control-Allow-Origin'] = '*'
            resp.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-Requested-With'
            resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
            resp.headers['Access-Control-Max-Age'] = '3600'
            return resp

    @app.after_request
    def add_cors_headers(response):
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-Requested-With'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        return response

    from .routes import register_routes
    register_routes(app)

    return app
