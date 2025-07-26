# app_extensions.py - FIXED VERSION
# Circular import diperbaiki dengan lazy import dan proper error handling

import os
import json
import logging
import subprocess
import uuid
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, render_template, redirect, url_for, current_app
from flask_login import login_required, current_user, login_user
import secrets
import hashlib
from sqlalchemy import and_, or_
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from werkzeug.security import check_password_hash

# Create Blueprint
extensions_bp = Blueprint('extensions', __name__)

# ===== HELPER FUNCTION TO GET DB AND MODELS (SOLUSI CIRCULAR IMPORT) =====
def get_db_and_models():
    """Lazy import untuk menghindari circular import"""
    from app_models import db, User, VideoProcess, VideoClip, Payment, CountdownSettings, PromoCode, SystemHealth, PromoUsage
    return db, User, VideoProcess, VideoClip, Payment, CountdownSettings, PromoCode, SystemHealth, PromoUsage

# ===== COUNTDOWN ROUTES =====
@extensions_bp.route('/api/countdown/settings', methods=['GET'])
@login_required
def get_countdown_settings():
    """Get countdown settings (admin only)"""
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        db, User, VideoProcess, VideoClip, Payment, CountdownSettings, PromoCode, SystemHealth, PromoUsage = get_db_and_models()
        countdown = CountdownSettings.get_current()
        return jsonify({
            'is_active': countdown.is_active,
            'target_datetime': countdown.target_datetime.isoformat() if countdown.target_datetime else None,
            'title': countdown.title,
            'subtitle': countdown.subtitle,
            'background_style': countdown.background_style,
            'redirect_after_launch': countdown.redirect_after_launch
        })
    except Exception as e:
        current_app.logger.error(f"Error getting countdown settings: {str(e)}")
        return jsonify({'error': 'Failed to get countdown settings'}), 500

@extensions_bp.route('/api/countdown/settings', methods=['POST'])
@login_required
def update_countdown_settings():
    """Update countdown settings (admin only)"""
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        db, User, VideoProcess, VideoClip, Payment, CountdownSettings, PromoCode, SystemHealth, PromoUsage = get_db_and_models()
        
        data = request.json
        countdown = CountdownSettings.get_current()
        
        if not countdown.id:
            db.session.add(countdown)
        
        countdown.is_active = data.get('is_active', countdown.is_active)
        countdown.title = data.get('title', countdown.title)
        countdown.subtitle = data.get('subtitle', countdown.subtitle)
        countdown.background_style = data.get('background_style', countdown.background_style)
        countdown.redirect_after_launch = data.get('redirect_after_launch', countdown.redirect_after_launch)
        
        if data.get('target_datetime'):
            countdown.target_datetime = datetime.fromisoformat(data['target_datetime'].replace('Z', '+00:00'))
        
        countdown.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Countdown settings updated'})
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating countdown: {str(e)}")
        return jsonify({'error': 'Failed to update countdown settings'}), 500

@extensions_bp.route('/api/countdown/status', methods=['GET'])
def get_countdown_status():
    """Get current countdown status"""
    try:
        db, User, VideoProcess, VideoClip, Payment, CountdownSettings, PromoCode, SystemHealth, PromoUsage = get_db_and_models()
        
        countdown = CountdownSettings.get_current()
        
        if not countdown.is_active:
            return jsonify({'active': False})
        
        if countdown.is_launch_time_passed():
            return jsonify({'active': False, 'launched': True})
        
        return jsonify({
            'active': True,
            'target_datetime': countdown.target_datetime.isoformat() if countdown.target_datetime else None,
            'title': countdown.title,
            'subtitle': countdown.subtitle,
            'background_style': countdown.background_style
        })
    except Exception as e:
        current_app.logger.error(f"Error getting countdown status: {str(e)}")
        return jsonify({'error': 'Failed to get countdown status'}), 500

