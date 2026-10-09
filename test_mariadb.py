"""Integración opt-in con MariaDB real y exclusivamente una base wol_test_* aislada."""
import os
import unittest
import pymysql
import database
import migrate_db
import test_app as base


class FixtureConnection:
    """Solo para sembrar/comprobar fixtures; traduce el SQL SQLite de los tests."""
    def __init__(self, connection):
        self.connection = connection
        self.cursors = []

    def execute(self, sql, params=()):
        cursor = self.connection.cursor()
        self.cursors.append(cursor)
        cursor.execute(sql.replace('?', '%s'), params)
        return cursor

    def __enter__(self):
        return self

    def __exit__(self, error_type, *args):
        try:
            self.connection.rollback() if error_type else self.connection.commit()
        finally:
            for cursor in self.cursors:
                cursor.close()
            self.connection.close()


@unittest.skipUnless(os.environ.get('WOL_TEST_MARIADB') == '1', 'MariaDB aislada no habilitada; consulta TESTING.md.')
class MariaDBApplicationTests(base.ApplicationTests):
    @classmethod
    def setUpClass(cls):
        # Validar ANTES de cualquier DDL o de parchear la configuración.
        settings = database.connection_settings()
        if not settings['database'].startswith('wol_test_') or settings['host'] not in ('127.0.0.1', 'localhost', '::1'):
            raise RuntimeError('Las pruebas solo admiten una base wol_test_* en loopback.')
        cls.real_connect = staticmethod(database.get_db_connection)
        super().setUpClass()
        migrate_db.migrate()

    def business_connection(self):
        return FixtureConnection(self.real_connect())

    def application_connection(self):
        return self.real_connect()

    def reset_business(self):
        with self.business_connection() as db:
            for table in ('audit_logs', 'devices', 'users'):
                db.execute('DELETE FROM ' + table)

    def test_schema_engine_charset_constraints_and_repeated_migration(self):
        self.login()
        before = database.fetch_all('SELECT id,name,mac,user_sub FROM devices ORDER BY id')
        migrate_db.migrate()
        migrate_db.migrate()
        self.assertEqual(database.fetch_all('SELECT id,name,mac,user_sub FROM devices ORDER BY id'), before)
        tables = database.fetch_all('SELECT TABLE_NAME,ENGINE,TABLE_COLLATION FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s', (os.environ['DB_NAME'],))
        self.assertEqual(len(tables), 3)
        for _, engine, collation in tables:
            self.assertEqual(engine, 'InnoDB')
            self.assertTrue(collation.startswith('utf8mb4'))
        with self.assertRaises(pymysql.IntegrityError):
            database.execute('INSERT INTO users (email,password) VALUES (%s,%s)', ('owner@example.invalid', 'duplicate'))
        with self.assertRaises(pymysql.IntegrityError):
            database.execute('INSERT INTO devices (name,mac,user_sub) VALUES (%s,%s,%s)', ('orphan', 'AA:BB:CC:DD:EE:09', 999999))

    def test_emoji_and_sql_values_are_preserved(self):
        self.login()
        name = "PC 🖥️ ' OR 1=1"
        self.client.post('/add', data={'name': name, 'mac': 'AA:BB:CC:DD:EE:09', 'wake_method': 'alexa', 'csrf_token': self.csrf()})
        self.assertEqual(database.fetch_one('SELECT name FROM devices WHERE name=%s', (name,))[0], name)
