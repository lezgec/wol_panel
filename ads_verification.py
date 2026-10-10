"""AdMob ECDSA verification over the unmodified raw query string."""
import base64
import os
import time
from urllib.parse import parse_qs
import requests
from flask import Blueprint, request, jsonify
from windows_agent import AgentError


class AdMobVerifier:
    def __init__(self):
        self.keys={}; self.updated=0

    def verify(self, raw):
        from cryptography.hazmat.primitives import serialization, hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        unit=os.environ.get('ADMOB_REWARDED_UNIT')
        if not unit: raise AgentError('ads_disabled','Recompensas todavía no configuradas.',409)
        try:
            if len(raw)>8192 or raw.count(b'&signature=')!=1: raise ValueError()
            content,tail=raw.split(b'&signature=',1)
            parts=tail.split(b'&key_id=')
            if len(parts)!=2 or b'&' in parts[1]: raise ValueError()
            key_id=int(parts[1]); signature=parts[0].decode('ascii')
            fields=parse_qs(content.decode('ascii'),strict_parsing=True)
            if any(len(v)!=1 for v in fields.values()): raise ValueError()
            if fields['ad_unit'][0]!=unit: raise ValueError()
            if abs(int(fields['timestamp'][0])/1000-time.time())>600: raise ValueError()
            if time.time()-self.updated>21600:
                response=requests.get('https://www.gstatic.com/admob/reward/verifier-keys.json',timeout=10,allow_redirects=False)
                response.raise_for_status()
                self.keys={int(k['keyId']):serialization.load_pem_public_key(k['pem'].encode()) for k in response.json()['keys']}
                self.updated=time.time()
            key=self.keys.get(key_id)
            if not key: raise ValueError()
            decoded=base64.urlsafe_b64decode(signature+'='*(-len(signature)%4))
            key.verify(decoded,content,ec.ECDSA(hashes.SHA256()))
            return fields['custom_data'][0],fields['transaction_id'][0]
        except AgentError: raise
        except Exception:
            raise AgentError('invalid_signature','Recompensa no verificada.',403) from None


def install(app,plans):
    verifier=AdMobVerifier(); bp=Blueprint('ads_verification',__name__)

    @bp.get('/api/ads/ssv')
    def reward():
        try:
            ticket,transaction=verifier.verify(request.query_string)
            plans.verified_reward(ticket,transaction)
            return jsonify(status='verified')
        except AgentError as error:
            return jsonify(error=error.code,message=error.message),error.status

    app.register_blueprint(bp)
    return verifier
