# app.py - FIXED VERSION - Main Flask Application
# Semua masalah circular import dan missing endpoints diperbaiki

import os
import logging
import secrets
import json
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_from_directory
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_mail import Mail, Message
from dotenv import load_dotenv
import redis
import google.generativeai as genai
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from werkzeug.security import generate_password_hash, check_password_hash

# Tambahkan ke app.py
from flask_wtf.csrf import CSRFProtect

csrf = CSRFProtect(app)
# Load environment variables
load_dotenv()

# Import models from separate file (SOLUSI CIRCULAR IMPORT)
from app_models import db, User, VideoProcess, VideoClip, Payment, CountdownSettings, PromoCode, SystemHealth, PromoUsage

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/var/www/askaraai/logs/app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ===== CREATE APP FUNCTION =====
def create_app():
    app = Flask(__name__)
    
    # Configuration
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', secrets.token_hex(32))
    
    # Database configuration with better error handling
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        db_password = os.getenv('DB_PASSWORD')
        if not db_password:
            logger.critical("FATAL: DB_PASSWORD environment variable not set!")
            raise ValueError("DB_PASSWORD environment variable must be set!")
        database_url = f'mysql+pymysql://askaraai:{db_password}@localhost/askaraai_db'

    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_recycle': 3600,
        'pool_pre_ping': True,
        'pool_timeout': 30,
        'max_overflow': 20,
        'pool_size': 10
    }
    
    # Other configurations
    app.config['MAIL_SERVER'] = os.getenv('SMTP_HOST', 'smtp.hostinger.com')
    app.config['MAIL_PORT'] = int(os.getenv('SMTP_PORT', 465))
    app.config['MAIL_USE_SSL'] = True
    app.config['MAIL_USERNAME'] = os.getenv('SMTP_USER')
    app.config['MAIL_PASSWORD'] = os.getenv('SMTP_PASS')
    app.config['GOOGLE_CLIENT_ID'] = os.getenv('GOOGLE_CLIENT_ID')
    app.config['GOOGLE_CLIENT_SECRET'] = os.getenv('GOOGLE_CLIENT_SECRET')
    app.config['TRIPAY_API_KEY'] = os.getenv('TRIPAY_API_KEY')
    app.config['TRIPAY_PRIVATE_KEY'] = os.getenv('TRIPAY_PRIVATE_KEY')
    app.config['TRIPAY_MERCHANT_CODE'] = os.getenv('TRIPAY_MERCHANT_CODE')
    
    return app

# Create app instance
app = create_app()

# Initialize extensions
db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
mail = Mail(app)

# Rate limiting with better error handling
try:
    limiter = Limiter(
        app=app,
        key_func=get_remote_address,
        default_limits=["1000 per day", "100 per hour"],
        storage_uri=os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    )
    logger.info("✅ Rate limiter initialized")
except Exception as e:
    logger.warning(f"⚠️ Rate limiter failed to initialize: {str(e)}")
    limiter = None

# Redis connection with better error handling
try:
    redis_client = redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379/0'))
    redis_client.ping()
    logger.info("✅ Redis connection established")
except Exception as e:
    logger.warning(f"⚠️ Redis connection failed: {str(e)}")
    redis_client = None

# Configure Gemini AI
try:
    gemini_api_key = os.getenv('GEMINI_API_KEY')
    if gemini_api_key:
        genai.configure(api_key=gemini_api_key)
        logger.info("✅ Gemini AI configured")
    else:
        logger.warning("⚠️ GEMINI_API_KEY not found")
except Exception as e:
    logger.warning(f"⚠️ Gemini AI configuration failed: {str(e)}")

@login_manager.user_loader
def load_user(user_id):
    try:
        return User.query.get(int(user_id))
    except Exception:
        return None

# ===== BASIC ROUTES =====
@app.route('/')
def index():
    """Main landing page"""
    return render_template('index.html')

