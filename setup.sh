#!/bin/bash

# AskaraAI Auto Setup Script untuk VPS - UPDATED VERSION
# Updated untuk mengakomodasi struktur file baru dengan app_models.py

set -e

echo "🚀 Memulai setup AskaraAI - UPDATED VERSION dengan struktur baru..."

# --- Variabel ---
APP_DIR="/var/www/askaraai"
APP_USER="www-data"
DB_NAME="askaraai_db"
DB_USER="askaraai"

# Update sistem
echo "📦 Updating sistem..."
sudo apt update && sudo apt upgrade -y

# Install dependencies
echo "🔧 Installing dependencies..."
sudo apt install -y python3 python3-pip python3-venv nginx redis-server mysql-server ufw fail2ban git curl wget openssl

# Setup firewall
echo "🔒 Setting up firewall..."
sudo ufw allow ssh
sudo ufw allow 'Nginx Full'
sudo ufw --force enable

# Setup fail2ban
echo "🛡️ Configuring fail2ban..."
sudo systemctl enable fail2ban
sudo systemctl start fail2ban

# Setup MySQL dengan password yang aman
echo "🗄️ Setting up MySQL..."

# Generate password yang kuat dan simpan ke file
DB_PASSWORD=$(openssl rand -base64 32 | tr -d "=+/" | cut -c1-25)
echo "Generated DB Password: $DB_PASSWORD"

# Simpan password ke file temporary untuk script bisa akses
echo "$DB_PASSWORD" > /tmp/db_password.txt
chmod 600 /tmp/db_password.txt

# Setup MySQL
sudo mysql -e "CREATE DATABASE IF NOT EXISTS ${DB_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
sudo mysql -e "CREATE USER IF NOT EXISTS '${DB_USER}'@'localhost' IDENTIFIED BY '${DB_PASSWORD}';"
sudo mysql -e "GRANT ALL PRIVILEGES ON ${DB_NAME}.* TO '${DB_USER}'@'localhost';"
sudo mysql -e "FLUSH PRIVILEGES;"
echo "✅ MySQL database dan user berhasil dibuat."

# Setup aplikasi directory
echo "📁 Setting up application directory..."
sudo mkdir -p ${APP_DIR}
sudo chown -R ${APP_USER}:${APP_USER} ${APP_DIR}

# Change to app directory
cd ${APP_DIR}

# Clone dari GitHub jika belum ada
if [ ! -d ".git" ]; then
    echo "📥 Cloning dari GitHub..."
    sudo -u ${APP_USER} git clone https://github.com/uteop23/askara-ai-app.git .
fi

# Setup Python virtual environment
echo "🐍 Setting up Python environment..."
sudo -u ${APP_USER} python3 -m venv venv
sudo -u ${APP_USER} bash -c "source venv/bin/activate && pip install --upgrade pip"
sudo -u ${APP_USER} bash -c "source venv/bin/activate && pip install -r requirements.txt"

# Setup environment file dengan password yang benar
echo "⚙️ Creating environment file..."
if [ ! -f ".env" ]; then
    SECRET_KEY=$(openssl rand -hex 32)
    
    sudo -u ${APP_USER} tee .env > /dev/null << EOL
# Flask Configuration
SECRET_KEY=${SECRET_KEY}
FLASK_ENV=production
FLASK_DEBUG=False

# Database Configuration
DATABASE_URL=mysql+pymysql://${DB_USER}:${DB_PASSWORD}@localhost/${DB_NAME}
DB_PASSWORD=${DB_PASSWORD}

# Redis Configuration
REDIS_URL=redis://localhost:6379/0

# Gemini AI Configuration (HARUS DIISI MANUAL)
GEMINI_API_KEY=your_gemini_api_key_here

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

# Admin Email
ADMIN_EMAIL=ujangbawbaw@gmail.com
EOL

    echo "✅ File .env berhasil dibuat dengan password database: $DB_PASSWORD"
    echo "⚠️  PENTING: Edit file .env dan isi API keys yang diperlukan!"
fi

# Setup direktori untuk uploads dan logs
sudo -u ${APP_USER} mkdir -p static/clips static/uploads logs

# Install FFmpeg & Rclone
echo "🎬 Installing FFmpeg & Rclone..."
sudo apt install -y ffmpeg
curl https://rclone.org/install.sh | sudo bash

