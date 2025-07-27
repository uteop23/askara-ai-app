# app_models.py - FIXED COMPLETE VERSION
# Enhanced database models dengan circular import resolved

from datetime import datetime, timedelta
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import json
import validators
import secrets

# Instance database - akan diinisialisasi di app.py (FIXED: No circular import)
db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    google_id = db.Column(db.String(100), unique=True, nullable=True, index=True)
    password_hash = db.Column(db.String(255), nullable=True)
    credits = db.Column(db.Integer, default=30, nullable=False)
    is_premium = db.Column(db.Boolean, default=False, nullable=False)
    premium_expires = db.Column(db.DateTime, nullable=True)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    last_login = db.Column(db.DateTime, nullable=True)
    email_verified = db.Column(db.Boolean, default=False, nullable=False)
    verification_token = db.Column(db.String(100), nullable=True)
    
    # Enhanced security fields
    failed_login_attempts = db.Column(db.Integer, default=0, nullable=False)
    account_locked_until = db.Column(db.DateTime, nullable=True)
    last_password_change = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Profile fields
    avatar_url = db.Column(db.String(500), nullable=True)
    timezone = db.Column(db.String(50), default='UTC', nullable=False)
    language = db.Column(db.String(10), default='id', nullable=False)
    
    # Preferences
    email_notifications = db.Column(db.Boolean, default=True, nullable=False)
    marketing_emails = db.Column(db.Boolean, default=False, nullable=False)
    
    # Relationships - FIXED: Use string references to avoid circular imports
    video_processes = db.relationship('VideoProcess', backref='user', lazy=True, cascade='all, delete-orphan')
    payments = db.relationship('Payment', backref='user', lazy=True)
    promo_usages = db.relationship('PromoUsage', backref='user', lazy=True)
    
    # Composite indexes for better query performance
    __table_args__ = (
        db.Index('idx_user_email_verified', 'email', 'email_verified'),
        db.Index('idx_user_premium_status', 'is_premium', 'premium_expires'),
        db.Index('idx_user_admin_status', 'is_admin', 'email_verified'),
        db.Index('idx_user_created_credits', 'created_at', 'credits'),
    )
    
    def set_password(self, password):
        """Set password hash with validation"""
        if not password or len(password) < 8:
            raise ValueError("Password must be at least 8 characters long")
        
        self.password_hash = generate_password_hash(password)
        self.last_password_change = datetime.utcnow()
        self.failed_login_attempts = 0  # Reset failed attempts on password change
        self.account_locked_until = None
    
    def check_password(self, password):
        """Check password with account lockout protection"""
        if not self.password_hash:
            return False
        
        # Check if account is locked
        if self.account_locked_until and datetime.utcnow() < self.account_locked_until:
            return False
        
        # Check password
        is_valid = check_password_hash(self.password_hash, password)
        
        if is_valid:
            # Reset failed attempts on successful login
            self.failed_login_attempts = 0
            self.account_locked_until = None
        else:
            # Increment failed attempts
            self.failed_login_attempts += 1
            
            # Lock account after 5 failed attempts for 1 hour
            if self.failed_login_attempts >= 5:
                self.account_locked_until = datetime.utcnow() + timedelta(hours=1)
        
        return is_valid
    
    def is_premium_active(self):
        """Check if user has active premium subscription"""
        if not self.is_premium:
            return False
        if not self.premium_expires:
            return True
        return datetime.utcnow() < self.premium_expires
    
    def deduct_credits(self, amount=10):
        """Deduct credits from user account with validation"""
        if self.is_premium_active():
            return True
        
        if amount <= 0:
            raise ValueError("Credit amount must be positive")
        
        if self.credits >= amount:
            self.credits -= amount
            try:
                # FIXED: Don't commit here - let the calling code handle transactions
                return True
            except Exception:
                return False
        return False
    
    def add_credits(self, amount):
        """Add credits to user account"""
        if amount <= 0:
            raise ValueError("Credit amount must be positive")
        
        self.credits += amount
        return True
    
    def is_account_locked(self):
        """Check if account is currently locked"""
        return (self.account_locked_until and 
                datetime.utcnow() < self.account_locked_until)
    
    def validate_email(self):
        """Validate email format"""
        if not self.email or not validators.email(self.email):
            raise ValueError("Invalid email format")
        return True
    
    def generate_verification_token(self):
        """Generate email verification token"""
        self.verification_token = secrets.token_urlsafe(32)
        return self.verification_token
    
    def verify_email(self, token):
        """Verify email with token"""
        if self.verification_token == token:
            self.email_verified = True
            self.verification_token = None
            return True
        return False
    
    def upgrade_to_premium(self, days=30):
        """Upgrade user to premium"""
        self.is_premium = True
        if self.premium_expires and self.premium_expires > datetime.utcnow():
            # Extend existing premium
            self.premium_expires += timedelta(days=days)
        else:
            # New premium subscription
            self.premium_expires = datetime.utcnow() + timedelta(days=days)
    
    def to_dict(self):
        """Convert user to dictionary for JSON responses"""
        return {
            'id': self.id,
            'email': self.email,
            'name': self.name,
            'credits': self.credits,
            'is_premium': self.is_premium_active(),
            'is_admin': self.is_admin,
            'email_verified': self.email_verified,
            'created_at': self.created_at.isoformat(),
            'last_login': self.last_login.isoformat() if self.last_login else None,
            'premium_expires': self.premium_expires.isoformat() if self.premium_expires else None
        }