@app.route('/launch')
def launch_page():
    """Countdown launch page"""
    try:
        countdown_settings = CountdownSettings.get_current()
        
        # If countdown is not active or time has passed, redirect
        if not countdown_settings.is_active or countdown_settings.is_launch_time_passed():
            return redirect(countdown_settings.redirect_after_launch)
        
        return render_template('launch.html', countdown=countdown_settings)
    except Exception as e:
        logger.error(f"Launch page error: {str(e)}")
        return redirect('/')

@app.route('/admin')
@login_required
def admin_dashboard():
    """Admin dashboard - hanya untuk admin"""
    if not current_user.is_admin or current_user.email != 'ujangbawbaw@gmail.com':
        return redirect(url_for('index'))
    
    try:
        # Get statistics
        total_users = User.query.count()
        premium_users = User.query.filter_by(is_premium=True).count()
        total_videos_processed = VideoProcess.query.count()
        total_clips_generated = db.session.query(db.func.sum(VideoProcess.clips_generated)).scalar() or 0
        recent_users = User.query.order_by(User.created_at.desc()).limit(10).all()
        recent_processes = VideoProcess.query.order_by(VideoProcess.created_at.desc()).limit(10).all()
        
        return render_template('admin.html',
                             total_users=total_users,
                             premium_users=premium_users,
                             total_videos_processed=total_videos_processed,
                             total_clips_generated=total_clips_generated,
                             recent_users=recent_users,
                             recent_processes=recent_processes)
    except Exception as e:
        logger.error(f"Admin dashboard error: {str(e)}")
        return render_template('admin.html',
                             total_users=0,
                             premium_users=0,
                             total_videos_processed=0,
                             total_clips_generated=0,
                             recent_users=[],
                             recent_processes=[])

# ===== API ENDPOINTS =====

@app.route('/api/config/google-client-id', methods=['GET'])
def get_google_client_id():
    """Get Google Client ID for frontend"""
    return jsonify({'client_id': app.config.get('GOOGLE_CLIENT_ID')})

@app.route('/api/get-session', methods=['GET'])
def get_session():
    """Get current user session"""
    if current_user.is_authenticated:
        return jsonify({
            'email': current_user.email,
            'name': current_user.name,
            'credits': current_user.credits,
            'is_premium': current_user.is_premium_active()
        })
    return jsonify({'error': 'Not authenticated'}), 401

@app.route('/api/logout', methods=['POST'])
@login_required
def logout():
    """Logout user"""
    logout_user()
    return jsonify({'success': True})

@app.route('/api/auth/google', methods=['POST'])
def google_auth():
    """Google OAuth authentication"""
    try:
        data = request.json
        token = data.get('token')
        
        if not token:
            return jsonify({'error': 'Token is required'}), 400
        
        # Verify Google token
        try:
            idinfo = id_token.verify_oauth2_token(
                token, 
                google_requests.Request(), 
                app.config['GOOGLE_CLIENT_ID']
            )
            
            if idinfo['iss'] not in ['accounts.google.com', 'https://accounts.google.com']:
                raise ValueError('Wrong issuer.')
                
        except ValueError as e:
            logger.error(f"Google token verification failed: {str(e)}")
            return jsonify({'error': 'Invalid token'}), 400
        
        # Get user info from token
        google_id = idinfo['sub']
        email = idinfo['email']
        name = idinfo['name']
        
        # Find or create user
        try:
            user = User.query.filter_by(google_id=google_id).first()
            if not user:
                user = User.query.filter_by(email=email).first()
                if user:
                    # Link Google account to existing user
                    user.google_id = google_id
                else:
                    # Create new user
                    user = User(
                        email=email,
                        name=name,
                        google_id=google_id,
                        email_verified=True,
                        credits=30
                    )
                    db.session.add(user)
            
            user.last_login = datetime.utcnow()
            db.session.commit()
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Database error in Google auth: {str(e)}")
            return jsonify({'error': 'Database error'}), 500
        
        # Login user
        login_user(user, remember=True)
        
        return jsonify({
            'email': user.email,
            'name': user.name,
            'credits': user.credits,
            'is_premium': user.is_premium_active()
        })
        
    except Exception as e:
        logger.error(f"Google auth error: {str(e)}")
        return jsonify({'error': 'Authentication failed'}), 500

