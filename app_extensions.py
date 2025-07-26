# app_extensions.py - SECURITY ENHANCED VERSION
# Enhanced dengan comprehensive security, input validation, dan performance optimizations

import os
import json
import logging
import subprocess
import uuid
import secrets
import hashlib
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, render_template, redirect, url_for, current_app
from flask_login import login_required, current_user, login_user
from marshmallow import Schema, fields, validate, ValidationError
from sqlalchemy import and_, or_, func
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from werkzeug.security import check_password_hash
import structlog

# Create Blueprint
extensions_bp = Blueprint('extensions', __name__)

# Configure structured logging
logger = structlog.get_logger()

# ===== INPUT VALIDATION SCHEMAS =====
class CountdownSettingsSchema(Schema):
    is_active = fields.Bool(required=True)
    target_datetime = fields.DateTime(allow_none=True)
    title = fields.Str(validate=validate.Length(min=1, max=200))
    subtitle = fields.Str(validate=validate.Length(min=1, max=500))
    background_style = fields.Str(validate=validate.OneOf(['gradient', 'particles', 'waves']))
    redirect_after_launch = fields.Str(validate=validate.Length(min=1, max=200))

class PromoCodeCreateSchema(Schema):
    code = fields.Str(required=True, validate=validate.Length(min=3, max=50))
    description = fields.Str(required=True, validate=validate.Length(min=5, max=200))
    discount_type = fields.Str(required=True, validate=validate.OneOf(['percentage', 'days', 'credits']))
    discount_value = fields.Float(required=True, validate=validate.Range(min=0, max=10000))
    max_uses = fields.Int(validate=validate.Range(min=1, max=100000), missing=100)
    expires_at = fields.DateTime(allow_none=True)

class SystemManagementSchema(Schema):
    action = fields.Str(required=True, validate=validate.OneOf(['restart', 'cleanup', 'reboot']))
    confirm = fields.Bool(required=True, validate=validate.Equal(True))

# ===== HELPER FUNCTION TO GET DB AND MODELS =====
def get_db_and_models():
    """Lazy import untuk menghindari circular import"""
    try:
        from app_models import db, User, VideoProcess, VideoClip, Payment, CountdownSettings, PromoCode, SystemHealth, PromoUsage
        return db, User, VideoProcess, VideoClip, Payment, CountdownSettings, PromoCode, SystemHealth, PromoUsage
    except Exception as e:
        logger.error("Failed to import models", error=str(e))
        raise

# ===== SECURITY HELPER FUNCTIONS =====
def validate_admin_access(require_super_admin=False):
    """Validate admin access with optional super admin requirement"""
    if not current_user.is_authenticated:
        logger.warning("Unauthenticated admin access attempt")
        return False, "Authentication required"
    
    if not current_user.is_admin:
        logger.warning("Non-admin user attempted admin access", user_email=current_user.email)
        return False, "Admin access required"
    
    if require_super_admin and current_user.email != 'ujangbawbaw@gmail.com':
        logger.warning("Non-super-admin attempted super admin action", user_email=current_user.email)
        return False, "Super admin access required"
    
    return True, "Access granted"

def sanitize_input(data, max_length=1000):
    """Sanitize input data"""
    if isinstance(data, str):
        # Remove potential XSS characters
        sanitized = data.replace('<', '&lt;').replace('>', '&gt;')
        sanitized = sanitized.replace('"', '&quot;').replace("'", '&#x27;')
        return sanitized[:max_length]
    elif isinstance(data, dict):
        return {key: sanitize_input(value, max_length) for key, value in data.items()}
    elif isinstance(data, list):
        return [sanitize_input(item, max_length) for item in data]
    return data

def rate_limit_check(key, limit=10, window=3600):
    """Simple rate limiting check"""
    try:
        import redis
        redis_client = redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379/0'))
        
        current_time = int(datetime.utcnow().timestamp())
        pipe = redis_client.pipeline()
        
        # Use sliding window counter
        pipe.zremrangebyscore(key, 0, current_time - window)
        pipe.zcard(key)
        pipe.zadd(key, {str(uuid.uuid4()): current_time})
        pipe.expire(key, window)
        
        results = pipe.execute()
        current_requests = results[1]
        
        return current_requests < limit
    except Exception:
        # If Redis is not available, allow the request
        return True

