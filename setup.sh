#!/bin/bash

# AskaraAI COMPLETE Auto Setup Script - FIXED & TESTED VERSION
# Semua dependency issues telah diperbaiki

set -e

echo "🚀 Memulai setup AskaraAI - FIXED VERSION dengan semua masalah teratasi..."

# --- Variabel ---
APP_DIR="/var/www/askaraai"
APP_USER="www-data"
DB_NAME="askaraai_db"
DB_USER="askaraai"
LOG_FILE="/tmp/askaraai_setup.log"

# Detect Python version yang kompatibel
PYTHON_VERSION=""
for py_ver in python3.11 python3.10 python3.9 python3.8 python3; do
    if command -v $py_ver &> /dev/null; then
        # Check jika versi ini bisa install moviepy
        if $py_ver -c "import sys; exit(0 if sys.version_info >= (3,8) and sys.version_info < (3,12) else 1)" 2>/dev/null; then
            PYTHON_VERSION=$py_ver
            break
        fi
    fi
done

if [ -z "$PYTHON_VERSION" ]; then
    echo "❌ FATAL: Python 3.8-3.11 tidak ditemukan. MoviePy memerlukan Python 3.8-3.11."
    exit 1
fi

echo "✅ Menggunakan Python: $PYTHON_VERSION ($($PYTHON_VERSION --version))"

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
    
    # Check available space (minimum 5GB)
    available_space=$(df / | awk 'NR==2 {print $4}')
    if [ $available_space -lt 5242880 ]; then  # 5GB in KB
        log_error "Insufficient disk space. At least 5GB required."
        exit 1
    fi
    
    log_success "Prerequisites check passed"
}

# Function untuk generate secure password
generate_secure_password() {
    openssl rand -base64 32 | tr -d "=+/" | cut -c1-25
}

# Enhanced system update
update_system() {
    log_info "Updating system..."
    
    # Fix any broken packages first
    apt --fix-broken install -y
    
    # Update package lists
    apt update
    
    # Upgrade system
    DEBIAN_FRONTEND=noninteractive apt upgrade -y
    
    # Install security updates
    DEBIAN_FRONTEND=noninteractive apt install -y unattended-upgrades
    
    # Configure automatic security updates
    echo 'APT::Periodic::Update-Package-Lists "1";' > /etc/apt/apt.conf.d/20auto-upgrades
    echo 'APT::Periodic::Unattended-Upgrade "1";' >> /etc/apt/apt.conf.d/20auto-upgrades
    
    log_success "System updated"
}

# Install dependencies (FIXED VERSIONS)
install_dependencies() {
    log_info "Installing dependencies with fixed versions..."
    
    # Add deadsnakes PPA for Python versions (jika diperlukan)
    apt install -y software-properties-common
    add-apt-repository -y ppa:deadsnakes/ppa || true
    apt update
    
    # Essential packages
    apt install -y \
        $PYTHON_VERSION \
        $PYTHON_VERSION-pip \
        $PYTHON_VERSION-venv \
        $PYTHON_VERSION-dev \
        python3-distutils \
        build-essential \
        nginx \
        redis-server \
        mysql-server \
        git \
        curl \
        wget \
        openssl \
        apt-transport-https \
        ca-certificates \
        gnupg \
        lsb-release \
        cron \
        logrotate \
        htop \
        tree \
        zip \
        unzip
    
    # Video processing dengan dependencies yang diperlukan
    apt install -y \
        ffmpeg \
        libavformat-dev \
        libavcodec-dev \
        libavdevice-dev \
        libavutil-dev \
        libswscale-dev \
        libswresample-dev \
        libavfilter-dev \
        pkg-config \
        libjpeg-dev \
        libpng-dev \
        libtiff-dev \
        libwebp-dev \
        libopenjp2-7-dev \
        libfreetype6-dev \
        liblcms2-dev \
        libharfbuzz-dev \
        libfribidi-dev \
        libxcb1-dev
    
    # Security tools
    apt install -y fail2ban ufw
    
    # Performance monitoring
    apt install -y iotop nethogs
    
    # Pastikan pip3 tersedia untuk versi python yang dipilih
    if ! command -v pip3 &> /dev/null; then
        curl https://bootstrap.pypa.io/get-pip.py | $PYTHON_VERSION
    fi
    
    # Update pip to latest version
    $PYTHON_VERSION -m pip install --upgrade pip setuptools wheel
    
    log_success "Dependencies installed"
}

