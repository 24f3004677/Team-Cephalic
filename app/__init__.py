from flask import Flask
from flask_login import LoginManager
from config import Config



# Import the shared db instance from models
from app.models import db

login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message_category = 'info'

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize extensions with the app
    db.init_app(app)
    
    
    login_manager.init_app(app)

    # Import models to ensure they are registered
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

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(user_bp, url_prefix='/user')
    app.register_blueprint(api_bp, url_prefix='/api')
    from app.routes.api_ml import api_ml_bp
    app.register_blueprint(api_ml_bp, url_prefix='/api/ml')

    import os
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not app.debug:
        from app.ml_engine import start_background_engine
        start_background_engine(app)
    # Optional: create tables and default admin
    with app.app_context():
        if app.config.get('AUTO_CREATE_DB'):
            db.create_all()

        # Ensure default admin exists
        if User.query.filter_by(role='admin').first() is None:
            admin = User(username='admin', email='admin@mine.com', role='admin')
            admin.set_password('admin123')  # default password
            db.session.add(admin)
            db.session.commit()
            print("Default admin created: username='admin', password='admin123'")

    return app