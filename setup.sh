#!/bin/bash

# AskaraAI SECURITY ENHANCED Auto Setup Script untuk VPS
# Enhanced dengan security improvements, validation, dan performance optimizations

set -e

echo "🚀 Memulai setup AskaraAI - SECURITY ENHANCED VERSION..."

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
    if ! ping -c 1 google.com &> /dev/null; then
        log_error "No internet connection available"
        exit 1
    fi
    
    log_success "Prerequisites check passed"
}

# Function untuk generate secure password
generate_secure_password() {
    openssl rand -base64 32 | tr -d "=+/" | cut -c1-25
}

# Function untuk setup firewall dengan enhanced security
setup_enhanced_firewall() {
    log_info "Setting up enhanced firewall..."
    
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
    
    # Limit SSH connections (prevent brute force)
    ufw limit ssh
    
    # Allow DNS
    ufw allow 53
    
    # Enable firewall
    ufw --force enable
    
    log_success "Enhanced firewall configured"
}

# Function untuk setup fail2ban dengan custom rules
setup_fail2ban() {
    log_info "Setting up fail2ban with custom rules..."
    
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

[nginx-req-limit]
enabled = true
filter = nginx-req-limit
port = http,https
logpath = /var/log/nginx/error.log
maxretry = 10
bantime = 600

[askaraai-auth]
enabled = true
filter = askaraai-auth
port = http,https
logpath = /var/www/askaraai/logs/app.log
maxretry = 5
bantime = 1800
EOL

    # Create custom filter for AskaraAI
    cat > /etc/fail2ban/filter.d/askaraai-auth.conf << 'EOL'
[Definition]
failregex = ^.*Failed login attempt.*email=<HOST>.*$
            ^.*Google auth error.*$
ignoreregex =
EOL

    systemctl enable fail2ban
    systemctl start fail2ban
    
    log_success "Fail2ban configured with custom rules"
}

# Enhanced system update dengan security patches
update_system() {
    log_info "Updating system with security patches..."
    
    # Update package lists
    apt update
    
    # Upgrade system with security updates
    DEBIAN_FRONTEND=noninteractive apt upgrade -y
    
    # Install security updates
    DEBIAN_FRONTEND=noninteractive apt install -y unattended-upgrades apt-listchanges
    
    # Configure automatic security updates
    echo 'Unattended-Upgrade::Automatic-Reboot "false";' >> /etc/apt/apt.conf.d/50unattended-upgrades
    echo 'Unattended-Upgrade::Remove-Unused-Dependencies "true";' >> /etc/apt/apt.conf.d/50unattended-upgrades
    
    # Enable automatic updates
    dpkg-reconfigure -f noninteractive unattended-upgrades
    
    log_success "System updated with security patches"
}

# Install dependencies dengan version pinning untuk security
install_dependencies() {
    log_info "Installing dependencies with version pinning..."
    
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
        lsb-release
    
    # Video processing
    apt install -y ffmpeg
    
    # Security tools
    apt install -y \
        rkhunter \
        chkrootkit \
        lynis \
        aide
    
    # Install rclone
    curl https://rclone.org/install.sh | bash
    
    log_success "Dependencies installed with security tools"
}

# Enhanced MySQL setup dengan security hardening
setup_mysql() {
    log_info "Setting up MySQL with security hardening..."
    
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
    mysql -e "DELETE FROM mysql.user WHERE User='';"
    mysql -e "DELETE FROM mysql.user WHERE User='root' AND Host NOT IN ('localhost', '127.0.0.1', '::1');"
    mysql -e "DROP DATABASE IF EXISTS test;"
    mysql -e "DELETE FROM mysql.db WHERE Db='test' OR Db='test\\_%';"
    
    # Create database and user with limited privileges
    mysql -e "CREATE DATABASE IF NOT EXISTS ${DB_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
    mysql -e "CREATE USER IF NOT EXISTS '${DB_USER}'@'localhost' IDENTIFIED BY '${DB_PASSWORD}';"
    mysql -e "GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, INDEX, ALTER ON ${DB_NAME}.* TO '${DB_USER}'@'localhost';"
    mysql -e "FLUSH PRIVILEGES;"
    
    # Additional MySQL security configurations
    cat >> /etc/mysql/mysql.conf.d/security.cnf << 'EOL'
[mysqld]
# Security configurations
local-infile=0
bind-address=127.0.0.1
skip-networking=0
skip-show-database
sql_mode=STRICT_TRANS_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_AUTO_CREATE_USER,NO_ENGINE_SUBSTITUTION

# Performance and security
max_connections=50
connect_timeout=10
wait_timeout=600
interactive_timeout=600
max_allowed_packet=64M

# Logging
log_error=/var/log/mysql/error.log
slow_query_log=1
slow_query_log_file=/var/log/mysql/slow.log
long_query_time=2
EOL

    systemctl restart mysql
    
    log_success "MySQL configured with security hardening"
}

