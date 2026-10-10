from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
import database
import logging
import socket
import ipaddress
import os
import re
import secrets
import sqlite3
import time
import hashlib
import hmac
from pathlib import Path
from contextlib import contextmanager
import uuid
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import parseaddr
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / '.env')

app = Flask(__name__)
STATE_DIR = Path(os.environ.get('WOL_STATE_DIR') or str(Path(__file__).parent / 'instance'))
STATE_DIR.mkdir(parents=True, exist_ok=True)
secret_path = STATE_DIR / 'session.key'
if not os.environ.get('FLASK_SECRET_KEY') and not secret_path.exists():
    try:
        with secret_path.open('x') as secret_file:
            secret_file.write(secrets.token_hex(32))
    except FileExistsError:
        pass
app.secret_key = os.environ.get('FLASK_SECRET_KEY') or secret_path.read_text().strip()
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('COOKIE_SECURE', '0') == '1'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
from production_config import configure
configure(app)

@contextmanager
def state_connection():
    conn = sqlite3.connect(STATE_DIR / 'auth.sqlite3', timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()

with state_connection() as state_db:
    state_db.execute('CREATE TABLE IF NOT EXISTS auth_codes (code TEXT PRIMARY KEY, user_id TEXT NOT NULL, client_id TEXT NOT NULL, redirect_uri TEXT NOT NULL, expires REAL NOT NULL, code_challenge TEXT)')
    if 'code_challenge' not in [column[1] for column in state_db.execute('PRAGMA table_info(auth_codes)')]:
        state_db.execute('ALTER TABLE auth_codes ADD COLUMN code_challenge TEXT')
    state_db.execute('CREATE TABLE IF NOT EXISTS auth_tokens (access_token TEXT PRIMARY KEY, refresh_token TEXT UNIQUE NOT NULL, user_id TEXT NOT NULL, client_id TEXT NOT NULL, expires REAL NOT NULL)')
    state_db.execute('CREATE TABLE IF NOT EXISTS challenges (id TEXT PRIMARY KEY, email TEXT NOT NULL, purpose TEXT NOT NULL, code_hash TEXT NOT NULL, expires REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0)')
    state_db.execute('CREATE TABLE IF NOT EXISTS rate_limits (key TEXT PRIMARY KEY, count INTEGER NOT NULL, expires REAL NOT NULL)')

def rate_allowed(bucket, identity, limit, seconds):
    key = hashlib.sha256((bucket + ':' + identity).encode()).hexdigest()
    now = time.time()
    with state_connection() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('DELETE FROM rate_limits WHERE expires <= ?', (now,))
        row = db.execute('SELECT count FROM rate_limits WHERE key=?', (key,)).fetchone()
        if row and row['count'] >= limit:
            return False
        db.execute('INSERT INTO rate_limits VALUES (?, 1, ?) ON CONFLICT(key) DO UPDATE SET count=count+1', (key, now + seconds))
    return True

REQUEST_LIMITS = {'login': (15, 60), 'oauth_authorize': (15, 60), 'oauth_token': (120, 60),
                  'register': (5, 900), 'forgot_password': (5, 900), 'wake_device': (12, 60),
                  'add_device': (30, 60), 'update_device_settings': (30, 60), 'edit_device': (30, 60), 'mobile_wake': (12, 60),
                  'mobile_create_device': (30, 60), 'mobile_update_device': (30, 60)}

def create_challenge(email, purpose, code):
    challenge_id = secrets.token_urlsafe(32)
    with state_connection() as conn:
        conn.execute('DELETE FROM challenges WHERE email = ? AND purpose = ?', (email, purpose))
        conn.execute('INSERT INTO challenges (id, email, purpose, code_hash, expires) VALUES (?, ?, ?, ?, ?)',
                     (challenge_id, email, purpose, generate_password_hash(code), time.time() + 600))
    return challenge_id

def consume_challenge(challenge_id, purpose, code):
    with state_connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM challenges WHERE id = ? AND purpose = ?', (challenge_id, purpose)).fetchone()
        if not row or row['expires'] < time.time() or row['attempts'] >= 5:
            return None
        conn.execute('UPDATE challenges SET attempts = attempts + 1 WHERE id = ?', (challenge_id,))
        if not check_password_hash(row['code_hash'], code):
            return None
        conn.execute('DELETE FROM challenges WHERE id = ?', (challenge_id,))
        return row['email']

def csrf_token():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_urlsafe(32)
    return session['csrf_token']

app.jinja_env.globals['csrf_token'] = csrf_token

@app.before_request
def protect_forms():
    # Estas rutas verifican Bearer o firma del puente; no usan la sesión web.
    if request.endpoint and request.endpoint.startswith('windows.') and (request.path.startswith('/api/agent/v1/') or request.endpoint == 'windows.alexa_custom'):
        return
    if request.path.startswith('/api/mobile/v1/') and 'user_id' not in session:
        return jsonify(error='authentication_required', message='Inicia sesión para continuar.'), 401
    if (request.method == 'POST' or (request.path.startswith('/api/mobile/v1/') and request.method in ('PUT', 'DELETE'))) and request.endpoint not in ('oauth_token', 'alexa_smarthome'):
        expected = session.get('csrf_token')
        supplied = request.headers.get('X-CSRF-Token', '') if request.path.startswith('/api/mobile/v1/') else request.form.get('csrf_token', '')
        if not expected or not secrets.compare_digest(expected.encode('utf-8'), supplied.encode('utf-8')):
            if request.path.startswith('/api/mobile/v1/'):
                return jsonify(error='csrf_expired', message='La sesión del formulario expiró. Actualiza tus equipos.'), 400
            return 'El formulario expiró. Recarga la página e inténtalo de nuevo.', 400
    if request.method in ('POST', 'PUT', 'DELETE'):
        rule = REQUEST_LIMITS.get(request.endpoint)
        if request.endpoint == 'verify_account' and request.form.get('action') == 'resend':
            rule = (5, 900)
        bucket = 'wake_device' if request.endpoint == 'mobile_wake' else request.endpoint
        if rule and not rate_allowed(bucket, str(session.get('user_id') or request.remote_addr), *rule):
            if request.path.startswith('/api/mobile/v1/'):
                return jsonify(error='rate_limited', message='Demasiadas solicitudes. Espera antes de intentarlo de nuevo.'), 429, {'Retry-After': str(rule[1])}
            return 'Demasiadas solicitudes. Espera antes de intentarlo de nuevo.', 429, {'Retry-After': str(rule[1])}

@app.after_request
def response_security(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['X-Frame-Options'] = 'DENY'
    if app.config['SESSION_COOKIE_SECURE']:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000'
    if request.endpoint not in ('privacy_policy', 'terms_of_use', 'static'):
        response.headers['Cache-Control'] = 'no-store'
    return response

def valid_password(password):
    return len(password) >= 8 and bool(re.search(r'[A-Z]', password)) and bool(re.search(r'[0-9]', password)) and bool(re.search(r'[^\w\s]', password))

def normalize_mac(mac):
    clean = mac.strip().replace('-', '').replace(':', '')
    if not re.fullmatch(r'[0-9a-fA-F]{12}', clean):
        raise ValueError('Dirección MAC inválida')
    return ':'.join(clean[i:i+2].upper() for i in range(0, 12, 2))

from alexa_wol import AlexaGateway
alexa_gateway = AlexaGateway(state_connection)

# --- CREDENCIALES OAUTH Y AMAZON ---
MY_CLIENT_ID = os.environ.get('MY_CLIENT_ID', '')
MY_CLIENT_SECRET = os.environ.get('MY_CLIENT_SECRET', '')

# --- CONFIGURACIÓN SMTP DE BREVO ---
SMTP_SERVER = os.environ.get('SMTP_SERVER', 'smtp-relay.brevo.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))
SMTP_USER = os.environ.get('SMTP_USER', '')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')

# --- FUNCIÓN DE LOGS DE AUDITORÍA ---
def log_action(user_id, action, details):
    try:
        database.execute('INSERT INTO audit_logs (user_id, action, details) VALUES (%s, %s, %s)',
                         (user_id, action[:100], details[:255]))
    except database.pymysql.MySQLError:
        logging.warning('No se pudo guardar la auditoría en MariaDB.')

@app.errorhandler(database.pymysql.MySQLError)
def database_unavailable(error):
    logging.error('Falló una operación de MariaDB (%s).', type(error).__name__)
    if request.path.startswith(('/api/mobile/v1/', '/api/agent/v1/')):
        return jsonify(error='database_unavailable', message='No se pudo completar la operación. Inténtalo de nuevo más tarde.'), 503
    return 'No se pudo completar la operación. Inténtalo de nuevo más tarde.', 503

# --- FUNCIÓN DE ENVÍO DE CORREOS DE RECUPERACIÓN (CON LOGO) ---
def send_reset_email(to_email, reset_code):
    try:
        msg = MIMEMultipart()
        msg['From'] = os.environ.get('SMTP_FROM', 'Soporte WoL Pro <support@luiszamora.dev>')
        msg['To'] = to_email
        msg['Subject'] = 'Código para restablecer tu contraseña - WoL Pro'

        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; background-color: #0b0f19; color: #f8f9fa; padding: 20px; margin: 0;">
            <div style="max-width: 600px; background: #161b22; padding: 40px; border-radius: 12px; border: 1px solid #30363d; margin: 0 auto; box-shadow: 0 8px 24px rgba(0,0,0,0.5);">
                <div style="text-align: center; margin-bottom: 30px;">
                    <h1 style="color: #ffffff; font-size: 28px; margin: 0; font-weight: 800; letter-spacing: 1px;">
                        WoL<span style="color: #20c997; font-weight: 400;">Pro</span>
                    </h1>
                    <p style="color: #8b949e; font-size: 12px; margin-top: 5px; text-transform: uppercase; letter-spacing: 2px;">Smart Power Systems</p>
                </div>
                
                <p style="color: #c9d1d9;">Hola,</p>
                <p style="color: #c9d1d9;">Recibimos una solicitud para restablecer la contraseña de tu cuenta en <b>wol.luiszamora.dev</b>.</p>
                <p style="color: #c9d1d9;">Tu código de verificación de un solo uso es:</p>
                
                <div style="text-align: center; margin: 35px 0;">
                    <span style="font-size: 34px; font-weight: bold; background: #0b0f19; padding: 15px 30px; border-radius: 8px; border: 1px solid #30363d; letter-spacing: 6px; color: #20c997; display: inline-block;">{reset_code}</span>
                </div>
                
                <p style="color: #8b949e; font-size: 14px;">Este código expirará en breve. Si tú no solicitaste este cambio, puedes ignorar este mensaje de forma segura.</p>
                
                <hr style="border: none; border-top: 1px solid #30363d; margin: 30px 0;">
                <p style="font-size: 11px; color: #6e7681; text-align: center;">Enviado automáticamente por support@luiszamora.dev • Wake-on-LAN Pro</p>
            </div>
        </body>
        </html>
        """
        msg.attach(MIMEText(body, 'html'))

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=20) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(parseaddr(msg['From'])[1], to_email, msg.as_string())
        return True
    except Exception:
        logging.warning('No se pudo enviar el correo de restablecimiento.')
        return False

# --- FUNCIÓN DE ENVÍO DE CORREOS DE VERIFICACIÓN (CON LOGO) ---
def send_verification_email(to_email, verify_code):
    try:
        msg = MIMEMultipart()
        msg['From'] = os.environ.get('SMTP_FROM', 'Soporte WoL Pro <support@luiszamora.dev>')
        msg['To'] = to_email
        msg['Subject'] = 'Código de verificación de cuenta - WoL Pro'

        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; background-color: #0b0f19; color: #f8f9fa; padding: 20px; margin: 0;">
            <div style="max-width: 600px; background: #161b22; padding: 40px; border-radius: 12px; border: 1px solid #30363d; margin: 0 auto; box-shadow: 0 8px 24px rgba(0,0,0,0.5);">
                <div style="text-align: center; margin-bottom: 30px;">
                    <h1 style="color: #ffffff; font-size: 28px; margin: 0; font-weight: 800; letter-spacing: 1px;">
                        WoL<span style="color: #20c997; font-weight: 400;">Pro</span>
                    </h1>
                    <p style="color: #8b949e; font-size: 12px; margin-top: 5px; text-transform: uppercase; letter-spacing: 2px;">Smart Power Systems</p>
                </div>
                
                <p style="color: #c9d1d9;">Hola,</p>
                <p style="color: #c9d1d9;">Gracias por registrarte en <b>wol.luiszamora.dev</b>. Para activar tu cuenta y comenzar a usar el panel, introduce el siguiente código de verificación:</p>
                
                <div style="text-align: center; margin: 35px 0;">
                    <span style="font-size: 34px; font-weight: bold; background: #0b0f19; padding: 15px 30px; border-radius: 8px; border: 1px solid #30363d; letter-spacing: 6px; color: #20c997; display: inline-block;">{verify_code}</span>
                </div>
                
                <p style="color: #8b949e; font-size: 14px;">Si tú no creaste esta cuenta, puedes ignorar este mensaje de forma segura.</p>
                
                <hr style="border: none; border-top: 1px solid #30363d; margin: 30px 0;">
                <p style="font-size: 11px; color: #6e7681; text-align: center;">Enviado automáticamente por support@luiszamora.dev • Wake-on-LAN Pro</p>
            </div>
        </body>
        </html>
        """
        msg.attach(MIMEText(body, 'html'))

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=20) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(parseaddr(msg['From'])[1], to_email, msg.as_string())
        return True
    except Exception:
        logging.warning('No se pudo enviar el correo de verificación.')
        return False

# --- FUNCIÓN WAKE-ON-LAN ---
def send_wol(mac_address, host=None, port=None):
    try:
        mac_bytes = bytes.fromhex(normalize_mac(mac_address).replace(':', ''))
        data = b'\xff' * 6 + mac_bytes * 16
        
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.sendto(data, (host or os.environ.get('WOL_BROADCAST', '255.255.255.255'), int(port or os.environ.get('WOL_PORT', '9'))))
        return True
    except Exception as e:
        print(f"Error enviando WoL: {e}")
    return False

def wake_settings(form):
    method = form.get('wake_method', 'local')
    if method == 'local' and not app.config['ALLOW_LOCAL_WOL']:
        raise ValueError('Selecciona Alexa o Router por Internet para el servidor público.')
    if method not in ('local', 'router', 'alexa'):
        raise ValueError('Selecciona un método de encendido válido.')
    host = form.get('wake_host', '').strip().lower()
    try:
        port = int(form.get('wake_port') or '9')
    except ValueError:
        raise ValueError('El puerto debe ser un número entre 1 y 65535.')
    if not 1 <= port <= 65535:
        raise ValueError('El puerto debe estar entre 1 y 65535.')
    if method == 'router':
        if not host or len(host) > 253:
            raise ValueError('Introduce la IPv4 pública o el dominio DDNS de tu router.')
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if '.' not in host or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in host.split('.')):
                raise ValueError('Usa un dominio DDNS sin http://, rutas ni puerto.')
            if all(part.isdigit() for part in host.split('.')):
                raise ValueError('La dirección IPv4 no es válida.')
        else:
            if address.version != 4 or not address.is_global or address.is_multicast:
                raise ValueError('El destino del router debe ser una IPv4 pública.')
    else:
        host = None
        port = 9
    return method, host, port

def send_router_wol(mac, host, port):
    try:
        _, host, port = wake_settings({'wake_method': 'router', 'wake_host': host or '', 'wake_port': str(port)})
        addresses = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_DGRAM)
        address = addresses[0][4][0]
        resolved = ipaddress.ip_address(address)
        if not resolved.is_global or resolved.is_multicast:
            return False
        return send_wol(mac, address, port)
    except (OSError, ValueError, IndexError):
        return False

