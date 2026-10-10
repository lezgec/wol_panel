"""Control de PC. Cola MariaDB, autorización por PC y API sin cookies."""
import hashlib
import os
import re
import secrets
import time
import uuid
from urllib.parse import urlencode
from pathlib import Path
from flask import Blueprint, request, session, jsonify, redirect, url_for, flash, send_file


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def text(value, maximum=100):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum or any(ord(c) < 32 for c in value):
        raise AgentError('invalid_input', 'Introduce un nombre válido.', 400)
    return value.strip()


class AgentError(Exception):
    def __init__(self, code, message, status=400):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


class AgentService:
    def __init__(self, database):
        self.db = database

    @staticmethod
    def rows(cursor, sql, params=()):
        cursor.execute(sql, params)
        names = [col[0] for col in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]

    def all(self, sql, params=()):
        with self.db.connection() as conn, conn.cursor() as cursor:
            return self.rows(cursor, sql, params)

    def first(self, sql, params=()):
        rows = self.all(sql, params)
        return rows[0] if rows else None

    def authenticate(self, token):
        if not isinstance(token, str) or len(token) > 256:
            raise AgentError('unauthorized', 'Vincula este PC de nuevo.', 401)
        row = self.first('SELECT a.*, d.name AS computer_name, u.email FROM agent_connections a JOIN devices d ON d.id=a.device_id JOIN users u ON u.id=a.user_id WHERE a.token_hash=%s AND a.expires>%s AND a.revoked=0', (digest(token), int(time.time())))
        if not row:
            raise AgentError('unauthorized', 'Vincula este PC de nuevo.', 401)
        return row

    def pair_start(self, name):
        name = text(name)
        device_code = secrets.token_urlsafe(32)
        code = ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(8))
        code = code[:4] + '-' + code[4:]
        now = int(time.time())
        with self.db.connection() as conn, conn.cursor() as c:
            c.execute('DELETE FROM agent_pairings WHERE expires<%s', (now,))
            c.execute('INSERT INTO agent_pairings (device_code_hash,user_code_hash,computer_name,expires,status) VALUES (%s,%s,%s,%s,%s)', (digest(device_code), digest(code), name, now+300, 'pending'))
        return dict(device_code=device_code, user_code=code, expires_in=300, interval=5)

    def pairing(self, code):
        code = text(code, 20).upper()
        if not re.fullmatch(r'[A-Z2-9]{4}-[A-Z2-9]{4}', code):
            raise AgentError('invalid_code', 'Código inválido o caducado.')
        row = self.first('SELECT * FROM agent_pairings WHERE user_code_hash=%s AND expires>%s AND status=%s', (digest(code), int(time.time()), 'pending'))
        if not row:
            raise AgentError('invalid_code', 'Código inválido o caducado.')
        return row

    def authorize(self, code, user_id, device_id, new_name='', mac=''):
        pair = self.pairing(code)
        with self.db.connection() as conn, conn.cursor() as c:
            if device_id:
                rows = self.rows(c, 'SELECT id FROM devices WHERE id=%s AND user_sub=%s', (device_id, user_id))
                if not rows:
                    raise AgentError('not_found', 'Equipo no encontrado.', 404)
            else:
                name = text(new_name)
                clean = mac.strip().replace(':', '').replace('-', '')
                if not re.fullmatch(r'[a-fA-F0-9]{12}', clean):
                    raise AgentError('invalid_mac', 'Introduce la MAC del equipo que vas a vincular.')
                mac = ':'.join(clean[i:i+2].upper() for i in range(0, 12, 2))
                c.execute('INSERT INTO devices (name,mac,user_sub,wake_method,wake_host,wake_port) VALUES (%s,%s,%s,%s,%s,%s)', (name, mac, user_id, 'alexa', '', 9))
                device_id = c.lastrowid
            active = self.rows(c, 'SELECT id FROM agent_connections WHERE device_id=%s AND revoked=0 AND expires>%s', (device_id, int(time.time())))
            if active:
                raise AgentError('already_linked', 'Este equipo ya tiene un agente. Desvincúlalo primero.')
            c.execute('UPDATE agent_pairings SET user_id=%s,device_id=%s,status=%s WHERE device_code_hash=%s AND status=%s AND expires>%s', (user_id, device_id, 'authorized', pair['device_code_hash'], 'pending', int(time.time())))
            if c.rowcount != 1:
                raise AgentError('invalid_code', 'El código ya se utilizó o caducó.')

    def pair_finish(self, device_code):
        device_code = text(device_code, 256)
        now = int(time.time())
        with self.db.connection() as conn, conn.cursor() as c:
            rows = self.rows(c, 'SELECT * FROM agent_pairings WHERE device_code_hash=%s AND expires>%s', (digest(device_code), now))
            if not rows:
                raise AgentError('expired_token', 'La vinculación caducó.', 400)
            pair = rows[0]
            if pair['status'] == 'pending':
                raise AgentError('authorization_pending', 'Confirma el código en la web.', 428)
            c.execute('UPDATE agent_pairings SET status=%s WHERE device_code_hash=%s AND status=%s', ('consumed', digest(device_code), 'authorized'))
            if c.rowcount != 1:
                raise AgentError('expired_token', 'La vinculación ya se utilizó.', 400)
            current = self.rows(c, 'SELECT id FROM agent_connections WHERE device_id=%s AND revoked=0 AND expires>%s', (pair['device_id'], now))
            if current:
                raise AgentError('already_linked', 'Este equipo ya está vinculado.', 409)
            # Reemplazar solamente conexiones ya revocadas/caducadas.
            c.execute('DELETE FROM agent_connections WHERE device_id=%s', (pair['device_id'],))
            token, agent_id = secrets.token_urlsafe(48), str(uuid.uuid4())
            c.execute('INSERT INTO agent_connections (id,user_id,device_id,token_hash,expires,last_seen) VALUES (%s,%s,%s,%s,%s,%s)', (agent_id, pair['user_id'], pair['device_id'], digest(token), now+90*86400, 0))
            user = self.rows(c, 'SELECT email FROM users WHERE id=%s', (pair['user_id'],))[0]
            device = self.rows(c, 'SELECT name FROM devices WHERE id=%s', (pair['device_id'],))[0]
        return dict(access_token=token, agent_id=agent_id, email=user['email'], computer_name=device['name'], expires_at=now+90*86400)

    def heartbeat(self, agent, data):
        apps, allow_shutdown = data.get('apps'), data.get('allow_shutdown')
        if not isinstance(apps, list) or len(apps) > 40 or type(allow_shutdown) is not bool:
            raise AgentError('invalid_catalog', 'Catálogo inválido.')
        clean = []
        for app in apps:
            if not isinstance(app, dict) or set(app) != {'id', 'name'}:
                raise AgentError('invalid_catalog', 'Solo se admiten identificadores y nombres del catálogo autorizado.')
            try:
                key = str(uuid.UUID(app['id']))
            except (ValueError, TypeError, AttributeError):
                raise AgentError('invalid_catalog', 'Identificador de aplicación inválido.') from None
            clean.append((key, text(app['name'])))
        if len({key for key, _ in clean}) != len(clean):
            raise AgentError('invalid_catalog', 'Aplicaciones duplicadas.')
        with self.db.connection() as conn, conn.cursor() as c:
            c.execute('UPDATE agent_connections SET last_seen=%s,allow_shutdown=%s WHERE id=%s AND revoked=0', (int(time.time()), int(allow_shutdown), agent['id']))
            if c.rowcount != 1:
                raise AgentError('unauthorized', 'Vincula este PC de nuevo.', 401)
            previous = self.rows(c, 'SELECT app_key,name FROM agent_apps WHERE agent_id=%s', (agent['id'],))
            if {(row['app_key'], row['name']) for row in previous} != set(clean):
                c.execute('DELETE FROM agent_apps WHERE agent_id=%s', (agent['id'],))
                for key, name in clean:
                    c.execute('INSERT INTO agent_apps (agent_id,app_key,name) VALUES (%s,%s,%s)', (agent['id'], key, name))
        return dict(email=agent['email'], computer_name=agent['computer_name'])

    def enqueue(self, user_id, agent_id, kind, app_key, dedupe):
        now = int(time.time())
        with self.db.connection() as conn, conn.cursor() as c:
            rows = self.rows(c, 'SELECT * FROM agent_connections WHERE id=%s AND user_id=%s AND revoked=0 AND expires>%s FOR UPDATE', (agent_id, user_id, now))
            if not rows:
                raise AgentError('not_found', 'Agente no encontrado.', 404)
            agent = rows[0]
            if agent['last_seen'] < now-20:
                raise AgentError('offline', 'El PC está desconectado o el agente no está abierto.', 409)
            if kind == 'shutdown':
                if not agent['allow_shutdown']:
                    raise AgentError('not_allowed', 'Autoriza el apagado en el agente de Windows.', 409)
            elif kind == 'launch':
                if not self.rows(c, 'SELECT app_key FROM agent_apps WHERE agent_id=%s AND app_key=%s', (agent_id, app_key)):
                    raise AgentError('not_allowed', 'La aplicación o el comando ya no está autorizado en este PC.', 409)
            else:
                raise AgentError('invalid_action', 'Acción inválida.')
            dedupe_hash = digest(str(user_id)+':'+dedupe)
            existing = self.rows(c, 'SELECT id FROM agent_commands WHERE dedupe_hash=%s', (dedupe_hash,))
            if existing:
                return existing[0]['id']
            command_id = str(uuid.uuid4())
            # MariaDB: solicitudes simultáneas con la misma clave comparten orden.
            c.execute('INSERT INTO agent_commands (id,user_id,agent_id,kind,app_key,created,expires,status,dedupe_hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE dedupe_hash=VALUES(dedupe_hash)', (command_id, user_id, agent_id, kind, app_key, now, now+60, 'pending', dedupe_hash))
            command_id = self.rows(c, 'SELECT id FROM agent_commands WHERE dedupe_hash=%s FOR UPDATE', (dedupe_hash,))[0]['id']
        return command_id

    def execute_action(self, user_id, action_id, dedupe):
        action = self.first('SELECT * FROM agent_actions WHERE id=%s AND user_id=%s', (action_id, user_id))
        if not action:
            raise AgentError('not_found', 'Acción no encontrada.', 404)
        return self.enqueue(user_id, action['agent_id'], action['kind'], action['app_key'], dedupe)

    def claim(self, agent):
        now = int(time.time())
        with self.db.connection() as conn, conn.cursor() as c:
            # Serializar consumidores por PC antes de tomar bloqueos del índice de cola.
            if not self.rows(c, 'SELECT id FROM agent_connections WHERE id=%s AND revoked=0 AND expires>%s FOR UPDATE', (agent['id'], now)):
                raise AgentError('unauthorized', 'Vincula este PC de nuevo.', 401)
            c.execute('UPDATE agent_commands SET status=%s,result=%s WHERE agent_id=%s AND status=%s AND expires<=%s', ('expired', 'expired', agent['id'], 'pending', now))
            # Nunca reencolar una orden cuyo efecto pudo ocurrir antes de perder la conexión.
            c.execute('UPDATE agent_commands SET status=%s,result=%s WHERE agent_id=%s AND status IN (%s,%s) AND expires<%s', ('uncertain', 'uncertain', agent['id'], 'claimed', 'scheduled', now-120))
            cancelled = self.rows(c, 'SELECT id FROM agent_commands WHERE agent_id=%s AND cancel_requested=1 AND status IN (%s,%s)', (agent['id'], 'claimed', 'scheduled'))
            pending = self.rows(c, 'SELECT id,kind,app_key,expires FROM agent_commands WHERE agent_id=%s AND status=%s AND expires>%s ORDER BY created,id LIMIT 1', (agent['id'], 'pending', now))
            command = None
            if pending:
                row = pending[0]
                claim_token = secrets.token_urlsafe(32)
                c.execute('UPDATE agent_commands SET status=%s,claim_hash=%s WHERE id=%s AND status=%s', ('claimed', digest(claim_token), row['id'], 'pending'))
                if c.rowcount == 1:
                    command = dict(row, claim_token=claim_token)
        return dict(command=command, cancel_commands=[row['id'] for row in cancelled], server_time=now)

    def report(self, agent, command_id, data):
        status, receipt = data.get('status'), data.get('claim_token')
        if status not in ('scheduled', 'executed', 'failed', 'cancelled', 'uncertain') or not isinstance(receipt, str):
            raise AgentError('invalid_report', 'Resultado inválido.')
        with self.db.connection() as conn, conn.cursor() as c:
            rows = self.rows(c, 'SELECT * FROM agent_commands WHERE id=%s AND agent_id=%s FOR UPDATE', (command_id, agent['id']))
            if not rows or rows[0]['claim_hash'] != digest(receipt):
                raise AgentError('not_found', 'Orden no encontrada.', 404)
            row = rows[0]
            if row['status'] in ('claimed', 'scheduled'):
                if status == 'scheduled' and row['kind'] != 'shutdown':
                    raise AgentError('invalid_report', 'Solo el apagado permite una cuenta atrás.')
                c.execute('UPDATE agent_commands SET status=%s,result=%s WHERE id=%s AND status IN (%s,%s)', (status, status, command_id, 'claimed', 'scheduled'))
            elif row['status'] != status:
                raise AgentError('already_finished', 'La orden ya terminó.', 409)
        return dict(status=status)


    def dashboard_data(self, user):
        now = int(time.time())
        agents = self.all('SELECT a.id,a.device_id,a.last_seen,a.allow_shutdown,a.expires,a.revoked,d.name FROM agent_connections a JOIN devices d ON d.id=a.device_id WHERE a.user_id=%s', (user,))
        apps = self.all('SELECT p.agent_id,p.app_key,p.name FROM agent_apps p JOIN agent_connections a ON a.id=p.agent_id WHERE a.user_id=%s AND a.revoked=0 ORDER BY p.name', (user,))
        actions = self.all('SELECT x.* FROM agent_actions x JOIN agent_connections a ON a.id=x.agent_id WHERE x.user_id=%s AND a.revoked=0 ORDER BY x.name', (user,))
        self.db.execute('UPDATE agent_commands SET status=%s,result=%s WHERE user_id=%s AND status=%s AND expires<=%s', ('expired', 'expired', user, 'pending', now))
        self.db.execute('UPDATE agent_commands SET status=%s,result=%s WHERE user_id=%s AND status IN (%s,%s) AND expires<%s', ('uncertain', 'uncertain', user, 'claimed', 'scheduled', now-120))
        commands = self.all('SELECT q.* FROM agent_commands q JOIN agent_connections a ON a.id=q.agent_id JOIN devices d ON d.id=a.device_id WHERE q.user_id=%s ORDER BY q.created DESC,q.id DESC LIMIT 30', (user,))
        result = {}
        for pc in agents:
            pc['online'] = not pc['revoked'] and pc['expires'] > now and pc['last_seen'] >= now-20
            pc['active'] = not pc['revoked'] and pc['expires'] > now
            pc['apps'] = [item for item in apps if item['agent_id'] == pc['id']]
            pc['actions'] = [item for item in actions if item['agent_id'] == pc['id']]
            pc['commands'] = [item for item in commands if item['agent_id'] == pc['id']]
            pc['nonce'] = secrets.token_urlsafe(24)
            result[pc['device_id']] = pc
        return result