@app.route('/api/auth/login', methods=['POST'])
def login():
    """Email/password login"""
    try:
        data = request.json
        email = data.get('email', '').lower().strip()
        password = data.get('password', '')
        
        if not email or not password:
            return jsonify({'error': 'Email and password are required'}), 400
        
        # Find user
        try:
            user = User.query.filter_by(email=email).first()
        except Exception as e:
            logger.error(f"Database error in login: {str(e)}")
            return jsonify({'error': 'Database error'}), 500
            
        if not user or not user.check_password(password):
            return jsonify({'error': 'Invalid email or password'}), 401
        
        # Update last login
        try:
            user.last_login = datetime.utcnow()
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error updating last login: {str(e)}")
        
        # Login user
        login_user(user, remember=True)
        
        return jsonify({
            'email': user.email,
            'name': user.name,
            'credits': user.credits,
            'is_premium': user.is_premium_active()
        })
        
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        return jsonify({'error': 'Login failed'}), 500

@app.route('/api/signup/free', methods=['POST'])
def signup_free():
    """Free signup with email/password"""
    try:
        data = request.json
        
        email = data.get('email', '').lower().strip()
        password = data.get('password', '')
        name = data.get('name', '').strip()
        
        if not email or not password or not name:
            return jsonify({'error': 'All fields are required'}), 400
        
        # Check if user exists
        try:
            existing_user = User.query.filter_by(email=email).first()
        except Exception as e:
            logger.error(f"Database error checking existing user: {str(e)}")
            return jsonify({'error': 'Database error'}), 500
            
        if existing_user:
            return jsonify({'error': 'Email already registered'}), 400
        
        # Create new user
        try:
            user = User(
                email=email,
                name=name,
                credits=30,
                email_verified=False,
                verification_token=secrets.token_hex(32)
            )
            user.set_password(password)
            
            db.session.add(user)
            db.session.commit()
            
            logger.info(f"New user created: {email}")
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error creating user: {str(e)}")
            return jsonify({'error': 'Failed to create account'}), 500
        
        return jsonify({
            'success': True,
            'message': 'Account created successfully! You can now login.',
            'user_id': user.id
        })
        
    except Exception as e:
        logger.error(f"Error in free signup: {str(e)}")
        return jsonify({'error': 'Failed to create account'}), 500

@app.route('/api/process-video', methods=['POST'])
@login_required
def process_video():
    """Process YouTube video"""
    try:
        data = request.json
        url = data.get('url')
        
        if not url:
            return jsonify({'error': 'URL is required'}), 400
        
        # Validate YouTube URL
        if 'youtube.com' not in url and 'youtu.be' not in url:
            return jsonify({'error': 'Please provide a valid YouTube URL'}), 400
        
        # Check user credits for non-premium users
        if not current_user.is_premium_active() and current_user.credits < 10:
            return jsonify({'error': 'Insufficient credits'}), 402
        
        # Generate task ID
        task_id = str(secrets.token_urlsafe(32))
        
        try:
            # Create video process record
            video_process = VideoProcess(
                user_id=current_user.id,
                youtube_url=url,
                task_id=task_id,
                status='pending'
            )
            db.session.add(video_process)
            db.session.commit()
            
            logger.info(f"Video process created: {task_id} for user {current_user.email}")
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error creating video process: {str(e)}")
            return jsonify({'error': 'Database error'}), 500
        
        # Start Celery task (lazy import to avoid circular import)
        try:
            from celery_app import process_video_task
            process_video_task.delay(video_process.id, url)
            logger.info(f"Celery task started for process {video_process.id}")
        except Exception as e:
            logger.error(f"Error starting Celery task: {str(e)}")
            return jsonify({'error': 'Failed to start processing'}), 500
        
        return jsonify({
            'success': True,
            'task_id': task_id,
            'message': 'Video processing started'
        })
        
    except Exception as e:
        logger.error(f"Process video error: {str(e)}")
        return jsonify({'error': 'Failed to start video processing'}), 500

