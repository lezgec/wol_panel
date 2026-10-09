"""Flujo completo del agente sin ejecutar acciones de Windows ni usar cuentas reales."""
import hashlib
import hmac
import json
import os
import time
import uuid
from datetime import datetime, timezone
from unittest.mock import patch
import test_app as base


class AgentFlowTests(base.ApplicationTests):
    def reset_business(self):
        super().reset_business()
        with self.business_connection() as db:
            db.executescript('''
            DROP TABLE IF EXISTS agent_pairings; DROP TABLE IF EXISTS agent_connections;
            DROP TABLE IF EXISTS agent_apps; DROP TABLE IF EXISTS agent_actions; DROP TABLE IF EXISTS agent_commands;
            CREATE TABLE agent_pairings (device_code_hash TEXT PRIMARY KEY,user_code_hash TEXT UNIQUE,computer_name TEXT,expires INTEGER,user_id INTEGER,device_id INTEGER,status TEXT);
            CREATE TABLE agent_connections (id TEXT PRIMARY KEY,user_id INTEGER,device_id INTEGER UNIQUE,token_hash TEXT UNIQUE,expires INTEGER,last_seen INTEGER,allow_shutdown INTEGER DEFAULT 0,revoked INTEGER DEFAULT 0);
            CREATE TABLE agent_apps (agent_id TEXT,app_key TEXT,name TEXT,PRIMARY KEY(agent_id,app_key));
            CREATE TABLE agent_actions (id TEXT PRIMARY KEY,user_id INTEGER,agent_id TEXT,name TEXT,kind TEXT,app_key TEXT,UNIQUE(user_id,name));
            CREATE TABLE agent_commands (id TEXT PRIMARY KEY,user_id INTEGER,agent_id TEXT,kind TEXT,app_key TEXT,created INTEGER,expires INTEGER,status TEXT,result TEXT,claim_hash TEXT,cancel_requested INTEGER DEFAULT 0,dedupe_hash TEXT UNIQUE,alexa_correlation TEXT,alexa_endpoint TEXT,alexa_notified INTEGER DEFAULT 0);
            ''')

    def setUp(self):
        super().setUp()
        config = patch.dict(self.module.app.config, ENABLE_WINDOWS_AGENT=True)
        config.start(); self.addCleanup(config.stop)
        self.service = self.module.agent_service
        self.app_key = str(uuid.uuid4())
        # Traducción del UPSERT para el doble SQLite. MariaDB usa la consulta real.
        original = base.SQLiteMySQLCursor.execute
        def execute(cursor, sql, params=()):
            sql = sql.replace(' ON DUPLICATE KEY UPDATE dedupe_hash=VALUES(dedupe_hash)', ' ON CONFLICT(dedupe_hash) DO NOTHING')
            sql = sql.replace(' FOR UPDATE', '')
            return original(cursor, sql, params)
        translate = patch.object(base.SQLiteMySQLCursor, 'execute', execute)
        translate.start(); self.addCleanup(translate.stop)

    def pair(self):
        started = self.client.post('/api/agent/v1/pair/start', json={'computer_name':'Mi PC'}).get_json()
        self.assertEqual(self.client.post('/api/agent/v1/pair/poll', json={'device_code':started['device_code']}).status_code, 428)
        self.login()
        response = self.client.post('/windows/link', data={'code':started['user_code'],'device_id':'1','csrf_token':self.csrf()})
        self.assertEqual(response.status_code, 200)
        completed = self.client.post('/api/agent/v1/pair/poll', json={'device_code':started['device_code']})
        self.assertEqual(completed.status_code, 200)
        self.credentials = completed.get_json()
        self.headers = {'Authorization':'Bearer '+self.credentials['access_token']}
        self.assertEqual(self.client.post('/api/agent/v1/pair/poll', json={'device_code':started['device_code']}).status_code, 400)
        response = self.client.post('/api/agent/v1/heartbeat', headers=self.headers, json={'allow_shutdown':True,'apps':[{'id':self.app_key,'name':'Spotify'}]})
        self.assertEqual(response.status_code, 200)
        self.agent = self.service.authenticate(self.credentials['access_token'])
        return started

    def command(self, kind='launch', dedupe=None):
        return self.service.enqueue(1, self.credentials['agent_id'], kind, self.app_key if kind=='launch' else None, dedupe or str(uuid.uuid4()))

    def test_agent_pair_bound_to_owner_and_one_use(self):
        self.pair()
        stored = self.module.database.fetch_one('SELECT token_hash FROM agent_connections')
        self.assertNotEqual(stored[0], self.credentials['access_token'])
        self.assertEqual(self.client.get('/windows').status_code, 200)
        self.assertEqual(self.client.get('/').status_code, 200)

    def test_agent_pair_requires_csrf_and_ownership(self):
        started = self.client.post('/api/agent/v1/pair/start', json={'computer_name':'Mi PC'}).get_json()
        self.login()
        self.assertEqual(self.client.post('/windows/link', data={'code':started['user_code'],'device_id':1}).status_code, 400)
        response = self.client.post('/windows/link', data={'code':started['user_code'],'device_id':2,'csrf_token':self.csrf()})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.post('/api/agent/v1/pair/poll', json={'device_code':started['device_code']}).status_code, 428)

    def test_agent_expired_pair_and_authentication(self):
        started = self.client.post('/api/agent/v1/pair/start', json={'computer_name':'Mi PC'}).get_json()
        self.module.database.execute('UPDATE agent_pairings SET expires=0')
        self.assertEqual(self.client.post('/api/agent/v1/pair/poll', json={'device_code':started['device_code']}).status_code,400)
        self.login()
        self.assertEqual(self.client.post('/api/agent/v1/commands/claim', json={}).status_code,401)
        self.assertEqual(self.client.post('/api/agent/v1/commands/claim', data='{}').status_code,415)

    def test_agent_catalog_cannot_receive_paths(self):
        self.pair()
        result = self.client.post('/api/agent/v1/heartbeat', headers=self.headers, json={'apps':[{'id':self.app_key,'name':'Spotify','path':'cmd.exe'}], 'allow_shutdown':True})
        self.assertEqual(result.status_code, 400)
        self.assertEqual(len(self.service.all('SELECT * FROM agent_apps')), 1)

    def test_agent_queue_deduplicates_claims_and_receipts(self):
        self.pair()
        command_id = self.command(dedupe='repeat')
        self.assertEqual(command_id,self.command(dedupe='repeat'))
        claim = self.client.post('/api/agent/v1/commands/claim',headers=self.headers,json={}).get_json()['command']
        self.assertEqual(claim['id'],command_id)
        self.assertIsNone(self.client.post('/api/agent/v1/commands/claim',headers=self.headers,json={}).get_json()['command'])
        endpoint = '/api/agent/v1/commands/'+command_id+'/report'
        self.assertEqual(self.client.post(endpoint,headers=self.headers,json={'status':'executed','claim_token':'wrong'}).status_code,404)
        for _ in range(2):
            self.assertEqual(self.client.post(endpoint,headers=self.headers,json={'status':'executed','claim_token':claim['claim_token']}).status_code,200)

    def test_agent_whitelist_offline_and_permissions(self):
        from windows_agent import AgentError
        self.pair()
        with self.assertRaises(AgentError): self.service.enqueue(2,self.agent['id'],'launch',self.app_key,'foreign')
        with self.assertRaises(AgentError): self.service.enqueue(1,self.agent['id'],'launch',str(uuid.uuid4()),'unknown')
        self.module.database.execute('UPDATE agent_connections SET allow_shutdown=0')
        with self.assertRaises(AgentError): self.command('shutdown')
        self.module.database.execute('UPDATE agent_connections SET last_seen=0')
        with self.assertRaises(AgentError): self.command()

    def test_agent_old_commands_not_replayed(self):
        self.pair(); command_id=self.command()
        self.module.database.execute('UPDATE agent_commands SET expires=0')
        self.assertIsNone(self.service.claim(self.agent)['command'])
        self.assertEqual(self.service.first('SELECT status FROM agent_commands WHERE id=%s',(command_id,))['status'],'expired')

    def test_agent_cancel_prevents_final_authorization(self):
        self.pair(); command_id=self.command('shutdown')
        claim=self.service.claim(self.agent)['command']
        endpoint='/api/agent/v1/commands/'+command_id
        self.assertTrue(self.client.post(endpoint+'/authorize',headers=self.headers,json={'claim_token':claim['claim_token']}).get_json()['allowed'])
        self.client.post('/windows/commands/'+command_id+'/cancel',data={'csrf_token':self.csrf()})
        self.assertFalse(self.client.post(endpoint+'/authorize',headers=self.headers,json={'claim_token':claim['claim_token']}).get_json()['allowed'])
        self.assertIn(command_id,self.service.claim(self.agent)['cancel_commands'])

    def test_agent_revocation_blocks_token(self):
        self.pair()
        self.client.post('/windows/agents/'+self.agent['id']+'/revoke',data={'csrf_token':self.csrf()})
        self.assertEqual(self.client.post('/api/agent/v1/commands/claim',headers=self.headers,json={}).status_code,401)

    def test_agent_create_run_action_and_history(self):
        self.pair()
        response=self.client.post('/windows/actions',data={'csrf_token':self.csrf(),'name':'Spotify en mi PC','kind':'launch','agent_id':self.agent['id'],'app_key':self.app_key})
        self.assertEqual(response.status_code,302)
        action=self.service.first('SELECT id FROM agent_actions')
        response=self.client.post('/windows/actions/'+action['id']+'/run',data={'csrf_token':self.csrf(),'nonce':'test'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(len(self.service.all('SELECT * FROM agent_commands')),1)
        self.assertIn(b'Spotify en mi PC',self.client.get('/windows').data)

    def custom_request(self, envelope, signature=True):
        payload=json.dumps(envelope).encode(); stamp=str(int(time.time()))
        signed=hmac.new(('x'*32).encode(),stamp.encode()+b'.'+payload,hashlib.sha256).hexdigest()
        return self.client.post('/alexa/custom',data=payload,content_type='application/json',headers={'X-Wol-Timestamp':stamp,'X-Wol-Signature':signed if signature else 'wrong'})

    def test_agent_custom_alexa_owner_signature_and_routine(self):
        self.pair()
        self.client.post('/windows/actions',data={'csrf_token':self.csrf(),'name':'Spotify en mi PC','kind':'launch','agent_id':self.agent['id'],'app_key':self.app_key})
        with self.module.state_connection() as db: db.execute('INSERT INTO auth_tokens VALUES (?,?,?,?,?)',('custom-access','custom-refresh','1','test-client',time.time()+600))
        envelope={'context':{'System':{'application':{'applicationId':'test-skill'},'user':{'accessToken':'custom-access'}}},'request':{'type':'LaunchRequest','requestId':'request-1','timestamp':datetime.now(timezone.utc).isoformat(),'task':{'name':'test-skill.ExecuteAction','version':'1','input':{'action':'Spotify en mi PC'}}}}
        with patch.dict(os.environ,ALEXA_BRIDGE_SECRET='x'*32,ALEXA_CUSTOM_SKILL_ID='test-skill'):
            self.assertEqual(self.custom_request(envelope,False).status_code,401)
            for _ in range(2):
                response=self.custom_request(envelope)
                self.assertEqual(response.get_json()['response']['directives'][0]['status']['code'],'200')
            self.assertEqual(len(self.service.all('SELECT * FROM agent_commands')),1)
            envelope['context']['System']['user']['accessToken']='foreign-token'
            self.assertEqual(self.custom_request(envelope).get_json()['response']['directives'][0]['status']['code'],'500')

    def test_agent_login_returns_to_pairing(self):
        started=self.client.post('/api/agent/v1/pair/start',json={'computer_name':'Mi PC'}).get_json()
        self.assertEqual(self.client.get('/windows/link?code='+started['user_code']).status_code,302)
        self.login()
        self.assertIn('/windows/link?code=',self.client.get('/').location)

    def test_agent_feature_disabled(self):
        with patch.dict(self.module.app.config,ENABLE_WINDOWS_AGENT=False):
            self.assertEqual(self.client.post('/api/agent/v1/pair/start',json={'computer_name':'Mi PC'}).status_code,404)

    def test_agent_custom_intent_shutdown_and_skill_id(self):
        self.pair()
        self.client.post('/windows/actions',data={'csrf_token':self.csrf(),'name':'Apagar mi PC','kind':'shutdown','agent_id':self.agent['id']})
        with self.module.state_connection() as db: db.execute('INSERT INTO auth_tokens VALUES (?,?,?,?,?)',('custom-access','custom-refresh','1','test-client',time.time()+600))
        envelope={'context':{'System':{'application':{'applicationId':'test-skill'},'user':{'accessToken':'custom-access'}}},'request':{'type':'IntentRequest','requestId':'request-shutdown','timestamp':datetime.now(timezone.utc).isoformat(),'intent':{'name':'ExecuteActionIntent','slots':{'action':{'value':'Apagar mi PC'}}}}}
        with patch.dict(os.environ,ALEXA_BRIDGE_SECRET='x'*32,ALEXA_CUSTOM_SKILL_ID='test-skill'):
            self.assertIn('Orden enviada',self.custom_request(envelope).get_json()['response']['outputSpeech']['text'])
            self.assertEqual(self.service.claim(self.agent)['command']['kind'],'shutdown')
            envelope['context']['System']['application']['applicationId']='wrong-skill'
            self.assertEqual(self.custom_request(envelope).status_code,400)

    def test_agent_report_does_not_cross_accounts(self):
        self.pair(); command_id=self.command(); command=self.service.claim(self.agent)['command']
        pairing=self.service.pair_start('Otro PC')
        self.service.authorize(pairing['user_code'],2,2)
        other=self.service.pair_finish(pairing['device_code'])
        headers={'Authorization':'Bearer '+other['access_token']}
        self.assertEqual(self.client.post('/api/agent/v1/commands/'+command_id+'/report',headers=headers,json={'status':'executed','claim_token':command['claim_token']}).status_code,404)
        with self.client.session_transaction() as session: session['user_id']=2
        self.client.post('/windows/commands/'+command_id+'/cancel',data={'csrf_token':self.csrf()})
        self.assertEqual(self.service.first('SELECT cancel_requested FROM agent_commands WHERE id=%s',(command_id,))['cancel_requested'],0)

    def test_agent_custom_lambda_signed_payload_and_failure(self):
        import lambda_custom
        event={'request':{'type':'LaunchRequest','task':{'name':'test-skill.ExecuteAction'}}}
        with patch.dict(os.environ,ALEXA_BRIDGE_SECRET='x'*32,WOL_CUSTOM_BACKEND_URL='https://backend.example/alexa/custom'), patch.object(lambda_custom.urllib.request,'build_opener') as build:
            build.return_value.open.side_effect=TimeoutError
            response=lambda_custom.lambda_handler(event,None)
            self.assertEqual(response['response']['directives'][0]['status']['code'],'500')
            outgoing=build.return_value.open.call_args.args[0]
            signature=hmac.new(('x'*32).encode(),outgoing.get_header('X-wol-timestamp').encode()+b'.'+outgoing.data,hashlib.sha256).hexdigest()
            self.assertEqual(outgoing.get_header('X-wol-signature'),signature)
            self.assertEqual(json.loads(outgoing.data),event)
            self.assertEqual(build.return_value.open.call_args.kwargs['timeout'],6)


if __name__ == '__main__':
    import unittest
    unittest.main()
