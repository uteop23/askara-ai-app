#!/usr/bin/env python3
"""
AskaraAI Local Database Backup Script - FIXED VERSION
Local backup only (tanpa Google Drive/rclone dependency)
"""

import os
import subprocess
import logging
import shutil
from datetime import datetime, timedelta
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables
load_dotenv()

# Configure logging
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
        self.backup_dir = os.getenv('BACKUP_DIR', '/var/www/askaraai/backup')
        self.retention_days = int(os.getenv('BACKUP_RETENTION_DAYS', '30'))

        if not self.db_password:
            logger.critical("FATAL: DB_PASSWORD environment variable not set!")
            raise ValueError("DB_PASSWORD not found in environment variables")

        # Ensure backup directory exists
        os.makedirs(self.backup_dir, exist_ok=True)
        logger.info(f"Backup directory: {self.backup_dir}")
        
    def create_backup_filename(self):
        """Generate backup filename with timestamp"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        return f"askaraai_backup_{timestamp}.sql"
    
    def create_mysql_dump(self, backup_path):
        """Create MySQL database dump"""
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
                '--events',
                '--hex-blob',
                '--add-drop-database',
                '--databases',
                self.db_name
            ]
            
            with open(backup_path, 'w') as f:
                result = subprocess.run(
                    cmd, 
                    stdout=f, 
                    stderr=subprocess.PIPE,
                    check=True,
                    text=True,
                    timeout=600  # 10 minutes timeout
                )
            
            # Verify backup file
            if os.path.exists(backup_path) and os.path.getsize(backup_path) > 0:
                file_size_mb = os.path.getsize(backup_path) / 1024 / 1024
                logger.info(f"MySQL dump created successfully: {backup_path} ({file_size_mb:.2f}MB)")
                return True
            else:
                logger.error("MySQL dump file is empty or not created")
                return False
                
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.decode() if e.stderr else str(e)
            logger.error(f"MySQL dump failed: {error_msg}")
            return False
        except subprocess.TimeoutExpired:
            logger.error("MySQL dump timed out after 10 minutes")
            return False
        except Exception as e:
            logger.error(f"Error creating MySQL dump: {str(e)}")
            return False
    
    def create_compressed_backup(self, backup_path):
        """Create compressed backup to save space"""
        try:
            compressed_path = backup_path + '.gz'
            logger.info(f"Compressing backup: {compressed_path}")
            
            with open(backup_path, 'rb') as f_in:
                with open(compressed_path, 'wb') as f_out:
                    subprocess.run(['gzip', '-c'], stdin=f_in, stdout=f_out, check=True)
            
            # Remove uncompressed file
            os.remove(backup_path)
            
            if os.path.exists(compressed_path):
                file_size_mb = os.path.getsize(compressed_path) / 1024 / 1024
                logger.info(f"Backup compressed successfully: {compressed_path} ({file_size_mb:.2f}MB)")
                return compressed_path
            else:
                logger.error("Compressed backup file not created")
                return None
                
        except Exception as e:
            logger.error(f"Error compressing backup: {str(e)}")
            return None
    
    def cleanup_old_backups(self):
        """Remove old backups based on retention policy"""
        try:
            logger.info(f"Cleaning up backups older than {self.retention_days} days...")
            
            cutoff_time = datetime.now() - timedelta(days=self.retention_days)
            deleted_count = 0
            total_size_deleted = 0
            
            backup_files = []
            
            # Collect all backup files
            for filename in os.listdir(self.backup_dir):
                if filename.startswith('askaraai_backup_') and (filename.endswith('.sql') or filename.endswith('.sql.gz')):
                    filepath = os.path.join(self.backup_dir, filename)
                    file_mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
                    file_size = os.path.getsize(filepath)
                    
                    backup_files.append({
                        'path': filepath,
                        'name': filename,
                        'mtime': file_mtime,
                        'size': file_size
                    })
            
            # Sort by modification time (newest first)
            backup_files.sort(key=lambda x: x['mtime'], reverse=True)
            
            # Keep the most recent backups and delete old ones
            for i, backup_file in enumerate(backup_files):
                # Always keep at least 3 most recent backups
                if i < 3:
                    continue
                
                # Delete if older than retention period
                if backup_file['mtime'] < cutoff_time:
                    try:
                        os.remove(backup_file['path'])
                        deleted_count += 1
                        total_size_deleted += backup_file['size']
                        logger.info(f"Deleted old backup: {backup_file['name']}")
                    except Exception as e:
                        logger.warning(f"Failed to delete {backup_file['name']}: {str(e)}")
            
            if deleted_count > 0:
                size_mb = total_size_deleted / 1024 / 1024
                logger.info(f"Cleanup completed. Deleted {deleted_count} old backups ({size_mb:.2f}MB freed)")
            else:
                logger.info("No old backups to clean up")
                
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")
    
    def backup_application_files(self, backup_filename):
        """Backup critical application files"""
        try:
            logger.info("Backing up critical application files...")
            
            app_backup_dir = os.path.join(self.backup_dir, 'app_files')
            os.makedirs(app_backup_dir, exist_ok=True)
            
            # List of critical files to backup
            critical_files = [
                '/var/www/askaraai/.env',
                '/var/www/askaraai/app.py',
                '/var/www/askaraai/app_models.py',
                '/var/www/askaraai/requirements.txt',
                '/etc/nginx/sites-available/askaraai',
                '/etc/systemd/system/askaraai.service'
            ]
            
            backed_up_files = []
            
            for file_path in critical_files:
                if os.path.exists(file_path):
                    try:
                        # Create backup filename
                        file_name = os.path.basename(file_path)
                        backup_file_path = os.path.join(app_backup_dir, f"{backup_filename}_{file_name}")
                        
                        # Copy file
                        shutil.copy2(file_path, backup_file_path)
                        backed_up_files.append(file_name)
                        
                    except Exception as e:
                        logger.warning(f"Failed to backup {file_path}: {str(e)}")
            
            if backed_up_files:
                logger.info(f"Application files backed up: {', '.join(backed_up_files)}")
            
        except Exception as e:
            logger.error(f"Error backing up application files: {str(e)}")
    
    def get_backup_statistics(self):
        """Get backup statistics"""
        try:
            backup_files = []
            total_size = 0
            
            for filename in os.listdir(self.backup_dir):
                if filename.startswith('askaraai_backup_') and (filename.endswith('.sql') or filename.endswith('.sql.gz')):
                    filepath = os.path.join(self.backup_dir, filename)
                    file_size = os.path.getsize(filepath)
                    file_mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
                    
                    backup_files.append({
                        'name': filename,
                        'size': file_size,
                        'date': file_mtime
                    })
                    total_size += file_size
            
            backup_files.sort(key=lambda x: x['date'], reverse=True)
            
            return {
                'total_backups': len(backup_files),
                'total_size_mb': total_size / 1024 / 1024,
                'latest_backup': backup_files[0] if backup_files else None,
                'backup_files': backup_files[:5]  # Return latest 5
            }
            
        except Exception as e:
            logger.error(f"Error getting backup statistics: {str(e)}")
            return {'error': str(e)}
    
    def send_backup_notification(self, success, backup_filename, error_msg=None, stats=None):
        """Send backup notification"""
        try:
            if success:
                message = f"✅ AskaraAI Database backup completed successfully"
                if stats:
                    message += f"\n📊 Statistics:"
                    message += f"\n   • Backup file: {backup_filename}"
                    message += f"\n   • Total backups: {stats.get('total_backups', 0)}"
                    message += f"\n   • Total size: {stats.get('total_size_mb', 0):.2f}MB"
                
                logger.info(message)
            else:
                message = f"❌ AskaraAI Database backup failed"
                if error_msg:
                    message += f"\n   Error: {error_msg}"
                logger.error(message)
            
            # TODO: Integrate with email/Slack notification if needed
            # You can add notification integration here
            
        except Exception as e:
            logger.error(f"Error sending notification: {str(e)}")
    
    def run_backup(self):
        """Main backup process"""
        logger.info("=== Starting AskaraAI Local Database Backup ===")
        
        backup_filename = self.create_backup_filename()
        backup_path = os.path.join(self.backup_dir, backup_filename)
        
        try:
            # Step 1: Create MySQL dump
            if not self.create_mysql_dump(backup_path):
                self.send_backup_notification(False, backup_filename, "MySQL dump failed")
                return False
            
            # Step 2: Compress backup
            compressed_path = self.create_compressed_backup(backup_path)
            if compressed_path:
                backup_filename = os.path.basename(compressed_path)
            
            # Step 3: Backup application files
            self.backup_application_files(backup_filename.replace('.sql.gz', '').replace('.sql', ''))
            
            # Step 4: Cleanup old backups
            self.cleanup_old_backups()
            
            # Step 5: Get statistics
            stats = self.get_backup_statistics()
            
            # Step 6: Send success notification
            self.send_backup_notification(True, backup_filename, stats=stats)
            
            logger.info("=== Local Database Backup Completed Successfully ===")
            return True
            
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            logger.error(error_msg)
            self.send_backup_notification(False, backup_filename, error_msg)
            
            # Cleanup failed backup file
            if os.path.exists(backup_path):
                try:
                    os.remove(backup_path)
                except:
                    pass
                    
            return False

def check_prerequisites():
    """Check if required tools are available"""
    required_tools = ['mysqldump', 'gzip']
    
    for tool in required_tools:
        try:
            subprocess.run([tool, '--version'], capture_output=True, check=True, timeout=10)
            logger.info(f"✓ {tool} is available")
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            logger.error(f"✗ {tool} is not available")
            return False
    
    return True

def main():
    """Main function for command line usage"""
    # Ensure logs directory exists
    os.makedirs('/var/www/askaraai/logs', exist_ok=True)
    
    logger.info("AskaraAI Local Database Backup Script Started")
    
    # Check prerequisites
    if not check_prerequisites():
        logger.error("Prerequisites check failed. Backup aborted.")
        return False
    
    try:
        # Run backup
        backup_manager = LocalDatabaseBackup()
        success = backup_manager.run_backup()
        
        if success:
            logger.info("Backup script completed successfully")
            return True
        else:
            logger.error("Backup script failed")
            return False
            
    except Exception as e:
        logger.error(f"Backup script error: {str(e)}")
        return False

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