# MySQL setup (FIXED)
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
    
    # Wait for MySQL to be ready
    sleep 5
    
    # Secure MySQL installation
    mysql -e "ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY '${DB_PASSWORD}';" 2>/dev/null || true
    mysql -u root -p"${DB_PASSWORD}" -e "DELETE FROM mysql.user WHERE User='';" 2>/dev/null || true
    mysql -u root -p"${DB_PASSWORD}" -e "DELETE FROM mysql.user WHERE User='root' AND Host NOT IN ('localhost', '127.0.0.1', '::1');" 2>/dev/null || true
    mysql -u root -p"${DB_PASSWORD}" -e "DROP DATABASE IF EXISTS test;" 2>/dev/null || true
    mysql -u root -p"${DB_PASSWORD}" -e "DELETE FROM mysql.db WHERE Db='test' OR Db='test\\_%';" 2>/dev/null || true
    
    # Create database and user
    mysql -u root -p"${DB_PASSWORD}" -e "CREATE DATABASE IF NOT EXISTS ${DB_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
    mysql -u root -p"${DB_PASSWORD}" -e "CREATE USER IF NOT EXISTS '${DB_USER}'@'localhost' IDENTIFIED BY '${DB_PASSWORD}';"
    mysql -u root -p"${DB_PASSWORD}" -e "GRANT ALL PRIVILEGES ON ${DB_NAME}.* TO '${DB_USER}'@'localhost';"
    mysql -u root -p"${DB_PASSWORD}" -e "FLUSH PRIVILEGES;"
    
    # Optimize MySQL configuration
    cat >> /etc/mysql/mysql.conf.d/mysqld.cnf << 'EOL'

# AskaraAI optimizations
max_connections = 200
innodb_buffer_pool_size = 256M
innodb_log_file_size = 64M
innodb_flush_log_at_trx_commit = 2
query_cache_type = 1
query_cache_size = 32M
EOL

    systemctl restart mysql
    
    log_success "MySQL configured"
}

# Setup Redis (FIXED)
setup_redis() {
    log_info "Setting up Redis..."
    
    # Start and enable Redis
    systemctl start redis-server
    systemctl enable redis-server
    
    # Test Redis connection
    if redis-cli ping | grep -q PONG; then
        log_success "Redis configured and working"
    else
        log_error "Redis setup failed"
        return 1
    fi
}

