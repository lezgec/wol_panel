"""Account entitlements. Private SQLite state shares the existing auth backup.

Every remote channel uses this service; UI flags never authorize an operation.
MariaDB user-row locks serialize device registration across processes.
"""
import hashlib
import json
import os
import secrets
import time
from flask import Blueprint, jsonify, request, session, render_template, redirect, url_for
from windows_agent import AgentError

DEFAULT_ADS = dict(enabled=False, banner=True, interstitial=True, rewarded=True,
                   web=True, reward_minutes=30, interval_seconds=600, daily_limit=3,
                   allowed_views=['home', 'devices', 'control', 'account', 'plan'])
SCHEMA = '''
CREATE TABLE IF NOT EXISTS plan_accounts (
 user_id TEXT PRIMARY KEY, selected_device INTEGER, suspended INTEGER NOT NULL DEFAULT 0,
 session_epoch INTEGER NOT NULL DEFAULT 0, ad_free_until INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS plan_grants (
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL,source TEXT NOT NULL,expires INTEGER NOT NULL,
 revoked INTEGER NOT NULL DEFAULT 0,created INTEGER NOT NULL,reason TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS plan_grants_owner ON plan_grants(user_id,expires);
CREATE TABLE IF NOT EXISTS plan_subscriptions (
 token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL,provider TEXT NOT NULL,token TEXT NOT NULL,
 product TEXT NOT NULL,state TEXT NOT NULL,expires INTEGER NOT NULL,verified INTEGER NOT NULL,
 auto_renew INTEGER NOT NULL DEFAULT 0,order_id TEXT,linked_hash TEXT);
CREATE INDEX IF NOT EXISTS plan_subscriptions_owner ON plan_subscriptions(user_id,expires);
CREATE TABLE IF NOT EXISTS plan_config (key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ad_tickets (
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL,kind TEXT NOT NULL,created INTEGER NOT NULL,
 expires INTEGER NOT NULL,used INTEGER NOT NULL DEFAULT 0,transaction_id TEXT UNIQUE,
 reward_minutes INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS admin_owners (
 user_id TEXT PRIMARY KEY,secret TEXT NOT NULL,last_counter INTEGER NOT NULL DEFAULT -1,
 enabled INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS admin_sessions (
 id_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL,expires INTEGER NOT NULL,csrf_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS admin_audit (
 id INTEGER PRIMARY KEY AUTOINCREMENT,actor TEXT NOT NULL,action TEXT NOT NULL,
 target TEXT NOT NULL,created INTEGER NOT NULL,before_json TEXT NOT NULL,
 after_json TEXT NOT NULL,reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS deletion_requests (
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL,created INTEGER NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending',UNIQUE(user_id,status));
'''