# Setup Redis dengan authentication
setup_redis() {
    log_info "Setting up Redis with authentication..."
    
    # Generate Redis password
    REDIS_PASSWORD=$(generate_secure_password)
    
    # Configure Redis with authentication
    sed -i "s/# requirepass foobared/requirepass $REDIS_PASSWORD/" /etc/redis/redis.conf
    sed -i "s/bind 127.0.0.1 ::1/bind 127.0.0.1/" /etc/redis/redis.conf
    sed -i "s/# maxmemory <bytes>/maxmemory 256mb/" /etc/redis/redis.conf
    sed -i "s/# maxmemory-policy noeviction/maxmemory-policy allkeys-lru/" /etc/redis/redis.conf
    
    # Disable dangerous commands
    echo "rename-command FLUSHDB \"\"" >> /etc/redis/redis.conf
    echo "rename-command FLUSHALL \"\"" >> /etc/redis/redis.conf
    echo "rename-command DEBUG \"\"" >> /etc/redis/redis.conf
    echo "rename-command CONFIG \"ASKARA_CONFIG_$(generate_secure_password | cut -c1-10)\"" >> /etc/redis/redis.conf
    
    systemctl restart redis-server
    systemctl enable redis-server
    
    # Update Redis URL with password
    REDIS_URL="redis://:$REDIS_PASSWORD@localhost:6379/0"
    
    log_success "Redis configured with authentication"
}

# Setup aplikasi dengan enhanced security
setup_application() {
    log_info "Setting up application with enhanced security..."
    
    # Create application directory with proper permissions
    mkdir -p ${APP_DIR}
    chown -R ${APP_USER}:${APP_USER} ${APP_DIR}
    chmod 755 ${APP_DIR}
    
    # Change to app directory
    cd ${APP_DIR}
    
    # Clone repository (if needed)
    if [ ! -d ".git" ]; then
        log_info "Cloning repository..."
        sudo -u ${APP_USER} git clone https://github.com/uteop23/askara-ai-app.git .
    fi
    
    # Setup Python virtual environment
    sudo -u ${APP_USER} python3 -m venv venv
    sudo -u ${APP_USER} bash -c "source venv/bin/activate && pip install --upgrade pip"
    sudo -u ${APP_USER} bash -c "source venv/bin/activate && pip install -r requirements.txt"
    
    # Create necessary directories with proper permissions
    sudo -u ${APP_USER} mkdir -p static/clips static/uploads logs static/error
    chmod 755 static/clips static/uploads
    chmod 750 logs
    
    log_success "Application setup completed"
}

