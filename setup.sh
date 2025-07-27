#!/bin/bash

# AskaraAI FIXED Auto Setup Script untuk VPS
# Bug-free version dengan local backup (tanpa Google Drive/rclone)

set -e

echo "🚀 Memulai setup AskaraAI - FIXED VERSION..."

# --- Variabel ---
APP_DIR="/var/www/askaraai"
APP_USER="www-data"
DB_NAME="askaraai_db"
DB_USER="askaraai"
LOG_FILE="/tmp/askaraai_setup.log"

# Create log file
touch $LOG_FILE
exec 1> >(tee -a $LOG_FILE)
exec 2> >(tee -a $LOG_FILE >&2)

echo "📋 Setup started at $(date)"
echo "📂 Logs saved to: $LOG_FILE"

# Function untuk logging
log_info() {
    echo "ℹ️  [INFO] $1" | tee -a $LOG_FILE
}

log_error() {
    echo "❌ [ERROR] $1" | tee -a $LOG_FILE
}

log_success() {
    echo "✅ [SUCCESS] $1" | tee -a $LOG_FILE
}

# Function untuk check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    # Check if running as root
    if [[ $EUID -ne 0 ]]; then
        log_error "This script must be run as root (use sudo)"
        exit 1
    fi
    
    # Check Ubuntu/Debian
    if ! command -v apt &> /dev/null; then
        log_error "This script requires Ubuntu/Debian with apt package manager"
        exit 1
    fi
    
    # Check internet connectivity
    if ! ping -c 1 8.8.8.8 &> /dev/null; then
        log_error "No internet connection available"
        exit 1
    fi
    
    log_success "Prerequisites check passed"
}

# Function untuk generate secure password
generate_secure_password() {
    openssl rand -base64 32 | tr -d "=+/" | cut -c1-25
}

# Function untuk setup firewall
setup_firewall() {
    log_info "Setting up firewall..."
    
    # Install and configure UFW
    apt install -y ufw
    
    # Default policies
    ufw --force reset
    ufw default deny incoming
    ufw default allow outgoing
    
    # Essential services
    ufw allow ssh
    ufw allow 80/tcp
    ufw allow 443/tcp
    
    # Limit SSH connections
    ufw limit ssh
    
    # Enable firewall
    ufw --force enable
    
    log_success "Firewall configured"
}

# Function untuk setup fail2ban
setup_fail2ban() {
    log_info "Setting up fail2ban..."
    
    apt install -y fail2ban
    
    # Create custom jail configuration
    cat > /etc/fail2ban/jail.local << 'EOL'
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 3
backend = systemd

[sshd]
enabled = true
port = ssh
filter = sshd
logpath = /var/log/auth.log
maxretry = 3
bantime = 3600

[nginx-http-auth]
enabled = true
filter = nginx-http-auth
port = http,https
logpath = /var/log/nginx/error.log
maxretry = 3
bantime = 1800
EOL

    systemctl enable fail2ban
    systemctl start fail2ban
    
    log_success "Fail2ban configured"
}

# Enhanced system update
update_system() {
    log_info "Updating system..."
    
    # Update package lists
    apt update
    
    # Upgrade system
    DEBIAN_FRONTEND=noninteractive apt upgrade -y
    
    # Install security updates
    DEBIAN_FRONTEND=noninteractive apt install -y unattended-upgrades
    
    log_success "System updated"
}

# Install dependencies (TANPA RCLONE)
install_dependencies() {
    log_info "Installing dependencies..."
    
    # Essential packages
    apt install -y \
        python3 \
        python3-pip \
        python3-venv \
        python3-dev \
        build-essential \
        nginx \
        redis-server \
        mysql-server \
        git \
        curl \
        wget \
        openssl \
        software-properties-common \
        apt-transport-https \
        ca-certificates \
        gnupg \
        lsb-release \
        cron
    
    # Video processing
    apt install -y ffmpeg
    
    # Security tools
    apt install -y fail2ban ufw
    
    # Python packages globally (untuk system utilities)
    pip3 install python-dotenv
    
    log_success "Dependencies installed"
}

