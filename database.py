"""MariaDB para cuentas, dispositivos y auditoría; sin estado de Flask/Alexa."""
import os
import re
from contextlib import contextmanager
from pathlib import Path
import pymysql
from pymysql.constants import CLIENT
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / '.env')


def connection_settings():
    name = os.environ.get('DB_NAME', 'wol_panel')
    user = os.environ.get('DB_USER', 'wol_user')
    if not re.fullmatch(r'[A-Za-z0-9_]{1,64}', name):
        raise ValueError('DB_NAME debe ser un identificador válido.')
    if name.lower() in ('spamkill', 'colesterol_game_db', 'mysql', 'sys', 'information_schema', 'performance_schema'):
        raise ValueError('DB_NAME no puede apuntar a una base ajena al proyecto.')
    if user.lower() == 'root':
        raise ValueError('La aplicación requiere un usuario MariaDB sin privilegios de root.')
    try:
        port = int(os.environ.get('DB_PORT', '3306'))
    except ValueError:
        raise ValueError('DB_PORT debe ser un puerto válido.') from None
    if not 1 <= port <= 65535:
        raise ValueError('DB_PORT debe estar entre 1 y 65535.')
    return dict(host=os.environ.get('DB_HOST', '127.0.0.1'), port=port,
                database=name, user=user, password=os.environ.get('DB_PASSWORD', ''),
                charset='utf8mb4', autocommit=False, connect_timeout=5,
                read_timeout=10, write_timeout=10, client_flag=CLIENT.FOUND_ROWS,
                init_command="SET time_zone = '+00:00'")


def get_db_connection():
    return pymysql.connect(**connection_settings())


@contextmanager
def connection():
    """Confirma al terminar, revierte al fallar y siempre cierra la conexión."""
    conn = get_db_connection()
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def fetch_one(sql, params=()):
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchone()


def fetch_all(sql, params=()):
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


def execute(sql, params=()):
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.rowcount
