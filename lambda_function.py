"""Puente para una skill Alexa Smart Home con endpoint AWS Lambda.

Configura WOL_BACKEND_URL=https://tu-dominio/alexa/smarthome y
ALEXA_BRIDGE_SECRET con la misma clave privada que el backend.
No requiere paquetes adicionales. El token de la directiva llega intacto al backend.
"""
import json
import os
import urllib.request
import urllib.error
import uuid
import hashlib
import hmac
import time


def lambda_handler(event, context):
    url = os.environ.get('WOL_BACKEND_URL', '')
    if not url.startswith('https://'):
        raise RuntimeError('Configura WOL_BACKEND_URL con la URL HTTPS del backend.')
    secret = os.environ.get('ALEXA_BRIDGE_SECRET', '')
    if len(secret) < 32:
        raise RuntimeError('Configura ALEXA_BRIDGE_SECRET con una clave de al menos 32 caracteres.')
    body = json.dumps(event).encode('utf-8')
    timestamp = str(int(time.time()))
    signature = hmac.new(secret.encode(), timestamp.encode() + b'.' + body, hashlib.sha256).hexdigest()
    request = urllib.request.Request(url, data=body,
        headers={'Content-Type': 'application/json', 'X-Wol-Timestamp': timestamp,
                 'X-Wol-Signature': signature}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=6) as response:
            return json.load(response)
    except (urllib.error.URLError, TimeoutError, ValueError):
        directive = event.get('directive', {})
        header = {'namespace': 'Alexa', 'name': 'ErrorResponse',
                  'payloadVersion': '3', 'messageId': str(uuid.uuid4())}
        if directive.get('header', {}).get('correlationToken'):
            header['correlationToken'] = directive['header']['correlationToken']
        response = {'event': {'header': header, 'payload': {
            'type': 'INTERNAL_ERROR', 'message': 'El servidor de encendido no está disponible.'}}}
        if directive.get('endpoint', {}).get('endpointId'):
            response['event']['endpoint'] = {'endpointId': directive['endpoint']['endpointId']}
        return response