# MySQL setup
setup_mysql() {
    log_info "Setting up MySQL..."
    
    # Generate secure password
    DB_PASSWORD=$(generate_secure_password)
    echo "Generated DB Password: $DB_PASSWORD"
    
    # Save password securely
    echo "$DB_PASSWORD" > /tmp/db_password.txt
    chmod 600 /tmp/db_password.txt
    
    # Start MySQL service
    systemctl start mysql
    systemctl enable mysql
    
    # Secure MySQL installation
    mysql -e "DELETE FROM mysql.user WHERE User='';" 2>/dev/null || true
    mysql -e "DELETE FROM mysql.user WHERE User='root' AND Host NOT IN ('localhost', '127.0.0.1', '::1');" 2>/dev/null || true
    mysql -e "DROP DATABASE IF EXISTS test;" 2>/dev/null || true
    mysql -e "DELETE FROM mysql.db WHERE Db='test' OR Db='test\\_%';" 2>/dev/null || true
    
    # Create database and user
    mysql -e "CREATE DATABASE IF NOT EXISTS ${DB_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
    mysql -e "CREATE USER IF NOT EXISTS '${DB_USER}'@'localhost' IDENTIFIED BY '${DB_PASSWORD}';"
    mysql -e "GRANT ALL PRIVILEGES ON ${DB_NAME}.* TO '${DB_USER}'@'localhost';"
    mysql -e "FLUSH PRIVILEGES;"
    
    systemctl restart mysql
    
    log_success "MySQL configured"
}

# Setup Redis
setup_redis() {
    log_info "Setting up Redis..."
    
    # Basic Redis configuration
    sed -i "s/bind 127.0.0.1 ::1/bind 127.0.0.1/" /etc/redis/redis.conf 2>/dev/null || true
    sed -i "s/# maxmemory <bytes>/maxmemory 256mb/" /etc/redis/redis.conf 2>/dev/null || true
    sed -i "s/# maxmemory-policy noeviction/maxmemory-policy allkeys-lru/" /etc/redis/redis.conf 2>/dev/null || true
    
    systemctl restart redis-server
    systemctl enable redis-server
    
    log_success "Redis configured"
}

# Setup aplikasi
setup_application() {
    log_info "Setting up application..."
    
    # Create application directory
    mkdir -p ${APP_DIR}
    chown -R ${APP_USER}:${APP_USER} ${APP_DIR}
    chmod 755 ${APP_DIR}
    
    # Change to app directory
    cd ${APP_DIR}
    
    # Setup Python virtual environment
    sudo -u ${APP_USER} python3 -m venv venv
    sudo -u ${APP_USER} bash -c "source venv/bin/activate && pip install --upgrade pip"
    
    # Create requirements.txt if not exists
    if [ ! -f "requirements.txt" ]; then
        sudo -u ${APP_USER} tee requirements.txt > /dev/null << 'EOL'
Flask==2.3.3
Flask-SQLAlchemy==3.1.1
Flask-Login==0.6.3
Flask-Mail==0.9.1
Flask-Limiter==3.5.0
Flask-WTF==1.2.1
Flask-Caching==2.1.0
flask-marshmallow==0.15.0
PyMySQL==1.1.0
SQLAlchemy==2.0.23
celery[redis]==5.3.4
redis==5.0.1
google-generativeai==0.3.2
google-auth==2.23.4
yt-dlp==2023.11.16
moviepy==1.0.3
ffmpeg-python==0.2.0
Pillow==10.1.0
requests==2.31.0
cryptography==41.0.8
PyJWT==2.8.0
gunicorn==21.2.0
python-dotenv==1.0.0
python-dateutil==2.8.2
validators==0.22.0
marshmallow==3.20.1
psutil==5.9.6
EOL
    fi
    
    # Install Python requirements
    sudo -u ${APP_USER} bash -c "source venv/bin/activate && pip install -r requirements.txt"
    
    # Create necessary directories
    sudo -u ${APP_USER} mkdir -p static/clips static/uploads logs static/error templates backup
    chmod 755 static/clips static/uploads templates static/error backup
    chmod 750 logs
    
    log_success "Application setup completed"
}