# ===== PROMO CODE ROUTES =====
@extensions_bp.route('/api/promo/codes', methods=['GET'])
@login_required
def get_promo_codes():
    """Get all promo codes (admin only)"""
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        db, User, VideoProcess, VideoClip, Payment, CountdownSettings, PromoCode, SystemHealth, PromoUsage = get_db_and_models()
        
        codes = PromoCode.query.order_by(PromoCode.created_at.desc()).all()
        
        return jsonify({
            'codes': [{
                'id': code.id,
                'code': code.code,
                'description': code.description,
                'discount_type': code.discount_type,
                'discount_value': code.discount_value,
                'max_uses': code.max_uses,
                'used_count': code.used_count,
                'is_active': code.is_active,
                'expires_at': code.expires_at.isoformat() if code.expires_at else None,
                'created_at': code.created_at.isoformat()
            } for code in codes]
        })
    except Exception as e:
        current_app.logger.error(f"Error getting promo codes: {str(e)}")
        return jsonify({'error': 'Failed to get promo codes'}), 500

@extensions_bp.route('/api/promo/codes', methods=['POST'])
@login_required
def create_promo_code():
    """Create new promo code (admin only)"""
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        db, User, VideoProcess, VideoClip, Payment, CountdownSettings, PromoCode, SystemHealth, PromoUsage = get_db_and_models()
        
        data = request.json
        
        # Validate required fields
        required_fields = ['code', 'description', 'discount_type', 'discount_value']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing field: {field}'}), 400
        
        # Check if code already exists
        existing = PromoCode.query.filter_by(code=data['code'].upper()).first()
        if existing:
            return jsonify({'error': 'Promo code already exists'}), 400
        
        promo_code = PromoCode(
            code=data['code'].upper(),
            description=data['description'],
            discount_type=data['discount_type'],
            discount_value=float(data['discount_value']),
            max_uses=int(data.get('max_uses', 100)),
            created_by=current_user.id
        )
        
        if data.get('expires_at'):
            promo_code.expires_at = datetime.fromisoformat(data['expires_at'].replace('Z', '+00:00'))
        
        db.session.add(promo_code)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Promo code created'})
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creating promo code: {str(e)}")
        return jsonify({'error': 'Failed to create promo code'}), 500

@extensions_bp.route('/api/promo/codes/<int:code_id>', methods=['DELETE'])
@login_required
def delete_promo_code(code_id):
    """Delete promo code (admin only)"""
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        db, User, VideoProcess, VideoClip, Payment, CountdownSettings, PromoCode, SystemHealth, PromoUsage = get_db_and_models()
        
        promo_code = PromoCode.query.get_or_404(code_id)
        db.session.delete(promo_code)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Promo code deleted'})
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting promo code: {str(e)}")
        return jsonify({'error': 'Failed to delete promo code'}), 500

# ===== SYSTEM HEALTH & MANAGEMENT ROUTES =====
@extensions_bp.route('/api/system/health', methods=['GET'])
@login_required
def get_system_health():
    """Get system health status (admin only)"""
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        db, User, VideoProcess, VideoClip, Payment, CountdownSettings, PromoCode, SystemHealth, PromoUsage = get_db_and_models()
        
        health_data = {
            'timestamp': datetime.utcnow().isoformat(),
            'database': {'status': 'healthy'},
            'redis': {'status': 'unknown'},
            'celery': {'status': 'unknown'},
            'overall': 'healthy'
        }
        
        # Test database
        try:
            db.engine.execute('SELECT 1')
            health_data['database']['status'] = 'healthy'
        except Exception as e:
            health_data['database']['status'] = 'unhealthy'
            health_data['database']['error'] = str(e)
            health_data['overall'] = 'unhealthy'
        
        # Test Redis
        try:
            import redis
            redis_client = redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379/0'))
            redis_client.ping()
            health_data['redis']['status'] = 'healthy'
        except Exception as e:
            health_data['redis']['status'] = 'unhealthy'
            health_data['redis']['error'] = str(e)
        
        # Test Celery
        try:
            result = subprocess.run(['systemctl', 'is-active', 'askaraai-celery'], 
                                  capture_output=True, text=True, timeout=5)
            if result.stdout.strip() == 'active':
                health_data['celery']['status'] = 'healthy'
            else:
                health_data['celery']['status'] = 'unhealthy'
        except Exception as e:
            health_data['celery']['status'] = 'unknown'
            health_data['celery']['error'] = str(e)
        
        return jsonify(health_data)
        
    except Exception as e:
        current_app.logger.error(f"Error checking system health: {str(e)}")
        return jsonify({'error': 'Failed to check system health'}), 500