class Plans:
    def __init__(self, database, state_connection):
        self.db, self.state = database, state_connection
        self.billing = None
        with self.state() as db:
            db.executescript(SCHEMA)

    @staticmethod
    def row(db, user_id):
        return db.execute('SELECT * FROM plan_accounts WHERE user_id=?', (str(user_id),)).fetchone()

    def snapshot(self, user_id):
        now = int(time.time())
        with self.state() as db:
            account = self.row(db, user_id)
            grants = db.execute('SELECT source,expires FROM plan_grants WHERE user_id=? AND revoked=0 AND expires>?',
                                (str(user_id), now)).fetchall()
            paid = db.execute("SELECT provider AS source,expires FROM plan_subscriptions WHERE user_id=? AND state IN ('SUBSCRIPTION_STATE_ACTIVE','SUBSCRIPTION_STATE_CANCELED','SUBSCRIPTION_STATE_IN_GRACE_PERIOD') AND expires>?",
                              (str(user_id), now)).fetchall()
            rows = list(grants) + list(paid)
            winner = max(rows, key=lambda r: r['expires']) if rows else None
            suspended = bool(account and account['suspended'])
            premium = bool(winner) and not suspended
            return dict(tier='premium' if premium else 'free', device_limit=10 if premium else 1,
                        can_launch=premium, expires_at=winner['expires'] if winner else None,
                        source=winner['source'] if winner else 'free', suspended=suspended,
                        selected_device=account['selected_device'] if account else None,
                        session_epoch=account['session_epoch'] if account else 0,
                        ad_free_until=account['ad_free_until'] if account else 0)

    def devices(self, user_id, cursor=None):
        sql = 'SELECT id FROM devices WHERE user_sub=%s ORDER BY id'
        if cursor is not None:
            cursor.execute(sql, (str(user_id),))
            return [r[0] for r in cursor.fetchall()]
        return [r[0] for r in self.db.fetch_all(sql, (str(user_id),))]

    def active_devices(self, user_id, cursor=None, plan=None):
        plan = plan or self.snapshot(user_id)
        devices = self.devices(user_id, cursor)
        if plan['suspended']:
            return []
        # Preserve all saved PCs. A missing/deleted selection defaults deterministically.
        selected = plan['selected_device']
        if selected in devices:
            devices.remove(selected)
            devices.insert(0, selected)
        return devices[:plan['device_limit']]

    def require(self, user_id, device_id=None, kind=None, cursor=None):
        if self.billing and self.billing.enabled:
            # RTDN is immediate; this recheck also handles a lost notification.
            with self.state() as db:
                stale = db.execute("SELECT token FROM plan_subscriptions WHERE user_id=? AND expires>? AND verified<? AND state IN ('SUBSCRIPTION_STATE_ACTIVE','SUBSCRIPTION_STATE_CANCELED','SUBSCRIPTION_STATE_IN_GRACE_PERIOD')", (str(user_id), int(time.time()), int(time.time())-300)).fetchall()
            for receipt in stale:
                self.billing.verify(user_id, receipt['token'])
        plan = self.snapshot(user_id)
        if plan['suspended']:
            raise AgentError('account_suspended', 'Esta cuenta está suspendida. Contacta con soporte.', 403)
        if device_id is not None and device_id not in self.devices(user_id, cursor):
            raise AgentError('not_found', 'Equipo no encontrado.', 404)
        if device_id is not None and device_id not in self.active_devices(user_id, cursor, plan):
            raise AgentError('inactive_device', 'Selecciona este equipo en Mi plan o activa Premium.', 403)
        if kind == 'launch' and not plan['can_launch']:
            raise AgentError('premium_required', 'Abrir aplicaciones y ejecutar comandos requiere Premium.', 403)
        return plan

    def registration_guard(self, cursor, user_id):
        # All inserts (web, mobile, agent pairing) hold this same InnoDB row lock.
        cursor.execute('SELECT id FROM users WHERE id=%s FOR UPDATE', (user_id,))
        if not cursor.fetchone():
            raise AgentError('not_found', 'Cuenta no encontrada.', 404)
        plan = self.require(user_id)
        if len(self.devices(user_id, cursor)) >= plan['device_limit']:
            raise AgentError('device_limit', 'Alcanzaste el límite de equipos de tu plan. Los equipos guardados se conservan.', 403)

    def create_device(self, user_id, name, mac, method='alexa', host='', port=9):
        with self.db.connection() as conn, conn.cursor() as c:
            self.registration_guard(c, user_id)
            c.execute('INSERT INTO devices (name,mac,user_sub,wake_method,wake_host,wake_port) VALUES (%s,%s,%s,%s,%s,%s)',
                      (name, mac, str(user_id), method, host, port))
            return c.lastrowid

    def select(self, user_id, device_id):
        self.require(user_id)
        if device_id not in self.devices(user_id):
            raise AgentError('not_found', 'Equipo no encontrado.', 404)
        with self.state() as db:
            db.execute('INSERT OR IGNORE INTO plan_accounts(user_id) VALUES (?)', (str(user_id),))
            db.execute('UPDATE plan_accounts SET selected_device=? WHERE user_id=?', (device_id, str(user_id)))

    def ads_config(self):
        with self.state() as db:
            row = db.execute("SELECT value FROM plan_config WHERE key='ads'").fetchone()
        return {**DEFAULT_ADS, **(json.loads(row['value']) if row else {})}

    def public(self, user_id):
        plan = self.snapshot(user_id)
        devices = self.devices(user_id)
        active = self.active_devices(user_id, plan=plan)
        config = self.ads_config()
        with self.state() as db:
            subscription = db.execute('SELECT provider,product,state,expires,auto_renew FROM plan_subscriptions WHERE user_id=? ORDER BY verified DESC LIMIT 1', (str(user_id),)).fetchone()
            used_intro = db.execute("SELECT 1 FROM plan_subscriptions WHERE user_id=? AND expires>0 AND state!='SUBSCRIPTION_STATE_PENDING' LIMIT 1", (str(user_id),)).fetchone()
            promo_row = db.execute("SELECT value FROM plan_config WHERE key='promotion'").fetchone()
        promotion = json.loads(promo_row['value']) if promo_row else dict(enabled=True, starts_at=0, ends_at=0)
        promo_eligible = not used_intro and promotion['enabled'] and promotion['starts_at'] <= time.time() and (not promotion['ends_at'] or promotion['ends_at']>time.time())
        eligible = not plan['suspended'] and plan['tier'] == 'free' and plan['ad_free_until'] <= time.time()
        return {**plan, 'registered_devices': len(devices), 'active_devices': active,
                'subscription': dict(subscription) if subscription else None,
                'ads': {**config, 'enabled': bool(config['enabled'] and eligible)},
                'billing': {'enabled': bool(self.billing and self.billing.enabled), 'provider': 'google_play',
                            'account_id': self.billing.account_id(user_id) if self.billing else None,
                            'products': os.environ.get('GOOGLE_PLAY_PRODUCTS','').split(',') if self.billing and self.billing.enabled else [],
                            'intro_eligible': bool(promo_eligible),
                            'reference_prices': {'currency': 'USD', 'monthly': '2.99', 'yearly': '24.99', 'intro_year': '19.99'}}}

    def ad_ticket(self, user_id, kind):
        if kind not in ('rewarded', 'interstitial'):
            raise AgentError('invalid_input', 'Formato inválido.')
        now = int(time.time())
        policy = self.public(user_id)['ads']
        if not policy['enabled'] or not policy[kind]:
            raise AgentError('ads_disabled', 'La publicidad está desactivada.', 409)
        ticket = secrets.token_urlsafe(24)
        with self.state() as db:
            db.execute('BEGIN IMMEDIATE')
            if kind == 'interstitial':
                recent = db.execute("SELECT created FROM ad_tickets WHERE user_id=? AND kind='interstitial' ORDER BY created DESC LIMIT 1", (str(user_id),)).fetchone()
                count = db.execute("SELECT COUNT(*) FROM ad_tickets WHERE user_id=? AND kind='interstitial' AND created>=?", (str(user_id), now-now % 86400)).fetchone()[0]
                if (recent and recent['created'] > now-policy['interval_seconds']) or count >= policy['daily_limit']:
                    raise AgentError('ad_frequency', 'Todavía no corresponde mostrar un anuncio.', 429)
            else:
                recent = db.execute("SELECT id FROM ad_tickets WHERE user_id=? AND kind='rewarded' AND expires>? AND used=0", (str(user_id), now)).fetchone()
                if recent:
                    raise AgentError('reward_pending', 'Ya hay una recompensa pendiente.', 409)
            db.execute('INSERT INTO ad_tickets(id,user_id,kind,created,expires,reward_minutes) VALUES (?,?,?,?,?,?)',
                       (ticket, str(user_id), kind, now, now+600, policy['reward_minutes'] if kind == 'rewarded' else 0))
        return dict(ticket=ticket, expires_at=now+600, reward_minutes=policy['reward_minutes'] if kind == 'rewarded' else 0)

    def verified_reward(self, ticket, transaction_id):
        """Only call after verifying Google's signature. Client completion is insufficient."""
        now = int(time.time())
        with self.state() as db:
            db.execute('BEGIN IMMEDIATE')
            duplicate = db.execute('SELECT id FROM ad_tickets WHERE transaction_id=?', (transaction_id,)).fetchone()
            if duplicate:
                if duplicate['id'] != ticket:
                    raise AgentError('invalid_reward', 'Recompensa inválida.', 400)
                return
            row = db.execute("SELECT * FROM ad_tickets WHERE id=? AND kind='rewarded' AND used=0 AND expires>?", (ticket, now)).fetchone()
            if not row:
                raise AgentError('invalid_reward', 'Recompensa inválida o caducada.', 400)
            db.execute('UPDATE ad_tickets SET used=1,transaction_id=? WHERE id=?', (transaction_id, ticket))
            db.execute('INSERT OR IGNORE INTO plan_accounts(user_id) VALUES (?)', (row['user_id'],))
            # Reward replaces the remaining interval; no unbounded stacking.
            db.execute('UPDATE plan_accounts SET ad_free_until=? WHERE user_id=?', (now+row['reward_minutes']*60, row['user_id']))


