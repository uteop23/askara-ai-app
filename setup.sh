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
PYTHON_CMD=""
for py_ver in python3.11 python3.10 python3.9 python3.8 python3; do
    if command -v $py_ver &> /dev/null; then
        if $py_ver -c "import sys; exit(0 if sys.version_info >= (3,8) and sys.version_info < (3,12) else 1)" 2>/dev/null; then
            PYTHON_CMD=$py_ver
            break
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo "❌ FATAL: Python 3.8-3.11 tidak ditemukan. MoviePy memerlukan Python 3.8-3.11."
    exit 1
fi

echo "✅ Menggunakan Python: $PYTHON_CMD ($($PYTHON_CMD --version))"

# Create log file
touch $LOG_FILE
exec &> >(tee -a $LOG_FILE)

echo "📋 Setup started at $(date)"
echo "📂 Logs saved to: $LOG_FILE"

# --- Functions ---
log_info() { echo "ℹ️  [INFO] $1"; }
log_error() { echo "❌ [ERROR] $1"; }
log_success() { echo "✅ [SUCCESS] $1"; }

# --- Main Script ---

log_info "Memeriksa prasyarat..."
if [[ $EUID -ne 0 ]]; then log_error "Skrip ini harus dijalankan sebagai root (gunakan sudo)"; exit 1; fi
if ! command -v apt &> /dev/null; then log_error "Skrip ini memerlukan Ubuntu/Debian dengan apt"; exit 1; fi
log_success "Prasyarat terpenuhi."

log_info "Memperbarui sistem..."
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get upgrade -y
log_success "Sistem telah diperbarui."

log_info "Menginstall dependencies utama..."
apt-get install -y \
    $PYTHON_CMD \
    $PYTHON_CMD-venv \
    $PYTHON_CMD-dev \
    build-essential \
    nginx \
    redis-server \
    mysql-server \
    git \
    curl \
    ffmpeg \
    fail2ban \
    ufw
log_success "Dependencies utama terinstall."

log_info "Mengkonfigurasi Redis..."
systemctl start redis-server
systemctl enable redis-server
if redis-cli ping | grep -q PONG; then
    log_success "Redis berjalan dengan baik."
else
    log_error "Konfigurasi Redis gagal."
    exit 1
fi

log_info "Menyiapkan direktori dan environment aplikasi..."
mkdir -p ${APP_DIR}
chown -R ${APP_USER}:${APP_USER} ${APP_DIR}
cd ${APP_DIR}

sudo -u ${APP_USER} $PYTHON_CMD -m venv venv
log_success "Virtual environment dibuat di ${APP_DIR}/venv."

