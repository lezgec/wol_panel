"""Native access: isolated accounts/state and mocked mail only."""
import unittest
from unittest.mock import patch
from werkzeug.security import check_password_hash
import test_windows_agent as agents

class NativeAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): agents.AgentFlowTests.setUpClass()
    @classmethod
    def tearDownClass(cls): agents.AgentFlowTests.tearDownClass()
    def setUp(self):
        fixture=agents.AgentFlowTests('runTest'); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        self.client=fixture.client; self.module=fixture.module
    def post_auth(self, path, data):
        response=self.client.get('/api/mobile/v1/auth/session').get_json()
        token=response.get('csrf_token') or response.get('data',{}).get('csrf_token')
        return self.client.post('/api/mobile/v1/auth/'+path,json=data,headers={'X-CSRF-Token':token})

    def test_login_cookie_rotation_remember_and_logout(self):
        original=self.client.get('/api/mobile/v1/auth/session').get_json()['csrf_token']
        self.assertEqual(self.client.post('/api/mobile/v1/auth/login',json={'email':'owner@example.invalid','password':'Password1!'}).status_code,400)
        logged=self.post_auth('login',dict(email='owner@example.invalid',password='Password1!',remember=True))
        self.assertEqual(logged.status_code,200); self.assertEqual(logged.get_json()['phase'],'authenticated')
        self.assertTrue(logged.get_json()['data']['remembered'])
        self.assertNotEqual(logged.get_json()['data']['csrf_token'],original)
        self.assertIn('HttpOnly',logged.headers['Set-Cookie'])
        self.assertEqual(self.client.get('/api/mobile/v1/devices').status_code,200)
        self.assertEqual(self.client.post('/api/mobile/v1/logout',json={},headers={'X-CSRF-Token':logged.get_json()['data']['csrf_token']}).status_code,200)
        self.assertEqual(self.client.get('/api/mobile/v1/devices').status_code,401)
        with self.module.state_connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM mobile_sessions').fetchone()[0],0)

    def test_bad_password_suspension_and_limits(self):
        self.assertEqual(self.post_auth('login',dict(email='owner@example.invalid',password='wrong')).status_code,401)
        with self.module.plans.state() as db:db.execute('INSERT INTO plan_accounts (user_id,suspended) VALUES (?,1) ON CONFLICT(user_id) DO UPDATE SET suspended=1',('1',))
        self.assertEqual(self.post_auth('login',dict(email='owner@example.invalid',password='Password1!')).status_code,403)
        with patch.object(self.module,'rate_allowed',return_value=False):self.assertEqual(self.post_auth('login',dict(email='owner@example.invalid',password='wrong')).status_code,429)

    def test_registration_resend_verification_and_login(self):
        with patch.object(self.module,'send_verification_email',return_value=True) as mail:
            registered=self.post_auth('register',dict(email='native@example.invalid',password='Password1!'))
            self.assertEqual(registered.status_code,200);self.assertEqual(registered.get_json()['phase'],'verify')
            first=mail.call_args.args[1]
            self.assertEqual(self.client.get('/api/mobile/v1/devices').status_code,401)
            self.assertEqual(self.post_auth('resend',{}).status_code,200)
            latest=mail.call_args.args[1]
            if first!=latest:self.assertEqual(self.post_auth('verify',dict(code=first)).status_code,400)
            self.assertEqual(self.post_auth('verify',dict(code=latest)).get_json()['phase'],'login')
            self.assertEqual(self.post_auth('verify',dict(code=latest)).status_code,400)
            self.assertEqual(self.post_auth('login',dict(email='native@example.invalid',password='Password1!')).status_code,200)

    def test_recovery_response_and_password_update(self):
        with patch.object(self.module,'send_reset_email',return_value=True) as mail:
            known=self.post_auth('forgot',dict(email='owner@example.invalid'));code=mail.call_args.args[1]
            self.assertEqual(self.post_auth('reset',dict(code='000000',password='Different1!')).status_code,400)
            self.assertEqual(self.post_auth('reset',dict(code=code,password='Different1!')).status_code,200)
            self.assertTrue(check_password_hash(self.module.database.fetch_one('SELECT password FROM users WHERE id=%s',(1,))[0],'Different1!'))
            unknown=self.post_auth('forgot',dict(email='missing@example.invalid'))
            self.assertEqual(known.get_json(),unknown.get_json());self.assertEqual(mail.call_count,1)

    def test_bridge_and_expired_session_never_redirect(self):
        self.post_auth('login',dict(email='owner@example.invalid',password='Password1!',remember=True))
        with self.module.state_connection() as db:db.execute('UPDATE mobile_sessions SET expires=0')
        bridge=self.client.get('/mobile/bridge')
        self.assertEqual(bridge.status_code,200);self.assertNotIn(b'<form',bridge.data);self.assertNotIn(b'<script',bridge.data)
        self.assertEqual(self.client.get('/api/mobile/v1/auth/session').get_json()['phase'],'login')
        self.assertEqual(self.client.get('/api/mobile/v1/devices').status_code,401)

    def test_pending_account_remains_unprivileged(self):
        with patch.object(self.module,'send_verification_email',return_value=True):
            self.post_auth('register',dict(email='pending@example.invalid',password='Password1!'))
            self.assertEqual(self.post_auth('login',dict(email='pending@example.invalid',password='Password1!')).get_json()['phase'],'verify')
            self.assertEqual(self.client.get('/api/mobile/v1/devices').status_code,401)
