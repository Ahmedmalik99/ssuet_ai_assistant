from flask import Flask, render_template, request, jsonify, send_from_directory, session, redirect, url_for, abort
from flask_cors import CORS
import requests
import mysql.connector
from mysql.connector import Error as MySQLError
import bcrypt
import os
import sys
import time
import json
from datetime import datetime
from dotenv import load_dotenv

# ── LOAD ENVIRONMENT VARIABLES ──
load_dotenv()

# ── RAG IMPORT ────────────────────────────────────────
try:
    from rag_engine import SSUETRAG
except Exception as e:
    print(f"⚠️  Could not import SSUETRAG from rag_engine: {e}")
    SSUETRAG = None   # will cause the init to fail gracefully

# Import security features
from security import (
    limiter, init_security, csrf_protect, login_required, admin_required,
    sanitize_input, sanitize_dict, otp_manager, lockout, ip_blocker,
    generate_csrf_token
)

# ── FLASK APP CONFIGURATION ──
app = Flask(__name__, static_folder='static', template_folder='templates', static_url_path='/static')
CORS(app)

# ── ENVIRONMENT SETTINGS ──
ENVIRONMENT = os.environ.get('ENVIRONMENT', 'development').lower()
DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'

# ── SECURITY: Load secret key from environment ──
SECRET_KEY = os.environ.get('FLASK_SECRET_KEY', 'dev_key_change_in_production_32chars_min')
if len(SECRET_KEY) < 32:
    print("⚠️  WARNING: FLASK_SECRET_KEY is too short (< 32 chars). Using default for development only.")
app.secret_key = SECRET_KEY

# Initialize security module on the app
init_security(app)

# ── DATABASE CONFIGURATION ──
def get_db_config():
    """Load database config from environment variables."""
    return {
        "host": os.environ.get('DB_HOST', 'localhost'),
        "user": os.environ.get('DB_USER', 'root'),
        "password": os.environ.get('DB_PASSWORD', 'root'),
        "database": os.environ.get('DB_NAME', 'ssuet_ai_db'),
        "port": int(os.environ.get('DB_PORT', 3306))
    }

DB_CONFIG = get_db_config()

# ── API CONFIGURATION ──
# Read API keys from environment
raw_api_keys = os.environ.get('OPENROUTER_API_KEYS', '')
OPENROUTER_API_KEYS = [k.strip() for k in raw_api_keys.split(';') if k.strip()]
if not OPENROUTER_API_KEYS:
    print("⚠️  WARNING: No OPENROUTER_API_KEYS found in environment variables!")

# Separate URLs for chat and rerank APIs
API_URL_CHAT = 'https://openrouter.ai/api/v1/chat/completions'
API_URL_RERANK = 'https://openrouter.ai/api/v1/rerank'
MAX_API_RETRIES = int(os.environ.get('MAX_API_RETRIES', 3))
API_TIMEOUT = int(os.environ.get('API_TIMEOUT_SECONDS', 15))
ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'admin@ssuet.edu.pk')

# CORRECTED MODEL IDENTIFIERS (Standard LLMs first for strict RAG execution; Search/Online models as final fallback)
MODELS = [
    # Standard Chat Models (will strictly use RAG context without searching the web)
    "nvidia/llama-nemotron-rerank-vl-1b-v2:free",
    "openai/gpt-4o:online",
    "meta-llama/llama-3.3-70b-instruct:online",
    "meta-llama/llama-3-8b-instruct:online",
    "deepseek/deepseek-r1:online",
    
    # Free standard chat models
    "openrouter/free",
    "meta-llama/llama-3-8b-instruct",

    # Online Search Models (as a fallback if API keys/standard models fail)
    "perplexity/sonar",
    "perplexity/sonar-reasoning",
    "perplexity/sonar-pro-search",
    "perplexity/sonar-deep-research",
    "openrouter/auto:online",
]

