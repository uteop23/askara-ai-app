# app.py - FIXED COMPLETE VERSION
# All-in-one Flask application dengan semua fitur lengkap

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

# Import models
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

# Input validation schemas
class VideoProcessSchema(Schema):
    url = fields.Url(required=True, validate=validate.Length(max=500))

class UserSignupSchema(Schema):
    name = fields.Str(required=True, validate=validate.Length(min=2, max=100))
    email = fields.Email(required=True, validate=validate.Length(max=120))
    password = fields.Str(required=True, validate=validate.Length(min=8, max=128))

class UserLoginSchema(Schema):
    email = fields.Email(required=True, validate=validate.Length(max=120))
    password = fields.Str(required=True, validate=validate.Length(min=1, max=128))

class CountdownSettingsSchema(Schema):
    is_active = fields.Bool(required=True)
    target_datetime = fields.DateTime(allow_none=True)
    title = fields.Str(validate=validate.Length(min=1, max=200))
    subtitle = fields.Str(validate=validate.Length(min=1, max=500))
    background_style = fields.Str(validate=validate.OneOf(['gradient', 'particles', 'waves']))
    redirect_after_launch = fields.Str(validate=validate.Length(min=1, max=200))

class PromoCodeCreateSchema(Schema):
    code = fields.Str(required=True, validate=validate.Length(min=3, max=50))
    description = fields.Str(required=True, validate=validate.Length(min=5, max=200))
    discount_type = fields.Str(required=True, validate=validate.OneOf(['percentage', 'days', 'credits']))
    discount_value = fields.Float(required=True, validate=validate.Range(min=0, max=10000))
    max_uses = fields.Int(validate=validate.Range(min=1, max=100000), missing=100)
    expires_at = fields.DateTime(allow_none=True)

# Security constants
ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv', 'webm'}
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB
MAX_VIDEO_DURATION = 10800  # 3 hours

def create_app():
    app = Flask(__name__)
    
    # Configuration
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', secrets.token_hex(32))
    
    # Database configuration
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
        'pool_reset_on_return': 'commit'
    }
    
    # Caching configuration
    app.config['CACHE_TYPE'] = 'redis'
    app.config['CACHE_REDIS_URL'] = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    app.config['CACHE_DEFAULT_TIMEOUT'] = 300
    
    # Mail configuration
    app.config['MAIL_SERVER'] = os.getenv('SMTP_HOST', 'smtp.hostinger.com')
    app.config['MAIL_PORT'] = int(os.getenv('SMTP_PORT', 465))
    app.config['MAIL_USE_SSL'] = True
    app.config['MAIL_USERNAME'] = os.getenv('SMTP_USER')
    app.config['MAIL_PASSWORD'] = os.getenv('SMTP_PASS')
    
    # Google configuration
    app.config['GOOGLE_CLIENT_ID'] = os.getenv('GOOGLE_CLIENT_ID')
    app.config['GOOGLE_CLIENT_SECRET'] = os.getenv('GOOGLE_CLIENT_SECRET')
    
    return app

# Create app instance
app = create_app()

# Initialize extensions
db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
mail = Mail(app)
cache = Cache(app)
ma = Marshmallow(app)

# Rate limiting
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

# Redis connection
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
    if gemini_api_key and gemini_api_key != 'your_gemini_api_key_here':
        genai.configure(api_key=gemini_api_key)
        logger.info("✅ Gemini AI configured")
    else:
        logger.warning("⚠️ GEMINI_API_KEY not configured")
except Exception as e:
    logger.warning(f"⚠️ Gemini AI configuration failed: {str(e)}")

@login_manager.user_loader
def load_user(user_id):
    try:
        return User.query.get(int(user_id))
    except Exception:
        return None

# Security helper functions
def validate_admin_access(require_super_admin=False):
    """Validate admin access with optional super admin requirement"""
    if not current_user.is_authenticated:
        logger.warning("Unauthenticated admin access attempt")
        return False, "Authentication required"
    
    if not current_user.is_admin:
        logger.warning("Non-admin user attempted admin access", user_email=current_user.email)
        return False, "Admin access required"
    
    if require_super_admin and current_user.email != 'ujangbawbaw@gmail.com':
        logger.warning("Non-super-admin attempted super admin action", user_email=current_user.email)
        return False, "Super admin access required"
    
    return True, "Access granted"

def monitor_system_resources():
    """Monitor system resources"""
    try:
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        if memory.percent > 90:
            logger.warning("High memory usage detected", memory_percent=memory.percent)
            
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