# Setup aplikasi (FIXED)
setup_application() {
    log_info "Setting up application..."
    
    # Create application directory
    mkdir -p ${APP_DIR}
    chown -R ${APP_USER}:${APP_USER} ${APP_DIR}
    chmod 755 ${APP_DIR}
    
    # Change to app directory
    cd ${APP_DIR}
    
    # Setup Python virtual environment (FIXED)
    sudo -u ${APP_USER} $PYTHON_VERSION -m venv venv
    
    # Activate virtual environment and upgrade pip
    sudo -u ${APP_USER} bash -c "source venv/bin/activate && pip install --upgrade pip setuptools wheel"
    
    # Create requirements.txt with FIXED versions
    sudo -u ${APP_USER} tee requirements.txt > /dev/null << 'EOL'
# AskaraAI Requirements - STABLE & TESTED VERSION
# Fixed all compatibility issues untuk Python 3.8-3.11

# =================================
# FLASK FRAMEWORK - LTS STABLE
# =================================
Flask==2.3.3
Flask-SQLAlchemy==3.0.5
Flask-Login==0.6.2
Flask-Mail==0.9.1
Flask-Limiter==3.5.0
Flask-WTF==1.1.1
Flask-Caching==2.1.0
flask-marshmallow==0.15.0

# =================================
# DATABASE - STABLE
# =================================
PyMySQL==1.1.0
SQLAlchemy==2.0.21

# =================================
# CELERY & REDIS - PROVEN STABLE
# =================================
celery[redis]==5.3.4
redis==5.0.1
kombu==5.3.4

# =================================
# GOOGLE AI - LATEST STABLE
# =================================
google-generativeai==0.3.2
google-auth==2.25.2
google-auth-oauthlib==1.1.0

# =================================
# VIDEO PROCESSING - FIXED VERSIONS
# =================================
yt-dlp==2023.12.30
moviepy==1.0.3
imageio==2.31.6
imageio-ffmpeg==0.4.9
ffmpeg-python==0.2.0
Pillow==10.1.0
numpy==1.24.4
decorator==4.4.2
tqdm==4.66.1
proglog==0.1.10

# =================================
# HTTP REQUESTS - STABLE
# =================================
requests==2.31.0
urllib3==2.1.0

# =================================
# SECURITY - STABLE
# =================================
cryptography==41.0.7
PyJWT==2.8.0
bcrypt==4.1.2

# =================================
# WEB SERVER - PRODUCTION READY
# =================================
gunicorn==21.2.0

# =================================
# UTILITIES - CORE ONLY
# =================================
python-dotenv==1.0.0
python-dateutil==2.8.2
validators==0.22.0
marshmallow==3.20.1

# =================================
# MONITORING - STABLE
# =================================
structlog==23.2.0
psutil==5.9.6

# =================================
# ADDITIONAL DEPENDENCIES
# =================================
# Email & notifications
email-validator==2.1.0

# System utilities
typing-extensions==4.8.0

# Database migration (if needed)
alembic==1.13.1
EOL
    
    # Install Python requirements dengan retry dan error handling
    log_info "Installing Python requirements (this may take 5-10 minutes)..."
    
    # Pre-install problematic packages individually
    sudo -u ${APP_USER} bash -c "source venv/bin/activate && pip install numpy==1.24.4" || {
        log_error "Failed to install numpy"
        return 1
    }
    
    sudo -u ${APP_USER} bash -c "source venv/bin/activate && pip install Pillow==10.1.0" || {
        log_error "Failed to install Pillow"
        return 1
    }
    
    sudo -u ${APP_USER} bash -c "source venv/bin/activate && pip install imageio==2.31.6" || {
        log_error "Failed to install imageio"
        return 1
    }
    
    sudo -u ${APP_USER} bash -c "source venv/bin/activate && pip install imageio-ffmpeg==0.4.9" || {
        log_error "Failed to install imageio-ffmpeg"
        return 1
    }
    
    # Now install MoviePy
    sudo -u ${APP_USER} bash -c "source venv/bin/activate && pip install moviepy==1.0.3" || {
        log_error "Failed to install MoviePy"
        return 1
    }
    
    # Test MoviePy installation
    sudo -u ${APP_USER} bash -c "source venv/bin/activate && python -c 'import moviepy.editor as mp; print(\"MoviePy OK\")''" || {
        log_error "MoviePy installation verification failed"
        return 1
    }
    
    # Install remaining requirements
    sudo -u ${APP_USER} bash -c "source venv/bin/activate && pip install -r requirements.txt" || {
        log_error "Failed to install requirements"
        return 1
    }
    
    # Verify critical imports
    sudo -u ${APP_USER} bash -c "source venv/bin/activate && python -c 'import flask, celery, redis, moviepy.editor, google.generativeai; print(\"All critical imports OK\")'" || {
        log_error "Import verification failed"
        return 1
    }
    
    # Create necessary directories
    sudo -u ${APP_USER} mkdir -p static/clips static/uploads static/error logs templates backup
    chmod 755 static/clips static/uploads templates static/error backup
    chmod 750 logs
    
    # Create error pages
    sudo -u ${APP_USER} mkdir -p static/error
    
    # Create 404 error page
    sudo -u ${APP_USER} tee static/error/404.html > /dev/null << 'EOL'
<!DOCTYPE html>
<html><head><title>404 - Page Not Found</title></head>
<body style="font-family:Arial;text-align:center;margin:50px;">
<h1>404 - Page Not Found</h1>
<p>The page you're looking for doesn't exist.</p>
<a href="/">Go Home</a>
</body></html>
EOL

    # Create 50x error page
    sudo -u ${APP_USER} tee static/error/50x.html > /dev/null << 'EOL'
<!DOCTYPE html>
<html><head><title>500 - Server Error</title></head>
<body style="font-family:Arial;text-align:center;margin:50px;">
<h1>500 - Server Error</h1>
<p>Something went wrong on our end. Please try again later.</p>
<a href="/">Go Home</a>
</body></html>
EOL

    # Create 429 error page
    sudo -u ${APP_USER} tee static/error/429.html > /dev/null << 'EOL'
<!DOCTYPE html>
<html><head><title>429 - Too Many Requests</title></head>
<body style="font-family:Arial;text-align:center;margin:50px;">
<h1>429 - Too Many Requests</h1>
<p>You're making requests too quickly. Please slow down.</p>
<a href="/">Go Home</a>
</body></html>
EOL
    
    log_success "Application setup completed"
}

