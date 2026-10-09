"""Inicializa MariaDB sin importar Flask, crear SQLite ni arrancar el worker."""
from pathlib import Path
from database import connection, connection_settings

SCHEMA_PATH = Path(__file__).parent / 'database' / 'wol_panel_mariadb.sql'


def migrate():
    name = connection_settings()['database']
    if name != 'wol_panel' and not name.startswith('wol_test_'):
        raise ValueError('La migración solo admite wol_panel o una base aislada wol_test_*.')
    # El archivo solo contiene DDL estático; no se interpolan valores de usuario.
    source = '\n'.join(line for line in SCHEMA_PATH.read_text(encoding='utf-8').splitlines()
                       if not line.lstrip().startswith('--'))
    with connection() as conn, conn.cursor() as cursor:
        for statement in source.split(';'):
            if statement.strip():
                cursor.execute(statement)
    # CREATE TABLE hace commit implícito; IF NOT EXISTS permite reintentar.
    print('Esquema MariaDB inicializado; los registros existentes se conservan.')


if __name__ == '__main__':
    try:
        migrate()
    except Exception:
        raise SystemExit('No se pudo inicializar MariaDB. Revisa DB_* y permisos; no se muestran credenciales.') from None
