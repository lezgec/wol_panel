"""Configuración explícita para un servidor público detrás de HTTPS."""
import os
from urllib.parse import urlsplit
from werkzeug.middleware.proxy_fix import ProxyFix


def configure(app):
    production = os.environ.get('APP_ENV') == 'production'
    if production:
        required = ('FLASK_SECRET_KEY', 'DB_CONNECTION_STRING', 'PUBLIC_BASE_URL',
                    'ALEXA_BRIDGE_SECRET', 'SMTP_USER', 'SMTP_PASSWORD')
        missing = [name for name in required if not os.environ.get(name)]
        if missing:
            raise RuntimeError('Faltan variables de producción: ' + ', '.join(missing))
        if any(len(os.environ[name]) < 32 for name in ('FLASK_SECRET_KEY', 'ALEXA_BRIDGE_SECRET')):
            raise RuntimeError('Las claves de sesión y puente deben tener al menos 32 caracteres.')
        base = urlsplit(os.environ['PUBLIC_BASE_URL'])
        if base.scheme != 'https' or not base.hostname or base.path not in ('', '/') or base.query or base.fragment or base.username:
            raise RuntimeError('PUBLIC_BASE_URL debe ser el origen HTTPS del panel.')
        if os.environ.get('COOKIE_SECURE', '1') != '1':
            raise RuntimeError('Producción requiere COOKIE_SECURE=1.')
        if os.environ.get('ALLOW_LOCAL_WOL', '0') != '0':
            raise RuntimeError('Desactiva ALLOW_LOCAL_WOL para el servidor público.')
        app.config['TRUSTED_HOSTS'] = [base.hostname]
    app.config['SESSION_COOKIE_SECURE'] = os.environ.get('COOKIE_SECURE', '1' if production else '0') == '1'
    app.config['ALLOW_LOCAL_WOL'] = os.environ.get('ALLOW_LOCAL_WOL', '0' if production else '1') == '1'
    app.config['MAX_CONTENT_LENGTH'] = 64 * 1024
    # Activar solamente si el backend es inaccesible directamente desde Internet.
    proxies = int(os.environ.get('TRUST_PROXY_COUNT', '0'))
    if proxies not in (0, 1):
        raise RuntimeError('TRUST_PROXY_COUNT debe ser 0 o 1.')
    if proxies:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=proxies, x_proto=proxies)
