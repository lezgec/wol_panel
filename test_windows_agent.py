"""Flujo completo del agente sin ejecutar acciones de Windows ni usar cuentas reales."""
import hashlib
import hmac
import json
import os
import time
import uuid
from zipfile import ZipFile
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch
import test_app as base


class AgentFlowTests(base.ApplicationTests):
    def reset_business(self):
        super().reset_business()
        with self.business_connection() as db:
            db.executescript('''
            DROP TABLE IF EXISTS agent_presence;
            DROP TABLE IF EXISTS agent_pairings; DROP TABLE IF EXISTS agent_connections;
            DROP TABLE IF EXISTS agent_apps; DROP TABLE IF EXISTS agent_actions; DROP TABLE IF EXISTS agent_commands;
            CREATE TABLE agent_pairings (device_code_hash TEXT PRIMARY KEY,user_code_hash TEXT UNIQUE,computer_name TEXT,expires INTEGER,user_id INTEGER,device_id INTEGER,status TEXT);
            CREATE TABLE agent_connections (id TEXT PRIMARY KEY,user_id INTEGER,device_id INTEGER UNIQUE,token_hash TEXT UNIQUE,expires INTEGER,last_seen INTEGER,allow_shutdown INTEGER DEFAULT 0,revoked INTEGER DEFAULT 0);
            CREATE TABLE agent_presence (agent_id TEXT PRIMARY KEY,token_hash TEXT UNIQUE,expires INTEGER,last_seen INTEGER DEFAULT 0);
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

    def test_boot_presence_confirms_connection_without_enabling_commands(self):
        self.pair()
        self.module.database.execute('INSERT INTO agent_actions (id,user_id,agent_id,name,kind,app_key) VALUES (%s,%s,%s,%s,%s,%s)',
            (str(uuid.uuid4()), 1, self.agent['id'], 'Spotify de prueba', 'launch', self.app_key))
        registered = self.client.post('/api/agent/v1/presence/register', headers=self.headers, json={})
        self.assertEqual(registered.status_code, 200)
        token = registered.get_json()['access_token']
        boot_headers = {'Authorization': 'Bearer '+token}
        self.module.database.execute('UPDATE agent_connections SET last_seen=0')
        self.assertEqual(self.client.post('/api/agent/v1/presence/heartbeat', headers=boot_headers, json={}).status_code, 200)
        stored = self.service.first('SELECT * FROM agent_presence')
        self.assertNotEqual(stored['token_hash'], token)
        state = self.service.connection_states(1)[1]
        self.assertEqual(state['state'], 'connected')
        self.assertTrue(state['pc_online'])
        self.assertFalse(state['online'])
        self.assertEqual(self.service.connection_states(2), {})
        for route in ('commands/claim', 'heartbeat', 'presence/register', 'presence/revoke', 'unlink'):
            self.assertEqual(self.client.post('/api/agent/v1/'+route, headers=boot_headers, json={}).status_code, 401)
        self.assertEqual(self.client.post('/api/agent/v1/presence/heartbeat', headers=self.headers, json={}).status_code, 401)
        self.assertEqual(self.client.post('/api/agent/v1/presence/heartbeat', headers=boot_headers, json={'apps':[]}).status_code, 400)
        with self.assertRaises(Exception) as failure:
            self.command()
        self.assertEqual(failure.exception.code, 'offline')
        page = self.client.get('/').get_data(as_text=True)
        self.assertIn('PC conectado · agente de sesión sin conexión', page)
        self.assertIn('data-pc-run="1"', page)
        self.assertEqual(self.client.get('/windows/status').get_json()['devices']['1']['state'], 'connected')
        self.module.database.execute('UPDATE agent_presence SET last_seen=0')
        self.assertEqual(self.service.connection_states(1)[1]['state'], 'offline')

    def test_boot_presence_rotation_expiry_and_parent_revocation(self):
        self.pair()
        def register():
            return self.client.post('/api/agent/v1/presence/register', headers=self.headers, json={}).get_json()['access_token']
        def beat(token):
            return self.client.post('/api/agent/v1/presence/heartbeat', headers={'Authorization':'Bearer '+token}, json={})
        first = register()
        second = register()
        self.assertEqual(beat(first).status_code, 401)
        self.assertEqual(beat(second).status_code, 200)
        self.client.post('/api/agent/v1/presence/revoke', headers=self.headers, json={})
        self.assertEqual(beat(second).status_code, 401)
        third = register()
        self.module.database.execute('UPDATE agent_presence SET expires=0')
        self.assertEqual(beat(third).status_code, 401)
        fourth = register()
        self.client.post('/api/agent/v1/unlink', headers=self.headers, json={})
        self.assertEqual(beat(fourth).status_code, 401)
        self.assertEqual(self.service.connection_states(1)[1]['state'], 'unlinked')

    def test_connection_status_requires_owner_session_and_feature(self):
        self.assertEqual(self.client.get('/windows/status').status_code, 302)
        self.pair()
        states = self.client.get('/windows/status')
        self.assertEqual(states.get_json()['devices']['1']['state'], 'ready')
        self.assertNotIn('2', states.get_json()['devices'])
        self.assertEqual(states.headers['Cache-Control'], 'no-store')
        with patch.dict(self.module.app.config, ENABLE_WINDOWS_AGENT=False):
            self.assertEqual(self.client.get('/windows/status').status_code, 404)

    def command(self, kind='launch', dedupe=None):
        return self.service.enqueue(1, self.credentials['agent_id'], kind, self.app_key if kind=='launch' else None, dedupe or str(uuid.uuid4()))

    def test_agent_dashboard_groups_controls_and_preserves_link_on_edit(self):
        self.pair()
        action_id = str(uuid.uuid4())
        self.module.database.execute('INSERT INTO agent_actions (id,user_id,agent_id,name,kind,app_key) VALUES (%s,%s,%s,%s,%s,%s)',
                                    (action_id, 1, self.agent['id'], 'Spotify en mi PC', 'launch', self.app_key))
        self.module.database.execute('INSERT INTO devices (id,name,mac,user_sub) VALUES (%s,%s,%s,%s)', (3, 'Segundo PC', '12:34:56:78:9A:BC', '1'))
        self.client.post('/devices/1/edit', data=dict(name='PC Renombrado', mac='12:34:56:78:9A:BD', wake_method='alexa', csrf_token=self.csrf()))
        data = self.service.dashboard_data(1)
        self.assertEqual(set(data), {1})
        self.assertEqual(data[1]['id'], self.agent['id'])
        self.assertEqual(data[1]['actions'][0]['id'], action_id)
        self.assertEqual(data[1]['apps'][0]['app_key'], self.app_key)
        self.assertEqual(self.service.dashboard_data(2), {})
        page = self.client.get('/')
        self.assertIn(b'PC Renombrado', page.data)
        self.assertIn(b'Spotify en mi PC', page.data)
        self.assertNotIn(b'PC ajena', page.data)
        response = self.client.post('/windows/actions/'+action_id+'/run', data=dict(csrf_token=self.csrf(), nonce='from-card', return_device='1'))
        self.assertEqual(response.location, '/#pc-1')
        self.assertEqual(len(self.service.dashboard_data(1)[1]['commands']), 1)

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

    def test_agent_download_requires_session_and_feature_and_serves_only_configured_file(self):
        archive = Path(self.temp.name) / 'download-test.zip'
        with ZipFile(archive, 'w') as package:
            package.writestr('WolPro.Agent.exe', b'fixture-only-not-executable')
        with patch.dict(self.module.app.config, WINDOWS_AGENT_DOWNLOAD_PATH=str(archive)):
            anonymous = self.client.get('/windows/download')
            self.assertEqual(anonymous.status_code, 302)
            self.assertIn('/login', anonymous.location)
            self.login()
            page = self.client.get('/').get_data(as_text=True)
            self.assertIn('Descargar agente para Windows', page)
            response = self.client.get('/windows/download?path=auth.sqlite3')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, archive.read_bytes())
            self.assertEqual(response.mimetype, 'application/zip')
            self.assertIn('attachment;', response.headers['Content-Disposition'])
            self.assertIn('WoLPro-Agent-win-x64.zip', response.headers['Content-Disposition'])
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            response.close()
            partial = self.client.get('/windows/download', headers={'Range':'bytes=0-9'})
            self.assertEqual(partial.status_code, 206)
            self.assertEqual(partial.data, archive.read_bytes()[:10])
            partial.close()
            with patch.dict(self.module.app.config, ENABLE_WINDOWS_AGENT=False):
                self.assertEqual(self.client.get('/windows/download').status_code, 404)
                self.assertNotIn('Descargar agente para Windows', self.client.get('/').get_data(as_text=True))

    def test_missing_agent_download_has_no_broken_button_or_server_path(self):
        archive = Path(self.temp.name) / 'not-deployed.zip'
        with patch.dict(self.module.app.config, WINDOWS_AGENT_DOWNLOAD_PATH=str(archive)):
            self.login()
            page = self.client.get('/').get_data(as_text=True)
            self.assertIn('Descarga disponible próximamente', page)
            self.assertNotIn('href="/windows/download"', page)
            response = self.client.get('/windows/download')
            self.assertEqual(response.status_code, 503)
            self.assertNotIn(str(archive), response.get_data(as_text=True))

    def test_installer_is_preferred_after_copy_and_portable_download_remains_compatible(self):
        folder = Path(self.temp.name) / 'installer-download'
        folder.mkdir(exist_ok=True)
        installer = folder / 'WoLPro-Agent-Setup.exe'
        portable = folder / 'WoLPro-Agent-win-x64.zip'
        with ZipFile(portable, 'w') as package:
            package.writestr('WolPro.Agent.exe', b'fixture-only')
        with patch.dict(self.module.app.config, WINDOWS_AGENT_DOWNLOAD_PATH=str(installer)):
            self.login()
            # The existing ZIP still works while the administrator uploads Setup.
            response = self.client.get('/windows/download')
            self.assertEqual(response.mimetype, 'application/zip')
            self.assertEqual(response.data, portable.read_bytes())
            response.close()
            installer.write_bytes(b'MZfixture-only-not-an-installer')
            page = self.client.get('/').get_data(as_text=True)
            self.assertIn('Instalador. Ábrelo', page)
            self.assertNotIn('ZIP portátil.', page)
            response = self.client.get('/windows/download?path=auth.sqlite3')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, 'application/octet-stream')
            self.assertEqual(response.data, installer.read_bytes())
            self.assertIn('WoLPro-Agent-Setup.exe', response.headers['Content-Disposition'])
            self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
            response.close()
            # An explicit custom ZIP location remains respected.
            with patch.dict(self.module.app.config, WINDOWS_AGENT_DOWNLOAD_PATH=str(portable)):
                response = self.client.get('/windows/download')
                self.assertEqual(response.mimetype, 'application/zip')
                response.close()

    def test_saved_console_command_uses_catalog_and_can_be_revoked_before_execution(self):
        self.pair()
        response = self.client.post('/api/agent/v1/heartbeat', headers=self.headers,
            json={'apps':[{'id':self.app_key,'name':'Reiniciar mi PC'}], 'allow_shutdown':False})
        self.assertEqual(response.status_code, 200)
        created = self.client.post('/windows/actions', data={'csrf_token':self.csrf(),
            'name':'Reiniciar mi PC', 'kind':'launch','agent_id':self.agent['id'],'app_key':self.app_key})
        self.assertEqual(created.status_code, 302)
        action = self.service.first('SELECT * FROM agent_actions WHERE agent_id=%s', (self.agent['id'],))
        command_id = self.service.execute_action(1, action['id'], 'console-test')
        claim = self.client.post('/api/agent/v1/commands/claim', headers=self.headers, json={}).get_json()['command']
        self.assertEqual(claim['id'], command_id)
        self.assertEqual(claim['app_key'], self.app_key)
        self.assertNotIn('script', claim)
        endpoint = '/api/agent/v1/commands/' + command_id + '/authorize'
        receipt = {'claim_token':claim['claim_token']}
        self.assertTrue(self.client.post(endpoint, headers=self.headers, json=receipt).get_json()['allowed'])
        page = self.client.get('/').get_data(as_text=True)
        self.assertIn('Aplicación o comando autorizado', page)
        self.assertIn('Reiniciar mi PC', page)
        # Turning off the local console permission withdraws commands from heartbeat.
        self.client.post('/api/agent/v1/heartbeat', headers=self.headers, json={'apps':[], 'allow_shutdown':False})
        self.assertFalse(self.client.post(endpoint, headers=self.headers, json=receipt).get_json()['allowed'])
        rejected = self.client.post('/api/agent/v1/heartbeat', headers=self.headers,
            json={'apps':[{'id':self.app_key,'name':'Reiniciar','script':'shutdown.exe /r /t 0'}], 'allow_shutdown':False})
        self.assertEqual(rejected.status_code, 400)

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
        with patch.dict(os.environ,ALEXA_BRIDGE_SECRET='x'*32,ALEXA_SKILL_ID='test-skill'):
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
        with patch.dict(os.environ,ALEXA_BRIDGE_SECRET='x'*32,ALEXA_SKILL_ID='test-skill'):
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
        import lambda_function
        event={'request':{'type':'LaunchRequest','task':{'name':'test-skill.ExecuteAction'}}}
        with patch.dict(os.environ,ALEXA_BRIDGE_SECRET='x'*32,WOL_BACKEND_URL='https://backend.example/alexa/smarthome'), patch.object(lambda_custom.urllib.request,'build_opener') as build:
            build.return_value.open.side_effect=TimeoutError
            response=lambda_function.lambda_handler(event,None)
            self.assertEqual(response['response']['directives'][0]['status']['code'],'500')
            outgoing=build.return_value.open.call_args.args[0]
            self.assertEqual(outgoing.full_url,'https://backend.example/alexa/custom')
            self.assertEqual(outgoing.get_header('User-agent'),'WoLPro-Alexa-Bridge/1.0')
            signature=hmac.new(('x'*32).encode(),outgoing.get_header('X-wol-timestamp').encode()+b'.'+outgoing.data,hashlib.sha256).hexdigest()
            self.assertEqual(outgoing.get_header('X-wol-signature'),signature)
            self.assertEqual(json.loads(outgoing.data),event)
            self.assertEqual(build.return_value.open.call_args.kwargs['timeout'],6)

    def test_agent_one_lambda_both_models_same_linked_account(self):
        import lambda_function
        from urllib.parse import urlsplit
        self.pair()
        self.client.post('/windows/actions',data={'csrf_token':self.csrf(),'name':'Spotify en mi PC','kind':'launch','agent_id':self.agent['id'],'app_key':self.app_key})
        token=self.token()
        envelope={'context':{'System':{'application':{'applicationId':'same-skill'},'user':{'accessToken':token}}},'request':{'type':'IntentRequest','requestId':'shared-request','timestamp':datetime.now(timezone.utc).isoformat(),'intent':{'name':'ExecuteActionIntent','slots':{'action':{'value':'Spotify en mi PC'}}}}}
        with patch.dict(os.environ,ALEXA_SKILL_ID='same-skill',ALEXA_BRIDGE_SECRET='s'*32,WOL_BACKEND_URL='https://backend.example/alexa/smarthome'), patch('lambda_custom.urllib.request.build_opener') as build, patch('lambda_function.urllib.request.urlopen',side_effect=TimeoutError) as smart:
            build.return_value.open.side_effect=TimeoutError
            lambda_function.lambda_handler(envelope,None)
            outgoing=build.return_value.open.call_args.args[0]
            response=self.client.post(urlsplit(outgoing.full_url).path,data=outgoing.data,headers=dict(outgoing.header_items()))
            self.assertEqual(response.status_code,200)
            self.assertIn('Orden enviada',response.get_json()['response']['outputSpeech']['text'])
            smart.assert_not_called()
            lambda_function.lambda_handler(self.directive(token,'Discover',namespace='Alexa.Discovery'),None)
            outgoing=smart.call_args.args[0]
            self.assertEqual(outgoing.full_url,'https://backend.example/alexa/smarthome')
            response=self.client.post(urlsplit(outgoing.full_url).path,data=outgoing.data,headers=dict(outgoing.header_items()))
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.get_json()['event']['header']['name'],'Discover.Response')
            self.assertEqual(self.service.first('SELECT user_id FROM agent_commands')['user_id'],1)

    def mobile_headers(self):
        return {'X-CSRF-Token': self.csrf()}

    def test_mobile_control_scope_secrets_and_presence(self):
        self.assertEqual(self.client.get('/api/mobile/v1/control').status_code, 401)
        self.pair()
        response = self.client.get('/api/mobile/v1/control')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        pc = response.json['pcs'][0]
        self.assertEqual(pc['device_id'], 1)
        self.assertTrue(pc['online'])
        self.assertEqual(pc['state'], 'ready')
        self.assertEqual(pc['apps'][0]['name'], 'Spotify')
        self.assertNotIn('token_hash', response.get_data(as_text=True))
        self.assertNotIn('nonce', pc)
        self.assertEqual(self.client.get('/api/mobile/v1/devices').json['devices'][0]['agent_state'], 'ready')
        self.module.database.execute('UPDATE agent_connections SET last_seen=0')
        registration = self.client.post('/api/agent/v1/presence/register', headers=self.headers, json={}).json
        self.client.post('/api/agent/v1/presence/heartbeat', headers={'Authorization': 'Bearer '+registration['access_token']}, json={})
        pc = self.client.get('/api/mobile/v1/control').json['pcs'][0]
        self.assertEqual(pc['state'], 'connected')
        self.assertFalse(pc['online'])
        self.assertTrue(pc['pc_online'])
        with self.client.session_transaction() as session:
            session['user_id'] = 2
        self.assertEqual(self.client.get('/api/mobile/v1/control').json['pcs'], [])

    def test_mobile_run_idempotent_authorized_and_claimable(self):
        self.pair()
        payload = {'kind':'launch', 'app_key':self.app_key, 'request_id':str(uuid.uuid4())}
        route = '/api/mobile/v1/control/devices/1/run'
        self.assertEqual(self.client.post(route, json=payload).status_code, 400)
        headers = self.mobile_headers()
        self.assertEqual(self.client.post('/api/mobile/v1/control/devices/2/run', headers=headers, json=payload).status_code, 404)
        bad = self.client.post(route, headers=headers, json={**payload, 'app_key':str(uuid.uuid4())})
        self.assertEqual(bad.status_code, 409)
        self.assertEqual(self.client.post(route, headers=headers, json={**payload, 'request_id':'bad'}).status_code, 400)
        first = self.client.post(route, headers=headers, json=payload)
        second = self.client.post(route, headers=headers, json=payload)
        self.assertEqual(first.status_code, 202)
        self.assertEqual(first.json['command_id'], second.json['command_id'])
        self.assertEqual(len(self.service.all('SELECT * FROM agent_commands')), 1)
        public = self.client.get('/api/mobile/v1/control').json['pcs'][0]['commands'][0]
        self.assertNotIn('claim_hash', public)
        self.assertNotIn('dedupe_hash', public)
        claimed = self.client.post('/api/agent/v1/commands/claim', headers=self.headers, json={}).json['command']
        self.assertEqual(claimed['id'], first.json['command_id'])
        self.assertEqual(claimed['app_key'], self.app_key)
        self.assertEqual(self.client.post('/api/mobile/v1/control/commands/'+claimed['id']+'/cancel', headers=headers).status_code, 409)

    def test_mobile_offline_and_revoked_catalog(self):
        self.pair()
        headers = self.mobile_headers()
        self.module.database.execute('UPDATE agent_connections SET last_seen=0')
        payload = {'kind':'launch', 'app_key':self.app_key, 'request_id':str(uuid.uuid4())}
        self.assertEqual(self.client.post('/api/mobile/v1/control/devices/1/run', headers=headers, json=payload).status_code, 409)
        self.module.database.execute('UPDATE agent_connections SET last_seen=%s,allow_shutdown=0', (int(time.time()),))
        self.assertEqual(self.client.post('/api/mobile/v1/control/devices/1/run', headers=headers, json={**payload,'kind':'shutdown'}).status_code, 409)
        self.assertEqual(self.client.delete('/api/mobile/v1/control/devices/2/agent', headers=headers).status_code, 404)
        self.assertEqual(self.client.delete('/api/mobile/v1/control/devices/1/agent', headers=headers).status_code, 200)
        pc = self.client.get('/api/mobile/v1/control').json['pcs'][0]
        self.assertFalse(pc['active'])
        self.assertEqual(pc['apps'], [])
        self.assertEqual(self.client.post('/api/agent/v1/heartbeat', headers=self.headers, json={'allow_shutdown':True,'apps':[]}).status_code, 401)

    def test_mobile_cancel_pending_and_shutdown_only(self):
        self.pair()
        headers = self.mobile_headers()
        command_id = self.command()
        route = '/api/mobile/v1/control/commands/'+command_id+'/cancel'
        with self.client.session_transaction() as session:
            session['user_id'] = 2
        self.assertEqual(self.client.post(route, headers=headers).status_code, 404)
        with self.client.session_transaction() as session:
            session['user_id'] = 1
        self.assertEqual(self.client.post(route, headers=headers).status_code, 200)
        self.assertEqual(self.service.first('SELECT status FROM agent_commands WHERE id=%s', (command_id,))['status'], 'cancelled')
        shutdown_id = self.command('shutdown')
        self.client.post('/api/agent/v1/commands/claim', headers=self.headers, json={})
        self.assertEqual(self.client.post('/api/mobile/v1/control/commands/'+shutdown_id+'/cancel', headers=headers).status_code, 200)
        claim = self.client.post('/api/agent/v1/commands/claim', headers=self.headers, json={}).json
        self.assertIn(shutdown_id, claim['cancel_commands'])

    def test_mobile_pair_preview_confirm_and_actions(self):
        self.login()
        headers = self.mobile_headers()
        started = self.client.post('/api/agent/v1/pair/start', json={'computer_name':'PC de prueba'}).json
        self.assertEqual(self.client.post('/api/mobile/v1/control/pair/preview', headers=headers, json={'code':started['user_code']}).json['computer_name'], 'PC de prueba')
        self.assertEqual(self.client.post('/api/mobile/v1/control/devices/2/pair', headers=headers, json={'code':started['user_code']}).status_code, 404)
        self.assertEqual(self.client.post('/api/mobile/v1/control/devices/1/pair', headers=headers, json={'code':started['user_code']}).status_code, 200)
        self.assertEqual(self.client.post('/api/mobile/v1/control/devices/1/pair', headers=headers, json={'code':started['user_code']}).status_code, 400)
        creds = self.client.post('/api/agent/v1/pair/poll', json={'device_code':started['device_code']}).json
        self.client.post('/api/agent/v1/heartbeat', headers={'Authorization':'Bearer '+creds['access_token']}, json={'allow_shutdown':True,'apps':[{'id':self.app_key,'name':'Spotify'}]})
        created = self.client.post('/api/mobile/v1/control/devices/1/actions', headers=headers, json={'kind':'launch','name':'Abrir Spotify','app_key':self.app_key})
        self.assertEqual(created.status_code, 201)
        self.assertEqual(self.client.get('/api/mobile/v1/control').json['pcs'][0]['actions'][0]['name'], 'Abrir Spotify')
        route = '/api/mobile/v1/control/actions/'+created.json['action_id']
        with self.client.session_transaction() as session:
            session['user_id'] = 2
        self.assertEqual(self.client.delete(route, headers=headers).status_code, 404)
        with self.client.session_transaction() as session:
            session['user_id'] = 1
        self.assertEqual(self.client.delete(route, headers=headers).status_code, 200)
        with patch.dict(self.module.app.config, ENABLE_WINDOWS_AGENT=False):
            self.assertEqual(self.client.get('/api/mobile/v1/control').status_code, 404)

    def test_mobile_delete_device_scoped_and_csrf(self):
        self.login()
        self.assertEqual(self.client.delete('/api/mobile/v1/devices/1').status_code, 400)
        headers = self.mobile_headers()
        self.assertEqual(self.client.delete('/api/mobile/v1/devices/2', headers=headers).status_code, 404)
        self.assertEqual(self.client.delete('/api/mobile/v1/devices/1', headers=headers).status_code, 200)
        self.assertEqual(self.client.get('/api/mobile/v1/devices').json['devices'], [])


if __name__ == '__main__':
    import unittest
    unittest.main()