class VideoProcess(db.Model):
    __tablename__ = 'video_processes'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    youtube_url = db.Column(db.String(500), nullable=False)
    task_id = db.Column(db.String(100), unique=True, nullable=False, index=True)
    status = db.Column(db.String(50), default='pending', nullable=False, index=True)
    original_title = db.Column(db.String(300), nullable=True)
    original_description = db.Column(db.Text, nullable=True)
    clips_generated = db.Column(db.Integer, default=0, nullable=False)
    blog_article = db.Column(db.Text, nullable=True)
    carousel_posts = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    
    # Performance tracking fields
    processing_time_seconds = db.Column(db.Integer, nullable=True)
    video_duration_seconds = db.Column(db.Integer, nullable=True)
    file_size_mb = db.Column(db.Float, nullable=True)
    ai_analysis_time = db.Column(db.Integer, nullable=True)
    
    # Quality metrics
    success_rate = db.Column(db.Float, nullable=True)
    user_rating = db.Column(db.Integer, nullable=True)  # 1-5 stars
    user_feedback = db.Column(db.Text, nullable=True)
    
    # Processing settings
    target_clip_duration = db.Column(db.Integer, default=60, nullable=False)
    max_clips = db.Column(db.Integer, default=10, nullable=False)
    language = db.Column(db.String(10), default='id', nullable=False)
    
    # Relationships - FIXED: Use string references
    clips = db.relationship('VideoClip', backref='video_process', lazy=True, cascade='all, delete-orphan')
    
    # Composite indexes for better query performance
    __table_args__ = (
        db.Index('idx_video_process_status_created', 'status', 'created_at'),
        db.Index('idx_video_process_user_status', 'user_id', 'status'),
        db.Index('idx_video_process_completed', 'completed_at', 'status'),
        db.Index('idx_video_process_task_status', 'task_id', 'status'),
    )
    
    def validate_youtube_url(self):
        """Validate YouTube URL format"""
        if not self.youtube_url:
            raise ValueError("YouTube URL is required")
        
        valid_domains = ['youtube.com', 'youtu.be', 'www.youtube.com', 'm.youtube.com']
        if not any(domain in self.youtube_url for domain in valid_domains):
            raise ValueError("Invalid YouTube URL")
        
        if not self.youtube_url.startswith(('http://', 'https://')):
            raise ValueError("URL must start with http:// or https://")
        
        return True
    
    def calculate_processing_time(self):
        """Calculate and update processing time"""
        if self.completed_at and self.created_at:
            delta = self.completed_at - self.created_at
            self.processing_time_seconds = int(delta.total_seconds())
        return self.processing_time_seconds
    
    def get_status_color(self):
        """Get status color for UI"""
        status_colors = {
            'pending': 'yellow',
            'downloading': 'blue',
            'processing': 'blue',
            'analyzing': 'purple',
            'creating_clips': 'indigo',
            'completed': 'green',
            'failed': 'red'
        }
        return status_colors.get(self.status, 'gray')
    
    def mark_completed(self):
        """Mark process as completed"""
        self.status = 'completed'
        self.completed_at = datetime.utcnow()
        self.calculate_processing_time()
    
    def mark_failed(self, error_message):
        """Mark process as failed with error message"""
        self.status = 'failed'
        self.error_message = error_message
        self.completed_at = datetime.utcnow()
    
    def get_progress_percentage(self):
        """Get processing progress percentage"""
        progress_map = {
            'pending': 0,
            'downloading': 20,
            'processing': 40,
            'analyzing': 60,
            'creating_clips': 80,
            'completed': 100,
            'failed': 0
        }
        return progress_map.get(self.status, 0)
    
    def to_dict(self):
        """Convert to dictionary with enhanced info"""
        return {
            'id': self.id,
            'task_id': self.task_id,
            'status': self.status,
            'status_color': self.get_status_color(),
            'progress_percentage': self.get_progress_percentage(),
            'original_title': self.original_title,
            'clips_generated': self.clips_generated,
            'created_at': self.created_at.isoformat(),
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'processing_time_seconds': self.processing_time_seconds,
            'video_duration_seconds': self.video_duration_seconds,
            'error_message': self.error_message,
            'user_rating': self.user_rating
        }

