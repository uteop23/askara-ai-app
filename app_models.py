# app_models.py - FIXED VERSION - Database Models Only
# Menghilangkan circular import dengan memisahkan models

from datetime import datetime, timedelta
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import json

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_login = db.Column(db.DateTime, nullable=True)
    email_verified = db.Column(db.Boolean, default=False, nullable=False)
    verification_token = db.Column(db.String(100), nullable=True)
    
    # Relationships
    video_processes = db.relationship('VideoProcess', backref='user', lazy=True, cascade='all, delete-orphan')
    payments = db.relationship('Payment', backref='user', lazy=True)
    promo_usages = db.relationship('PromoUsage', backref='user', lazy=True)
    
    def set_password(self, password):
        """Set password hash"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Check password"""
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)
    
    def is_premium_active(self):
        """Check if user has active premium subscription"""
        if not self.is_premium:
            return False
        if not self.premium_expires:
            return True
        return datetime.utcnow() < self.premium_expires
    
    def deduct_credits(self, amount=10):
        """Deduct credits from user account"""
        if self.is_premium_active():
            return True
        if self.credits >= amount:
            self.credits -= amount
            try:
                db.session.commit()
                return True
            except Exception:
                db.session.rollback()
                return False
        return False
    
    def to_dict(self):
        """Convert user to dictionary for JSON responses"""
        return {
            'id': self.id,
            'email': self.email,
            'name': self.name,
            'credits': self.credits,
            'is_premium': self.is_premium_active(),
            'created_at': self.created_at.isoformat()
        }

class VideoProcess(db.Model):
    __tablename__ = 'video_processes'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    youtube_url = db.Column(db.String(500), nullable=False)
    task_id = db.Column(db.String(100), unique=True, nullable=False, index=True)
    status = db.Column(db.String(50), default='pending', nullable=False)
    original_title = db.Column(db.String(300), nullable=True)
    clips_generated = db.Column(db.Integer, default=0, nullable=False)
    blog_article = db.Column(db.Text, nullable=True)
    carousel_posts = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    
    # Relationships
    clips = db.relationship('VideoClip', backref='video_process', lazy=True, cascade='all, delete-orphan')
    
    def to_dict(self):
        """Convert to dictionary"""
        return {
            'id': self.id,
            'task_id': self.task_id,
            'status': self.status,
            'original_title': self.original_title,
            'clips_generated': self.clips_generated,
            'created_at': self.created_at.isoformat(),
            'completed_at': self.completed_at.isoformat() if self.completed_at else None
        }

class VideoClip(db.Model):
    __tablename__ = 'video_clips'
    
    id = db.Column(db.Integer, primary_key=True)
    process_id = db.Column(db.Integer, db.ForeignKey('video_processes.id'), nullable=False)
    filename = db.Column(db.String(200), nullable=False)
    title = db.Column(db.String(300), nullable=True)
    duration = db.Column(db.Float, nullable=True)
    viral_score = db.Column(db.Float, default=0.0, nullable=False)
    start_time = db.Column(db.Float, nullable=True)
    end_time = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    def to_dict(self):
        """Convert to dictionary"""
        return {
            'id': self.id,
            'filename': self.filename,
            'title': self.title,
            'duration': self.duration,
            'viral_score': self.viral_score,
            'start_time': self.start_time,
            'end_time': self.end_time
        }

class Payment(db.Model):
    __tablename__ = 'payments'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    tripay_reference = db.Column(db.String(100), unique=True, nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(50), default='pending', nullable=False)
    payment_method = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    paid_at = db.Column(db.DateTime, nullable=True)

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
        return cls.query.first() or cls()
    
    def is_launch_time_passed(self):
        """Check if launch time has passed"""
        if not self.target_datetime:
            return True
        return datetime.utcnow() >= self.target_datetime

class PromoCode(db.Model):
    __tablename__ = 'promo_codes'
    
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    description = db.Column(db.String(200), nullable=False)
    discount_type = db.Column(db.String(20), nullable=False)  # percentage, days, credits
    discount_value = db.Column(db.Float, nullable=False)
    max_uses = db.Column(db.Integer, default=100, nullable=False)
    used_count = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    usages = db.relationship('PromoUsage', backref='promo_code', lazy=True)
    
    def to_dict(self):
        """Convert to dictionary"""
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
            'created_at': self.created_at.isoformat()
        }

class SystemHealth(db.Model):
    __tablename__ = 'system_health'
    
    id = db.Column(db.Integer, primary_key=True)
    check_time = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    overall_status = db.Column(db.String(20), nullable=False)
    database_status = db.Column(db.String(20), nullable=False)
    redis_status = db.Column(db.String(20), nullable=False)
    celery_status = db.Column(db.String(20), nullable=False)
    disk_usage = db.Column(db.Float, nullable=True)
    memory_usage = db.Column(db.Float, nullable=True)
    cpu_usage = db.Column(db.Float, nullable=True)
    details = db.Column(db.Text, nullable=True)

class PromoUsage(db.Model):
    __tablename__ = 'promo_usage'
    
    id = db.Column(db.Integer, primary_key=True)
    promo_code_id = db.Column(db.Integer, db.ForeignKey('promo_codes.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    applied_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)