@extensions_bp.route('/api/system/stats', methods=['GET'])
@login_required
def get_system_stats():
    """Get system statistics (admin only)"""
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        db, User, VideoProcess, VideoClip, Payment, CountdownSettings, PromoCode, SystemHealth, PromoUsage = get_db_and_models()
        
        # User statistics
        total_users = User.query.count()
        premium_users = User.query.filter_by(is_premium=True).count()
        new_users_30d = User.query.filter(
            User.created_at >= datetime.utcnow() - timedelta(days=30)
        ).count()
        
        # Video statistics
        total_videos = VideoProcess.query.count()
        completed_videos = VideoProcess.query.filter_by(status='completed').count()
        total_clips = db.session.query(db.func.sum(VideoProcess.clips_generated)).scalar() or 0
        
        stats = {
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
            }
        }
        
        return jsonify(stats)
        
    except Exception as e:
        current_app.logger.error(f"Error getting system stats: {str(e)}")
        return jsonify({'error': 'Failed to get system stats'}), 500

@extensions_bp.route('/api/system/restart-services', methods=['POST'])
@login_required
def restart_services():
    """Restart application services (admin only)"""
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        services = ['askaraai', 'askaraai-celery', 'askaraai-celery-beat']
        results = {}
        
        for service in services:
            try:
                result = subprocess.run(['sudo', 'systemctl', 'restart', service], 
                                      check=True, 
                                      capture_output=True,
                                      timeout=30)
                results[service] = 'restarted'
            except subprocess.CalledProcessError as e:
                results[service] = f'failed: {e.stderr.decode()}'
            except subprocess.TimeoutExpired:
                results[service] = 'timeout'
        
        current_app.logger.info(f"Services restart initiated by admin: {current_user.email}")
        
        return jsonify({
            'success': True,
            'message': 'Services restart initiated',
            'results': results
        })
        
    except Exception as e:
        current_app.logger.error(f"Error restarting services: {str(e)}")
        return jsonify({'error': 'Failed to restart services'}), 500

@extensions_bp.route('/api/system/reboot', methods=['POST'])
@login_required
def reboot_server():
    """Reboot server (admin only)"""
    if not current_user.is_admin or current_user.email != 'ujangbawbaw@gmail.com':
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        # Schedule reboot in 1 minute
        subprocess.Popen(['sudo', 'shutdown', '-r', '+1'], 
                        stdout=subprocess.DEVNULL, 
                        stderr=subprocess.DEVNULL)
        
        current_app.logger.warning(f"Server reboot initiated by admin: {current_user.email}")
        
        return jsonify({
            'success': True, 
            'message': 'Server will reboot in 1 minute. Please wait 2-3 minutes before accessing again.'
        })
        
    except Exception as e:
        current_app.logger.error(f"Error rebooting server: {str(e)}")
        return jsonify({'error': 'Failed to reboot server'}), 500

# ===== FUNCTION TO REGISTER BLUEPRINT =====
def register_extensions(app):
    """Register the extensions blueprint with the app"""
    app.register_blueprint(extensions_bp)
    
    # Initialize new tables if needed
    with app.app_context():
        try:
            db, User, VideoProcess, VideoClip, Payment, CountdownSettings, PromoCode, SystemHealth, PromoUsage = get_db_and_models()
            db.create_all()
            print("✅ Extension tables created/verified")
        except Exception as e:
            print(f"❌ Error creating extension tables: {str(e)}")

# ===== INITIALIZATION =====
def init_extensions():
    """Initialize extension-specific data"""
    try:
        db, User, VideoProcess, VideoClip, Payment, CountdownSettings, PromoCode, SystemHealth, PromoUsage = get_db_and_models()
        
        # Create default countdown settings if not exists
        existing_countdown = CountdownSettings.query.first()
        if not existing_countdown:
            default_countdown = CountdownSettings(
                is_active=False,
                title="AskaraAI Launching Soon!",
                subtitle="AI-powered video clipper coming soon",
                background_style="gradient",
                redirect_after_launch="/"
            )
            db.session.add(default_countdown)
            db.session.commit()
            print("✅ Default countdown settings created!")
        
        return True
    except Exception as e:
        print(f"❌ Error initializing extensions: {str(e)}")
        return False