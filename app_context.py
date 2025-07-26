import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

# Instance global
db = SQLAlchemy()
app = None

def create_app_context():
    """Create application context for Celery and other components"""
    global app
    
    if app is None:
        app = Flask(__name__)
        
        # Configuration
        app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-key')
        
        # Database configuration
        database_url = os.getenv('DATABASE_URL')
        if not database_url:
            db_password = os.getenv('DB_PASSWORD')
            if not db_password:
                raise ValueError("DB_PASSWORD environment variable must be set!")
            database_url = f'mysql+pymysql://askaraai:{db_password}@localhost/askaraai_db'

        app.config['SQLALCHEMY_DATABASE_URI'] = database_url
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        
        # Initialize extensions
        db.init_app(app)
    
    return app

def get_models():
    """Get database models"""
    # Import models here to avoid circular import
    from app_models import User, VideoProcess, VideoClip, Payment, CountdownSettings, PromoCode, SystemHealth, PromoUsage
    return User, VideoProcess, VideoClip, Payment, CountdownSettings, PromoCode, SystemHealth, PromoUsage