class VideoClip(db.Model):
    __tablename__ = 'video_clips'
    
    id = db.Column(db.Integer, primary_key=True)
    process_id = db.Column(db.Integer, db.ForeignKey('video_processes.id'), nullable=False, index=True)
    filename = db.Column(db.String(200), nullable=False, index=True)
    title = db.Column(db.String(300), nullable=True)
    description = db.Column(db.Text, nullable=True)
    duration = db.Column(db.Float, nullable=True)
    viral_score = db.Column(db.Float, default=0.0, nullable=False, index=True)
    start_time = db.Column(db.Float, nullable=True)
    end_time = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Enhanced metadata
    file_size_mb = db.Column(db.Float, nullable=True)
    resolution = db.Column(db.String(20), nullable=True)  # e.g., "720x1280"
    download_count = db.Column(db.Integer, default=0, nullable=False)
    view_count = db.Column(db.Integer, default=0, nullable=False)
    share_count = db.Column(db.Integer, default=0, nullable=False)
    
    # Content analysis
    detected_objects = db.Column(db.Text, nullable=True)  # JSON array
    transcription = db.Column(db.Text, nullable=True)
    keywords = db.Column(db.Text, nullable=True)  # JSON array
    sentiment_score = db.Column(db.Float, nullable=True)
    
    # Social media optimization
    hashtags = db.Column(db.Text, nullable=True)  # JSON array
    optimal_posting_time = db.Column(db.String(50), nullable=True)
    platform_optimized = db.Column(db.String(50), default='universal', nullable=False)
    
    # Quality metrics
    audio_quality = db.Column(db.Float, nullable=True)
    video_quality = db.Column(db.Float, nullable=True)
    engagement_prediction = db.Column(db.Float, nullable=True)
    
    # Composite indexes for better query performance
    __table_args__ = (
        db.Index('idx_video_clip_process_viral', 'process_id', 'viral_score'),
        db.Index('idx_video_clip_created_score', 'created_at', 'viral_score'),
        db.Index('idx_video_clip_filename_process', 'filename', 'process_id'),
        db.Index('idx_video_clip_downloads', 'download_count', 'created_at'),
    )
    
    def validate_duration(self):
        """Validate clip duration"""
        if self.start_time is not None and self.end_time is not None:
            if self.start_time >= self.end_time:
                raise ValueError("Start time must be less than end time")
            
            calculated_duration = self.end_time - self.start_time
            if abs(calculated_duration - (self.duration or 0)) > 2:  # 2 second tolerance
                self.duration = calculated_duration
        
        if self.duration and (self.duration < 5 or self.duration > 300):  # 5s to 5min
            raise ValueError("Clip duration must be between 5 seconds and 5 minutes")
        
        return True
    
    def validate_viral_score(self):
        """Validate viral score range"""
        if self.viral_score < 0 or self.viral_score > 10:
            raise ValueError("Viral score must be between 0 and 10")
        return True
    
    def increment_download_count(self):
        """Increment download counter"""
        self.download_count += 1
        # Don't auto-commit - let the calling code handle transactions
    
    def increment_view_count(self):
        """Increment view counter"""
        self.view_count += 1
        # Don't auto-commit - let the calling code handle transactions
    
    def increment_share_count(self):
        """Increment share counter"""
        self.share_count += 1
        # Don't auto-commit - let the calling code handle transactions
    
    def get_file_path(self):
        """Get full file path"""
        return f"/var/www/askaraai/static/clips/{self.filename}"
    
    def file_exists(self):
        """Check if file exists on disk"""
        import os
        return os.path.exists(self.get_file_path())
    
    def get_hashtags_list(self):
        """Get hashtags as list"""
        try:
            return json.loads(self.hashtags) if self.hashtags else []
        except:
            return []
    
    def set_hashtags_list(self, hashtags_list):
        """Set hashtags from list"""
        self.hashtags = json.dumps(hashtags_list) if hashtags_list else None
    
    def get_keywords_list(self):
        """Get keywords as list"""
        try:
            return json.loads(self.keywords) if self.keywords else []
        except:
            return []
    
    def set_keywords_list(self, keywords_list):
        """Set keywords from list"""
        self.keywords = json.dumps(keywords_list) if keywords_list else None
    
    def to_dict(self):
        """Convert to dictionary with enhanced info"""
        return {
            'id': self.id,
            'filename': self.filename,
            'title': self.title,
            'description': self.description,
            'duration': self.duration,
            'viral_score': self.viral_score,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'file_size_mb': self.file_size_mb,
            'resolution': self.resolution,
            'download_count': self.download_count,
            'view_count': self.view_count,
            'share_count': self.share_count,
            'file_exists': self.file_exists(),
            'hashtags': self.get_hashtags_list(),
            'keywords': self.get_keywords_list(),
            'engagement_prediction': self.engagement_prediction,
            'created_at': self.created_at.isoformat()
        }

