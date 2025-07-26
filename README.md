# AskaraAI - AI Video Clipper

![AskaraAI Logo](https://askaraai.com/static/logo.png)

AskaraAI adalah platform AI generatif yang mengubah video panjang menjadi klip-klip pendek viral dengan teknologi Gemini AI dari Google. Platform ini dirancang untuk kreator konten, marketer, dan agensi digital yang ingin mengoptimalkan waktu produksi konten.

## 🚀 Fitur Utama

### 🎯 AI Viral Finder™
- Analisis otomatis untuk menemukan momen paling menarik dalam video
- Scoring viral berdasarkan potensi engagement
- Rekomendasi klip terbaik untuk di-posting

### 🎥 AI Speaker Tracking
- Deteksi pembicara otomatis
- Framing dinamis untuk menjaga pembicara di tengah frame
- Optimasi format vertikal (9:16) untuk media sosial

### 📱 Content Repurposing Hub
- Klip video vertikal siap posting
- Artikel blog SEO-optimized
- Caption carousel untuk media sosial
- Multiple format dari satu video

## 🛠️ Teknologi Stack

- **Backend**: Python Flask + Celery
- **Database**: MySQL
- **Cache**: Redis
- **AI Engine**: Google Gemini Pro 1.5
- **Video Processing**: FFmpeg + MoviePy
- **Cloud Storage**: Google Drive (via Rclone)
- **Payment**: Tripay Gateway
- **Authentication**: Google OAuth
- **Deployment**: Nginx + Gunicorn
- **Server**: VPS Contabo (3vCPU, 8GB RAM, 150GB SSD)

## 📋 Prerequisites

- Ubuntu 20.04+ atau Debian 11+
- Python 3.8+
- MySQL 8.0+
- Redis 6.0+
- FFmpeg 4.0+
- Nginx 1.18+
- Node.js 18+ (untuk frontend tools)

## 🚀 Quick Start

### 1. Clone Repository

```bash
git clone https://github.com/uteop23/askara-ai-app.git
cd askara-ai-app
```

### 2. Auto Setup (Recommended)

```bash
chmod +x setup.sh
sudo ./setup.sh
```

Script ini akan:
- Install semua dependencies
- Setup database MySQL
- Konfigurasi Nginx
- Setup systemd services
- Konfigurasi firewall dan security

### 3. Manual Setup

Jika ingin setup manual, ikuti langkah berikut:

#### Install Dependencies

```bash
# Update sistem
sudo apt update && sudo apt upgrade -y

# Install Python dan tools
sudo apt install -y python3 python3-pip python3-venv

# Install database dan cache
sudo apt install -y mysql-server redis-server

# Install web server
sudo apt install -y nginx

# Install video processing
sudo apt install -y ffmpeg

# Install security tools
sudo apt install -y ufw fail2ban
```

#### Setup Database

```bash
# Login ke MySQL
sudo mysql

# Buat database dan user
CREATE DATABASE askaraai_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'askaraai'@'localhost' IDENTIFIED BY 'AskAra2025!Strong';
GRANT ALL PRIVILEGES ON askaraai_db.* TO 'askaraai'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

#### Setup Python Environment

```bash
# Buat virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

#### Setup Environment Variables

Buat file `.env`:

```bash
cp .env.example .env
```

Edit `.env` dengan konfigurasi Anda:

```env
# Flask Configuration
SECRET_KEY=your-secret-key-here
FLASK_ENV=production
FLASK_DEBUG=False

# Database Configuration
DATABASE_URL=mysql+pymysql://askaraai:AskAra2025!Strong@localhost/askaraai_db

# Redis Configuration
REDIS_URL=redis://localhost:6379/0

# Gemini AI Configuration
GEMINI_API_KEY=your-gemini-api-key-here

# Google OAuth Configuration
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret

# SMTP Configuration
SMTP_HOST=smtp.hostinger.com
SMTP_PORT=465
SMTP_USER=support@askaraai.com
SMTP_PASS=your-smtp-password

# Tripay Configuration
TRIPAY_API_KEY=your-tripay-api-key
TRIPAY_PRIVATE_KEY=your-tripay-private-key
TRIPAY_MERCHANT_CODE=your-tripay-merchant-code
```

#### Initialize Database

```bash
python3 -c "
from app import create_app, db
app = create_app()
with app.app_context():
    db.create_all()
    print('Database initialized!')
"
```

## 🔧 Konfigurasi

### Google AI Studio Setup

1. Buka [Google AI Studio](https://makersuite.google.com/)
2. Buat project baru
3. Generate API key untuk Gemini
4. Masukkan API key ke file `.env`

### Google OAuth Setup

1. Buka [Google Cloud Console](https://console.cloud.google.com/)
2. Buat project atau pilih yang sudah ada
3. Enable Google+ API
4. Buat OAuth 2.0 credentials
5. Tambahkan domain `askaraai.com` ke authorized domains
6. Masukkan Client ID dan Secret ke `.env`

### Tripay Setup

1. Daftar di [Tripay](https://tripay.co.id/)
2. Dapatkan API key, Private key, dan Merchant code
3. Setup webhook URL: `https://askaraai.com/api/tripay-callback`
4. Masukkan credentials ke `.env`

### Rclone Google Drive Setup

```bash
# Install rclone
curl https://rclone.org/install.sh | sudo bash

# Konfigurasi Google Drive
rclone config
# Pilih Google Drive, ikuti instruksi authorization
```

## 🚀 Deployment

### Start Services

```bash
# Start aplikasi utama
sudo systemctl start askaraai

# Start Celery worker
sudo systemctl start askaraai-celery

# Start Celery beat (scheduler)
sudo systemctl start askaraai-celery-beat

# Start Redis dan MySQL
sudo systemctl start redis-server mysql

# Start Nginx
sudo systemctl start nginx
```

### Enable Auto-start

```bash
sudo systemctl enable askaraai askaraai-celery askaraai-celery-beat redis-server mysql nginx
```

### SSL Certificate (Let's Encrypt)

```bash
# Install Certbot
sudo apt install certbot python3-certbot-nginx

# Generate SSL certificate
sudo certbot --nginx -d askaraai.com

# Auto-renewal
sudo crontab -e
# Tambahkan: 0 12 * * * /usr/bin/certbot renew --quiet
```

## 📊 Monitoring

### Check Service Status

```bash
# App status
sudo systemctl status askaraai

# Celery worker status
sudo systemctl status askaraai-celery

# View logs
sudo journalctl -u askaraai -f
sudo journalctl -u askaraai-celery -f
```

### Monitor Celery Tasks

```bash
# Install Flower (optional)
pip install flower

# Start Flower monitoring
celery -A celery_app.celery flower --port=5555

# Access via: http://localhost:5555
```

### Database Backup

Backup otomatis sudah dikonfigurasi untuk berjalan setiap 26 hari. Manual backup:

```bash
python3 backup_database.py
```

## 🔒 Security

### Firewall Configuration

```bash
# Basic firewall setup
sudo ufw allow ssh
sudo ufw allow 80
sudo ufw allow 443
sudo ufw enable
```

### Fail2Ban Configuration

Fail2ban sudah dikonfigurasi untuk melindungi dari brute force attack.

### Rate Limiting

- API endpoints dibatasi 10 request/menit
- Video streaming dibatasi 1 video per 5 menit per IP
- Login attempts dibatasi 5 percobaan per menit

## 📁 Struktur Project

```
askara-ai-app/
├── app.py                 # Main Flask application
├── celery_app.py          # Celery configuration & tasks
├── backup_database.py     # Database backup script
├── requirements.txt       # Python dependencies
├── setup.sh              # Auto setup script
├── .env                  # Environment variables
├── templates/
│   ├── index.html        # Landing page
│   └── admin.html        # Admin dashboard
├── static/
│   ├── clips/           # Generated video clips
│   ├── uploads/         # Temporary uploads
│   └── assets/          # CSS, JS, images
└── logs/                # Application logs
```

## 🎯 API Endpoints

### Public API

```bash
# Process video
POST /api/process-video
{
  "url": "https://youtube.com/watch?v=..."
}

# Check task status
GET /api/task-status/{task_id}

# Authentication
POST /api/auth/google
POST /api/logout
GET /api/get-session
```

### Admin API

```bash
# Admin endpoints (requires admin auth)
GET /admin                    # Admin dashboard
POST /api/admin/update-pricing
GET /api/admin/export-data
```

## 🧪 Testing

### Test Video Processing

```bash
# Test dengan video YouTube pendek
curl -X POST https://askaraai.com/api/process-video \
  -H "Content-Type: application/json" \
  -d '{"url": "https://youtube.com/watch?v=dQw4w9WgXcQ"}'
```

### Test Authentication

1. Buka https://askaraai.com
2. Klik "Masuk" dan login dengan Google
3. Coba proses video

## 📞 Support

- **Email**: official@askaraai.com
- **GitHub Issues**: [Create Issue](https://github.com/uteop23/askara-ai-app/issues)
- **Documentation**: [Wiki](https://github.com/uteop23/askara-ai-app/wiki)

## 🔄 Updates & Maintenance

### Update Aplikasi

```bash
# Pull latest changes
git pull origin main

# Update dependencies
pip install -r requirements.txt

# Restart services
sudo systemctl restart askaraai askaraai-celery
```

### Database Migration

```bash
# Jika ada perubahan schema database
python3 -c "
from app import create_app, db
app = create_app()
with app.app_context():
    db.create_all()
"
```

## 🎉 Production Checklist

- [ ] ✅ SSL Certificate installed
- [ ] ✅ Firewall configured
- [ ] ✅ Fail2Ban active
- [ ] ✅ Database backup scheduled
- [ ] ✅ Monitoring setup
- [ ] ✅ Rate limiting enabled
- [ ] ✅ Error logging configured
- [ ] ✅ Environment variables secured
- [ ] ✅ Admin account created
- [ ] ✅ Payment gateway tested

## 📜 License

Copyright © 2025 AskaraAI. All rights reserved.

---

**AskaraAI** - Mengubah video panjang menjadi klip viral dengan kekuatan AI ✨