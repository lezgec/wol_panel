"""Integración opt-in con MariaDB real y exclusivamente una base wol_test_* aislada."""
import os
import unittest
import pymysql
import database
import migrate_db
import test_app as base
import test_windows_agent as agents


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
            for table in ('agent_presence', 'agent_commands', 'agent_actions', 'agent_apps', 'agent_connections', 'agent_pairings', 'audit_logs', 'devices', 'users'):
                db.execute('DELETE FROM ' + table)
            db.execute('ALTER TABLE devices AUTO_INCREMENT=1')

    def test_schema_engine_charset_constraints_and_repeated_migration(self):
        self.login()
        before = database.fetch_all('SELECT id,name,mac,user_sub FROM devices ORDER BY id')
        migrate_db.migrate()
        migrate_db.migrate()
        self.assertEqual(database.fetch_all('SELECT id,name,mac,user_sub FROM devices ORDER BY id'), before)
        tables = database.fetch_all('SELECT TABLE_NAME,ENGINE,TABLE_COLLATION FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s', (os.environ['DB_NAME'],))
        self.assertEqual(len(tables), 9)
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

    def test_free_registration_quota_serializes_competing_requests(self):
        from concurrent.futures import ThreadPoolExecutor
        from windows_agent import AgentError
        with self.module.state_connection() as state:
            state.execute('DELETE FROM plan_grants')
        database.execute('DELETE FROM devices WHERE user_sub=%s', ('1',))
        def create(index):
            try:
                self.module.plans.create_device(1,'Concurrent '+str(index),'AA:BB:CC:DD:EE:01')
                return 'created'
            except AgentError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(create,range(2)))
        self.assertCountEqual(results,['created','device_limit'])
        self.assertEqual(len(self.module.plans.devices(1)),1)


@unittest.skipUnless(os.environ.get('WOL_TEST_MARIADB') == '1', 'MariaDB aislada no habilitada.')
class MariaDBAgentTests(agents.AgentFlowTests):
    @classmethod
    def setUpClass(cls):
        settings = database.connection_settings()
        if not settings['database'].startswith('wol_test_') or settings['host'] not in ('127.0.0.1','localhost','::1'):
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
            for table in ('agent_presence','agent_commands','agent_actions','agent_apps','agent_connections','agent_pairings','audit_logs','devices','users'):
                db.execute('DELETE FROM '+table)
            db.execute('ALTER TABLE devices AUTO_INCREMENT=1')

    def test_agent_concurrent_dedupe_and_claim(self):
        from concurrent.futures import ThreadPoolExecutor
        self.pair()
        with ThreadPoolExecutor(max_workers=2) as pool:
            commands = list(pool.map(lambda _: self.command(dedupe='parallel'),range(2)))
        self.assertEqual(commands[0],commands[1])
        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = list(pool.map(lambda _: self.service.claim(self.agent)['command'],range(2)))
        self.assertEqual(sum(item is not None for item in claims),1)
