from flask import Flask
from flask_login import LoginManager
from config import Config
import os

from app.models import db

login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message_category = 'info'


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    login_manager.init_app(app)

    from app.models import User, Mine, Node, SensorData, AnalysisLog, Alert

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # Register blueprints
    from app.routes.auth import auth_bp
    from app.routes.main import main_bp
    from app.routes.admin import admin_bp
    from app.routes.user import user_bp
    from app.routes.api import api_bp
    from app.routes.api_ml import api_ml_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(user_bp, url_prefix='/user')
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(api_ml_bp, url_prefix='/api/ml')

    # ---- Create tables FIRST ----
    with app.app_context():
        if app.config.get('AUTO_CREATE_DB'):
            db.create_all()

        # Seed admin if missing OR update password if admin exists but can't log in
        admin = User.query.filter_by(role='admin').first()
        if admin is None:
            admin = User(
                username='admin',
                email='admin@mine.com',
                role='admin',
                is_blacklisted=False,
            )
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
            print("✅ Default admin created: email='admin@mine.com', username='admin', password='admin123'")
        else:
            # Ensure admin is not blacklisted
            if admin.is_blacklisted:
                admin.is_blacklisted = False
                db.session.commit()
                print("⚠️  Admin was blacklisted — un-blacklisted.")
            # Safety: re-set password if you forgot it
            # (uncomment the two lines below ONLY if you're locked out)
            # admin.set_password('admin123')
            # db.session.commit()

    # ---- Start background workers AFTER tables exist ----
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not app.debug:
        try:
            from app.ml_engine import start_background_engine
            start_background_engine(app)
        except Exception as e:
            print(f"[ML-BG] Failed to start: {e}")

        try:
            from app.serial_bridge import start_serial_bridge
            start_serial_bridge(app)
        except Exception as e:
            print(f"[SERIAL] Failed to start: {e}")

    return app