# Basic routes
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
    """Admin dashboard with integrated login"""
    if not current_user.is_admin or current_user.email != 'ujangbawbaw@gmail.com':
        logger.warning("Unauthorized admin access attempt", user_email=current_user.email)
        return redirect(url_for('index'))
    
    try:
        stats = get_admin_stats()
        return render_template('admin.html', **stats)
    except Exception as e:
        logger.error("Admin dashboard error", error=str(e))
        return render_template('admin.html',
                             total_users=0,
                             premium_users=0,
                             total_videos_processed=0,
                             total_clips_generated=0,
                             recent_users=[])

@app.route('/admin/login')
def admin_login():
    """Admin login page"""
    if current_user.is_authenticated and current_user.is_admin:
        return redirect(url_for('admin_dashboard'))
    return render_template('admin_login.html')

@cache.cached(timeout=300, key_prefix='admin_stats')
def get_admin_stats():
    """Get admin statistics with caching"""
    try:
        total_users = User.query.count()
        premium_users = User.query.filter_by(is_premium=True).count()
        total_videos_processed = VideoProcess.query.count()
        total_clips_generated = db.session.query(db.func.sum(VideoProcess.clips_generated)).scalar() or 0
        recent_users = User.query.order_by(User.created_at.desc()).limit(10).all()
        
        return {
            'total_users': total_users,
            'premium_users': premium_users,
            'total_videos_processed': total_videos_processed,
            'total_clips_generated': total_clips_generated,
            'recent_users': recent_users
        }
    except Exception as e:
        logger.error("Error getting admin stats", error=str(e))
        return {
            'total_users': 0,
            'premium_users': 0,
            'total_videos_processed': 0,
            'total_clips_generated': 0,
            'recent_users': []
        }

# API endpoints
@app.route('/api/config/google-client-id', methods=['GET'])
@cache.cached(timeout=3600)
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
            'is_premium': current_user.is_premium_active(),
            'is_admin': current_user.is_admin
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
def google_auth():
    """Google OAuth authentication"""
    if limiter:
        limiter.limit("10 per minute")(lambda: None)()
    
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
        
        # Validate email
        if '@' not in email or len(email) > 120:
            return jsonify({'error': 'Invalid email format'}), 400
        
        # Find or create user
        try:
            user = User.query.filter_by(google_id=google_id).first()
            if not user:
                user = User.query.filter_by(email=email).first()
                if user:
                    user.google_id = google_id
                else:
                    user = User(
                        email=email,
                        name=name,
                        google_id=google_id,
                        email_verified=True,
                        credits=30,
                        is_admin=(email == 'ujangbawbaw@gmail.com')
                    )
                    db.session.add(user)
            
            user.last_login = datetime.utcnow()
            db.session.commit()
            
            logger.info("Google auth success", user_email=email)
            
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
            'is_premium': user.is_premium_active(),
            'is_admin': user.is_admin
        })
        
    except Exception as e:
        logger.error("Google auth error", error=str(e))
        return jsonify({'error': 'Authentication failed'}), 500

@app.route('/api/auth/login', methods=['POST'])
def login():
    """Email/password login"""
    if limiter:
        limiter.limit("5 per minute")(lambda: None)()
    
    try:
        schema = UserLoginSchema()
        try:
            data = schema.load(request.json)
        except ValidationError as err:
            return jsonify({'error': 'Invalid input', 'details': err.messages}), 400
        
        email = data['email'].lower().strip()
        password = data['password']
        
        try:
            user = User.query.filter_by(email=email).first()
        except Exception as e:
            logger.error("Database error in login", error=str(e))
            return jsonify({'error': 'Database error'}), 500
            
        if not user or not user.check_password(password):
            logger.warning("Failed login attempt", email=email)
            return jsonify({'error': 'Invalid email or password'}), 401
        
        try:
            user.last_login = datetime.utcnow()
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error("Error updating last login", error=str(e))
        
        login_user(user, remember=True)
        
        logger.info("User login success", user_email=email)
        
        return jsonify({
            'email': user.email,
            'name': user.name,
            'credits': user.credits,
            'is_premium': user.is_premium_active(),
            'is_admin': user.is_admin
        })
        
    except Exception as e:
        logger.error("Login error", error=str(e))
        return jsonify({'error': 'Login failed'}), 500