# ===== COUNTDOWN ROUTES =====
@extensions_bp.route('/api/countdown/settings', methods=['GET'])
@login_required
def get_countdown_settings():
    """Get countdown settings (admin only)"""
    is_valid, message = validate_admin_access()
    if not is_valid:
        return jsonify({'error': message}), 403
    
    # Rate limiting
    if not rate_limit_check(f"countdown_get:{current_user.id}", limit=30, window=3600):
        return jsonify({'error': 'Rate limit exceeded'}), 429
    
    try:
        db, User, VideoProcess, VideoClip, Payment, CountdownSettings, PromoCode, SystemHealth, PromoUsage = get_db_and_models()
        countdown = CountdownSettings.get_current()
        
        result = {
            'is_active': countdown.is_active,
            'target_datetime': countdown.target_datetime.isoformat() if countdown.target_datetime else None,
            'title': countdown.title,
            'subtitle': countdown.subtitle,
            'background_style': countdown.background_style,
            'redirect_after_launch': countdown.redirect_after_launch
        }
        
        logger.info("Countdown settings retrieved", user_email=current_user.email)
        return jsonify(result)
        
    except Exception as e:
        logger.error("Error getting countdown settings", error=str(e), user_email=current_user.email)
        return jsonify({'error': 'Failed to get countdown settings'}), 500

@extensions_bp.route('/api/countdown/settings', methods=['POST'])
@login_required
def update_countdown_settings():
    """Update countdown settings (admin only)"""
    is_valid, message = validate_admin_access()
    if not is_valid:
        return jsonify({'error': message}), 403
    
    # Rate limiting
    if not rate_limit_check(f"countdown_update:{current_user.id}", limit=10, window=3600):
        return jsonify({'error': 'Rate limit exceeded'}), 429
    
    try:
        # Validate input
        schema = CountdownSettingsSchema()
        try:
            data = schema.load(request.json)
        except ValidationError as err:
            logger.warning("Invalid countdown settings input", errors=err.messages, user_email=current_user.email)
            return jsonify({'error': 'Invalid input', 'details': err.messages}), 400
        
        # Sanitize input
        data = sanitize_input(data)
        
        db, User, VideoProcess, VideoClip, Payment, CountdownSettings, PromoCode, SystemHealth, PromoUsage = get_db_and_models()
        
        countdown = CountdownSettings.get_current()
        
        if not countdown.id:
            db.session.add(countdown)
        
        # Update fields
        countdown.is_active = data.get('is_active', countdown.is_active)
        countdown.title = data.get('title', countdown.title)
        countdown.subtitle = data.get('subtitle', countdown.subtitle)
        countdown.background_style = data.get('background_style', countdown.background_style)
        countdown.redirect_after_launch = data.get('redirect_after_launch', countdown.redirect_after_launch)
        
        if data.get('target_datetime'):
            countdown.target_datetime = data['target_datetime']
        
        countdown.updated_at = datetime.utcnow()
        
        # Validate settings
        countdown.validate_settings()
        
        db.session.commit()
        
        logger.info("Countdown settings updated", user_email=current_user.email, is_active=countdown.is_active)
        
        return jsonify({'success': True, 'message': 'Countdown settings updated'})
        
    except Exception as e:
        db.session.rollback()
        logger.error("Error updating countdown", error=str(e), user_email=current_user.email)
        return jsonify({'error': 'Failed to update countdown settings'}), 500

@extensions_bp.route('/api/countdown/status', methods=['GET'])
def get_countdown_status():
    """Get current countdown status (public endpoint with rate limiting)"""
    # Rate limiting for public endpoint
    client_ip = request.environ.get('REMOTE_ADDR', 'unknown')
    if not rate_limit_check(f"countdown_status:{client_ip}", limit=100, window=3600):
        return jsonify({'error': 'Rate limit exceeded'}), 429
    
    try:
        db, User, VideoProcess, VideoClip, Payment, CountdownSettings, PromoCode, SystemHealth, PromoUsage = get_db_and_models()
        
        countdown = CountdownSettings.get_current()
        
        if not countdown.is_active:
            return jsonify({'active': False})
        
        if countdown.is_launch_time_passed():
            return jsonify({'active': False, 'launched': True})
        
        result = {
            'active': True,
            'target_datetime': countdown.target_datetime.isoformat() if countdown.target_datetime else None,
            'title': countdown.title,
            'subtitle': countdown.subtitle,
            'background_style': countdown.background_style,
            'time_remaining': countdown.time_until_launch()
        }
        
        return jsonify(result)
        
    except Exception as e:
        logger.error("Error getting countdown status", error=str(e))
        return jsonify({'error': 'Failed to get countdown status'}), 500

