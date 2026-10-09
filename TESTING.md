# Verificación reproducible

## Suite sin servidor de base de datos

```bash
python -m pip install -r requirements.txt
python -m unittest -v test_app test_database
```

45 pruebas de Flask, contrato PyMySQL, transacciones y aislamiento con SQLite de
prueba. El doble PyMySQL devuelve un entero de `execute`, por lo que no oculta
el error habitual de encadenar `.fetchone()` a esa llamada. Los tests crean estado
temporal propio; no usan `instance` ni las tablas de una instalación real.

UDP, SMTP y HTTP de Amazon se simulan. Guardas adicionales bloquean llamadas de
red no simuladas desde las funciones de control. Solo la suite de integración
permite la conexión de PyMySQL a MariaDB en loopback.

## Integración con MariaDB 10.11+

**Utiliza una base nueva aislada cuyo nombre empiece por `wol_test_`.** Los tests
limpian sus tablas entre casos. No apuntes a `wol_panel`, `spamkill` ni
`colesterol_game_db`; la suite comprueba nombre/host antes de ejecutar DDL.
Ejecuta desde el checkout de desarrollo, sin cargar configuración de producción.

En un MariaDB de pruebas local, abre una sesión administrativa:

```bash
sudo env MYSQL_HISTFILE=/dev/null mariadb
```

Crea exclusivamente estos recursos temporales. Reemplaza la contraseña de ejemplo
por una privada local; no la subas a Git:

```sql
CREATE DATABASE wol_test_manual CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'wol_test_user'@'127.0.0.1' IDENTIFIED BY 'REEMPLAZAR_PASSWORD_DE_PRUEBA';
GRANT ALL PRIVILEGES ON wol_test_manual.* TO 'wol_test_user'@'127.0.0.1';
EXIT;
```

En Bash, evita colocar contraseñas en el historial:

```bash
export DB_HOST=127.0.0.1 DB_PORT=3306 DB_NAME=wol_test_manual DB_USER=wol_test_user
read -rsp 'Contraseña de prueba: ' DB_PASSWORD
export DB_PASSWORD
export WOL_TEST_MARIADB=1
python -m unittest -v test_app test_database test_mariadb
unset DB_PASSWORD WOL_TEST_MARIADB
```

La aplicación se prueba con usuario no root. El instalador crea tablas y luego
se reejecuta verificando que equipos/cuentas continúen presentes. Se verifican
InnoDB, utf8mb4, clave foránea del propietario y unicidad del correo, además de
las mismas rutas y operaciones OAuth/Alexa. Un subproceso nuevo importa Flask,
lee el SQLite conservado y renueva un token emitido antes del reinicio.

Al terminar, elimina **solo** los recursos de prueba nombrados aquí, en el cliente
administrativo; nunca reutilices estos comandos con nombres de producción:

```sql
DROP DATABASE wol_test_manual;
DROP USER 'wol_test_user'@'127.0.0.1';
```

Sin `WOL_TEST_MARIADB=1`, los 42 casos MariaDB se marcan como omitidos y no se
intenta conexión. Un error de configuración con la opción habilitada falla la
suite, en lugar de ocultarse como omisión.

## Resultado de esta entrega

87 pruebas: 40 de aplicación sin MariaDB, 5 de contrato/instalador y 42 de aplicación
con MariaDB 10.11.14 real en Windows x64/Python 3.13. La instancia portátil se
preparó en una carpeta temporal, escuchando únicamente en loopback con puerto
separado; cada ejecución creó/eliminó su propia base `wol_test_codex_*`. No se
usó la VM Azure ni las bases de otras aplicaciones.

Quedan para Ubuntu: `systemd-analyze verify`, `nginx -t`, los certificados existentes,
DNS y comportamiento Cloudflare, consumo combinado de RAM, entrega SMTP real,
vinculación/certificación Amazon y encendido físico. Las órdenes de Echo se prueban
con respuestas simuladas del gateway; el éxito automático no demuestra arranque.
