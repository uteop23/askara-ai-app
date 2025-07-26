# app.py - SECURITY ENHANCED VERSION - Main Flask Application
# Enhanced dengan CSRF protection, input validation, caching, dan security improvements

import os
import logging
import secrets
import json
import magic
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_from_directory
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_mail import Mail, Message
from flask_wtf.csrf import CSRFProtect
from flask_caching import Cache
from flask_marshmallow import Marshmallow
from marshmallow import Schema, fields, validate, ValidationError
from dotenv import load_dotenv
import redis
import google.generativeai as genai
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from werkzeug.security import generate_password_hash, check_password_hash
import structlog
import psutil

# Load environment variables
load_dotenv()

# Import models from separate file (SOLUSI CIRCULAR IMPORT)
from app_models import db, User, VideoProcess, VideoClip, Payment, CountdownSettings, PromoCode, SystemHealth, PromoUsage

# Configure structured logging
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.ConsoleRenderer()
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    logger_factory=structlog.WriteLoggerFactory(),
    cache_logger_on_first_use=True,
)
logger = structlog.get_logger()

# Configure basic logging as fallback
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/var/www/askaraai/logs/app.log'),
        logging.StreamHandler()
    ]
)

# ===== INPUT VALIDATION SCHEMAS =====
class VideoProcessSchema(Schema):
    url = fields.Url(required=True, validate=validate.Length(max=500))

class UserSignupSchema(Schema):
    name = fields.Str(required=True, validate=validate.Length(min=2, max=100))
    email = fields.Email(required=True, validate=validate.Length(max=120))
    password = fields.Str(required=True, validate=validate.Length(min=8, max=128))

class UserLoginSchema(Schema):
    email = fields.Email(required=True, validate=validate.Length(max=120))
    password = fields.Str(required=True, validate=validate.Length(min=1, max=128))

class PromoCodeSchema(Schema):
    code = fields.Str(required=True, validate=validate.Length(min=3, max=50))
    description = fields.Str(required=True, validate=validate.Length(min=5, max=200))
    discount_type = fields.Str(required=True, validate=validate.OneOf(['percentage', 'days', 'credits']))
    discount_value = fields.Float(required=True, validate=validate.Range(min=0, max=100))
    max_uses = fields.Int(validate=validate.Range(min=1, max=10000))

# ===== SECURITY CONSTANTS =====
ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv', 'webm'}
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB
MAX_VIDEO_DURATION = 10800  # 3 hours

# ===== CREATE APP FUNCTION =====
def create_app():
    app = Flask(__name__)
    
    # Configuration
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', secrets.token_hex(32))
    
    # Database configuration with enhanced connection pool
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
        'pool_size': 10,
        'pool_reset_on_return': 'commit'  # Enhanced safety
    }
    
    # CSRF Protection
    app.config['WTF_CSRF_TIME_LIMIT'] = 3600  # 1 hour
    app.config['WTF_CSRF_SSL_STRICT'] = False  # Set to True in production with HTTPS
    
    # Caching configuration
    app.config['CACHE_TYPE'] = 'redis'
    app.config['CACHE_REDIS_URL'] = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    app.config['CACHE_DEFAULT_TIMEOUT'] = 300
    
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
csrf = CSRFProtect(app)
cache = Cache(app)
ma = Marshmallow(app)

