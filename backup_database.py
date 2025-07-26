#!/usr/bin/env python3
"""
AskaraAI Database Backup Script
Automatically backs up database to Google Drive every 26 days
"""

import os
import subprocess
import logging
from datetime import datetime
from dotenv import load_dotenv

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

class DatabaseBackup:
    def __init__(self):
        self.db_host = 'localhost'
        self.db_user = 'askaraai'
        self.db_password = os.getenv('DB_PASSWORD')
        self.db_name = 'askaraai_db'
        self.backup_dir = '/tmp'
        self.drive_backup_path = 'AskaraAI/backups'

        if not self.db_password:
            logger.critical("FATAL: DB_PASSWORD environment variable not set. Backup aborted.")
            raise ValueError("DB_PASSWORD tidak ditemukan di environment variables.")

        
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
                    text=True
                )
            
            # Check if file was created and has content
            if os.path.exists(backup_path) and os.path.getsize(backup_path) > 0:
                logger.info(f"MySQL dump created successfully: {backup_path}")
                return True
            else:
                logger.error("MySQL dump file is empty or not created")
                return False
                
        except subprocess.CalledProcessError as e:
            logger.error(f"MySQL dump failed: {e.stderr.decode() if e.stderr else str(e)}")
            return False
        except Exception as e:
            logger.error(f"Error creating MySQL dump: {str(e)}")
            return False
    
    def upload_to_google_drive(self, backup_path, backup_filename):
        """Upload backup to Google Drive using rclone"""
        try:
            logger.info(f"Uploading {backup_filename} to Google Drive...")
            
            # Rclone copy command
            drive_path = f"gdrive:{self.drive_backup_path}/{backup_filename}"
            cmd = ['rclone', 'copy', backup_path, f"gdrive:{self.drive_backup_path}/"]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            
            logger.info(f"Backup uploaded successfully to: {drive_path}")
            return True
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Upload to Google Drive failed: {e.stderr}")
            return False
        except Exception as e:
            logger.error(f"Error uploading to Google Drive: {str(e)}")
            return False
    
    def cleanup_old_backups(self):
        """Remove old backups from Google Drive (keep only last 5)"""
        try:
            logger.info("Cleaning up old backups...")
            
            # List files in backup directory
            cmd = ['rclone', 'lsf', f"gdrive:{self.drive_backup_path}/", '--max-age', '200d']
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0 and result.stdout.strip():
                files = [f.strip() for f in result.stdout.strip().split('\n') if f.strip().endswith('.sql')]
                files.sort()  # Sort by name (which includes timestamp)
                
                # Keep only the last 5 backups
                if len(files) > 5:
                    files_to_delete = files[:-5]  # All except last 5
                    
                    for file_to_delete in files_to_delete:
                        delete_cmd = ['rclone', 'delete', f"gdrive:{self.drive_backup_path}/{file_to_delete}"]
                        delete_result = subprocess.run(delete_cmd, capture_output=True)
                        
                        if delete_result.returncode == 0:
                            logger.info(f"Deleted old backup: {file_to_delete}")
                        else:
                            logger.warning(f"Failed to delete old backup: {file_to_delete}")
                
                logger.info(f"Cleanup completed. Kept {min(len(files), 5)} backups")
            else:
                logger.info("No old backups found to clean up")
                
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")
    
    def cleanup_local_backup(self, backup_path):
        """Remove local backup file"""
        try:
            if os.path.exists(backup_path):
                os.remove(backup_path)
                logger.info(f"Local backup file removed: {backup_path}")
        except Exception as e:
            logger.error(f"Error removing local backup: {str(e)}")
    
    def send_backup_notification(self, success, backup_filename, error_msg=None):
        """Send backup notification (optional - integrate with email/Slack)"""
        try:
            if success:
                message = f"✅ AskaraAI Database backup completed successfully: {backup_filename}"
                logger.info(message)
            else:
                message = f"❌ AskaraAI Database backup failed: {error_msg}"
                logger.error(message)
            
            # TODO: Integrate with email notification or Slack webhook
            # You can add email/Slack notification here if needed
            
        except Exception as e:
            logger.error(f"Error sending notification: {str(e)}")
    
    def run_backup(self):
        """Main backup process"""
        logger.info("=== Starting AskaraAI Database Backup ===")
        
        backup_filename = self.create_backup_filename()
        backup_path = os.path.join(self.backup_dir, backup_filename)
        
        try:
            # Step 1: Create MySQL dump
            if not self.create_mysql_dump(backup_path):
                self.send_backup_notification(False, backup_filename, "MySQL dump failed")
                return False
            
            # Step 2: Upload to Google Drive
            if not self.upload_to_google_drive(backup_path, backup_filename):
                self.send_backup_notification(False, backup_filename, "Google Drive upload failed")
                self.cleanup_local_backup(backup_path)
                return False
            
            # Step 3: Cleanup old backups
            self.cleanup_old_backups()
            
            # Step 4: Remove local backup file
            self.cleanup_local_backup(backup_path)
            
            # Step 5: Send success notification
            self.send_backup_notification(True, backup_filename)
            
            logger.info("=== Database Backup Completed Successfully ===")
            return True
            
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            logger.error(error_msg)
            self.send_backup_notification(False, backup_filename, error_msg)
            self.cleanup_local_backup(backup_path)
            return False

def check_prerequisites():
    """Check if required tools are available"""
    required_tools = ['mysqldump', 'rclone']
    
    for tool in required_tools:
        try:
            subprocess.run([tool, '--version'], capture_output=True, check=True)
            logger.info(f"✓ {tool} is available")
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.error(f"✗ {tool} is not available or not configured")
            return False
    
    # Check rclone Google Drive configuration
    try:
        result = subprocess.run(['rclone', 'lsd', 'gdrive:'], capture_output=True, check=True)
        logger.info("✓ Rclone Google Drive configuration is working")
        return True
    except subprocess.CalledProcessError:
        logger.error("✗ Rclone Google Drive configuration is not working")
        return False

if __name__ == "__main__":
    # Ensure logs directory exists
    os.makedirs('/var/www/askaraai/logs', exist_ok=True)
    
    logger.info("AskaraAI Database Backup Script Started")
    
    # Check prerequisites
    if not check_prerequisites():
        logger.error("Prerequisites check failed. Backup aborted.")
        exit(1)
    
    # Run backup
    backup_manager = DatabaseBackup()
    success = backup_manager.run_backup()
    
    if success:
        logger.info("Backup script completed successfully")
        exit(0)
    else:
        logger.error("Backup script failed")
        exit(1)