@app.route('/api/task-status/<task_id>', methods=['GET'])
def get_task_status(task_id):
    """Get processing task status"""
    try:
        # Get video process from database
        video_process = VideoProcess.query.filter_by(task_id=task_id).first()
        if not video_process:
            return jsonify({'error': 'Task not found'}), 404
        
        # Return status based on database record
        if video_process.status == 'completed':
            # Get clips
            clips = VideoClip.query.filter_by(process_id=video_process.id).all()
            clips_data = [clip.to_dict() for clip in clips]
            
            # Parse carousel posts
            carousel_posts = []
            if video_process.carousel_posts:
                try:
                    carousel_posts = json.loads(video_process.carousel_posts)
                except:
                    carousel_posts = video_process.carousel_posts.split('\n') if video_process.carousel_posts else []
            
            return jsonify({
                'state': 'SUCCESS',
                'result': {
                    'original_title': video_process.original_title,
                    'clips': clips_data,
                    'blog_article': video_process.blog_article,
                    'carousel_posts': carousel_posts
                }
            })
        
        elif video_process.status == 'failed':
            return jsonify({
                'state': 'FAILURE',
                'status': video_process.error_message or 'Processing failed'
            })
        
        else:
            # Return current status
            status_map = {
                'pending': 'PENDING',
                'downloading': 'PROGRESS',
                'processing': 'PROGRESS',
                'analyzing': 'PROGRESS',
                'creating_clips': 'PROGRESS'
            }
            
            return jsonify({
                'state': status_map.get(video_process.status, 'PENDING'),
                'status': f'Processing: {video_process.status}'
            })
        
    except Exception as e:
        logger.error(f"Task status error: {str(e)}")
        return jsonify({'error': 'Failed to get task status'}), 500

# ===== ADMIN API ENDPOINTS =====

@app.route('/api/countdown/settings', methods=['GET'])
@login_required
def get_countdown_settings():
    """Get countdown settings (admin only)"""
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        countdown = CountdownSettings.get_current()
        return jsonify({
            'is_active': countdown.is_active,
            'target_datetime': countdown.target_datetime.isoformat() if countdown.target_datetime else None,
            'title': countdown.title,
            'subtitle': countdown.subtitle,
            'background_style': countdown.background_style,
            'redirect_after_launch': countdown.redirect_after_launch
        })
    except Exception as e:
        logger.error(f"Error getting countdown settings: {str(e)}")
        return jsonify({'error': 'Failed to get countdown settings'}), 500

@app.route('/api/countdown/settings', methods=['POST'])
@login_required
def update_countdown_settings():
    """Update countdown settings (admin only)"""
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        data = request.json
        countdown = CountdownSettings.get_current()
        
        if not countdown.id:
            db.session.add(countdown)
        
        countdown.is_active = data.get('is_active', countdown.is_active)
        countdown.title = data.get('title', countdown.title)
        countdown.subtitle = data.get('subtitle', countdown.subtitle)
        countdown.background_style = data.get('background_style', countdown.background_style)
        countdown.redirect_after_launch = data.get('redirect_after_launch', countdown.redirect_after_launch)
        
        if data.get('target_datetime'):
            countdown.target_datetime = datetime.fromisoformat(data['target_datetime'].replace('Z', '+00:00'))
        
        countdown.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Countdown settings updated'})
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating countdown: {str(e)}")
        return jsonify({'error': 'Failed to update countdown settings'}), 500