SYSTEM_PROMPT = """You are the official AI Assistant for Sir Syed University of Engineering and Technology (SSUET), Karachi, Pakistan.

CRITICAL RULES:
1. RAG-FIRST APPROACH: Try to answer the user's question using the provided "RETRIEVED CONTEXT FROM SSUET WEBSITE" first. If the information is not present or insufficient in the context, you may use your internal knowledge or perform an online lookup to find the correct answer about SSUET.
2. NO CITATION NUMBERS: Do not output bracketed citation numbers or footnotes (like [1], [2], [8], [47], etc.) inline inside the sentences. Keep your sentences clean.
3. REFERENCE LINKS AT THE BOTTOM: If you mention any reference links or URLs, do not include them inline inside the text. Instead, collect them and list them cleanly under a "Sources:" or "References:" header at the very bottom of your response.
4. Keep answers directly focused on the university, its departments, programs, and faculty.

SSUET KEY FACTS:
- Full name: Sir Syed University of Engineering and Technology (SSUET)
- Location: University Road, Karachi-75300, Sindh, Pakistan
- Phone: +92-21-34988000 | Email: info@ssuet.edu.pk | Website: www.ssuet.edu.pk
- Founded: 1993 | Type: Private Research University
- Recognized by: HEC and PEC

FACULTIES:
1. Faculty of Electrical & Computer Engineering (FoECE) - Dean: Dr. Farooq Ahmad
2. Faculty of Computing & Applied Sciences (FoCAS) - Dean: Dr. Salman Ahmed
3. Faculty of Civil Engineering & Architecture (FoCVA) - Dean: Dr. Asma Khan
4. Faculty of Business Management & Social Science (FoBMS) - Dean: Dr. Hassan Raza

PROGRAMS:
- BS Computer Science, Computer Engineering, Electronic Engineering, Electrical Engineering
- BS Civil Engineering, Software Engineering, Biomedical Engineering, Telecommunication Engineering
- BS Robotics & Intelligent Machines (NEW — Spring 2026)
- BBA, MBA, MS Computer Engineering, MS Electronic Engineering

CURRENT NEWS:
- Spring 2026 Admissions: CLOSED
- Fall 2026 Admissions: Opening Soon
- New Program: BS Robotics & Intelligent Machines

OFFICIAL SOCIAL MEDIA:
- Facebook: https://www.facebook.com/SSUET.Karachi
- Twitter/X: https://twitter.com/ssuet_karachi
- LinkedIn: https://www.linkedin.com/school/ssuet/
- YouTube: https://www.youtube.com/@SSUETOfficial

Be warm, friendly, helpful. Use bullet points. Direct fee/timetable queries to ssuet.edu.pk or +92-21-34988000."""

# ── DATABASE CONNECTION ──
def get_db_connection():
    """Get database connection with retry logic."""
    for attempt in range(3):
        try:
            conn = mysql.connector.connect(**DB_CONFIG)
            return conn
        except MySQLError as e:
            if attempt < 2:
                wait_time = 2 ** attempt
                print(f"⚠️  DB Connection Attempt {attempt + 1} failed, retrying in {wait_time}s: {e}")
                time.sleep(wait_time)
            else:
                print(f"❌ Database Connection Failed (final attempt): {e}")
                return None
    return None