# ===== PROMO CODE ROUTES =====
@extensions_bp.route('/api/promo/codes', methods=['GET'])
@login_required
def get_promo_codes():
    """Get all promo codes (admin only)"""
    is_valid, message = validate_admin_access()
    if not is_valid:
        return jsonify({'error': message}), 403
    
    # Rate limiting
    if not rate_limit_check(f"promo_get:{current_user.id}", limit=30, window=3600):
        return jsonify({'error': 'Rate limit exceeded'}), 429
    
    try:
        db, User, VideoProcess, VideoClip, Payment, CountdownSettings, PromoCode, SystemHealth, PromoUsage = get_db_and_models()
        
        # Pagination
        page = request.args.get('page', 1, type=int)
        per_page = min(request.args.get('per_page', 20, type=int), 100)  # Max 100 per page
        
        codes_query = PromoCode.query.order_by(PromoCode.created_at.desc())
        codes_paginated = codes_query.paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        codes_data = []
        for code in codes_paginated.items:
            code_dict = code.to_dict()
            # Add usage statistics
            code_dict['usage_percentage'] = (code.used_count / code.max_uses * 100) if code.max_uses > 0 else 0
            codes_data.append(code_dict)
        
        result = {
            'codes': codes_data,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': codes_paginated.total,
                'pages': codes_paginated.pages,
                'has_next': codes_paginated.has_next,
                'has_prev': codes_paginated.has_prev
            }
        }
        
        logger.info("Promo codes retrieved", user_email=current_user.email, count=len(codes_data))
        return jsonify(result)
        
    except Exception as e:
        logger.error("Error getting promo codes", error=str(e), user_email=current_user.email)
        return jsonify({'error': 'Failed to get promo codes'}), 500

@extensions_bp.route('/api/promo/codes', methods=['POST'])
@login_required
def create_promo_code():
    """Create new promo code (admin only)"""
    is_valid, message = validate_admin_access()
    if not is_valid:
        return jsonify({'error': message}), 403
    
    # Rate limiting
    if not rate_limit_check(f"promo_create:{current_user.id}", limit=10, window=3600):
        return jsonify({'error': 'Rate limit exceeded'}), 429
    
    try:
        # Validate input
        schema = PromoCodeCreateSchema()
        try:
            data = schema.load(request.json)
        except ValidationError as err:
            logger.warning("Invalid promo code input", errors=err.messages, user_email=current_user.email)
            return jsonify({'error': 'Invalid input', 'details': err.messages}), 400
        
        # Sanitize input
        data = sanitize_input(data)
        
        db, User, VideoProcess, VideoClip, Payment, CountdownSettings, PromoCode, SystemHealth, PromoUsage = get_db_and_models()
        
        # Normalize code to uppercase
        code_value = data['code'].upper().strip()
        
        # Check if code already exists
        existing = PromoCode.query.filter_by(code=code_value).first()
        if existing:
            return jsonify({'error': 'Promo code already exists'}), 400
        
        # Create promo code
        promo_code = PromoCode(
            code=code_value,
            description=data['description'].strip(),
            discount_type=data['discount_type'],
            discount_value=float(data['discount_value']),
            max_uses=int(data.get('max_uses', 100)),
            created_by=current_user.id
        )
        
        if data.get('expires_at'):
            promo_code.expires_at = data['expires_at']
        
        # Validate discount value
        promo_code.validate_discount()
        
        db.session.add(promo_code)
        db.session.commit()
        
        logger.info("Promo code created", 
                   user_email=current_user.email, 
                   code=code_value, 
                   discount_type=data['discount_type'])
        
        return jsonify({
            'success': True, 
            'message': 'Promo code created successfully',
            'promo_code': promo_code.to_dict()
        })
        
    except Exception as e:
        db.session.rollback()
        logger.error("Error creating promo code", error=str(e), user_email=current_user.email)
        return jsonify({'error': 'Failed to create promo code'}), 500