# Rate limiting with enhanced security
try:
    limiter = Limiter(
        app=app,
        key_func=get_remote_address,
        default_limits=["1000 per day", "100 per hour"],
        storage_uri=os.getenv('REDIS_URL', 'redis://localhost:6379/0'),
        headers_enabled=True
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

# ===== SECURITY HELPER FUNCTIONS =====
def validate_video_file(file_content):
    """Validate video file content using python-magic"""
    try:
        # Check MIME type
        file_magic = magic.from_buffer(file_content[:1024], mime=True)
        
        if not file_magic.startswith('video/'):
            raise ValueError("File is not a valid video")
        
        # Check file size
        if len(file_content) > MAX_FILE_SIZE:
            raise ValueError(f"File too large. Maximum size: {MAX_FILE_SIZE // (1024*1024)}MB")
        
        return True
    except Exception as e:
        logger.error("File validation failed", error=str(e))
        raise ValueError(f"File validation failed: {str(e)}")

def monitor_system_resources():
    """Monitor system resources and raise alerts if necessary"""
    try:
        # Check memory usage
        memory = psutil.virtual_memory()
        if memory.percent > 90:
            logger.warning("High memory usage detected", memory_percent=memory.percent)
            
        # Check disk usage
        disk = psutil.disk_usage('/')
        if disk.percent > 90:
            logger.critical("Critical disk usage", disk_percent=disk.percent)
            
        return {
            'memory_percent': memory.percent,
            'disk_percent': disk.percent,
            'cpu_percent': psutil.cpu_percent(interval=1)
        }
    except Exception as e:
        logger.error("Resource monitoring failed", error=str(e))
        return {}

def validate_youtube_url(url):
    """Enhanced YouTube URL validation"""
    if not url or not isinstance(url, str):
        return False
    
    # Basic URL validation
    if not (url.startswith('http://') or url.startswith('https://')):
        return False
    
    # YouTube domain validation
    valid_domains = ['youtube.com', 'www.youtube.com', 'youtu.be', 'm.youtube.com']
    
    for domain in valid_domains:
        if domain in url:
            return True
    
    return False

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
        logger.error("Launch page error", error=str(e))
        return redirect('/')

@app.route('/admin')
@login_required
def admin_dashboard():
    """Admin dashboard - hanya untuk admin"""
    if not current_user.is_admin or current_user.email != 'ujangbawbaw@gmail.com':
        logger.warning("Unauthorized admin access attempt", user_email=current_user.email)
        return redirect(url_for('index'))
    
    try:
        # Get statistics with caching
        stats = get_admin_stats()
        
        return render_template('admin.html', **stats)
    except Exception as e:
        logger.error("Admin dashboard error", error=str(e))
        return render_template('admin.html',
                             total_users=0,
                             premium_users=0,
                             total_videos_processed=0,
                             total_clips_generated=0,
                             recent_users=[],
                             recent_processes=[])

@cache.cached(timeout=300, key_prefix='admin_stats')
def get_admin_stats():
    """Get admin statistics with caching"""
    try:
        total_users = User.query.count()
        premium_users = User.query.filter_by(is_premium=True).count()
        total_videos_processed = VideoProcess.query.count()
        total_clips_generated = db.session.query(db.func.sum(VideoProcess.clips_generated)).scalar() or 0
        recent_users = User.query.order_by(User.created_at.desc()).limit(10).all()
        recent_processes = VideoProcess.query.order_by(VideoProcess.created_at.desc()).limit(10).all()
        
        return {
            'total_users': total_users,
            'premium_users': premium_users,
            'total_videos_processed': total_videos_processed,
            'total_clips_generated': total_clips_generated,
            'recent_users': recent_users,
            'recent_processes': recent_processes
        }
    except Exception as e:
        logger.error("Error getting admin stats", error=str(e))
        return {
            'total_users': 0,
            'premium_users': 0,
            'total_videos_processed': 0,
            'total_clips_generated': 0,
            'recent_users': [],
            'recent_processes': []
        }

# ===== API ENDPOINTS WITH ENHANCED SECURITY =====

@app.route('/api/config/google-client-id', methods=['GET'])
@cache.cached(timeout=3600)  # Cache for 1 hour
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
    logger.info("User logout", user_email=current_user.email)
    logout_user()
    return jsonify({'success': True})

@app.route('/api/auth/google', methods=['POST'])
@limiter.limit("10 per minute")
def google_auth():
    """Google OAuth authentication with enhanced security"""
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
            logger.error("Google token verification failed", error=str(e))
            return jsonify({'error': 'Invalid token'}), 400
        
        # Get user info from token
        google_id = idinfo['sub']
        email = idinfo['email']
        name = idinfo['name']
        
        # Validate email domain (optional security measure)
        if '@' not in email or len(email) > 120:
            return jsonify({'error': 'Invalid email format'}), 400
        
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
            
            logger.info("Google auth success", user_email=email, new_user=user.id)
            
        except Exception as e:
            db.session.rollback()
            logger.error("Database error in Google auth", error=str(e))
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
        logger.error("Google auth error", error=str(e))
        return jsonify({'error': 'Authentication failed'}), 500

@app.route('/api/auth/login', methods=['POST'])
@limiter.limit("5 per minute")
def login():
    """Email/password login with input validation"""
    try:
        # Validate input
        schema = UserLoginSchema()
        try:
            data = schema.load(request.json)
        except ValidationError as err:
            return jsonify({'error': 'Invalid input', 'details': err.messages}), 400
        
        email = data['email'].lower().strip()
        password = data['password']
        
        # Find user
        try:
            user = User.query.filter_by(email=email).first()
        except Exception as e:
            logger.error("Database error in login", error=str(e))
            return jsonify({'error': 'Database error'}), 500
            
        if not user or not user.check_password(password):
            logger.warning("Failed login attempt", email=email)
            return jsonify({'error': 'Invalid email or password'}), 401
        
        # Update last login
        try:
            user.last_login = datetime.utcnow()
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error("Error updating last login", error=str(e))
        
        # Login user
        login_user(user, remember=True)
        
        logger.info("User login success", user_email=email)
        
        return jsonify({
            'email': user.email,
            'name': user.name,
            'credits': user.credits,
            'is_premium': user.is_premium_active()
        })
        
    except Exception as e:
        logger.error("Login error", error=str(e))
        return jsonify({'error': 'Login failed'}), 500

@app.route('/api/signup/free', methods=['POST'])
@limiter.limit("3 per minute")
def signup_free():
    """Free signup with enhanced validation"""
    try:
        # Validate input
        schema = UserSignupSchema()
        try:
            data = schema.load(request.json)
        except ValidationError as err:
            return jsonify({'error': 'Invalid input', 'details': err.messages}), 400
        
        email = data['email'].lower().strip()
        password = data['password']
        name = data['name'].strip()
        
        # Additional security checks
        if len(name.split()) < 1:
            return jsonify({'error': 'Please provide a valid name'}), 400
        
        # Check if user exists
        try:
            existing_user = User.query.filter_by(email=email).first()
        except Exception as e:
            logger.error("Database error checking existing user", error=str(e))
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
            
            logger.info("New user created", user_email=email)
            
        except Exception as e:
            db.session.rollback()
            logger.error("Error creating user", error=str(e))
            return jsonify({'error': 'Failed to create account'}), 500
        
        return jsonify({
            'success': True,
            'message': 'Account created successfully! You can now login.',
            'user_id': user.id
        })
        
    except Exception as e:
        logger.error("Error in free signup", error=str(e))
        return jsonify({'error': 'Failed to create account'}), 500

@app.route('/api/process-video', methods=['POST'])
@limiter.limit("2 per minute", per_method=True)
@limiter.limit("10 per hour", per_method=True)
@login_required
def process_video():
    """Process YouTube video with enhanced validation"""
    try:
        # Monitor system resources
        resources = monitor_system_resources()
        if resources.get('memory_percent', 0) > 85:
            logger.warning("High memory usage, delaying video processing")
            return jsonify({'error': 'System busy, please try again later'}), 503
        
        # Validate input
        schema = VideoProcessSchema()
        try:
            data = schema.load(request.json)
        except ValidationError as err:
            return jsonify({'error': 'Invalid input', 'details': err.messages}), 400
        
        url = data['url']
        
        # Enhanced YouTube URL validation
        if not validate_youtube_url(url):
            return jsonify({'error': 'Please provide a valid YouTube URL'}), 400
        
        # Check user credits for non-premium users
        if not current_user.is_premium_active() and current_user.credits < 10:
            logger.info("Insufficient credits", user_email=current_user.email, credits=current_user.credits)
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
            
            logger.info("Video process created", 
                       task_id=task_id, 
                       user_email=current_user.email,
                       url=url)
            
        except Exception as e:
            db.session.rollback()
            logger.error("Error creating video process", error=str(e))
            return jsonify({'error': 'Database error'}), 500
        
        # Start Celery task (lazy import to avoid circular import)
        try:
            from celery_app import process_video_task
            process_video_task.delay(video_process.id, url)
            logger.info("Celery task started", process_id=video_process.id)
        except Exception as e:
            logger.error("Error starting Celery task", error=str(e))
            return jsonify({'error': 'Failed to start processing'}), 500
        
        return jsonify({
            'success': True,
            'task_id': task_id,
            'message': 'Video processing started'
        })
        
    except Exception as e:
        logger.error("Process video error", error=str(e))
        return jsonify({'error': 'Failed to start video processing'}), 500

@app.route('/api/task-status/<task_id>', methods=['GET'])
@limiter.limit("30 per minute")
def get_task_status(task_id):
    """Get processing task status with enhanced security"""
    try:
        # Validate task_id format
        if not task_id or len(task_id) > 100:
            return jsonify({'error': 'Invalid task ID'}), 400
        
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
        logger.error("Task status error", error=str(e))
        return jsonify({'error': 'Failed to get task status'}), 500

# ===== STATIC FILE SERVING WITH SECURITY =====
@app.route('/clips/<filename>')
@limiter.limit("20 per minute")
def serve_clip(filename):
    """Serve video clips with security checks"""
    try:
        # Validate filename
        if not filename or '..' in filename or '/' in filename:
            return jsonify({'error': 'Invalid filename'}), 400
        
        # Check file extension
        if not filename.lower().endswith('.mp4'):
            return jsonify({'error': 'Invalid file type'}), 400
        
        return send_from_directory('static/clips', filename)
    except Exception as e:
        logger.error("Error serving clip", filename=filename, error=str(e))
        return jsonify({'error': 'File not found'}), 404

@app.route('/uploads/<filename>')
@limiter.limit("10 per minute")
def serve_upload(filename):
    """Serve uploaded files with security checks"""
    try:
        # Validate filename
        if not filename or '..' in filename or '/' in filename:
            return jsonify({'error': 'Invalid filename'}), 400
        
        return send_from_directory('static/uploads', filename)
    except Exception as e:
        logger.error("Error serving upload", filename=filename, error=str(e))
        return jsonify({'error': 'File not found'}), 404

# ===== ERROR HANDLERS =====
@app.errorhandler(404)
def not_found(error):
    return redirect(url_for('index'))

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    logger.error("Internal server error", error=str(error))
    return jsonify({'error': 'Internal server error'}), 500

@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({'error': 'Rate limit exceeded. Please try again later.'}), 429

@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    return jsonify({'error': 'CSRF token missing or invalid'}), 400

# ===== HEALTH CHECK =====
@app.route('/health')
@cache.cached(timeout=60)
def health_check():
    try:
        db.engine.execute('SELECT 1')
        redis_status = "connected" if redis_client and redis_client.ping() else "disconnected"
        
        # System resource check
        resources = monitor_system_resources()
        
        return jsonify({
            'status': 'healthy',
            'database': 'connected',
            'redis': redis_status,
            'timestamp': datetime.utcnow().isoformat(),
            'resources': resources
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
    """Initialize database with enhanced security"""
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
            # Set a secure password for admin
            admin.set_password(secrets.token_urlsafe(32))
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
