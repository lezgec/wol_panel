"""AdMob ECDSA verification with Google/Tink URI query decoding."""
import base64
import logging
import os
import re
import time
from urllib.parse import parse_qs, unquote_to_bytes
import requests
from flask import Blueprint, request, jsonify
from windows_agent import AgentError

# Reserved custom_data for AdMob's console URL verification. This is only a
# diagnostic: signature and freshness checks still run; no account changes.
CONSOLE_CHECK = 'wolpro-ssv-console-check'
# Observed in AdMob's console verification callback; never a reward source.
CONSOLE_TEST_UNIT = '1234567890'
logger = logging.getLogger(__name__)


class AdMobVerifier:
    def __init__(self):
        self.keys={}; self.updated=0

    def verify(self, raw):
        from cryptography.hazmat.primitives import serialization, hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        unit=os.environ.get('ADMOB_REWARDED_UNIT')
        if not unit: raise AgentError('ads_disabled','Recompensas todavía no configuradas.',409)
        stage='configuration'; received_unit='absent'; age='unknown'
        key_label='unknown'; key_http='unused'; console_check=False
        signature_escaped=False; content_escaped=False
        try:
            # Google sends only the numeric suffix in ad_unit, while the console
            # and mobile SDK use ca-app-pub-PUBLISHER/UNIT.
            configured=re.fullmatch(r'(?:ca-app-pub-\d{16}/)?(\d+)',unit)
            if not configured: raise ValueError()
            stage='query_structure'
            if len(raw)>8192 or raw.count(b'&signature=')!=1: raise ValueError()
            content,tail=raw.split(b'&signature=',1)
            content_escaped=b'%' in content
            parts=tail.split(b'&key_id=')
            if len(parts)!=2 or b'&' in parts[1]: raise ValueError()
            key_id=int(parts[1]); signature=parts[0].decode('ascii')
            key_label=key_id if 0 <= key_id < 2**64 else 'unexpected'
            signature_escaped='%' in signature
            stage='parameters'
            fields=parse_qs(content.decode('ascii'),strict_parsing=True)
            if any(len(v)!=1 for v in fields.values()): raise ValueError()
            candidate=fields.get('ad_unit',[''])[0]
            # Log only a public ad-unit identifier, never arbitrary query values.
            received_unit=candidate if re.fullmatch(r'(?:ca-app-pub-\d{16}/)?\d{1,24}',candidate) else 'unexpected'
            console_check=fields.get('custom_data') == [CONSOLE_CHECK]
            stage='ad_unit'
            console_test=console_check and candidate == CONSOLE_TEST_UNIT
            if candidate!=configured.group(1) and not console_test: raise ValueError()
            stage='timestamp'
            age=time.time()-int(fields['timestamp'][0])/1000
            if abs(age)>600: raise ValueError()
            if time.time()-self.updated>21600:
                stage='keys_download'
                response=requests.get('https://www.gstatic.com/admob/reward/verifier-keys.json',timeout=10,allow_redirects=False)
                key_http=response.status_code
                response.raise_for_status()
                stage='keys_parse'
                self.keys={int(k['keyId']):serialization.load_pem_public_key(k['pem'].encode()) for k in response.json()['keys']}
                self.updated=time.time()
            stage='key_id'
            key=self.keys.get(key_id)
            if not key: raise ValueError()
            stage='signature_content'
            # Google/Tink uses URI.getQuery(): decode percent escapes once,
            # keeping order and literal '+' (this is not form-urlencoded).
            # Reject malformed escapes and encoded field delimiters so signed
            # content and our parsed reward fields cannot disagree on structure.
            if re.search(rb'%(?![0-9a-fA-F]{2})',content): raise ValueError()
            signed_content=unquote_to_bytes(content)
            signed_content.decode('utf-8',errors='strict')
            if signed_content.count(b'&')!=content.count(b'&'): raise ValueError()
            stage='signature_encoding'
            if re.search(r'%(?![0-9a-fA-F]{2})',signature): raise ValueError()
            signature=unquote_to_bytes(signature).decode('ascii')
            decoded=base64.b64decode(signature+'='*(-len(signature)%4),altchars=b'-_',validate=True)
            stage='signature'
            key.verify(decoded,signed_content,ec.ECDSA(hashes.SHA256()))
            stage='reward_data'
            return fields['custom_data'][0],fields['transaction_id'][0]
        except AgentError: raise
        except Exception as error:
            logger.warning(
                'AdMob SSV rejected stage=%s unit=%s age_s=%s key_id=%s key_http=%s console_check=%s signature_escaped=%s content_escaped=%s error=%s',
                stage,received_unit,round(age,1) if isinstance(age,(int,float)) else age,
                key_label,key_http,console_check,signature_escaped,content_escaped,type(error).__name__)
            raise AgentError('invalid_signature','Recompensa no verificada.',403) from None


def install(app,plans):
    verifier=AdMobVerifier(); bp=Blueprint('ads_verification',__name__)

    @bp.get('/api/ads/ssv')
    def reward():
        try:
            ticket,transaction=verifier.verify(request.query_string)
            if ticket == CONSOLE_CHECK:
                return jsonify(status='verified', diagnostic=True, reward_granted=False)
            plans.verified_reward(ticket,transaction)
            return jsonify(status='verified')
        except AgentError as error:
            return jsonify(error=error.code,message=error.message),error.status

    app.register_blueprint(bp)
    return verifier
