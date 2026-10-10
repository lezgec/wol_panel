"""Pruebas aisladas; MariaDB real se verifica adicionalmente en test_mariadb.py."""
import base64
import hashlib
import importlib
import os
import socket
import sqlite3
import tempfile
import time
import unittest
import subprocess
import sys
import json
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


class SQLiteMySQLCursor:
    """Doble de prueba: execute devuelve un entero, como PyMySQL, no un cursor."""
    def __init__(self, cursor):
        self.cursor = cursor

    def execute(self, sql, params=()):
        self.cursor.execute(sql.replace('%s', '?'), params)
        return self.cursor.rowcount

    def __getattr__(self, name):
        return getattr(self.cursor, name)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.cursor.close()


class SQLiteMySQLConnection:
    def __init__(self, connection):
        self.connection = connection

    def cursor(self):
        return SQLiteMySQLCursor(self.connection.cursor())

    def __getattr__(self, name):
        return getattr(self.connection, name)


class ApplicationTests(unittest.TestCase):
    def business_connection(self):
        return sqlite3.connect(self.db_path, factory=ClosingConnection)

    def application_connection(self):
        return SQLiteMySQLConnection(self.business_connection())
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.environment = patch.dict(os.environ, {
            'WOL_STATE_DIR': cls.temp.name, 'FLASK_SECRET_KEY': 'test-key-only',
            'ALEXA_CLIENT_ID': 'test-client', 'ALEXA_CLIENT_SECRET': 'test-secret',
            'ALEXA_REDIRECT_URIS': 'https://alexa.example/link', 'COOKIE_SECURE': '0',
            'APP_ENV': 'development', 'ALLOW_LOCAL_WOL': '1', 'ALEXA_BRIDGE_SECRET': '',
        })
        cls.environment.start()
        cls.module = importlib.reload(importlib.import_module('app'))
        cls.module.app.config['TESTING'] = True

    @classmethod
    def tearDownClass(cls):
        cls.environment.stop()
        cls.temp.cleanup()

    def reset_business(self):
        with self.business_connection() as db:
            db.executescript('''
                DROP TABLE IF EXISTS users; DROP TABLE IF EXISTS devices; DROP TABLE IF EXISTS audit_logs;
                CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT UNIQUE, password TEXT,
                                    amazon_id TEXT, is_verified INTEGER, verification_code TEXT);
                CREATE TABLE devices (id INTEGER PRIMARY KEY, name TEXT, mac TEXT, user_sub TEXT, wake_method TEXT NOT NULL DEFAULT 'local', wake_host TEXT, wake_port INTEGER NOT NULL DEFAULT 9);
                CREATE TABLE audit_logs (user_id INTEGER, action TEXT, details TEXT);
            ''')
    def setUp(self):
        self.db_path = Path(self.temp.name) / 'business.sqlite3'
        self.reset_business()
        with self.business_connection() as db:
            db.execute('INSERT INTO users (id,email,password,amazon_id,is_verified,verification_code) VALUES (1, ?, ?, NULL, 1, NULL)',
                       ('owner@example.invalid', self.module.generate_password_hash('Password1!')))
            db.execute("INSERT INTO users (id,email,password,is_verified) VALUES (2, 'other@example.invalid', 'unused', 1)")
            db.execute("INSERT INTO devices (id,name,mac,user_sub) VALUES (1, 'PC propia', 'AA:BB:CC:DD:EE:FF', '1')")
            db.execute("INSERT INTO devices (id,name,mac,user_sub) VALUES (2, 'PC ajena', '11:22:33:44:55:66', '2')")
        self.db_mock = patch.object(self.module.database, 'get_db_connection', side_effect=self.application_connection)
        self.db_mock.start()
        self.addCleanup(self.db_mock.stop)
        self.real_send_wol = self.module.send_wol
        for target, name in ((self.module, 'send_wol'), (self.module.smtplib, 'SMTP'),
                             (self.module.requests, 'get'), (self.module.requests, 'post')):
            guard = patch.object(target, name, side_effect=AssertionError('Una prueba intentó acceder a la red sin mock.'))
            guard.start()
            self.addCleanup(guard.stop)
        with self.module.state_connection() as db:
            for table in ('auth_codes', 'auth_tokens', 'challenges', 'alexa_grants', 'alexa_jobs', 'rate_limits'):
                db.execute('DELETE FROM ' + table)
        self.client = self.module.app.test_client()

    def csrf(self):
        with self.client.session_transaction() as session:
            session['csrf_token'] = 'test-csrf'
        return 'test-csrf'

    def login(self):
        return self.client.post('/login', data={'email': 'owner@example.invalid', 'password': 'Password1!', 'csrf_token': self.csrf()})

    def authorize(self, extra=None):
        params = dict(client_id='test-client', response_type='code', redirect_uri='https://alexa.example/link', state='test-state')
        params.update(extra or {})
        response = self.client.post('/oauth/authorize', query_string=params,
                                    data={'email': 'owner@example.invalid', 'password': 'Password1!', 'csrf_token': self.csrf()})
        self.assertEqual(response.status_code, 302)
        query = parse_qs(urlsplit(response.location).query)
        self.assertEqual(query['state'], ['test-state'])
        return query['code'][0]

    def exchange(self, code, **kwargs):
        data = dict(grant_type='authorization_code', code=code, client_id='test-client',
                    client_secret='test-secret', redirect_uri='https://alexa.example/link')
        data.update(kwargs)
        return self.client.post('/oauth/token', data=data)

    def token(self):
        return self.exchange(self.authorize()).json['access_token']

    def directive(self, token, name='TurnOn', endpoint='1', namespace='Alexa.PowerController'):
        directive = {'header': {'namespace': namespace, 'name': name, 'messageId': 'test', 'correlationToken': 'correlation', 'payloadVersion': '3'},
                     'payload': {}, 'endpoint': {'endpointId': endpoint, 'scope': {'type': 'BearerToken', 'token': token},
                                                'cookie': {'mac': '11:22:33:44:55:66'}}}
        if namespace == 'Alexa.Discovery':
            directive['payload']['scope'] = directive['endpoint'].pop('scope')
        return {'directive': directive}

    def test_mobile_devices_require_session_and_only_return_owned_devices(self):
        self.assertEqual(self.client.get('/api/mobile/v1/devices').status_code, 401)
        self.login()
        response = self.client.get('/api/mobile/v1/devices')
        self.assertEqual(response.status_code, 200)
        self.assertEqual([device['id'] for device in response.json['devices']], [1])
        self.assertFalse(response.json['devices'][0]['can_wake'])
        self.assertIsInstance(response.json['alexa_ready'], bool)
        self.assertTrue(response.json['csrf_token'])
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_mobile_wake_enforces_csrf_ownership_and_coming_soon(self):
        self.login()
        self.assertEqual(self.client.post('/api/mobile/v1/devices/1/wake').status_code, 400)
        headers = {'X-CSRF-Token': self.client.get('/api/mobile/v1/devices').json['csrf_token']}
        with patch.object(self.module, 'send_wol', return_value=True) as sender:
            self.assertEqual(self.client.post('/api/mobile/v1/devices/2/wake', headers=headers).status_code, 404)
            sender.assert_not_called()
            response = self.client.post('/api/mobile/v1/devices/1/wake', headers=headers)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json['error'], 'coming_soon')
            sender.assert_not_called()

    def test_mobile_alexa_and_disabled_local_do_not_send_packets(self):
        self.login()
        headers = {'X-CSRF-Token': self.client.get('/api/mobile/v1/devices').json['csrf_token']}
        with self.business_connection() as db:
            db.execute("UPDATE devices SET wake_method='alexa' WHERE id=1")
        response = self.client.post('/api/mobile/v1/devices/1/wake', headers=headers)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json['error'], 'alexa_required')
        with self.business_connection() as db:
            db.execute("UPDATE devices SET wake_method='local' WHERE id=1")
        with patch.dict(self.module.app.config, {'ALLOW_LOCAL_WOL': False}):
            response = self.client.post('/api/mobile/v1/devices/1/wake', headers=headers)
            self.assertEqual(response.json['error'], 'coming_soon')

    def test_mobile_router_is_disabled_and_rate_limited(self):
        self.login()
        headers = {'X-CSRF-Token': self.client.get('/api/mobile/v1/devices').json['csrf_token']}
        with self.business_connection() as db:
            db.execute("UPDATE devices SET wake_method='router', wake_host='example.invalid', wake_port=9 WHERE id=1")
        with patch.object(self.module, 'send_router_wol', return_value=False) as sender:
            response = self.client.post('/api/mobile/v1/devices/1/wake', headers=headers)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json['error'], 'coming_soon')
            sender.assert_not_called()
        with patch.object(self.module, 'rate_allowed', return_value=False):
            response = self.client.post('/api/mobile/v1/devices/1/wake', headers=headers)
            self.assertEqual(response.status_code, 429)
            self.assertIn('Retry-After', response.headers)

    def test_mobile_create_validates_and_always_uses_alexa(self):
        self.login()
        headers = {'X-CSRF-Token': self.client.get('/api/mobile/v1/devices').json['csrf_token']}
        for payload in ({'name': '', 'mac': 'AA:BB:CC:DD:EE:11'}, {'name': 'PC', 'mac': 'bad'},
                        {'name': 'PC', 'mac': 'AA:BB:CC:DD:EE:11', 'wake_method': 'router'}, [],
                        {'name': 123, 'mac': 'AA:BB:CC:DD:EE:11'}):
            response = self.client.post('/api/mobile/v1/devices', json=payload, headers=headers)
            self.assertEqual(response.status_code, 400)
        response = self.client.post('/api/mobile/v1/devices', json={'name': ' Nuevo ', 'mac': 'aa-bb-cc-dd-ee-11'}, headers=headers)
        self.assertEqual(response.status_code, 201)
        self.assertEqual([device['id'] for device in response.json['devices']], [1, 3])
        with self.business_connection() as db:
            row = db.execute('SELECT name, mac, user_sub, wake_method FROM devices WHERE id=3').fetchone()
            self.assertEqual((row[0], row[1], str(row[2]), row[3]),
                             ('Nuevo', 'AA:BB:CC:DD:EE:11', '1', 'alexa'))

    def test_mobile_edit_enforces_csrf_ownership_and_preserves_settings(self):
        self.login()
        headers = {'X-CSRF-Token': self.client.get('/api/mobile/v1/devices').json['csrf_token']}
        payload = {'name': 'Renombrado', 'mac': 'AA:BB:CC:DD:EE:12'}
        self.assertEqual(self.client.put('/api/mobile/v1/devices/1', json=payload).status_code, 400)
        self.assertEqual(self.client.put('/api/mobile/v1/devices/2', json=payload, headers=headers).status_code, 404)
        with self.business_connection() as db:
            db.execute("UPDATE devices SET wake_method='router', wake_host='router.example', wake_port=7 WHERE id=1")
        self.assertEqual(self.client.put('/api/mobile/v1/devices/1', json=payload, headers=headers).status_code, 200)
        with self.business_connection() as db:
            self.assertEqual(db.execute('SELECT name, mac, wake_method, wake_host, wake_port FROM devices WHERE id=1').fetchone(),
                             ('Renombrado', 'AA:BB:CC:DD:EE:12', 'router', 'router.example', 7))
            self.assertEqual(db.execute('SELECT name FROM devices WHERE id=2').fetchone()[0], 'PC ajena')

    def test_mobile_logout_requires_csrf_and_clears_session(self):
        self.login()
        headers = {'X-CSRF-Token': self.client.get('/api/mobile/v1/devices').json['csrf_token']}
        self.assertEqual(self.client.post('/api/mobile/v1/logout').status_code, 400)
        self.assertEqual(self.client.post('/api/mobile/v1/logout', headers=headers).status_code, 200)
        self.assertEqual(self.client.get('/api/mobile/v1/devices').status_code, 401)
        self.assertEqual(self.client.put('/api/mobile/v1/devices/1', json={}, headers=headers).status_code, 401)

    def test_mobile_writes_are_rate_limited(self):
        self.login()
        headers = {'X-CSRF-Token': self.client.get('/api/mobile/v1/devices').json['csrf_token']}
        with patch.object(self.module, 'rate_allowed', return_value=False):
            self.assertEqual(self.client.put('/api/mobile/v1/devices/1', json={}, headers=headers).status_code, 429)
            self.assertEqual(self.client.post('/api/mobile/v1/devices', json={}, headers=headers).status_code, 429)

    def test_magic_packet_format_and_destination_without_network(self):
        with patch.object(self.module.socket, 'socket') as socket_factory:
            sender = socket_factory.return_value.__enter__.return_value
            self.assertTrue(self.real_send_wol('aa-bb-cc-dd-ee-ff', '127.0.0.1', 9))
            packet, destination = sender.sendto.call_args.args
            self.assertEqual(destination, ('127.0.0.1', 9))
        self.assertEqual(packet, b'\xff' * 6 + bytes.fromhex('aabbccddeeff') * 16)
        self.assertEqual(len(packet), 102)

    def test_invalid_mac_never_opens_socket(self):
        with patch.object(self.module.socket, 'socket') as send:
            self.assertFalse(self.real_send_wol('GG:BB:CC:DD:EE:FF'))
            send.assert_not_called()

    def test_panel_edit_requires_csrf_and_ownership(self):
        self.login()
        fields = dict(name='Nuevo nombre', mac='12:34:56:78:9A:BC', wake_method='alexa')
        self.assertEqual(self.client.post('/devices/1/edit', data=fields).status_code, 400)
        fields['csrf_token'] = self.csrf()
        self.client.post('/devices/2/edit', data=fields)
        self.assertEqual(self.module.database.fetch_one('SELECT name,mac FROM devices WHERE id=2'),
                         ('PC ajena', '11:22:33:44:55:66'))
        for _ in range(2):
            response = self.client.post('/devices/1/edit', data=fields, follow_redirects=True)
            self.assertIn('Equipo actualizado.'.encode(), response.data)
        self.assertEqual(self.module.database.fetch_one('SELECT name,mac,wake_method FROM devices WHERE id=1'),
                         ('Nuevo nombre', '12:34:56:78:9A:BC', 'alexa'))

    def test_panel_invalid_edit_is_atomic(self):
        self.login()
        initial = self.module.database.fetch_one('SELECT name,mac,wake_method,wake_host,wake_port FROM devices WHERE id=1')
        fields = dict(name='Cambio', mac='12:34:56:78:9A:BC', wake_method='alexa', csrf_token=self.csrf())
        for invalid in ({'name': ''}, {'mac': 'invalid'}, {'wake_method': 'router', 'wake_host': '127.0.0.1'}):
            self.client.post('/devices/1/edit', data={**fields, **invalid})
            self.assertEqual(self.module.database.fetch_one('SELECT name,mac,wake_method,wake_host,wake_port FROM devices WHERE id=1'), initial)

    def test_panel_login_dashboard_and_wake(self):
        self.assertEqual(self.login().status_code, 302)
        page = self.client.get('/')
        self.assertIn(b'PC propia', page.data)
        self.assertNotIn(b'PC ajena', page.data)
        self.assertIn(b'csrf_token', page.data)
        with patch.object(self.module, 'send_wol', return_value=True) as send:
            result = self.client.post('/wake/1', data={'csrf_token': self.csrf()}, follow_redirects=True)
            send.assert_called_once_with('AA:BB:CC:DD:EE:FF')
            self.assertIn(b'Paquete de encendido enviado', result.data)

    def test_panel_reports_send_failure_and_protects_other_devices(self):
        self.login()
        with patch.object(self.module, 'send_wol', return_value=False) as send:
            result = self.client.post('/wake/1', data={'csrf_token': self.csrf()}, follow_redirects=True)
            self.assertIn(b'No se pudo enviar', result.data)
            send.reset_mock()
            self.client.post('/wake/2', data={'csrf_token': self.csrf()})
            send.assert_not_called()

    def test_csrf_and_get_cannot_mutate(self):
        self.login()
        self.assertEqual(self.client.get('/wake/1').status_code, 405)
        self.assertEqual(self.client.get('/delete/1').status_code, 405)
        self.assertEqual(self.client.post('/delete/1').status_code, 400)

    def test_add_validation_and_delete_ownership(self):
        self.login()
        self.client.post('/add', data={'name': 'New', 'mac': 'invalid', 'csrf_token': self.csrf()})
        self.client.post('/delete/2', data={'csrf_token': self.csrf()})
        with self.business_connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM devices').fetchone()[0], 2)
        self.client.post('/add', data={'name': 'New', 'mac': 'aa-bb-cc-dd-ee-01', 'csrf_token': self.csrf()})
        with self.business_connection() as db:
            self.assertEqual(db.execute("SELECT mac FROM devices WHERE name='New'").fetchone()[0], 'AA:BB:CC:DD:EE:01')
        self.client.post('/delete/1', data={'csrf_token': self.csrf()})
        with self.business_connection() as db:
            self.assertIsNone(db.execute('SELECT id FROM devices WHERE id=1').fetchone())

    def test_oauth_code_single_use_and_refresh(self):
        code = self.authorize()
        result = self.exchange(code)
        self.assertEqual(result.status_code, 200)
        old_token = result.json['access_token']
        self.assertEqual(self.exchange(code).status_code, 400)
        refreshed = self.client.post('/oauth/token', data={'grant_type': 'refresh_token', 'refresh_token': result.json['refresh_token'],
                                                          'client_id': 'test-client', 'client_secret': 'test-secret'})
        self.assertEqual(refreshed.status_code, 200)
        self.assertNotEqual(old_token, refreshed.json['access_token'])
        with self.module.state_connection() as db:
            self.assertIsNone(db.execute('SELECT * FROM auth_tokens WHERE access_token=?', (old_token,)).fetchone())

    def test_oauth_rejects_invalid_credentials_code_redirect_and_expiration(self):
        self.assertEqual(self.client.post('/oauth/token', data={'code': 'invented'}).status_code, 401)
        self.assertEqual(self.exchange('invented').status_code, 400)
        code = self.authorize()
        self.assertEqual(self.exchange(code, redirect_uri='https://evil.example').status_code, 400)
        with self.module.state_connection() as db:
            db.execute('UPDATE auth_codes SET expires=0')
        self.assertEqual(self.exchange(code).status_code, 400)
        self.assertEqual(self.client.get('/oauth/authorize', query_string={'client_id': 'test-client', 'redirect_uri': 'https://evil.example'}).status_code, 400)

    def test_pkce_and_basic_auth(self):
        verifier = 'a' * 43
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        code = self.authorize({'code_challenge': challenge, 'code_challenge_method': 'S256'})
        self.assertEqual(self.exchange(code).status_code, 400)
        result = self.client.post('/oauth/token', data={'code': code, 'grant_type': 'authorization_code', 'redirect_uri': 'https://alexa.example/link', 'code_verifier': verifier},
                                  headers={'Authorization': 'Basic ' + base64.b64encode(b'test-client:test-secret').decode()})
        self.assertEqual(result.status_code, 200)

    def test_alexa_discovery_scoped_to_token_user(self):
        token = self.token()
        result = self.client.post('/alexa/smarthome', json=self.directive(token, name='Discover', namespace='Alexa.Discovery'))
        self.assertEqual([e['endpointId'] for e in result.json['event']['payload']['endpoints']], ['1'])

    def test_alexa_wake_uses_saved_mac_ignores_cookie_and_rejects_other_device(self):
        token = self.token()
        with patch.object(self.module, 'send_wol', return_value=True) as send:
            result = self.client.post('/alexa/smarthome', json=self.directive(token))
            self.assertEqual(result.json['event']['header']['name'], 'Response')
            self.assertEqual(result.json['event']['endpoint']['endpointId'], '1')
            send.assert_called_once_with('AA:BB:CC:DD:EE:FF')
            send.reset_mock()
            result = self.client.post('/alexa/smarthome', json=self.directive(token, endpoint='2'))
            self.assertEqual(result.json['event']['payload']['type'], 'NO_SUCH_ENDPOINT')
            send.assert_not_called()

    def test_alexa_errors_for_invalid_expired_tokens_and_send_failure(self):
        result = self.client.post('/alexa/smarthome', json=self.directive('invalid'))
        self.assertEqual(result.json['event']['payload']['type'], 'INVALID_AUTHORIZATION_CREDENTIAL')
        token = self.token()
        with patch.object(self.module, 'send_wol', return_value=False):
            result = self.client.post('/alexa/smarthome', json=self.directive(token))
            self.assertEqual(result.json['event']['payload']['type'], 'ENDPOINT_UNREACHABLE')
        with self.module.state_connection() as db:
            db.execute('UPDATE auth_tokens SET expires=0')
        result = self.client.post('/alexa/smarthome', json=self.directive(token))
        self.assertEqual(result.json['event']['payload']['type'], 'INVALID_AUTHORIZATION_CREDENTIAL')

    def test_turnoff_does_not_claim_to_shutdown(self):
        with patch.object(self.module, 'send_wol') as send:
            result = self.client.post('/alexa/smarthome', json=self.directive(self.token(), name='TurnOff'))
            self.assertEqual(result.json['event']['header']['name'], 'ErrorResponse')
            send.assert_not_called()

    def test_registration_verification_and_resend(self):
        with patch.object(self.module, 'send_verification_email', return_value=True) as mail:
            result = self.client.post('/register', data={'email': 'new@example.invalid', 'password': 'Password1!', 'csrf_token': self.csrf()})
            self.assertEqual(result.status_code, 302)
            code = mail.call_args.args[1]
            self.client.post('/verify', data={'action': 'resend', 'csrf_token': self.csrf()})
            code = mail.call_args.args[1]
            result = self.client.post('/verify', data={'code': code, 'csrf_token': self.csrf()})
            self.assertEqual(result.location, '/login')
        with self.business_connection() as db:
            self.assertEqual(db.execute("SELECT is_verified FROM users WHERE email='new@example.invalid'").fetchone()[0], 1)

    def test_reset_code_not_in_cookie_and_reset_works(self):
        with patch.object(self.module, 'send_reset_email', return_value=True) as mail:
            self.client.post('/forgot-password', data={'email': 'owner@example.invalid', 'csrf_token': self.csrf()})
            code = mail.call_args.args[1]
        with self.client.session_transaction() as session:
            self.assertNotIn('reset_code', session)
        result = self.client.post('/reset-password', data={'code': code, 'password': 'NewPassword2!', 'csrf_token': self.csrf()})
        self.assertEqual(result.location, '/login')
        with self.business_connection() as db:
            self.assertTrue(self.module.check_password_hash(db.execute('SELECT password FROM users WHERE id=1').fetchone()[0], 'NewPassword2!'))

    def test_challenge_expiry_attempt_limit_and_replay(self):
        challenge = self.module.create_challenge('x', 'reset', '123456')
        for _ in range(5):
            self.assertIsNone(self.module.consume_challenge(challenge, 'reset', 'wrong'))
        self.assertIsNone(self.module.consume_challenge(challenge, 'reset', '123456'))
        challenge = self.module.create_challenge('x', 'reset', '123456')
        self.assertEqual(self.module.consume_challenge(challenge, 'reset', '123456'), 'x')
        self.assertIsNone(self.module.consume_challenge(challenge, 'reset', '123456'))
        challenge = self.module.create_challenge('x', 'reset', '123456')
        with self.module.state_connection() as db:
            db.execute('UPDATE challenges SET expires=0')
        self.assertIsNone(self.module.consume_challenge(challenge, 'reset', '123456'))

    def test_amazon_callback_rejects_missing_or_wrong_state(self):
        with patch.object(self.module.requests, 'post') as exchange:
            self.assertEqual(self.client.get('/callback/amazon?code=fake&state=wrong').status_code, 400)
            exchange.assert_not_called()

    def test_amazon_valid_callback_creates_authenticated_session(self):
        with self.client.session_transaction() as session:
            session['amazon_state'] = 'valid-state'
        with patch.object(self.module.requests, 'post') as token_request, patch.object(self.module.requests, 'get') as profile_request:
            token_request.return_value.json.return_value = {'access_token': 'amazon-test-token'}
            profile_request.return_value.json.return_value = {'user_id': 'amazon-test-user', 'email': 'amazon@example.invalid'}
            response = self.client.get('/callback/amazon?code=test-code&state=valid-state')
            self.assertEqual(response.location, '/')
        with self.client.session_transaction() as session:
            self.assertEqual(session['email'], 'amazon@example.invalid')
            self.assertIn('user_id', session)

    def test_lambda_bridge_preserves_directive_and_response(self):
        import io
        import json
        import lambda_function
        event = self.directive('test-token')
        expected = {'event': {'header': {'name': 'Response'}}}
        with patch.dict(os.environ, {'WOL_BACKEND_URL': 'https://backend.example/alexa/smarthome', 'ALEXA_BRIDGE_SECRET': 's' * 32}), patch.object(lambda_function.urllib.request, 'urlopen') as opener:
            opener.return_value.__enter__.return_value = io.BytesIO(json.dumps(expected).encode())
            self.assertEqual(lambda_function.lambda_handler(event, None), expected)
            self.assertEqual(json.loads(opener.call_args.args[0].data), event)

    def test_lambda_bridge_reports_backend_failure(self):
        import lambda_function
        with patch.dict(os.environ, {'WOL_BACKEND_URL': 'https://backend.example/alexa/smarthome', 'ALEXA_BRIDGE_SECRET': 's' * 32}), patch.object(lambda_function.urllib.request, 'urlopen', side_effect=TimeoutError):
            response = lambda_function.lambda_handler(self.directive('test-token'), None)
            self.assertEqual(response['event']['payload']['type'], 'INTERNAL_ERROR')
            self.assertEqual(response['event']['endpoint']['endpointId'], '1')

    def set_device_method(self, method, host=None, port=9):
        with self.business_connection() as db:
            db.execute('UPDATE devices SET wake_method=?, wake_host=?, wake_port=? WHERE id=1', (method, host, port))

    def grant(self, expired=False):
        with self.module.state_connection() as db:
            db.execute('INSERT INTO alexa_grants VALUES (?, ?, ?, ?)', ('1', 'gateway-token', 'gateway-refresh', 0 if expired else time.time() + 3600))

    def test_router_registration_and_settings_are_scoped(self):
        self.login()
        response = self.client.post('/add', data={'name': 'Router PC', 'mac': 'AA:BB:CC:DD:EE:01', 'wake_method': 'router',
                                                  'wake_host': 'casa.example.net', 'wake_port': '40009', 'csrf_token': self.csrf()})
        self.assertEqual(response.status_code, 302)
        with self.business_connection() as db:
            self.assertEqual(db.execute("SELECT wake_method,wake_host,wake_port FROM devices WHERE name='Router PC'").fetchone(),
                             ('router', 'casa.example.net', 40009))
        self.client.post('/devices/1/settings', data={'wake_method': 'alexa', 'csrf_token': self.csrf()})
        self.client.post('/devices/2/settings', data={'wake_method': 'router', 'wake_host': '8.8.8.8', 'csrf_token': self.csrf()})
        with self.business_connection() as db:
            self.assertEqual(db.execute('SELECT wake_method FROM devices WHERE id=1').fetchone()[0], 'alexa')
            self.assertEqual(db.execute('SELECT wake_method FROM devices WHERE id=2').fetchone()[0], 'local')

    def test_router_destination_validation(self):
        for host in ('127.0.0.1', '192.168.1.2', '100.64.1.2', '169.254.169.254', '224.0.0.1', '255.255.255.255', 'https://casa.example.net', '999.1.1.1', '', '::1'):
            with self.subTest(host=host), self.assertRaises(ValueError):
                self.module.wake_settings({'wake_method': 'router', 'wake_host': host})
        for port in ('0', '65536', 'not-a-port'):
            with self.assertRaises(ValueError):
                self.module.wake_settings({'wake_method': 'router', 'wake_host': '8.8.8.8', 'wake_port': port})
        self.assertEqual(self.module.wake_settings({'wake_method': 'router', 'wake_host': 'CASA.example.net', 'wake_port': '40009'}),
                         ('router', 'casa.example.net', 40009))

    def test_router_send_resolves_public_destination_and_blocks_private_dns(self):
        self.login()
        self.set_device_method('router', 'casa.example.net', 40009)
        real_lookup = socket.getaddrinfo
        def lookup(host, port, *args, **kwargs):
            if host == 'casa.example.net':
                return [(socket.AF_INET, socket.SOCK_DGRAM, 17, '', ('8.8.8.8', 40009))]
            return real_lookup(host, port, *args, **kwargs)
        with patch.object(self.module.socket, 'getaddrinfo', side_effect=lookup), patch.object(self.module, 'send_wol', return_value=True) as send:
            result = self.client.post('/wake/1', data={'csrf_token': self.csrf()}, follow_redirects=True)
            send.assert_called_once_with('AA:BB:CC:DD:EE:FF', '8.8.8.8', 40009)
            self.assertIn(b'Paquete de encendido enviado', result.data)
        with patch.object(self.module.socket, 'getaddrinfo', return_value=[(socket.AF_INET, socket.SOCK_DGRAM, 17, '', ('127.0.0.1', 40009))]), patch.object(self.module, 'send_wol') as send:
            self.assertFalse(self.module.send_router_wol('AA:BB:CC:DD:EE:FF', 'casa.example.net', 40009))
            send.assert_not_called()

    def test_alexa_router_mode_uses_saved_destination(self):
        self.set_device_method('router', 'casa.example.net', 40009)
        with patch.object(self.module, 'send_router_wol', return_value=True) as send:
            result = self.client.post('/alexa/smarthome', json=self.directive(self.token()))
            self.assertEqual(result.json['event']['header']['name'], 'Response')
            send.assert_called_once_with('AA:BB:CC:DD:EE:FF', 'casa.example.net', 40009)

    def test_echo_discovery_exposes_normalized_mac(self):
        self.set_device_method('alexa')
        result = self.client.post('/alexa/smarthome', json=self.directive(self.token(), name='Discover', namespace='Alexa.Discovery'))
        capabilities = result.json['event']['payload']['endpoints'][0]['capabilities']
        wol = next(c for c in capabilities if c['interface'] == 'Alexa.WakeOnLANController')
        self.assertEqual(wol['configuration']['MACAddresses'], ['AA-BB-CC-DD-EE-FF'])

    def test_accept_grant_identifies_user_and_persists_credentials(self):
        token = self.token()
        event = {'directive': {'header': {'namespace': 'Alexa.Authorization', 'name': 'AcceptGrant'},
                               'payload': {'grantee': {'type': 'BearerToken', 'token': token},
                                           'grant': {'type': 'OAuth2.AuthorizationCode', 'code': 'amazon-code'}}}}
        with patch.object(self.module.alexa_gateway, 'exchange', return_value={'access_token': 'gateway-token', 'refresh_token': 'gateway-refresh', 'expires_in': 3600}) as exchange:
            result = self.client.post('/alexa/smarthome', json=event)
            self.assertEqual(result.json['event']['header']['name'], 'AcceptGrant.Response')
            exchange.assert_called_once_with(grant_type='authorization_code', code='amazon-code')
        self.assertTrue(self.module.alexa_gateway.is_linked('1'))
        self.assertFalse(self.module.alexa_gateway.is_linked('2'))
        event['directive']['payload']['grantee']['token'] = 'invalid'
        self.assertEqual(self.client.post('/alexa/smarthome', json=event).json['event']['payload']['type'], 'INVALID_AUTHORIZATION_CREDENTIAL')

    def test_echo_turnon_deferred_then_gateway_wakeup_then_response(self):
        self.set_device_method('alexa')
        self.grant()
        event = self.directive(self.token())
        with patch.object(self.module, 'send_wol') as udp:
            result = self.client.post('/alexa/smarthome', json=event)
            self.assertEqual(result.json['event']['header']['name'], 'DeferredResponse')
            self.assertEqual(result.json['event']['header']['correlationToken'], 'correlation')
            udp.assert_not_called()
        # Reintentos de la misma directiva no duplican la orden.
        self.client.post('/alexa/smarthome', json=event)
        with self.module.state_connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM alexa_jobs').fetchone()[0], 1)
            db.execute('UPDATE alexa_jobs SET created=?', (time.time() - 2,))
        with patch('alexa_wol.requests.post') as post:
            post.return_value.status_code = 202
            self.assertTrue(self.module.alexa_gateway.process_next())
            events = [call.kwargs['json'] for call in post.call_args_list]
            self.assertEqual([e['event']['header']['name'] for e in events], ['WakeUp', 'Response'])
            self.assertEqual(events[0]['event']['endpoint']['scope']['token'], 'gateway-token')
            self.assertEqual(events[0]['event']['header']['correlationToken'], 'correlation')
        with self.module.state_connection() as db:
            self.assertEqual(db.execute('SELECT status FROM alexa_jobs').fetchone()[0], 'done')

    def test_echo_requires_grant_and_browser_does_not_forge_alexa_directive(self):
        self.set_device_method('alexa')
        result = self.client.post('/alexa/smarthome', json=self.directive(self.token()))
        self.assertEqual(result.json['event']['header']['name'], 'ErrorResponse')
        self.login()
        with patch.object(self.module.alexa_gateway, 'wake_now') as wake, patch.object(self.module, 'send_wol') as udp:
            result = self.client.post('/wake/1', data={'csrf_token': self.csrf()}, follow_redirects=True)
            self.assertIn(b'desde la app Alexa', result.data)
            wake.assert_not_called()
            udp.assert_not_called()

    def test_gateway_refresh_and_job_failure(self):
        self.grant(expired=True)
        with patch.object(self.module.alexa_gateway, 'exchange', return_value={'access_token': 'renewed', 'expires_in': 3600}) as exchange:
            self.assertEqual(self.module.alexa_gateway.access_token('1'), 'renewed')
            exchange.assert_called_once_with(grant_type='refresh_token', refresh_token='gateway-refresh')
        self.module.alexa_gateway.enqueue('1', '1', 'correlation', 'failure-test')
        with self.module.state_connection() as db:
            db.execute('UPDATE alexa_jobs SET created=?', (time.time() - 2,))
        with patch.object(self.module.alexa_gateway, 'wake_now', side_effect=RuntimeError), patch.object(self.module.alexa_gateway, 'send') as send:
            self.assertTrue(self.module.alexa_gateway.process_next())
            self.assertEqual(send.call_args.args[1]['event']['header']['name'], 'ErrorResponse')
        with self.module.state_connection() as db:
            self.assertEqual(db.execute('SELECT status FROM alexa_jobs').fetchone()[0], 'failed')

    def test_gateway_region_and_endpoint_scope(self):
        self.grant()
        with patch.dict(os.environ, {'ALEXA_REGION': 'EU'}), patch('alexa_wol.requests.post') as post:
            post.return_value.status_code = 202
            self.module.alexa_gateway.wake_now('1', '1', 'correlation')
            self.assertEqual(post.call_args.args[0], 'https://api.eu.amazonalexa.com/v3/events')
            self.assertEqual(post.call_args.kwargs['headers']['Authorization'], 'Bearer gateway-token')

    def test_public_server_blocks_local_wake_and_discovery(self):
        self.login()
        token = self.token()
        with patch.dict(self.module.app.config, {'ALLOW_LOCAL_WOL': False}), patch.object(self.module, 'send_wol') as send:
            page = self.client.get('/')
            self.assertNotIn(b'<option value="local">', page.data)
            with self.assertRaises(ValueError):
                self.module.wake_settings({'wake_method': 'local'})
            self.client.post('/wake/1', data={'csrf_token': self.csrf()})
            response = self.client.post('/alexa/smarthome', json=self.directive(token))
            self.assertEqual(response.json['event']['payload']['type'], 'ENDPOINT_UNREACHABLE')
            discovered = self.client.post('/alexa/smarthome', json=self.directive(token, 'Discover', namespace='Alexa.Discovery'))
            self.assertEqual(discovered.json['event']['payload']['endpoints'], [])
            send.assert_not_called()

    def test_signed_lambda_directive_and_rejection_of_tampering(self):
        import json
        import lambda_function
        token = self.token()
        event = self.directive(token, 'Discover', namespace='Alexa.Discovery')
        with patch.dict(os.environ, {'ALEXA_BRIDGE_SECRET': 's' * 32, 'WOL_BACKEND_URL': 'https://backend.example/alexa/smarthome'}), patch.object(lambda_function.urllib.request, 'urlopen', side_effect=TimeoutError) as opener:
            lambda_function.lambda_handler(event, None)
            outgoing = opener.call_args.args[0]
            headers = dict(outgoing.header_items())
            self.assertEqual(self.client.post('/alexa/smarthome', data=outgoing.data, headers=headers).status_code, 200)
            self.assertEqual(self.client.post('/alexa/smarthome', json=event).status_code, 401)
            self.assertEqual(self.client.post('/alexa/smarthome', data=outgoing.data + b' ', headers=headers).status_code, 401)
            headers['X-wol-timestamp'] = '1'
            self.assertEqual(self.client.post('/alexa/smarthome', data=outgoing.data, headers=headers).status_code, 401)

    def test_rate_limit_blocks_login_and_recovers_after_expiry(self):
        with patch.dict(self.module.REQUEST_LIMITS, {'login': (2, 60)}):
            self.login()
            self.login()
            self.assertEqual(self.login().status_code, 302)  # cambia de IP a identidad autenticada
            self.login()
            self.assertEqual(self.login().status_code, 429)
            with self.module.state_connection() as db:
                db.execute('UPDATE rate_limits SET expires=0')
            self.assertEqual(self.login().status_code, 302)

    def test_production_configuration_requires_secrets_https_and_secure_cookies(self):
        from flask import Flask
        from production_config import configure
        settings = {'APP_ENV': 'production', 'FLASK_SECRET_KEY': 'f' * 32, 'ALEXA_BRIDGE_SECRET': 'b' * 32,
                    'DB_HOST': '127.0.0.1', 'DB_PORT': '3306', 'DB_NAME': 'wol_panel', 'DB_USER': 'wol_user', 'DB_PASSWORD': 'test-only',
                    'PUBLIC_BASE_URL': 'https://wol.example', 'HOST': '127.0.0.1',
                    'SMTP_USER': 'configured', 'SMTP_PASSWORD': 'configured', 'COOKIE_SECURE': '1',
                    'SMTP_FROM': 'test@example.invalid',
                    'ALLOW_LOCAL_WOL': '0', 'TRUST_PROXY_COUNT': '0'}
        with patch.dict(os.environ, settings):
            public = Flask('production-test')
            configure(public)
            self.assertTrue(public.config['SESSION_COOKIE_SECURE'])
            self.assertFalse(public.config['ALLOW_LOCAL_WOL'])
            self.assertEqual(public.test_client().get('/', headers={'Host': 'evil.example'}).status_code, 400)
            for key, invalid in [('FLASK_SECRET_KEY', ''), ('PUBLIC_BASE_URL', 'http://wol.example'), ('COOKIE_SECURE', '0'), ('ALLOW_LOCAL_WOL', '1'), ('HOST', '0.0.0.0')]:
                with patch.dict(os.environ, {key: invalid}), self.assertRaises(RuntimeError):
                    configure(Flask('invalid-test'))

    def test_echo_gateway_keeps_two_users_tokens_and_devices_separate(self):
        self.set_device_method('alexa')
        with self.business_connection() as db:
            db.execute("UPDATE devices SET wake_method='alexa' WHERE id=2")
        self.grant()
        with self.module.state_connection() as db:
            db.execute('INSERT INTO alexa_grants VALUES (?, ?, ?, ?)', ('2', 'second-gateway-token', 'second-refresh', time.time() + 3600))
            db.execute('INSERT INTO auth_tokens VALUES (?, ?, ?, ?, ?)', ('second-access-token', 'second-app-refresh', '2', 'test-client', time.time() + 3600))
        token = self.token()
        one = self.client.post('/alexa/smarthome', json=self.directive(token, 'Discover', namespace='Alexa.Discovery'))
        two = self.client.post('/alexa/smarthome', json=self.directive('second-access-token', 'Discover', namespace='Alexa.Discovery'))
        self.assertEqual([d['endpointId'] for d in one.json['event']['payload']['endpoints']], ['1'])
        self.assertEqual([d['endpointId'] for d in two.json['event']['payload']['endpoints']], ['2'])
        denied = self.client.post('/alexa/smarthome', json=self.directive('second-access-token', endpoint='1'))
        self.assertEqual(denied.json['event']['payload']['type'], 'NO_SUCH_ENDPOINT')
        request = self.directive('second-access-token', endpoint='2')
        request['directive']['header']['messageId'] = 'second-users-order'
        self.assertEqual(self.client.post('/alexa/smarthome', json=request).json['event']['header']['name'], 'DeferredResponse')
        with self.module.state_connection() as db:
            db.execute('UPDATE alexa_jobs SET created=?', (time.time() - 2,))
        with patch('alexa_wol.requests.post') as post:
            post.return_value.status_code = 202
            self.module.alexa_gateway.process_next()
            for call in post.call_args_list:
                self.assertEqual(call.kwargs['headers']['Authorization'], 'Bearer second-gateway-token')
                self.assertEqual(call.kwargs['json']['event']['endpoint']['endpointId'], '2')

    def test_sqlite_state_and_oauth_refresh_survive_a_new_process(self):
        token = self.token()
        self.grant()
        self.module.alexa_gateway.enqueue('1', '1', 'persist-correlation', 'persist-directive')
        with self.module.state_connection() as db:
            refresh = db.execute('SELECT refresh_token FROM auth_tokens WHERE access_token=?', (token,)).fetchone()[0]
        child_env = dict(os.environ, TEST_REFRESH_TOKEN=refresh)
        source = '''
import json, os, app
with app.state_connection() as db:
    saved = db.execute("SELECT count(*) FROM alexa_grants").fetchone()[0] == 1
    queued = db.execute("SELECT count(*) FROM alexa_jobs WHERE status='pending'").fetchone()[0] == 1
result = app.app.test_client().post('/oauth/token', data=dict(grant_type='refresh_token', refresh_token=os.environ['TEST_REFRESH_TOKEN'], client_id='test-client', client_secret='test-secret'))
print(json.dumps(dict(grants=saved, jobs=queued, refreshed=result.status_code == 200)))
'''
        result = subprocess.run([sys.executable, '-c', source], env=child_env, capture_output=True, text=True, check=True, timeout=20)
        self.assertEqual(json.loads(result.stdout), {'grants': True, 'jobs': True, 'refreshed': True})

    def test_database_failure_does_not_leak_credentials(self):
        self.login()
        with patch.object(self.module.database, 'fetch_all', side_effect=self.module.database.pymysql.OperationalError(1045, 'private-test-password')), self.assertLogs(level='ERROR') as logs:
            response = self.client.get('/')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(b'private-test-password', response.data)
        self.assertNotIn('private-test-password', ''.join(logs.output))

    def test_repeated_settings_update_still_finds_owned_device(self):
        self.login()
        self.set_device_method('alexa')
        for _ in range(2):
            response = self.client.post('/devices/1/settings', data={'wake_method': 'alexa', 'csrf_token': self.csrf()}, follow_redirects=True)
            self.assertIn('Método de encendido guardado.'.encode(), response.data)

    def test_logout_removes_authenticated_session(self):
        self.login()
        self.assertEqual(self.client.get('/logout').status_code, 302)
        with self.client.session_transaction() as session:
            self.assertNotIn('user_id', session)
        self.assertEqual(self.client.get('/').location, '/login')

    def test_smtp_uses_verified_sender_and_hides_errors(self):
        with patch.dict(os.environ, {'SMTP_FROM': 'Soporte <support@example.invalid>'}), patch.object(self.module.smtplib, 'SMTP') as smtp:
            server = smtp.return_value.__enter__.return_value
            self.assertTrue(self.module.send_reset_email('user@example.invalid', '123456'))
            self.assertEqual(server.sendmail.call_args.args[:2], ('support@example.invalid', 'user@example.invalid'))
            server.sendmail.side_effect = RuntimeError('private-smtp-password')
            with self.assertLogs(level='WARNING') as logs:
                self.assertFalse(self.module.send_verification_email('user@example.invalid', '123456'))
            self.assertNotIn('private-smtp-password', ''.join(logs.output))


if __name__ == '__main__':
    unittest.main()