# Create environment file (TANPA RCLONE CONFIG)
create_environment_file() {
    log_info "Creating environment file..."
    
    if [ ! -f ".env" ]; then
        # Generate secure keys
        SECRET_KEY=$(openssl rand -hex 32)
        JWT_SECRET_KEY=$(openssl rand -hex 32)
        
        # Get DB password
        DB_PASSWORD=$(cat /tmp/db_password.txt 2>/dev/null || echo "CHANGE_ME")
        
        sudo -u ${APP_USER} tee .env > /dev/null << EOL
# Flask Configuration
SECRET_KEY=${SECRET_KEY}
FLASK_ENV=production
FLASK_DEBUG=False

# Database Configuration
DATABASE_URL=mysql+pymysql://${DB_USER}:${DB_PASSWORD}@localhost/${DB_NAME}?charset=utf8mb4
DB_PASSWORD=${DB_PASSWORD}

# Redis Configuration
REDIS_URL=redis://localhost:6379/0

# Security Configuration
JWT_SECRET_KEY=${JWT_SECRET_KEY}
JWT_ACCESS_TOKEN_EXPIRES=3600

# Rate Limiting
RATE_LIMIT_PER_MINUTE=60
RATE_LIMIT_PER_DAY=1000
RATE_LIMIT_API_PER_MINUTE=5

# Gemini AI Configuration (HARUS DIISI MANUAL)
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-pro
GEMINI_MAX_TOKENS=8192
GEMINI_TEMPERATURE=0.7

# Google OAuth Configuration (HARUS DIISI MANUAL)
GOOGLE_CLIENT_ID=your_google_client_id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your_google_client_secret_here

# SMTP Configuration (OPSIONAL)
SMTP_HOST=smtp.hostinger.com
SMTP_PORT=465
SMTP_USER=support@askaraai.com
SMTP_PASS=your_smtp_password_here

# Tripay Configuration (OPSIONAL)
TRIPAY_API_KEY=your_tripay_api_key_here
TRIPAY_PRIVATE_KEY=your_tripay_private_key_here
TRIPAY_MERCHANT_CODE=your_tripay_merchant_code_here
TRIPAY_SANDBOX=false

# Application Configuration
DOMAIN=askaraai.com
BASE_URL=https://askaraai.com
MAX_UPLOAD_SIZE=500MB
ALLOWED_VIDEO_EXTENSIONS=mp4,avi,mov,mkv,webm
MAX_VIDEO_DURATION=10800
MAX_CLIPS_PER_VIDEO=20
DEFAULT_CLIP_DURATION=60

# Celery Configuration
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
CELERY_TIMEZONE=UTC

# Logging Configuration
LOG_LEVEL=INFO
LOG_FILE=/var/www/askaraai/logs/app.log
MAX_LOG_SIZE=10MB
LOG_BACKUP_COUNT=5

# Admin Configuration
ADMIN_EMAIL=ujangbawbaw@gmail.com

# Backup Configuration (LOCAL ONLY)
BACKUP_DIR=/var/www/askaraai/backup
BACKUP_RETENTION_DAYS=30

# Performance Configuration
FFMPEG_THREADS=4
MAX_CONCURRENT_PROCESSES=2
CACHE_DEFAULT_TIMEOUT=300
CACHE_REDIS_DB=1
SESSION_TIMEOUT=86400
PERMANENT_SESSION_LIFETIME=2592000

# Feature Flags
ENABLE_API_PUBLIC=true
ENABLE_PREMIUM_FEATURES=true
ENABLE_ADMIN_DASHBOARD=true
ENABLE_ANALYTICS=true
ENABLE_BACKUP=true

# Maintenance Mode
MAINTENANCE_MODE=false
MAINTENANCE_MESSAGE="Kami sedang melakukan pemeliharaan sistem. Mohon coba lagi dalam beberapa menit."

# Localization
DEFAULT_LANGUAGE=id
TIMEZONE=Asia/Jakarta
EOL

        chmod 600 .env
        chown ${APP_USER}:${APP_USER} .env
        
        log_success "Environment file created"
        log_info "Database Password: $DB_PASSWORD"
        log_info "⚠️  IMPORTANT: Edit .env file and add required API keys!"
    fi
}