# ================= WEB ROUTES =================

def render_dashboard(**context):
    user_id = session['user_id']
    devices = database.fetch_all('SELECT id, name, mac, wake_method, wake_host, wake_port FROM devices WHERE user_sub = %s ORDER BY id', (str(user_id),))
    controls = agent_service.dashboard_data(user_id) if app.config['ENABLE_WINDOWS_AGENT'] else {}
    return render_template('dashboard.html', devices=devices, email=session.get('email'),
                           alexa_ready=alexa_gateway.is_linked(str(user_id)),
                           allow_local=app.config['ALLOW_LOCAL_WOL'], controls=controls, **context)

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    agent_return = session.pop('agent_return', '')
    if agent_return.startswith('/windows/link?'):
        return redirect(agent_return)
    
    return render_dashboard()

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        user = database.fetch_one('SELECT id, email, password, is_verified FROM users WHERE email = %s', (email,))
        
        if user and check_password_hash(user[2], password):
            # Permite el acceso si está verificado o si el valor es nulo/1
            if user[3] is not None and int(user[3]) == 0:
                error = 'Debes verificar tu correo electrónico antes de iniciar sesión.'
            else:
                session['user_id'] = user[0]
                session['email'] = user[1]
                log_action(user[0], "LOGIN_LOCAL", f"Inicio de sesión exitoso para {email}")
                return redirect(url_for('index'))
        else:
            error = 'Correo o contraseña incorrectos.'
            
    return render_template('login.html', error=error)