@app.route('/api/system/health', methods=['GET'])
@login_required
def get_system_health():
    """Get system health status (admin only)"""
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        health_data = {
            'timestamp': datetime.utcnow().isoformat(),
            'database': {'status': 'healthy'},
            'redis': {'status': 'unknown'},
            'celery': {'status': 'unknown'},
            'overall': 'healthy'
        }
        
        # Test database
        try:
            db.engine.execute('SELECT 1')
            health_data['database']['status'] = 'healthy'
        except Exception as e:
            health_data['database']['status'] = 'unhealthy'
            health_data['database']['error'] = str(e)
            health_data['overall'] = 'unhealthy'
        
        # Test Redis
        if redis_client:
            try:
                redis_client.ping()
                health_data['redis']['status'] = 'healthy'
            except Exception as e:
                health_data['redis']['status'] = 'unhealthy'
                health_data['redis']['error'] = str(e)
        
        return jsonify(health_data)
        
    except Exception as e:
        logger.error(f"Error checking system health: {str(e)}")
        return jsonify({'error': 'Failed to check system health'}), 500

# ===== STATIC FILE SERVING =====
@app.route('/clips/<filename>')
def serve_clip(filename):
    """Serve video clips"""
    return send_from_directory('static/clips', filename)

@app.route('/uploads/<filename>')
def serve_upload(filename):
    """Serve uploaded files"""
    return send_from_directory('static/uploads', filename)

# ===== ERROR HANDLERS =====
@app.errorhandler(404)
def not_found(error):
    return redirect(url_for('index'))

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    logger.error(f"Internal server error: {str(error)}")
    return jsonify({'error': 'Internal server error'}), 500

# ===== HEALTH CHECK =====
@app.route('/health')
def health_check():
    try:
        db.engine.execute('SELECT 1')
        redis_status = "connected" if redis_client and redis_client.ping() else "disconnected"
        
        return jsonify({
            'status': 'healthy',
            'database': 'connected',
            'redis': redis_status,
            'timestamp': datetime.utcnow().isoformat()
        })
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }), 500

# ===== CLI COMMANDS =====
@app.cli.command()
def init_db():
    """Initialize database"""
    try:
        logger.info("🔄 Initializing database...")
        
        # Test connection
        db.engine.execute('SELECT 1')
        logger.info("✅ Database connection successful")
        
        # Create tables
        db.create_all()
        logger.info("✅ Database tables created successfully!")
        
        # Create admin user
        admin_email = 'ujangbawbaw@gmail.com'
        admin = User.query.filter_by(email=admin_email).first()
        
        if not admin:
            admin = User(
                email=admin_email,
                name='Admin',
                is_admin=True,
                email_verified=True,
                credits=999999,
                is_premium=True
            )
            db.session.add(admin)
            db.session.commit()
            logger.info(f"✅ Admin user created: {admin_email}")
        else:
            admin.is_admin = True
            admin.is_premium = True
            admin.credits = 999999
            db.session.commit()
            logger.info(f"✅ Admin user updated: {admin_email}")
            
        logger.info("🎉 Database initialization completed successfully!")
        
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {str(e)}")
        raise

# ===== CREATE DIRECTORIES =====
def create_directories():
    """Create necessary directories"""
    os.makedirs('static/clips', exist_ok=True)
    os.makedirs('static/uploads', exist_ok=True)
    os.makedirs('logs', exist_ok=True)

# ===== MAIN EXECUTION =====
if __name__ == '__main__':
    with app.app_context():
        try:
            # Test database connection
            db.engine.execute('SELECT 1')
            logger.info("✅ Database connection verified")
            
            # Create tables
            db.create_all()
            logger.info("✅ Database tables verified")
            
            # Create directories
            create_directories()
            logger.info("✅ Directories created")
            
        except Exception as e:
            logger.error(f"❌ Startup check failed: {str(e)}")
    
    debug_mode = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(debug=debug_mode, host='0.0.0.0', port=5000)