# Create minimal app files
create_app_files() {
    log_info "Creating application files..."
    
    # Create app_models.py (FIXED)
    sudo -u ${APP_USER} tee app_models.py > /dev/null << 'EOL'
from datetime import datetime, timedelta
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import json

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    google_id = db.Column(db.String(100), unique=True, nullable=True, index=True)
    password_hash = db.Column(db.String(255), nullable=True)
    credits = db.Column(db.Integer, default=30, nullable=False)
    is_premium = db.Column(db.Boolean, default=False, nullable=False)
    premium_expires = db.Column(db.DateTime, nullable=True)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    last_login = db.Column(db.DateTime, nullable=True)
    email_verified = db.Column(db.Boolean, default=False, nullable=False)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)
    
    def is_premium_active(self):
        if not self.is_premium:
            return False
        if not self.premium_expires:
            return True
        return datetime.utcnow() < self.premium_expires
    
    def deduct_credits(self, amount=10):
        if self.is_premium_active():
            return True
        if self.credits >= amount:
            self.credits -= amount
            try:
                db.session.commit()
                return True
            except Exception:
                db.session.rollback()
                return False
        return False

class VideoProcess(db.Model):
    __tablename__ = 'video_processes'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    youtube_url = db.Column(db.String(500), nullable=False)
    task_id = db.Column(db.String(100), unique=True, nullable=False, index=True)
    status = db.Column(db.String(50), default='pending', nullable=False, index=True)
    original_title = db.Column(db.String(300), nullable=True)
    clips_generated = db.Column(db.Integer, default=0, nullable=False)
    blog_article = db.Column(db.Text, nullable=True)
    carousel_posts = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    error_message = db.Column(db.Text, nullable=True)

class VideoClip(db.Model):
    __tablename__ = 'video_clips'
    
    id = db.Column(db.Integer, primary_key=True)
    process_id = db.Column(db.Integer, db.ForeignKey('video_processes.id'), nullable=False, index=True)
    filename = db.Column(db.String(200), nullable=False, index=True)
    title = db.Column(db.String(300), nullable=True)
    duration = db.Column(db.Float, nullable=True)
    viral_score = db.Column(db.Float, default=0.0, nullable=False)
    start_time = db.Column(db.Float, nullable=True)
    end_time = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    def to_dict(self):
        return {
            'id': self.id,
            'filename': self.filename,
            'title': self.title,
            'duration': self.duration,
            'viral_score': self.viral_score,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'created_at': self.created_at.isoformat()
        }

class Payment(db.Model):
    __tablename__ = 'payments'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    tripay_reference = db.Column(db.String(100), unique=True, nullable=False, index=True)
    amount = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(50), default='pending', nullable=False, index=True)
    payment_method = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    paid_at = db.Column(db.DateTime, nullable=True)

