"""Native mobile forms reuse existing accounts, challenges and cookie sessions."""
import re
import secrets
from flask import Blueprint, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

PUBLIC_ENDPOINTS = frozenset('mobile_auth.' + name for name in ('bootstrap', 'login', 'register', 'verify', 'resend', 'forgot', 'reset'))
RATE_BUCKETS = {'mobile_auth.login':'login', 'mobile_auth.register':'register', 'mobile_auth.forgot':'forgot_password', 'mobile_auth.resend':'verify_account', 'mobile_auth.verify':'native_verify', 'mobile_auth.reset':'reset_password'}

def install(app, host):
    bp = Blueprint('mobile_auth', __name__)
    dummy_hash = generate_password_hash(secrets.token_urlsafe(32))
    def fail(message, status=400, **extra):
        return jsonify(message=message, **extra), status
    def body():
        value = request.get_json(silent=True)
        return value if isinstance(value, dict) else None
    def email(value):
        return isinstance(value, str) and len(value) <= 150 and bool(re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value.strip()))
    def credentials(data):
        return data and email(data.get('email')) and isinstance(data.get('password'), str) and 0 < len(data['password']) <= 1024
    def authenticated():
        return jsonify(phase='authenticated', data=host.mobile_devices().get_json())
    def verification(address):
        code = str(secrets.randbelow(900000) + 100000)
        session['pending_email'] = address
        session['verify_challenge'] = host.create_challenge(address, 'verify', code)
        sent = host.send_verification_email(address, code)
        return jsonify(phase='verify', email=address, message='Introduce el código enviado a tu correo.' if sent else 'No pudimos enviar el correo. Puedes solicitar otro código.'), 200 if sent else 503

    @bp.get('/mobile/bridge')
    def bridge():
        return '<!doctype html><html><head><meta charset="utf-8"><title>WoL Pro</title></head><body></body></html>'

    @bp.get('/api/mobile/v1/auth/session')
    def bootstrap():
        if 'user_id' in session:
            return authenticated()
        return jsonify(phase='verify' if session.get('pending_email') else 'login', csrf_token=host.csrf_token(), email=session.get('pending_email'))

    @bp.post('/api/mobile/v1/auth/login')
    def login():
        data = body()
        if not credentials(data) or ('remember' in data and type(data['remember']) is not bool):
            return fail('Introduce un correo y una contraseña válidos.')
        address = data['email'].strip().lower()
        user = host.database.fetch_one('SELECT id,email,password,is_verified FROM users WHERE email=%s', (address,))
        valid = check_password_hash(user[2] if user else dummy_hash, data['password'])
        if not user or not valid:
            return fail('Correo o contraseña incorrectos.', 401, phase='login')
        plan = host.plans.snapshot(user[0])
        if plan['suspended']:
            return fail('Esta cuenta está suspendida. Contacta con soporte.', 403)
        if user[3] is not None and int(user[3]) == 0:
            if not host.rate_allowed('verify_account', request.remote_addr or 'unknown', 5, 900):
                return fail('Espera antes de solicitar otro código.', 429, phase='verify', email=address)
            return verification(address)
        host.revoke_mobile_session(); session.clear()
        session.update(user_id=user[0], email=user[1], plan_epoch=plan['session_epoch'])
        host.set_mobile_session(data.get('remember', False))
        host.log_action(user[0], 'LOGIN_LOCAL', 'Inicio de sesión desde la app móvil')
        return authenticated()

    @bp.post('/api/mobile/v1/auth/register')
    def register():
        data = body()
        if not credentials(data):
            return fail('Introduce un correo y una contraseña válidos.')
        if not host.valid_password(data['password']):
            return fail('La contraseña debe tener al menos 8 caracteres, una mayúscula, un número y un símbolo.')
        address = data['email'].strip().lower()
        try:
            with host.database.connection() as conn, conn.cursor() as cursor:
                cursor.execute('SELECT id,password,is_verified FROM users WHERE email=%s', (address,))
                existing = cursor.fetchone()
                if not existing:
                    cursor.execute('INSERT INTO users (email,password,is_verified,verification_code) VALUES (%s,%s,0,%s)', (address, generate_password_hash(data['password']), None))
            if existing and (existing[2] or not check_password_hash(existing[1], data['password'])):
                return fail('El correo ya está registrado. Inicia sesión o recupera tu contraseña.', 409)
            return verification(address)
        except host.database.pymysql.IntegrityError:
            return fail('El correo ya está registrado. Inicia sesión o recupera tu contraseña.', 409)

    @bp.post('/api/mobile/v1/auth/resend')
    def resend():
        if body() is None or not session.get('pending_email'):
            return fail('Inicia sesión o registra tu cuenta para solicitar un código.', phase='login')
        return verification(session['pending_email'])

    @bp.post('/api/mobile/v1/auth/verify')
    def verify():
        data = body(); address = session.get('pending_email')
        if not data or not address or not isinstance(data.get('code'), str) or not re.fullmatch(r'[0-9]{6}', data['code']):
            return fail('Introduce el código de seis dígitos.')
        if host.consume_challenge(session.get('verify_challenge'), 'verify', data['code']) != address:
            return fail('Código incorrecto o caducado. Puedes solicitar otro.')
        host.database.execute('UPDATE users SET is_verified=1,verification_code=NULL WHERE email=%s', (address,))
        user = host.database.fetch_one('SELECT id FROM users WHERE email=%s', (address,))
        session.pop('pending_email', None); session.pop('verify_challenge', None)
        host.log_action(user[0], 'REGISTER_VERIFIED', 'Correo verificado desde la app móvil')
        return jsonify(phase='login', message='Correo verificado. Ya puedes iniciar sesión.')

    @bp.post('/api/mobile/v1/auth/forgot')
    def forgot():
        data = body()
        if not data or not email(data.get('email')):
            return fail('Introduce un correo válido.')
        address = data['email'].strip().lower()
        session.pop('reset_challenge', None); session.pop('reset_email', None)
        user = host.database.fetch_one('SELECT id FROM users WHERE email=%s', (address,))
        if user:
            code = str(secrets.randbelow(900000) + 100000)
            session['reset_email'] = address
            session['reset_challenge'] = host.create_challenge(address, 'reset', code)
            host.send_reset_email(address, code)
            host.log_action(user[0], 'FORGOT_PASSWORD', 'Recuperación solicitada desde la app móvil')
        return jsonify(phase='reset', message='Si el correo está registrado, recibirás un código para cambiar la contraseña.')

    @bp.post('/api/mobile/v1/auth/reset')
    def reset():
        data = body()
        if not data or not isinstance(data.get('password'), str) or len(data['password']) > 1024 or not host.valid_password(data['password']):
            return fail('La contraseña debe tener al menos 8 caracteres, una mayúscula, un número y un símbolo.')
        code = data.get('code'); address = session.get('reset_email')
        if not isinstance(code, str) or not re.fullmatch(r'[0-9]{6}', code):
            return fail('Introduce el código de seis dígitos.')
        if not address or host.consume_challenge(session.get('reset_challenge'), 'reset', code) != address:
            return fail('Código incorrecto o caducado. Solicita otro código de recuperación.')
        host.database.execute('UPDATE users SET password=%s WHERE email=%s', (generate_password_hash(data['password']), address))
        session.pop('reset_email', None); session.pop('reset_challenge', None)
        return jsonify(phase='login', message='Contraseña actualizada. Ya puedes iniciar sesión.')

    app.register_blueprint(bp)