@app.route('/api/signup/free', methods=['POST'])
def signup_free():
    """Free signup"""
    if limiter:
        limiter.limit("3 per minute")(lambda: None)()
    
    try:
        schema = UserSignupSchema()
        try:
            data = schema.load(request.json)
        except ValidationError as err:
            return jsonify({'error': 'Invalid input', 'details': err.messages}), 400
        
        email = data['email'].lower().strip()
        password = data['password']
        name = data['name'].strip()
        
        if len(name.split()) < 1:
            return jsonify({'error': 'Please provide a valid name'}), 400
        
        try:
            existing_user = User.query.filter_by(email=email).first()
        except Exception as e:
            logger.error("Database error checking existing user", error=str(e))
            return jsonify({'error': 'Database error'}), 500
            
        if existing_user:
            return jsonify({'error': 'Email already registered'}), 400
        
        try:
            user = User(
                email=email,
                name=name,
                credits=30,
                email_verified=False,
                is_admin=(email == 'ujangbawbaw@gmail.com')
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
@login_required
def process_video():
    """Process YouTube video (placeholder for now)"""
    if limiter:
        limiter.limit("2 per minute")(lambda: None)()
    
    try:
        # Monitor system resources
        resources = monitor_system_resources()
        if resources.get('memory_percent', 0) > 85:
            logger.warning("High memory usage, delaying video processing")
            return jsonify({'error': 'System busy, please try again later'}), 503
        
        schema = VideoProcessSchema()
        try:
            data = schema.load(request.json)
        except ValidationError as err:
            return jsonify({'error': 'Invalid input', 'details': err.messages}), 400
        
        url = data['url']
        
        if not validate_youtube_url(url):
            return jsonify({'error': 'Please provide a valid YouTube URL'}), 400
        
        # Check user credits
        if not current_user.is_premium_active() and current_user.credits < 10:
            logger.info("Insufficient credits", user_email=current_user.email, credits=current_user.credits)
            return jsonify({'error': 'Insufficient credits'}), 402
        
        # Generate task ID
        task_id = str(secrets.token_urlsafe(32))
        
        try:
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
        
        # For now, return a placeholder response
        # In the full version, this would start a Celery task
        return jsonify({
            'success': True,
            'task_id': task_id,
            'message': 'Video processing will be available after configuring Celery worker'
        })
        
    except Exception as e:
        logger.error("Process video error", error=str(e))
        return jsonify({'error': 'Failed to start video processing'}), 500

@app.route('/api/task-status/<task_id>', methods=['GET'])
def get_task_status(task_id):
    """Get processing task status"""
    if limiter:
        limiter.limit("30 per minute")(lambda: None)()
    
    try:
        if not task_id or len(task_id) > 100:
            return jsonify({'error': 'Invalid task ID'}), 400
        
        video_process = VideoProcess.query.filter_by(task_id=task_id).first()
        if not video_process:
            return jsonify({'error': 'Task not found'}), 404
        
        if video_process.status == 'completed':
            clips = VideoClip.query.filter_by(process_id=video_process.id).all()
            clips_data = [clip.to_dict() for clip in clips]
            
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

# ===== ADMIN API ENDPOINTS =====

@app.route('/api/countdown/settings', methods=['GET'])
@login_required
def get_countdown_settings():
    """Get countdown settings (admin only)"""
    is_valid, message = validate_admin_access()
    if not is_valid:
        return jsonify({'error': message}), 403
    
    try:
        countdown = CountdownSettings.get_current()
        
        result = {
            'is_active': countdown.is_active,
            'target_datetime': countdown.target_datetime.isoformat() if countdown.target_datetime else None,
            'title': countdown.title,
            'subtitle': countdown.subtitle,
            'background_style': countdown.background_style,
            'redirect_after_launch': countdown.redirect_after_launch
        }
        
        logger.info("Countdown settings retrieved", user_email=current_user.email)
        return jsonify(result)
        
    except Exception as e:
        logger.error("Error getting countdown settings", error=str(e), user_email=current_user.email)
        return jsonify({'error': 'Failed to get countdown settings'}), 500

@app.route('/api/countdown/settings', methods=['POST'])
@login_required
def update_countdown_settings():
    """Update countdown settings (admin only)"""
    is_valid, message = validate_admin_access()
    if not is_valid:
        return jsonify({'error': message}), 403
    
    try:
        # Validate input
        schema = CountdownSettingsSchema()
        try:
            data = schema.load(request.json)
        except ValidationError as err:
            logger.warning("Invalid countdown settings input", errors=err.messages, user_email=current_user.email)
            return jsonify({'error': 'Invalid input', 'details': err.messages}), 400
        
        countdown = CountdownSettings.get_current()
        
        if not countdown.id:
            db.session.add(countdown)
        
        # Update fields
        countdown.is_active = data.get('is_active', countdown.is_active)
        countdown.title = data.get('title', countdown.title)
        countdown.subtitle = data.get('subtitle', countdown.subtitle)
        countdown.background_style = data.get('background_style', countdown.background_style)
        countdown.redirect_after_launch = data.get('redirect_after_launch', countdown.redirect_after_launch)
        
        if data.get('target_datetime'):
            countdown.target_datetime = data['target_datetime']
        
        countdown.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        logger.info("Countdown settings updated", user_email=current_user.email, is_active=countdown.is_active)
        
        return jsonify({'success': True, 'message': 'Countdown settings updated'})
        
    except Exception as e:
        db.session.rollback()
        logger.error("Error updating countdown", error=str(e), user_email=current_user.email)
        return jsonify({'error': 'Failed to update countdown settings'}), 500

@app.route('/api/promo/codes', methods=['GET'])
@login_required
def get_promo_codes():
    """Get all promo codes (admin only)"""
    is_valid, message = validate_admin_access()
    if not is_valid:
        return jsonify({'error': message}), 403
    
    try:
        # Pagination
        page = request.args.get('page', 1, type=int)
        per_page = min(request.args.get('per_page', 20, type=int), 100)  # Max 100 per page
        
        codes_query = PromoCode.query.order_by(PromoCode.created_at.desc())
        codes_paginated = codes_query.paginate(page=page, per_page=per_page, error_out=False)
        
        codes_data = []
        for code in codes_paginated.items:
            code_dict = {
                'id': code.id,
                'code': code.code,
                'description': code.description,
                'discount_type': code.discount_type,
                'discount_value': code.discount_value,
                'max_uses': code.max_uses,
                'used_count': code.used_count,
                'is_active': code.is_active,
                'expires_at': code.expires_at.isoformat() if code.expires_at else None,
                'created_at': code.created_at.isoformat(),
                'usage_percentage': (code.used_count / code.max_uses * 100) if code.max_uses > 0 else 0
            }
            codes_data.append(code_dict)
        
        result = {
            'codes': codes_data,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': codes_paginated.total,
                'pages': codes_paginated.pages,
                'has_next': codes_paginated.has_next,
                'has_prev': codes_paginated.has_prev
            }
        }
        
        logger.info("Promo codes retrieved", user_email=current_user.email, count=len(codes_data))
        return jsonify(result)
        
    except Exception as e:
        logger.error("Error getting promo codes", error=str(e), user_email=current_user.email)
        return jsonify({'error': 'Failed to get promo codes'}), 500