class CountdownSettings(db.Model):
    __tablename__ = 'countdown_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    is_active = db.Column(db.Boolean, default=False, nullable=False)
    target_datetime = db.Column(db.DateTime, nullable=True)
    title = db.Column(db.String(200), default='AskaraAI Launching Soon!', nullable=False)
    subtitle = db.Column(db.String(500), default='AI-powered video clipper coming soon', nullable=False)
    background_style = db.Column(db.String(50), default='gradient', nullable=False)
    redirect_after_launch = db.Column(db.String(200), default='/', nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    @classmethod
    def get_current(cls):
        settings = cls.query.first()
        if not settings:
            settings = cls()
        return settings
    
    def is_launch_time_passed(self):
        if not self.target_datetime:
            return True
        return datetime.utcnow() >= self.target_datetime

class PromoCode(db.Model):
    __tablename__ = 'promo_codes'
    
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    description = db.Column(db.String(200), nullable=False)
    discount_type = db.Column(db.String(20), nullable=False)
    discount_value = db.Column(db.Float, nullable=False)
    max_uses = db.Column(db.Integer, default=100, nullable=False)
    used_count = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

class SystemHealth(db.Model):
    __tablename__ = 'system_health'
    
    id = db.Column(db.Integer, primary_key=True)
    check_time = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    overall_status = db.Column(db.String(20), nullable=False)
    database_status = db.Column(db.String(20), nullable=False)
    redis_status = db.Column(db.String(20), nullable=False)
    celery_status = db.Column(db.String(20), nullable=False)
    disk_usage = db.Column(db.Float, nullable=True)
    memory_usage = db.Column(db.Float, nullable=True)
    cpu_usage = db.Column(db.Float, nullable=True)
    details = db.Column(db.Text, nullable=True)

class PromoUsage(db.Model):
    __tablename__ = 'promo_usage'
    
    id = db.Column(db.Integer, primary_key=True)
    promo_code_id = db.Column(db.Integer, db.ForeignKey('promo_codes.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    applied_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
EOL

    # Create basic app.py (FIXED)
    sudo -u ${APP_USER} tee app.py > /dev/null << 'EOL'
import os
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_caching import Cache
from dotenv import load_dotenv
import redis
import google.generativeai as genai
import logging

# Load environment variables
load_dotenv()

# Import models
from app_models import db, User, VideoProcess, VideoClip

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_app():
    app = Flask(__name__)
    
    # Configuration
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
    
    # Database configuration
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        db_password = os.getenv('DB_PASSWORD')
        database_url = f'mysql+pymysql://askaraai:{db_password}@localhost/askaraai_db'

    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # Caching
    app.config['CACHE_TYPE'] = 'redis'
    app.config['CACHE_REDIS_URL'] = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    
    return app

app = create_app()

# Initialize extensions
db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
cache = Cache(app)

# Rate limiting
try:
    limiter = Limiter(
        app=app,
        key_func=get_remote_address,
        default_limits=["1000 per day", "100 per hour"],
        storage_uri=os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    )
except Exception as e:
    logger.warning(f"Rate limiter failed: {str(e)}")
    limiter = None

@login_manager.user_loader
def load_user(user_id):
    try:
        return User.query.get(int(user_id))
    except Exception:
        return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/health')
def health_check():
    try:
        # Test database connection
        db.engine.execute('SELECT 1')
        return jsonify({
            'status': 'healthy',
            'database': 'connected',
            'timestamp': str(datetime.utcnow())
        })
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'error': str(e)
        }), 500

@app.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        return redirect(url_for('index'))
    
    try:
        total_users = User.query.count()
        premium_users = User.query.filter_by(is_premium=True).count()
        total_videos = VideoProcess.query.count()
        total_clips = db.session.query(db.func.sum(VideoProcess.clips_generated)).scalar() or 0
        recent_users = User.query.order_by(User.created_at.desc()).limit(10).all()
        
        return render_template('admin.html',
                             total_users=total_users,
                             premium_users=premium_users,
                             total_videos_processed=total_videos,
                             total_clips_generated=total_clips,
                             recent_users=recent_users)
    except Exception as e:
        logger.error(f"Admin dashboard error: {str(e)}")
        return render_template('admin.html',
                             total_users=0,
                             premium_users=0,
                             total_videos_processed=0,
                             total_clips_generated=0,
                             recent_users=[])

@app.cli.command()
def init_db():
    """Initialize database"""
    try:
        db.create_all()
        
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
            print(f"Admin user created: {admin_email}")
        else:
            admin.is_admin = True
            admin.is_premium = True
            admin.credits = 999999
            db.session.commit()
            print(f"Admin user updated: {admin_email}")
            
        print("Database initialization completed!")
        
    except Exception as e:
        print(f"Database initialization failed: {str(e)}")

if __name__ == '__main__':
    with app.app_context():
        try:
            db.create_all()
            logger.info("Database tables created")
        except Exception as e:
            logger.error(f"Database setup failed: {str(e)}")
    
    app.run(debug=False, host='0.0.0.0', port=5000)
EOL

    # Create backup_database.py (LOCAL BACKUP ONLY)
    sudo -u ${APP_USER} tee backup_database.py > /dev/null << 'EOL'
#!/usr/bin/env python3
"""
AskaraAI Local Database Backup Script
Local backup only (tidak menggunakan Google Drive/rclone)
"""

import os
import subprocess
import logging
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/var/www/askaraai/logs/backup.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class LocalDatabaseBackup:
    def __init__(self):
        self.db_host = 'localhost'
        self.db_user = 'askaraai'
        self.db_password = os.getenv('DB_PASSWORD')
        self.db_name = 'askaraai_db'
        self.backup_dir = '/var/www/askaraai/backup'
        
        if not self.db_password:
            logger.critical("DB_PASSWORD environment variable not set")
            raise ValueError("DB_PASSWORD not found")

        # Ensure backup directory exists
        os.makedirs(self.backup_dir, exist_ok=True)
        
    def create_backup_filename(self):
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        return f"askaraai_backup_{timestamp}.sql"
    
    def create_mysql_dump(self, backup_path):
        try:
            logger.info(f"Creating MySQL dump: {backup_path}")
            
            cmd = [
                'mysqldump',
                '-h', self.db_host,
                '-u', self.db_user,
                f'-p{self.db_password}',
                '--single-transaction',
                '--routines',
                '--triggers',
                '--add-drop-database',
                '--databases',
                self.db_name
            ]
            
            with open(backup_path, 'w') as f:
                result = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, check=True, text=True)
            
            if os.path.exists(backup_path) and os.path.getsize(backup_path) > 0:
                logger.info(f"MySQL dump created successfully: {backup_path}")
                return True
            else:
                logger.error("MySQL dump file is empty")
                return False
                
        except subprocess.CalledProcessError as e:
            logger.error(f"MySQL dump failed: {e.stderr.decode() if e.stderr else str(e)}")
            return False
        except Exception as e:
            logger.error(f"Error creating MySQL dump: {str(e)}")
            return False
    
    def cleanup_old_backups(self, retention_days=30):
        try:
            logger.info("Cleaning up old backups...")
            
            cutoff_time = datetime.now().timestamp() - (retention_days * 24 * 3600)
            deleted_count = 0
            
            for filename in os.listdir(self.backup_dir):
                if filename.startswith('askaraai_backup_') and filename.endswith('.sql'):
                    filepath = os.path.join(self.backup_dir, filename)
                    if os.path.getmtime(filepath) < cutoff_time:
                        os.remove(filepath)
                        deleted_count += 1
                        logger.info(f"Deleted old backup: {filename}")
            
            logger.info(f"Cleanup completed. Deleted {deleted_count} old backups")
            
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")
    
    def run_backup(self):
        logger.info("=== Starting Local Database Backup ===")
        
        backup_filename = self.create_backup_filename()
        backup_path = os.path.join(self.backup_dir, backup_filename)
        
        try:
            # Create MySQL dump
            if not self.create_mysql_dump(backup_path):
                logger.error("Backup failed - MySQL dump creation failed")
                return False
            
            # Cleanup old backups
            self.cleanup_old_backups()
            
            logger.info(f"=== Local Backup Completed Successfully: {backup_filename} ===")
            return True
            
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            logger.error(error_msg)
            return False