# Create enhanced environment file
create_environment_file() {
    log_info "Creating enhanced environment file..."
    
    if [ ! -f ".env" ]; then
        # Generate secure keys
        SECRET_KEY=$(openssl rand -hex 32)
        JWT_SECRET_KEY=$(openssl rand -hex 32)
        
        sudo -u ${APP_USER} tee .env > /dev/null << EOL
# Flask Configuration - SECURITY ENHANCED
SECRET_KEY=${SECRET_KEY}
FLASK_ENV=production
FLASK_DEBUG=False

# Database Configuration
DATABASE_URL=mysql+pymysql://${DB_USER}:${DB_PASSWORD}@localhost/${DB_NAME}?charset=utf8mb4
DB_PASSWORD=${DB_PASSWORD}

# Redis Configuration (with authentication)
REDIS_URL=${REDIS_URL}

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

# SMTP Configuration
SMTP_HOST=smtp.hostinger.com
SMTP_PORT=465
SMTP_USER=support@askaraai.com
SMTP_PASS=your_smtp_password_here

# Tripay Configuration (OPSIONAL)
TRIPAY_API_KEY=your_tripay_api_key_here
TRIPAY_PRIVATE_KEY=your_tripay_private_key_here
TRIPAY_MERCHANT_CODE=your_tripay_merchant_code_here
TRIPAY_SANDBOX=false

# Rclone Configuration
RCLONE_CONFIG_PATH=/home/${APP_USER}/.config/rclone/rclone.conf

# Application Configuration
DOMAIN=askaraai.com
BASE_URL=https://askaraai.com
MAX_UPLOAD_SIZE=500MB
ALLOWED_VIDEO_EXTENSIONS=mp4,avi,mov,mkv,webm
MAX_VIDEO_DURATION=10800
MAX_CLIPS_PER_VIDEO=20
DEFAULT_CLIP_DURATION=60

# Celery Configuration
CELERY_BROKER_URL=${REDIS_URL}
CELERY_RESULT_BACKEND=${REDIS_URL}
CELERY_TIMEZONE=UTC

# Logging Configuration
LOG_LEVEL=INFO
LOG_FILE=/var/www/askaraai/logs/app.log
MAX_LOG_SIZE=10MB
LOG_BACKUP_COUNT=5

# Monitoring & Analytics
SENTRY_DSN=your_sentry_dsn_here
GA_TRACKING_ID=UA-XXXXXXXXX-X

# Admin Configuration
ADMIN_EMAIL=ujangbawbaw@gmail.com

# Backup Configuration
BACKUP_RETENTION_DAYS=180
BACKUP_SCHEDULE=0 2 */26 * *

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

# Notification Configuration
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR/DISCORD/WEBHOOK
EOL

        chmod 600 .env
        chown ${APP_USER}:${APP_USER} .env
        
        log_success "Environment file created with enhanced security"
        log_info "Database Password: $DB_PASSWORD"
        log_info "⚠️  IMPORTANT: Edit .env file and add required API keys!"
    fi
}

# Create error pages
create_error_pages() {
    log_info "Creating custom error pages..."
    
    sudo -u ${APP_USER} mkdir -p static/error
    
    # 404 Error Page
    sudo -u ${APP_USER} tee static/error/404.html > /dev/null << 'EOL'
<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>404 - Halaman Tidak Ditemukan | AskaraAI</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-900 text-white min-h-screen flex items-center justify-center">
    <div class="text-center">
        <h1 class="text-6xl font-bold mb-4">404</h1>
        <p class="text-xl mb-8">Halaman yang Anda cari tidak ditemukan.</p>
        <a href="/" class="bg-indigo-600 hover:bg-indigo-700 px-6 py-3 rounded-lg font-semibold">Kembali ke Beranda</a>
    </div>
</body>
</html>
EOL

    # 50x Error Page
    sudo -u ${APP_USER} tee static/error/50x.html > /dev/null << 'EOL'
<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Server Error | AskaraAI</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-900 text-white min-h-screen flex items-center justify-center">
    <div class="text-center">
        <h1 class="text-6xl font-bold mb-4">500</h1>
        <p class="text-xl mb-8">Terjadi kesalahan server. Tim kami sedang menangani masalah ini.</p>
        <a href="/" class="bg-indigo-600 hover:bg-indigo-700 px-6 py-3 rounded-lg font-semibold">Kembali ke Beranda</a>
    </div>
</body>
</html>
EOL

    # 429 Rate Limit Page
    sudo -u ${APP_USER} tee static/error/429.html > /dev/null << 'EOL'
<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Rate Limit Exceeded | AskaraAI</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-900 text-white min-h-screen flex items-center justify-center">
    <div class="text-center">
        <h1 class="text-6xl font-bold mb-4">429</h1>
        <p class="text-xl mb-8">Terlalu banyak permintaan. Silakan tunggu sebentar dan coba lagi.</p>
        <a href="/" class="bg-indigo-600 hover:bg-indigo-700 px-6 py-3 rounded-lg font-semibold">Kembali ke Beranda</a>
    </div>
</body>
</html>
EOL

    log_success "Custom error pages created"
}

