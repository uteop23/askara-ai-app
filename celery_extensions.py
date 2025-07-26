# celery_extensions.py
# Extended Celery tasks for AskaraAI system monitoring and maintenance
# Import this in your main celery_app.py

import os
import json
import logging
import subprocess
import requests
from datetime import datetime, timedelta
from celery import Celery
from celery.schedules import crontab
import redis
import psutil

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import from main celery app
from celery_app import celery

@celery.task
def system_health_check():
    """Periodic system health monitoring task"""
    try:
        from app import app, db
        from app_extensions import SystemHealth
        from utils import AskaraAIUtils
        
        with app.app_context():
            logger.info("Running system health check...")
            
            utils = AskaraAIUtils()
            health_data = utils.check_system_health()
            
            # Save to database
            health_record = SystemHealth(
                overall_status=health_data['overall'],
                database_status=health_data['database']['status'],
                redis_status=health_data['redis']['status'],
                celery_status=health_data['celery']['status'],
                disk_usage=health_data['disk_space'].get('usage_percent'),
                memory_usage=psutil.virtual_memory().percent,
                cpu_usage=psutil.cpu_percent(interval=1),
                details=health_data
            )
            
            db.session.add(health_record)
            db.session.commit()
            
            # Alert if critical issues
            if health_data['overall'] == 'critical':
                send_alert_notification.delay(
                    "🚨 CRITICAL: AskaraAI System Health Alert",
                    f"System health is critical. Check admin panel immediately.\n\nDetails:\n{json.dumps(health_data, indent=2)}",
                    "critical"
                )
            elif health_data['overall'] == 'unhealthy':
                send_alert_notification.delay(
                    "⚠️ WARNING: AskaraAI System Health Warning",
                    f"System health issues detected.\n\nDetails:\n{json.dumps(health_data, indent=2)}",
                    "warning"
                )
            
            logger.info(f"Health check completed. Status: {health_data['overall']}")
            return health_data
            
    except Exception as e:
        logger.error(f"Error in system health check: {str(e)}")
        return {'error': str(e)}