if __name__ == "__main__":
    os.makedirs('/var/www/askaraai/logs', exist_ok=True)
    
    logger.info("AskaraAI Local Database Backup Script Started")
    
    backup_manager = LocalDatabaseBackup()
    success = backup_manager.run_backup()
    
    if success:
        logger.info("Backup script completed successfully")
        exit(0)
    else:
        logger.error("Backup script failed")
        exit(1)
EOL

    # Create templates
    sudo -u ${APP_USER} mkdir -p templates
    
    # Create basic index.html
    sudo -u ${APP_USER} tee templates/index.html > /dev/null << 'EOL'
<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AskaraAI - Coming Soon</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-900 text-white min-h-screen flex items-center justify-center">
    <div class="text-center">
        <h1 class="text-6xl font-bold mb-4">AskaraAI</h1>
        <p class="text-xl mb-8">AI Video Clipper - Coming Soon</p>
        <p class="text-gray-400">Setup completed! Configure your .env file and restart services.</p>
        <div class="mt-8">
            <a href="/health" class="bg-indigo-600 hover:bg-indigo-700 px-6 py-3 rounded-lg font-semibold">Check Health</a>
        </div>
    </div>
</body>
</html>
EOL

    # Create basic admin.html
    sudo -u ${APP_USER} tee templates/admin.html > /dev/null << 'EOL'
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AskaraAI Admin Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-100">
    <div class="container mx-auto px-4 py-8">
        <h1 class="text-3xl font-bold mb-8">AskaraAI Admin Dashboard</h1>
        <div class="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
            <div class="bg-white p-6 rounded-lg shadow">
                <h3 class="text-lg font-semibold mb-2">Total Users</h3>
                <p class="text-3xl font-bold text-blue-600">{{ total_users }}</p>
            </div>
            <div class="bg-white p-6 rounded-lg shadow">
                <h3 class="text-lg font-semibold mb-2">Premium Users</h3>
                <p class="text-3xl font-bold text-green-600">{{ premium_users }}</p>
            </div>
            <div class="bg-white p-6 rounded-lg shadow">
                <h3 class="text-lg font-semibold mb-2">Videos Processed</h3>
                <p class="text-3xl font-bold text-purple-600">{{ total_videos_processed }}</p>
            </div>
            <div class="bg-white p-6 rounded-lg shadow">
                <h3 class="text-lg font-semibold mb-2">Clips Generated</h3>
                <p class="text-3xl font-bold text-yellow-600">{{ total_clips_generated }}</p>
            </div>
        </div>
        <div class="bg-white rounded-lg shadow p-6">
            <h2 class="text-xl font-bold mb-4">Recent Users</h2>
            <div class="overflow-x-auto">
                <table class="min-w-full">
                    <thead>
                        <tr class="border-b">
                            <th class="text-left py-2">Name</th>
                            <th class="text-left py-2">Email</th>
                            <th class="text-left py-2">Credits</th>
                            <th class="text-left py-2">Status</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for user in recent_users %}
                        <tr class="border-b">
                            <td class="py-2">{{ user.name }}</td>
                            <td class="py-2">{{ user.email }}</td>
                            <td class="py-2">{{ user.credits }}</td>
                            <td class="py-2">
                                <span class="px-2 py-1 text-xs rounded {% if user.is_premium %}bg-green-100 text-green-800{% else %}bg-gray-100 text-gray-800{% endif %}">
                                    {% if user.is_premium %}Premium{% else %}Free{% endif %}
                                </span>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