@app.route('/login/amazon')
def login_amazon():
    if not MY_CLIENT_ID or not MY_CLIENT_SECRET:
        return render_template('login.html', error='El acceso con Amazon no está configurado. Puedes entrar con tu correo y contraseña.'), 503
    session['amazon_state'] = secrets.token_urlsafe(32)
    amazon_auth_url = (
        f"https://www.amazon.com/ap/oa"
        f"?client_id={MY_CLIENT_ID}"
        f"&scope=profile"
        f"&response_type=code"
        f"&redirect_uri={os.environ.get('AMAZON_REDIRECT_URI', 'https://wol.luiszamora.dev/callback/amazon')}"
        f"&state={session['amazon_state']}"
    )
    return redirect(amazon_auth_url)

@app.route('/callback/amazon')
def callback_amazon():
    expected_state = session.pop('amazon_state', None)
    if not expected_state or not secrets.compare_digest(expected_state, request.args.get('state', '')):
        return 'Estado de autenticación inválido. Inicia sesión de nuevo.', 400
    code = request.args.get('code')
    if not code:
        return redirect(url_for('login'))
    
    token_url = "https://api.amazon.com/auth/o2/token"
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": MY_CLIENT_ID,
        "client_secret": MY_CLIENT_SECRET,
        "redirect_uri": os.environ.get('AMAZON_REDIRECT_URI', 'https://wol.luiszamora.dev/callback/amazon')
    }
    
    try:
        token_res = requests.post(token_url, data=payload, timeout=20)
        token_res.raise_for_status()
        token_data = token_res.json()
        access_token = token_data.get("access_token")

        if not access_token:
            return redirect(url_for('login'))

        profile_res = requests.get("https://api.amazon.com/user/profile", headers={"Authorization": f"Bearer {access_token}"}, timeout=20)
        profile_res.raise_for_status()
        profile_data = profile_res.json()

        amazon_unique_id = profile_data.get("user_id")
        if not amazon_unique_id:
            return redirect(url_for('login'))
        amazon_email = profile_data.get("email", f"{amazon_unique_id}@amazon.user")

        with database.connection() as conn, conn.cursor() as cursor:
            cursor.execute('SELECT id, email FROM users WHERE amazon_id = %s', (amazon_unique_id,))
            user = cursor.fetchone()
            if not user:
                cursor.execute('INSERT INTO users (email, password, amazon_id, is_verified) VALUES (%s, %s, %s, 1)',
                               (amazon_email, 'AUTH_AMAZON_SECURE', amazon_unique_id))
                user = (cursor.lastrowid, amazon_email)
        session['user_id'], session['email'] = user
        log_action(session['user_id'], "LOGIN_AMAZON", "Inicio de sesión vía Amazon exitoso")
        
    except Exception:
        logging.warning('No se pudo completar el acceso con Amazon.')
        return redirect(url_for('login'))

    return redirect(url_for('index'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    error = None
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']
        if len(email) > 150 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
            return render_template('register.html', error='Introduce un correo válido de hasta 150 caracteres.'), 400
        if not valid_password(password):
            return render_template('register.html', error='La contraseña debe tener al menos 8 caracteres, una mayúscula, un número y un símbolo.'), 400
        hashed_password = generate_password_hash(password)
        code = str(secrets.randbelow(900000) + 100000)
        
        try:
            with database.connection() as conn, conn.cursor() as cursor:
                cursor.execute('SELECT id, password, is_verified FROM users WHERE email = %s', (email,))
                existing = cursor.fetchone()
                if not existing:
                    cursor.execute('INSERT INTO users (email, password, is_verified, verification_code) VALUES (%s, %s, 0, %s)',
                                   (email, hashed_password, None))
            if existing:
                if not existing[2] and check_password_hash(existing[1], password):
                    session['pending_email'] = email
                    session['verify_challenge'] = create_challenge(email, 'verify', code)
                    flash('Código enviado.' if send_verification_email(email, code) else 'No se pudo enviar el correo. Puedes solicitarlo de nuevo.', 'info')
                    return redirect(url_for('verify_account'))
                return render_template('register.html', error='El correo ya está registrado.'), 400
            session['pending_email'] = email
            session['verify_challenge'] = create_challenge(email, 'verify', code)
            if not send_verification_email(email, code):
                flash('No se pudo enviar el correo. Puedes volver a solicitarlo.', 'danger')
            return redirect(url_for('verify_account'))
        except database.pymysql.IntegrityError:
            error = 'El correo ya está registrado o hubo un error en la base de datos.'
            
    return render_template('register.html', error=error)

@app.route('/verify', methods=['GET', 'POST'])
def verify_account():
    error = None
    if 'pending_email' not in session:
        return redirect(url_for('register'))

    if request.method == 'POST':
        if request.form.get('action') == 'resend':
            code = str(secrets.randbelow(900000) + 100000)
            session['verify_challenge'] = create_challenge(session['pending_email'], 'verify', code)
            flash('Código enviado.' if send_verification_email(session['pending_email'], code) else 'No se pudo enviar el correo. Revisa la configuración SMTP.', 'info')
            return redirect(url_for('verify_account'))
        entered_code = request.form['code']
        email = session['pending_email']

        user = database.fetch_one('SELECT id, verification_code FROM users WHERE email = %s', (email,))
        if user and consume_challenge(session.get('verify_challenge'), 'verify', entered_code) == email:
            database.execute('UPDATE users SET is_verified = 1, verification_code = NULL WHERE email = %s', (email,))

            session.pop('pending_email', None)
            session.pop('verify_challenge', None)
            log_action(user[0], "REGISTER_VERIFIED", f"Cuenta verificada exitosamente para {email}")
            return redirect(url_for('login'))
        else:
            error = "Código incorrecto o expirado. Puedes solicitar otro código."

    return render_template('verify_register.html', error=error)

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    error = None
    if request.method == 'POST':
        email = request.form['email']
        
        user = database.fetch_one('SELECT id FROM users WHERE email = %s', (email,))

        if user:
            code = str(secrets.randbelow(900000) + 100000)
            session['reset_challenge'] = create_challenge(email, 'reset', code)
            session['reset_email'] = email

            if send_reset_email(email, code):
                log_action(user[0], "FORGOT_PASSWORD", f"Solicitud de restablecimiento enviada a {email}")
                return redirect(url_for('reset_password'))
            else:
                error = "Error al enviar el correo. Inténtalo más tarde."
        else:
            error = "Si el correo está registrado, se enviaron las instrucciones."
            
    return render_template('forgot_password.html', error=error)

@app.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    error = None
    if 'reset_email' not in session:
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        entered_code = request.form['code']
        new_password = request.form['password']

        if not valid_password(new_password):
            return render_template('reset_password.html', error='La contraseña debe tener al menos 8 caracteres, una mayúscula, un número y un símbolo.'), 400
        if consume_challenge(session.get('reset_challenge'), 'reset', entered_code) == session['reset_email']:
            hashed_password = generate_password_hash(new_password)
            email = session['reset_email']

            database.execute('UPDATE users SET password = %s WHERE email = %s', (hashed_password, email))

            session.pop('reset_challenge', None)
            session.pop('reset_email', None)

            return redirect(url_for('login'))
        else:
            error = "Código incorrecto o expirado. Solicita otro código de recuperación."

    return render_template('reset_password.html', error=error)

@app.route('/privacy')
def privacy_policy():
    return render_template('privacy.html')

@app.route('/terms')
def terms_of_use():
    return render_template('terms.html')

@app.route('/logout')
def logout():
    if 'user_id' in session:
        log_action(session['user_id'], "LOGOUT", "Cierre de sesión")
    session.clear()
    return redirect(url_for('login'))

@app.route('/add', methods=['POST'])
def add_device():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    name = request.form['name'].strip()
    try:
        mac = normalize_mac(request.form['mac'])
    except ValueError:
        flash('Introduce una MAC válida, por ejemplo AA:BB:CC:DD:EE:FF.', 'danger')
        return redirect(url_for('index'))
    if not name or len(name) > 100:
        flash('Introduce un nombre de entre 1 y 100 caracteres.', 'danger')
        return redirect(url_for('index'))
    try:
        method, host, port = wake_settings(request.form)
    except ValueError as error:
        flash(str(error), 'danger')
        return redirect(url_for('index'))
    user_sub = str(session['user_id'])
    
    database.execute('INSERT INTO devices (name, mac, user_sub, wake_method, wake_host, wake_port) VALUES (%s, %s, %s, %s, %s, %s)',
                     (name, mac, user_sub, method, host, port))
    
    log_action(session['user_id'], "ADD_DEVICE", f"Dispositivo añadido: {name} ({mac})")
    return redirect(url_for('index'))

def wake_result(device_id, user_id):
    """Una sola implementación de encendido para panel y cliente móvil."""
    user_sub = str(user_id)
    row = database.fetch_one('SELECT name, mac, wake_method, wake_host, wake_port FROM devices WHERE id = %s AND user_sub = %s', (device_id, user_sub))
    if not row:
        return dict(error='device_not_found', message='Equipo no encontrado.', category='danger'), 404
    dev_name, dev_mac, method, host, port = row
    if method == 'alexa':
        return dict(error='alexa_required', message=f'Enciende {dev_name} desde la app Alexa o diciendo «Alexa, enciende {dev_name}». Para encender aquí, selecciona Router por Internet.', category='info'), 409
    if method == 'local' and not app.config['ALLOW_LOCAL_WOL']:
        return dict(error='local_unavailable', message='Cambia este equipo a Alexa o Router por Internet. La red local del servidor no alcanza tu casa.', category='warning'), 409
    if method not in ('router', 'local'):
        return dict(error='invalid_method', message='Revisa el método de encendido del equipo.', category='danger'), 409
    sent = send_router_wol(dev_mac, host, port) if method == 'router' else send_wol(dev_mac)
    if not sent:
        return dict(error='wake_failed', message=f'No se pudo enviar el paquete a {dev_name}. Revisa la MAC y la red del servidor.', category='danger'), 502
    log_action(user_id, "SEND_WOL", f"Orden WoL enviada a {dev_name} ({dev_mac})")
    return dict(message=f'Paquete de encendido enviado a {dev_name}. Esto no confirma que haya arrancado.', category='success', sent=True), 200


@app.route('/api/mobile/v1/devices')
def mobile_devices():
    if 'user_id' not in session:
        return jsonify(error='authentication_required', message='Inicia sesión para ver tus equipos.'), 401
    rows = database.fetch_all('SELECT id, name, mac, wake_method, wake_host, wake_port FROM devices WHERE user_sub = %s ORDER BY id', (str(session['user_id']),))
    devices = [dict(id=row[0], name=row[1], mac=row[2], wake_method=row[3],
                    can_wake=False) for row in rows]
    return jsonify(version=1, devices=devices, email=session.get('email'),
                   alexa_ready=alexa_gateway.is_linked(str(session['user_id'])), csrf_token=csrf_token())


def mobile_device_fields():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get('name'), str) or not isinstance(data.get('mac'), str):
        raise ValueError('Introduce el nombre y la dirección MAC del dispositivo.')
    if set(data) - {'name', 'mac'}:
        raise ValueError('Solo puedes modificar el nombre y la dirección MAC desde la app.')
    name = data['name'].strip()
    if not name or len(name) > 100:
        raise ValueError('Introduce un nombre de entre 1 y 100 caracteres.')
    return name, normalize_mac(data['mac'])


@app.route('/api/mobile/v1/devices', methods=['POST'])
def mobile_create_device():
    try:
        name, mac = mobile_device_fields()
    except ValueError as error:
        return jsonify(error='invalid_device', message=str(error)), 400
    database.execute('INSERT INTO devices (name, mac, user_sub, wake_method, wake_host, wake_port) VALUES (%s, %s, %s, %s, %s, %s)',
                     (name, mac, str(session['user_id']), 'alexa', '', 9))
    log_action(session['user_id'], 'ADD_DEVICE', f'Dispositivo añadido desde app: {name} ({mac})')
    return mobile_devices(), 201


@app.route('/api/mobile/v1/devices/<int:device_id>', methods=['PUT'])
def mobile_update_device(device_id):
    try:
        name, mac = mobile_device_fields()
    except ValueError as error:
        return jsonify(error='invalid_device', message=str(error)), 400
    count = database.execute('UPDATE devices SET name=%s, mac=%s WHERE id=%s AND user_sub=%s',
                             (name, mac, device_id, str(session['user_id'])))
    if not count:
        return jsonify(error='device_not_found', message='Dispositivo no encontrado.'), 404
    log_action(session['user_id'], 'UPDATE_DEVICE', f'Dispositivo actualizado desde app: {name} ({mac})')
    return mobile_devices()


@app.route('/api/mobile/v1/logout', methods=['POST'])
def mobile_logout():
    log_action(session['user_id'], 'LOGOUT', 'Cierre de sesión desde app')
    session.clear()
    return jsonify(message='Sesión cerrada.')


@app.route('/api/mobile/v1/devices/<int:device_id>/wake', methods=['POST'])
def mobile_wake(device_id):
    if 'user_id' not in session:
        return jsonify(error='authentication_required', message='Inicia sesión para encender tus equipos.'), 401
    row = database.fetch_one('SELECT name, wake_method FROM devices WHERE id=%s AND user_sub=%s', (device_id, str(session['user_id'])))
    if not row:
        return jsonify(error='device_not_found', message='Dispositivo no encontrado.'), 404
    if row[1] == 'alexa':
        return jsonify(error='alexa_required', message=f'Di «Alexa, enciende {row[0]}» o usa la app Alexa.'), 409
    return jsonify(error='coming_soon', message='El encendido directo desde la app estará disponible próximamente.'), 409


@app.route('/wake/<int:device_id>', methods=['POST'])
def wake_device(device_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    result, _ = wake_result(device_id, session['user_id'])
    flash(result['message'], result['category'])
    return redirect(url_for('index', _anchor=f'pc-{device_id}'))

@app.route('/devices/<int:device_id>/settings', methods=['POST'])
def update_device_settings(device_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    try:
        method, host, port = wake_settings(request.form)
    except ValueError as error:
        flash(str(error), 'danger')
        return redirect(url_for('index'))
    count = database.execute('UPDATE devices SET wake_method=%s, wake_host=%s, wake_port=%s WHERE id=%s AND user_sub=%s',
                             (method, host, port, device_id, str(session['user_id'])))
    flash('Método de encendido guardado.' if count else 'Equipo no encontrado.', 'success' if count else 'danger')
    return redirect(url_for('index'))

@app.post('/devices/<int:device_id>/edit')
def edit_device(device_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    owner = str(session['user_id'])
    if not database.fetch_one('SELECT id FROM devices WHERE id=%s AND user_sub=%s', (device_id, owner)):
        flash('Equipo no encontrado.', 'danger')
        return redirect(url_for('index'))
    try:
        name = request.form.get('name', '').strip()
        if not name or len(name) > 100:
            raise ValueError('Introduce un nombre de entre 1 y 100 caracteres.')
        mac = normalize_mac(request.form.get('mac', ''))
        method, host, port = wake_settings(request.form)
    except ValueError as error:
        flash(str(error), 'danger')
    else:
        database.execute('UPDATE devices SET name=%s,mac=%s,wake_method=%s,wake_host=%s,wake_port=%s WHERE id=%s AND user_sub=%s',
                         (name, mac, method, host, port, device_id, owner))
        log_action(session['user_id'], 'UPDATE_DEVICE', f'Equipo actualizado: {name} ({mac})')
        flash('Equipo actualizado. Si usas Alexa, vuelve a descubrir los dispositivos.', 'success')
    return redirect(url_for('index', _anchor=f'pc-{device_id}'))

@app.route('/delete/<int:device_id>', methods=['POST'])
def delete_device(device_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    user_sub = str(session['user_id'])
    count = database.execute('DELETE FROM devices WHERE id = %s AND user_sub = %s', (device_id, user_sub))
    
    if count:
        log_action(session['user_id'], "DELETE_DEVICE", f"Dispositivo ID {device_id} eliminado")
    return redirect(url_for('index'))


# ================= OAUTH2 & ALEXA ENDPOINTS =================

def alexa_client_config():
    return (os.environ.get('ALEXA_CLIENT_ID') or MY_CLIENT_ID,
            os.environ.get('ALEXA_CLIENT_SECRET') or MY_CLIENT_SECRET)

@app.route('/oauth/authorize', methods=['GET', 'POST'])
def oauth_authorize():
    configured_id, configured_secret = alexa_client_config()
    client_id = request.args.get('client_id', '')
    redirect_uri = request.args.get('redirect_uri', '')
    state = request.args.get('state', '')
    allowed = [uri.strip() for uri in os.environ.get('ALEXA_REDIRECT_URIS', '').split(',') if uri.strip()]
    if not configured_id or not configured_secret or not allowed:
        return 'La vinculación con Alexa no está configurada en el servidor.', 503
    if client_id != configured_id or redirect_uri not in allowed:
        return 'Cliente o URL de retorno no autorizado', 400
    if request.args.get('response_type') != 'code':
        return 'response_type debe ser code', 400
    challenge = request.args.get('code_challenge')
    if challenge and (request.args.get('code_challenge_method') != 'S256' or not re.fullmatch(r'[A-Za-z0-9_-]{43}', challenge)):
        return 'PKCE debe usar S256 con un desafío válido.', 400
    if request.method == 'POST':
        email = request.form.get('email', '')
        password = request.form.get('password', '')
        user = database.fetch_one('SELECT id, password, is_verified FROM users WHERE email = %s', (email,))
        if user and user[2] and check_password_hash(user[1], password):
            auth_code = secrets.token_urlsafe(32)
            with state_connection() as db:
                db.execute('INSERT INTO auth_codes VALUES (?, ?, ?, ?, ?, ?)',
                           (auth_code, str(user[0]), client_id, redirect_uri, time.time() + 300, challenge))
            from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl
            parts = urlsplit(redirect_uri)
            query = parse_qsl(parts.query) + [('code', auth_code), ('state', state)]
            log_action(user[0], 'ALEXA_LINKING', 'Autorización para Alexa emitida')
            return redirect(urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)))
        return render_template('oauth_login.html', error='Credenciales incorrectas o cuenta sin verificar.', client_id=client_id, redirect_uri=redirect_uri, state=state), 401
    return render_template('oauth_login.html', client_id=client_id, redirect_uri=redirect_uri, state=state)

@app.route('/oauth/token', methods=['POST'])
def oauth_token():
    configured_id, configured_secret = alexa_client_config()
    credentials = request.authorization
    if credentials and credentials.type.lower() == 'basic':
        client_id, client_secret = credentials.username or '', credentials.password or ''
    else:
        client_id = request.form.get('client_id', '')
        client_secret = request.form.get('client_secret', '')
    if not configured_id or not configured_secret or client_id != configured_id or not secrets.compare_digest(client_secret, configured_secret):
        return jsonify(error='invalid_client'), 401
    grant = request.form.get('grant_type')
    with state_connection() as db:
        db.execute('BEGIN IMMEDIATE')
        if grant == 'authorization_code':
            row = db.execute('SELECT * FROM auth_codes WHERE code = ?', (request.form.get('code', ''),)).fetchone()
            if not row or row['expires'] < time.time() or row['client_id'] != client_id or row['redirect_uri'] != request.form.get('redirect_uri'):
                return jsonify(error='invalid_grant'), 400
            if row['code_challenge']:
                import hashlib
                import base64
                verifier = request.form.get('code_verifier', '')
                computed = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
                if not re.fullmatch(r'[A-Za-z0-9._~-]{43,128}', verifier) or not secrets.compare_digest(computed, row['code_challenge']):
                    return jsonify(error='invalid_grant'), 400
            user_id = row['user_id']
            db.execute('DELETE FROM auth_codes WHERE code = ?', (row['code'],))
            refresh_token = secrets.token_urlsafe(48)
        elif grant == 'refresh_token':
            row = db.execute('SELECT * FROM auth_tokens WHERE refresh_token = ? AND client_id = ?',
                             (request.form.get('refresh_token', ''), client_id)).fetchone()
            if not row:
                return jsonify(error='invalid_grant'), 400
            user_id = row['user_id']
            refresh_token = row['refresh_token']
            db.execute('DELETE FROM auth_tokens WHERE refresh_token = ?', (refresh_token,))
        else:
            return jsonify(error='unsupported_grant_type'), 400
        access_token = secrets.token_urlsafe(48)
        db.execute('INSERT INTO auth_tokens VALUES (?, ?, ?, ?, ?)',
                   (access_token, refresh_token, user_id, client_id, time.time() + 3600))
    response = jsonify(access_token=access_token, token_type='Bearer', expires_in=3600, refresh_token=refresh_token)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Pragma'] = 'no-cache'
    return response


def alexa_error(directive, error_type, message):
    header = directive.get('header', {})
    event = {'header': {'namespace': 'Alexa', 'name': 'ErrorResponse', 'payloadVersion': '3', 'messageId': str(uuid.uuid4())},
             'payload': {'type': error_type, 'message': message}}
    if header.get('correlationToken'):
        event['header']['correlationToken'] = header['correlationToken']
    endpoint = directive.get('endpoint')
    if isinstance(endpoint, dict) and endpoint.get('endpointId'):
        event['endpoint'] = {'endpointId': endpoint['endpointId']}
    return jsonify(event=event)

@app.route('/alexa/smarthome', methods=['POST'])
def alexa_smarthome():
    bridge_secret = os.environ.get('ALEXA_BRIDGE_SECRET', '')
    if bridge_secret:
        timestamp = request.headers.get('X-Wol-Timestamp', '')
        signature = request.headers.get('X-Wol-Signature', '')
        try:
            recent = abs(time.time() - int(timestamp)) <= 300
        except ValueError:
            recent = False
        expected = hmac.new(bridge_secret.encode(), timestamp.encode() + b'.' + request.get_data(), hashlib.sha256).hexdigest()
        if not recent or not secrets.compare_digest(expected, signature):
            return jsonify(error='Puente no autorizado'), 401
    req = request.get_json(silent=True)
    directive = req.get('directive') if isinstance(req, dict) else None
    if not isinstance(directive, dict) or not isinstance(directive.get('header'), dict):
        return jsonify(error='Petición inválida'), 400
    header = directive['header']
    namespace, name = header.get('namespace'), header.get('name')
    endpoint = directive.get('endpoint', {})
    payload = directive.get('payload', {})
    if not isinstance(endpoint, dict) or not isinstance(payload, dict):
        return jsonify(error='Petición inválida'), 400
    scope = payload.get('grantee', {}) if namespace == 'Alexa.Authorization' else (payload.get('scope', {}) if namespace == 'Alexa.Discovery' else endpoint.get('scope', {}))
    if not isinstance(scope, dict) or scope.get('type') != 'BearerToken' or not isinstance(scope.get('token'), str):
        return alexa_error(directive, 'INVALID_AUTHORIZATION_CREDENTIAL', 'Falta el token de autorización.')
    with state_connection() as db:
        token = db.execute('SELECT user_id FROM auth_tokens WHERE access_token = ? AND expires > ?', (scope['token'], time.time())).fetchone()
    if not token:
        return alexa_error(directive, 'INVALID_AUTHORIZATION_CREDENTIAL', 'Token inválido o expirado. Vincula tu cuenta de nuevo.')
    user_id = token['user_id']
    if namespace == 'Alexa.Authorization' and name == 'AcceptGrant':
        grant = payload.get('grant', {})
        if not isinstance(grant, dict) or grant.get('type') != 'OAuth2.AuthorizationCode' or not isinstance(grant.get('code'), str) or not grant['code']:
            return jsonify(event={'header': {'namespace': 'Alexa.Authorization', 'name': 'ErrorResponse', 'payloadVersion': '3', 'messageId': str(uuid.uuid4())},
                                  'payload': {'type': 'ACCEPT_GRANT_FAILED', 'message': 'Código de autorización inválido.'}})
        try:
            alexa_gateway.accept_grant(user_id, grant['code'])
        except Exception as exc:
            response = getattr(exc, "response", None)
            status = getattr(response, "status_code", None)
            amazon_error = "no_disponible"
            if response is not None:
                try:
                    data = response.json()
                    if isinstance(data, dict):
                        amazon_error = str(
                            data.get("error", "sin_codigo")
                        )[:60]
                except ValueError:
                    pass
            app.logger.warning(
                "ALEXA_GRANT_DIAGNOSTICO tipo=%s http=%s codigo=%s",
                type(exc).__name__,
                status,
                amazon_error
            )
            return jsonify(event={'header': {'namespace': 'Alexa.Authorization', 'name': 'ErrorResponse', 'payloadVersion': '3', 'messageId': str(uuid.uuid4())},
                                  'payload': {'type': 'ACCEPT_GRANT_FAILED', 'message': 'No se pudo autorizar el envío de eventos a Alexa.'}})
        return jsonify(event={'header': {'namespace': 'Alexa.Authorization', 'name': 'AcceptGrant.Response', 'payloadVersion': '3', 'messageId': str(uuid.uuid4())}, 'payload': {}})
    if namespace == 'Alexa.Discovery' and name == 'Discover':
        devices = database.fetch_all('SELECT id, name, mac, wake_method FROM devices WHERE user_sub = %s', (user_id,))
        endpoints = []
        for dev_id, dev_name, dev_mac, method in devices:
            if method == 'local' and not app.config['ALLOW_LOCAL_WOL']:
                continue
            endpoints.append({'endpointId': str(dev_id), 'manufacturerName': 'WoL Pro', 'friendlyName': dev_name,
                              'description': 'Computadora con Wake-on-LAN', 'displayCategories': ['COMPUTER'],
                              'cookie': {}, 'capabilities': [
                                  {'type': 'AlexaInterface', 'interface': 'Alexa.PowerController', 'version': '3',
                                   'properties': {'supported': [{'name': 'powerState'}], 'retrievable': False, 'proactivelyReported': False}},
                                  {'type': 'AlexaInterface', 'interface': 'Alexa', 'version': '3'}]})
            if method == 'alexa':
                try:
                    formatted_mac = normalize_mac(dev_mac).replace(':', '-')
                except ValueError:
                    endpoints.pop()
                    continue
                endpoints[-1]['capabilities'].insert(0, {'type': 'AlexaInterface', 'interface': 'Alexa.WakeOnLANController',
                                                        'version': '3', 'configuration': {'MACAddresses': [formatted_mac]}, 'properties': {}})
        return jsonify(event={'header': {'namespace': 'Alexa.Discovery', 'name': 'Discover.Response', 'payloadVersion': '3', 'messageId': str(uuid.uuid4())},
                              'payload': {'endpoints': endpoints}})
    if namespace == 'Alexa.PowerController' and name in ('TurnOn', 'TurnOff'):
        endpoint_id = endpoint.get('endpointId')
        if not isinstance(endpoint_id, str) or not endpoint_id.isascii() or not endpoint_id.isdigit() or len(endpoint_id) > 10 or int(endpoint_id) > 2147483647:
            return alexa_error(directive, 'NO_SUCH_ENDPOINT', 'Identificador de equipo inválido.')
        device = database.fetch_one('SELECT name, mac, wake_method, wake_host, wake_port FROM devices WHERE id = %s AND user_sub = %s',
                                    (endpoint.get('endpointId'), user_id))
        if not device:
            return alexa_error(directive, 'NO_SUCH_ENDPOINT', 'No existe un equipo autorizado con ese identificador.')
        if name == 'TurnOff':
            return alexa_error(directive, 'INVALID_VALUE', 'Este equipo solo admite encendido mediante Wake-on-LAN.')
        if device[2] == 'local' and not app.config['ALLOW_LOCAL_WOL']:
            return alexa_error(directive, 'ENDPOINT_UNREACHABLE', 'Cambia el equipo a Alexa o Router por Internet en el panel.')
        if not rate_allowed('alexa_wake', user_id, 12, 60):
            return alexa_error(directive, 'RATE_LIMIT_EXCEEDED', 'Espera antes de enviar más órdenes de encendido.')
        if device[2] == 'alexa':
            try:
                alexa_gateway.enqueue(user_id, endpoint_id, header.get('correlationToken'), header.get('messageId'))
            except Exception:
                return alexa_error(directive, 'INTERNAL_ERROR', 'Vincula la skill y autoriza el envío de eventos de Alexa.')
            return jsonify(event={'header': {'namespace': 'Alexa', 'name': 'DeferredResponse', 'payloadVersion': '3',
                                             'messageId': str(uuid.uuid4()), 'correlationToken': header['correlationToken']},
                                  'payload': {'estimatedDeferralInSeconds': 5}})
        sent = send_router_wol(device[1], device[3], device[4]) if device[2] == 'router' else send_wol(device[1])
        if not sent:
            return alexa_error(directive, 'ENDPOINT_UNREACHABLE', 'No se pudo enviar el paquete de encendido.')
        log_action(user_id, 'ALEXA_WOL', f'Paquete de encendido enviado a {device[0]}')
        now = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
        return jsonify(context={'properties': [{'namespace': 'Alexa.PowerController', 'name': 'powerState', 'value': 'ON',
                                               'timeOfSample': now, 'uncertaintyInMilliseconds': 500}]},
                       event={'header': {'namespace': 'Alexa', 'name': 'Response', 'payloadVersion': '3', 'messageId': str(uuid.uuid4()),
                                         'correlationToken': header.get('correlationToken', '')},
                              'endpoint': {'endpointId': str(endpoint['endpointId'])}, 'payload': {}})
    return alexa_error(directive, 'INVALID_DIRECTIVE', 'Directiva no compatible.')

from windows_agent import install as install_windows_agent
agent_service = install_windows_agent(app, database, state_connection, rate_allowed, log_action, render_dashboard)

if __name__ == '__main__':
    from waitress import serve
    alexa_gateway.start()
    serve(app, host=os.environ.get('HOST', '127.0.0.1'), port=int(os.environ.get('PORT', '5000')), threads=4)
