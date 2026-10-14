"""Behavioral regressions: entitlement expiry, queue guards, billing and admin."""
import base64
import hashlib
import json
import os
import time
import unittest
import uuid
from unittest.mock import patch
from datetime import datetime, timezone
from urllib.parse import urlencode, quote, unquote_to_bytes
import test_windows_agent as agent_tests
from windows_agent import AgentError
from admin_api import totp
from monetization import DEFAULT_ADS
from ads_verification import AdMobVerifier, CONSOLE_CHECK


class MonetizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        agent_tests.AgentFlowTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        agent_tests.AgentFlowTests.tearDownClass()

    def setUp(self):
        self.f=agent_tests.AgentFlowTests('test_router_destination_validation')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.app=self.f.module
        self.plans=self.app.plans
        self.client=self.f.client
        self.clear_premium()

    def clear_premium(self):
        with self.plans.state() as db:
            db.execute('DELETE FROM plan_grants')

    def premium(self,expires=None):
        with self.plans.state() as db:
            db.execute('INSERT INTO plan_grants VALUES (?,?,?,?,?,?,?)',(str(uuid.uuid4()),'1','courtesy',expires or int(time.time())+3600,0,int(time.time()),'Prueba de cortesía'))

    def headers(self):
        self.f.login()
        return {'X-CSRF-Token':self.f.csrf()}

    def ads(self):
        with self.plans.state() as db:
            db.execute("INSERT INTO plan_config VALUES ('ads',?)",(json.dumps({**DEFAULT_ADS,'enabled':True}),))

    def admin_login(self,user_id=1):
        secret=base64.b32encode(b'test-secret-only-1234').decode()
        with self.plans.state() as db:
            db.execute('INSERT INTO admin_owners(user_id,secret) VALUES (?,?)',(str(user_id),secret))
        self.code=totp(secret,int(time.time())//30)
        response=self.client.post('/api/admin/v1/login',headers={'Origin':'http://localhost'},json=dict(email='owner@example.invalid',password='Password1!',code=self.code))
        self.assertEqual(response.status_code,200)
        return {'Origin':'http://localhost','X-Admin-CSRF':response.json['csrf']}

    def test_free_quota_applies_to_web_mobile_and_new_agent_pair(self):
        headers=self.headers()
        self.assertEqual(self.client.post('/api/mobile/v1/devices',headers=headers,json=dict(name='Extra',mac='AA:BB:CC:DD:EE:02')).status_code,403)
        response=self.client.post('/add',data=dict(name='Extra',mac='AA:BB:CC:DD:EE:02',wake_method='alexa',csrf_token=self.f.csrf()),follow_redirects=True)
        self.assertIn('límite',response.get_data(as_text=True))
        started=self.app.agent_service.pair_start('Extra')
        with self.assertRaises(AgentError) as failure:
            self.app.agent_service.authorize(started['user_code'],1,0,'Extra','AA:BB:CC:DD:EE:02')
        self.assertEqual(failure.exception.code,'device_limit')
        self.assertEqual(self.plans.devices(1),[1])

    def test_premium_maximum_and_selection_preserve_config_after_expiry(self):
        self.premium()
        for index in range(9): self.plans.create_device(1,'PC '+str(index),'AA:BB:CC:DD:EE:01')
        with self.assertRaises(AgentError): self.plans.create_device(1,'Once','AA:BB:CC:DD:EE:01')
        selected=self.plans.devices(1)[-1]
        self.plans.select(1,selected)
        self.clear_premium()
        self.assertEqual(len(self.plans.devices(1)),10)
        self.assertEqual(self.plans.active_devices(1),[selected])
        with self.assertRaises(AgentError): self.plans.require(1,1,'shutdown')
        self.plans.require(1,selected,'shutdown')
        with self.assertRaises(AgentError): self.plans.select(1,2)

    def test_free_shutdown_works_and_apps_fail_in_all_queue_channels(self):
        self.f.pair()
        shutdown=self.app.agent_service.enqueue(1,self.f.agent['id'],'shutdown',None,str(uuid.uuid4()))
        self.assertTrue(shutdown)
        with self.assertRaises(AgentError) as failure: self.f.command()
        self.assertEqual(failure.exception.code,'premium_required')
        response=self.client.post('/api/mobile/v1/control/devices/1/run',headers={'X-CSRF-Token':self.f.csrf()},json=dict(kind='launch',app_key=self.f.app_key,request_id=str(uuid.uuid4())))
        self.assertEqual(response.status_code,403)
        saved=self.client.post('/api/mobile/v1/control/devices/1/actions',headers={'X-CSRF-Token':self.f.csrf()},json=dict(kind='launch',app_key=self.f.app_key,name='Spotify'))
        self.assertEqual(saved.status_code,403)
        action=str(uuid.uuid4())
        self.app.database.execute('INSERT INTO agent_actions VALUES (%s,%s,%s,%s,%s,%s)',(action,1,self.f.agent['id'],'Spotify','launch',self.f.app_key))
        with self.assertRaises(AgentError): self.app.agent_service.execute_action(1,action,str(uuid.uuid4()))

    def test_premium_expiry_after_claim_denies_execution_but_allows_cancellation(self):
        self.premium(); self.f.pair(); command=self.f.command()
        claim=self.client.post('/api/agent/v1/commands/claim',headers=self.f.headers,json={}).json['command']
        pending=self.f.command()
        self.clear_premium()
        allowed=self.client.post('/api/agent/v1/commands/'+command+'/authorize',headers=self.f.headers,json=dict(claim_token=claim['claim_token']))
        self.assertFalse(allowed.json['allowed'])
        result=self.client.post('/api/mobile/v1/control/commands/'+pending+'/cancel',headers={'X-CSRF-Token':self.f.csrf()},json={})
        self.assertEqual(result.status_code,200)

    def test_free_discovery_only_exposes_selected_pc(self):
        self.premium(); extra=self.plans.create_device(1,'Segundo','AA:BB:CC:DD:EE:01'); self.plans.select(1,extra); self.clear_premium()
        self.f.set_device_method('alexa')
        result=self.client.post('/alexa/smarthome',json=self.f.directive(self.f.token(),name='Discover',namespace='Alexa.Discovery'))
        self.assertEqual([e['endpointId'] for e in result.json['event']['payload']['endpoints']],[str(extra)])

    def test_reward_is_30_minutes_account_wide_idempotent_without_premium(self):
        self.ads(); ticket=self.plans.ad_ticket(1,'rewarded')['ticket']
        self.plans.verified_reward(ticket,'verified-transaction')
        first=self.plans.public(1)
        self.assertEqual(first['tier'],'free'); self.assertFalse(first['can_launch']); self.assertFalse(first['ads']['enabled'])
        self.assertAlmostEqual(first['ad_free_until']-time.time(),1800,delta=2)
        self.plans.verified_reward(ticket,'verified-transaction')
        self.assertEqual(self.plans.public(1)['ad_free_until'],first['ad_free_until'])
        self.assertTrue(self.plans.public(2)['ads']['enabled'])
        with self.assertRaises(AgentError): self.plans.verified_reward('other-ticket','verified-transaction')

    def test_ads_test_scope_covers_all_app_formats_and_preserves_entitlements(self):
        with patch.dict(os.environ, ADS_TEST_USER_IDS='1'):
            self.assertFalse(self.plans.public(1)['ads']['enabled'])
            self.ads()
            policy = self.plans.public(1)['ads']
            self.assertTrue(policy['enabled']); self.assertTrue(policy['rewarded'])
            self.assertTrue(policy['banner']); self.assertTrue(policy['interstitial']); self.assertFalse(policy['web'])
            self.assertFalse(self.plans.public(2)['ads']['enabled'])
            for user_id, kind in ((2, 'rewarded'), (2, 'interstitial')):
                with self.assertRaises(AgentError) as error: self.plans.ad_ticket(user_id, kind)
                self.assertEqual(error.exception.code, 'ads_disabled')
            self.plans.ad_ticket(1, 'interstitial')
            with self.plans.state() as db:
                db.execute("UPDATE plan_config SET value=? WHERE key='ads'", (json.dumps({**DEFAULT_ADS, 'enabled': True, 'banner': False, 'interstitial': False}),))
            self.assertFalse(self.plans.public(1)['ads']['banner'])
            with self.assertRaises(AgentError): self.plans.ad_ticket(1, 'interstitial')
            self.premium()
            self.assertFalse(self.plans.public(1)['ads']['enabled'])
            with self.assertRaises(AgentError): self.plans.ad_ticket(1, 'rewarded')
            self.clear_premium()
            ticket = self.plans.ad_ticket(1, 'rewarded')['ticket']
            self.plans.verified_reward(ticket, 'test-scope-signed-reward')
            account = self.plans.public(1)
            self.assertEqual(account['tier'], 'free')
            self.assertAlmostEqual(account['ad_free_until']-time.time(), 1800, delta=2)
            self.assertFalse(account['ads']['enabled'])

    def test_invalid_ads_test_scope_fails_closed(self):
        self.ads()
        for scope in ('1,', '1,all', '0', '-1', '١'):
            with self.subTest(scope=scope), patch.dict(os.environ, ADS_TEST_USER_IDS=scope):
                self.assertFalse(self.plans.public(1)['ads']['enabled'])
                with self.assertRaises(AgentError): self.plans.ad_ticket(1, 'rewarded')

    def test_web_readiness_scope_and_pause_are_independent_of_android_test_scope(self):
        self.ads()
        with patch.dict(os.environ, ADS_WEB_READY='0', ADS_WEB_TEST_USER_IDS='', ADS_TEST_USER_IDS='1'):
            self.assertFalse(self.plans.public(1)['ads']['web'])
        with patch.dict(os.environ, ADS_WEB_READY='1', ADS_WEB_TEST_USER_IDS='2', ADS_TEST_USER_IDS='1'):
            self.assertTrue(self.plans.public(1)['ads']['enabled'])
            self.assertFalse(self.plans.public(1)['ads']['web'])
            self.assertFalse(self.plans.public(2)['ads']['enabled'])
            self.assertTrue(self.plans.public(2)['ads']['web'])
            with self.assertRaises(AgentError): self.plans.ad_ticket(2, 'rewarded')
        with patch.dict(os.environ, ADS_WEB_READY='1', ADS_WEB_TEST_USER_IDS='1', ADS_TEST_USER_IDS='1'):
            self.assertTrue(self.plans.public(1)['ads']['web'])
            self.premium()
            self.assertFalse(self.plans.public(1)['ads']['web'])
            self.clear_premium()
            ticket = self.plans.ad_ticket(1, 'rewarded')['ticket']
            self.plans.verified_reward(ticket, 'web-pause-verified')
            self.assertFalse(self.plans.public(1)['ads']['web'])

    def test_invalid_web_scope_and_disabled_admin_policy_block_web(self):
        self.ads()
        with patch.dict(os.environ, ADS_WEB_READY='1'):
            for scope in ('1,', '1,all', '0', '-1', '١'):
                with self.subTest(scope=scope), patch.dict(os.environ, ADS_WEB_TEST_USER_IDS=scope):
                    self.assertFalse(self.plans.public(1)['ads']['web'])
            with patch.dict(os.environ, ADS_WEB_TEST_USER_IDS='1'):
                with self.plans.state() as db:
                    db.execute("UPDATE plan_config SET value=? WHERE key='ads'", (json.dumps({**DEFAULT_ADS, 'enabled': True, 'web': False}),))
                self.assertFalse(self.plans.public(1)['ads']['web'])
                with self.plans.state() as db:
                    db.execute("UPDATE plan_config SET value=? WHERE key='ads'", (json.dumps({**DEFAULT_ADS, 'enabled': False, 'web': True}),))
                self.assertFalse(self.plans.public(1)['ads']['web'])

    def test_interstitial_frequency_and_daily_cap_are_server_side(self):
        # Keep simulated impressions in one UTC day, even near midnight.
        noon=(int(time.time())//86400)*86400+43200
        with patch('monetization.time.time',return_value=noon):
            self.ads()
            self.plans.ad_ticket(1,'interstitial')
            with self.assertRaises(AgentError) as failure: self.plans.ad_ticket(1,'interstitial')
            self.assertEqual(failure.exception.code,'ad_frequency')
            with self.plans.state() as db: db.execute('UPDATE ad_tickets SET created=created-601')
            self.plans.ad_ticket(1,'interstitial')
            with self.plans.state() as db: db.execute('UPDATE ad_tickets SET created=created-601')
            self.plans.ad_ticket(1,'interstitial')
            with self.plans.state() as db: db.execute('UPDATE ad_tickets SET created=created-601')
            with self.assertRaises(AgentError): self.plans.ad_ticket(1,'interstitial')

    def test_admob_signature_over_raw_query_rejects_tampering(self):
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import hashes
        private=ec.generate_private_key(ec.SECP256R1())
        verifier=AdMobVerifier(); verifier.keys={7:private.public_key()}; verifier.updated=time.time()
        raw=urlencode(dict(ad_unit='3375316331',timestamp=int(time.time()*1000),custom_data='ticket',transaction_id='transaction')).encode()
        signature=base64.urlsafe_b64encode(private.sign(raw,ec.ECDSA(hashes.SHA256()))).rstrip(b'=')
        query=raw+b'&signature='+signature+b'&key_id=7'
        for unit in ('3375316331','ca-app-pub-8703217786138724/3375316331'):
            with self.subTest(unit=unit),patch.dict(os.environ,ADMOB_REWARDED_UNIT=unit):
                self.assertEqual(verifier.verify(query),('ticket','transaction'))
                with self.assertRaises(AgentError): verifier.verify(query.replace(b'ticket',b'forged'))
        for unit in ('9595083634','invalid-unit'):
            with self.subTest(unit=unit),patch.dict(os.environ,ADMOB_REWARDED_UNIT=unit):
                with self.assertRaises(AgentError): verifier.verify(query)

    def test_signed_console_check_never_grants_reward_and_normal_tickets_still_work(self):
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import hashes
        private=ec.generate_private_key(ec.SECP256R1())
        verifier=self.app.admob_verifier

        def query(ticket=CONSOLE_CHECK,unit='3375316331',timestamp=None):
            raw=urlencode(dict(ad_unit=unit,timestamp=timestamp or int(time.time()*1000),
                               custom_data=ticket,reward_item='minutos sin anuncios',
                               transaction_id='console-test-transaction'),quote_via=quote).encode()
            signature=base64.urlsafe_b64encode(private.sign(unquote_to_bytes(raw),ec.ECDSA(hashes.SHA256()))).rstrip(b'=')
            return (raw+b'&signature='+signature+b'&key_id=7').decode()

        with patch.dict(os.environ,ADMOB_REWARDED_UNIT='ca-app-pub-8703217786138724/3375316331'), \
             patch.object(verifier,'keys',{7:private.public_key()}), \
             patch.object(verifier,'updated',time.time()), \
             patch.object(self.plans,'verified_reward',wraps=self.plans.verified_reward) as reward:
            before=self.plans.public(1)
            signed=query()
            console_signed=query(unit='1234567890')
            for diagnostic in (signed,console_signed):
                for _ in range(2):
                    response=self.client.get('/api/ads/ssv?'+diagnostic)
                    self.assertEqual(response.status_code,200)
                    self.assertEqual(response.json,dict(status='verified',diagnostic=True,reward_granted=False))
            reward.assert_not_called()
            self.assertEqual(self.plans.public(1),before)
            for invalid in ('custom_data='+CONSOLE_CHECK,
                            signed.replace(CONSOLE_CHECK,'tampered'),
                            console_signed.replace(CONSOLE_CHECK,'tampered'),
                            console_signed.replace('console-test-transaction','forged-transaction'),
                            console_signed.replace('key_id=7','key_id=8'),
                            query(ticket='unknown-ticket',unit='1234567890'),
                            query(unit='9595083634'),
                            query(unit='1234567891'),
                            query(timestamp=int((time.time()-600.02)*1000)),
                            query(timestamp=int((time.time()-601)*1000)),
                            query(unit='1234567890',timestamp=int((time.time()-601)*1000))):
                self.assertEqual(self.client.get('/api/ads/ssv?'+invalid).status_code,403)
            reward.assert_not_called()
            self.assertEqual(self.client.get('/api/ads/ssv?'+query(ticket='unknown-ticket')).status_code,400)
            self.assertEqual(self.plans.public(1),before)
            self.ads()
            ticket=self.plans.ad_ticket(1,'rewarded')['ticket']
            self.assertEqual(self.client.get('/api/ads/ssv?'+query(ticket=ticket,unit='1234567890')).status_code,403)
            self.assertEqual(self.plans.public(1)['tier'],'free')
            self.assertEqual(self.plans.public(1)['ad_free_until'],before['ad_free_until'])
            self.assertEqual(self.client.get('/api/ads/ssv?'+query(ticket=ticket)).status_code,200)
            self.assertAlmostEqual(self.plans.public(1)['ad_free_until']-time.time(),1800,delta=2)
            self.assertEqual(self.plans.public(1)['tier'],'free')

    def test_ssv_uri_decoding_preserves_signed_order_plus_and_rejects_tampering(self):
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import hashes
        private=ec.generate_private_key(ec.SECP256R1())
        verifier=AdMobVerifier(); verifier.keys={7:private.public_key()}; verifier.updated=time.time()

        def signed(raw,escape_signature=False):
            signature=base64.urlsafe_b64encode(private.sign(unquote_to_bytes(raw),ec.ECDSA(hashes.SHA256())))
            if escape_signature: signature=signature.replace(b'=',b'%3D')
            return raw+b'&signature='+signature+b'&key_id=7'

        with patch.dict(os.environ,ADMOB_REWARDED_UNIT='3375316331'):
            for item in ('30 minutos sin anuncios','crédito + 30 minutos','literal%20'):
                raw=urlencode(dict(ad_unit='3375316331',custom_data='ticket',reward_item=item,
                                   timestamp=int(time.time()*1000),transaction_id='transaction'),quote_via=quote).encode()
                for escape in (False,True):
                    with self.subTest(item=item,escape_signature=escape):
                        query=signed(raw,escape)
                        self.assertEqual(verifier.verify(query),('ticket','transaction'))
                        with self.assertRaises(AgentError): verifier.verify(query.replace(b'ticket',b'forged'))
                        with self.assertRaises(AgentError): verifier.verify(query.replace(b'reward_item=',b'reward_item=changed'))
                if b'%2B' in raw:
                    self.assertEqual(verifier.verify(signed(raw.replace(b'%2B',b'+'))),('ticket','transaction'))
            for item in ('bad%escape','one&custom_data=forged'):
                raw=urlencode(dict(ad_unit='3375316331',custom_data='ticket',reward_item='placeholder',
                                   timestamp=int(time.time()*1000),transaction_id='transaction')).encode()
                replacement=item.encode() if '%' in item else quote(item).encode()
                with self.assertRaises(AgentError): verifier.verify(signed(raw.replace(b'placeholder',replacement)))

    def test_client_cannot_grant_reward_or_premium_with_a_flag(self):
        headers=self.headers()
        self.assertEqual(self.client.post('/api/ads/ssv',headers=headers,json={'rewarded':True}).status_code,405)
        self.assertEqual(self.client.post('/api/mobile/v1/plan/purchase',headers=headers,json={'premium':True}).status_code,400)
        self.assertEqual(self.plans.snapshot(1)['tier'],'free')

    def test_ssv_rejection_log_identifies_stage_without_receipt_or_user_data(self):
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import hashes
        private=ec.generate_private_key(ec.SECP256R1())
        verifier=AdMobVerifier(); verifier.keys={7:private.public_key()}; verifier.updated=time.time()
        raw=urlencode(dict(ad_unit='3375316331',timestamp=int(time.time()*1000),
                           custom_data='secret-ticket',transaction_id='secret-transaction',
                           user_id='private@example.invalid')).encode()
        signature=base64.urlsafe_b64encode(private.sign(raw,ec.ECDSA(hashes.SHA256()))).rstrip(b'=')
        query=raw+b'&signature='+signature+b'&key_id=7'
        cases=[(query.replace(b'secret-ticket',b'changed-ticket'),'signature'),
               (query.replace(b'3375316331',b'9595083634'),'ad_unit'),
               (b'custom_data=secret-ticket','query_structure')]
        with patch.dict(os.environ,ADMOB_REWARDED_UNIT='3375316331'):
            for rejected,stage in cases:
                with self.subTest(stage=stage),self.assertLogs('ads_verification',level='WARNING') as logs:
                    with self.assertRaises(AgentError): verifier.verify(rejected)
                message=' '.join(logs.output)
                self.assertIn('stage='+stage,message)
                for sensitive in ('secret-ticket','changed-ticket','secret-transaction','private',signature.decode()):
                    self.assertNotIn(sensitive,message)

    def receipt(self,state='SUBSCRIPTION_STATE_ACTIVE'):
        return dict(subscriptionState=state,acknowledgementState='ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED',externalAccountIdentifiers={'obfuscatedExternalAccountId':self.app.billing.account_id(1)},lineItems=[dict(productId='premium',expiryTime=datetime.fromtimestamp(time.time()+3600,timezone.utc).isoformat(),autoRenewingPlan={'autoRenewEnabled':True})])

    def test_verified_purchase_cancel_expiry_and_token_owner(self):
        with patch.dict(os.environ,GOOGLE_PLAY_PRODUCTS='premium'),patch.object(self.app.billing,'google',return_value=self.receipt()) as provider:
            self.app.billing.verify(1,'purchase-token-one')
            self.assertEqual(self.plans.snapshot(1)['tier'],'premium')
            with self.assertRaises(AgentError): self.app.billing.verify(2,'purchase-token-one')
            provider.return_value=self.receipt('SUBSCRIPTION_STATE_CANCELED'); self.app.billing.verify(1,'purchase-token-one')
            self.assertEqual(self.plans.snapshot(1)['tier'],'premium')
            provider.return_value=self.receipt('SUBSCRIPTION_STATE_EXPIRED'); self.app.billing.verify(1,'purchase-token-one')
            self.assertEqual(self.plans.snapshot(1)['tier'],'free')

    def test_pending_purchase_and_wrong_account_never_grant_access(self):
        with patch.dict(os.environ,GOOGLE_PLAY_PRODUCTS='premium'),patch.object(self.app.billing,'google',return_value=self.receipt('SUBSCRIPTION_STATE_PENDING')) as provider:
            self.app.billing.verify(1,'pending-token-one'); self.assertEqual(self.plans.snapshot(1)['tier'],'free')
            receipt=self.receipt();receipt['externalAccountIdentifiers']['obfuscatedExternalAccountId']='wrong-account';provider.return_value=receipt
            with self.assertRaises(AgentError): self.app.billing.verify(1,'wrong-token-one')
            self.assertEqual(self.plans.snapshot(1)['tier'],'free')

    def test_pending_replacement_preserves_paid_access_and_old_notifications_cannot_revive_it(self):
        with patch.dict(os.environ,GOOGLE_PLAY_PRODUCTS='premium'),patch.object(self.app.billing,'google',return_value=self.receipt()) as provider:
            self.app.billing.verify(1,'original-purchase-token')
            replacement=self.receipt('SUBSCRIPTION_STATE_PENDING')
            replacement['linkedPurchaseToken']='original-purchase-token'
            provider.return_value=replacement
            self.app.billing.verify(1,'replacement-purchase-token')
            self.assertEqual(self.plans.snapshot(1)['tier'],'premium')
            replacement['subscriptionState']='SUBSCRIPTION_STATE_ACTIVE'
            self.app.billing.verify(1,'replacement-purchase-token')
            provider.return_value=self.receipt('SUBSCRIPTION_STATE_EXPIRED')
            self.app.billing.verify(1,'replacement-purchase-token')
            provider.return_value=self.receipt()
            calls=provider.call_count
            self.app.billing.verify(1,'original-purchase-token')
            self.assertEqual(provider.call_count,calls)
            self.assertEqual(self.plans.snapshot(1)['tier'],'free')

    def test_admin_needs_owner_role_totp_origin_and_separate_csrf(self):
        self.f.login(); self.assertEqual(self.client.get('/api/admin/v1/users').status_code,401)
        headers=self.admin_login()
        self.assertEqual(self.client.get('/api/admin/v1/users').status_code,200)
        self.assertEqual(self.client.post('/api/admin/v1/users/2/courtesy',headers={'Origin':'http://localhost'},json={'expires_at':int(time.time())+3600,'reason':'Prueba válida'}).status_code,403)
        repeated=self.client.post('/api/admin/v1/login',headers={'Origin':'http://localhost'},json=dict(email='owner@example.invalid',password='Password1!',code=self.code))
        self.assertEqual(repeated.status_code,401)
        result=self.client.post('/api/admin/v1/users/2/courtesy',headers=headers,json=dict(expires_at=int(time.time())+3600,reason='Cortesía de prueba'))
        self.assertEqual(result.status_code,200)
        self.assertEqual(self.plans.snapshot(2)['source'],'courtesy')
        events=self.client.get('/api/admin/v1/audit').json['events']
        self.assertEqual(events[0]['action'],'courtesy_granted')
        self.assertNotIn('secret',json.dumps(self.client.get('/api/admin/v1/users/2').json))

    def test_admin_suspension_invalidates_existing_consumer_sessions(self):
        headers=self.admin_login(user_id=1)
        other=self.app.app.test_client()
        with other.session_transaction() as session: session['user_id']=2; session['plan_epoch']=0
        self.assertEqual(other.get('/api/mobile/v1/devices').status_code,200)
        response=self.client.post('/api/admin/v1/users/2/status',headers=headers,json=dict(suspended=True,reason='Suspensión de prueba'))
        self.assertEqual(response.status_code,200)
        self.assertEqual(other.get('/api/mobile/v1/devices').status_code,401)
        with self.assertRaises(AgentError): self.plans.require(2)

    def test_totp_matches_rfc6238_sha1_vector(self):
        secret=base64.b32encode(b'12345678901234567890').decode()
        self.assertEqual(totp(secret,59//30),'287082')

    def test_admin_ad_limits_and_promotion_are_audited_and_enabling_is_guarded(self):
        headers=self.admin_login()
        config={**DEFAULT_ADS,'allowed_views':['home','plan']}
        invalid={**config,'daily_limit':4}
        self.assertEqual(self.client.post('/api/admin/v1/ads',headers=headers,json=dict(ads=invalid,reason='Límite inválido de prueba')).status_code,400)
        with patch.dict(os.environ,ADS_LIVE_READY='0'):
            enabled={**config,'enabled':True}
            self.assertEqual(self.client.post('/api/admin/v1/ads',headers=headers,json=dict(ads=enabled,reason='Intento de activar sin proveedor')).status_code,409)
        self.assertEqual(self.client.post('/api/admin/v1/ads',headers=headers,json=dict(ads=config,reason='Pantallas autorizadas de prueba')).status_code,200)
        self.assertEqual(self.plans.public(1)['ads']['allowed_views'],['home','plan'])
        promo=dict(enabled=False,starts_at=0,ends_at=0)
        result=self.client.post('/api/admin/v1/promotion',headers=headers,json=dict(promotion=promo,reason='Desactivar promoción de prueba'))
        self.assertEqual(result.status_code,200)
        self.assertFalse(self.plans.public(1)['billing']['intro_eligible'])
        events=self.client.get('/api/admin/v1/audit').json['events']
        self.assertEqual(events[0]['action'],'promotion_updated')

    def test_deletion_request_is_confirmed_idempotent_and_queued_for_support(self):
        headers=self.headers()
        self.assertEqual(self.client.post('/account-deletion/request',data={'csrf_token':self.f.csrf()}).status_code,400)
        data=dict(csrf_token=self.f.csrf(),confirmed='yes')
        self.assertEqual(self.client.post('/account-deletion/request',data=data).status_code,302)
        self.client.post('/account-deletion/request',data=data)
        with self.plans.state() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM deletion_requests').fetchone()[0],1)
            request_id=db.execute('SELECT id FROM deletion_requests').fetchone()[0]
        admin_headers=self.admin_login()
        response=self.client.post('/api/admin/v1/deletions/'+request_id+'/status',headers=admin_headers,json=dict(status='processing',reason='Identidad verificada en prueba'))
        self.assertEqual(response.status_code,200)
        self.client.post('/account-deletion/request',data=data)
        with self.plans.state() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM deletion_requests').fetchone()[0],1)
        self.assertTrue(self.app.database.fetch_one('SELECT id FROM users WHERE id=%s',(1,)))
