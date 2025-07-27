    #!/bin/bash

    # AskaraAI COMPLETE Auto Setup Script - REPAIRED & SYNCED VERSION
    # Semua bug yang ditemukan telah diperbaiki, sinkron dengan file proyek.

    set -e

    echo "🚀 Memulai setup AskaraAI - VERSI PERBAIKAN..."

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
        if [[ $EUID -ne 0 ]]; then log_error "This script must be run as root (use sudo)"; exit 1; fi
        if ! command -v apt &> /dev/null; then log_error "This script requires Ubuntu/Debian with apt package manager"; exit 1; fi
        if ! ping -c 1 8.8.8.8 &> /dev/null; then log_error "No internet connection available"; exit 1; fi
        available_space=$(df / | awk 'NR==2 {print $4}')
        if [ $available_space -lt 5242880 ]; then log_error "Insufficient disk space. At least 5GB required."; exit 1; fi
        log_success "Prerequisites check passed"
    }

    # Enhanced system update
    update_system() {
        log_info "Updating system..."
        apt --fix-broken install -y
        apt update
        DEBIAN_FRONTEND=noninteractive apt upgrade -y
        DEBIAN_FRONTEND=noninteractive apt install -y unattended-upgrades
        echo 'APT::Periodic::Update-Package-Lists "1";' > /etc/apt/apt.conf.d/20auto-upgrades
        echo 'APT::Periodic::Unattended-Upgrade "1";' >> /etc/apt/apt.conf.d/20auto-upgrades
        log_success "System updated"
    }

    # Install dependencies (FIXED VERSIONS)
    install_dependencies() {
        log_info "Installing dependencies with fixed versions..."
        apt install -y software-properties-common
        add-apt-repository -y ppa:deadsnakes/ppa || true
        apt update
        
        # Essential packages - FIXED for Ubuntu 22.04
        apt install -y \
            $PYTHON_VERSION \
            python3-pip \
            python3-venv \
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
        
        # Video processing dependencies
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
        
        if ! command -v pip3 &> /dev/null; then
            curl https://bootstrap.pypa.io/get-pip.py | $PYTHON_VERSION
        fi
        
        $PYTHON_VERSION -m pip install --upgrade pip setuptools wheel
        
        log_success "Dependencies installed"
    }

    # MySQL setup (REPAIRED: DISABLED FOR MANUAL SETUP)
    #setup_mysql() { ... }

    # Setup Redis (FIXED)
    setup_redis() {
        log_info "Setting up Redis..."
        systemctl start redis-server
        systemctl enable redis-server
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
        mkdir -p ${APP_DIR}
        chown -R ${APP_USER}:${APP_USER} ${APP_DIR}
        chmod 755 ${APP_DIR}
        cd ${APP_DIR}
        
        sudo -u ${APP_USER} $PYTHON_VERSION -m venv venv
        sudo -u ${APP_USER} bash -c "source venv/bin/activate && pip install --upgrade pip setuptools wheel"
        
        # Create requirements.txt with REPAIRED & COMPATIBLE versions
        sudo -u ${APP_USER} tee requirements.txt > /dev/null << 'EOL'
    Flask==2.2.2
    Flask-SQLAlchemy==3.0.3
    SQLAlchemy==1.4.46
    Werkzeug==2.3.8
    Flask-Login==0.6.2
    Flask-Mail==0.9.1
    Flask-Limiter==3.5.0
    Flask-Caching==2.1.0
    flask-marshmallow==0.15.0
    marshmallow==3.20.1
    celery==5.3.6
    redis==5.0.1
    kombu==5.3.4
    google-generativeai==0.3.2
    google-auth==2.25.2
    google-auth-oauthlib==1.1.0
    yt-dlp==2023.12.30
    moviepy==1.0.3
    imageio==2.31.6
    imageio-ffmpeg==0.4.9
    ffmpeg-python==0.2.0
    Pillow==10.0.1
    numpy==1.24.4
    decorator==4.4.2
    tqdm==4.66.1
    proglog==0.1.10
    gunicorn==21.2.0
    python-dotenv==1.0.0
    python-dateutil==2.8.2
    validators==0.22.0
    structlog==23.2.0
    psutil==5.9.6
    email-validator==2.1.0
    typing-extensions==4.8.0
    PyMySQL==1.1.1
    EOL
        
        log_info "Installing Python requirements (this may take 5-10 minutes)..."
        sudo -u ${APP_USER} bash -c "source venv/bin/activate && pip install -r requirements.txt" || {
            log_error "Failed to install requirements"
            return 1
        }
        
        # Test MoviePy installation - FIXED SYNTAX
        sudo -u ${APP_USER} bash -c "source venv/bin/activate && python -c 'import moviepy.editor as mp; print(\"MoviePy OK\")'" || {
            log_error "MoviePy installation verification failed"
            return 1
        }
        
        # Verify critical imports
        sudo -u ${APP_USER} bash -c "source venv/bin/activate && python -c 'import flask, celery, redis, moviepy.editor, google.generativeai; print(\"All critical imports OK\")'" || {
            log_error "Import verification failed"
            return 1
        }
        
        sudo -u ${APP_USER} mkdir -p static/clips static/uploads static/error logs templates backup
        chmod 755 static/clips static/uploads templates static/error backup
        chmod 750 logs
        
        sudo -u ${APP_USER} mkdir -p static/error
        
        sudo -u ${APP_USER} tee static/error/404.html > /dev/null << 'EOL'
    <!DOCTYPE html><html><head><title>404 - Not Found</title></head><body><h1>404</h1></body></html>
    EOL
        sudo -u ${APP_USER} tee static/error/50x.html > /dev/null << 'EOL'
    <!DOCTYPE html><html><head><title>500 - Server Error</title></head><body><h1>500</h1></body></html>
    EOL
        sudo -u ${APP_USER} tee static/error/429.html > /dev/null << 'EOL'
    <!DOCTYPE html><html><head><title>429 - Too Many Requests</title></head><body><h1>429</h1></body></html>
    EOL
        
        log_success "Application setup completed"
    }

    # Create environment file (FIXED)
    create_environment_file() {
        log_info "Creating environment file..."
        if [ ! -f ".env" ]; then
            SECRET_KEY=$(openssl rand -hex 32)
            JWT_SECRET_KEY=$(openssl rand -hex 32)
            DB_PASSWORD="PASTE_YOUR_MANUAL_DB_PASSWORD_HERE"
            
            sudo -u ${APP_USER} tee .env > /dev/null << EOL
    # Flask Configuration
    SECRET_KEY=${SECRET_KEY}
    FLASK_ENV=production
    # Database Configuration
    DATABASE_URL=mysql+pymysql://${DB_USER}:${DB_PASSWORD}@127.0.0.1/${DB_NAME}?charset=utf8mb4
    DB_PASSWORD=${DB_PASSWORD}
    # Redis Configuration
    REDIS_URL=redis://localhost:6379/0
    # ... (rest of .env content from your .env.example)
    EOL
            chmod 600 .env
            chown ${APP_USER}:${APP_USER} .env
            log_success "Environment file created"
            log_info "⚠️  IMPORTANT: Edit .env file and add required API keys and your manual DB password!"
        fi
    }

    # Create minimal app.py for testing - FIXED SYNTAX
    create_minimal_app() {
        log_info "Creating minimal test application..."
        
        sudo -u ${APP_USER} tee app.py > /dev/null << 'EOL'
    #!/usr/bin/env python3
    import os
    from flask import Flask, jsonify, render_template_string
    from dotenv import load_dotenv
    load_dotenv()
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-key')
    @app.route('/health')
    def health_check():
        return jsonify({'status': 'healthy', 'message': 'AskaraAI test app is running'})
    @app.route('/')
    def index():
        return render_template_string('<h1>✅ AskaraAI Setup Complete!</h1><p>Your server is running. Please follow the manual steps to complete the setup.</p>')
    if __name__ == '__main__':
        app.run(debug=False, host='0.0.0.0', port=5000)
    EOL

        sudo -u ${APP_USER} bash -c "cd ${APP_DIR} && source venv/bin/activate && python -c 'import app; print(\"App import successful\")'" || {
            log_error "App test failed"
            return 1
        }
        log_success "Minimal app created and tested"
    }

    # Setup firewall (BASIC)
    setup_firewall() {
        log_info "Setting up basic firewall..."
        apt install -y ufw
        ufw --force reset
        ufw default deny incoming
        ufw default allow outgoing
        ufw allow ssh
        ufw allow 80/tcp
        ufw allow 443/tcp
        ufw limit ssh
        ufw --force enable
        log_success "Firewall configured"
    }

    # Setup fail2ban (BASIC)
    setup_fail2ban() {
        log_info "Setting up fail2ban..."
        apt install -y fail2ban
        cat > /etc/fail2ban/jail.local << 'EOL'
    [DEFAULT]
    bantime = 3600
    findtime = 600
    maxretry = 3
    [sshd]
    enabled = true
    [nginx-http-auth]
    enabled = true
    EOL
        systemctl enable fail2ban
        systemctl start fail2ban
        log_success "Fail2ban configured"
    }

    # Setup Nginx (SIMPLIFIED)
    setup_nginx() {
        log_info "Setting up Nginx..."
        tee /etc/nginx/sites-available/askaraai > /dev/null << EOL
    server {
        listen 80 default_server;
        server_name _;
        client_max_body_size 500M;
        location / {
            proxy_pass http://unix:/var/www/askaraai/askaraai.sock;
            proxy_set_header Host \$host;
            proxy_set_header X-Real-IP \$remote_addr;
            proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto \$scheme;
            proxy_connect_timeout 30s;
            proxy_send_timeout 120s;
            proxy_read_timeout 120s;
        }
        location /static/ {
            alias /var/www/askaraai/static/;
            expires 7d;
        }
        location /health {
            proxy_pass http://unix:/var/www/askaraai/askaraai.sock;
            access_log off;
        }
    }
    EOL
        ln -sf /etc/nginx/sites-available/askaraai /etc/nginx/sites-enabled/
        rm -f /etc/nginx/sites-enabled/default
        nginx -t && systemctl restart nginx
        systemctl enable nginx
        log_success "Nginx configured"
    }

    # Setup systemd service (SIMPLIFIED)
    setup_systemd_service() {
        log_info "Setting up systemd service..."
        tee /etc/systemd/system/askaraai.service > /dev/null << EOL
    [Unit]
    Description=AskaraAI Flask Application
    After=network.target
    [Service]
    Type=notify
    User=${APP_USER}
    Group=${APP_USER}
    WorkingDirectory=${APP_DIR}
    Environment="PATH=${APP_DIR}/venv/bin"
    ExecStart=${APP_DIR}/venv/bin/gunicorn --workers 2 --bind unix:askaraai.sock app:app
    Restart=always
    [Install]
    WantedBy=multi-user.target
    EOL
        chown -R ${APP_USER}:${APP_USER} ${APP_DIR}
        systemctl daemon-reload
        systemctl enable askaraai.service
        log_success "Systemd service created"
    }

    # Start services
    start_services() {
        log_info "Starting services..."
        systemctl start redis-server
        systemctl start askaraai.service
        systemctl start nginx
        log_success "All services started"
    }

    # Check service status
    check_services() {
        log_info "Checking service status..."
        services=("redis-server" "nginx" "askaraai")
        for service in "${services[@]}"; do
            if systemctl is-active --quiet $service; then
                log_success "$service is running"
            else
                log_error "$service is not running"
                systemctl restart $service
            fi
        done
    }

    # Main execution
    main() {
        echo "🚀 Starting AskaraAI REPAIRED Setup (Production Ready)"
        echo "=================================================="
        
        check_prerequisites
        update_system
        install_dependencies
        #setup_mysql # DISABLED - Lakukan secara manual
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
        
        echo ""
        echo "✅ AskaraAI Server Setup Completed Successfully!"
        echo "=============================================="
        echo ""
        log_info "LANGKAH MANUAL BERIKUTNYA (WAJIB):"
        echo "--------------------------------------------------"
        echo "1. INSTAL & AMANKAN MYSQL:"
        echo "   sudo apt install mysql-server -y"
        echo "   sudo mysql_secure_installation"
        echo " "
        echo "2. BUAT DATABASE & USER:"
        echo "   sudo mysql -u root -p"
        echo "   > CREATE DATABASE ${DB_NAME};"
        echo "   > CREATE USER '${DB_USER}'@'localhost' IDENTIFIED BY 'PASSWORD_KUAT_ANDA';"
        echo "   > GRANT ALL PRIVILEGES ON ${DB_NAME}.* TO '${DB_USER}'@'localhost';"
        echo "   > FLUSH PRIVILEGES; EXIT;"
        echo " "
        echo "3. EDIT FILE .env:"
        echo "   sudo nano ${APP_DIR}/.env"
        echo "   (Isi DB_PASSWORD, API keys, dll.)"
        echo " "
        echo "4. SALIN FILE APLIKASI LENGKAP ANDA:"
        echo "   sudo cp /home/askarauser/askara-ai-app/*.py ${APP_DIR}/"
        echo "   sudo cp /home/askarauser/askara-ai-app/*.html ${APP_DIR}/templates/"
        echo " "
        echo "5. INISIALISASI DATABASE:"
        echo "   cd ${APP_DIR}"
        echo "   sudo -u www-data bash -c \"source venv/bin/activate && python3 -c 'from app import app, db; app.app_context().push(); db.create_all()'\""
        echo " "
        echo "6. RESTART APLIKASI:"
        echo "   sudo systemctl restart askaraai"
        echo " "
        echo "7. SETUP SSL (HTTPS):"
        echo "   sudo certbot --nginx -d domainanda.com"
        echo ""
        log_info "Instalasi selesai. Ikuti langkah manual di atas untuk menyelesaikan."
    }

    # Run main function
    main "$@"
    