def install(app, plans, rate_allowed):
    bp = Blueprint('plans', __name__)

    @bp.before_request
    def limit():
        if request.method == 'POST' and session.get('user_id') and not rate_allowed('plan_changes', str(session['user_id']), 20, 300):
            raise AgentError('rate_limited', 'Espera antes de enviar más solicitudes.', 429)

    @bp.errorhandler(AgentError)
    def error(exc):
        return jsonify(error=exc.code, message=exc.message), exc.status

    @bp.get('/api/mobile/v1/plan')
    def plan():
        return jsonify(version=1, plan=plans.public(session['user_id']))

    @bp.post('/api/mobile/v1/plan/device')
    def select():
        data = request.get_json(silent=True) or {}
        value = data.get('device_id')
        if type(value) is not int:
            raise AgentError('invalid_input', 'Selecciona un equipo.')
        plans.select(session['user_id'], value)
        return plan()

    @bp.post('/api/mobile/v1/ads/ticket')
    def ticket():
        return jsonify(plans.ad_ticket(session['user_id'], (request.get_json(silent=True) or {}).get('kind')))

    @bp.post('/account-deletion/request')
    def deletion_request():
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if request.form.get('confirmed') != 'yes':
            raise AgentError('confirmation_required', 'Confirma que deseas solicitar la eliminación.')
        with plans.state() as db:
            db.execute('BEGIN IMMEDIATE')
            opened = db.execute("SELECT id FROM deletion_requests WHERE user_id=? AND status IN ('pending','processing')", (str(session['user_id']),)).fetchone()
            if not opened:
                db.execute('INSERT OR IGNORE INTO deletion_requests(id,user_id,created) VALUES (?,?,?)',
                           (secrets.token_urlsafe(24), str(session['user_id']), int(time.time())))
        from flask import flash
        flash('Solicitud de eliminación registrada. Soporte verificará la identidad y tramitará la eliminación. Cancela por separado cualquier suscripción de Google Play.', 'info')
        return redirect(url_for('plans.page'))

    @bp.get('/mi-plan')
    def page():
        if 'user_id' not in session:
            return redirect(url_for('login'))
        devices = plans.db.fetch_all('SELECT id,name FROM devices WHERE user_sub=%s ORDER BY id', (str(session['user_id']),))
        return render_template('plan.html', plan=plans.public(session['user_id']), devices=devices)

    @bp.post('/mi-plan/equipo')
    def select_web():
        if 'user_id' not in session:
            return redirect(url_for('login'))
        value = request.form.get('device_id', type=int)
        if value is None:
            raise AgentError('invalid_input', 'Selecciona un equipo.')
        plans.select(session['user_id'], value)
        return redirect(url_for('plans.page'))

    app.register_blueprint(bp)