@app.route('/api/promo/codes', methods=['POST'])
@login_required
def create_promo_code():
    """Create new promo code (admin only)"""
    is_valid, message = validate_admin_access()
    if not is_valid:
        return jsonify({'error': message}), 403
    
    try:
        # Validate input
        schema = PromoCodeCreateSchema()
        try:
            data = schema.load(request.json)
        except ValidationError as err:
            logger.warning("Invalid promo code input", errors=err.messages, user_email=current_user.email)
            return jsonify({'error': 'Invalid input', 'details': err.messages}), 400
        
        # Normalize code to uppercase
        code_value = data['code'].upper().strip()
        
        # Check if code already exists
        existing = PromoCode.query.filter_by(code=code_value).first()
        if existing:
            return jsonify({'error': 'Promo code already exists'}), 400
        
        # Create promo code
        promo_code = PromoCode(
            code=code_value,
            description=data['description'].strip(),
            discount_type=data['discount_type'],
            discount_value=float(data['discount_value']),
            max_uses=int(data.get('max_uses', 100)),
            created_by=current_user.id
        )
        
        if data.get('expires_at'):
            promo_code.expires_at = data['expires_at']
        
        db.session.add(promo_code)
        db.session.commit()
        
        logger.info("Promo code created", 
                   user_email=current_user.email, 
                   code=code_value, 
                   discount_type=data['discount_type'])
        
        return jsonify({
            'success': True, 
            'message': 'Promo code created successfully'
        })
        
    except Exception as e:
        db.session.rollback()
        logger.error("Error creating promo code", error=str(e), user_email=current_user.email)
        return jsonify({'error': 'Failed to create promo code'}), 500