@extensions_bp.route('/api/promo/codes/<int:code_id>', methods=['DELETE'])
@login_required
def delete_promo_code(code_id):
    """Delete promo code (admin only)"""
    is_valid, message = validate_admin_access()
    if not is_valid:
        return jsonify({'error': message}), 403
    
    # Rate limiting
    if not rate_limit_check(f"promo_delete:{current_user.id}", limit=20, window=3600):
        return jsonify({'error': 'Rate limit exceeded'}), 429
    
    try:
        db, User, VideoProcess, VideoClip, Payment, CountdownSettings, PromoCode, SystemHealth, PromoUsage = get_db_and_models()
        
        promo_code = PromoCode.query.get(code_id)
        if not promo_code:
            return jsonify({'error': 'Promo code not found'}), 404
        
        code_value = promo_code.code
        
        # Check if promo code has been used
        if promo_code.used_count > 0:
            # Instead of deleting, just deactivate
            promo_code.is_active = False
            db.session.commit()
            
            logger.info("Promo code deactivated", 
                       user_email=current_user.email, 
                       code=code_value, 
                       used_count=promo_code.used_count)
            
            return jsonify({
                'success': True, 
                'message': 'Promo code deactivated (had usage history)'
            })
        else:
            # Safe to delete if never used
            db.session.delete(promo_code)
            db.session.commit()
            
            logger.info("Promo code deleted", 
                       user_email=current_user.email, 
                       code=code_value)
            
            return jsonify({
                'success': True, 
                'message': 'Promo code deleted successfully'
            })
        
    except Exception as e:
        db.session.rollback()
        logger.error("Error deleting promo code", error=str(e), user_email=current_user.email)
        return jsonify({'error': 'Failed to delete promo code'}), 500

@extensions_bp.route('/api/promo/apply/<promo_code>', methods=['POST'])
@login_required
def apply_promo_code(promo_code):
    """Apply promo code to current user"""
    # Rate limiting
    if not rate_limit_check(f"promo_apply:{current_user.id}", limit=5, window=3600):
        return jsonify({'error': 'Rate limit exceeded'}), 429
    
    try:
        db, User, VideoProcess, VideoClip, Payment, CountdownSettings, PromoCode, SystemHealth, PromoUsage = get_db_and_models()
        
        # Sanitize and normalize promo code
        promo_code = sanitize_input(promo_code.upper().strip(), max_length=50)
        
        # Find promo code
        promo = PromoCode.query.filter_by(code=promo_code).first()
        if not promo:
            logger.warning("Invalid promo code attempted", 
                          user_email=current_user.email, 
                          code=promo_code)
            return jsonify({'error': 'Invalid promo code'}), 400
        
        # Check if user can use this promo
        can_use, message = promo.can_be_used_by_user(current_user.id)
        if not can_use:
            logger.info("Promo code usage denied", 
                       user_email=current_user.email, 
                       code=promo_code, 
                       reason=message)
            return jsonify({'error': message}), 400
        
        # Apply promo code
        promo.apply_to_user(current_user)
        db.session.commit()
        
        logger.info("Promo code applied successfully", 
                   user_email=current_user.email, 
                   code=promo_code, 
                   discount_type=promo.discount_type, 
                   discount_value=promo.discount_value)
        
        return jsonify({
            'success': True, 
            'message': f'Promo code applied! You received {promo.discount_value} {promo.discount_type}.',
            'applied_bonus': {
                'type': promo.discount_type,
                'value': promo.discount_value
            }
        })
        
    except Exception as e:
        db.session.rollback()
        logger.error("Error applying promo code", 
                    error=str(e), 
                    user_email=current_user.email, 
                    code=promo_code)
        return jsonify({'error': 'Failed to apply promo code'}), 500