</body>
</html>
EOL

    log_success "Application files created"
}

# Setup Nginx (FIXED)
setup_nginx() {
    log_info "Setting up Nginx..."
    
    # Create site configuration
    tee /etc/nginx/sites-available/askaraai > /dev/null << 'EOL'
server {
    listen 80 default_server;
    server_name askaraai.com www.askaraai.com _;
    
    # Security headers
    add_header X-Frame-Options DENY always;
    add_header X-Content-Type-Options nosniff always;
    add_header X-XSS-Protection "1; mode=block" always;
    
    root /var/www/askaraai;
    
    # Rate limiting
    limit_req_zone $binary_remote_addr zone=general:10m rate=50r/m;
    
    # Main application
    location / {
        limit_req zone=general burst=20 nodelay;
        try_files $uri @app;
    }
    
    # Application proxy
    location @app {
        proxy_pass http://unix:/var/www/askaraai/askaraai.sock;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        proxy_connect_timeout 30s;
        proxy_send_timeout 120s;
    }
    
    # Static files
    location /static {
        alias /var/www/askaraai/static;
        expires 7d;
        add_header Cache-Control "public";
    }
    
    # Block sensitive files
    location ~ /\. {
        deny all;
        return 404;
    }
    
    # Health check
    location /health {
        access_log off;
        try_files $uri @app;
    }
}
EOL

    # Enable site
    ln -sf /etc/nginx/sites-available/askaraai /etc/nginx/sites-enabled/
    rm -f /etc/nginx/sites-enabled/default
    
    # Test and restart
    nginx -t && systemctl restart nginx
    systemctl enable nginx
    
    log_success "Nginx configured"
}