@app.route('/api/promo/codes/<int:code_id>', methods=['DELETE'])
@login_required
def delete_promo_code(code_id):
    """Delete promo code (admin only)"""
    is_valid, message = validate_admin_access()
    if not is_valid:
        return jsonify({'error': message}), 403
    
    try:
        promo_code = PromoCode.query.get(code_id)
        if not promo_code:
            return jsonify({'error': 'Promo code not found'}), 404
        
        code_value = promo_code.code
        
        # Check if promo code has been used
        if promo_code.used_count > 0:
            # Instead of deleting, just deactivate
            promo_code.is_active = False
            db.session.commit()
            
            logger.info("Promo code deactivated", 
                       user_email=current_user.email, 
                       code=code_value, 
                       used_count=promo_code.used_count)
            
            return jsonify({
                'success': True, 
                'message': 'Promo code deactivated (had usage history)'
            })
        else:
            # Safe to delete if never used
            db.session.delete(promo_code)
            db.session.commit()
            
            logger.info("Promo code deleted", 
                       user_email=current_user.email, 
                       code=code_value)
            
            return jsonify({
                'success': True, 
                'message': 'Promo code deleted successfully'
            })
        
    except Exception as e:
        db.session.rollback()
        logger.error("Error deleting promo code", error=str(e), user_email=current_user.email)
        return jsonify({'error': 'Failed to delete promo code'}), 500

@app.route('/api/system/health', methods=['GET'])
@login_required
def get_system_health():
    """Get system health status (admin only)"""
    is_valid, message = validate_admin_access()
    if not is_valid:
        return jsonify({'error': message}), 403
    
    try:
        from utils import AskaraAIUtils
        
        utils = AskaraAIUtils()
        health_data = utils.check_system_health()
        
        # Save health check to database
        try:
            health_record = SystemHealth(
                overall_status=health_data.get('overall', 'unknown'),
                database_status=health_data.get('database', {}).get('status', 'unknown'),
                redis_status=health_data.get('redis', {}).get('status', 'unknown'),
                celery_status=health_data.get('celery', {}).get('status', 'unknown'),
                disk_usage=health_data.get('disk_space', {}).get('usage_percent'),
                memory_usage=health_data.get('memory_usage', {}).get('usage_percent'),
                cpu_usage=health_data.get('cpu_usage'),
                details=json.dumps(health_data)
            )
            
            db.session.add(health_record)
            db.session.commit()
            
        except Exception as e:
            logger.error("Failed to save health record", error=str(e))
        
        logger.info("System health checked", user_email=current_user.email, status=health_data.get('overall'))
        
        return jsonify(health_data)
        
    except Exception as e:
        logger.error("Error checking system health", error=str(e), user_email=current_user.email)
        return jsonify({'error': 'Failed to check system health'}), 500

@app.route('/api/system/stats', methods=['GET'])
@login_required
def get_system_stats():
    """Get system statistics (admin only)"""
    is_valid, message = validate_admin_access()
    if not is_valid:
        return jsonify({'error': message}), 403
    
    try:
        from utils import AskaraAIUtils
        
        utils = AskaraAIUtils()
        stats = utils.get_system_stats()
        
        logger.info("System stats retrieved", user_email=current_user.email)
        
        return jsonify(stats)
        
    except Exception as e:
        logger.error("Error getting system stats", error=str(e), user_email=current_user.email)
        return jsonify({'error': 'Failed to get system stats'}), 500

# Static file serving
@app.route('/clips/<filename>')
def serve_clip(filename):
    """Serve video clips"""
    if limiter:
        limiter.limit("20 per minute")(lambda: None)()
    
    try:
        if not filename or '..' in filename or '/' in filename:
            return jsonify({'error': 'Invalid filename'}), 400
        
        if not filename.lower().endswith('.mp4'):
            return jsonify({'error': 'Invalid file type'}), 400
        
        return send_from_directory('static/clips', filename)
    except Exception as e:
        logger.error("Error serving clip", filename=filename, error=str(e))
        return jsonify({'error': 'File not found'}), 404

@app.route('/uploads/<filename>')
def serve_upload(filename):
    """Serve uploaded files"""
    if limiter:
        limiter.limit("10 per minute")(lambda: None)()
    
    try:
        if not filename or '..' in filename or '/' in filename:
            return jsonify({'error': 'Invalid filename'}), 400
        
        return send_from_directory('static/uploads', filename)
    except Exception as e:
        logger.error("Error serving upload", filename=filename, error=str(e))
        return jsonify({'error': 'File not found'}), 404

# Error handlers
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

# Health check
@app.route('/health')
@cache.cached(timeout=60)
def health_check():
    try:
        db.engine.execute('SELECT 1')
        redis_status = "connected" if redis_client and redis_client.ping() else "disconnected"
        
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

# CLI commands
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
            admin.set_password('admin123456')
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

# Create directories
def create_directories():
    """Create necessary directories"""
    os.makedirs('static/clips', exist_ok=True)
    os.makedirs('static/uploads', exist_ok=True)
    os.makedirs('logs', exist_ok=True)
    os.makedirs('backup', exist_ok=True)

# Main execution
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
