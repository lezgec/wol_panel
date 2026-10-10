"""Play purchase validation and authenticated RTDN. No client-granted Premium."""
import base64
import hashlib
import hmac
import json
import os
import time
from datetime import datetime
from urllib.parse import quote
from flask import Blueprint, jsonify, request, session
from windows_agent import AgentError


class PlayBilling:
    def __init__(self, plans, secret):
        self.plans, self.secret = plans, str(secret)

    @property
    def enabled(self):
        return all(os.environ.get(key) for key in ('GOOGLE_PLAY_CREDENTIALS','GOOGLE_PLAY_PRODUCTS','BILLING_ACCOUNT_SECRET','GOOGLE_RTDN_AUDIENCE','GOOGLE_RTDN_SERVICE_EMAIL'))

    def account_id(self, user_id):
        return hmac.new(self.secret.encode(), ('play:'+str(user_id)).encode(), hashlib.sha256).hexdigest()

    def google(self, method, path, data=None):
        if not self.enabled:
            raise AgentError('billing_disabled', 'Las compras todavía no están activadas.', 409)
        from google.oauth2 import service_account
        from google.auth.transport.requests import AuthorizedSession
        try:
            credentials = service_account.Credentials.from_service_account_file(os.environ['GOOGLE_PLAY_CREDENTIALS'],
                            scopes=['https://www.googleapis.com/auth/androidpublisher'])
        except Exception:
            raise AgentError('billing_unavailable', 'La configuración de compras requiere revisión por soporte.', 503) from None
        # Only this fixed Google origin; purchase tokens never enter logs/admin responses.
        with AuthorizedSession(credentials) as client:
            try:
                response = client.request(method, 'https://androidpublisher.googleapis.com/androidpublisher/v3/applications/'+path,
                                          json=data, timeout=15, allow_redirects=False)
            except Exception:
                raise AgentError('verification_unavailable', 'Google Play no está disponible para verificar la compra. Inténtalo nuevamente.', 503) from None
            if response.status_code not in (200, 204):
                raise AgentError('verification_failed', 'No se pudo verificar la compra con Google Play. Inténtalo nuevamente.', 502)
            try:
                return response.json() if response.content else {}
            except ValueError:
                raise AgentError('verification_failed', 'Respuesta de compra inválida.', 502) from None

    def verify(self, user_id, token, revoked=False):
        if not isinstance(token,str) or not 10<=len(token)<=4096:
            raise AgentError('invalid_purchase','Compra inválida.')
        token_hash=hashlib.sha256(token.encode()).hexdigest()
        with self.plans.state() as db:
            previous=db.execute('SELECT user_id,state FROM plan_subscriptions WHERE token_hash=?',(token_hash,)).fetchone()
        if previous and previous['user_id']!=str(user_id):
            raise AgentError('purchase_owner','Esta compra está vinculada con otra cuenta.',409)
        if previous and previous['state']=='SUPERSEDED':
            return self.plans.public(user_id)
        package=os.environ.get('GOOGLE_PLAY_PACKAGE','dev.luiszamora.wolpro')
        response=self.google('GET',quote(package,safe='')+'/purchases/subscriptionsv2/tokens/'+quote(token,safe=''))
        identity=response.get('externalAccountIdentifiers',{}).get('obfuscatedExternalAccountId','')
        if not hmac.compare_digest(identity,self.account_id(user_id)):
            raise AgentError('purchase_owner','La compra no corresponde a esta cuenta WoL Pro.',403)
        products=set(os.environ.get('GOOGLE_PLAY_PRODUCTS','').split(','))
        items=response.get('lineItems',[])
        if not items or any(i.get('productId') not in products for i in items):
            raise AgentError('invalid_product','Producto no autorizado.',403)
        try:
            expiry=max(int(datetime.fromisoformat(i['expiryTime'].replace('Z','+00:00')).timestamp()) for i in items)
        except (KeyError,ValueError,TypeError):
            # Pending purchases may not have an expiry yet; never grant access.
            expiry=0
        state='SUBSCRIPTION_STATE_EXPIRED' if revoked else response.get('subscriptionState','UNKNOWN')
        active=state in ('SUBSCRIPTION_STATE_ACTIVE','SUBSCRIPTION_STATE_CANCELED','SUBSCRIPTION_STATE_IN_GRACE_PERIOD') and expiry>time.time()
        product=items[0]['productId']
        linked=response.get('linkedPurchaseToken')
        linked_hash=hashlib.sha256(linked.encode()).hexdigest() if linked else None
        with self.plans.state() as db:
            old=db.execute('SELECT user_id FROM plan_subscriptions WHERE token_hash=?',(linked_hash,)).fetchone() if linked_hash else None
        if old and old['user_id']!=str(user_id):
            raise AgentError('purchase_owner','La suscripción anterior pertenece a otra cuenta.',403)
        if active and response.get('acknowledgementState')=='ACKNOWLEDGEMENT_STATE_PENDING':
            self.google('POST',quote(package,safe='')+'/purchases/subscriptions/'+quote(product,safe='')+'/tokens/'+quote(token,safe='')+':acknowledge',{})
        now=int(time.time())
        with self.plans.state() as db:
            db.execute('BEGIN IMMEDIATE')
            previous=db.execute('SELECT user_id FROM plan_subscriptions WHERE token_hash=?',(token_hash,)).fetchone()
            if previous and previous['user_id']!=str(user_id):
                raise AgentError('purchase_owner','Compra utilizada en otra cuenta.',409)
            if linked_hash and active:
                db.execute("UPDATE plan_subscriptions SET state='SUPERSEDED',expires=0 WHERE token_hash=?",(linked_hash,))
            db.execute('INSERT INTO plan_subscriptions(token_hash,user_id,provider,token,product,state,expires,verified,auto_renew,order_id,linked_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(token_hash) DO UPDATE SET state=excluded.state,expires=excluded.expires,verified=excluded.verified,auto_renew=excluded.auto_renew,order_id=excluded.order_id',
                       (token_hash,str(user_id),'google_play',token,product,state,expiry,now,int(any(i.get('autoRenewingPlan',{}).get('autoRenewEnabled',False) for i in items)),response.get('latestOrderId'),linked_hash))
        return self.plans.public(user_id)

    def refresh(self):
        """Scheduled command complements RTDN and reconciles canceled/refunded access."""
        with self.plans.state() as db:
            rows=db.execute("SELECT user_id,token FROM plan_subscriptions WHERE provider='google_play' AND state NOT IN ('SUPERSEDED','SUBSCRIPTION_STATE_EXPIRED')").fetchall()
        failures=0
        for row in rows:
            try: self.verify(row['user_id'],row['token'])
            except Exception: failures+=1  # Never print provider exceptions containing tokens.
        return dict(checked=len(rows),failed=failures)