# Setup systemd services (FIXED)
setup_systemd_services() {
    log_info "Setting up systemd services..."
    
    # Main application service
    tee /etc/systemd/system/askaraai.service > /dev/null << EOL
[Unit]
Description=AskaraAI Flask Application
After=network.target mysql.service redis.service
Wants=mysql.service redis.service

[Service]
Type=exec
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
Environment="PATH=${APP_DIR}/venv/bin"
Environment="FLASK_ENV=production"

ExecStart=${APP_DIR}/venv/bin/gunicorn \\
    --bind unix:${APP_DIR}/askaraai.sock \\
    --workers 2 \\
    --worker-class sync \\
    --timeout 120 \\
    --keep-alive 2 \\
    --preload \\
    --log-level info \\
    --access-logfile ${APP_DIR}/logs/gunicorn_access.log \\
    --error-logfile ${APP_DIR}/logs/gunicorn_error.log \\
    --pid ${APP_DIR}/gunicorn.pid \\
    app:app

ExecReload=/bin/kill -s HUP \$MAINPID
Restart=always
RestartSec=3

# Security
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOL

    # Daily backup service (LOCAL)
    tee /etc/systemd/system/askaraai-backup.service > /dev/null << EOL
[Unit]
Description=AskaraAI Local Database Backup
After=mysql.service

[Service]
Type=oneshot
User=${APP_USER}
WorkingDirectory=${APP_DIR}
Environment="PATH=${APP_DIR}/venv/bin"
ExecStart=${APP_DIR}/venv/bin/python3 ${APP_DIR}/backup_database.py

[Install]
WantedBy=multi-user.target
EOL

    # Daily backup timer
    tee /etc/systemd/system/askaraai-backup.timer > /dev/null << 'EOL'
[Unit]
Description=Run AskaraAI backup daily
Requires=askaraai-backup.service

[Timer]
OnCalendar=daily
Persistent=true
RandomizedDelaySec=3600

[Install]
WantedBy=timers.target
EOL

    # Setup logrotate
    tee /etc/logrotate.d/askaraai > /dev/null << EOL
${APP_DIR}/logs/*.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    postrotate
        systemctl reload askaraai
    endscript
}
EOL

    # Set proper permissions
    chown -R ${APP_USER}:${APP_USER} ${APP_DIR}
    
    # Reload and enable services
    systemctl daemon-reload
    systemctl enable askaraai.service
    systemctl enable askaraai-backup.timer
    
    log_success "Systemd services created"
}

# Start services
start_services() {
    log_info "Starting services..."
    
    # Start dependencies
    systemctl start mysql redis-server
    sleep 2
    
    # Initialize database
    cd ${APP_DIR}
    sudo -u ${APP_USER} bash -c "source venv/bin/activate && python3 -c 'from app import app, db; app.app_context().push(); db.create_all(); print(\"Database initialized\")'"
    
    # Start application
    systemctl start askaraai.service
    sleep 3
    
    # Start web server
    systemctl start nginx
    
    # Start backup timer
    systemctl start askaraai-backup.timer
    
    log_success "All services started"
}

# Check service status
check_services() {
    log_info "Checking service status..."
    
    services=("mysql" "redis-server" "nginx" "askaraai")
    
    for service in "${services[@]}"; do
        if systemctl is-active --quiet $service; then
            log_success "$service is running"
        else
            log_error "$service is not running"
            systemctl restart $service
            sleep 2
            if systemctl is-active --quiet $service; then
                log_success "$service restarted successfully"
            fi
        fi
    done
}

# Cleanup
cleanup() {
    log_info "Cleaning up..."
    
    # Remove temporary files
    (sleep 10 && rm -f /tmp/db_password.txt) &
    
    # Clean package cache
    apt autoremove -y
    apt autoclean
    
    log_success "Cleanup completed"
}

# Main execution
main() {
    echo "🚀 Starting AskaraAI FIXED Setup (No Google Drive/Rclone)"
    echo "======================================================="
    
    check_prerequisites
    update_system
    install_dependencies
    setup_firewall
    setup_fail2ban
    setup_mysql
    setup_redis
    setup_application
    create_environment_file
    create_app_files
    setup_nginx
    setup_systemd_services
    start_services
    sleep 5
    check_services
    cleanup
    
    echo ""
    echo "✅ AskaraAI FIXED Setup Completed!"
    echo "=================================="
    echo ""
    echo "📋 Setup Information:"
    echo "   Database Password: $(cat /tmp/db_password.txt 2>/dev/null || echo 'Check logs')"
    echo "   Database Name: $DB_NAME"
    echo "   Database User: $DB_USER"
    echo ""
    echo "🔒 Security Features:"
    echo "   ✅ Firewall (UFW)"
    echo "   ✅ Fail2Ban"
    echo "   ✅ MySQL security"
    echo "   ✅ Local backup system"
    echo "   ✅ Nginx security headers"
    echo ""
    echo "📁 File Structure:"
    echo "   ${APP_DIR}/               - Application root"
    echo "   ${APP_DIR}/app.py         - Main Flask app"
    echo "   ${APP_DIR}/.env           - Environment config"
    echo "   ${APP_DIR}/logs/          - Application logs"
    echo "   ${APP_DIR}/backup/        - Local database backups"
    echo ""
    echo "🔧 Next Steps:"
    echo "1. Edit ${APP_DIR}/.env and add your API keys"
    echo "2. Restart services: systemctl restart askaraai"
    echo "3. Test: curl http://localhost/health"
    echo ""
    echo "🎉 Installation Complete!"
    echo "📄 Setup log: $LOG_FILE"
    echo ""
}

# Run main function
main "$@"