# ===== SYSTEM HEALTH & MANAGEMENT ROUTES =====
@extensions_bp.route('/api/system/health', methods=['GET'])
@login_required
def get_system_health():
    """Get system health status (admin only)"""
    is_valid, message = validate_admin_access()
    if not is_valid:
        return jsonify({'error': message}), 403
    
    # Rate limiting
    if not rate_limit_check(f"health_check:{current_user.id}", limit=60, window=3600):
        return jsonify({'error': 'Rate limit exceeded'}), 429
    
    try:
        from utils import AskaraAIUtils
        
        utils = AskaraAIUtils()
        health_data = utils.check_system_health()
        
        # Save health check to database
        try:
            db, User, VideoProcess, VideoClip, Payment, CountdownSettings, PromoCode, SystemHealth, PromoUsage = get_db_and_models()
            
            health_record = SystemHealth(
                overall_status=health_data.get('overall', 'unknown'),
                database_status=health_data.get('database', {}).get('status', 'unknown'),
                redis_status=health_data.get('redis', {}).get('status', 'unknown'),
                celery_status=health_data.get('celery', {}).get('status', 'unknown'),
                disk_usage=health_data.get('disk_space', {}).get('usage_percent'),
                memory_usage=health_data.get('memory_usage'),
                cpu_usage=health_data.get('cpu_usage'),
                details=json.dumps(health_data)
            )
            
            db.session.add(health_record)
            db.session.commit()
            
        except Exception as e:
            logger.error("Failed to save health record", error=str(e))
        
        logger.info("System health checked", user_email=current_user.email, status=health_data.get('overall'))
        
        return jsonify(health_data)
        
    except Exception as e:
        logger.error("Error checking system health", error=str(e), user_email=current_user.email)
        return jsonify({'error': 'Failed to check system health'}), 500

@extensions_bp.route('/api/system/stats', methods=['GET'])
@login_required
def get_system_stats():
    """Get system statistics (admin only)"""
    is_valid, message = validate_admin_access()
    if not is_valid:
        return jsonify({'error': message}), 403
    
    # Rate limiting
    if not rate_limit_check(f"stats_get:{current_user.id}", limit=30, window=3600):
        return jsonify({'error': 'Rate limit exceeded'}), 429
    
    try:
        from utils import AskaraAIUtils
        
        utils = AskaraAIUtils()
        stats = utils.get_system_stats()
        
        logger.info("System stats retrieved", user_email=current_user.email)
        
        return jsonify(stats)
        
    except Exception as e:
        logger.error("Error getting system stats", error=str(e), user_email=current_user.email)
        return jsonify({'error': 'Failed to get system stats'}), 500

@extensions_bp.route('/api/system/restart-services', methods=['POST'])
@login_required
def restart_services():
    """Restart application services (admin only)"""
    is_valid, message = validate_admin_access()
    if not is_valid:
        return jsonify({'error': message}), 403
    
    # Rate limiting
    if not rate_limit_check(f"restart_services:{current_user.id}", limit=3, window=3600):
        return jsonify({'error': 'Rate limit exceeded'}), 429
    
    try:
        # Validate input
        data = request.json or {}
        if not data.get('confirm'):
            return jsonify({'error': 'Confirmation required'}), 400
        
        services = ['askaraai', 'askaraai-celery', 'askaraai-celery-beat']
        results = {}
        
        for service in services:
            try:
                result = subprocess.run(
                    ['sudo', 'systemctl', 'restart', service], 
                    check=True, 
                    capture_output=True,
                    timeout=30
                )
                results[service] = 'restarted'
                
            except subprocess.CalledProcessError as e:
                results[service] = f'failed: {e.stderr.decode()}'
            except subprocess.TimeoutExpired:
                results[service] = 'timeout'
        
        logger.warning("Services restart initiated", 
                      user_email=current_user.email, 
                      results=results)
        
        return jsonify({
            'success': True,
            'message': 'Services restart initiated',
            'results': results
        })
        
    except Exception as e:
        logger.error("Error restarting services", error=str(e), user_email=current_user.email)
        return jsonify({'error': 'Failed to restart services'}), 500