def install(app, database, state_connection, rate_allowed, audit, render_dashboard):
    service = AgentService(database)
    bp = Blueprint('windows', __name__)
    app.config['ENABLE_WINDOWS_AGENT'] = os.environ.get('ENABLE_WINDOWS_AGENT', '0') == '1'

    @app.context_processor
    def feature_context():
        ready = app.config['ENABLE_WINDOWS_AGENT'] and download_ready()
        return dict(windows_agent_enabled=app.config['ENABLE_WINDOWS_AGENT'],
                    agent_download_ready=ready,
                    agent_download_is_installer=ready and download_path().suffix.lower() == '.exe')

    def download_path():
        # Only server configuration selects the file; request arguments never select paths.
        path = Path(app.config['WINDOWS_AGENT_DOWNLOAD_PATH']).expanduser().resolve()
        # Preserve existing deployments until the operator copies the new installer.
        if path.name == 'WoLPro-Agent-Setup.exe' and not path.is_file():
            portable = path.with_name('WoLPro-Agent-win-x64.zip')
            if portable.is_file():
                return portable
        return path

    def download_ready():
        try:
            path = download_path()
            return path.suffix.lower() in ('.zip', '.exe') and path.is_file() and path.stat().st_size > 0
        except OSError:
            return False

    @bp.before_request
    def guard():
        if not app.config['ENABLE_WINDOWS_AGENT']:
            return jsonify(error='disabled', message='Control de PC no habilitado.'), 404
        if request.path.startswith('/windows') and 'user_id' not in session:
            if request.path == '/windows/link':
                session['agent_return'] = '/windows/link?' + urlencode({'code': request.args.get('code', '')[:20]})
            return redirect(url_for('login'))
        if request.path.startswith('/api/agent/v1/') and request.method == 'POST' and not request.is_json:
            return jsonify(error='json_required'), 415
        identity = request.remote_addr or 'unknown'
        if not rate_allowed('windows_ip', identity, 240, 60):
            return jsonify(error='rate_limited'), 429, {'Retry-After': '60'}

    @bp.errorhandler(AgentError)
    def error(exc):
        if request.path.startswith('/windows'):
            flash(exc.message, 'warning')
            return redirect(url_for('windows.link')) if request.path == '/windows/link' else panel_return()
        return jsonify(error=exc.code, message=exc.message), exc.status

    def body():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise AgentError('invalid_json', 'Petición inválida.')
        return data

    def panel_return():
        device_id = request.form.get('return_device', '')
        anchor = 'pc-' + device_id if device_id.isascii() and device_id.isdigit() and len(device_id) <= 10 else None
        return redirect(url_for('index', _anchor=anchor))

    def agent():
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            raise AgentError('unauthorized', 'Vincula este PC de nuevo.', 401)
        return service.authenticate(auth[7:])

    @bp.get('/windows/download')
    def download_agent():
        if not download_ready():
            return 'La descarga del agente todavía no está disponible. Inténtalo más tarde.', 503
        try:
            path = download_path()
            installer = path.suffix.lower() == '.exe'
            return send_file(path, mimetype='application/octet-stream' if installer else 'application/zip', as_attachment=True,
                             download_name='WoLPro-Agent-Setup.exe' if installer else 'WoLPro-Agent-win-x64.zip', conditional=True, max_age=0)
        except OSError:
            return 'La descarga del agente no está disponible temporalmente.', 503

    @bp.post('/api/agent/v1/pair/start')
    def pair_start():
        if not rate_allowed('windows_pair', request.remote_addr or 'unknown', 10, 900):
            return jsonify(error='rate_limited'), 429
        result = service.pair_start(body().get('computer_name'))
        base = os.environ.get('PUBLIC_BASE_URL', '').rstrip('/')
        result['verification_uri'] = base + '/windows/link'
        return jsonify(result)

    @bp.post('/api/agent/v1/pair/poll')
    def pair_poll():
        return jsonify(service.pair_finish(body().get('device_code')))

    @bp.post('/api/agent/v1/heartbeat')
    def heartbeat():
        return jsonify(service.heartbeat(agent(), body()))

    @bp.post('/api/agent/v1/commands/claim')
    def claim():
        body()
        return jsonify(service.claim(agent()))

    @bp.post('/api/agent/v1/commands/<command_id>/report')
    def report(command_id):
        return jsonify(service.report(agent(), command_id, body()))

    @bp.post('/api/agent/v1/commands/<command_id>/authorize')
    def authorize_command(command_id):
        current, data = agent(), body()
        row = service.first('SELECT * FROM agent_commands WHERE id=%s AND agent_id=%s', (command_id, current['id']))
        if not row or row['claim_hash'] != digest(text(data.get('claim_token'), 256)):
            raise AgentError('not_found', 'Orden no encontrada.', 404)
        allowed = row['status'] in ('claimed', 'scheduled') and not row['cancel_requested'] and row['expires'] > int(time.time())
        if row['kind'] == 'shutdown':
            allowed = allowed and bool(current['allow_shutdown'])
        else:
            allowed = allowed and bool(service.first('SELECT app_key FROM agent_apps WHERE agent_id=%s AND app_key=%s', (current['id'], row['app_key'])))
        return jsonify(allowed=allowed)

    @bp.post('/api/agent/v1/unlink')
    def unlink():
        current = agent()
        database.execute('UPDATE agent_connections SET revoked=1,allow_shutdown=0 WHERE id=%s', (current['id'],))
        database.execute('UPDATE agent_commands SET cancel_requested=1 WHERE agent_id=%s AND status IN (%s,%s,%s)', (current['id'], 'pending', 'claimed', 'scheduled'))
        return jsonify(status='revoked')

    @bp.route('/windows/link', methods=['GET', 'POST'])
    def link():
        code = request.values.get('code', '').strip().upper()
        pairing = service.pairing(code) if code else None
        if request.method == 'POST':
            if not rate_allowed('windows_authorize', str(session['user_id']), 10, 300):
                raise AgentError('rate_limited', 'Espera antes de vincular más equipos.', 429)
            try:
                device_id = int(request.form.get('device_id', '0'))
            except ValueError:
                raise AgentError('invalid_input', 'Selecciona un equipo.') from None
            service.authorize(code, session['user_id'], device_id, request.form.get('name', ''), request.form.get('mac', ''))
            audit(session['user_id'], 'AGENT_LINK', 'PC autorizado mediante código temporal')
            return render_dashboard(link_complete=True)
        selected = request.args.get('device_id', type=int)
        return render_dashboard(show_link=True, pair_code=code, pairing=pairing, selected_device=selected)

    @bp.get('/windows')
    def panel():
        return render_dashboard()

    @bp.post('/windows/agents/<agent_id>/revoke')
    def revoke(agent_id):
        changed = database.execute('UPDATE agent_connections SET revoked=1,allow_shutdown=0 WHERE id=%s AND user_id=%s', (agent_id, session['user_id']))
        if not changed:
            raise AgentError('not_found', 'Agente no encontrado.', 404)
        database.execute('UPDATE agent_commands SET cancel_requested=1 WHERE agent_id=%s AND status IN (%s,%s,%s)', (agent_id, 'pending', 'claimed', 'scheduled'))
        audit(session['user_id'], 'AGENT_REVOKE', 'Acceso de PC revocado')
        flash('PC desvinculado.', 'success')
        return panel_return()

    @bp.post('/windows/actions')
    def create_action():
        user, name = session['user_id'], text(request.form.get('name'))
        agent_id, kind = request.form.get('agent_id'), request.form.get('kind')
        linked = service.first('SELECT * FROM agent_connections WHERE id=%s AND user_id=%s AND revoked=0 AND expires>%s', (agent_id, user, int(time.time())))
        if not linked:
            raise AgentError('not_found', 'Selecciona un PC vinculado.', 404)
        key = request.form.get('app_key') if kind == 'launch' else None
        if kind == 'launch':
            if not service.first('SELECT app_key FROM agent_apps WHERE agent_id=%s AND app_key=%s', (agent_id, key)):
                raise AgentError('not_allowed', 'Selecciona una aplicación o un comando permitido.')
        elif kind != 'shutdown' or not linked['allow_shutdown']:
            raise AgentError('not_allowed', 'Autoriza el apagado en Windows primero.')
        if service.first('SELECT id FROM agent_actions WHERE user_id=%s AND name=%s', (user, name)):
            raise AgentError('duplicate_name', 'Ya existe una acción con ese nombre.')
        database.execute('INSERT INTO agent_actions (id,user_id,agent_id,name,kind,app_key) VALUES (%s,%s,%s,%s,%s,%s)', (str(uuid.uuid4()), user, agent_id, name, kind, key))
        flash('Acción creada.', 'success')
        return panel_return()

    @bp.post('/windows/actions/<action_id>/run')
    def run_action(action_id):
        if not rate_allowed('windows_run', str(session['user_id']), 12, 60):
            raise AgentError('rate_limited', 'Espera antes de enviar más órdenes.', 429)
        nonce = text(request.form.get('nonce'), 100)
        command_id = service.execute_action(session['user_id'], action_id, 'web:'+action_id+':'+nonce)
        audit(session['user_id'], 'AGENT_COMMAND', 'Orden Windows '+command_id)
        flash('Orden enviada. Consulta el resultado en el historial.', 'success')
        return panel_return()

    @bp.post('/windows/actions/<action_id>/delete')
    def delete_action(action_id):
        database.execute('DELETE FROM agent_actions WHERE id=%s AND user_id=%s', (action_id, session['user_id']))
        return panel_return()

    @bp.post('/windows/commands/<command_id>/cancel')
    def cancel_command(command_id):
        with database.connection() as conn, conn.cursor() as c:
            rows = service.rows(c, 'SELECT status FROM agent_commands WHERE id=%s AND user_id=%s', (command_id, session['user_id']))
            if not rows:
                raise AgentError('not_found', 'Orden no encontrada.', 404)
            c.execute('UPDATE agent_commands SET cancel_requested=1 WHERE id=%s AND status IN (%s,%s,%s)', (command_id, 'pending', 'claimed', 'scheduled'))
            c.execute('UPDATE agent_commands SET status=%s,result=%s WHERE id=%s AND status=%s', ('cancelled', 'cancelled', command_id, 'pending'))
        flash('Cancelación solicitada. Si la acción ya se ejecutó, no puede deshacerse.', 'info')
        return panel_return()

    from alexa_windows import register_custom
    register_custom(bp, service, state_connection, rate_allowed, audit)
    app.register_blueprint(bp)
    return service