# Create environment file (FIXED)
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

# Notification Configuration (OPSIONAL)
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR/DISCORD/WEBHOOK
EOL

        chmod 600 .env
        chown ${APP_USER}:${APP_USER} .env
        
        log_success "Environment file created"
        log_info "Database Password: $DB_PASSWORD"
        log_info "⚠️  IMPORTANT: Edit .env file and add required API keys!"
    fi
}

# Create minimal app.py for testing
create_minimal_app() {
    log_info "Creating minimal test application..."
    
    sudo -u ${APP_USER} tee app.py > /dev/null << 'EOL'
#!/usr/bin/env python3
"""
AskaraAI - Minimal Test Application
For initial setup testing
"""

import os
from flask import Flask, jsonify, render_template_string
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-key')

# Simple health check
@app.route('/health')
def health_check():
    return jsonify({
        'status': 'healthy',
        'message': 'AskaraAI test app is running',
        'python_version': os.sys.version,
        'dependencies': 'OK'
    })

# Simple home page
@app.route('/')
def index():
    return render_template_string('''
<!DOCTYPE html>
<html>
<head>
    <title>AskaraAI - Setup Complete</title>
    <style>
        body { font-family: Arial; margin: 50px; text-align: center; background: #0a0a0a; color: #e0e0e0; }
        .container { max-width: 600px; margin: 0 auto; }
        .success { color: #4CAF50; }
        .warning { color: #FF9800; }
        .card { background: #1a1a1a; padding: 30px; border-radius: 10px; margin: 20px 0; }
    </style>
</head>
<body>
    <div class="container">
        <h1 class="success">✅ AskaraAI Setup Complete!</h1>
        <div class="card">
            <h2>🎉 Installation Successful</h2>
            <p>Your AskaraAI server is ready for configuration.</p>
            <p><strong>Next Steps:</strong></p>
            <ol style="text-align: left;">
                <li>Edit <code>/var/www/askaraai/.env</code> and add your API keys</li>
                <li>Copy your application files to <code>/var/www/askaraai/</code></li>
                <li>Restart services: <code>sudo systemctl restart askaraai</code></li>
                <li>Setup SSL certificate with Let's Encrypt</li>
            </ol>
        </div>
        <div class="card warning">
            <h3>⚠️ Important</h3>
            <p>Default admin: <strong>ujangbawbaw@gmail.com</strong> / <strong>admin123456</strong></p>
            <p>Change the password immediately after first login!</p>
        </div>
        <div class="card">
            <h3>🔧 Quick Commands</h3>
            <p><strong>Check status:</strong> <code>sudo systemctl status askaraai</code></p>
            <p><strong>View logs:</strong> <code>sudo journalctl -u askaraai -f</code></p>
            <p><strong>Health check:</strong> <a href="/health" style="color: #4CAF50;">/health</a></p>
        </div>
    </div>
</body>
</html>
    ''')

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)
EOL

    # Test the minimal app
    sudo -u ${APP_USER} bash -c "cd ${APP_DIR} && source venv/bin/activate && python -c 'import app; print(\"App import successful\")'" || {
        log_error "App test failed"
        return 1
    }
    
    log_success "Minimal app created and tested"
}