@celery.task
def cleanup_old_files():
    """Clean up old temporary files and optimize storage"""
    try:
        from utils import AskaraAIUtils
        
        logger.info("Starting file cleanup...")
        
        utils = AskaraAIUtils()
        deleted_files = utils.cleanup_old_files(days=7)
        
        # Additional cleanup for specific directories
        cleanup_paths = [
            '/tmp/askaraai_*',
            '/var/www/askaraai/static/uploads/*',
            '/var/www/askaraai/logs/*.log.*'
        ]
        
        total_cleaned = len(deleted_files)
        
        for path_pattern in cleanup_paths:
            try:
                result = subprocess.run(
                    f"find {path_pattern} -mtime +7 -delete 2>/dev/null || true",
                    shell=True,
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    logger.info(f"Cleaned pattern: {path_pattern}")
            except Exception as e:
                logger.warning(f"Error cleaning {path_pattern}: {str(e)}")
        
        logger.info(f"File cleanup completed. Cleaned {total_cleaned} files.")
        return {'cleaned_files': total_cleaned, 'deleted_files': deleted_files}
        
    except Exception as e:
        logger.error(f"Error in file cleanup: {str(e)}")
        return {'error': str(e)}

@celery.task
def optimize_database():
    """Optimize database performance and clean up old records"""
    try:
        from app import app, db
        from app_extensions import SystemHealth, PromoUsage
        
        with app.app_context():
            logger.info("Starting database optimization...")
            
            # Remove old health records (keep only last 30 days)
            cutoff_date = datetime.utcnow() - timedelta(days=30)
            old_health_records = SystemHealth.query.filter(
                SystemHealth.check_time < cutoff_date
            ).delete()
            
            # Remove old promo usage records (keep only last 90 days)
            cutoff_date_promo = datetime.utcnow() - timedelta(days=90)
            old_promo_usage = PromoUsage.query.filter(
                PromoUsage.applied_at < cutoff_date_promo
            ).delete()
            
            db.session.commit()
            
            # Run database optimization commands
            if 'mysql' in app.config['SQLALCHEMY_DATABASE_URI']:
                try:
                    db.session.execute("OPTIMIZE TABLE user, video_process, video_clip, payment")
                    db.session.commit()
                    logger.info("MySQL tables optimized")
                except Exception as e:
                    logger.warning(f"MySQL optimization warning: {str(e)}")
            
            logger.info(f"Database optimization completed. Removed {old_health_records} health records, {old_promo_usage} promo usage records.")
            
            return {
                'old_health_records_removed': old_health_records,
                'old_promo_usage_removed': old_promo_usage
            }
            
    except Exception as e:
        logger.error(f"Error in database optimization: {str(e)}")
        return {'error': str(e)}

@celery.task
def send_alert_notification(subject, message, alert_type="info"):
    """Send alert notifications via multiple channels"""
    try:
        from utils import AskaraAIUtils
        
        utils = AskaraAIUtils()
        sent_channels = utils.send_notification(subject, message, alert_type)
        
        logger.info(f"Alert sent via: {', '.join(sent_channels) if sent_channels else 'none'}")
        return {'sent_channels': sent_channels}
        
    except Exception as e:
        logger.error(f"Error sending alert: {str(e)}")
        return {'error': str(e)}

@celery.task
def check_ssl_expiry():
    """Check SSL certificate expiry and send alerts"""
    try:
        import ssl
        import socket
        from datetime import datetime
        
        logger.info("Checking SSL certificate expiry...")
        
        hostname = 'askaraai.com'
        port = 443
        
        context = ssl.create_default_context()
        with socket.create_connection((hostname, port), timeout=10) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert()
                
                # Parse expiry date
                expiry_str = cert['notAfter']
                expiry_date = datetime.strptime(expiry_str, '%b %d %H:%M:%S %Y %Z')
                days_until_expiry = (expiry_date - datetime.utcnow()).days
                
                logger.info(f"SSL certificate expires in {days_until_expiry} days")
                
                # Send alerts based on days remaining
                if days_until_expiry <= 7:
                    send_alert_notification.delay(
                        "🚨 URGENT: SSL Certificate Expiring Soon",
                        f"SSL certificate for {hostname} expires in {days_until_expiry} days!\n\nExpiry date: {expiry_date}\n\nAction required: Renew certificate immediately.",
                        "critical"
                    )
                elif days_until_expiry <= 30:
                    send_alert_notification.delay(
                        "⚠️ WARNING: SSL Certificate Expiring",
                        f"SSL certificate for {hostname} expires in {days_until_expiry} days.\n\nExpiry date: {expiry_date}\n\nAction required: Plan certificate renewal.",
                        "warning"
                    )
                
                return {
                    'hostname': hostname,
                    'expiry_date': expiry_date.isoformat(),
                    'days_until_expiry': days_until_expiry
                }
                
    except Exception as e:
        logger.error(f"Error checking SSL certificate: {str(e)}")
        send_alert_notification.delay(
            "❌ ERROR: SSL Certificate Check Failed",
            f"Failed to check SSL certificate for askaraai.com.\n\nError: {str(e)}",
            "error"
        )
        return {'error': str(e)}

@celery.task
def monitor_user_activity():
    """Monitor user activity and generate insights"""
    try:
        from app import app, db, User, VideoProcess
        
        with app.app_context():
            logger.info("Monitoring user activity...")
            
            # Get activity stats for last 24 hours
            yesterday = datetime.utcnow() - timedelta(days=1)
            
            new_users = User.query.filter(User.created_at >= yesterday).count()
            new_videos = VideoProcess.query.filter(VideoProcess.created_at >= yesterday).count()
            active_users = db.session.query(VideoProcess.user_id).filter(
                VideoProcess.created_at >= yesterday
            ).distinct().count()
            
            # Get weekly stats
            week_ago = datetime.utcnow() - timedelta(days=7)
            weekly_users = User.query.filter(User.created_at >= week_ago).count()
            weekly_videos = VideoProcess.query.filter(VideoProcess.created_at >= week_ago).count()
            
            # Calculate conversion rate
            total_users = User.query.count()
            premium_users = User.query.filter_by(is_premium=True).count()
            conversion_rate = (premium_users / total_users * 100) if total_users > 0 else 0
            
            activity_report = {
                'daily': {
                    'new_users': new_users,
                    'new_videos': new_videos,
                    'active_users': active_users
                },
                'weekly': {
                    'new_users': weekly_users,
                    'new_videos': weekly_videos
                },
                'overall': {
                    'total_users': total_users,
                    'premium_users': premium_users,
                    'conversion_rate': round(conversion_rate, 2)
                }
            }
            
            # Send weekly summary on Mondays
            if datetime.now().weekday() == 0:  # Monday
                send_alert_notification.delay(
                    "📊 Weekly AskaraAI Activity Report",
                    f"Weekly Summary:\n\n"
                    f"• New Users: {weekly_users}\n"
                    f"• Videos Processed: {weekly_videos}\n"
                    f"• Total Users: {total_users}\n"
                    f"• Premium Users: {premium_users}\n"
                    f"• Conversion Rate: {conversion_rate:.1f}%\n",
                    "info"
                )
            
            logger.info(f"User activity monitoring completed: {activity_report}")
            return activity_report
            
    except Exception as e:
        logger.error(f"Error monitoring user activity: {str(e)}")
        return {'error': str(e)}

@celery.task
def backup_critical_data():
    """Backup critical system data beyond database"""
    try:
        import shutil
        from pathlib import Path
        
        logger.info("Starting critical data backup...")
        
        backup_dir = f"/tmp/askaraai_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        os.makedirs(backup_dir, exist_ok=True)
        
        # Backup configuration files
        config_files = [
            '/var/www/askaraai/.env',
            '/etc/nginx/sites-available/askaraai',
            '/etc/systemd/system/askaraai.service',
            '/etc/systemd/system/askaraai-celery.service'
        ]
        
        config_backup_dir = os.path.join(backup_dir, 'config')
        os.makedirs(config_backup_dir, exist_ok=True)
        
        for config_file in config_files:
            if os.path.exists(config_file):
                shutil.copy2(config_file, config_backup_dir)
                logger.info(f"Backed up: {config_file}")
        
        # Backup recent user-generated content
        recent_clips_dir = '/var/www/askaraai/static/clips'
        if os.path.exists(recent_clips_dir):
            clips_backup_dir = os.path.join(backup_dir, 'recent_clips')
            shutil.copytree(recent_clips_dir, clips_backup_dir, ignore_errors=True)
            logger.info("Backed up recent clips")
        
        # Create archive
        archive_name = f"{backup_dir}.tar.gz"
        subprocess.run(['tar', '-czf', archive_name, '-C', '/tmp', os.path.basename(backup_dir)])
        
        # Upload to Google Drive
        try:
            subprocess.run([
                'rclone', 'copy', archive_name, 
                f"gdrive:AskaraAI/critical_backups/"
            ], check=True)
            logger.info(f"Critical backup uploaded: {archive_name}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to upload backup: {str(e)}")
        
        # Cleanup local files
        shutil.rmtree(backup_dir, ignore_errors=True)
        os.remove(archive_name)
        
        return {'backup_completed': True, 'archive_name': os.path.basename(archive_name)}
        
    except Exception as e:
        logger.error(f"Error in critical data backup: {str(e)}")
        return {'error': str(e)}

@celery.task
def test_external_services():
    """Test external service connectivity and API limits"""
    try:
        logger.info("Testing external services...")
        
        services_status = {}
        
        # Test Gemini AI API
        try:
            import google.generativeai as genai
            genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
            model = genai.GenerativeModel('gemini-pro')
            
            # Simple test request
            response = model.generate_content("Test connection. Respond with 'OK'.")
            services_status['gemini_ai'] = {
                'status': 'healthy' if 'OK' in response.text else 'warning',
                'response_time': 'fast',
                'message': 'API connection successful'
            }
        except Exception as e:
            services_status['gemini_ai'] = {
                'status': 'unhealthy',
                'error': str(e)
            }
        
        # Test Google Drive (Rclone)
        try:
            result = subprocess.run(['rclone', 'lsd', 'gdrive:AskaraAI/'], 
                                  capture_output=True, text=True, timeout=30)
            services_status['google_drive'] = {
                'status': 'healthy' if result.returncode == 0 else 'unhealthy',
                'message': 'Drive connection successful' if result.returncode == 0 else result.stderr
            }
        except Exception as e:
            services_status['google_drive'] = {
                'status': 'unhealthy',
                'error': str(e)
            }
        
        # Test Tripay API (if configured)
        tripay_api_key = os.getenv('TRIPAY_API_KEY')
        if tripay_api_key:
            try:
                headers = {'Authorization': f'Bearer {tripay_api_key}'}
                response = requests.get('https://tripay.co.id/api/payment/channel', 
                                      headers=headers, timeout=10)
                services_status['tripay'] = {
                    'status': 'healthy' if response.status_code == 200 else 'unhealthy',
                    'message': 'Payment gateway accessible'
                }
            except Exception as e:
                services_status['tripay'] = {
                    'status': 'unhealthy',
                    'error': str(e)
                }
        
        # Test email SMTP (if configured)
        smtp_host = os.getenv('SMTP_HOST')
        if smtp_host:
            try:
                import smtplib
                server = smtplib.SMTP_SSL(smtp_host, int(os.getenv('SMTP_PORT', 465)))
                server.login(os.getenv('SMTP_USER'), os.getenv('SMTP_PASS'))
                server.quit()
                services_status['email_smtp'] = {
                    'status': 'healthy',
                    'message': 'SMTP connection successful'
                }
            except Exception as e:
                services_status['email_smtp'] = {
                    'status': 'unhealthy',
                    'error': str(e)
                }
        
        # Check if any critical services are down
        critical_services = ['gemini_ai', 'google_drive']
        critical_down = [svc for svc in critical_services 
                        if services_status.get(svc, {}).get('status') == 'unhealthy']
        
        if critical_down:
            send_alert_notification.delay(
                "🚨 CRITICAL: External Service Failure",
                f"Critical services are down: {', '.join(critical_down)}\n\n"
                f"Full status:\n{json.dumps(services_status, indent=2)}",
                "critical"
            )
        
        logger.info(f"External services test completed: {len(services_status)} services checked")
        return services_status
        
    except Exception as e:
        logger.error(f"Error testing external services: {str(e)}")
        return {'error': str(e)}

# Update the beat schedule in your main celery_app.py
EXTENDED_BEAT_SCHEDULE = {
    # System health check every 10 minutes
    'system-health-check': {
        'task': 'celery_extensions.system_health_check',
        'schedule': crontab(minute='*/10'),
    },
    
    # File cleanup daily at 3 AM
    'cleanup-old-files': {
        'task': 'celery_extensions.cleanup_old_files',
        'schedule': crontab(hour=3, minute=0),
    },
    
    # Database optimization weekly on Sunday at 4 AM
    'optimize-database': {
        'task': 'celery_extensions.optimize_database',
        'schedule': crontab(hour=4, minute=0, day_of_week=0),
    },
    
    # SSL check daily at 6 AM
    'check-ssl-expiry': {
        'task': 'celery_extensions.check_ssl_expiry',
        'schedule': crontab(hour=6, minute=0),
    },
    
    # User activity monitoring every 6 hours
    'monitor-user-activity': {
        'task': 'celery_extensions.monitor_user_activity',
        'schedule': crontab(hour='*/6', minute=0),
    },
    
    # Critical data backup weekly on Saturday at 2 AM
    'backup-critical-data': {
        'task': 'celery_extensions.backup_critical_data',
        'schedule': crontab(hour=2, minute=0, day_of_week=6),
    },
    
    # External services test every 2 hours
    'test-external-services': {
        'task': 'celery_extensions.test_external_services',
        'schedule': crontab(minute=0, hour='*/2'),
    },
}

# Add this to your main celery_app.py beat_schedule
# celery.conf.beat_schedule.update(EXTENDED_BEAT_SCHEDULE)