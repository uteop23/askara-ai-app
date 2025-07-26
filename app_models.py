# app_models.py - PERFORMANCE ENHANCED VERSION - Database Models
# Enhanced dengan indexes, validations, dan performance optimizations

from datetime import datetime, timedelta
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import json
import validators

# Instance database - akan diinisialisasi di app.py
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
    
    # Relationships
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
                db.session.commit()
                return True
            except Exception:
                db.session.rollback()
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
    
    def to_dict(self):
        """Convert user to dictionary for JSON responses"""
        return {
            'id': self.id,
            'email': self.email,
            'name': self.name,
            'credits': self.credits,
            'is_premium': self.is_premium_active(),
            'created_at': self.created_at.isoformat(),
            'last_login': self.last_login.isoformat() if self.last_login else None
        }

class VideoProcess(db.Model):
    __tablename__ = 'video_processes'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    youtube_url = db.Column(db.String(500), nullable=False)
    task_id = db.Column(db.String(100), unique=True, nullable=False, index=True)
    status = db.Column(db.String(50), default='pending', nullable=False, index=True)
    original_title = db.Column(db.String(300), nullable=True)
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
    
    # Relationships
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
    
    def to_dict(self):
        """Convert to dictionary with enhanced info"""
        return {
            'id': self.id,
            'task_id': self.task_id,
            'status': self.status,
            'status_color': self.get_status_color(),
            'original_title': self.original_title,
            'clips_generated': self.clips_generated,
            'created_at': self.created_at.isoformat(),
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'processing_time_seconds': self.processing_time_seconds,
            'video_duration_seconds': self.video_duration_seconds,
            'error_message': self.error_message
        }

class VideoClip(db.Model):
    __tablename__ = 'video_clips'
    
    id = db.Column(db.Integer, primary_key=True)
    process_id = db.Column(db.Integer, db.ForeignKey('video_processes.id'), nullable=False, index=True)
    filename = db.Column(db.String(200), nullable=False, index=True)
    title = db.Column(db.String(300), nullable=True)
    duration = db.Column(db.Float, nullable=True)
    viral_score = db.Column(db.Float, default=0.0, nullable=False, index=True)
    start_time = db.Column(db.Float, nullable=True)
    end_time = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Enhanced metadata
    file_size_mb = db.Column(db.Float, nullable=True)
    resolution = db.Column(db.String(20), nullable=True)  # e.g., "720x1280"
    download_count = db.Column(db.Integer, default=0, nullable=False)
    
    # Composite indexes for better query performance
    __table_args__ = (
        db.Index('idx_video_clip_process_viral', 'process_id', 'viral_score'),
        db.Index('idx_video_clip_created_score', 'created_at', 'viral_score'),
        db.Index('idx_video_clip_filename_process', 'filename', 'process_id'),
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
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
    
    def get_file_path(self):
        """Get full file path"""
        return f"/var/www/askaraai/static/clips/{self.filename}"
    
    def file_exists(self):
        """Check if file exists on disk"""
        import os
        return os.path.exists(self.get_file_path())
    
    def to_dict(self):
        """Convert to dictionary with enhanced info"""
        return {
            'id': self.id,
            'filename': self.filename,
            'title': self.title,
            'duration': self.duration,
            'viral_score': self.viral_score,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'file_size_mb': self.file_size_mb,
            'resolution': self.resolution,
            'download_count': self.download_count,
            'file_exists': self.file_exists(),
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
    
    # Composite indexes
    __table_args__ = (
        db.Index('idx_payment_user_status', 'user_id', 'status'),
        db.Index('idx_payment_status_created', 'status', 'created_at'),
        db.Index('idx_payment_reference_status', 'tripay_reference', 'status'),
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
    
    def validate_amount(self):
        """Validate payment amount"""
        if self.amount <= 0:
            raise ValueError("Payment amount must be positive")
        if self.amount > 10000000:  # 100 million rupiah max
            raise ValueError("Payment amount too large")
        return True
    
    def to_dict(self):
        """Convert to dictionary"""
        return {
            'id': self.id,
            'tripay_reference': self.tripay_reference,
            'amount': self.amount,
            'currency': self.currency,
            'status': self.status,
            'payment_method': self.payment_method,
            'description': self.description,
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
    
    # Relationships
    usages = db.relationship('PromoUsage', backref='promo_code', lazy=True)
    
    # Composite indexes
    __table_args__ = (
        db.Index('idx_promo_code_active_expires', 'is_active', 'expires_at'),
        db.Index('idx_promo_code_type_active', 'discount_type', 'is_active'),
        db.Index('idx_promo_code_usage', 'used_count', 'max_uses'),
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
        
        # Check if user has already used this promo
        existing_usage = PromoUsage.query.filter_by(
            promo_code_id=self.id,
            user_id=user_id
        ).first()
        
        if existing_usage:
            return False, "You have already used this promo code"
        
        return True, "Can be used"
    
    def apply_to_user(self, user):
        """Apply promo code to user"""
        can_use, message = self.can_be_used_by_user(user.id)
        if not can_use:
            raise ValueError(message)
        
        # Apply the discount
        if self.discount_type == 'credits':
            user.add_credits(int(self.discount_value))
        elif self.discount_type == 'days':
            if user.is_premium:
                if user.premium_expires:
                    user.premium_expires += timedelta(days=int(self.discount_value))
                else:
                    user.premium_expires = datetime.utcnow() + timedelta(days=int(self.discount_value))
            else:
                user.is_premium = True
                user.premium_expires = datetime.utcnow() + timedelta(days=int(self.discount_value))
        elif self.discount_type == 'percentage':
            # For percentage discounts, this would typically be applied at payment time
            # This is a placeholder for payment integration
            pass
        
        # Record usage
        usage = PromoUsage(
            promo_code_id=self.id,
            user_id=user.id
        )
        db.session.add(usage)
        
        # Increment usage count
        self.used_count += 1
        
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
            'usage_percentage': (self.used_count / self.max_uses * 100) if self.max_uses > 0 else 0
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
    
    def to_dict(self):
        """Convert to dictionary"""
        return {
            'id': self.id,
            'check_time': self.check_time.isoformat(),
            'overall_status': self.overall_status,
            'database_status': self.database_status,
            'redis_status': self.redis_status,
            'celery_status': self.celery_status,
            'disk_usage': self.disk_usage,
            'memory_usage': self.memory_usage,
            'cpu_usage': self.cpu_usage,
            'details': json.loads(self.details) if self.details else None
        }

class PromoUsage(db.Model):
    __tablename__ = 'promo_usage'
    
    id = db.Column(db.Integer, primary_key=True)
    promo_code_id = db.Column(db.Integer, db.ForeignKey('promo_codes.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    applied_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Composite indexes
    __table_args__ = (
        db.Index('idx_promo_usage_user_promo', 'user_id', 'promo_code_id'),
        db.Index('idx_promo_usage_promo_time', 'promo_code_id', 'applied_at'),
        db.UniqueConstraint('user_id', 'promo_code_id', name='uq_user_promo'),  # Prevent duplicate usage
    )
    
    def to_dict(self):
        """Convert to dictionary"""
        return {
            'id': self.id,
            'promo_code_id': self.promo_code_id,
            'user_id': self.user_id,
            'applied_at': self.applied_at.isoformat()
        }
