"""Owner-only administration. Independent sessions, TOTP and audited mutations."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import struct
import time
from flask import Blueprint, jsonify, request
from werkzeug.security import check_password_hash
from windows_agent import AgentError
from monetization import DEFAULT_ADS


def totp(secret, counter):
    key = base64.b32decode(secret, casefold=True)
    value = hmac.new(key, struct.pack('>Q', counter), hashlib.sha1).digest()
    offset = value[-1] & 15
    return str((struct.unpack('>I', value[offset:offset+4])[0] & 0x7fffffff) % 1000000).zfill(6)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def install(app, plans, rate_allowed):
    bp = Blueprint('admin_api', __name__, url_prefix='/api/admin/v1')

    @bp.errorhandler(AgentError)
    def error(exc):
        return jsonify(error=exc.code, message=exc.message), exc.status

    def origin():
        expected = os.environ.get('ADMIN_ORIGIN', request.host_url.rstrip('/'))
        if request.headers.get('Origin') != expected:
            raise AgentError('invalid_origin', 'Origen no autorizado.', 403)

    def identity():
        value = request.cookies.get('wol_admin', '')
        with plans.state() as db:
            row = db.execute('SELECT s.* FROM admin_sessions s JOIN admin_owners o ON o.user_id=s.user_id WHERE s.id_hash=? AND s.expires>? AND o.enabled=1',
                             (digest(value), int(time.time()))).fetchone()
        if not row or plans.snapshot(row['user_id'])['suspended']:
            raise AgentError('authentication_required', 'Inicia sesión como administrador.', 401)
        if request.method != 'GET':
            origin()
            supplied = request.headers.get('X-Admin-CSRF', '')
            if not hmac.compare_digest(row['csrf_hash'], digest(supplied)):
                raise AgentError('invalid_csrf', 'Actualiza tu sesión de administración.', 403)
        return row['user_id']

    def body():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise AgentError('invalid_input', 'Introduce los datos de la operación.')
        return data

    def reason(data):
        value = data.get('reason', '')
        if not isinstance(value, str) or not 5 <= len(value.strip()) <= 500:
            raise AgentError('reason_required', 'Escribe un motivo de entre 5 y 500 caracteres.')
        return value.strip()

    def audit(db, actor, action, target, before, after, why):
        db.execute('INSERT INTO admin_audit(actor,action,target,created,before_json,after_json,reason) VALUES (?,?,?,?,?,?,?)',
                   (str(actor), action, str(target), int(time.time()), json.dumps(before), json.dumps(after), why))

    def user(user_id):
        row = plans.db.fetch_one('SELECT id,email,is_verified FROM users WHERE id=%s', (user_id,))
        if not row:
            raise AgentError('not_found', 'Cuenta no encontrada.', 404)
        return dict(id=row[0], email=row[1], verified=bool(row[2]))

    @bp.post('/login')
    def login():
        origin()
        if not rate_allowed('admin_login', request.remote_addr, 5, 900):
            raise AgentError('rate_limited', 'Espera antes de intentar nuevamente.', 429)
        data = body()
        email, password, code = data.get('email'), data.get('password'), data.get('code')
        if not all(isinstance(v, str) for v in (email, password, code)) or len(password)>512 or len(email)>254 or len(code)!=6:
            raise AgentError('unauthorized', 'Credenciales inválidas.', 401)
        account = plans.db.fetch_one('SELECT id,password,is_verified FROM users WHERE email=%s', (email.strip().lower(),))
        if not account or not account[2] or not check_password_hash(account[1], password) or plans.snapshot(account[0])['suspended']:
            raise AgentError('unauthorized', 'Credenciales inválidas.', 401)
        token, csrf, now = secrets.token_urlsafe(32), secrets.token_urlsafe(32), int(time.time())
        with plans.state() as db:
            db.execute('BEGIN IMMEDIATE')
            owner = db.execute('SELECT * FROM admin_owners WHERE user_id=? AND enabled=1', (str(account[0]),)).fetchone()
            counter = now//30
            match = next((c for c in (counter-1,counter,counter+1) if owner and c>owner['last_counter'] and hmac.compare_digest(totp(owner['secret'],c),code)), None)
            if match is None:
                raise AgentError('unauthorized', 'Credenciales inválidas o código ya utilizado.', 401)
            db.execute('UPDATE admin_owners SET last_counter=? WHERE user_id=?', (match, str(account[0])))
            db.execute('DELETE FROM admin_sessions WHERE expires<=?', (now,))
            db.execute('INSERT INTO admin_sessions VALUES (?,?,?,?)', (digest(token),str(account[0]),now+1800,digest(csrf)))
            audit(db, account[0], 'admin_login', account[0], {}, {}, 'Inicio de sesión con contraseña y TOTP')
        response = jsonify(user_id=account[0], csrf=csrf, expires_at=now+1800)
        response.set_cookie('wol_admin',token,httponly=True,secure=app.config['SESSION_COOKIE_SECURE'],samesite='Strict',path='/api/admin/v1',max_age=1800)
        response.set_cookie('wol_admin_csrf',csrf,httponly=True,secure=app.config['SESSION_COOKIE_SECURE'],samesite='Strict',path='/api/admin/v1',max_age=1800)
        return response

    @bp.get('/session')
    def current():
        return jsonify(user_id=identity(), csrf=request.cookies.get('wol_admin_csrf'))

    @bp.post('/logout')
    def logout():
        actor = identity()
        with plans.state() as db:
            db.execute('DELETE FROM admin_sessions WHERE id_hash=?', (digest(request.cookies.get('wol_admin','')),))
            audit(db,actor,'admin_logout',actor,{}, {},'Cierre de sesión')
        response=jsonify(status='ok')
        for name in ('wol_admin','wol_admin_csrf'):
            response.delete_cookie(name,path='/api/admin/v1')
        return response

    @bp.get('/overview')
    def overview():
        identity()
        total=plans.db.fetch_one('SELECT COUNT(*) FROM users')[0]
        with plans.state() as db:
            ids=db.execute("SELECT DISTINCT user_id FROM plan_grants WHERE revoked=0 AND expires>? UNION SELECT user_id FROM plan_subscriptions WHERE expires>? AND state IN ('SUBSCRIPTION_STATE_ACTIVE','SUBSCRIPTION_STATE_CANCELED','SUBSCRIPTION_STATE_IN_GRACE_PERIOD')",(int(time.time()),int(time.time()))).fetchall()
            pending=db.execute("SELECT COUNT(*) FROM deletion_requests WHERE status='pending'").fetchone()[0]
            subscriptions=db.execute('SELECT state,COUNT(*) AS count FROM plan_subscriptions GROUP BY state').fetchall()
        premium=sum(plans.snapshot(r['user_id'])['tier']=='premium' for r in ids)
        now=int(time.time())
        connected=plans.db.fetch_one('SELECT COUNT(*) FROM agent_connections a LEFT JOIN agent_presence p ON p.agent_id=a.id WHERE a.revoked=0 AND a.expires>%s AND (a.last_seen>=%s OR (p.expires>%s AND p.last_seen>=%s))',(now,now-20,now,now-20))[0]
        errors=plans.db.fetch_one('SELECT COUNT(*) FROM agent_commands WHERE created>%s AND status IN (%s,%s)',(now-86400,'failed','uncertain'))[0]
        return jsonify(users=total,premium=premium,free=total-premium,deletions_pending=pending,
                       connected_pcs=connected,command_errors_24h=errors,
                       subscriptions=[dict(r) for r in subscriptions],ads=plans.ads_config(),
                       services=dict(billing_configured=bool(plans.billing and plans.billing.enabled),ads_configured=bool(os.environ.get('ADMOB_REWARDED_UNIT')),alexa_configured=bool(os.environ.get('ALEXA_CLIENT_ID'))),
                       revenue_status='Sin informes financieros conectados')

    @bp.get('/users')
    def users():
        identity()
        query=request.args.get('q','').strip()[:100]
        rows=plans.db.fetch_all('SELECT id,email,is_verified FROM users WHERE email LIKE %s ORDER BY id LIMIT 100',('%'+query+'%',))
        return jsonify(users=[dict(id=r[0],email=r[1],verified=bool(r[2]),plan=plans.public(r[0])) for r in rows])

    @bp.get('/users/<int:user_id>')
    def detail(user_id):
        identity()
        with plans.state() as db:
            subscriptions=db.execute('SELECT provider,product,state,expires,verified,auto_renew FROM plan_subscriptions WHERE user_id=?',(str(user_id),)).fetchall()
            grants=db.execute('SELECT id,source,expires,revoked,created,reason FROM plan_grants WHERE user_id=?',(str(user_id),)).fetchall()
        devices=plans.db.fetch_all('SELECT id,name,wake_method FROM devices WHERE user_sub=%s ORDER BY id',(str(user_id),))
        return jsonify(user=user(user_id),plan=plans.public(user_id),devices=[dict(id=r[0],name=r[1],wake_method=r[2]) for r in devices],subscriptions=[dict(r) for r in subscriptions],grants=[dict(r) for r in grants])

    @bp.post('/users/<int:user_id>/courtesy')
    def courtesy(user_id):
        actor=identity(); user(user_id); data=body(); why=reason(data)
        expires=data.get('expires_at'); now=int(time.time())
        if type(expires) is not int or not now<expires<=now+366*86400:
            raise AgentError('invalid_expiry','Selecciona una fecha futura, de hasta un año.')
        before=plans.snapshot(user_id)
        grant=secrets.token_urlsafe(24)
        with plans.state() as db:
            db.execute('INSERT INTO plan_grants VALUES (?,?,?,?,?,?,?)',(grant,str(user_id),'courtesy',expires,0,now,why))
            audit(db,actor,'courtesy_granted',user_id,before,dict(id=grant,expires_at=expires),why)
        return jsonify(plan=plans.public(user_id))

    @bp.post('/users/<int:user_id>/courtesy/revoke')
    def revoke_grant(user_id):
        actor=identity(); user(user_id); data=body(); why=reason(data)
        with plans.state() as db:
            rows=db.execute("SELECT id,expires FROM plan_grants WHERE user_id=? AND source='courtesy' AND revoked=0",(str(user_id),)).fetchall()
            db.execute("UPDATE plan_grants SET revoked=1 WHERE user_id=? AND source='courtesy'",(str(user_id),))
            audit(db,actor,'courtesy_revoked',user_id,[dict(r) for r in rows],{},why)
        return jsonify(plan=plans.public(user_id))

    @bp.post('/users/<int:user_id>/status')
    def status(user_id):
        actor=identity(); user(user_id); data=body(); why=reason(data)
        suspended=data.get('suspended')
        if type(suspended) is not bool or str(user_id)==actor:
            raise AgentError('invalid_input','No puedes suspender tu propia cuenta administrativa.')
        before=plans.snapshot(user_id)
        with plans.state() as db:
            db.execute('INSERT OR IGNORE INTO plan_accounts(user_id) VALUES (?)',(str(user_id),))
            db.execute('UPDATE plan_accounts SET suspended=?,session_epoch=session_epoch+1 WHERE user_id=?',(int(suspended),str(user_id)))
            db.execute('DELETE FROM mobile_sessions WHERE user_id=?',(str(user_id),))
            db.execute('DELETE FROM admin_sessions WHERE user_id=?',(str(user_id),))
            db.execute('DELETE FROM auth_tokens WHERE user_id=?',(str(user_id),))
            audit(db,actor,'account_status',user_id,before,dict(suspended=suspended),why)
        return jsonify(plan=plans.public(user_id))

    @bp.post('/users/<int:user_id>/revoke-access')
    def revoke_access(user_id):
        actor=identity(); user(user_id); data=body(); why=reason(data)
        # Pending commands are canceled before existing agent credentials are revoked.
        plans.db.execute('UPDATE agent_commands SET cancel_requested=1 WHERE user_id=%s AND status IN (%s,%s,%s)',(user_id,'pending','claimed','scheduled'))
        plans.db.execute('UPDATE agent_connections SET revoked=1,allow_shutdown=0 WHERE user_id=%s',(user_id,))
        with plans.state() as db:
            db.execute('INSERT OR IGNORE INTO plan_accounts(user_id) VALUES (?)',(str(user_id),))
            db.execute('UPDATE plan_accounts SET session_epoch=session_epoch+1 WHERE user_id=?',(str(user_id),))
            db.execute('DELETE FROM mobile_sessions WHERE user_id=?',(str(user_id),))
            db.execute('DELETE FROM admin_sessions WHERE user_id=?',(str(user_id),))
            db.execute('DELETE FROM auth_tokens WHERE user_id=?',(str(user_id),))
            audit(db,actor,'access_revoked',user_id,{},dict(web=True,mobile=True,alexa=True,agents=True),why)
        return jsonify(status='revoked')

    @bp.route('/ads',methods=['GET','POST'])
    def ads():
        actor=identity()
        if request.method=='GET': return jsonify(ads=plans.ads_config())
        data=body(); why=reason(data); config=data.get('ads')
        if not isinstance(config,dict) or set(config)!=set(DEFAULT_ADS):
            raise AgentError('invalid_input','Configuración publicitaria incompleta.')
        for key in ('enabled','banner','interstitial','rewarded','web'):
            if type(config[key]) is not bool: raise AgentError('invalid_input','Interruptor inválido.')
        views=config.get('allowed_views')
        if not isinstance(views,list) or len(views)>5 or any(v not in DEFAULT_ADS['allowed_views'] for v in views) or len(set(views))!=len(views):
            raise AgentError('invalid_input','Pantallas publicitarias inválidas.')
        for key,low,high in (('reward_minutes',1,60),('interval_seconds',600,86400),('daily_limit',0,3)):
            if type(config[key]) is not int or not low<=config[key]<=high: raise AgentError('invalid_input','Límites publicitarios inválidos.')
        # Enabling requires an SDK build and configured providers; no unconfigured live ads.
        if config['enabled'] and not os.environ.get('ADS_LIVE_READY')=='1':
            raise AgentError('ads_not_ready','Primero configura los proveedores, el consentimiento y la nueva compilación.',409)
        before=plans.ads_config()
        with plans.state() as db:
            db.execute("INSERT INTO plan_config(key,value) VALUES ('ads',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps(config),))
            audit(db,actor,'ads_updated','global',before,config,why)
        return jsonify(ads=config)

    @bp.route('/promotion',methods=['GET','POST'])
    def promotion():
        actor=identity()
        with plans.state() as db:
            row=db.execute("SELECT value FROM plan_config WHERE key='promotion'").fetchone()
        before=json.loads(row['value']) if row else dict(enabled=True,starts_at=0,ends_at=0)
        if request.method=='GET': return jsonify(promotion=before,reference_price='USD 19.99 primer año; USD 24.99 renovación',store_notice='El precio real y la oferta se configuran en Google Play.')
        data=body(); why=reason(data); value=data.get('promotion')
        if not isinstance(value,dict) or set(value)!={'enabled','starts_at','ends_at'} or type(value['enabled']) is not bool or any(type(value[k]) is not int or value[k]<0 for k in ('starts_at','ends_at')) or (value['ends_at'] and value['ends_at']<=value['starts_at']):
            raise AgentError('invalid_input','Fechas de promoción inválidas.')
        with plans.state() as db:
            db.execute("INSERT INTO plan_config VALUES ('promotion',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps(value),))
            audit(db,actor,'promotion_updated','global',before,value,why)
        return jsonify(promotion=value)

    @bp.get('/audit')
    def history():
        identity()
        with plans.state() as db:
            rows=db.execute('SELECT * FROM admin_audit ORDER BY id DESC LIMIT 200').fetchall()
        return jsonify(events=[dict(r) for r in rows])

    @bp.get('/deletions')
    def deletions():
        identity()
        with plans.state() as db:
            rows=db.execute('SELECT * FROM deletion_requests ORDER BY created DESC LIMIT 100').fetchall()
        return jsonify(requests=[dict(r) for r in rows])

    @bp.post('/deletions/<request_id>/status')
    def deletion_status(request_id):
        actor=identity(); data=body(); why=reason(data)
        state=data.get('status')
        if state not in ('pending','processing','completed','rejected'):
            raise AgentError('invalid_input','Estado inválido.')
        with plans.state() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM deletion_requests WHERE id=?',(request_id,)).fetchone()
            if not row: raise AgentError('not_found','Solicitud no encontrada.',404)
            duplicate=db.execute('SELECT id FROM deletion_requests WHERE user_id=? AND status=? AND id<>?',(row['user_id'],state,request_id)).fetchone()
            if duplicate: raise AgentError('deletion_state_conflict','Ya existe otra solicitud con ese estado para esta cuenta.',409)
            db.execute('UPDATE deletion_requests SET status=? WHERE id=?',(state,request_id))
            audit(db,actor,'deletion_status',row['user_id'],dict(row),dict(status=state),why)
        return jsonify(status=state)

    app.register_blueprint(bp)