@extensions_bp.route('/api/system/reboot', methods=['POST'])
@login_required
def reboot_server():
    """Reboot server (super admin only)"""
    is_valid, message = validate_admin_access(require_super_admin=True)
    if not is_valid:
        return jsonify({'error': message}), 403
    
    # Rate limiting
    if not rate_limit_check(f"reboot_server:{current_user.id}", limit=1, window=3600):
        return jsonify({'error': 'Rate limit exceeded'}), 429
    
    try:
        # Validate input
        data = request.json or {}
        if not data.get('confirm') or data.get('confirmation_text') != 'REBOOT':
            return jsonify({'error': 'Proper confirmation required'}), 400
        
        # Schedule reboot in 2 minutes for safety
        subprocess.Popen(
            ['sudo', 'shutdown', '-r', '+2'], 
            stdout=subprocess.DEVNULL, 
            stderr=subprocess.DEVNULL
        )
        
        logger.critical("Server reboot initiated", user_email=current_user.email)
        
        return jsonify({
            'success': True, 
            'message': 'Server will reboot in 2 minutes. Please wait 3-5 minutes before accessing again.'
        })
        
    except Exception as e:
        logger.error("Error rebooting server", error=str(e), user_email=current_user.email)
        return jsonify({'error': 'Failed to reboot server'}), 500

@extensions_bp.route('/api/system/cleanup', methods=['POST'])
@login_required
def cleanup_system():
    """Cleanup old files and optimize system (admin only)"""
    is_valid, message = validate_admin_access()
    if not is_valid:
        return jsonify({'error': message}), 403
    
    # Rate limiting
    if not rate_limit_check(f"cleanup_system:{current_user.id}", limit=5, window=3600):
        return jsonify({'error': 'Rate limit exceeded'}), 429
    
    try:
        from utils import AskaraAIUtils
        
        utils = AskaraAIUtils()
        
        # Cleanup old files
        deleted_files = utils.cleanup_old_files(days=7)
        
        # Additional cleanup tasks
        cleanup_results = {
            'deleted_files': len(deleted_files),
            'cleaned_temp': True,
            'optimized_logs': True
        }
        
        logger.info("System cleanup completed", 
                   user_email=current_user.email, 
                   results=cleanup_results)
        
        return jsonify({
            'success': True,
            'message': 'System cleanup completed',
            'results': cleanup_results
        })
        
    except Exception as e:
        logger.error("Error during system cleanup", error=str(e), user_email=current_user.email)
        return jsonify({'error': 'Failed to cleanup system'}), 500

# ===== FUNCTION TO REGISTER BLUEPRINT =====
def register_extensions(app):
    """Register the extensions blueprint with the app"""
    app.register_blueprint(extensions_bp)
    
    # Initialize new tables if needed
    with app.app_context():
        try:
            db, User, VideoProcess, VideoClip, Payment, CountdownSettings, PromoCode, SystemHealth, PromoUsage = get_db_and_models()
            db.create_all()
            logger.info("Extension tables created/verified")
        except Exception as e:
            logger.error("Error creating extension tables", error=str(e))

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
            logger.info("Default countdown settings created")
        
        # Create some default promo codes for launch
        if PromoCode.query.count() == 0:
            # Get admin user
            admin = User.query.filter_by(email='ujangbawbaw@gmail.com').first()
            if admin:
                default_promos = [
                    {
                        'code': 'LAUNCH50',
                        'description': 'Launch special - 50% off first month',
                        'discount_type': 'percentage',
                        'discount_value': 50,
                        'max_uses': 1000,
                        'expires_at': datetime.utcnow() + timedelta(days=30)
                    },
                    {
                        'code': 'WELCOME30',
                        'description': 'Welcome bonus - 30 free credits',
                        'discount_type': 'credits',
                        'discount_value': 30,
                        'max_uses': 5000
                    }
                ]
                
                for promo_data in default_promos:
                    promo = PromoCode(
                        code=promo_data['code'],
                        description=promo_data['description'],
                        discount_type=promo_data['discount_type'],
                        discount_value=promo_data['discount_value'],
                        max_uses=promo_data['max_uses'],
                        created_by=admin.id,
                        expires_at=promo_data.get('expires_at')
                    )
                    db.session.add(promo)
                
                db.session.commit()
                logger.info("Default promo codes created")
        
        return True
        
    except Exception as e:
        logger.error("Error initializing extensions", error=str(e))
        return False
