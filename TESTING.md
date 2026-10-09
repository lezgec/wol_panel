# Verificación reproducible

## Suite sin servidor de base de datos

```bash
python -m pip install -r requirements.txt
python -m unittest -v test_app test_database test_windows_agent
```

Pruebas de Flask, contrato PyMySQL, transacciones y aislamiento con SQLite de
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
python -m unittest -v test_app test_database test_windows_agent test_mariadb
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

Sin `WOL_TEST_MARIADB=1`, los casos MariaDB se marcan como omitidos y no se
intenta conexión. Un error de configuración con la opción habilitada falla la
suite, en lugar de ocultarse como omisión.

## Verificación del control Windows

La suite añade vinculación con código temporal, consumo único de credenciales,
CSRF, propietario, catálogo permitido, revocación, cola sin repetición, caducidad,
reportes, cancelación y comprobación final de autorización. La integración real
verifica además solicitudes simultáneas para que una orden tenga un único
consumidor. Las pruebas Custom cubren firma Lambda, ID de skill, intents y tareas
para rutinas. El SQL se aplica a una base vacía y se reejecuta sin borrar datos.

La suite completa de esta entrega contiene 232 comprobaciones Python (incluye
flujos compartidos ejecutados con SQLite y MariaDB 10.11.14). El agente separado
tiene 22 pruebas .NET y compilación Release sin advertencias. Su vista de
verificación comprueba DPAPI y dibuja la ventana sin usar credenciales reales ni
ejecutar órdenes. Nunca se apaga el PC durante las pruebas.

La prueba automatizada no confirma encendido físico, apertura de Spotify real,
apagado real, entrega SMTP ni vinculación/certificación en Amazon. La VM Azure
se actualiza manualmente y los Echo deben probarse después de configurar la skill.