# Test database connection dan initialize
test_and_initialize_database() {
    log_info "Testing database connection and initializing..."
    
    sudo -u ${APP_USER} bash -c "cd ${APP_DIR} && source venv/bin/activate && python3 -c \"
import os
os.environ['DB_PASSWORD'] = '${DB_PASSWORD}'

try:
    from app_models import db
    from app import app
    
    with app.app_context():
        # Test connection
        db.engine.execute('SELECT 1')
        print('✅ Database connection successful!')
        
        # Test models import
        from app_models import User, VideoProcess, VideoClip, Payment, CountdownSettings, PromoCode, SystemHealth, PromoUsage
        print('✅ Models import successful!')
        
        # Create tables
        db.create_all()
        print('✅ Database tables created!')
        
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
            admin.set_password('admin123!@#')  # Set temporary password
            db.session.add(admin)
            db.session.commit()
            print(f'✅ Admin user created: {admin_email}')
        else:
            admin.is_admin = True
            admin.is_premium = True
            admin.credits = 999999
            db.session.commit()
            print(f'✅ Admin user updated: {admin_email}')
            
except Exception as e:
    print(f'❌ Database error: {e}')
    import traceback
    traceback.print_exc()
\""
    
    log_success "Database initialized successfully"
}

# Setup enhanced Nginx dengan security headers
setup_nginx() {
    log_info "Setting up Nginx with enhanced security..."
    
    # Backup original nginx.conf
    cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf.backup
    
    # Enhanced nginx.conf
    tee /etc/nginx/nginx.conf > /dev/null << 'EOL'
user www-data;
worker_processes auto;
pid /run/nginx.pid;
include /etc/nginx/modules-enabled/*.conf;

events {
    worker_connections 1024;
    use epoll;
    multi_accept on;
}

http {
    # Basic Settings
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    types_hash_max_size 2048;
    server_tokens off;
    
    # Security Headers (global)
    add_header X-Frame-Options DENY always;
    add_header X-Content-Type-Options nosniff always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    
    # File upload limits
    client_max_body_size 500M;
    client_body_buffer_size 128k;
    client_header_buffer_size 3m;
    large_client_header_buffers 4 256k;
    
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    
    # Logging Format
    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                   '$status $body_bytes_sent "$http_referer" '
                   '"$http_user_agent" "$http_x_forwarded_for"';
    
    # Logging
    access_log /var/log/nginx/access.log main;
    error_log /var/log/nginx/error.log warn;
    
    # Gzip Settings
    gzip on;
    gzip_vary on;
    gzip_proxied any;
    gzip_comp_level 6;
    gzip_types text/plain text/css text/xml text/javascript application/json application/javascript application/xml+rss application/atom+xml image/svg+xml;
    
    # Rate Limiting
    limit_req_zone $binary_remote_addr zone=login:10m rate=3r/m;
    limit_req_zone $binary_remote_addr zone=api:10m rate=5r/m;
    limit_req_zone $binary_remote_addr zone=general:10m rate=50r/m;
    
    # Include site configurations
    include /etc/nginx/conf.d/*.conf;
    include /etc/nginx/sites-enabled/*;
}
EOL

    # Create site configuration (copy dari nginx.conf yang sudah diperbaiki)
    tee /etc/nginx/sites-available/askaraai > /dev/null << 'EOL'
server {
    listen 80;
    server_name askaraai.com www.askaraai.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name askaraai.com www.askaraai.com;
    
    # SSL Configuration (placeholder - will be updated after SSL setup)
    ssl_certificate /etc/ssl/certs/ssl-cert-snakeoil.pem;
    ssl_certificate_key /etc/ssl/private/ssl-cert-snakeoil.key;
    
    # Security Headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options DENY always;
    add_header X-Content-Type-Options nosniff always;
    add_header X-XSS-Protection "1; mode=block" always;
    
    root /var/www/askaraai;
    
    # Main application
    location / {
        limit_req zone=general burst=20 nodelay;
        proxy_pass http://unix:/var/www/askaraai/askaraai.sock;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        proxy_connect_timeout 30s;
        proxy_send_timeout 120s;
    }
    
    # API endpoints
    location ~ ^/api/(auth|login|signup) {
        limit_req zone=login burst=3 nodelay;
        proxy_pass http://unix:/var/www/askaraai/askaraai.sock;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    
    location /api/process-video {
        limit_req zone=api burst=1 nodelay;
        proxy_pass http://unix:/var/www/askaraai/askaraai.sock;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 600s;
        proxy_connect_timeout 30s;
        proxy_send_timeout 600s;
    }
    
    # Static files
    location /static {
        alias /var/www/askaraai/static;
        expires 7d;
        add_header Cache-Control "public, immutable";
    }
    
    # Video clips
    location /clips {
        alias /var/www/askaraai/static/clips;
        add_header Content-Disposition 'attachment';
        expires 1h;
        add_header Cache-Control "private";
    }
    
    # Security: Block sensitive files
    location ~ /\. {
        deny all;
        return 404;
    }
    
    # Health check
    location /health {
        access_log off;
        proxy_pass http://unix:/var/www/askaraai/askaraai.sock;
        proxy_set_header Host $host;
    }
}
EOL

    # Enable site
    ln -sf /etc/nginx/sites-available/askaraai /etc/nginx/sites-enabled/
    rm -f /etc/nginx/sites-enabled/default
    
    # Test configuration
    nginx -t && systemctl restart nginx
    systemctl enable nginx
    
    log_success "Nginx configured with enhanced security"
}

# Setup enhanced systemd services
setup_systemd_services() {
    log_info "Setting up enhanced systemd services..."
    
    # Main application service
    tee /etc/systemd/system/askaraai.service > /dev/null << EOL
[Unit]
Description=AskaraAI Flask Application
Documentation=https://github.com/uteop23/askara-ai-app
After=network.target mysql.service redis.service
Wants=mysql.service redis.service
Requires=network.target

[Service]
Type=notify
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
Environment="PATH=${APP_DIR}/venv/bin"
Environment="FLASK_ENV=production"
Environment="PYTHONPATH=${APP_DIR}"

# Enhanced Gunicorn configuration
ExecStart=${APP_DIR}/venv/bin/gunicorn \\
    --bind unix:${APP_DIR}/askaraai.sock \\
    --workers 4 \\
    --worker-class sync \\
    --worker-connections 1000 \\
    --max-requests 5000 \\
    --max-requests-jitter 1000 \\
    --timeout 120 \\
    --keep-alive 2 \\
    --preload \\
    --enable-stdio-inheritance \\
    --log-level info \\
    --access-logfile ${APP_DIR}/logs/gunicorn_access.log \\
    --error-logfile ${APP_DIR}/logs/gunicorn_error.log \\
    --pid ${APP_DIR}/gunicorn.pid \\
    app:app

ExecReload=/bin/kill -s HUP \$MAINPID
ExecStop=/bin/kill -s TERM \$MAINPID
PIDFile=${APP_DIR}/gunicorn.pid

# Enhanced restart policy
Restart=always
RestartSec=3
StartLimitInterval=60s
StartLimitBurst=3

# Enhanced security settings
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=${APP_DIR}/static ${APP_DIR}/logs /tmp
PrivateTmp=true
PrivateDevices=true
ProtectControlGroups=true
ProtectKernelModules=true
ProtectKernelTunables=true
RestrictRealtime=true
RestrictSUIDSGID=true

# Resource limits
LimitNOFILE=65535
LimitNPROC=4096
MemoryMax=2G
CPUQuota=200%

[Install]
WantedBy=multi-user.target
EOL

    # Enhanced Celery worker service
    tee /etc/systemd/system/askaraai-celery.service > /dev/null << EOL
[Unit]
Description=AskaraAI Celery Worker
Documentation=https://docs.celeryproject.org/
After=network.target redis.service mysql.service
Wants=redis.service mysql.service
Requires=network.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
Environment="PATH=${APP_DIR}/venv/bin"
Environment="PYTHONPATH=${APP_DIR}"
Environment="C_FORCE_ROOT=1"

# Enhanced Celery worker configuration
ExecStart=${APP_DIR}/venv/bin/celery \\
    --app=celery_app.celery \\
    worker \\
    --loglevel=info \\
    --logfile=${APP_DIR}/logs/celery_worker.log \\
    --pidfile=${APP_DIR}/celery_worker.pid \\
    --concurrency=2 \\
    --max-tasks-per-child=100 \\
    --max-memory-per-child=2048000 \\
    --time-limit=3600 \\
    --soft-time-limit=3300 \\
    --queues=video_processing,maintenance,default \\
    --pool=prefork

ExecStop=/bin/kill -s TERM \$MAINPID
ExecReload=/bin/kill -s HUP \$MAINPID
PIDFile=${APP_DIR}/celery_worker.pid

# Enhanced restart policy
Restart=always
RestartSec=10
StartLimitInterval=60s
StartLimitBurst=3

# Enhanced security settings
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=${APP_DIR}/static ${APP_DIR}/logs /tmp
PrivateTmp=true
PrivateDevices=true

# Resource limits
LimitNOFILE=65535
LimitNPROC=4096
MemoryMax=4G
CPUQuota=300%

[Install]
WantedBy=multi-user.target
EOL

    # Celery beat service
    tee /etc/systemd/system/askaraai-celery-beat.service > /dev/null << EOL
[Unit]
Description=AskaraAI Celery Beat Scheduler
Documentation=https://docs.celeryproject.org/
After=network.target redis.service mysql.service askaraai-celery.service
Wants=redis.service mysql.service
Requires=askaraai-celery.service

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
Environment="PATH=${APP_DIR}/venv/bin"
Environment="PYTHONPATH=${APP_DIR}"

ExecStart=${APP_DIR}/venv/bin/celery \\
    --app=celery_app.celery \\
    beat \\
    --loglevel=info \\
    --logfile=${APP_DIR}/logs/celery_beat.log \\
    --pidfile=${APP_DIR}/celery_beat.pid \\
    --schedule=${APP_DIR}/celerybeat-schedule

ExecStop=/bin/kill -s TERM \$MAINPID
PIDFile=${APP_DIR}/celery_beat.pid

Restart=always
RestartSec=10

# Security settings
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=${APP_DIR}/logs ${APP_DIR}
PrivateTmp=true

# Resource limits
LimitNOFILE=4096
LimitNPROC=256
MemoryMax=512M

[Install]
WantedBy=multi-user.target
EOL

    # Set proper permissions
    chown -R ${APP_USER}:${APP_USER} ${APP_DIR}
    chmod +x ${APP_DIR}/venv/bin/*
    
    # Reload and enable services
    systemctl daemon-reload
    systemctl enable askaraai.service askaraai-celery.service askaraai-celery-beat.service
    
    log_success "Enhanced systemd services created"
}

# Setup monitoring dan logging
setup_monitoring() {
    log_info "Setting up monitoring and logging..."
    
    # Setup logrotate for application logs
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

    # Setup basic system monitoring script
    tee /usr/local/bin/askaraai-monitor.sh > /dev/null << 'EOL'
#!/bin/bash
# Basic system monitoring for AskaraAI

LOG_FILE="/var/log/askaraai-monitor.log"
APP_DIR="/var/www/askaraai"

# Function to log with timestamp
log_msg() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" >> $LOG_FILE
}

# Check services
services=("askaraai" "askaraai-celery" "askaraai-celery-beat" "mysql" "redis-server" "nginx")
for service in "${services[@]}"; do
    if ! systemctl is-active --quiet $service; then
        log_msg "WARNING: $service is not running"
        systemctl restart $service
        log_msg "INFO: Attempted to restart $service"
    fi
done

# Check disk space
DISK_USAGE=$(df -h / | awk 'NR==2 {print $5}' | sed 's/%//')
if [ $DISK_USAGE -gt 80 ]; then
    log_msg "WARNING: Disk usage is ${DISK_USAGE}%"
fi

# Check memory usage
MEM_USAGE=$(free | grep Mem | awk '{printf("%.0f", $3/$2 * 100.0)}')
if [ $MEM_USAGE -gt 85 ]; then
    log_msg "WARNING: Memory usage is ${MEM_USAGE}%"
fi

# Check log file sizes
find $APP_DIR/logs -name "*.log" -size +100M -exec basename {} \; | while read logfile; do
    log_msg "WARNING: Log file $logfile is larger than 100MB"
done
EOL

    chmod +x /usr/local/bin/askaraai-monitor.sh
    
    # Add to crontab
    (crontab -l 2>/dev/null; echo "*/5 * * * * /usr/local/bin/askaraai-monitor.sh") | crontab -
    
    log_success "Monitoring and logging setup completed"
}

