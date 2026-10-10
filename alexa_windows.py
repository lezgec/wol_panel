"""Modelo Custom de la misma skill WoL Pro: acciones de la cuenta OAuth."""
import hashlib
import hmac
import os
import secrets
import time
from datetime import datetime
from flask import request, jsonify
from windows_agent import AgentError, text


def speech(message, task=False, success=True, link=False):
    response = dict(outputSpeech=dict(type='PlainText', text=message), shouldEndSession=True)
    if task:
        response['directives'] = [dict(type='Tasks.CompleteTask', status=dict(code='200' if success else '500', message=message), result={})]
    elif link:
        response['card'] = dict(type='LinkAccount')
    return jsonify(version='1.0', response=response)


def register_custom(bp, service, state_connection, rate_allowed, audit):
    @bp.post('/alexa/custom')
    def alexa_custom():
        secret = os.environ.get('ALEXA_BRIDGE_SECRET', '')
        skill_id = os.environ.get('ALEXA_SKILL_ID') or os.environ.get('ALEXA_CUSTOM_SKILL_ID', '')
        if len(secret) < 32 or not skill_id:
            return jsonify(error='skill_not_configured'), 503
        stamp = request.headers.get('X-Wol-Timestamp', '')
        try:
            recent = abs(time.time()-int(stamp)) <= 300
        except ValueError:
            recent = False
        expected = hmac.new(secret.encode(), stamp.encode()+b'.'+request.get_data(), hashlib.sha256).hexdigest()
        if not recent or not secrets.compare_digest(expected, request.headers.get('X-Wol-Signature', '')):
            return jsonify(error='unauthorized'), 401
        envelope = request.get_json(silent=True)
        try:
            system = envelope['context']['System']
            req = envelope['request']
            if system['application']['applicationId'] != skill_id or not isinstance(req, dict):
                raise ValueError()
            when = datetime.fromisoformat(req['timestamp'].replace('Z', '+00:00')).timestamp()
            if abs(time.time()-when) > 300:
                raise ValueError()
        except (KeyError, TypeError, ValueError, AttributeError):
            return jsonify(error='invalid_request'), 400
        task = req.get('task')
        if task and (not isinstance(task, dict) or task.get('name') != skill_id+'.ExecuteAction' or str(task.get('version')) != '1'):
            return speech('Esta tarea no está disponible.', True, False)
        token = system.get('user', {}).get('accessToken') if isinstance(system.get('user'), dict) else None
        with state_connection() as db:
            owner = db.execute('SELECT user_id FROM auth_tokens WHERE access_token=? AND expires>?', (token, time.time())).fetchone() if isinstance(token, str) else None
        if not owner:
            return speech('Vincula tu cuenta de WoL Pro desde la aplicación Alexa.', bool(task), False, True)
        if req.get('type') == 'SessionEndedRequest':
            return jsonify(version='1.0', response={})
        action_name = None
        if req.get('type') == 'LaunchRequest' and task:
            inputs = task.get('input', {})
            action_name = inputs.get('action') if isinstance(inputs, dict) else None
        elif req.get('type') == 'IntentRequest':
            intent = req.get('intent', {})
            if not isinstance(intent, dict):
                return speech('Petición inválida.', success=False)
            if intent.get('name') in ('AMAZON.StopIntent', 'AMAZON.CancelIntent'):
                return speech('De acuerdo.')
            if intent.get('name') == 'ExecuteActionIntent':
                try:
                    action_name = intent['slots']['action']['value']
                except (KeyError, TypeError):
                    pass
        if not action_name:
            return speech('Crea una acción en el panel y di: ejecuta Spotify en mi PC.', bool(task), not bool(task))
        try:
            name = text(action_name)
            user_id = owner['user_id']
            if not rate_allowed('windows_run', str(user_id), 12, 60):
                raise AgentError('rate_limited', 'Espera antes de enviar más órdenes.', 429)
            action = service.first('SELECT id FROM agent_actions WHERE user_id=%s AND LOWER(name)=LOWER(%s)', (user_id, name))
            if not action:
                raise AgentError('not_found', 'No encuentro esa acción en tu cuenta.')
            request_id = text(req.get('requestId'), 256)
            command_id = service.execute_action(user_id, action['id'], 'custom:'+request_id)
            audit(user_id, 'ALEXA_WINDOWS', 'Orden Windows '+command_id)
            return speech('Orden enviada al agente de Windows.', bool(task))
        except AgentError as exc:
            return speech(exc.message, bool(task), False)