def install(app, billing, rate_allowed):
    bp=Blueprint('billing',__name__)

    @bp.errorhandler(AgentError)
    def error(exc): return jsonify(error=exc.code,message=exc.message),exc.status

    @bp.post('/api/mobile/v1/plan/purchase')
    def purchase():
        if not rate_allowed('purchase_verify', str(session['user_id']), 12, 300):
            raise AgentError('rate_limited', 'Espera antes de verificar más compras.', 429)
        data=request.get_json(silent=True) or {}
        billing.plans.require(session['user_id'])
        return jsonify(version=1,plan=billing.verify(session['user_id'],data.get('purchase_token')))

    @bp.post('/api/billing/google/rtdn')
    def notification():
        from google.oauth2 import id_token
        from google.auth.transport.requests import Request
        audience=os.environ.get('GOOGLE_RTDN_AUDIENCE')
        email=os.environ.get('GOOGLE_RTDN_SERVICE_EMAIL')
        auth=request.headers.get('Authorization','')
        if not audience or not email or not auth.startswith('Bearer '):
            raise AgentError('unauthorized','Notificación no autorizada.',401)
        try:
            claims=id_token.verify_oauth2_token(auth[7:],Request(),audience=audience)
            if claims.get('email')!=email or claims.get('email_verified') is not True:
                raise ValueError()
            envelope=request.get_json()
            raw=envelope['message']['data']
            if not isinstance(raw,str) or len(raw)>32768: raise ValueError()
            data=json.loads(base64.b64decode(raw,validate=True))
        except Exception:
            raise AgentError('unauthorized','Notificación no autorizada.',401) from None
        if data.get('packageName')!=os.environ.get('GOOGLE_PLAY_PACKAGE','dev.luiszamora.wolpro'):
            raise AgentError('invalid_package','Paquete inválido.',400)
        notice=data.get('subscriptionNotification')
        if not notice: return jsonify(status='ignored')
        token=notice.get('purchaseToken','')
        if not isinstance(token,str) or not 10<=len(token)<=4096:
            raise AgentError('invalid_purchase','Notificación de compra inválida.',400)
        with billing.plans.state() as db:
            owner=db.execute('SELECT user_id FROM plan_subscriptions WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if owner: billing.verify(owner['user_id'],token,revoked=notice.get('notificationType')==12)
        # Unmapped initial purchases are validated by the user's authenticated purchase/restore.
        return jsonify(status='processed' if owner else 'unmapped')

    app.register_blueprint(bp)
