import os
from flask_mail import Mail
from flask import Flask, request
from flask_mysqldb import MySQL
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

mail = Mail()
mysql = MySQL()

# Create limiter globally (NOT inside function)
def rate_limit_key():
    # Gunicorn is bound to loopback behind Nginx (see DEPLOYMENT_GUIDE.md).
    # Trust Nginx's overwritten X-Real-IP only for a loopback peer; ignore
    # forwarded headers from every other peer.
    peer = request.remote_addr
    if peer in ('127.0.0.1', '::1'):
        forwarded_ip = request.headers.get('X-Real-IP')
        if forwarded_ip:
            return forwarded_ip
    return get_remote_address()


limiter = Limiter(key_func=rate_limit_key)

def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)

    # Load environment variables from .env file if available
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    app.config.from_mapping(
        SECRET_KEY=os.environ.get('SECRET_KEY', 'dev-sarkari-sahayata-secret-key-2026'),
        # Gunicorn workers do not share this backend. Use shared storage (for
        # example Redis) before relying on limits across multiple workers.
        RATELIMIT_STORAGE_URI='memory://',
        MYSQL_HOST=os.environ.get('MYSQL_HOST', '127.0.0.1'),
        MYSQL_USER=os.environ.get('MYSQL_USER', 'root'),
        MYSQL_PASSWORD=os.environ.get('MYSQL_PASSWORD', ''),
        MYSQL_DB=os.environ.get('MYSQL_DB', 'defaultdb'),
        MYSQL_PORT=int(os.environ.get('MYSQL_PORT', 3306)),
        MAIL_SERVER=os.environ.get('MAIL_SERVER', 'smtp.gmail.com'),
        MAIL_PORT=int(os.environ.get('MAIL_PORT', 465)),
        MAIL_USE_TLS=os.environ.get('MAIL_USE_TLS', 'false').lower() in ['true', 'on', '1'],
        MAIL_USE_SSL=os.environ.get('MAIL_USE_SSL', 'true').lower() in ['true', 'on', '1'],
        MAIL_DEBUG=os.environ.get('MAIL_DEBUG', 'false').lower() in ['true', 'on', '1'],
        MAIL_USERNAME=os.environ.get('MAIL_USERNAME', ''),
        MAIL_PASSWORD=os.environ.get('MAIL_PASSWORD', ''),
        MAIL_DEFAULT_SENDER=os.environ.get('MAIL_DEFAULT_SENDER', os.environ.get('MAIL_USERNAME', '')),
        MASTER_USER=os.environ.get('MASTER_USER', 'sarkariadmin1'),
        MASTER_PASSWORD=os.environ.get('MASTER_PASSWORD', 'sarkari123'),
    )

    if test_config is None:
        app.config.from_pyfile('config.py', silent=True)
    else:
        app.config.from_mapping(test_config)

    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    # Initialize extensions
    mail.init_app(app)
    mysql.init_app(app)
    limiter.init_app(app)

    @app.errorhandler(429)
    def rate_limit_exceeded(error):
        return "Too many login attempts. Please wait a minute and try again.", 429

    from . import db
    db.init_app(app)

    from . import auth
    app.register_blueprint(auth.bp)

    from . import home
    app.register_blueprint(home.bp)
    app.add_url_rule('/', endpoint='index')

    from . import categories
    app.register_blueprint(categories.bp)

    from . import chatbot
    app.register_blueprint(chatbot.bp)

    from . import admin
    app.register_blueprint(admin.admin_bp)

    # ── Jinja2 custom filter: parse JSON in templates ──
    import json as _json
    def from_json_filter(value):
        if not value:
            return None
        try:
            return _json.loads(value)
        except Exception:
            return None
    app.jinja_env.filters['from_json'] = from_json_filter

    return app