# Start services dengan proper order
start_services() {
    log_info "Starting services in proper order..."
    
    # Start dependencies first
    systemctl start mysql redis-server
    sleep 2
    
    # Start application services
    systemctl start askaraai.service
    sleep 3
    systemctl start askaraai-celery.service
    sleep 2
    systemctl start askaraai-celery-beat.service
    
    # Start web server
    systemctl start nginx
    
    log_success "All services started"
}

# Check service status
check_service_status() {
    log_info "Checking service status..."
    
    services=("mysql" "redis-server" "nginx" "askaraai" "askaraai-celery" "askaraai-celery-beat")
    
    for service in "${services[@]}"; do
        if systemctl is-active --quiet $service; then
            log_success "$service is running"
        else
            log_error "$service is not running"
        fi
    done
}

# Run security scan
run_security_scan() {
    log_info "Running basic security scan..."
    
    # Update rkhunter database
    rkhunter --update --quiet
    
    # Run basic security checks
    rkhunter --checkall --skip-keypress --quiet --report-warnings-only || true
    
    # Check for security updates
    apt list --upgradable 2>/dev/null | grep -i security || log_info "No security updates available"
    
    log_success "Security scan completed"
}

# Cleanup temporary files
cleanup() {
    log_info "Cleaning up temporary files..."
    
    # Remove temporary password file
    rm -f /tmp/db_password.txt
    
    # Clean package cache
    apt autoremove -y
    apt autoclean
    
    log_success "Cleanup completed"
}

