-- Agente Windows: tablas nuevas; no altera cuentas ni dispositivos existentes.
CREATE TABLE IF NOT EXISTS agent_pairings (
    device_code_hash CHAR(64) CHARACTER SET ascii NOT NULL PRIMARY KEY,
    user_code_hash CHAR(64) CHARACTER SET ascii NOT NULL UNIQUE,
    computer_name VARCHAR(100) NOT NULL,
    expires BIGINT NOT NULL,
    user_id INT UNSIGNED NULL,
    device_id INT UNSIGNED NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'pending'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS agent_connections (
    id CHAR(36) CHARACTER SET ascii NOT NULL PRIMARY KEY,
    user_id INT UNSIGNED NOT NULL,
    device_id INT UNSIGNED NOT NULL UNIQUE,
    token_hash CHAR(64) CHARACTER SET ascii NOT NULL UNIQUE,
    expires BIGINT NOT NULL,
    last_seen BIGINT NOT NULL DEFAULT 0,
    allow_shutdown TINYINT NOT NULL DEFAULT 0,
    revoked TINYINT NOT NULL DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS agent_apps (
    agent_id CHAR(36) CHARACTER SET ascii NOT NULL,
    app_key CHAR(36) CHARACTER SET ascii NOT NULL,
    name VARCHAR(100) NOT NULL,
    PRIMARY KEY (agent_id, app_key),
    FOREIGN KEY (agent_id) REFERENCES agent_connections(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS agent_actions (
    id CHAR(36) CHARACTER SET ascii NOT NULL PRIMARY KEY,
    user_id INT UNSIGNED NOT NULL,
    agent_id CHAR(36) CHARACTER SET ascii NOT NULL,
    name VARCHAR(100) NOT NULL,
    kind VARCHAR(16) NOT NULL,
    app_key CHAR(36) CHARACTER SET ascii NULL,
    UNIQUE KEY uq_agent_action_name (user_id, name),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (agent_id) REFERENCES agent_connections(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS agent_commands (
    id CHAR(36) CHARACTER SET ascii NOT NULL PRIMARY KEY,
    user_id INT UNSIGNED NOT NULL,
    agent_id CHAR(36) CHARACTER SET ascii NOT NULL,
    kind VARCHAR(16) NOT NULL,
    app_key CHAR(36) CHARACTER SET ascii NULL,
    created BIGINT NOT NULL,
    expires BIGINT NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    result VARCHAR(40) NULL,
    claim_hash CHAR(64) CHARACTER SET ascii NULL,
    cancel_requested TINYINT NOT NULL DEFAULT 0,
    dedupe_hash CHAR(64) CHARACTER SET ascii NOT NULL UNIQUE,
    KEY ix_agent_pending (agent_id, status, created),
    KEY ix_agent_owner_history (user_id, created),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (agent_id) REFERENCES agent_connections(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