log_info "Membuat file requirements.txt yang stabil..."
sudo -u ${APP_USER} tee requirements.txt > /dev/null < <(curl -s https://gist.githubusercontent.com/assistant-gemini/21b920409a3e20e8b15e47a956972412/raw/e87a2bd5451c3c9c6141a02798e16d44a2df46b1/askara_requirements.txt)
log_success "File requirements.txt dibuat."

log_info "Menginstall package Python (ini bisa memakan waktu 5-15 menit)..."
sudo -u ${APP_USER} bash -c "source ${APP_DIR}/venv/bin/activate && pip install --upgrade pip && pip install -r ${APP_DIR}/requirements.txt"
log_success "Semua package Python berhasil diinstall."

log_info "Memverifikasi instalasi MoviePy..."
sudo -u ${APP_USER} bash -c "source ${APP_DIR}/venv/bin/activate && python -c 'import moviepy.editor as mp; print(\"MoviePy OK\")'"
log_success "MoviePy terverifikasi."

log_info "Membuat struktur direktori..."
sudo -u ${APP_USER} mkdir -p static/clips static/uploads logs templates backup
log_success "Struktur direktori dibuat."

log_info "Mengkonfigurasi Firewall (UFW)..."
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
log_success "Firewall aktif."

log_info "Mengkonfigurasi Nginx..."
tee /etc/nginx/sites-available/askaraai > /dev/null << EOL
server {
    listen 80;
    server_name _; # Ganti dengan domain Anda nanti
    client_max_body_size 500M;

    location / {
        proxy_pass http://unix:${APP_DIR}/askaraai.sock;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
    }
    location /static {
        alias ${APP_DIR}/static;
    }
}
EOL
ln -sf /etc/nginx/sites-available/askaraai /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl restart nginx
log_success "Nginx telah dikonfigurasi."

log_info "Membuat service systemd untuk aplikasi..."
tee /etc/systemd/system/askaraai.service > /dev/null << EOL
[Unit]
Description=AskaraAI Flask Application
After=network.target

[Service]
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
Environment="PATH=${APP_DIR}/venv/bin"
ExecStart=${APP_DIR}/venv/bin/gunicorn --workers 4 --bind unix:askaraai.sock app:app

Restart=always

[Install]
WantedBy=multi-user.target
EOL
systemctl daemon-reload
systemctl enable askaraai
log_success "Service systemd 'askaraai.service' dibuat."

echo " "
echo "=================================================================="
echo "✅ Instalasi Dasar Selesai! Sekarang ikuti langkah manual ini:"
echo "=================================================================="
echo " "
echo "1. AMANKAN & BUAT DATABASE MYSQL:"
echo "   - Jalankan: sudo mysql_secure_installation"
echo "   - Login ke MySQL: sudo mysql -u root -p"
echo "   - Jalankan perintah SQL berikut:"
echo "     CREATE DATABASE ${DB_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
echo "     CREATE USER '${DB_USER}'@'localhost' IDENTIFIED BY 'PASSWORD_BARU_ANDA';"
echo "     GRANT ALL PRIVILEGES ON ${DB_NAME}.* TO '${DB_USER}'@'localhost';"
echo "     FLUSH PRIVILEGES;"
echo "     EXIT;"
echo " "
echo "2. SALIN SEMUA FILE APLIKASI ANDA:"
echo "   - Pastikan semua file .py, .html, .sh, dll, ada di dalam ${APP_DIR}/"
echo "   - Contoh: sudo cp /path/to/your/files/* ${APP_DIR}/"
echo "   - Atur kepemilikan: sudo chown -R ${APP_USER}:${APP_USER} ${APP_DIR}"
echo " "
echo "3. BUAT DAN ISI FILE .env:"
echo "   - Buat file: sudo nano ${APP_DIR}/.env"
echo "   - Salin konten dari file .env.example Anda dan isi semua nilainya (DB_PASSWORD, API Keys, dll)."
echo "   - Atur kepemilikan: sudo chown ${APP_USER}:${APP_USER} ${APP_DIR}/.env && sudo chmod 600 ${APP_DIR}/.env"
echo " "
echo "4. INISIALISASI DATABASE APLIKASI:"
echo "   - cd ${APP_DIR}"
echo "   - sudo -u ${APP_USER} bash -c \"source venv/bin/activate && flask init-db\""
echo " "
echo "5. JALANKAN SEMUA SERVICE LENGKAP:"
echo "   (Salin semua file .service dan .timer Anda ke /etc/systemd/system/ terlebih dahulu)"
echo "   - sudo systemctl daemon-reload"
echo "   - sudo systemctl restart askaraai askaraai-celery askaraai-celery-beat"
echo "   - sudo systemctl enable askaraai askaraai-celery askaraai-celery-beat"
echo " "
echo "6. KONFIGURASI DOMAIN & SSL (HTTPS):"
echo "   - Arahkan domain Anda ke IP server ini."
echo "   - Edit file Nginx: sudo nano /etc/nginx/sites-available/askaraai (ganti 'server_name _;' dengan 'server_name domainanda.com www.domainanda.com;')"
echo "   - Install Certbot: sudo apt install certbot python3-certbot-nginx -y"
echo "   - Jalankan Certbot: sudo certbot --nginx -d domainanda.com -d www.domainanda.com"
echo " "
echo "🎉 Setup selesai. Silakan lanjutkan dengan langkah manual di atas."