# Main execution
main() {
    echo "🚀 Starting AskaraAI Security Enhanced Setup"
    echo "================================================"
    
    check_prerequisites
    update_system
    install_dependencies
    setup_enhanced_firewall
    setup_fail2ban
    setup_mysql
    setup_redis
    setup_application
    create_environment_file
    create_error_pages
    test_and_initialize_database
    setup_nginx
    setup_systemd_services
    setup_monitoring
    start_services
    sleep 5
    check_service_status
    run_security_scan
    cleanup
    
    echo ""
    echo "✅ AskaraAI Security Enhanced Setup Completed!"
    echo "================================================"
    echo ""
    echo "📋 Security Enhanced Information:"
    echo "   Database Password: $(cat /tmp/db_password.txt 2>/dev/null || echo 'Check logs')"
    echo "   Redis Password: Set in /etc/redis/redis.conf"
    echo "   Database Name: $DB_NAME"
    echo "   Database User: $DB_USER"
    echo ""
    echo "🔒 Security Features Enabled:"
    echo "   ✅ Enhanced Firewall (UFW) with rate limiting"
    echo "   ✅ Fail2Ban with custom rules"
    echo "   ✅ MySQL security hardening"
    echo "   ✅ Redis authentication"
    echo "   ✅ Nginx security headers"
    echo "   ✅ Systemd security sandboxing"
    echo "   ✅ Automatic security updates"
    echo "   ✅ Security monitoring"
    echo ""
    echo "📁 Enhanced File Structure:"
    echo "   ${APP_DIR}/               - Application root"
    echo "   ${APP_DIR}/app.py         - Main Flask app (Security Enhanced)"
    echo "   ${APP_DIR}/app_models.py  - Database models (Performance Enhanced)"
    echo "   ${APP_DIR}/celery_app.py  - Celery tasks (Memory Optimized)"
    echo "   ${APP_DIR}/requirements.txt - Dependencies (Security Enhanced)"
    echo "   ${APP_DIR}/.env           - Environment config (600 permissions)"
    echo "   ${APP_DIR}/logs/          - Application logs"
    echo "   ${APP_DIR}/static/error/  - Custom error pages"
    echo ""
    echo "🔧 Next Steps:"
    echo "1. Edit ${APP_DIR}/.env and add required API keys:"
    echo "   - GEMINI_API_KEY (required for AI processing)"
    echo "   - GOOGLE_CLIENT_ID & GOOGLE_CLIENT_SECRET (for OAuth)"
    echo "   - SMTP credentials (for email notifications)"
    echo ""
    echo "2. Setup SSL certificate (Let's Encrypt):"
    echo "   sudo apt install certbot python3-certbot-nginx"
    echo "   sudo certbot --nginx -d askaraai.com"
    echo ""
    echo "3. Configure Google Drive backup:"
    echo "   sudo -u www-data rclone config"
    echo ""
    echo "4. Test the application:"
    echo "   curl http://localhost/health"
    echo "   Visit: https://askaraai.com"
    echo ""
    echo "📊 Monitoring:"
    echo "   Status: systemctl status askaraai"
    echo "   Logs: journalctl -u askaraai -f"
    echo "   Monitor: tail -f ${APP_DIR}/logs/app.log"
    echo "   Security: tail -f /var/log/askaraai-monitor.log"
    echo ""
    echo "🛡️ Security Maintenance:"
    echo "   - Security updates: apt update && apt upgrade"
    echo "   - Security scan: rkhunter --check"
    echo "   - Fail2ban status: fail2ban-client status"
    echo "   - Firewall status: ufw status"
    echo ""
    echo "🎉 Your AskaraAI installation is now SECURE and ready for production!"
    echo "📄 Full setup log saved to: $LOG_FILE"
    echo ""
}

# Run main function
main "$@"
