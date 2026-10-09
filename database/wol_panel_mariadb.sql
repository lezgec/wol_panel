-- Ejecutar en wol_panel: no crea ni elimina bases o usuarios.
-- MariaDB 10.11+ (Ubuntu 24.04). Reejecutar preserva todas las filas.
CREATE TABLE IF NOT EXISTS users (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    email VARCHAR(150) NOT NULL,
    password VARCHAR(255) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    amazon_id VARCHAR(255) CHARACTER SET ascii COLLATE ascii_bin NULL,
    is_verified TINYINT UNSIGNED NOT NULL DEFAULT 0,
    verification_code VARCHAR(10) NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_users_email (email),
    UNIQUE KEY uq_users_amazon (amazon_id),
    CONSTRAINT chk_users_verified CHECK (is_verified IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS devices (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    name VARCHAR(100) NOT NULL,
    mac CHAR(17) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    user_sub INT UNSIGNED NOT NULL,
    wake_method VARCHAR(16) NOT NULL DEFAULT 'local',
    wake_host VARCHAR(253) NULL,
    wake_port SMALLINT UNSIGNED NOT NULL DEFAULT 9,
    PRIMARY KEY (id),
    KEY ix_devices_owner (user_sub, id),
    CONSTRAINT fk_devices_owner FOREIGN KEY (user_sub) REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT chk_devices_method CHECK (wake_method IN ('alexa', 'router', 'local')),
    CONSTRAINT chk_devices_port CHECK (wake_port BETWEEN 1 AND 65535),
    CONSTRAINT chk_devices_host CHECK (wake_method <> 'router' OR (wake_host IS NOT NULL AND CHAR_LENGTH(wake_host) > 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS audit_logs (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id INT UNSIGNED NULL,
    action VARCHAR(100) NOT NULL,
    details VARCHAR(255) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY ix_audit_user_created (user_id, created_at),
    CONSTRAINT fk_audit_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
