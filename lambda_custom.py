"""Puente del modelo Custom; lo invoca la Lambda única lambda_function."""
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise urllib.error.URLError('Redirect refused')


def lambda_handler(event, context):
    base = urlsplit(os.environ.get('WOL_BACKEND_URL', ''))
    if base.path != '/alexa/smarthome':
        raise RuntimeError('Configura WOL_BACKEND_URL con el endpoint HTTPS /alexa/smarthome.')
    url = urlunsplit((base.scheme, base.netloc, '/alexa/custom', base.query, base.fragment))
    parsed = urlsplit(url)
    secret = os.environ.get('ALEXA_BRIDGE_SECRET', '')
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.query or parsed.fragment or parsed.path != '/alexa/custom' or len(secret) < 32:
        raise RuntimeError('Configura el endpoint HTTPS de WoL Pro y ALEXA_BRIDGE_SECRET.')
    body = json.dumps(event).encode()
    stamp = str(int(time.time()))
    signature = hmac.new(secret.encode(), stamp.encode()+b'.'+body, hashlib.sha256).hexdigest()
    req = urllib.request.Request(url, data=body, headers={'Content-Type':'application/json','User-Agent':'WoLPro-Alexa-Bridge/1.0','X-Wol-Timestamp':stamp,'X-Wol-Signature':signature}, method='POST')
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=6) as response:
            return json.load(response)
    except (urllib.error.URLError, TimeoutError, ValueError):
        response = {'outputSpeech': {'type':'PlainText', 'text':'No se pudo enviar la orden al servidor.'}, 'shouldEndSession':True}
        if isinstance(event.get('request'), dict) and event['request'].get('task'):
            response['directives'] = [{'type':'Tasks.CompleteTask','status':{'code':'500','message':'Servidor no disponible'},'result':{}}]
        return {'version':'1.0', 'response':response}