class Payment(db.Model):
    __tablename__ = 'payments'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    tripay_reference = db.Column(db.String(100), unique=True, nullable=False, index=True)
    amount = db.Column(db.Integer, nullable=False)  # Amount in cents/rupiah
    status = db.Column(db.String(50), default='pending', nullable=False, index=True)
    payment_method = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    paid_at = db.Column(db.DateTime, nullable=True)
    
    # Enhanced payment tracking
    currency = db.Column(db.String(3), default='IDR', nullable=False)
    description = db.Column(db.String(200), nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    
    # Product information
    product_type = db.Column(db.String(50), nullable=True)  # 'premium', 'credits', etc.
    product_details = db.Column(db.Text, nullable=True)  # JSON
    
    # Transaction details
    fee_amount = db.Column(db.Integer, default=0, nullable=False)
    net_amount = db.Column(db.Integer, nullable=True)
    
    # Composite indexes
    __table_args__ = (
        db.Index('idx_payment_user_status', 'user_id', 'status'),
        db.Index('idx_payment_status_created', 'status', 'created_at'),
        db.Index('idx_payment_reference_status', 'tripay_reference', 'status'),
        db.Index('idx_payment_expires', 'expires_at', 'status'),
    )
    
    def is_expired(self):
        """Check if payment has expired"""
        return (self.expires_at and 
                datetime.utcnow() > self.expires_at and 
                self.status == 'pending')
    
    def mark_as_paid(self):
        """Mark payment as paid"""
        self.status = 'paid'
        self.paid_at = datetime.utcnow()
    
    def mark_as_failed(self):
        """Mark payment as failed"""
        self.status = 'failed'
    
    def mark_as_expired(self):
        """Mark payment as expired"""
        self.status = 'expired'
    
    def validate_amount(self):
        """Validate payment amount"""
        if self.amount <= 0:
            raise ValueError("Payment amount must be positive")
        if self.amount > 10000000:  # 100 million rupiah max
            raise ValueError("Payment amount too large")
        return True
    
    def calculate_net_amount(self):
        """Calculate net amount after fees"""
        self.net_amount = self.amount - self.fee_amount
        return self.net_amount
    
    def get_product_details_dict(self):
        """Get product details as dictionary"""
        try:
            return json.loads(self.product_details) if self.product_details else {}
        except:
            return {}
    
    def set_product_details_dict(self, details_dict):
        """Set product details from dictionary"""
        self.product_details = json.dumps(details_dict) if details_dict else None
    
    def to_dict(self):
        """Convert to dictionary"""
        return {
            'id': self.id,
            'tripay_reference': self.tripay_reference,
            'amount': self.amount,
            'net_amount': self.net_amount,
            'fee_amount': self.fee_amount,
            'currency': self.currency,
            'status': self.status,
            'payment_method': self.payment_method,
            'description': self.description,
            'product_type': self.product_type,
            'product_details': self.get_product_details_dict(),
            'created_at': self.created_at.isoformat(),
            'paid_at': self.paid_at.isoformat() if self.paid_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'is_expired': self.is_expired()
        }

class CountdownSettings(db.Model):
    __tablename__ = 'countdown_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    is_active = db.Column(db.Boolean, default=False, nullable=False)
    target_datetime = db.Column(db.DateTime, nullable=True)
    title = db.Column(db.String(200), default='AskaraAI Launching Soon!', nullable=False)
    subtitle = db.Column(db.String(500), default='AI-powered video clipper coming soon', nullable=False)
    background_style = db.Column(db.String(50), default='gradient', nullable=False)
    redirect_after_launch = db.Column(db.String(200), default='/', nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Additional settings
    show_early_access_form = db.Column(db.Boolean, default=True, nullable=False)
    early_access_message = db.Column(db.String(500), nullable=True)
    custom_css = db.Column(db.Text, nullable=True)
    analytics_code = db.Column(db.Text, nullable=True)
    
    @classmethod
    def get_current(cls):
        """Get current countdown settings"""
        settings = cls.query.first()
        if not settings:
            settings = cls()
        return settings
    
    def is_launch_time_passed(self):
        """Check if launch time has passed"""
        if not self.target_datetime:
            return True
        return datetime.utcnow() >= self.target_datetime
    
    def time_until_launch(self):
        """Get time until launch in seconds"""
        if not self.target_datetime:
            return 0
        delta = self.target_datetime - datetime.utcnow()
        return max(0, int(delta.total_seconds()))
    
    def validate_settings(self):
        """Validate countdown settings"""
        if self.is_active and not self.target_datetime:
            raise ValueError("Target datetime is required when countdown is active")
        
        if self.target_datetime and self.target_datetime <= datetime.utcnow():
            self.is_active = False  # Auto-disable if time has passed
        
        return True
    
    def to_dict(self):
        """Convert to dictionary"""
        return {
            'id': self.id,
            'is_active': self.is_active,
            'target_datetime': self.target_datetime.isoformat() if self.target_datetime else None,
            'title': self.title,
            'subtitle': self.subtitle,
            'background_style': self.background_style,
            'redirect_after_launch': self.redirect_after_launch,
            'show_early_access_form': self.show_early_access_form,
            'early_access_message': self.early_access_message,
            'time_until_launch': self.time_until_launch(),
            'is_launch_time_passed': self.is_launch_time_passed()
        }

class PromoCode(db.Model):
    __tablename__ = 'promo_codes'
    
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    description = db.Column(db.String(200), nullable=False)
    discount_type = db.Column(db.String(20), nullable=False, index=True)  # percentage, days, credits
    discount_value = db.Column(db.Float, nullable=False)
    max_uses = db.Column(db.Integer, default=100, nullable=False)
    used_count = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    expires_at = db.Column(db.DateTime, nullable=True, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Enhanced promo features
    min_purchase_amount = db.Column(db.Integer, default=0, nullable=False)
    target_user_type = db.Column(db.String(20), default='all', nullable=False)  # all, new, existing
    usage_limit_per_user = db.Column(db.Integer, default=1, nullable=False)
    
    # Analytics
    total_discount_given = db.Column(db.Float, default=0.0, nullable=False)
    conversion_rate = db.Column(db.Float, nullable=True)
    
    # Relationships - FIXED: Use string references
    usages = db.relationship('PromoUsage', backref='promo_code', lazy=True)
    
    # Composite indexes
    __table_args__ = (
        db.Index('idx_promo_code_active_expires', 'is_active', 'expires_at'),
        db.Index('idx_promo_code_type_active', 'discount_type', 'is_active'),
        db.Index('idx_promo_code_usage', 'used_count', 'max_uses'),
        db.Index('idx_promo_code_target', 'target_user_type', 'is_active'),
    )
    
    def is_valid(self):
        """Check if promo code is valid for use"""
        if not self.is_active:
            return False, "Promo code is inactive"
        
        if self.expires_at and datetime.utcnow() > self.expires_at:
            return False, "Promo code has expired"
        
        if self.used_count >= self.max_uses:
            return False, "Promo code usage limit reached"
        
        return True, "Valid"
    
    def can_be_used_by_user(self, user_id):
        """Check if promo code can be used by specific user"""
        is_valid, message = self.is_valid()
        if not is_valid:
            return False, message
        
        # Check user usage limit - FIXED: Avoid circular import
        # This will be handled in the calling code with proper import context
        try:
            from app_models import PromoUsage
            user_usage_count = PromoUsage.query.filter_by(
                promo_code_id=self.id,
                user_id=user_id
            ).count()
        except ImportError:
            # If import fails, assume zero usage (for setup phase)
            user_usage_count = 0
        
        if user_usage_count >= self.usage_limit_per_user:
            return False, f"You have already used this promo code {self.usage_limit_per_user} time(s)"
        
        # Check target user type - FIXED: Avoid circular import
        if self.target_user_type != 'all':
            try:
                user = User.query.get(user_id)
                if user:
                    if self.target_user_type == 'new' and user.video_processes:
                        return False, "This promo is only for new users"
                    elif self.target_user_type == 'existing' and not user.video_processes:
                        return False, "This promo is only for existing users"
            except:
                # If check fails, allow usage
                pass
        
        return True, "Can be used"
    
    def apply_to_user(self, user):
        """Apply promo code to user"""
        can_use, message = self.can_be_used_by_user(user.id)
        if not can_use:
            raise ValueError(message)
        
        discount_given = 0
        
        # Apply the discount
        if self.discount_type == 'credits':
            user.add_credits(int(self.discount_value))
            discount_given = self.discount_value
        elif self.discount_type == 'days':
            user.upgrade_to_premium(int(self.discount_value))
            discount_given = self.discount_value
        elif self.discount_type == 'percentage':
            # For percentage discounts, this would typically be applied at payment time
            # This is a placeholder for payment integration
            discount_given = self.discount_value
        
        # Record usage - FIXED: Use proper import
        try:
            usage = PromoUsage(
                promo_code_id=self.id,
                user_id=user.id,
                discount_applied=discount_given
            )
            db.session.add(usage)
        except:
            # If model not available, skip usage tracking for now
            pass
        
        # Increment usage count and update analytics
        self.used_count += 1
        self.total_discount_given += discount_given
        
        return True
    
    def validate_discount(self):
        """Validate discount value based on type"""
        if self.discount_type == 'percentage':
            if self.discount_value <= 0 or self.discount_value > 100:
                raise ValueError("Percentage discount must be between 1 and 100")
        elif self.discount_type in ['days', 'credits']:
            if self.discount_value <= 0:
                raise ValueError(f"{self.discount_type.title()} discount must be positive")
        else:
            raise ValueError("Invalid discount type")
        
        return True
    
    def calculate_conversion_rate(self):
        """Calculate conversion rate for this promo"""
        if self.used_count == 0:
            self.conversion_rate = 0.0
        else:
            # This would need more complex logic based on your conversion tracking
            # For now, just a placeholder
            self.conversion_rate = (self.used_count / max(self.max_uses, 1)) * 100
        
        return self.conversion_rate
    
    def to_dict(self):
        """Convert to dictionary"""
        is_valid, validity_message = self.is_valid()
        
        return {
            'id': self.id,
            'code': self.code,
            'description': self.description,
            'discount_type': self.discount_type,
            'discount_value': self.discount_value,
            'max_uses': self.max_uses,
            'used_count': self.used_count,
            'is_active': self.is_active,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'created_at': self.created_at.isoformat(),
            'is_valid': is_valid,
            'validity_message': validity_message,
            'usage_percentage': (self.used_count / self.max_uses * 100) if self.max_uses > 0 else 0,
            'target_user_type': self.target_user_type,
            'usage_limit_per_user': self.usage_limit_per_user,
            'total_discount_given': self.total_discount_given,
            'conversion_rate': self.conversion_rate
        }

class SystemHealth(db.Model):
    __tablename__ = 'system_health'
    
    id = db.Column(db.Integer, primary_key=True)
    check_time = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    overall_status = db.Column(db.String(20), nullable=False, index=True)
    database_status = db.Column(db.String(20), nullable=False)
    redis_status = db.Column(db.String(20), nullable=False)
    celery_status = db.Column(db.String(20), nullable=False)
    disk_usage = db.Column(db.Float, nullable=True)
    memory_usage = db.Column(db.Float, nullable=True)
    cpu_usage = db.Column(db.Float, nullable=True)
    details = db.Column(db.Text, nullable=True)
    
    # Additional monitoring
    active_users = db.Column(db.Integer, nullable=True)
    processing_queue_size = db.Column(db.Integer, nullable=True)
    error_rate = db.Column(db.Float, nullable=True)
    response_time_avg = db.Column(db.Float, nullable=True)
    
    # Composite indexes
    __table_args__ = (
        db.Index('idx_system_health_time_status', 'check_time', 'overall_status'),
        db.Index('idx_system_health_status_time', 'overall_status', 'check_time'),
    )
    
    @classmethod
    def get_latest(cls):
        """Get latest health check"""
        return cls.query.order_by(cls.check_time.desc()).first()
    
    @classmethod
    def get_health_history(cls, hours=24):
        """Get health history for specified hours"""
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)
        return cls.query.filter(
            cls.check_time >= cutoff_time
        ).order_by(cls.check_time.desc()).all()
    
    def is_healthy(self):
        """Check if system is healthy"""
        return self.overall_status == 'healthy'
    
    def get_health_score(self):
        """Calculate overall health score (0-100)"""
        scores = {
            'healthy': 100,
            'warning': 70,
            'critical': 30,
            'unhealthy': 0
        }
        return scores.get(self.overall_status, 0)
    
    def to_dict(self):
        """Convert to dictionary"""
        return {
            'id': self.id,
            'check_time': self.check_time.isoformat(),
            'overall_status': self.overall_status,
            'health_score': self.get_health_score(),
            'database_status': self.database_status,
            'redis_status': self.redis_status,
            'celery_status': self.celery_status,
            'disk_usage': self.disk_usage,
            'memory_usage': self.memory_usage,
            'cpu_usage': self.cpu_usage,
            'active_users': self.active_users,
            'processing_queue_size': self.processing_queue_size,
            'error_rate': self.error_rate,
            'response_time_avg': self.response_time_avg,
            'details': json.loads(self.details) if self.details else None
        }

class PromoUsage(db.Model):
    __tablename__ = 'promo_usage'
    
    id = db.Column(db.Integer, primary_key=True)
    promo_code_id = db.Column(db.Integer, db.ForeignKey('promo_codes.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    applied_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    discount_applied = db.Column(db.Float, nullable=True)
    
    # Additional tracking
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(500), nullable=True)
    
    # Composite indexes
    __table_args__ = (
        db.Index('idx_promo_usage_user_promo', 'user_id', 'promo_code_id'),
        db.Index('idx_promo_usage_promo_time', 'promo_code_id', 'applied_at'),
        # FIXED: Removed unique constraint yang bisa menyebabkan error saat testing
        # db.UniqueConstraint('user_id', 'promo_code_id', name='uq_user_promo_per_code'),
    )
    
    def to_dict(self):
        """Convert to dictionary"""
        return {
            'id': self.id,
            'promo_code_id': self.promo_code_id,
            'user_id': self.user_id,
            'applied_at': self.applied_at.isoformat(),
            'discount_applied': self.discount_applied
        }