# ── DATABASE INITIALIZATION ──
def init_db():
    """Initialize database tables if they don't exist."""
    conn = get_db_connection()
    if not conn:
        print("❌ Cannot initialize database: Connection failed")
        return False

    try:
        cursor = conn.cursor()

        # Create users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                email VARCHAR(100) UNIQUE NOT NULL,
                phone VARCHAR(20),
                password_hash VARCHAR(255) NOT NULL,
                last_login DATETIME NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create chat_sessions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                session_name VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        # Create messages table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INT AUTO_INCREMENT PRIMARY KEY,
                session_id INT NOT NULL,
                sender ENUM('user', 'ai') NOT NULL,
                content LONGTEXT NOT NULL,
                model_used VARCHAR(100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES chat_sessions(id)
            )
        """)

        # Create leads table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                name VARCHAR(100) NOT NULL,
                email VARCHAR(100) NOT NULL,
                phone VARCHAR(20),
                interest_program VARCHAR(100),
                status ENUM('new', 'contacted', 'converted') DEFAULT 'new',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        # Create feedback table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                rating INT NOT NULL,
                category VARCHAR(50) DEFAULT 'general',
                comment LONGTEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        # Create tickets table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                subject VARCHAR(255) NOT NULL,
                description LONGTEXT NOT NULL,
                priority ENUM('low', 'medium', 'high') DEFAULT 'medium',
                status ENUM('open', 'in_progress', 'resolved') DEFAULT 'open',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        # Create faculty table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS faculty (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                designation VARCHAR(100),
                department VARCHAR(100),
                email VARCHAR(100),
                specialization VARCHAR(255)
            )
        """)

        # Create otp_codes table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS otp_codes (
                id INT AUTO_INCREMENT PRIMARY KEY,
                email VARCHAR(100) NOT NULL,
                otp_code VARCHAR(6) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME NOT NULL,
                used BOOLEAN DEFAULT FALSE,
                INDEX idx_email_otp (email, otp_code),
                INDEX idx_expires (expires_at)
            )
        """)

        # Create login_attempts table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS login_attempts (
                id INT AUTO_INCREMENT PRIMARY KEY,
                ip_address VARCHAR(45) NOT NULL,
                email VARCHAR(100) NOT NULL,
                attempted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_email_time (email, attempted_at),
                INDEX idx_ip_time (ip_address, attempted_at)
            )
        """)

        # Create blocked_ips table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS blocked_ips (
                id INT AUTO_INCREMENT PRIMARY KEY,
                ip_address VARCHAR(45) NOT NULL UNIQUE,
                reason VARCHAR(255) DEFAULT 'Suspicious activity',
                blocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME NULL,
                INDEX idx_ip (ip_address),
                INDEX idx_expires (expires_at)
            )
        """)

        # Add email_verified column to users (safe fallback)
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN email_verified BOOLEAN DEFAULT FALSE")
        except MySQLError as err:
            # Ignore "Duplicate column name" error (1060)
            if err.errno != 1060:
                print(f"⚠️  Error altering users table: {err}")

        conn.commit()
        cursor.close()
        print("✅ DATABASE TABLES INITIALIZED SUCCESSFULLY")
        return True

    except MySQLError as e:
        print(f"❌ Database Initialization Error: {e}")
        return False
    finally:
        if conn:
            conn.close()

# ── RAG INITIALIZATION ──
try:
    rag_engine = SSUETRAG() if SSUETRAG is not None else None
    print("✅ RAG ENGINE INITIALIZED SUCCESSFULLY")
except Exception as e:
    print(f"⚠️  RAG Engine initialization failed: {e}")
    rag_engine = None  # Fallback to no RAG

# ── IP BLOCKING MIDDLEWARE ──
@app.before_request
def check_ip_block():
    ip_address = request.remote_addr
    if ip_blocker.is_blocked(get_db_connection, ip_address):
        abort(403, description="Access denied: Your IP address has been blocked due to suspicious activity.")

# ── MAIN ROUTES ──
@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('index.html', user_name=session.get('user_name', 'User'))

# ── AUTH ROUTES ──
@app.route('/register', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
@csrf_protect
def register():
    if request.method == 'POST':
        conn = None
        try:
            data = request.json
            name = sanitize_input(data.get('name', '')).strip()
            email = sanitize_input(data.get('email', '')).strip().lower()
            phone = sanitize_input(data.get('phone', '')).strip()
            password = data.get('password', '')

            # Validation
            if not all([name, email, phone, password]):
                return jsonify({"error": "All fields are required"}), 400

            if len(password) < 6:
                return jsonify({"error": "Password must be at least 6 characters"}), 400

            if '@' not in email:
                return jsonify({"error": "Invalid email address"}), 400

            conn = get_db_connection()
            if not conn:
                return jsonify({"error": "Database connection failed"}), 500

            cursor = conn.cursor(dictionary=True)

            # Check if email verified via OTP (Must be verified in last 10 minutes)
            cursor.execute(
                "SELECT * FROM otp_codes WHERE email=%s AND used=TRUE AND expires_at > DATE_SUB(NOW(), INTERVAL 10 MINUTE)",
                (email,)
            )
            otp_verified = cursor.fetchone()
            if not otp_verified:
                cursor.close()
                return jsonify({"error": "Please verify your email first via OTP code"}), 400

            # Check if email exists
            cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
            if cursor.fetchone():
                cursor.close()
                return jsonify({"error": "Email already registered"}), 400

            # Hash password
            password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

            # Insert user
            cursor.execute(
                "INSERT INTO users (name, email, phone, password_hash, email_verified) VALUES (%s, %s, %s, %s, TRUE)",
                (name, email, phone, password_hash)
            )
            conn.commit()
            user_id = cursor.lastrowid

            # Create lead entry
            cursor.execute(
                "INSERT INTO leads (user_id, name, email, phone) VALUES (%s, %s, %s, %s)",
                (user_id, name, email, phone)
            )
            conn.commit()

            cursor.close()
            return jsonify({"success": True, "message": "Registration successful! Please login."})

        except Exception as e:
            print(f"❌ Registration Error: {e}")
            return jsonify({"error": "Registration failed. Please try again."}), 500
        finally:
            if conn:
                conn.close()

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
@csrf_protect
def login():
    if request.method == 'POST':
        conn = None
        try:
            data = request.json
            email = sanitize_input(data.get('email', '')).strip().lower()
            password = data.get('password', '')
            ip_address = request.remote_addr

            if not email or not password:
                return jsonify({"error": "Email and password required"}), 400

            # Check lockout
            locked, mins = lockout.is_locked(get_db_connection, email, ip_address)
            if locked:
                return jsonify({
                    "error": f"Account or IP locked due to too many failed attempts. Try again in {mins} minutes.",
                    "lockout_minutes": mins
                }), 403

            conn = get_db_connection()
            if not conn:
                return jsonify({"error": "Database connection failed"}), 500

            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
            user = cursor.fetchone()
            cursor.close()

            if user and bcrypt.checkpw(password.encode('utf-8'), user['password_hash'].encode('utf-8')):
                # Reset failed login attempts on success
                lockout.clear_attempts(get_db_connection, email)

                session['user_id'] = user['id']
                session['user_name'] = user['name']
                session['user_email'] = user['email']

                # Update last login
                cursor = conn.cursor()
                cursor.execute("UPDATE users SET last_login = NOW() WHERE id = %s", (user['id'],))
                conn.commit()
                cursor.close()

                # Redirect admin to admin panel
                if email == ADMIN_EMAIL:
                    return jsonify({
                        "success": True,
                        "message": "Login successful! Redirecting to admin panel...",
                        "redirect": "/admin"
                    })

                return jsonify({
                    "success": True,
                    "message": "Login successful!",
                    "redirect": "/"
                })
            else:
                # Record failed login attempt
                lockout.record_failed_attempt(get_db_connection, ip_address, email)

                # Check if this IP has surpassed threshold (10+ attempts in last 15 mins)
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM login_attempts WHERE ip_address = %s AND attempted_at > DATE_SUB(NOW(), INTERVAL 15 MINUTE)", (ip_address,))
                failed_count = cursor.fetchone()[0]
                cursor.close()

                if failed_count >= 10:
                    ip_blocker.block_ip(get_db_connection, ip_address, "Brute force attack: 10+ failed logins", duration_hours=24)
                    return jsonify({"error": "Too many failed attempts. Your IP address has been blocked."}), 403

                return jsonify({"error": "Invalid email or password"}), 401

        except Exception as e:
            print(f"❌ Login Error: {e}")
            return jsonify({"error": "Login failed. Please try again."}), 500
        finally:
            if conn:
                conn.close()

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ── NEW OTP ENDPOINTS ──
@app.route('/api/send-otp', methods=['POST'])
@limiter.limit("10 per minute")
@csrf_protect
def send_otp():
    conn = None
    try:
        data = request.json or {}
        email = sanitize_input(data.get('email', '')).strip().lower()
        name = sanitize_input(data.get('name', 'SSUET User')).strip()

        if not email or '@' not in email:
            return jsonify({"error": "A valid email address is required"}), 400

        # Generate OTP code
        otp_code = otp_manager.generate_otp()

        # Save to database (expires in 5 minutes)
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500

        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO otp_codes (email, otp_code, expires_at, used) VALUES (%s, %s, DATE_ADD(NOW(), INTERVAL 5 MINUTE), FALSE)",
            (email, otp_code)
        )
        conn.commit()
        cursor.close()

        # Send email
        success, err = otp_manager.send_otp_email(email, otp_code, name)
        if not success:
            return jsonify({"error": f"Failed to send email: {err}"}), 500

        return jsonify({"success": True, "message": "Verification code sent successfully!"})

    except Exception as e:
        print(f"❌ Error in send_otp: {e}")
        return jsonify({"error": "Failed to process OTP request"}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/verify-otp', methods=['POST'])
@limiter.limit("10 per minute")
@csrf_protect
def verify_otp():
    conn = None
    try:
        data = request.json or {}
        email = sanitize_input(data.get('email', '')).strip().lower()
        otp_code = sanitize_input(data.get('otp_code', '')).strip()

        if not email or not otp_code:
            return jsonify({"error": "Email and OTP code are required"}), 400

        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500

        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id FROM otp_codes WHERE email = %s AND otp_code = %s AND used = FALSE AND expires_at > NOW() ORDER BY created_at DESC LIMIT 1",
            (email, otp_code)
        )
        record = cursor.fetchone()

        if not record:
            cursor.close()
            return jsonify({"error": "Invalid or expired verification code"}), 400

        # Mark as used
        cursor.execute(
            "UPDATE otp_codes SET used = TRUE WHERE id = %s",
            (record['id'],)
        )
        conn.commit()
        cursor.close()

        return jsonify({"success": True, "verified": True, "message": "Email verified successfully!"})

    except Exception as e:
        print(f"❌ Error in verify_otp: {e}")
        return jsonify({"error": "Failed to verify OTP"}), 500
    finally:
        if conn:
            conn.close()

# ── IMPROVED API CHAT ENDPOINT WITH RERANKING ──
@app.route('/api/chat', methods=['POST'])
@login_required
@csrf_protect
@limiter.limit("20 per minute")
def chat():
    conn = None
    try:
        data = request.json
        user_message = sanitize_input(data.get('message', '')).strip()
        session_id = data.get('session_id')

        if not user_message:
            return jsonify({"error": "Message cannot be empty"}), 400

        # Create or use existing session
        if not session_id:
            conn = get_db_connection()
            if conn:
                try:
                    cursor = conn.cursor()
                    cursor.execute(
                        "INSERT INTO chat_sessions (user_id, session_name) VALUES (%s, %s)",
                        (session['user_id'], f"Chat {datetime.now().strftime('%Y-%m-%d %H:%M')}")
                    )
                    conn.commit()
                    session_id = cursor.lastrowid
                    cursor.close()
                except Exception as db_e:
                    print(f"⚠️  DB Error creating session: {db_e}")
                finally:
                    conn.close()

        # Save user message
        try:
            conn = get_db_connection()
            if conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO messages (session_id, sender, content) VALUES (%s, %s, %s)",
                    (session_id, 'user', user_message)
                )
                conn.commit()
                cursor.close()
        except Exception as db_e:
            print(f"⚠️  DB Error saving user message: {db_e}")
        finally:
            if conn:
                conn.close()

        # Get chat history (last 20 messages)
        history = []
        try:
            conn = get_db_connection()
            if conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT sender, content FROM messages WHERE session_id = %s ORDER BY created_at ASC LIMIT 20",
                    (session_id,)
                )
                history = [{"role": "assistant" if row[0] == "ai" else "user", "content": row[1]} for row in cursor.fetchall()]
                cursor.close()
        except Exception as db_e:
            print(f"⚠️  DB Error retrieving history: {db_e}")
        finally:
            if conn:
                conn.close()

        # ── RAG CONTEXT AUGMENTATION WITH RERANKING ──
        rag_context = ""
        chunks = []   # list of chunk dicts from RAG
        if rag_engine:
            try:
                # Retrieve a larger set of chunks for reranking (e.g., 50)
                chunks = rag_engine.retrieve(user_message, k=50)
                print(f"🔍 RAG retrieved {len(chunks)} chunks for query: '{user_message[:50]}...'")
            except Exception as e:
                print(f"⚠️  RAG retrieval error: {e}")
                chunks = []

        # Helper function to build context string from a list of chunks
        def _build_context_string(chunks_list, max_chars=3000):
            if not chunks_list:
                return ""
            header = "=== RETRIEVED CONTEXT FROM SSUET WEBSITE ===\n"
            footer = "=== END OF RETRIEVED CONTEXT ===\n"
            parts = []
            cur_len = 0
            for ch in chunks_list:
                src = f"[Source: {ch['title']} ({ch['url']})]"
                txt = ch.get("content_text", "").strip()
                if not txt:
                    txt = ch.get("content", "").strip()
                block = f"{src}\n{txt}\n"
                block_len = len(block)
                if cur_len + block_len > max_chars:
                    remaining_space = max_chars - cur_len - len(src) - 50
                    if remaining_space > 200:
                        truncated_txt = txt[:remaining_space] + "... [Content truncated to fit context limits]"
                        block = f"{src}\n{truncated_txt}\n"
                        parts.append(block)
                        cur_len += len(block)
                    else:
                        break
                else:
                    parts.append(block)
                    cur_len += block_len
            return header + "".join(parts) + footer

        # If we have chunks and API keys, try to rerank
        if chunks and OPENROUTER_API_KEYS:
            # Prepare documents for reranking: use the 'content' field of each chunk
            doc_texts = [ch.get("content", "") for ch in chunks]
            # Try to call the rerank API with the free model
            reranked_chunks = None
            for key in OPENROUTER_API_KEYS:
                try:
                    print(f"🔄 Attempting rerank with key ending in ...{key[-4:]}")
                    response = requests.post(
                        API_URL_RERANK,
                        headers={
                            'Content-Type': 'application/json',
                            'Authorization': f'Bearer {key}',
                            'HTTP-Referer': 'https://ssuet.edu.pk',
                            'X-Title': 'SSUET AI Assistant'
                        },
                        json={
                            "model": "nvidia/llama-nemotron-rerank-vl-1b-v2:free",
                            "query": user_message,
                            "documents": doc_texts
                        },
                        timeout=API_TIMEOUT
                    )
                    if response.status_code != 200:
                        print(f"⚠️  Rerank API error: {response.status_code} - {response.text[:200]}")
                        continue

                    try:
                        result = response.json()
                    except json.JSONDecodeError as e:
                        print(f"⚠️  Failed to parse JSON from rerank response: {e}")
                        continue

                    # Check the structure of the result
                    if 'results' not in result or not isinstance(result['results'], list):
                        print(f"⚠️  Unexpected rerank response structure: {result}")
                        continue

                    reranked_results = result['results']
                    # Validate each result has 'index' and 'score'
                    valid_results = []
                    for res in reranked_results:
                        if isinstance(res, dict) and 'index' in res and 'score' in res:
                            valid_results.append(res)
                        else:
                            print(f"⚠️  Invalid result item in rerank response: {res}")

                    if not valid_results:
                        print("⚠️  No valid results in rerank response after validation")
                        continue

                    # Sort by score descending
                    valid_results.sort(key=lambda x: x['score'], reverse=True)
                    top_indices = [res['index'] for res in valid_results]
                    reranked_chunks = [chunks[i] for i in top_indices if i < len(chunks)]
                    print(f"✅ Rerank successful. Got {len(reranked_chunks)} chunks.")
                    break   # break out of the key loop on success

                except Exception as e:
                    print(f"⚠️  Unexpected error during rerank: {e}")
                    continue

            if reranked_chunks:
                # Take top 5 (or up to 5) of the reranked chunks
                top_chunks = reranked_chunks[:5]
                # Build context string from these top chunks
                rag_context = _build_context_string(top_chunks, max_chars=3000)
                print(f"🔍 Using reranked context ({len(rag_context)} chars) from top {len(top_chunks)} chunks")
            else:
                # If rerank failed, fall back to the original method
                print("⚠️  Rerank failed, falling back to original RAG context")
                if rag_engine:
                    try:
                        rag_context = rag_engine.get_context_prompt(user_message, max_chars=3000)
                    except Exception as e:
                        print(f"⚠️  RAG retrieval error in fallback: {e}")
                        rag_context = ""
        else:
            # If no chunks or no API keys, use the original method
            if rag_engine:
                try:
                    rag_context = rag_engine.get_context_prompt(user_message, max_chars=3000)
                except Exception as e:
                    print(f"⚠️  RAG retrieval error: {e}")
                    rag_context = ""

        messages_payload = [
            {"role": "system", "content": SYSTEM_PROMPT + rag_context},
            *history,
        ]

        # ── IMPROVED API FALLBACK LOGIC ──
        last_error = None
        attempted_models = []

        for model in MODELS:
            attempted_models.append(model)  # Bug #6 fix: Move to beginning of the loop
            for key in OPENROUTER_API_KEYS:
                try:
                    print(f"🔄 Attempting: Model={model}")

                    response = requests.post(
                        API_URL_CHAT,
                        headers={
                            'Content-Type': 'application/json',
                            'Authorization': f'Bearer {key}',
                            'HTTP-Referer': 'https://ssuet.edu.pk',
                            'X-Title': 'SSUET AI Assistant'
                        },
                        json={
                            "model": model,
                            "max_tokens": 1024,
                            "messages": messages_payload
                        },
                        timeout=API_TIMEOUT
                    )

                    if response.status_code == 200:
                        result = response.json()
                        ai_reply = result['choices'][0]['message']['content']

                        # Save AI response
                        try:
                            conn = get_db_connection()
                            if conn:
                                cursor = conn.cursor()
                                cursor.execute(
                                    "INSERT INTO messages (session_id, sender, content, model_used) VALUES (%s, %s, %s, %s)",
                                    (session_id, 'ai', ai_reply, model)
                                )
                                conn.commit()
                                cursor.close()
                        except Exception as db_e:
                            print(f"⚠️  DB Error saving AI response: {db_e}")
                        finally:
                            if conn:
                                conn.close()

                        print(f"✅ SUCCESS! Used Model: {model}")
                        return jsonify({
                            "reply": ai_reply,
                            "session_id": session_id,
                            "model": model
                        })

                    elif response.status_code == 429:
                        last_error = "Rate limited by API"
                        print(f"⚠️  Rate limited for {model}")
                        continue

                    elif response.status_code == 401:
                        last_error = "Invalid API key"
                        print(f"⚠️  Invalid API key")
                        continue

                    else:
                        last_error = f"API error: {response.status_code}"
                        print(f"⚠️  API returned status {response.status_code}")
                        continue

                except requests.Timeout:
                    last_error = "Request timeout"
                    print(f"⚠️  Request timeout for {model}")
                    continue

                except requests.ConnectionError:
                    last_error = "Connection error"
                    print(f"⚠️  Connection error for {model}")
                    continue

                except Exception as e:
                    last_error = str(e)
                    print(f"⚠️  Unexpected error with {model}: {e}")
                    continue

        # All models and keys exhausted
        error_message = "❌ All AI models are currently unavailable. Please try again in a few moments."
        print(f"❌ All API attempts exhausted. Last error: {last_error}")

        return jsonify({"reply": error_message, "session_id": session_id}), 503

    except Exception as e:
        print(f"❌ CRITICAL SERVER ERROR in /api/chat: {e}")
        return jsonify({"reply": "❌ Server error. Please try again."}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/sessions', methods=['GET'])
@login_required
def get_sessions():
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500

        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, session_name, created_at FROM chat_sessions WHERE user_id = %s ORDER BY created_at DESC",
            (session['user_id'],)
        )
        sessions = cursor.fetchall()
        cursor.close()

        return jsonify({"sessions": sessions})
    except Exception as e:
        print(f"❌ Error fetching sessions: {e}")
        return jsonify({"error": "Failed to fetch sessions"}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/messages/<int:session_id>', methods=['GET'])
@login_required
def get_messages(session_id):
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500

        cursor = conn.cursor(dictionary=True)

        # Verify session belongs to user
        cursor.execute("SELECT user_id FROM chat_sessions WHERE id = %s", (session_id,))
        result = cursor.fetchone()

        if not result or result['user_id'] != session['user_id']:
            cursor.close()
            return jsonify({"error": "Unauthorized"}), 403

        cursor.execute(
            "SELECT sender, content, created_at FROM messages WHERE session_id = %s ORDER BY created_at ASC",
            (session_id,)
        )
        messages = cursor.fetchall()
        cursor.close()

        return jsonify({"messages": messages})
    except Exception as e:
        print(f"❌ Error fetching messages: {e}")
        return jsonify({"error": "Failed to fetch messages"}), 500
    finally:
        if conn:
            conn.close()

# ── FEEDBACK ROUTES ──
@app.route('/api/feedback', methods=['POST'])
@login_required
@csrf_protect
def submit_feedback():
    conn = None
    try:
        data = request.json
        rating = data.get('rating')
        category = sanitize_input(data.get('category', 'general')).strip()
        comment = sanitize_input(data.get('comment', '')).strip()

        if not rating or not isinstance(rating, int) or rating < 1 or rating > 5:
            return jsonify({"error": "Invalid rating"}), 400

        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500

        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO feedback (user_id, rating, category, comment) VALUES (%s, %s, %s, %s)",
            (session['user_id'], rating, category, comment)
        )
        conn.commit()
        cursor.close()

        return jsonify({"success": True, "message": "Thank you for your feedback!"})
    except Exception as e:
        print(f"❌ Error submitting feedback: {e}")
        return jsonify({"error": "Failed to submit feedback"}), 500
    finally:
        if conn:
            conn.close()

# ── TICKET ROUTES ──
@app.route('/api/tickets', methods=['POST', 'GET'])
@login_required
@csrf_protect
def tickets():
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500

        cursor = conn.cursor(dictionary=True)

        if request.method == 'POST':
            data = request.json
            subject = sanitize_input(data.get('subject', '')).strip()
            description = sanitize_input(data.get('description', '')).strip()
            priority = sanitize_input(data.get('priority', 'medium')).strip()

            if not subject or not description:
                cursor.close()
                return jsonify({"error": "Subject and description required"}), 400

            if priority not in ['low', 'medium', 'high']:
                priority = 'medium'

            cursor.execute(
                "INSERT INTO tickets (user_id, subject, description, priority) VALUES (%s, %s, %s, %s)",
                (session['user_id'], subject, description, priority)
            )
            conn.commit()
            ticket_id = cursor.lastrowid
            cursor.close()

            return jsonify({"success": True, "ticket_id": ticket_id, "message": "Ticket created successfully!"})

        else:
            cursor.execute(
                "SELECT id, subject, status, priority, created_at FROM tickets WHERE user_id = %s ORDER BY created_at DESC",
                (session['user_id'],)
            )
            tickets_list = cursor.fetchall()
            cursor.close()

            return jsonify({"tickets": tickets_list})

    except Exception as e:
        print(f"❌ Error with tickets: {e}")
        return jsonify({"error": "Failed to process ticket"}), 500
    finally:
        if conn:
            conn.close()

# ── PASSWORD CHANGE ENDPOINT ──
@app.route('/api/change-password', methods=['POST'])
@login_required
@csrf_protect
def change_password():
    conn = None
    try:
        data = request.json
        current_password = data.get('current_password', '')
        new_password = data.get('new_password', '')

        if not current_password or not new_password:
            return jsonify({"error": "Current and new passwords are required"}), 400

        if len(new_password) < 6:
            return jsonify({"error": "New password must be at least 6 characters"}), 400

        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500

        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT password_hash FROM users WHERE id = %s", (session['user_id'],))
        user = cursor.fetchone()

        if not user:
            cursor.close()
            return jsonify({"error": "User not found"}), 404

        if not bcrypt.checkpw(current_password.encode('utf-8'), user['password_hash'].encode('utf-8')):
            cursor.close()
            return jsonify({"error": "Current password is incorrect"}), 401

        new_password_hash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        cursor.execute(
            "UPDATE users SET password_hash = %s WHERE id = %s",
            (new_password_hash, session['user_id'])
        )
        conn.commit()
        cursor.close()

        return jsonify({"success": True, "message": "Password changed successfully!"})

    except Exception as e:
        print(f"❌ Error changing password: {e}")
        return jsonify({"error": "Failed to change password"}), 500
    finally:
        if conn:
            conn.close()

# ── ADMIN ROUTES ──
@app.route('/admin')
def admin():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if session.get('user_email') != ADMIN_EMAIL:
        return render_template('index.html', user_name=session.get('user_name', 'User'))

    return render_template('admin.html', admin_name=session.get('user_name', 'Admin'))

@app.route('/api/admin/stats')
@admin_required
def admin_stats():
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500

        cursor = conn.cursor(dictionary=True)

        stats = {}

        cursor.execute("SELECT COUNT(*) as count FROM users")
        stats['total_users'] = cursor.fetchone()['count']

        cursor.execute("SELECT COUNT(*) as count FROM messages")
        stats['total_messages'] = cursor.fetchone()['count']

        cursor.execute("SELECT COUNT(*) as count FROM leads")
        stats['total_leads'] = cursor.fetchone()['count']

        cursor.execute("SELECT STATUS, COUNT(*) as count FROM leads GROUP BY status")
        stats['leads_by_status'] = cursor.fetchall()

        cursor.execute("SELECT AVG(rating) as avg_rating FROM feedback")
        avg_rating = cursor.fetchone()['avg_rating']
        stats['avg_rating'] = round(avg_rating, 1) if avg_rating else 0

        cursor.execute("SELECT STATUS, COUNT(*) as count FROM tickets GROUP BY status")
        stats['tickets_by_status'] = cursor.fetchall()

        cursor.execute("""
            SELECT DATE(created_at) as date, COUNT(*) as count
            FROM messages
            WHERE created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
            GROUP BY DATE(created_at)
            ORDER BY date ASC
        """)
        stats['messages_per_day'] = cursor.fetchall()

        cursor.close()
        return jsonify(stats)
    except Exception as e:
        print(f"❌ Error fetching admin stats: {e}")
        return jsonify({"error": "Failed to fetch stats"}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/admin/leads')
@admin_required
def admin_leads():
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500

        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM leads ORDER BY created_at DESC")
        leads = cursor.fetchall()
        cursor.close()

        return jsonify({"leads": leads})
    except Exception as e:
        print(f"❌ Error fetching leads: {e}")
        return jsonify({"error": "Failed to fetch leads"}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/admin/faculty')
@admin_required  # Bug #11 fix: Enforce admin check
def get_faculty():
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500

        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM faculty ORDER BY department, name")
        faculty = cursor.fetchall()
        cursor.close()

        return jsonify({"faculty": faculty})
    except Exception as e:
        print(f"❌ Error fetching faculty: {e}")
        return jsonify({"error": "Failed to fetch faculty"}), 500
    finally:
        if conn:
            conn.close()

# ── NEW SECURITY ADMIN ENDPOINTS ──
@app.route('/api/admin/security', methods=['GET'])
@admin_required
def admin_security():
    try:
        blocked_ips = ip_blocker.get_blocked_ips(get_db_connection)
        login_attempts = lockout.get_recent_attempts(get_db_connection)
        
        # Convert any datetime objects to string format for JSON serialization
        for ip in blocked_ips:
            if ip.get('blocked_at'):
                ip['blocked_at'] = ip['blocked_at'].isoformat()
            if ip.get('expires_at'):
                ip['expires_at'] = ip['expires_at'].isoformat()
                
        for attempt in login_attempts:
            if attempt.get('attempted_at'):
                attempt['attempted_at'] = attempt['attempted_at'].isoformat()

        return jsonify({
            "blocked_ips": blocked_ips,
            "login_attempts": login_attempts
        })
    except Exception as e:
        print(f"❌ Error fetching admin security stats: {e}")
        return jsonify({"error": "Failed to fetch security data"}), 500

@app.route('/api/admin/block-ip', methods=['POST'])
@admin_required
@csrf_protect
def admin_block_ip():
    try:
        data = request.json or {}
        ip_address = sanitize_input(data.get('ip_address', '')).strip()
        reason = sanitize_input(data.get('reason', 'Manually blocked by admin')).strip()

        if not ip_address:
            return jsonify({"error": "IP address is required"}), 400

        ip_blocker.block_ip(get_db_connection, ip_address, reason, duration_hours=24)
        return jsonify({"success": True, "message": f"IP {ip_address} blocked successfully."})
    except Exception as e:
        print(f"❌ Error blocking IP: {e}")
        return jsonify({"error": "Failed to block IP"}), 500

@app.route('/api/admin/unblock-ip', methods=['POST'])
@admin_required
@csrf_protect
def admin_unblock_ip():
    try:
        data = request.json or {}
        ip_address = sanitize_input(data.get('ip_address', '')).strip()

        if not ip_address:
            return jsonify({"error": "IP address is required"}), 400

        ip_blocker.unblock_ip(get_db_connection, ip_address)
        return jsonify({"success": True, "message": f"IP {ip_address} unblocked successfully."})
    except Exception as e:
        print(f"❌ Error unblocking IP: {e}")
        return jsonify({"error": "Failed to unblock IP"}), 500

# ── HEALTH CHECK ──
@app.route('/api/health')
def health():
    return jsonify({
        "status": "ok",
        "message": "SSUET AI Server is running!",
        "environment": ENVIRONMENT,
        "models_available": len(MODELS),
        "free_models": len([m for m in MODELS if ":free" in m])
    })

# ── ERROR HANDLERS ──
@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(500)
def server_error(e):
    print(f"❌ Server error: {e}")
    return jsonify({"error": "Internal server error"}), 500

# ── MAIN ──
if __name__ == '__main__':
    # Initialize DB (Bug #8 fix)
    init_db()

    print("\n" + "="*70)
    print("🎓 SSUET AI ASSISTANT SERVER")
    print("="*70)
    print(f"Environment: {ENVIRONMENT}")
    print(f"Debug Mode: {DEBUG}")
    print(f"Database: {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}")
    print(f"Models: {len(MODELS)} available")
    print(f"Admin Email: {ADMIN_EMAIL}")
    print("="*70)
    print("✓ Login URL: http://localhost:5000/login")
    print("✓ Register URL: http://localhost:5000/register")
    print("✓ Admin URL: http://localhost:5000/admin")  # Bug #9 fix: always print admin URL
    print("="*70 + "\n")

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=DEBUG,
        use_reloader=DEBUG
    )
