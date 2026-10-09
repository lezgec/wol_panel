"""Autorización y WakeUp por el gateway oficial de Alexa."""
import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
import requests

GATEWAYS = {'NA': 'https://api.amazonalexa.com/v3/events',
            'EU': 'https://api.eu.amazonalexa.com/v3/events',
            'FE': 'https://api.fe.amazonalexa.com/v3/events'}


class AlexaGateway:
    def __init__(self, connection):
        self.connection = connection
        self._worker = None
        with self.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS alexa_grants (user_id TEXT PRIMARY KEY, access_token TEXT NOT NULL, refresh_token TEXT NOT NULL, expires REAL NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS alexa_jobs (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, endpoint_id TEXT NOT NULL, correlation TEXT NOT NULL, directive_id TEXT UNIQUE NOT NULL, created REAL NOT NULL, status TEXT NOT NULL)')

    def is_linked(self, user_id):
        with self.connection() as db:
            return db.execute('SELECT 1 FROM alexa_grants WHERE user_id=?', (user_id,)).fetchone() is not None

    def exchange(self, **grant):
        client_id = os.environ.get('ALEXA_EVENT_CLIENT_ID', '')
        secret = os.environ.get('ALEXA_EVENT_CLIENT_SECRET', '')
        if not client_id or not secret:
            raise RuntimeError('Faltan las credenciales de Send Alexa Events.')
        response = requests.post('https://api.amazon.com/auth/o2/token',
                                 data=dict(client_id=client_id, client_secret=secret, **grant), timeout=5)
        response.raise_for_status()
        token = response.json()
        if not token.get('access_token') or float(token.get('expires_in', 0)) <= 0:
            raise RuntimeError('Amazon no devolvió un token válido.')
        return token

    def accept_grant(self, user_id, code):
        token = self.exchange(grant_type='authorization_code', code=code)
        if not token.get('refresh_token'):
            raise RuntimeError('Amazon no devolvió el token de renovación.')
        with self.connection() as db:
            db.execute('INSERT OR REPLACE INTO alexa_grants VALUES (?, ?, ?, ?)',
                       (user_id, token['access_token'], token['refresh_token'], time.time() + float(token['expires_in'])))

    def access_token(self, user_id, force=False):
        with self.connection() as db:
            row = db.execute('SELECT * FROM alexa_grants WHERE user_id=?', (user_id,)).fetchone()
        if not row:
            raise RuntimeError('Vincula la skill y autoriza Send Alexa Events.')
        if not force and row['expires'] > time.time() + 30:
            return row['access_token']
        token = self.exchange(grant_type='refresh_token', refresh_token=row['refresh_token'])
        with self.connection() as db:
            db.execute('UPDATE alexa_grants SET access_token=?, refresh_token=?, expires=? WHERE user_id=?',
                       (token['access_token'], token.get('refresh_token', row['refresh_token']),
                        time.time() + float(token['expires_in']), user_id))
        return token['access_token']

    def send(self, user_id, event):
        region = os.environ.get('ALEXA_REGION', 'NA').upper()
        if region not in GATEWAYS:
            raise RuntimeError('ALEXA_REGION debe ser NA, EU o FE.')
        token = self.access_token(user_id)
        message = json.loads(json.dumps(event))
        message['event']['endpoint']['scope'] = {'type': 'BearerToken', 'token': token}
        response = requests.post(GATEWAYS[region], json=message,
                                 headers={'Authorization': 'Bearer ' + token}, timeout=5)
        if response.status_code == 401:
            token = self.access_token(user_id, force=True)
            message['event']['endpoint']['scope']['token'] = token
            response = requests.post(GATEWAYS[region], json=message,
                                     headers={'Authorization': 'Bearer ' + token}, timeout=5)
        response.raise_for_status()
        return response

    @staticmethod
    def event(namespace, name, endpoint_id, correlation=None, payload=None):
        header = dict(namespace=namespace, name=name, payloadVersion='3', messageId=str(uuid.uuid4()))
        if correlation:
            header['correlationToken'] = correlation
        return {'event': {'header': header, 'endpoint': {'endpointId': endpoint_id}, 'payload': payload or {}}}

    def wake_now(self, user_id, endpoint_id, correlation=None):
        if not correlation:
            raise ValueError('WakeUp requiere una orden de Alexa con correlationToken.')
        self.send(user_id, self.event('Alexa.WakeOnLANController', 'WakeUp', endpoint_id, correlation))

    def enqueue(self, user_id, endpoint_id, correlation, directive_id):
        if not self.is_linked(user_id):
            raise RuntimeError('Falta la autorización del gateway de Alexa.')
        if not correlation or not directive_id:
            raise ValueError('La directiva debe incluir correlationToken y messageId.')
        with self.connection() as db:
            db.execute('INSERT OR IGNORE INTO alexa_jobs VALUES (?, ?, ?, ?, ?, ?, ?)',
                       (str(uuid.uuid4()), user_id, endpoint_id, correlation, directive_id, time.time(), 'pending'))

    def process_next(self):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE alexa_jobs SET status='expired' WHERE status IN ('pending','processing') AND created < ?", (time.time() - 60,))
            job = db.execute("SELECT * FROM alexa_jobs WHERE status='pending' AND created < ? ORDER BY created LIMIT 1", (time.time() - 1,)).fetchone()
            if not job:
                return False
            db.execute("UPDATE alexa_jobs SET status='processing' WHERE id=?", (job['id'],))
        status = 'failed'
        try:
            self.wake_now(job['user_id'], job['endpoint_id'], job['correlation'])
            result = self.event('Alexa', 'Response', job['endpoint_id'], job['correlation'])
            result['context'] = {'properties': [{'namespace': 'Alexa.PowerController', 'name': 'powerState', 'value': 'ON',
                                                 'timeOfSample': datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
                                                 'uncertaintyInMilliseconds': 500}]}
            self.send(job['user_id'], result)
            status = 'done'
        except Exception:
            logging.warning('No se completó la orden Echo WoL %s.', job['id'])
            try:
                self.send(job['user_id'], self.event('Alexa', 'ErrorResponse', job['endpoint_id'], job['correlation'],
                          {'type': 'ENDPOINT_UNREACHABLE', 'message': 'No se pudo completar el encendido mediante Echo.'}))
            except Exception:
                logging.warning('No se pudo entregar la respuesta de error de Echo WoL.')
        finally:
            with self.connection() as db:
                db.execute('UPDATE alexa_jobs SET status=? WHERE id=?', (status, job['id']))
        return True

    def run(self):
        while True:
            try:
                self.process_next()
            except Exception:
                logging.exception('Error procesando la cola de Alexa.')
            time.sleep(0.5)

    def start(self):
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(target=self.run, daemon=True, name='alexa-wol')
            self._worker.start()
