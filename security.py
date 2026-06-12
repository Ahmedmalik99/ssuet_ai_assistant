"""
SSUET AI Assistant - Security Module
Handles: Rate Limiting, CSRF, Security Headers, OTP, Account Lockout, IP Blocking
"""
import os
import random
import string
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from functools import wraps
from datetime import datetime, timedelta

from flask import request, session, jsonify, abort
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import bleach

# ── RATE LIMITER (DoS/DDoS PROTECTION) ──
# Create the limiter instance (app will be initialized later via init_app)
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per minute", "1000 per hour"],
    storage_uri="memory://",
    strategy="fixed-window"
)

# ── CSRF PROTECTION ──
def generate_csrf_token():
    """Generate a CSRF token and store in session."""
    if '_csrf_token' not in session:
        session['_csrf_token'] = ''.join(random.choices(string.ascii_letters + string.digits, k=64))
    return session['_csrf_token']

def validate_csrf_token():
    """Validate CSRF token from request header or form data."""
    token = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token')
    if not token or token != session.get('_csrf_token'):
        abort(403, description="CSRF token missing or invalid")

def csrf_protect(f):
    """Decorator to enforce CSRF protection on POST/PUT/DELETE."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.method in ['POST', 'PUT', 'DELETE']:
            validate_csrf_token()
        return f(*args, **kwargs)
    return decorated

# ── SECURITY HEADERS MIDDLEWARE ──
def add_security_headers(response):
    """Add security headers to every response."""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(self), geolocation=()'
    # Only set HSTS in production
    if os.environ.get('ENVIRONMENT', 'development') == 'production':
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    # Basic CSP
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: https://upload.wikimedia.org; "
        "connect-src 'self'; "
        "frame-ancestors 'none';"
    )
    return response

# ── LOGIN REQUIRED DECORATOR ──
def login_required(f):
    """Decorator to require login for a route."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({"error": "Please login first"}), 401
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    """Decorator to require admin access."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({"error": "Please login first"}), 401
        admin_email = os.environ.get('ADMIN_EMAIL', 'admin@ssuet.edu.pk')
        if session.get('user_email') != admin_email:
            return jsonify({"error": "Unauthorized — admin access required"}), 403
        return f(*args, **kwargs)
    return decorated

# ── INPUT SANITIZATION ──
def sanitize_input(text):
    """Strip all HTML tags from user input to prevent XSS."""
    if not text:
        return text
    return bleach.clean(str(text), tags=[], strip=True).strip()

def sanitize_dict(data, fields):
    """Sanitize specific fields in a dict."""
    if not data:
        return data
    for field in fields:
        if field in data and isinstance(data[field], str):
            data[field] = sanitize_input(data[field])
    return data

# ── OTP EMAIL VERIFICATION ──
class OTPManager:
    """Handles OTP generation and email sending via Gmail SMTP."""
    
    def __init__(self):
        self.smtp_email = os.environ.get('SMTP_EMAIL', '')
        self.smtp_password = os.environ.get('SMTP_PASSWORD', '')
        self.smtp_server = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
        self.smtp_port = int(os.environ.get('SMTP_PORT', 587))
    
    def generate_otp(self):
        """Generate a 6-digit OTP code."""
        return ''.join(random.choices(string.digits, k=6))
    
    def send_otp_email(self, to_email, otp_code, user_name="User"):
        """Send OTP via Gmail SMTP. Returns (success: bool, error: str|None)."""
        if not self.smtp_email or not self.smtp_password:
            print("⚠️  SMTP not configured — OTP email cannot be sent")
            return False, "Email service not configured"
        
        try:
            msg = MIMEMultipart('alternative')
            msg['From'] = f'SSUET AI Assistant <{self.smtp_email}>'
            msg['To'] = to_email
            msg['Subject'] = f'🔐 SSUET AI — Your Verification Code: {otp_code}'
            
            html_body = f"""
            <div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 500px; margin: 0 auto; background: #f5f0fa; padding: 30px; border-radius: 16px;">
                <div style="text-align: center; margin-bottom: 24px;">
                    <div style="font-size: 40px;">🎓</div>
                    <h2 style="color: #6a0dad; margin: 8px 0 4px;">SSUET AI Assistant</h2>
                    <p style="color: #7a6a8a; font-size: 13px;">Email Verification</p>
                </div>
                <div style="background: white; padding: 24px; border-radius: 12px; text-align: center; border: 1.5px solid #e0d0f0;">
                    <p style="color: #1a0a2e; margin-bottom: 16px;">Hello <strong>{user_name}</strong>,</p>
                    <p style="color: #7a6a8a; font-size: 14px; margin-bottom: 20px;">Your verification code is:</p>
                    <div style="font-size: 36px; font-weight: 800; letter-spacing: 8px; color: #6a0dad; background: linear-gradient(135deg, #f5f0fa, #e8d5f5); padding: 16px 24px; border-radius: 12px; display: inline-block; margin-bottom: 20px;">
                        {otp_code}
                    </div>
                    <p style="color: #ef4444; font-size: 12px; margin-top: 8px;">⏱️ This code expires in 5 minutes</p>
                    <hr style="border: none; border-top: 1px solid #e0d0f0; margin: 20px 0;">
                    <p style="color: #7a6a8a; font-size: 11px;">If you didn't request this code, please ignore this email.</p>
                </div>
                <p style="text-align: center; color: #7a6a8a; font-size: 11px; margin-top: 16px;">Sir Syed University of Engineering & Technology, Karachi</p>
            </div>
            """
            
            msg.attach(MIMEText(html_body, 'html'))
            
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(self.smtp_email, self.smtp_password)
                server.sendmail(self.smtp_email, to_email, msg.as_string())
            
            print(f"✅ OTP email sent to {to_email}")
            return True, None
            
        except smtplib.SMTPAuthenticationError:
            print(f"❌ SMTP Auth failed — check SMTP_EMAIL and SMTP_PASSWORD in .env")
            return False, "Email authentication failed"
        except Exception as e:
            print(f"❌ Failed to send OTP email: {e}")
            return False, str(e)

otp_manager = OTPManager()

# ── ACCOUNT LOCKOUT ──
class AccountLockout:
    """Track failed login attempts and lock accounts after threshold."""
    
    MAX_ATTEMPTS = 5
    LOCKOUT_MINUTES = 15
    
    @staticmethod
    def record_failed_attempt(db_func, ip_address, email):
        """Record a failed login attempt. db_func should return a connection."""
        conn = db_func()
        if not conn:
            return
        try:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO login_attempts (ip_address, email, attempted_at) VALUES (%s, %s, NOW())",
                (ip_address, email)
            )
            conn.commit()
            cursor.close()
        except Exception as e:
            print(f"⚠️  Error recording login attempt: {e}")
        finally:
            conn.close()
    
    @staticmethod
    def clear_attempts(db_func, email):
        """Clear failed attempts after successful login."""
        conn = db_func()
        if not conn:
            return
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM login_attempts WHERE email = %s", (email,))
            conn.commit()
            cursor.close()
        except Exception as e:
            print(f"⚠️  Error clearing login attempts: {e}")
        finally:
            conn.close()
    
    @staticmethod
    def is_locked(db_func, email, ip_address):
        """Check if the account or IP is locked. Returns (locked: bool, minutes_remaining: int)."""
        conn = db_func()
        if not conn:
            return False, 0
        try:
            cursor = conn.cursor()
            window = datetime.now() - timedelta(minutes=AccountLockout.LOCKOUT_MINUTES)
            cursor.execute(
                "SELECT COUNT(*) as cnt, MAX(attempted_at) as last_attempt FROM login_attempts WHERE (email = %s OR ip_address = %s) AND attempted_at > %s",
                (email, ip_address, window)
            )
            row = cursor.fetchone()
            cursor.close()
            conn.close()
            
            if row and row[0] >= AccountLockout.MAX_ATTEMPTS:
                if row[1]:
                    unlock_time = row[1] + timedelta(minutes=AccountLockout.LOCKOUT_MINUTES)
                    remaining = (unlock_time - datetime.now()).total_seconds() / 60
                    return True, max(1, int(remaining))
                return True, AccountLockout.LOCKOUT_MINUTES
            return False, 0
        except Exception as e:
            print(f"⚠️  Error checking lockout: {e}")
            try:
                conn.close()
            except:
                pass
            return False, 0

    @staticmethod
    def get_recent_attempts(db_func, limit=50):
        """Get recent failed login attempts for admin dashboard."""
        conn = db_func()
        if not conn:
            return []
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT ip_address, email, attempted_at FROM login_attempts ORDER BY attempted_at DESC LIMIT %s",
                (limit,)
            )
            attempts = cursor.fetchall()
            cursor.close()
            conn.close()
            return attempts
        except Exception as e:
            print(f"⚠️  Error fetching login attempts: {e}")
            try:
                conn.close()
            except:
                pass
            return []

lockout = AccountLockout()

# ── IP BLOCKING ──
class IPBlocker:
    """Manage blocked IPs."""
    
    @staticmethod
    def is_blocked(db_func, ip_address):
        """Check if an IP is currently blocked."""
        conn = db_func()
        if not conn:
            return False
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM blocked_ips WHERE ip_address = %s AND (expires_at IS NULL OR expires_at > NOW())",
                (ip_address,)
            )
            result = cursor.fetchone()
            cursor.close()
            conn.close()
            return result is not None
        except Exception as e:
            print(f"⚠️  Error checking IP block: {e}")
            try:
                conn.close()
            except:
                pass
            return False
    
    @staticmethod
    def block_ip(db_func, ip_address, reason="Suspicious activity", duration_hours=24):
        """Block an IP address."""
        conn = db_func()
        if not conn:
            return
        try:
            cursor = conn.cursor()
            expires = datetime.now() + timedelta(hours=duration_hours)
            cursor.execute(
                "INSERT INTO blocked_ips (ip_address, reason, blocked_at, expires_at) VALUES (%s, %s, NOW(), %s) ON DUPLICATE KEY UPDATE reason=%s, expires_at=%s",
                (ip_address, reason, expires, reason, expires)
            )
            conn.commit()
            cursor.close()
            print(f"🚫 IP BLOCKED: {ip_address} — {reason}")
        except Exception as e:
            print(f"⚠️  Error blocking IP: {e}")
        finally:
            conn.close()
    
    @staticmethod
    def unblock_ip(db_func, ip_address):
        """Unblock an IP address."""
        conn = db_func()
        if not conn:
            return
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM blocked_ips WHERE ip_address = %s", (ip_address,))
            conn.commit()
            cursor.close()
        except Exception as e:
            print(f"⚠️  Error unblocking IP: {e}")
        finally:
            conn.close()
    
    @staticmethod
    def get_blocked_ips(db_func):
        """Get all currently blocked IPs for admin dashboard."""
        conn = db_func()
        if not conn:
            return []
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT ip_address, reason, blocked_at, expires_at FROM blocked_ips WHERE expires_at IS NULL OR expires_at > NOW() ORDER BY blocked_at DESC"
            )
            ips = cursor.fetchall()
            cursor.close()
            conn.close()
            return ips
        except Exception as e:
            print(f"⚠️  Error fetching blocked IPs: {e}")
            try:
                conn.close()
            except:
                pass
            return []

ip_blocker = IPBlocker()

# ── SESSION CONFIGURATION ──
def configure_session(app):
    """Apply security settings to Flask session."""
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)
    
    if os.environ.get('ENVIRONMENT', 'development') == 'production':
        app.config['SESSION_COOKIE_SECURE'] = True
    
    # Make sessions permanent so the timeout applies
    @app.before_request
    def make_session_permanent():
        session.permanent = True

def init_security(app):
    """Initialize all security features on the Flask app."""
    # Rate limiter
    limiter.init_app(app)
    
    # Session security
    configure_session(app)
    
    # Security headers on every response
    app.after_request(add_security_headers)
    
    # Make csrf_token available in all templates
    app.jinja_env.globals['csrf_token'] = generate_csrf_token
    
    print("🛡️  SECURITY MODULE INITIALIZED")
    print("   ✓ Rate Limiting (DoS/DDoS Protection)")
    print("   ✓ CSRF Protection")
    print("   ✓ Security Headers")
    print("   ✓ Session Hardening")
    print("   ✓ Input Sanitization")
    print("   ✓ OTP Email Verification")
    print("   ✓ Account Lockout")
    print("   ✓ IP Blocking")