# Buat file nginx.conf jika tidak ada
echo "📝 Creating Nginx configuration..."
sudo tee /etc/nginx/sites-available/askaraai > /dev/null << 'EOL'
server {
    listen 80;
    server_name askaraai.com www.askaraai.com;
    
    client_max_body_size 100M;
    
    location / {
        proxy_pass http://unix:/var/www/askaraai/askaraai.sock;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300;
        proxy_connect_timeout 300;
        proxy_send_timeout 300;
    }
    
    location /static {
        alias /var/www/askaraai/static;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
    
    location /clips {
        alias /var/www/askaraai/static/clips;
        add_header Content-Disposition 'attachment';
        expires 7d;
        add_header Cache-Control "public";
    }
}
EOL

# Setup Nginx
echo "🌐 Setting up Nginx..."
sudo ln -sf /etc/nginx/sites-available/askaraai /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx

# Test database connection dengan struktur baru
echo "🧪 Testing database connection with new structure..."
sudo -u ${APP_USER} bash -c "cd ${APP_DIR} && source venv/bin/activate && python3 -c \"
import os
os.environ['DB_PASSWORD'] = '${DB_PASSWORD}'

# Test import struktur baru
try:
    from app_models import db
    from app import app
    
    with app.app_context():
        db.engine.execute('SELECT 1')
        print('✅ Database connection with new structure successful!')
        
        # Test models import
        from app_models import User, VideoProcess, VideoClip
        print('✅ Models import successful!')
        
except ImportError as e:
    print(f'❌ Import error: {e}')
    print('⚠️  Make sure app_models.py exists and is properly formatted')
except Exception as e:
    print(f'❌ Database connection error: {e}')
\""

# Initialize database dengan struktur baru
echo "🗄️ Initializing database with new structure..."
sudo -u ${APP_USER} bash -c "cd ${APP_DIR} && source venv/bin/activate && python3 -c \"
import os
os.environ['DB_PASSWORD'] = '${DB_PASSWORD}'

try:
    from app import app
    from app_models import db
    
    with app.app_context():
        # Create all tables
        db.create_all()
        print('✅ Database tables created successfully!')
        
        # Create admin user
        from app_models import User
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
            print(f'✅ Admin user created: {admin_email}')
        else:
            admin.is_admin = True
            admin.is_premium = True
            admin.credits = 999999
            db.session.commit()
            print(f'✅ Admin user updated: {admin_email}')
            
except Exception as e:
    print(f'❌ Database initialization error: {e}')
    import traceback
    traceback.print_exc()
\""

# Setup systemd services
echo "⚙️ Setting up systemd services..."

# Main application service
sudo tee /etc/systemd/system/askaraai.service > /dev/null << EOL
[Unit]
Description=AskaraAI Flask Application
After=network.target mysql.service redis.service

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
Environment="PATH=${APP_DIR}/venv/bin"
ExecStart=${APP_DIR}/venv/bin/gunicorn --workers 4 --bind unix:${APP_DIR}/askaraai.sock -m 007 app:app --timeout 300
Restart=always
RestartSec=3
KillMode=mixed
KillSignal=SIGINT
TimeoutStopSec=5

[Install]
WantedBy=multi-user.target
EOL

# Celery worker service
sudo tee /etc/systemd/system/askaraai-celery.service > /dev/null << EOL
[Unit]
Description=AskaraAI Celery Worker
After=network.target mysql.service redis.service

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
Environment="PATH=${APP_DIR}/venv/bin"
ExecStart=${APP_DIR}/venv/bin/celery -A celery_app.celery worker --loglevel=info --concurrency=2
Restart=always
RestartSec=3
KillMode=mixed
KillSignal=SIGTERM
TimeoutStopSec=10

[Install]
WantedBy=multi-user.target
EOL

# Celery beat service
sudo tee /etc/systemd/system/askaraai-celery-beat.service > /dev/null << EOL
[Unit]
Description=AskaraAI Celery Beat Scheduler
After=network.target mysql.service redis.service

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
Environment="PATH=${APP_DIR}/venv/bin"
ExecStart=${APP_DIR}/venv/bin/celery -A celery_app.celery beat --loglevel=info
Restart=always
RestartSec=3
KillMode=mixed
KillSignal=SIGTERM
TimeoutStopSec=5

[Install]
WantedBy=multi-user.target
EOL

# Set permissions yang benar
sudo chown -R ${APP_USER}:${APP_USER} ${APP_DIR}
sudo chmod +x ${APP_DIR}/venv/bin/*

# Enable dan start services
echo "🚀 Starting services..."
sudo systemctl daemon-reload

# Start dependencies first
sudo systemctl enable redis-server mysql nginx
sudo systemctl start redis-server mysql nginx

# Start application services
sudo systemctl enable askaraai.service askaraai-celery.service askaraai-celery-beat.service
sudo systemctl start askaraai.service askaraai-celery.service askaraai-celery-beat.service

# Wait a bit for services to start
sleep 5

# Check service status
echo "🔍 Checking service status..."
echo "Database Status:"
sudo systemctl is-active mysql || echo "❌ MySQL not running"
echo "Redis Status:"
sudo systemctl is-active redis-server || echo "❌ Redis not running"
echo "Nginx Status:"
sudo systemctl is-active nginx || echo "❌ Nginx not running"
echo "AskaraAI Status:"
sudo systemctl is-active askaraai.service || echo "❌ AskaraAI not running"
echo "Celery Worker Status:"
sudo systemctl is-active askaraai-celery.service || echo "❌ Celery Worker not running"
echo "Celery Beat Status:"
sudo systemctl is-active askaraai-celery-beat.service || echo "❌ Celery Beat not running"

# Test basic functionality
echo "🧪 Testing basic functionality..."
sudo -u ${APP_USER} bash -c "cd ${APP_DIR} && source venv/bin/activate && python3 -c \"
try:
    # Test imports
    from app import app
    from app_models import db, User
    from app_extensions import register_extensions
    
    print('✅ All imports successful')
    
    # Test app context
    with app.app_context():
        user_count = User.query.count()
        print(f'✅ Database query successful: {user_count} users')
        
except Exception as e:
    print(f'❌ Functionality test failed: {e}')
    import traceback
    traceback.print_exc()
\""

# Setup backup cron job
echo "💾 Setting up backup cron job..."
(crontab -l 2>/dev/null; echo "0 2 */26 * * cd ${APP_DIR} && ${APP_DIR}/venv/bin/python3 backup_database.py") | sudo -u ${APP_USER} crontab -

# Cleanup temporary files
rm -f /tmp/db_password.txt

echo ""
echo "✅ Setup AskaraAI dengan struktur baru selesai!"
echo ""
echo "📋 Informasi Penting:"
echo "   Database Password: $DB_PASSWORD"
echo "   Database Name: $DB_NAME"
echo "   Database User: $DB_USER"
echo ""
echo "📁 Struktur File Baru:"
echo "   app_models.py      - Database models (BARU)"
echo "   app.py             - Main application (UPDATED)"
echo "   app_extensions.py  - Extensions blueprint (UPDATED)"
echo "   celery_app.py      - Celery tasks (UPDATED)"
echo ""
echo "🔧 Langkah selanjutnya:"
echo "1. Edit file .env (${APP_DIR}/.env) dan isi API keys:"
echo "   - GEMINI_API_KEY (wajib untuk AI processing)"
echo "   - GOOGLE_CLIENT_ID & GOOGLE_CLIENT_SECRET (untuk OAuth)"
echo "   - SMTP credentials (untuk email notifications)"
echo ""
echo "2. Pastikan file app_models.py ada dan berisi semua models"
echo ""
echo "3. Setup Google Drive backup (opsional):"
echo "   sudo rclone config"
echo ""
echo "4. Setup SSL certificate:"
echo "   sudo apt install certbot python3-certbot-nginx"
echo "   sudo certbot --nginx -d askaraai.com"
echo ""
echo "🌐 Aplikasi berjalan di:"
echo "   HTTP: http://askaraai.com (atau IP server Anda)"
echo "   Setelah SSL: https://askaraai.com"
echo ""
echo "📊 Monitor aplikasi:"
echo "   Status: sudo systemctl status askaraai"
echo "   Logs: sudo journalctl -u askaraai -f"
echo "   Celery: sudo journalctl -u askaraai-celery -f"
echo ""
echo "🧪 Test aplikasi:"
echo "   curl http://localhost:5000/health"
echo "   curl http://localhost:5000/api/config/google-client-id"
echo ""
echo "💡 Tips troubleshooting:"
echo "   - Jika ada import error, pastikan app_models.py ada"
echo "   - Jika database error, cek DB_PASSWORD di .env"
echo "   - Test imports: source venv/bin/activate && python3 -c 'from app_models import db'"
echo "   - Restart services: sudo systemctl restart askaraai askaraai-celery"
echo ""
echo "🎉 Struktur baru dengan app_models.py sudah siap untuk production!"
echo ""