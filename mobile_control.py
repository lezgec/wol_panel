"""Mobile views of the existing Windows queue; session/CSRF guarded by Flask."""
import time
import uuid
from flask import Blueprint, jsonify, request, session
from windows_agent import AgentError, text


def install(app, service, database, rate_allowed, audit):
    bp = Blueprint('mobile_control', __name__, url_prefix='/api/mobile/v1/control')

    @bp.before_request
    def guard():
        if not app.config['ENABLE_WINDOWS_AGENT']:
            return jsonify(error='disabled', message='Control de PC no habilitado.'), 404
        if request.method != 'GET' and not rate_allowed('windows_mobile', str(session['user_id']), 30, 60):
            return jsonify(error='rate_limited', message='Espera antes de enviar más solicitudes.'), 429

    @bp.errorhandler(AgentError)
    def error(exc):
        return jsonify(error=exc.code, message=exc.message), exc.status

    def body():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise AgentError('invalid_json', 'Petición inválida.')
        return data

    def linked(device_id):
        pc = service.first('SELECT * FROM agent_connections WHERE device_id=%s AND user_id=%s AND revoked=0 AND expires>%s',
                           (device_id, session['user_id'], int(time.time())))
        if not pc:
            raise AgentError('not_found', 'Selecciona un PC vinculado.', 404)
        return pc

    @bp.get('')
    def overview():
        pcs = []
        for pc in service.dashboard_data(session['user_id']).values():
            # Never expose hashes, receipts, Alexa tokens or backend-only identifiers.
            item = {key: pc[key] for key in ('id', 'device_id', 'name', 'active', 'online', 'pc_online', 'state', 'last_seen')}
            item['allow_shutdown'] = bool(pc['allow_shutdown']) and pc['active']
            item['apps'] = [{key: entry[key] for key in ('app_key', 'name')} for entry in pc['apps']] if pc['active'] else []
            item['actions'] = [{key: entry[key] for key in ('id', 'name', 'kind', 'app_key')} for entry in pc['actions']] if pc['active'] else []
            item['commands'] = []
            for command in pc['commands']:
                public = {key: command[key] for key in ('id', 'kind', 'app_key', 'created', 'expires', 'status', 'result')}
                public['cancel_requested'] = bool(command['cancel_requested'])
                public['can_cancel'] = pc['active'] and not public['cancel_requested'] and (
                    command['status'] == 'pending' or command['kind'] == 'shutdown' and command['status'] in ('claimed', 'scheduled'))
                item['commands'].append(public)
            pcs.append(item)
        return jsonify(version=1, pcs=pcs, server_time=int(time.time()))

    @bp.post('/devices/<int:device_id>/run')
    def run(device_id):
        data = body()
        pc = linked(device_id)
        try:
            request_id = str(uuid.UUID(data.get('request_id', '')))
        except (ValueError, TypeError, AttributeError):
            raise AgentError('invalid_request_id', 'Identificador de solicitud inválido.') from None
        if not rate_allowed('windows_run', str(session['user_id']), 12, 60):
            raise AgentError('rate_limited', 'Espera antes de enviar más órdenes.', 429)
        # The Windows agent publishes only permitted IDs; no scripts or paths accepted.
        kind, key = data.get('kind'), data.get('app_key')
        if kind == 'launch':
            key = text(key, 100)
        elif kind == 'shutdown':
            key = None
        else:
            raise AgentError('invalid_action', 'Selecciona una acción autorizada.')
        command_id = service.enqueue(session['user_id'], pc['id'], kind, key,
                                     'mobile:'+str(device_id)+':'+str(kind)+':'+str(key)+':'+request_id)
        audit(session['user_id'], 'AGENT_COMMAND', 'Orden Windows desde app '+command_id)
        return jsonify(command_id=command_id, message='Orden enviada. Consulta el resultado en el historial.'), 202

    @bp.post('/commands/<command_id>/cancel')
    def cancel(command_id):
        with database.connection() as conn, conn.cursor() as c:
            rows = service.rows(c, 'SELECT status,kind FROM agent_commands WHERE id=%s AND user_id=%s FOR UPDATE', (command_id, session['user_id']))
            if not rows:
                raise AgentError('not_found', 'Orden no encontrada.', 404)
            row = rows[0]
            if row['status'] != 'pending' and not (row['kind'] == 'shutdown' and row['status'] in ('claimed', 'scheduled')):
                raise AgentError('already_started', 'Esta orden ya no puede cancelarse.', 409)
            c.execute('UPDATE agent_commands SET cancel_requested=1 WHERE id=%s', (command_id,))
            c.execute('UPDATE agent_commands SET status=%s,result=%s WHERE id=%s AND status=%s', ('cancelled', 'cancelled', command_id, 'pending'))
        return jsonify(message='Cancelación solicitada. Una acción ya ejecutada no puede deshacerse.')

    @bp.post('/pair/preview')
    def preview():
        if not rate_allowed('windows_authorize', str(session['user_id']), 10, 300):
            raise AgentError('rate_limited', 'Espera antes de vincular más equipos.', 429)
        pair = service.pairing(body().get('code'))
        return jsonify(computer_name=pair['computer_name'], expires_at=pair['expires'])

    @bp.post('/devices/<int:device_id>/pair')
    def pair(device_id):
        if not rate_allowed('windows_authorize', str(session['user_id']), 10, 300):
            raise AgentError('rate_limited', 'Espera antes de vincular más equipos.', 429)
        service.authorize(body().get('code'), session['user_id'], device_id)
        audit(session['user_id'], 'AGENT_LINK', 'PC autorizado desde app mediante código temporal')
        return jsonify(message='Vinculación autorizada. Espera la confirmación en Windows.')

    @bp.delete('/devices/<int:device_id>/agent')
    def revoke(device_id):
        pc = linked(device_id)
        database.execute('UPDATE agent_connections SET revoked=1,allow_shutdown=0 WHERE id=%s AND user_id=%s', (pc['id'], session['user_id']))
        database.execute('UPDATE agent_commands SET cancel_requested=1 WHERE agent_id=%s AND status IN (%s,%s,%s)', (pc['id'], 'pending', 'claimed', 'scheduled'))
        audit(session['user_id'], 'AGENT_REVOKE', 'Acceso de PC revocado desde app')
        return jsonify(message='PC desvinculado.')

    @bp.post('/devices/<int:device_id>/actions')
    def create_action(device_id):
        pc, data = linked(device_id), body()
        name, kind = text(data.get('name')), data.get('kind')
        key = data.get('app_key') if kind == 'launch' else None
        if service.plans:
            service.plans.require(session['user_id'], device_id, kind)
        if kind == 'launch':
            key = text(key)
            if not service.first('SELECT app_key FROM agent_apps WHERE agent_id=%s AND app_key=%s', (pc['id'], key)):
                raise AgentError('not_allowed', 'Selecciona una aplicación o un comando permitido.')
        elif kind != 'shutdown' or not pc['allow_shutdown']:
            raise AgentError('not_allowed', 'Autoriza el apagado en Windows primero.')
        if service.first('SELECT id FROM agent_actions WHERE user_id=%s AND name=%s', (session['user_id'], name)):
            raise AgentError('duplicate_name', 'Ya existe una acción con ese nombre.')
        action_id = str(uuid.uuid4())
        database.execute('INSERT INTO agent_actions (id,user_id,agent_id,name,kind,app_key) VALUES (%s,%s,%s,%s,%s,%s)',
                         (action_id, session['user_id'], pc['id'], name, kind, key))
        return jsonify(action_id=action_id, message='Acción guardada. También estará disponible en el panel y Alexa.'), 201

    @bp.delete('/actions/<action_id>')
    def delete_action(action_id):
        if not database.execute('DELETE FROM agent_actions WHERE id=%s AND user_id=%s', (action_id, session['user_id'])):
            raise AgentError('not_found', 'Acción no encontrada.', 404)
        return jsonify(message='Acción eliminada.')

    app.register_blueprint(bp)
