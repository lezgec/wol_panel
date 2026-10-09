"""Contrato de conexión PyMySQL y protección del instalador, sin conexiones reales."""
import os
import subprocess
import sys
import unittest
from unittest.mock import Mock, MagicMock, patch
import database


class DatabaseTests(unittest.TestCase):
    def test_parameterized_queries_and_transaction_close(self):
        conn = MagicMock()
        cursor = conn.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = ('saved',)
        with patch.object(database, 'get_db_connection', return_value=conn):
            self.assertEqual(database.fetch_one('SELECT email FROM users WHERE email=%s', ("a' OR 1=1",)), ('saved',))
        cursor.execute.assert_called_once_with('SELECT email FROM users WHERE email=%s', ("a' OR 1=1",))
        conn.commit.assert_called_once()
        conn.close.assert_called_once()
        conn.rollback.assert_not_called()

    def test_failed_transaction_rolls_back_and_closes(self):
        conn = Mock()
        with patch.object(database, 'get_db_connection', return_value=conn):
            with self.assertRaises(database.pymysql.IntegrityError):
                with database.connection():
                    raise database.pymysql.IntegrityError('test-only')
        conn.commit.assert_not_called()
        conn.rollback.assert_called_once()
        conn.close.assert_called_once()

    def test_connection_settings_utf8mb4_and_found_rows(self):
        with patch.dict(os.environ, {'DB_NAME': 'wol_panel', 'DB_USER': 'wol_user', 'DB_PORT': '3306'}):
            settings = database.connection_settings()
            self.assertEqual(settings['charset'], 'utf8mb4')
            self.assertFalse(settings['autocommit'])
            self.assertTrue(settings['client_flag'] & database.CLIENT.FOUND_ROWS)
            for key, invalid in [('DB_NAME', 'spamkill'), ('DB_NAME', 'colesterol_game_db'), ('DB_NAME', 'wol;DROP'), ('DB_USER', 'root'), ('DB_PORT', '0')]:
                with patch.dict(os.environ, {key: invalid}), self.assertRaises(ValueError):
                    database.connection_settings()

    def test_migration_import_has_no_flask_or_sqlite_side_effects(self):
        source = "import sys, migrate_db; assert 'app' not in sys.modules; assert 'sqlite3' not in sys.modules"
        subprocess.run([sys.executable, '-c', source], check=True, capture_output=True, timeout=10)

    def test_migration_refuses_an_unrelated_database(self):
        import migrate_db
        with patch.dict(os.environ, {'DB_NAME': 'unrelated_app', 'DB_USER': 'wol_user'}), patch.object(migrate_db, 'connection') as connect:
            with self.assertRaises(ValueError):
                migrate_db.migrate()
            connect.assert_not_called()
