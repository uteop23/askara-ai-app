#!/usr/bin/env python3
"""
AskaraAI Utility Scripts & Helper Functions
Collection of utility functions for maintenance, monitoring, and administration
"""

import os
import sys
import json
import logging
import subprocess
import requests
from datetime import datetime, timedelta
from pathlib import Path
import mysql.connector
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
        self.redis_client = redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379/0'))
        
    def check_system_health(self):
        """Check overall system health"""
        health_status = {
            'timestamp': datetime.now().isoformat(),
            'database': self._check_database(),
            'redis': self._check_redis(),
            'disk_space': self._check_disk_space(),
            'nginx': self._check_nginx(),
            'celery': self._check_celery(),
            'ssl_certificate': self._check_ssl_certificate()
        }
        
        overall_status = all(health_status[key]['status'] == 'healthy' for key in health_status if key != 'timestamp')
        health_status['overall'] = 'healthy' if overall_status else 'unhealthy'
        
        return health_status
    
    def _check_database(self):
        """Check MySQL database connectivity"""
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM user")
            user_count = cursor.fetchone()[0]
            cursor.close()
            conn.close()
            
            return {
                'status': 'healthy',
                'user_count': user_count,
                'message': 'Database connection successful'
            }
        except Exception as e:
            return {
                'status': 'unhealthy',
                'error': str(e),
                'message': 'Database connection failed'
            }
    
    def _check_redis(self):
        """Check Redis connectivity"""
        try:
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
            result = subprocess.run(['df', '-h', '/'], capture_output=True, text=True)
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
    
    def _check_nginx(self):
        """Check Nginx status"""
        try:
            result = subprocess.run(['systemctl', 'is-active', 'nginx'], capture_output=True, text=True)
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
            result = subprocess.run(['systemctl', 'is-active', 'askaraai-celery'], capture_output=True, text=True)
            active = result.stdout.strip() == 'active'
            
            # Try to get worker stats
            worker_stats = {}
            try:
                from celery_app import celery
                inspect = celery.control.inspect()
                stats = inspect.stats()
                if stats:
                    worker_stats = {'workers': len(stats)}
            except:
                pass
            
            return {
                'status': 'healthy' if active else 'unhealthy',
                'active': active,
                'worker_stats': worker_stats,
                'message': 'Celery is active' if active else 'Celery is not active'
            }
        except Exception as e:
            return {
                'status': 'unhealthy',
                'error': str(e),
                'message': 'Failed to check Celery status'
            }
    
    def _check_ssl_certificate(self):
        """Check SSL certificate expiration"""
        try:
            result = subprocess.run([
                'openssl', 's_client', '-servername', 'askaraai.com',
                '-connect', 'askaraai.com:443', '-showcerts'
            ], input='', capture_output=True, text=True, timeout=10)
            
            # Parse certificate expiration
            cert_info = subprocess.run([
                'openssl', 'x509', '-noout', '-enddate'
            ], input=result.stdout, capture_output=True, text=True)
            
            if cert_info.stdout:
                exp_date_str = cert_info.stdout.replace('notAfter=', '').strip()
                exp_date = datetime.strptime(exp_date_str, '%b %d %H:%M:%S %Y %Z')
                days_until_expiry = (exp_date - datetime.now()).days
                
                status = 'healthy' if days_until_expiry > 30 else 'warning' if days_until_expiry > 7 else 'critical'
                
                return {
                    'status': status,
                    'expiry_date': exp_date.isoformat(),
                    'days_until_expiry': days_until_expiry,
                    'message': f'SSL certificate expires in {days_until_expiry} days'
                }
            
            return {
                'status': 'unknown',
                'message': 'Could not parse SSL certificate'
            }
        except Exception as e:
            return {
                'status': 'unhealthy',
                'error': str(e),
                'message': 'Failed to check SSL certificate'
            }
    
    def cleanup_old_files(self, days=7):
        """Clean up old temporary files and clips"""
        try:
            clips_dir = Path('/var/www/askaraai/static/clips')
            uploads_dir = Path('/var/www/askaraai/static/uploads')
            logs_dir = Path('/var/www/askaraai/logs')
            
            cutoff_date = datetime.now() - timedelta(days=days)
            deleted_files = []
            
            # Clean up old clips (older than specified days)
            for clip_file in clips_dir.glob('*.mp4'):
                if datetime.fromtimestamp(clip_file.stat().st_mtime) < cutoff_date:
                    clip_file.unlink()
                    deleted_files.append(str(clip_file))
            
            # Clean up uploads directory
            for upload_file in uploads_dir.glob('*'):
                if datetime.fromtimestamp(upload_file.stat().st_mtime) < cutoff_date:
                    upload_file.unlink()
                    deleted_files.append(str(upload_file))
            
            # Clean up old log files (keep only recent ones)
            for log_file in logs_dir.glob('*.log.*'):
                if datetime.fromtimestamp(log_file.stat().st_mtime) < cutoff_date:
                    log_file.unlink()
                    deleted_files.append(str(log_file))
            
            logger.info(f"Cleaned up {len(deleted_files)} old files")
            return deleted_files
            
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")
            return []
    
    def get_system_stats(self):
        """Get comprehensive system statistics"""
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            
            # User statistics
            cursor.execute("SELECT COUNT(*) FROM user")
            total_users = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM user WHERE is_premium = 1")
            premium_users = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM user WHERE created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)")
            new_users_30d = cursor.fetchone()[0]
            
            # Video processing statistics
            cursor.execute("SELECT COUNT(*) FROM video_process")
            total_videos = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM video_process WHERE status = 'completed'")
            completed_videos = cursor.fetchone()[0]
            
            cursor.execute("SELECT SUM(clips_generated) FROM video_process")
            total_clips = cursor.fetchone()[0] or 0
            
            # Recent activity
            cursor.execute("""
                SELECT DATE(created_at) as date, COUNT(*) as count 
                FROM video_process 
                WHERE created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
                GROUP BY DATE(created_at)
                ORDER BY date
            """)
            recent_activity = cursor.fetchall()
            
            cursor.close()
            conn.close()
            
            return {
                'users': {
                    'total': total_users,
                    'premium': premium_users,
                    'new_30d': new_users_30d,
                    'conversion_rate': (premium_users / total_users * 100) if total_users > 0 else 0
                },
                'videos': {
                    'total': total_videos,
                    'completed': completed_videos,
                    'success_rate': (completed_videos / total_videos * 100) if total_videos > 0 else 0
                },
                'clips': {
                    'total': total_clips,
                    'average_per_video': (total_clips / completed_videos) if completed_videos > 0 else 0
                },
                'recent_activity': [{'date': str(date), 'count': count} for date, count in recent_activity]
            }
            
        except Exception as e:
            logger.error(f"Error getting system stats: {str(e)}")
            return {}
    
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

def main():
    """Main function for command-line usage"""
    if len(sys.argv) < 2:
        print("Usage: python utils.py <command>")
        print("Commands:")
        print("  health - Check system health")
        print("  stats - Get system statistics")
        print("  cleanup - Clean up old files")
        print("  notify <message> - Send test notification")
        return
    
    utils = AskaraAIUtils()
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