"""Añade destinos de encendido conservando los equipos existentes."""
from app import get_db_connection


def migrate():
    conn = get_db_connection()
    try:
        conn.cursor().execute("""
            IF OBJECT_ID('dbo.users', 'U') IS NULL
            CREATE TABLE dbo.users (
                id int IDENTITY(1,1) PRIMARY KEY,
                email nvarchar(150) NOT NULL UNIQUE,
                password varchar(255) NOT NULL,
                created_at datetime NOT NULL DEFAULT GETUTCDATE(),
                amazon_id varchar(255) NULL,
                is_verified bit NOT NULL DEFAULT 0,
                verification_code varchar(10) NULL
            );
            IF OBJECT_ID('dbo.devices', 'U') IS NULL
            CREATE TABLE dbo.devices (
                id int IDENTITY(1,1) PRIMARY KEY,
                name nvarchar(100) NOT NULL,
                mac varchar(50) NOT NULL,
                user_sub varchar(255) NOT NULL
            );
            IF OBJECT_ID('dbo.audit_logs', 'U') IS NULL
            CREATE TABLE dbo.audit_logs (
                id int IDENTITY(1,1) PRIMARY KEY,
                user_id int NULL,
                action varchar(100) NULL,
                details nvarchar(255) NULL,
                created_at datetime NOT NULL DEFAULT GETUTCDATE()
            );
        """)
        for name, definition in (
            ('wake_method', "varchar(16) NOT NULL CONSTRAINT DF_devices_wake_method DEFAULT 'local'"),
            ('wake_host', 'varchar(253) NULL'),
            ('wake_port', 'int NOT NULL CONSTRAINT DF_devices_wake_port DEFAULT 9'),
        ):
            conn.cursor().execute(f"IF COL_LENGTH('devices', '{name}') IS NULL ALTER TABLE devices ADD {name} {definition}")
        conn.commit()
        print('Esquema y migración de destinos WoL completados.')
    finally:
        conn.close()


if __name__ == '__main__':
    migrate()
