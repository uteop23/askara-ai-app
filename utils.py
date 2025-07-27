#!/usr/bin/env python3
"""
AskaraAI Utility Scripts & Helper Functions - FIXED VERSION
Collection of utility functions for maintenance, monitoring, and administration
Tanpa dependency Google Drive/rclone
"""

import os
import sys
import json
import logging
import subprocess
import requests
from datetime import datetime, timedelta
from pathlib import Path
import redis
from dotenv import load_dotenv
import smtplib
from email.mime.text import MimeText
from email.mime.multipart import MimeMultipart

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class AskaraAIUtils:
    def __init__(self):
        self.db_password = os.getenv('DB_PASSWORD')
        if not self.db_password:
            raise ValueError("DB_PASSWORD environment variable not set.")

        self.db_config = {
            'host': 'localhost',
            'user': 'askaraai',
            'password': self.db_password,
            'database': 'askaraai_db'
        }
        
        try:
            self.redis_client = redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379/0'))
            self.redis_client.ping()
        except Exception as e:
            logger.warning(f"Redis connection failed: {str(e)}")
            self.redis_client = None
        
    def check_system_health(self):
        """Check overall system health"""
        health_status = {
            'timestamp': datetime.now().isoformat(),
            'database': self._check_database(),
            'redis': self._check_redis(),
            'disk_space': self._check_disk_space(),
            'nginx': self._check_nginx(),
            'celery': self._check_celery(),
            'ssl_certificate': self._check_ssl_certificate(),
            'memory_usage': self._check_memory_usage()
        }
        
        # Determine overall status
        critical_services = ['database', 'nginx']
        overall_healthy = True
        
        for service in critical_services:
            if health_status[service]['status'] not in ['healthy', 'warning']:
                overall_healthy = False
                break
        
        health_status['overall'] = 'healthy' if overall_healthy else 'unhealthy'
        
        return health_status
    
    def _check_database(self):
        """Check MySQL database connectivity"""
        try:
            # Try using PyMySQL first
            try:
                import pymysql
                conn = pymysql.connect(**self.db_config)
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = %s", (self.db_config['database'],))
                table_count = cursor.fetchone()[0]
                cursor.close()
                conn.close()
                
                return {
                    'status': 'healthy',
                    'table_count': table_count,
                    'message': 'Database connection successful (PyMySQL)'
                }
            except ImportError:
                # Fallback to mysql.connector
                try:
                    import mysql.connector
                    conn = mysql.connector.connect(**self.db_config)
                    cursor = conn.cursor()
                    cursor.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = %s", (self.db_config['database'],))
                    table_count = cursor.fetchone()[0]
                    cursor.close()
                    conn.close()
                    
                    return {
                        'status': 'healthy',
                        'table_count': table_count,
                        'message': 'Database connection successful (mysql.connector)'
                    }
                except ImportError:
                    # Final fallback using subprocess
                    result = subprocess.run([
                        'mysql', '-h', self.db_config['host'], 
                        '-u', self.db_config['user'], 
                        f"-p{self.db_config['password']}", 
                        '-e', 'SELECT 1;'
                    ], capture_output=True, text=True, timeout=10)
                    
                    if result.returncode == 0:
                        return {
                            'status': 'healthy',
                            'message': 'Database connection successful (mysql cli)'
                        }
                    else:
                        raise Exception(f"MySQL CLI error: {result.stderr}")
                        
        except Exception as e:
            return {
                'status': 'unhealthy',
                'error': str(e),
                'message': 'Database connection failed'
            }
    
    def _check_redis(self):
        """Check Redis connectivity"""
        try:
            if not self.redis_client:
                return {
                    'status': 'unhealthy',
                    'error': 'Redis client not initialized',
                    'message': 'Redis connection failed'
                }
                
            self.redis_client.ping()
            info = self.redis_client.info()
            
            return {
                'status': 'healthy',
                'memory_usage': info.get('used_memory_human'),
                'connected_clients': info.get('connected_clients'),
                'message': 'Redis connection successful'
            }
        except Exception as e:
            return {
                'status': 'unhealthy',
                'error': str(e),
                'message': 'Redis connection failed'
            }
    
    def _check_disk_space(self):
        """Check disk space usage"""
        try:
            result = subprocess.run(['df', '-h', '/'], capture_output=True, text=True, timeout=10)
            lines = result.stdout.strip().split('\n')
            if len(lines) >= 2:
                parts = lines[1].split()
                if len(parts) >= 5:
                    usage_percent = int(parts[4].replace('%', ''))
                    
                    status = 'healthy' if usage_percent < 80 else 'warning' if usage_percent < 90 else 'critical'
                    
                    return {
                        'status': status,
                        'usage_percent': usage_percent,
                        'available': parts[3],
                        'total': parts[1],
                        'message': f'Disk usage: {usage_percent}%'
                    }
            
            return {
                'status': 'unknown',
                'message': 'Could not parse disk usage'
            }
        except Exception as e:
            return {
                'status': 'unhealthy',
                'error': str(e),
                'message': 'Failed to check disk space'
            }
    
    def _check_memory_usage(self):
        """Check memory usage"""
        try:
            with open('/proc/meminfo', 'r') as f:
                meminfo = f.read()
            
            mem_total = 0
            mem_available = 0
            for line in meminfo.split('\n'):
                if line.startswith('MemTotal:'):
                    mem_total = int(line.split()[1]) * 1024
                elif line.startswith('MemAvailable:'):
                    mem_available = int(line.split()[1]) * 1024
            
            if mem_total > 0:
                usage_percent = ((mem_total - mem_available) / mem_total * 100)
                status = 'healthy' if usage_percent < 80 else 'warning' if usage_percent < 90 else 'critical'
                
                return {
                    'status': status,
                    'usage_percent': round(usage_percent, 2),
                    'total_mb': round(mem_total / 1024 / 1024, 2),
                    'available_mb': round(mem_available / 1024 / 1024, 2),
                    'message': f'Memory usage: {usage_percent:.1f}%'
                }
            
            return {
                'status': 'unknown',
                'message': 'Could not parse memory usage'
            }
        except Exception as e:
            return {
                'status': 'unhealthy',
                'error': str(e),
                'message': 'Failed to check memory usage'
            }
    
    def _check_nginx(self):
        """Check Nginx status"""
        try:
            result = subprocess.run(['systemctl', 'is-active', 'nginx'], capture_output=True, text=True, timeout=10)
            active = result.stdout.strip() == 'active'
            
            return {
                'status': 'healthy' if active else 'unhealthy',
                'active': active,
                'message': 'Nginx is active' if active else 'Nginx is not active'
            }
        except Exception as e:
            return {
                'status': 'unhealthy',
                'error': str(e),
                'message': 'Failed to check Nginx status'
            }
    
    def _check_celery(self):
        """Check Celery worker status"""
        try:
            # Check if Celery service is running
            result = subprocess.run(['systemctl', 'is-active', 'askaraai-celery'], capture_output=True, text=True, timeout=10)
            active = result.stdout.strip() == 'active'
            
            # If service doesn't exist, check if process is running
            if not active:
                result = subprocess.run(['pgrep', '-f', 'celery.*worker'], capture_output=True, text=True, timeout=10)
                active = bool(result.stdout.strip())
            
            return {
                'status': 'healthy' if active else 'warning',
                'active': active,
                'message': 'Celery is active' if active else 'Celery is not active'
            }
        except Exception as e:
            return {
                'status': 'warning',
                'error': str(e),
                'message': 'Failed to check Celery status (service may not be configured yet)'
            }
    
    def _check_ssl_certificate(self):
        """Check SSL certificate expiration"""
        try:
            # Check if using Let's Encrypt certificate
            cert_path = '/etc/letsencrypt/live/askaraai.com/fullchain.pem'
            if os.path.exists(cert_path):
                try:
                    result = subprocess.run([
                        'openssl', 'x509', '-in', cert_path, '-noout', '-enddate'
                    ], capture_output=True, text=True, timeout=10)
                    
                    if result.returncode == 0 and result.stdout:
                        exp_date_str = result.stdout.replace('notAfter=', '').strip()
                        try:
                            exp_date = datetime.strptime(exp_date_str, '%b %d %H:%M:%S %Y %Z')
                            days_until_expiry = (exp_date - datetime.now()).days
                            
                            status = 'healthy' if days_until_expiry > 30 else 'warning' if days_until_expiry > 7 else 'critical'
                            
                            return {
                                'status': status,
                                'expiry_date': exp_date.isoformat(),
                                'days_until_expiry': days_until_expiry,
                                'message': f'SSL certificate expires in {days_until_expiry} days'
                            }
                        except:
                            pass
                except Exception:
                    pass
            
            # Check if using self-signed certificate
            try:
                cert_result = subprocess.run([
                    'openssl', 'x509', '-in', '/etc/ssl/certs/ssl-cert-snakeoil.pem',
                    '-noout', '-enddate'
                ], capture_output=True, text=True, timeout=10)
                
                if cert_result.returncode == 0:
                    return {
                        'status': 'warning',
                        'message': 'Using self-signed certificate. Consider setting up Let\'s Encrypt.'
                    }
            except:
                pass
            
            return {
                'status': 'warning',
                'message': 'SSL certificate check failed. May not be configured yet.'
            }
            
        except Exception as e:
            return {
                'status': 'warning',
                'error': str(e),
                'message': 'SSL certificate check failed'
            }
    
    def cleanup_old_files(self, days=7):
        """Clean up old temporary files and clips"""
        try:
            clips_dir = Path('/var/www/askaraai/static/clips')
            uploads_dir = Path('/var/www/askaraai/static/uploads')
            logs_dir = Path('/var/www/askaraai/logs')
            
            cutoff_date = datetime.now() - timedelta(days=days)
            deleted_files = []
            
            # Clean up old clips
            if clips_dir.exists():
                for clip_file in clips_dir.glob('*.mp4'):
                    try:
                        if datetime.fromtimestamp(clip_file.stat().st_mtime) < cutoff_date:
                            clip_file.unlink()
                            deleted_files.append(str(clip_file))
                    except Exception as e:
                        logger.warning(f"Failed to delete clip file {clip_file}: {str(e)}")
            
            # Clean up uploads directory
            if uploads_dir.exists():
                for upload_file in uploads_dir.glob('*'):
                    try:
                        if datetime.fromtimestamp(upload_file.stat().st_mtime) < cutoff_date:
                            upload_file.unlink()
                            deleted_files.append(str(upload_file))
                    except Exception as e:
                        logger.warning(f"Failed to delete upload file {upload_file}: {str(e)}")
            
            # Clean up old log files
            if logs_dir.exists():
                for log_file in logs_dir.glob('*.log.*'):
                    try:
                        if datetime.fromtimestamp(log_file.stat().st_mtime) < cutoff_date:
                            log_file.unlink()
                            deleted_files.append(str(log_file))
                    except Exception as e:
                        logger.warning(f"Failed to delete log file {log_file}: {str(e)}")
            
            # Clean up temporary directories
            temp_dirs = ['/tmp/askaraai_*']
            for temp_pattern in temp_dirs:
                try:
                    subprocess.run(f"find /tmp -name 'askaraai_*' -type d -mtime +{days} -exec rm -rf {{}} + 2>/dev/null || true", 
                                 shell=True, timeout=30)
                except Exception as e:
                    logger.warning(f"Failed to clean temp directories: {str(e)}")
            
            logger.info(f"Cleaned up {len(deleted_files)} old files")
            return deleted_files
            
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")
            return []
    
    def get_system_stats(self):
        """Get comprehensive system statistics"""
        try:
            stats = self._get_database_stats()
            stats.update(self._get_system_performance_stats())
            return stats
            
        except Exception as e:
            logger.error(f"Error getting system stats: {str(e)}")
            return {
                'error': str(e),
                'users': {'total': 0, 'premium': 0, 'new_30d': 0, 'conversion_rate': 0},
                'videos': {'total': 0, 'completed': 0, 'success_rate': 0},
                'clips': {'total': 0, 'average_per_video': 0},
                'recent_activity': []
            }
    
    def _get_database_stats(self):
        """Get statistics from database"""
        try:
            conn = None
            cursor = None
            
            try:
                import pymysql
                conn = pymysql.connect(**self.db_config)
                cursor = conn.cursor()
            except ImportError:
                try:
                    import mysql.connector
                    conn = mysql.connector.connect(**self.db_config)
                    cursor = conn.cursor()
                except ImportError:
                    return {
                        'users': {'total': 0, 'premium': 0, 'new_30d': 0, 'conversion_rate': 0},
                        'videos': {'total': 0, 'completed': 0, 'success_rate': 0},
                        'clips': {'total': 0, 'average_per_video': 0},
                        'recent_activity': [],
                        'note': 'Database statistics unavailable - no database driver found'
                    }
            
            stats = {}
            
            # Check if tables exist first
            cursor.execute("SHOW TABLES LIKE 'users'")
            if not cursor.fetchone():
                return {
                    'users': {'total': 0, 'premium': 0, 'new_30d': 0, 'conversion_rate': 0},
                    'videos': {'total': 0, 'completed': 0, 'success_rate': 0},
                    'clips': {'total': 0, 'average_per_video': 0},
                    'recent_activity': [],
                    'note': 'Database tables not found - run database initialization'
                }
            
            # User statistics
            try:
                cursor.execute("SELECT COUNT(*) FROM users")
                total_users = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM users WHERE is_premium = 1")
                premium_users = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM users WHERE created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)")
                new_users_30d = cursor.fetchone()[0]
                
                stats['users'] = {
                    'total': total_users,
                    'premium': premium_users,
                    'new_30d': new_users_30d,
                    'conversion_rate': (premium_users / total_users * 100) if total_users > 0 else 0
                }
            except Exception as e:
                logger.warning(f"Failed to get user stats: {str(e)}")
                stats['users'] = {'total': 0, 'premium': 0, 'new_30d': 0, 'conversion_rate': 0}
            
            # Video processing statistics
            try:
                cursor.execute("SELECT COUNT(*) FROM video_processes")
                total_videos = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM video_processes WHERE status = 'completed'")
                completed_videos = cursor.fetchone()[0]
                
                cursor.execute("SELECT COALESCE(SUM(clips_generated), 0) FROM video_processes")
                total_clips = cursor.fetchone()[0] or 0
                
                stats['videos'] = {
                    'total': total_videos,
                    'completed': completed_videos,
                    'success_rate': (completed_videos / total_videos * 100) if total_videos > 0 else 0
                }
                
                stats['clips'] = {
                    'total': total_clips,
                    'average_per_video': (total_clips / completed_videos) if completed_videos > 0 else 0
                }
            except Exception as e:
                logger.warning(f"Failed to get video stats: {str(e)}")
                stats['videos'] = {'total': 0, 'completed': 0, 'success_rate': 0}
                stats['clips'] = {'total': 0, 'average_per_video': 0}
            
            # Recent activity
            try:
                cursor.execute("""
                    SELECT DATE(created_at) as date, COUNT(*) as count 
                    FROM video_processes 
                    WHERE created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
                    GROUP BY DATE(created_at)
                    ORDER BY date
                """)
                recent_activity = cursor.fetchall()
                stats['recent_activity'] = [{'date': str(date), 'count': count} for date, count in recent_activity]
            except Exception as e:
                logger.warning(f"Failed to get recent activity: {str(e)}")
                stats['recent_activity'] = []
            
            cursor.close()
            conn.close()
            
            return stats
            
        except Exception as e:
            logger.error(f"Database stats error: {str(e)}")
            return {
                'users': {'total': 0, 'premium': 0, 'new_30d': 0, 'conversion_rate': 0},
                'videos': {'total': 0, 'completed': 0, 'success_rate': 0},
                'clips': {'total': 0, 'average_per_video': 0},
                'recent_activity': [],
                'error': str(e)
            }
    
    def _get_system_performance_stats(self):
        """Get system performance statistics"""
        try:
            # Get system load
            load_avg = os.getloadavg()
            
            # Get memory info
            try:
                with open('/proc/meminfo', 'r') as f:
                    meminfo = f.read()
                
                mem_total = 0
                mem_available = 0
                for line in meminfo.split('\n'):
                    if line.startswith('MemTotal:'):
                        mem_total = int(line.split()[1]) * 1024
                    elif line.startswith('MemAvailable:'):
                        mem_available = int(line.split()[1]) * 1024
                
                memory_usage = ((mem_total - mem_available) / mem_total * 100) if mem_total > 0 else 0
                
            except Exception:
                memory_usage = 0
            
            return {
                'system_performance': {
                    'load_average': {
                        '1min': load_avg[0],
                        '5min': load_avg[1],
                        '15min': load_avg[2]
                    },
                    'memory_usage_percent': round(memory_usage, 2)
                }
            }
            
        except Exception as e:
            logger.warning(f"Failed to get performance stats: {str(e)}")
            return {
                'system_performance': {
                    'load_average': {'1min': 0, '5min': 0, '15min': 0},
                    'memory_usage_percent': 0
                }
            }
    
    def send_notification(self, subject, message, notification_type='info'):
        """Send notification via email/Slack/Discord"""
        notifications_sent = []
        
        # Email notification
        if self._send_email_notification(subject, message):
            notifications_sent.append('email')
        
        # Slack notification
        if self._send_slack_notification(message, notification_type):
            notifications_sent.append('slack')
        
        # Discord notification
        if self._send_discord_notification(message, notification_type):
            notifications_sent.append('discord')
        
        return notifications_sent
    
    def _send_email_notification(self, subject, message):
        """Send email notification"""
        try:
            smtp_host = os.getenv('SMTP_HOST')
            smtp_port = int(os.getenv('SMTP_PORT', 465))
            smtp_user = os.getenv('SMTP_USER')
            smtp_pass = os.getenv('SMTP_PASS')
            admin_email = os.getenv('ADMIN_EMAIL', 'ujangbawbaw@gmail.com')
            
            if not all([smtp_host, smtp_user, smtp_pass]):
                return False
            
            msg = MimeMultipart()
            msg['From'] = smtp_user
            msg['To'] = admin_email
            msg['Subject'] = f"[AskaraAI] {subject}"
            
            msg.attach(MimeText(message, 'plain'))
            
            server = smtplib.SMTP_SSL(smtp_host, smtp_port)
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
            server.quit()
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email notification: {str(e)}")
            return False
    
    def _send_slack_notification(self, message, notification_type):
        """Send Slack notification"""
        try:
            webhook_url = os.getenv('SLACK_WEBHOOK_URL')
            if not webhook_url:
                return False
            
            color_map = {
                'info': '#36a64f',
                'warning': '#ffbb33',
                'error': '#ff0000',
                'success': '#36a64f'
            }
            
            payload = {
                'attachments': [{
                    'color': color_map.get(notification_type, '#36a64f'),
                    'title': 'AskaraAI System Notification',
                    'text': message,
                    'footer': 'AskaraAI Monitoring',
                    'ts': int(datetime.now().timestamp())
                }]
            }
            
            response = requests.post(webhook_url, json=payload, timeout=10)
            return response.status_code == 200
            
        except Exception as e:
            logger.error(f"Failed to send Slack notification: {str(e)}")
            return False
    
    def _send_discord_notification(self, message, notification_type):
        """Send Discord notification"""
        try:
            webhook_url = os.getenv('DISCORD_WEBHOOK_URL')
            if not webhook_url:
                return False
            
            color_map = {
                'info': 0x3498db,
                'warning': 0xf39c12,
                'error': 0xe74c3c,
                'success': 0x2ecc71
            }
            
            payload = {
                'embeds': [{
                    'title': 'AskaraAI System Notification',
                    'description': message,
                    'color': color_map.get(notification_type, 0x3498db),
                    'footer': {
                        'text': 'AskaraAI Monitoring'
                    },
                    'timestamp': datetime.now().isoformat()
                }]
            }
            
            response = requests.post(webhook_url, json=payload, timeout=10)
            return response.status_code == 204
            
        except Exception as e:
            logger.error(f"Failed to send Discord notification: {str(e)}")
            return False

    def run_local_backup(self):
        """Run local database backup"""
        try:
            import sys
            sys.path.append('/var/www/askaraai')
            from backup_database import LocalDatabaseBackup
            
            backup_manager = LocalDatabaseBackup()
            success = backup_manager.run_backup()
            
            return {
                'success': success,
                'message': 'Local backup completed' if success else 'Local backup failed'
            }
            
        except Exception as e:
            logger.error(f"Failed to run local backup: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }

def main():
    """Main function for command-line usage"""
    if len(sys.argv) < 2:
        print("Usage: python utils.py <command>")
        print("Commands:")
        print("  health - Check system health")
        print("  stats - Get system statistics")
        print("  cleanup - Clean up old files")
        print("  backup - Run local database backup")
        print("  notify <message> - Send test notification")
        return
    
    try:
        utils = AskaraAIUtils()
    except Exception as e:
        print(f"Error initializing utils: {str(e)}")
        return
    
    command = sys.argv[1]
    
    if command == 'health':
        health = utils.check_system_health()
        print(json.dumps(health, indent=2))
    
    elif command == 'stats':
        stats = utils.get_system_stats()
        print(json.dumps(stats, indent=2))
    
    elif command == 'cleanup':
        deleted_files = utils.cleanup_old_files()
        print(f"Cleaned up {len(deleted_files)} files")
        for file in deleted_files:
            print(f"  - {file}")
    
    elif command == 'backup':
        result = utils.run_local_backup()
        if result['success']:
            print(f"✅ {result['message']}")
        else:
            print(f"❌ {result.get('message', 'Backup failed')}")
            if 'error' in result:
                print(f"Error: {result['error']}")
    
    elif command == 'notify':
        if len(sys.argv) < 3:
            print("Usage: python utils.py notify <message>")
            return
        
        message = ' '.join(sys.argv[2:])
        sent = utils.send_notification("Test Notification", message)
        print(f"Notification sent via: {', '.join(sent) if sent else 'none'}")
    
    else:
        print(f"Unknown command: {command}")

if __name__ == "__main__":
    main()