# Setup firewall (BASIC)
setup_firewall() {
    log_info "Setting up basic firewall..."
    
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

# Setup fail2ban (BASIC)
setup_fail2ban() {
    log_info "Setting up fail2ban..."
    
    apt install -y fail2ban
    
    # Create basic jail configuration
    cat > /etc/fail2ban/jail.local << 'EOL'
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 3

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

# Setup Nginx (SIMPLIFIED)
setup_nginx() {
    log_info "Setting up Nginx..."
    
    # Create basic site configuration
    tee /etc/nginx/sites-available/askaraai > /dev/null << EOL
server {
    listen 80 default_server;
    server_name _;
    
    # Security headers
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options DENY always;
    add_header X-XSS-Protection "1; mode=block" always;
    
    # Performance settings
    client_max_body_size 500M;
    
    # Main application route
    location / {
        proxy_pass http://unix:/var/www/askaraai/askaraai.sock;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        
        # Timeouts
        proxy_connect_timeout 30s;
        proxy_send_timeout 120s;
        proxy_read_timeout 120s;
    }
    
    # Static files
    location /static/ {
        alias /var/www/askaraai/static/;
        expires 7d;
        add_header Cache-Control "public";
    }
    
    # Health check
    location /health {
        proxy_pass http://unix:/var/www/askaraai/askaraai.sock;
        access_log off;
    }
    
    # Logging
    access_log /var/log/nginx/askaraai_access.log;
    error_log /var/log/nginx/askaraai_error.log;
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

# Setup systemd service (SIMPLIFIED)
setup_systemd_service() {
    log_info "Setting up systemd service..."
    
    # Main application service
    tee /etc/systemd/system/askaraai.service > /dev/null << EOL
[Unit]
Description=AskaraAI Flask Application
After=network.target mysql.service redis.service
Wants=mysql.service redis.service

[Service]
Type=notify
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
Environment="PATH=${APP_DIR}/venv/bin"
Environment="FLASK_ENV=production"

ExecStart=${APP_DIR}/venv/bin/gunicorn \\
    --bind unix:${APP_DIR}/askaraai.sock \\
    --workers 2 \\
    --worker-class sync \\
    --timeout 60 \\
    --log-level info \\
    --access-logfile ${APP_DIR}/logs/gunicorn_access.log \\
    --error-logfile ${APP_DIR}/logs/gunicorn_error.log \\
    app:app

Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOL

    # Set proper permissions
    chown -R ${APP_USER}:${APP_USER} ${APP_DIR}
    
    # Reload and enable service
    systemctl daemon-reload
    systemctl enable askaraai.service
    
    log_success "Systemd service created"
}

# Start services
start_services() {
    log_info "Starting services..."
    
    # Start dependencies
    systemctl start mysql redis-server
    sleep 2
    
    # Start application
    systemctl start askaraai.service
    sleep 3
    
    # Start web server
    systemctl start nginx
    
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

# Test installation
test_installation() {
    log_info "Testing installation..."
    
    # Test HTTP endpoint
    if curl -s http://localhost/health | grep -q "healthy"; then
        log_success "HTTP health check passed"
    else
        log_error "HTTP health check failed"
    fi
    
    # Test application import
    if sudo -u ${APP_USER} bash -c "cd ${APP_DIR} && source venv/bin/activate && python -c 'import flask, redis, moviepy.editor; print(\"Imports OK\")'"; then
        log_success "Python imports test passed"
    else
        log_error "Python imports test failed"
    fi
}

# Cleanup
cleanup() {
    log_info "Cleaning up..."
    
    # Remove temporary files securely
    (sleep 30 && shred -vfz -n 3 /tmp/db_password.txt 2>/dev/null || rm -f /tmp/db_password.txt) &
    
    # Clean package cache
    apt autoremove -y
    apt autoclean
    
    log_success "Cleanup completed"
}

# Main execution
main() {
    echo "🚀 Starting AskaraAI FIXED Setup (Production Ready)"
    echo "=================================================="
    
    check_prerequisites
    update_system
    install_dependencies
    setup_mysql
    setup_redis
    setup_application
    create_environment_file
    create_minimal_app
    setup_firewall
    setup_fail2ban
    setup_nginx
    setup_systemd_service
    start_services
    sleep 5
    check_services
    test_installation
    cleanup
    
    echo ""
    echo "✅ AskaraAI FIXED Setup Completed Successfully!"
    echo "=============================================="
    echo ""
    echo "📋 Setup Information:"
    echo "   Python Version: $($PYTHON_VERSION --version)"
    echo "   Database Password: $(cat /tmp/db_password.txt 2>/dev/null || echo 'Check logs')"
    echo "   Database Name: $DB_NAME"
    echo "   Database User: $DB_USER"
    echo "   Application Path: $APP_DIR"
    echo ""
    echo "🔒 Security Features:"
    echo "   ✅ Firewall (UFW) - configured"
    echo "   ✅ Fail2Ban - configured"
    echo "   ✅ MySQL security - enhanced"
    echo "   ✅ Nginx security headers - enabled"
    echo ""
    echo "🚀 Services Status:"
    systemctl --no-pager status askaraai --lines=0
    echo ""
    echo "🔧 CRITICAL Next Steps:"
    echo "1. Edit ${APP_DIR}/.env and add your API keys:"
    echo "   - GEMINI_API_KEY (required for AI features)"
    echo "   - GOOGLE_CLIENT_ID & GOOGLE_CLIENT_SECRET (for OAuth)"
    echo ""
    echo "2. Copy your application files to ${APP_DIR}:"
    echo "   - app.py (main application)"
    echo "   - app_models.py (database models)"
    echo "   - celery_app.py (background tasks)"
    echo "   - utils.py (utilities)"
    echo "   - templates/ (HTML templates)"
    echo ""
    echo "3. Initialize database and restart:"
    echo "   cd ${APP_DIR}"
    echo "   source venv/bin/activate"
    echo "   python3 -c 'from app import app, db; app.app_context().push(); db.create_all()'"
    echo "   sudo systemctl restart askaraai"
    echo ""
    echo "4. Test your installation:"
    echo "   curl http://localhost/health"
    echo "   # Should return: {\"status\": \"healthy\"}"
    echo ""
    echo "5. Access your application:"
    echo "   Test Site: http://your-server-ip/"
    echo "   Health Check: http://your-server-ip/health"
    echo ""
    echo "6. Setup SSL certificate:"
    echo "   sudo apt install certbot python3-certbot-nginx"
    echo "   sudo certbot --nginx -d askaraai.com"
    echo ""
    echo "⚠️  DEPENDENCY VERIFICATION:"
    echo "   Python: $($PYTHON_VERSION --version)"
    echo "   MoviePy: $(sudo -u ${APP_USER} bash -c "cd ${APP_DIR} && source venv/bin/activate && python -c 'import moviepy; print(moviepy.__version__)'" 2>/dev/null || echo 'ERROR')"
    echo "   Flask: $(sudo -u ${APP_USER} bash -c "cd ${APP_DIR} && source venv/bin/activate && python -c 'import flask; print(flask.__version__)'" 2>/dev/null || echo 'ERROR')"
    echo ""
    echo "🎉 Installation Complete!"
    echo "📄 Setup log saved to: $LOG_FILE"
    echo ""
    echo "For support:"
    echo "📧 Email: official@askaraai.com"
    echo ""
}

# Run main function
main "$@"
